#!/usr/bin/env python3
"""Add the two runtime-confirmed u43 garage action menus to a file build."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
import shutil

try:
    from scripts.build_character_name_patch import load_built_primary_mapping
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.build_special_screen_patch import (
        encode_special_entry,
        load_object,
        sha256_bytes,
        sha256_file,
        validate_special_screen_artifacts,
        write_json,
    )
except ModuleNotFoundError:
    from build_character_name_patch import load_built_primary_mapping
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_special_screen_patch import (
        encode_special_entry,
        load_object,
        sha256_bytes,
        sha256_file,
        validate_special_screen_artifacts,
        write_json,
    )


CLASSIFICATION = "garage_action_menu"
EXPECTED_MENU_COUNT = 2


def build_garage_action_menu_patch(
    *,
    file_build_dir: Path,
    workset_path: Path,
    translation_path: Path,
    source_allbin_path: Path,
    output_dir: Path,
) -> dict:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    source_allbin = source_allbin_path.read_bytes()
    workset = load_object(workset_path)
    translation = load_object(translation_path)
    entries, _by_id, translations, validation = validate_special_screen_artifacts(
        workset,
        translation,
        workset_path=workset_path,
        source_allbin=source_allbin,
    )
    menus = [entry for entry in entries if entry["classification"] == CLASSIFICATION]
    if len(menus) != EXPECTED_MENU_COUNT:
        raise ValueError(
            f"garage action menu population differs: {len(menus)} != "
            f"{EXPECTED_MENU_COUNT}"
        )

    input_allbin_path = file_build_dir / "ALLBIN.BIN"
    input_allbin = input_allbin_path.read_bytes()
    if sha256_bytes(input_allbin) != base_manifest["outputs"]["ALLBIN.BIN"]["sha256"]:
        raise ValueError("ALLBIN.BIN base file-build hash differs")
    mapping_path = file_build_dir / "primary-korean-glyph-map.json"
    mapping = load_built_primary_mapping(mapping_path)

    patched = bytearray(input_allbin)
    allowed_ranges: list[tuple[int, int]] = []
    reports: list[dict] = []
    for entry in menus:
        entry_id = str(entry["entry_id"])
        offset = int(entry["source"]["file_offset"], 16)
        source_raw = bytes.fromhex(entry["original"]["raw_hex"])
        if bytes(patched[offset : offset + len(source_raw)]) != source_raw:
            raise ValueError(f"{entry_id}: garage menu source slot differs")
        replacement, report = encode_special_entry(
            entry,
            translations[entry_id],
            mapping,
        )
        patched[offset : offset + len(source_raw)] = replacement
        allowed_ranges.append((offset, offset + len(source_raw)))
        reports.append(
            {
                **report,
                "replacement_sha256": sha256_bytes(replacement),
            }
        )

    expected = verify_expected_writes(
        input_allbin,
        bytes(patched),
        allowed_ranges=allowed_ranges,
        owner="u43 runtime-confirmed garage action menus",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_payloads: dict[str, bytes] = {}
    for name in base_manifest["outputs"]:
        if name == "glyph_map":
            continue
        source = file_build_dir / name
        if not source.is_file():
            continue
        payload = bytes(patched) if name == "ALLBIN.BIN" else source.read_bytes()
        (output_dir / name).write_bytes(payload)
        output_payloads[name] = payload
    output_map = output_dir / mapping_path.name
    shutil.copyfile(mapping_path, output_map)

    special = copy.deepcopy(base_manifest.get("special_screen", {}))
    old_count = int(special.get("entry_count", 0))
    if old_count not in (0, len(entries) - EXPECTED_MENU_COUNT):
        raise ValueError("base special-screen population is unexpected")
    special["entry_count"] = len(entries)
    unit_counts = dict(special.get("unit_entry_counts", {}))
    unit_counts["u43"] = int(unit_counts.get("u43", 0)) + EXPECTED_MENU_COUNT
    special["unit_entry_counts"] = unit_counts
    special["garage_action_menu"] = {
        "entry_count": EXPECTED_MENU_COUNT,
        "runtime_observed": True,
        "fixed_slot_overflow_count": 0,
        "entries": reports,
    }

    manifest = {
        **base_manifest,
        "sources": {
            **base_manifest["sources"],
            "garage_action_menu_base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
            "special_screen_workset": {
                "path": str(workset_path.resolve()),
                "sha256": sha256_file(workset_path),
            },
            "special_screen_translation": {
                "path": str(translation_path.resolve()),
                "sha256": sha256_file(translation_path),
            },
        },
        "special_screen": special,
        "garage_action_menu": {
            "status": "runtime-observed-static-injection-user-validation-required",
            "entry_count": EXPECTED_MENU_COUNT,
            "artifact_validation": validation,
            "entries": reports,
        },
        "expected_writes": {
            **base_manifest.get("expected_writes", {}),
            "garage_action_menu": {
                "ALLBIN.BIN_relative_to_base_build": expected,
            },
        },
        "outputs": {
            **{
                name: {
                    "path": str((output_dir / name).resolve()),
                    "size": len(payload),
                    "sha256": sha256_bytes(payload),
                }
                for name, payload in output_payloads.items()
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
        default=Path("work/translations/disc1-special-screen-text.json"),
    )
    parser.add_argument(
        "--translation",
        type=Path,
        default=Path("data/translations/disc1-special-screen-ko.json"),
    )
    parser.add_argument(
        "--source-allbin",
        type=Path,
        default=Path("work/extracted/disc1/iso/ALLBIN.BIN"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_garage_action_menu_patch(
        file_build_dir=args.file_build_dir,
        workset_path=args.workset,
        translation_path=args.translation,
        source_allbin_path=args.source_allbin,
        output_dir=args.output_dir,
    )
    print(
        f"garage_menus={manifest['garage_action_menu']['entry_count']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
