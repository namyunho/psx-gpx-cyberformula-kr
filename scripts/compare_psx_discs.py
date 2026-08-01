#!/usr/bin/env python3
"""Compare two verified game discs while separating content from raw-sector position.

Raw CD sectors contain absolute MSF addresses and EDC/ECC, so bytewise Track 1
comparison reports false content differences when ISO extents move.  This tool
hashes each ISO extent's sector form, XA subheader, and complete user payload,
then compares the boot-EXE schedules and their units independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.original_media import (
        file_hashes,
        load_manifest,
        read_cue_files,
        resolved_paths,
        verify_cue,
        verify_track,
    )
    from scripts.psx_disc import PsxDisc
    from scripts.psx_layout import build_inventory
except ModuleNotFoundError:  # Direct execution from the repository root.
    from original_media import (
        file_hashes,
        load_manifest,
        read_cue_files,
        resolved_paths,
        verify_cue,
        verify_track,
    )
    from psx_disc import PsxDisc
    from psx_layout import build_inventory


SYNC = bytes.fromhex("00FFFFFFFFFFFFFFFFFFFF00")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_sector_content(sector: bytes) -> bytes:
    """Return content bytes without absolute MSF or regenerable EDC/ECC."""

    if len(sector) != 2352 or sector[:12] != SYNC:
        raise ValueError("invalid raw CD sector")
    mode = sector[15]
    if mode == 1:
        return b"M1" + sector[16:2064]
    if mode != 2:
        raise ValueError(f"unsupported sector mode: {mode}")
    if sector[16:20] != sector[20:24]:
        raise ValueError("Mode 2 duplicated subheader mismatch")
    form2 = bool(sector[18] & 0x20)
    payload_size = 2324 if form2 else 2048
    tag = b"M2F2" if form2 else b"M2F1"
    return tag + sector[16:20] + sector[24 : 24 + payload_size]


def normalized_extent_hash(
    disc: PsxDisc,
    *,
    lba: int,
    logical_size: int,
) -> str:
    block_count = (logical_size + 2047) // 2048
    digest = hashlib.sha256()
    for index in range(block_count):
        digest.update(normalized_sector_content(disc.read_raw_sector(lba + index)))
    return digest.hexdigest()


def byte_differences(left: bytes, right: bytes) -> list[dict[str, Any]]:
    if len(left) != len(right):
        raise ValueError("byte difference listing requires equal-sized inputs")
    return [
        {"offset": offset, "offset_hex": f"0x{offset:X}", "left": a, "right": b}
        for offset, (a, b) in enumerate(zip(left, right, strict=True))
        if a != b
    ]


def cue_track_reports(cue: Path) -> list[dict[str, Any]]:
    return [
        {"track": index, "filename": name, **file_hashes(cue.parent / name)}
        for index, name in enumerate(read_cue_files(cue), start=1)
    ]


def paired_roles(
    left_entries: dict[str, Any],
    right_entries: dict[str, Any],
    *,
    left_boot: str,
    right_boot: str,
) -> Iterable[tuple[str, Any, Any]]:
    left_by_role = {
        ("BOOT_EXE" if name == left_boot.upper() else name): entry
        for name, entry in left_entries.items()
    }
    right_by_role = {
        ("BOOT_EXE" if name == right_boot.upper() else name): entry
        for name, entry in right_entries.items()
    }
    if left_by_role.keys() != right_by_role.keys():
        raise ValueError(
            "ISO root roles differ: "
            f"left-only={sorted(left_by_role.keys() - right_by_role.keys())}, "
            f"right-only={sorted(right_by_role.keys() - left_by_role.keys())}"
        )
    for role in sorted(left_by_role):
        yield role, left_by_role[role], right_by_role[role]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", default="disc1")
    parser.add_argument("--right", default="disc2")
    parser.add_argument("--left-root", type=Path)
    parser.add_argument("--right-root", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("work/analysis/disc1-disc2-comparison.json"),
    )
    args = parser.parse_args()

    manifest = load_manifest()
    paths = resolved_paths(manifest)
    left_key = args.left.lower()
    right_key = args.right.lower()
    for key in (left_key, right_key):
        if key not in manifest:
            parser.error(f"unsupported disc key: {key}")
    left_manifest = manifest[left_key]
    right_manifest = manifest[right_key]
    left_root = args.left_root or Path("work") / left_key / "full"
    right_root = args.right_root or Path("work") / right_key / "full"
    left_track = paths[f"{left_key}_track1"]
    right_track = paths[f"{right_key}_track1"]
    left_cue = paths[f"{left_key}_cue"]
    right_cue = paths[f"{right_key}_cue"]

    sources = {
        left_key: {
            "track1": verify_track(
                left_track,
                left_manifest["data_track"],
                label=f"{left_key} data track",
            ),
            "cue": verify_cue(left_cue, left_manifest["expected_tracks"]),
        },
        right_key: {
            "track1": verify_track(
                right_track,
                right_manifest["data_track"],
                label=f"{right_key} data track",
            ),
            "cue": verify_cue(right_cue, right_manifest["expected_tracks"]),
        },
    }

    file_reports = []
    with PsxDisc(left_track) as left_disc, PsxDisc(right_track) as right_disc:
        left_entries = {
            entry.name.upper(): entry
            for entry in left_disc.root_entries()
            if not entry.is_directory
        }
        right_entries = {
            entry.name.upper(): entry
            for entry in right_disc.root_entries()
            if not entry.is_directory
        }
        for role, left_entry, right_entry in paired_roles(
            left_entries,
            right_entries,
            left_boot=left_manifest["boot_exe"],
            right_boot=right_manifest["boot_exe"],
        ):
            external = (
                left_entry.lba >= left_disc.sector_count
                or right_entry.lba >= right_disc.sector_count
            )
            item: dict[str, Any] = {
                "role": role,
                "left_name": left_entry.name,
                "right_name": right_entry.name,
                "left_lba": left_entry.lba,
                "right_lba": right_entry.lba,
                "lba_delta": right_entry.lba - left_entry.lba,
                "left_size": left_entry.size,
                "right_size": right_entry.size,
                "external_cdda_reference": external,
            }
            if not external:
                left_logical = left_disc.read_extent(left_entry.lba, left_entry.size)
                right_logical = right_disc.read_extent(
                    right_entry.lba, right_entry.size
                )
                left_normalized = normalized_extent_hash(
                    left_disc, lba=left_entry.lba, logical_size=left_entry.size
                )
                right_normalized = normalized_extent_hash(
                    right_disc, lba=right_entry.lba, logical_size=right_entry.size
                )
                item.update(
                    {
                        "logical_sha256_left": sha256_bytes(left_logical),
                        "logical_sha256_right": sha256_bytes(right_logical),
                        "logical_equal": left_logical == right_logical,
                        "normalized_sector_content_sha256_left": left_normalized,
                        "normalized_sector_content_sha256_right": right_normalized,
                        "normalized_sector_content_equal": (
                            left_normalized == right_normalized
                        ),
                    }
                )
            file_reports.append(item)

    left_layout = build_inventory(
        left_root / left_manifest["boot_exe"], left_root
    )
    right_layout = build_inventory(
        right_root / right_manifest["boot_exe"], right_root
    )
    schedule_reports = []
    changed_units = []
    for filename in sorted(left_layout["schedules"]):
        left_schedule = left_layout["schedules"][filename]
        right_schedule = right_layout["schedules"][filename]
        left_units = left_schedule["inventory"]["units"]
        right_units = right_schedule["inventory"]["units"]
        differing = [
            left_unit["index"]
            for left_unit, right_unit in zip(left_units, right_units, strict=True)
            if left_unit["sha256"] != right_unit["sha256"]
        ]
        schedule_reports.append(
            {
                "filename": filename,
                "entry_count": left_schedule["entry_count"],
                "partition_equal": left_schedule["entries"] == right_schedule["entries"],
                "different_unit_indices": differing,
            }
        )
        changed_units.extend(
            {"filename": filename, "unit_index": index} for index in differing
        )

    start_left = (left_root / "START.BIN").read_bytes()
    start_right = (right_root / "START.BIN").read_bytes()
    start_differences = byte_differences(start_left, start_right)
    start_entries = left_layout["schedules"]["START.BIN"]["entries"]
    for difference in start_differences:
        offset = difference["offset"]
        unit = next(
            entry
            for entry in start_entries
            if entry["byte_offset"] <= offset < entry["byte_end"]
        )
        difference["unit_index"] = unit["index"]
        difference["unit_offset"] = offset - unit["byte_offset"]
        difference["unit_offset_hex"] = f"0x{difference['unit_offset']:X}"

    left_cue_tracks = cue_track_reports(left_cue)
    right_cue_tracks = cue_track_reports(right_cue)
    cue_track_comparison = [
        {
            "track": left["track"],
            "left_filename": left["filename"],
            "right_filename": right["filename"],
            "size_equal": left["size"] == right["size"],
            "sha256_equal": left["sha256"] == right["sha256"],
            "sha256_left": left["sha256"],
            "sha256_right": right["sha256"],
        }
        for left, right in zip(left_cue_tracks, right_cue_tracks, strict=True)
    ]

    report = {
        "schema_version": 1,
        "left": left_key,
        "right": right_key,
        "sources": sources,
        "summary": {
            "iso_role_count": len(file_reports),
            "on_track_iso_role_count": sum(
                not item["external_cdda_reference"] for item in file_reports
            ),
            "logical_different_roles": [
                item["role"]
                for item in file_reports
                if not item["external_cdda_reference"] and not item["logical_equal"]
            ],
            "normalized_content_different_roles": [
                item["role"]
                for item in file_reports
                if not item["external_cdda_reference"]
                and not item["normalized_sector_content_equal"]
            ],
            "schedule_count": len(schedule_reports),
            "scheduled_unit_count": sum(
                item["entry_count"] for item in schedule_reports
            ),
            "changed_scheduled_units": changed_units,
            "start_changed_byte_count": len(start_differences),
            "cdda_tracks_2_to_4_equal": all(
                item["sha256_equal"] for item in cue_track_comparison[1:]
            ),
        },
        "iso_files": file_reports,
        "schedules": schedule_reports,
        "start_byte_differences": start_differences,
        "cue_tracks": cue_track_comparison,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
