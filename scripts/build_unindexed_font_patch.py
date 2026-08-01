#!/usr/bin/env python3
"""Inject reviewed u38 mini-game continuations and u39 save-system text."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from pathlib import Path
import struct
from typing import Any

try:
    from scripts.build_character_name_patch import load_built_primary_mapping
    from scripts.build_dialogue_chapter_patch import (
        EXPECTED_ALLBIN_SHA256,
        EXPECTED_START_SHA256,
        verify_expected_writes,
    )
    from scripts.build_special_screen_patch import (
        encode_special_entry,
        extend_primary_font,
        load_object,
        sha256_bytes,
        sha256_file,
        special_required_characters,
        validate_special_screen_artifacts,
        write_json,
    )
    from scripts.unindexed_font_common import (
        encode_unindexed_entry,
        validate_unindexed_artifacts,
    )
except ModuleNotFoundError:
    from build_character_name_patch import load_built_primary_mapping
    from build_dialogue_chapter_patch import (
        EXPECTED_ALLBIN_SHA256,
        EXPECTED_START_SHA256,
        verify_expected_writes,
    )
    from build_special_screen_patch import (
        encode_special_entry,
        extend_primary_font,
        load_object,
        sha256_bytes,
        sha256_file,
        special_required_characters,
        validate_special_screen_artifacts,
        write_json,
    )
    from unindexed_font_common import (
        encode_unindexed_entry,
        validate_unindexed_artifacts,
    )


EXPECTED_SELECTED_COUNTS = {38: 73, 39: 27}


def _entry_start(entry: dict[str, Any]) -> int:
    return int(entry["source"]["file_offset"], 16)


def _source_raw(entry: dict[str, Any]) -> bytes:
    return bytes.fromhex(entry["original"]["raw_hex"])


def _special_translation_map(document: dict[str, Any]) -> dict[str, str]:
    translations = document.get("translations")
    if not isinstance(translations, list):
        raise ValueError("special-screen translations must be an array")
    result = {
        str(item["id"]): str(item["ko"])
        for item in translations
    }
    if len(result) != len(translations):
        raise ValueError("special-screen translation IDs are duplicated")
    return result


def _pack_u38_continuations(
    *,
    patched_allbin: bytearray,
    input_allbin: bytes,
    source_allbin: bytes,
    additional_entries: list[dict[str, Any]],
    additional_translation_by_id: dict[str, dict[str, Any]],
    special_entries: list[dict[str, Any]],
    special_translation_by_id: dict[str, str],
    mapping: dict[str, int],
) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    special_entries = sorted(special_entries, key=_entry_start)
    additional_entries = sorted(additional_entries, key=_entry_start)
    reports: list[dict[str, Any]] = []
    allowed: list[tuple[int, int]] = []
    covered: set[str] = set()

    for index, special in enumerate(special_entries):
        segment_start = _entry_start(special)
        special_source_end = segment_start + len(_source_raw(special))
        segment_end = (
            _entry_start(special_entries[index + 1])
            if index + 1 < len(special_entries)
            else special_source_end
        )
        continuations = [
            entry
            for entry in additional_entries
            if special_source_end <= _entry_start(entry) < segment_end
        ]
        if not continuations:
            continue
        if _entry_start(continuations[0]) != special_source_end:
            raise ValueError(
                f"{special['entry_id']}: continuation does not start "
                "immediately after its indexed page"
            )
        for left, right in zip(continuations, continuations[1:]):
            if _entry_start(left) + len(_source_raw(left)) != _entry_start(
                right
            ):
                raise ValueError(
                    f"{right['entry_id']}: continuation run is not contiguous"
                )

        source_special = _source_raw(special)
        source_special_offset = _entry_start(special)
        source_replacement, special_report = encode_special_entry(
            special,
            special_translation_by_id[special["entry_id"]],
            mapping,
        )
        encoded_special = source_replacement[
            : int(special_report["encoded_stream_bytes"])
        ]
        if (
            input_allbin[
                source_special_offset :
                source_special_offset + len(source_replacement)
            ]
            != source_replacement
        ):
            raise ValueError(
                f"{special['entry_id']}: base special-screen bytes differ"
            )
        if (
            source_allbin[
                source_special_offset :
                source_special_offset + len(source_special)
            ]
            != source_special
        ):
            raise ValueError(
                f"{special['entry_id']}: original special bytes differ"
            )

        streams = [encoded_special]
        continuation_reports: list[dict[str, Any]] = []
        for entry in continuations:
            entry_id = str(entry["entry_id"])
            source_offset = _entry_start(entry)
            raw = _source_raw(entry)
            if input_allbin[source_offset : source_offset + len(raw)] != raw:
                raise ValueError(f"{entry_id}: base continuation bytes differ")
            encoded, report = encode_unindexed_entry(
                entry,
                additional_translation_by_id[entry_id],
                mapping,
            )
            streams.append(encoded)
            continuation_reports.append(report)
            covered.add(entry_id)

        packed = b"".join(streams)
        capacity = segment_end - segment_start
        if len(packed) > capacity:
            raise ValueError(
                f"{special['entry_id']}: continuation segment exceeds "
                f"capacity by {len(packed) - capacity} bytes"
            )
        output = packed + bytes(capacity - len(packed))
        patched_allbin[segment_start:segment_end] = output
        if bytes(patched_allbin[segment_start:segment_end]) != output:
            raise AssertionError(
                f"{special['entry_id']}: continuation write-back differs"
            )
        allowed.append((segment_start, segment_end))
        reports.append(
            {
                "anchor_special_entry_id": special["entry_id"],
                "segment_start": f"0x{segment_start:X}",
                "segment_end_exclusive": f"0x{segment_end:X}",
                "segment_capacity_bytes": capacity,
                "encoded_bytes": len(packed),
                "tail_padding_bytes": capacity - len(packed),
                "special_start_preserved": True,
                "continuation_entry_count": len(continuations),
                "continuations": continuation_reports,
            }
        )

    expected_ids = {str(entry["entry_id"]) for entry in additional_entries}
    if covered != expected_ids:
        missing = sorted(expected_ids - covered)
        raise ValueError(
            "u38 continuation coverage differs: " + ", ".join(missing)
        )
    return reports, allowed


def _pack_u39_save_stream(
    *,
    patched_allbin: bytearray,
    input_allbin: bytes,
    entries: list[dict[str, Any]],
    translation_by_id: dict[str, dict[str, Any]],
    mapping: dict[str, int],
) -> tuple[dict[str, Any], tuple[int, int]]:
    entries = sorted(entries, key=_entry_start)
    if not entries:
        raise ValueError("u39 save-system stream is empty")
    for left, right in zip(entries, entries[1:]):
        if _entry_start(left) + len(_source_raw(left)) != _entry_start(right):
            raise ValueError("u39 save-system source stream is not contiguous")
    region_start = _entry_start(entries[0])
    region_end = _entry_start(entries[-1]) + len(_source_raw(entries[-1]))

    streams: list[bytes] = []
    reports: list[dict[str, Any]] = []
    for entry in entries:
        entry_id = str(entry["entry_id"])
        offset = _entry_start(entry)
        raw = _source_raw(entry)
        if input_allbin[offset : offset + len(raw)] != raw:
            raise ValueError(f"{entry_id}: base save-system bytes differ")
        encoded, report = encode_unindexed_entry(
            entry,
            translation_by_id[entry_id],
            mapping,
        )
        streams.append(encoded)
        reports.append(report)

    packed = b"".join(streams)
    capacity = region_end - region_start
    if len(packed) > capacity:
        raise ValueError(
            f"u39 save-system stream exceeds capacity by "
            f"{len(packed) - capacity} bytes"
        )
    output = packed + bytes(capacity - len(packed))
    patched_allbin[region_start:region_end] = output
    if bytes(patched_allbin[region_start:region_end]) != output:
        raise AssertionError("u39 save-system write-back differs")
    return {
        "entry_count": len(entries),
        "region_start": f"0x{region_start:X}",
        "region_end_exclusive": f"0x{region_end:X}",
        "region_capacity_bytes": capacity,
        "encoded_bytes": len(packed),
        "tail_padding_bytes": capacity - len(packed),
        "source_order_preserved": True,
        "first_stream_start_preserved": True,
        "entries": reports,
    }, (region_start, region_end)


def build_unindexed_font_patch(
    *,
    file_build_dir: Path,
    workset_path: Path,
    translation_path: Path,
    special_workset_path: Path,
    special_translation_path: Path,
    original_glyph_map_path: Path,
    font_profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    input_start = (file_build_dir / "START.BIN").read_bytes()
    input_allbin = (file_build_dir / "ALLBIN.BIN").read_bytes()
    input_slps_path = file_build_dir / "SLPS_019.58"
    built_map_path = file_build_dir / "primary-korean-glyph-map.json"
    for name, payload in (
        ("START.BIN", input_start),
        ("ALLBIN.BIN", input_allbin),
    ):
        if sha256_bytes(payload) != base_manifest["outputs"][name]["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")
    if sha256_file(built_map_path) != base_manifest["outputs"]["glyph_map"][
        "sha256"
    ]:
        raise ValueError("primary glyph map base-build hash differs")

    source_start_path = Path(base_manifest["sources"]["START.BIN"]["path"])
    source_allbin_path = Path(base_manifest["sources"]["ALLBIN.BIN"]["path"])
    source_start = source_start_path.read_bytes()
    source_allbin = source_allbin_path.read_bytes()
    if sha256_bytes(source_start) != EXPECTED_START_SHA256:
        raise ValueError("START.BIN verified original hash differs")
    if sha256_bytes(source_allbin) != EXPECTED_ALLBIN_SHA256:
        raise ValueError("ALLBIN.BIN verified original hash differs")

    workset = load_object(workset_path)
    translation = load_object(translation_path)
    entries, translation_by_id, validation = validate_unindexed_artifacts(
        workset,
        translation,
        workset_path=workset_path,
        source_allbin=source_allbin,
        expected_allbin_sha256=EXPECTED_ALLBIN_SHA256,
    )
    selected_by_unit = {
        unit: [
            entry
            for entry in entries
            if int(entry["source"]["unit_index"]) == unit
        ]
        for unit in EXPECTED_SELECTED_COUNTS
    }
    actual_counts = {
        unit: len(selected_by_unit[unit])
        for unit in EXPECTED_SELECTED_COUNTS
    }
    if actual_counts != EXPECTED_SELECTED_COUNTS:
        raise ValueError("u38/u39 unindexed population differs")

    required = special_required_characters(
        item["ko"] for item in translation_by_id.values()
    )
    base_mapping = load_built_primary_mapping(built_map_path)
    patched_start, mapping, font_report, start_allowed = extend_primary_font(
        input_start,
        source_start,
        base_mapping,
        required,
        original_glyph_map_path=original_glyph_map_path,
        font_profile_path=font_profile_path,
    )

    special_workset = load_object(special_workset_path)
    special_translation = load_object(special_translation_path)
    special_entries, _special_by_id, _special_texts, _special_validation = (
        validate_special_screen_artifacts(
            special_workset,
            special_translation,
            workset_path=special_workset_path,
            source_allbin=source_allbin,
        )
    )
    u38_special_entries = [
        entry
        for entry in special_entries
        if int(entry["source"]["unit_index"]) == 38
    ]
    special_translation_by_id = _special_translation_map(
        special_translation
    )

    patched_allbin = bytearray(input_allbin)
    u38_reports, u38_allowed = _pack_u38_continuations(
        patched_allbin=patched_allbin,
        input_allbin=input_allbin,
        source_allbin=source_allbin,
        additional_entries=selected_by_unit[38],
        additional_translation_by_id=translation_by_id,
        special_entries=u38_special_entries,
        special_translation_by_id=special_translation_by_id,
        mapping=mapping,
    )
    u39_report, u39_allowed = _pack_u39_save_stream(
        patched_allbin=patched_allbin,
        input_allbin=input_allbin,
        entries=selected_by_unit[39],
        translation_by_id=translation_by_id,
        mapping=mapping,
    )
    allbin_allowed = [*u38_allowed, u39_allowed]

    start_expected = verify_expected_writes(
        input_start,
        patched_start,
        allowed_ranges=start_allowed,
        owner="remaining primary Korean glyph extension",
    )
    allbin_expected = verify_expected_writes(
        input_allbin,
        bytes(patched_allbin),
        allowed_ranges=allbin_allowed,
        owner="u38 continuation and u39 save-system Korean text",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "START.BIN": patched_start,
        "ALLBIN.BIN": bytes(patched_allbin),
    }
    if input_slps_path.is_file():
        input_slps = input_slps_path.read_bytes()
        if sha256_bytes(input_slps) != base_manifest["outputs"][
            "SLPS_019.58"
        ]["sha256"]:
            raise ValueError("SLPS_019.58: base file-build hash differs")
        outputs["SLPS_019.58"] = input_slps
    for name, payload in outputs.items():
        (output_dir / name).write_bytes(payload)

    base_map = load_object(built_map_path)
    output_map = output_dir / built_map_path.name
    write_json(
        output_map,
        {
            **{
                key: copy.deepcopy(value)
                for key, value in base_map.items()
                if key != "mapping"
            },
            "status": (
                "nonrelease-all-reviewed-nongraphic-font-corpus-static-map"
            ),
            "mapping": {
                character: f"0x{index:03X}"
                for character, index in sorted(
                    mapping.items(), key=lambda item: item[1]
                )
            },
            "unindexed_font_extension": font_report,
        },
    )

    manifest = {
        **base_manifest,
        "status": (
            "nonrelease-all-reviewed-nongraphic-font-text-"
            "runtime-validation-required"
        ),
        "release_eligible": False,
        "sources": {
            **base_manifest["sources"],
            "base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
            "unindexed_font_workset": {
                "path": str(workset_path.resolve()),
                "sha256": sha256_file(workset_path),
            },
            "unindexed_font_translation": {
                "path": str(translation_path.resolve()),
                "sha256": sha256_file(translation_path),
            },
        },
        "font_scope": (
            "all-reviewed-nongraphic-primary-font-text-including-"
            "u38-continuations-and-u39-save-system"
        ),
        "unindexed_font": {
            "status": "statically-injected-runtime-route-qa-required",
            "release_eligible": False,
            "entry_count": len(entries),
            "story_entry_count": (
                len(entries)
                - EXPECTED_SELECTED_COUNTS[38]
                - EXPECTED_SELECTED_COUNTS[39]
            ),
            "u38_entry_count": EXPECTED_SELECTED_COUNTS[38],
            "u39_entry_count": EXPECTED_SELECTED_COUNTS[39],
            "validation": validation,
            "font": font_report,
            "u38": {
                "anchor_segment_count": len(u38_reports),
                "entry_count": sum(
                    int(report["continuation_entry_count"])
                    for report in u38_reports
                ),
                "segments": u38_reports,
            },
            "u39": u39_report,
            "runtime_review": [
                "exercise every newly translated race branch in u30..u34",
                "exercise every newly translated mini-game branch in u38",
                "exercise save, load, overwrite, missing-data, and error paths",
            ],
        },
        "expected_writes": {
            **base_manifest.get("expected_writes", {}),
            "unindexed_font": {
                "START.BIN_relative_to_base_build": start_expected,
                "ALLBIN.BIN_relative_to_base_build": allbin_expected,
            },
        },
        "outputs": {
            **base_manifest["outputs"],
            **{
                name: {
                    "path": str((output_dir / name).resolve()),
                    "size": len(payload),
                    "sha256": sha256_bytes(payload),
                }
                for name, payload in outputs.items()
            },
            "glyph_map": {
                "path": str(output_map.resolve()),
                "sha256": sha256_file(output_map),
            },
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-build-dir", type=Path, required=True)
    parser.add_argument(
        "--workset",
        type=Path,
        default=Path(
            "work/translations/disc1-unindexed-font-text.json"
        ),
    )
    parser.add_argument(
        "--translation",
        type=Path,
        default=Path(
            "data/translations/disc1-unindexed-font-ko.json"
        ),
    )
    parser.add_argument(
        "--special-workset",
        type=Path,
        default=Path(
            "work/translations/disc1-special-screen-text.json"
        ),
    )
    parser.add_argument(
        "--special-translation",
        type=Path,
        default=Path("data/translations/disc1-special-screen-ko.json"),
    )
    parser.add_argument(
        "--glyph-map",
        type=Path,
        default=Path("data/glyph-map.json"),
    )
    parser.add_argument(
        "--font-profile",
        type=Path,
        default=Path("config/font-profile.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_unindexed_font_patch(
        file_build_dir=args.file_build_dir,
        workset_path=args.workset,
        translation_path=args.translation,
        special_workset_path=args.special_workset,
        special_translation_path=args.special_translation,
        original_glyph_map_path=args.glyph_map,
        font_profile_path=args.font_profile,
        output_dir=args.output_dir,
    )
    print(
        f"entries={manifest['unindexed_font']['entry_count']} "
        f"START={manifest['outputs']['START.BIN']['sha256']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
