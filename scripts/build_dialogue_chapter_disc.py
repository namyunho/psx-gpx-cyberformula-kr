#!/usr/bin/env python3
"""Insert a verified partial chapter build into the original Disc 1 track."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable

try:
    from scripts.build_dialogue_chapter_patch import (
        changed_ranges,
        verify_expected_writes,
    )
    from scripts.original_media import (
        DEFAULT_MANIFEST,
        file_hashes,
        load_manifest,
        read_cue_text,
        resolved_paths,
        verify_cue,
        verify_track,
    )
    from scripts.psx_disc import PsxDisc
    from scripts.psx_sector import (
        EDC_OFFSET,
        RAW_SECTOR_SIZE,
        USER_DATA_OFFSET,
        USER_DATA_SIZE,
        inspect_mode2_form1,
        rebuild_mode2_form1,
    )
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import (
        changed_ranges,
        verify_expected_writes,
    )
    from original_media import (
        DEFAULT_MANIFEST,
        file_hashes,
        load_manifest,
        read_cue_text,
        resolved_paths,
        verify_cue,
        verify_track,
    )
    from psx_disc import PsxDisc
    from psx_sector import (
        EDC_OFFSET,
        RAW_SECTOR_SIZE,
        USER_DATA_OFFSET,
        USER_DATA_SIZE,
        inspect_mode2_form1,
        rebuild_mode2_form1,
    )


OUTPUT_TRACK_NAME = "disc1-chapter01-nonrelease-track1.bin"
OUTPUT_CUE_NAME = "disc1-chapter01-nonrelease.cue"


@dataclass(frozen=True)
class SectorMutation:
    owner: str
    file_offset: int
    payload_offset: int
    expected: bytes
    replacement: bytes


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def plan_file_mutations(
    *,
    owner: str,
    file_lba: int,
    source: bytes,
    replacement: bytes,
) -> dict[int, list[SectorMutation]]:
    if len(source) != len(replacement):
        raise ValueError(f"{owner}: replacement must preserve ISO file size")
    planned: dict[int, list[SectorMutation]] = defaultdict(list)
    for start, end in changed_ranges(source, replacement):
        position = start
        while position < end:
            lba = file_lba + position // USER_DATA_SIZE
            payload_offset = position % USER_DATA_SIZE
            length = min(end - position, USER_DATA_SIZE - payload_offset)
            planned[lba].append(
                SectorMutation(
                    owner=owner,
                    file_offset=position,
                    payload_offset=payload_offset,
                    expected=source[position : position + length],
                    replacement=replacement[position : position + length],
                )
            )
            position += length
    return dict(planned)


def merge_sector_plans(
    plans: Iterable[dict[int, list[SectorMutation]]],
) -> dict[int, list[SectorMutation]]:
    merged: dict[int, list[SectorMutation]] = defaultdict(list)
    for plan in plans:
        for lba, mutations in plan.items():
            merged[lba].extend(mutations)
    return {
        lba: sorted(mutations, key=lambda item: item.payload_offset)
        for lba, mutations in sorted(merged.items())
    }


def apply_sector_mutations(
    original: bytes,
    mutations: list[SectorMutation],
) -> tuple[bytes, dict[str, Any]]:
    source_integrity = inspect_mode2_form1(original)
    if not source_integrity.valid:
        raise ValueError("source MODE2/Form1 sector has invalid EDC/ECC")
    address_mode = source_integrity.ecc_address_mode
    if address_mode == "zero-or-sector":
        address_mode = "zero"
    if address_mode not in {"zero", "sector"}:
        raise ValueError(f"unsupported source ECC address mode: {address_mode}")

    working = bytearray(original)
    previous_end = -1
    for mutation in mutations:
        start = mutation.payload_offset
        end = start + len(mutation.expected)
        if start < previous_end:
            raise ValueError("overlapping raw-sector payload mutations")
        if len(mutation.expected) != len(mutation.replacement):
            raise ValueError("sector mutation must preserve length")
        raw_start = USER_DATA_OFFSET + start
        raw_end = USER_DATA_OFFSET + end
        if working[raw_start:raw_end] != mutation.expected:
            raise ValueError(
                f"{mutation.owner}: source payload differs at "
                f"file offset 0x{mutation.file_offset:X}"
            )
        working[raw_start:raw_end] = mutation.replacement
        previous_end = end

    rebuilt = rebuild_mode2_form1(working, address_mode=address_mode)
    output_integrity = inspect_mode2_form1(rebuilt)
    if not output_integrity.valid:
        raise ValueError("rebuilt MODE2/Form1 sector failed EDC/ECC validation")

    expected_write = verify_expected_writes(
        original,
        rebuilt,
        allowed_ranges=[
            *[
                (
                    USER_DATA_OFFSET + mutation.payload_offset,
                    USER_DATA_OFFSET
                    + mutation.payload_offset
                    + len(mutation.replacement),
                )
                for mutation in mutations
            ],
            (EDC_OFFSET, RAW_SECTOR_SIZE),
        ],
        owner="raw-sector-payload-and-integrity",
    )
    return rebuilt, {
        "ecc_address_mode": address_mode,
        "source_integrity": asdict(source_integrity),
        "output_integrity": asdict(output_integrity),
        "payload_write_count": len(mutations),
        "payload_changed_byte_count": sum(
            len(mutation.replacement) for mutation in mutations
        ),
        "expected_write": expected_write,
    }


def compact_integer_ranges(values: Iterable[int]) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    for value in sorted(set(values)):
        if result and value == result[-1]["end_inclusive"] + 1:
            result[-1]["end_inclusive"] = value
            result[-1]["count"] += 1
        else:
            result.append(
                {
                    "start": value,
                    "end_inclusive": value,
                    "count": 1,
                }
            )
    return result


def compare_raw_tracks(
    source_path: Path,
    output_path: Path,
) -> set[int]:
    if source_path.stat().st_size != output_path.stat().st_size:
        raise ValueError("raw Track 1 output size differs from source")
    changed: set[int] = set()
    sectors_per_chunk = 4096
    chunk_size = RAW_SECTOR_SIZE * sectors_per_chunk
    lba_base = 0
    with source_path.open("rb") as source, output_path.open("rb") as output:
        while True:
            source_chunk = source.read(chunk_size)
            output_chunk = output.read(chunk_size)
            if source_chunk != output_chunk:
                sector_count = len(source_chunk) // RAW_SECTOR_SIZE
                for index in range(sector_count):
                    begin = index * RAW_SECTOR_SIZE
                    end = begin + RAW_SECTOR_SIZE
                    if source_chunk[begin:end] != output_chunk[begin:end]:
                        changed.add(lba_base + index)
            if not source_chunk:
                break
            if len(source_chunk) != len(output_chunk):
                raise ValueError("raw Track 1 comparison encountered short output")
            lba_base += len(source_chunk) // RAW_SECTOR_SIZE
    return changed


def write_local_cue(
    source_cue: Path,
    *,
    output_track: Path,
    output_cue: Path,
) -> None:
    pattern = re.compile(
        r'^(\s*FILE\s+)(?:"([^"]+)"|(\S+))(\s+\S+.*)$',
        re.IGNORECASE,
    )
    file_index = 0
    rewritten: list[str] = []
    for line in read_cue_text(source_cue).splitlines():
        match = pattern.match(line)
        if not match:
            rewritten.append(line)
            continue
        file_index += 1
        if file_index == 1:
            target = output_track
        else:
            source_name = match.group(2) or match.group(3)
            target = (source_cue.parent / source_name).resolve()
        relative = Path(
            os.path.relpath(target.resolve(), output_cue.parent.resolve())
        )
        rewritten.append(
            f'{match.group(1)}"{relative.as_posix()}"{match.group(4)}'
        )
    if file_index == 0:
        raise ValueError("source CUE contains no FILE records")
    output_cue.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def build_disc(
    *,
    file_build_dir: Path,
    output_dir: Path,
    original_media_manifest: Path,
) -> dict[str, Any]:
    media = load_manifest(original_media_manifest)
    paths = resolved_paths(media)
    source_track = paths["disc1_track1"]
    source_cue = paths["disc1_cue"]
    track_verification = verify_track(
        source_track,
        media["disc1"]["data_track"],
    )
    cue_verification = verify_cue(
        source_cue,
        media["disc1"]["expected_tracks"],
    )

    file_manifest_path = file_build_dir / "manifest.json"
    file_manifest = load_object(file_manifest_path)
    selected_units = file_manifest.get("selected_story_units")
    if selected_units not in ([0], [0, 21]):
        raise ValueError(
            "chapter 1 disc builder requires selected_story_units == [0] "
            "or [0, 21]"
        )
    accepted_file_statuses = {
        "nonrelease-partial-chapter-build",
        "nonrelease-fixed-original-offset-overflow-diagnostic",
    }
    if file_manifest.get("status") not in accepted_file_statuses:
        raise ValueError("unexpected partial file-build status")

    replacements = {
        name: (file_build_dir / name).read_bytes()
        for name in ("START.BIN", "ALLBIN.BIN")
    }
    for name, replacement in replacements.items():
        expected_hash = file_manifest["outputs"][name]["sha256"]
        if hashlib.sha256(replacement).hexdigest() != expected_hash:
            raise ValueError(f"{name}: file-build output hash differs")

    with PsxDisc(source_track) as disc:
        entries = {
            entry.name.upper(): entry
            for entry in disc.root_entries()
            if not entry.is_directory
        }
        sources: dict[str, bytes] = {}
        plans: list[dict[int, list[SectorMutation]]] = []
        file_reports: dict[str, Any] = {}
        for name, replacement in replacements.items():
            entry = entries.get(name)
            if entry is None:
                raise ValueError(f"ISO root has no {name}")
            source = disc.read_extent(entry.lba, entry.size)
            if len(source) != len(replacement):
                raise ValueError(f"{name}: ISO extent size differs")
            expected_source_hash = file_manifest["sources"][name]["sha256"]
            if hashlib.sha256(source).hexdigest() != expected_source_hash:
                raise ValueError(f"{name}: ISO source hash differs")
            sources[name] = source
            file_plan = plan_file_mutations(
                owner=name,
                file_lba=entry.lba,
                source=source,
                replacement=replacement,
            )
            plans.append(file_plan)
            file_reports[name] = {
                "lba": entry.lba,
                "size": entry.size,
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "replacement_sha256": hashlib.sha256(
                    replacement
                ).hexdigest(),
                "changed_file_byte_count": sum(
                    end - start
                    for start, end in changed_ranges(source, replacement)
                ),
                "changed_file_range_count": len(
                    changed_ranges(source, replacement)
                ),
                "changed_sector_count": len(file_plan),
                "changed_sector_ranges": compact_integer_ranges(file_plan),
            }
        sector_plan = merge_sector_plans(plans)
        rebuilt_sectors: dict[int, bytes] = {}
        sector_reports: dict[str, Any] = {}
        for lba, mutations in sector_plan.items():
            rebuilt, sector_report = apply_sector_mutations(
                disc.read_raw_sector(lba),
                mutations,
            )
            rebuilt_sectors[lba] = rebuilt
            sector_reports[str(lba)] = {
                **sector_report,
                "mutations": [
                    {
                        "owner": mutation.owner,
                        "file_offset": f"0x{mutation.file_offset:X}",
                        "payload_offset": f"0x{mutation.payload_offset:X}",
                        "bytes": len(mutation.replacement),
                    }
                    for mutation in mutations
                ],
            }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_track = output_dir / OUTPUT_TRACK_NAME
    output_cue = output_dir / OUTPUT_CUE_NAME
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{OUTPUT_TRACK_NAME}.",
            suffix=".tmp",
            dir=output_dir,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        shutil.copyfile(source_track, temporary_path)
        with temporary_path.open("r+b") as output:
            for lba, sector in rebuilt_sectors.items():
                output.seek(lba * RAW_SECTOR_SIZE)
                output.write(sector)
        temporary_path.replace(output_track)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    actual_changed_sectors = compare_raw_tracks(source_track, output_track)
    planned_changed_sectors = set(sector_plan)
    if actual_changed_sectors != planned_changed_sectors:
        raise ValueError(
            "raw Track 1 changed-sector set differs from Expected Writes"
        )

    with PsxDisc(output_track) as disc:
        output_entries = {
            entry.name.upper(): entry
            for entry in disc.root_entries()
            if not entry.is_directory
        }
        for name, replacement in replacements.items():
            entry = output_entries[name]
            if disc.read_extent(entry.lba, entry.size) != replacement:
                raise ValueError(f"{name}: output ISO extraction differs")
        for lba, expected_sector in rebuilt_sectors.items():
            if disc.read_raw_sector(lba) != expected_sector:
                raise ValueError(f"LBA {lba}: output raw sector differs")
            if not inspect_mode2_form1(expected_sector).valid:
                raise ValueError(f"LBA {lba}: output EDC/ECC is invalid")

    write_local_cue(
        source_cue,
        output_track=output_track,
        output_cue=output_cue,
    )
    manifest = {
        "schema_version": 1,
        "status": (
            "nonrelease-fixed-original-offset-overflow-runtime-diagnostic"
            if file_manifest.get("status")
            == "nonrelease-fixed-original-offset-overflow-diagnostic"
            else "nonrelease-chapter01-runtime-validation-required"
        ),
        "chapter": {
            "human_label": (
                "chapter-01-plus-general-race-u21"
                if selected_units == [0, 21]
                else "chapter-01"
            ),
            "selected_units": selected_units,
            "entry_count": file_manifest["selected_entry_count"],
        },
        "warning": (
            "The global primary font is replaced for the full candidate "
            f"corpus, but only units {selected_units} are re-encoded. Do not "
            "enter other dialogue units with this partial build."
        ),
        "sources": {
            "original_media_manifest": str(
                original_media_manifest.resolve()
            ),
            "track1": track_verification,
            "cue": cue_verification,
            "file_build_manifest": {
                "path": str(file_manifest_path.resolve()),
                "sha256": sha256_file(file_manifest_path),
            },
        },
        "iso_files": file_reports,
        "raw_expected_writes": {
            "sector_size": RAW_SECTOR_SIZE,
            "changed_sector_count": len(sector_plan),
            "changed_sector_ranges": compact_integer_ranges(sector_plan),
            "actual_changed_sector_set_matches_plan": True,
            "all_changed_source_sectors_integrity_valid": all(
                report["source_integrity"]["edc_valid"]
                and (
                    report["source_integrity"][
                        "zero_address_ecc_valid"
                    ]
                    or report["source_integrity"][
                        "sector_address_ecc_valid"
                    ]
                )
                for report in sector_reports.values()
            ),
            "all_changed_output_sectors_integrity_valid": all(
                report["output_integrity"]["edc_valid"]
                and (
                    report["output_integrity"][
                        "zero_address_ecc_valid"
                    ]
                    or report["output_integrity"][
                        "sector_address_ecc_valid"
                    ]
                )
                for report in sector_reports.values()
            ),
            "sectors": sector_reports,
        },
        "outputs": {
            "track1": {
                "path": str(output_track.resolve()),
                **file_hashes(output_track),
            },
            "cue": {
                "path": str(output_cue.resolve()),
                "sha256": sha256_file(output_cue),
            },
            "START.BIN": {
                "sha256": hashlib.sha256(
                    replacements["START.BIN"]
                ).hexdigest(),
                "verified_by_reextraction": True,
            },
            "ALLBIN.BIN": {
                "sha256": hashlib.sha256(
                    replacements["ALLBIN.BIN"]
                ).hexdigest(),
                "verified_by_reextraction": True,
            },
        },
        "runtime_validation": {
            "status": "not-run-user-gui-required",
            "required": [
                "boot the generated CUE",
                "enter chapter 1",
                "confirm Korean glyph palette/outline/shadow",
                (
                    "observe fixed-address overlap boundaries; this diagnostic "
                    "is not expected to advance through every entry"
                    if file_manifest.get("status")
                    == "nonrelease-fixed-original-offset-overflow-diagnostic"
                    else "confirm selected dialogue entries render and advance"
                ),
                (
                    "continue to general-race unit 21 and inspect its first "
                    "overlap boundary"
                    if 21 in selected_units
                    else "do not continue into an unselected dialogue unit"
                ),
            ],
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-build-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--original-media-manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    args = parser.parse_args()
    manifest = build_disc(
        file_build_dir=args.file_build_dir,
        output_dir=args.output_dir,
        original_media_manifest=args.original_media_manifest,
    )
    print(
        f"chapter=1 units={manifest['chapter']['selected_units']} "
        f"entries={manifest['chapter']['entry_count']} "
        f"changed_sectors="
        f"{manifest['raw_expected_writes']['changed_sector_count']} "
        f"track={manifest['outputs']['track1']['path']} "
        f"cue={manifest['outputs']['cue']['path']}"
    )


if __name__ == "__main__":
    main()
