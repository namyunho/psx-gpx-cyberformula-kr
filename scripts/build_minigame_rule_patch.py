#!/usr/bin/env python3
"""Update the verified u38 mini-game rule labels and 13-column pages."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
import shutil

try:
    from scripts.build_character_name_patch import load_built_primary_mapping
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.build_special_screen_patch import (
        EXPECTED_BASELINE_ID,
        encode_special_entry,
        load_object,
        sha256_bytes,
        sha256_file,
        special_required_characters,
        validate_special_screen_artifacts,
        write_json,
    )
except ModuleNotFoundError:
    from build_character_name_patch import load_built_primary_mapping
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_special_screen_patch import (
        EXPECTED_BASELINE_ID,
        encode_special_entry,
        load_object,
        sha256_bytes,
        sha256_file,
        special_required_characters,
        validate_special_screen_artifacts,
        write_json,
    )


RULE_CLASSIFICATIONS = frozenset(
    {"minigame_rule_heading", "minigame_rule_title", "minigame_rule_page"}
)
EXPECTED_RULE_ENTRY_COUNT = 29


def build_minigame_rule_patch(
    *,
    file_build_dir: Path,
    workset_path: Path,
    translation_path: Path,
    source_allbin_path: Path,
    output_dir: Path,
) -> dict:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    prior_special = base_manifest.get("special_screen")
    if (
        not isinstance(prior_special, dict)
        or prior_special.get("baseline_id") != EXPECTED_BASELINE_ID
    ):
        raise ValueError("base build has no compatible special-screen patch")

    source_allbin = source_allbin_path.read_bytes()
    workset = load_object(workset_path)
    translation = load_object(translation_path)
    entries, _by_id, translations, validation = validate_special_screen_artifacts(
        workset,
        translation,
        workset_path=workset_path,
        source_allbin=source_allbin,
    )
    rules = [
        entry
        for entry in entries
        if entry["classification"] in RULE_CLASSIFICATIONS
    ]
    if len(rules) != EXPECTED_RULE_ENTRY_COUNT:
        raise ValueError(
            f"mini-game rule population differs: {len(rules)} != "
            f"{EXPECTED_RULE_ENTRY_COUNT}"
        )
    if any(int(entry["layout"]["columns"]) != 13 for entry in rules):
        raise ValueError("mini-game rule entry does not use 13 columns")

    input_allbin_path = file_build_dir / "ALLBIN.BIN"
    input_allbin = input_allbin_path.read_bytes()
    if sha256_bytes(input_allbin) != base_manifest["outputs"]["ALLBIN.BIN"][
        "sha256"
    ]:
        raise ValueError("ALLBIN.BIN base file-build hash differs")
    mapping_path = file_build_dir / "primary-korean-glyph-map.json"
    mapping = load_built_primary_mapping(mapping_path)
    required = special_required_characters(
        translations[str(entry["entry_id"])] for entry in rules
    )
    missing = [character for character in required if character not in mapping]
    if missing:
        raise ValueError(f"mini-game rule glyphs are missing: {missing}")

    prior_reports = {
        str(report.get("id")): report
        for report in prior_special.get("entries", [])
        if isinstance(report, dict) and isinstance(report.get("id"), str)
    }
    patched = bytearray(input_allbin)
    allowed_ranges: list[tuple[int, int]] = []
    reports: list[dict] = []
    for entry in rules:
        entry_id = str(entry["entry_id"])
        offset = int(entry["source"]["file_offset"], 16)
        source_raw = bytes.fromhex(entry["original"]["raw_hex"])
        current_raw = bytes(patched[offset : offset + len(source_raw)])
        if current_raw != source_raw:
            prior = prior_reports.get(entry_id)
            if (
                prior is None
                or int(str(prior.get("source_file_offset")), 16) != offset
                or int(prior.get("source_bytes", -1)) != len(source_raw)
                or prior.get("replacement_sha256") != sha256_bytes(current_raw)
            ):
                raise ValueError(
                    f"{entry_id}: current slot is neither original nor the "
                    "verified prior replacement"
                )
        replacement, report = encode_special_entry(
            entry,
            translations[entry_id],
            mapping,
        )
        patched[offset : offset + len(source_raw)] = replacement
        allowed_ranges.append((offset, offset + len(source_raw)))
        reports.append(
            {**report, "replacement_sha256": sha256_bytes(replacement)}
        )

    expected = verify_expected_writes(
        input_allbin,
        bytes(patched),
        allowed_ranges=allowed_ranges,
        owner="u38 mini-game rule labels and 13-column pages",
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

    merged_reports = copy.deepcopy(prior_special.get("entries", []))
    merged_by_id = {
        str(report.get("id")): index
        for index, report in enumerate(merged_reports)
        if isinstance(report, dict) and isinstance(report.get("id"), str)
    }
    for report in reports:
        index = merged_by_id.get(report["id"])
        if index is None:
            merged_by_id[report["id"]] = len(merged_reports)
            merged_reports.append(report)
        else:
            merged_reports[index] = report

    special = copy.deepcopy(prior_special)
    special["entry_count"] = len(entries)
    unit_counts = dict(special.get("unit_entry_counts", {}))
    unit_counts["u38"] = sum(
        int(entry["source"]["unit_index"]) == 38 for entry in entries
    )
    special["unit_entry_counts"] = unit_counts
    special["entries"] = merged_reports
    special["minigame_rule_text"] = {
        "entry_count": len(rules),
        "columns": 13,
        "fixed_slot_overflow_count": 0,
        "layout_issue_count": 0,
        "runtime_vram_observed": True,
        "entries": reports,
    }

    manifest = {
        **base_manifest,
        "sources": {
            **base_manifest["sources"],
            "minigame_rule_base_file_build_manifest": {
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
        "minigame_rule_text": {
            "status": "static-update-complete-runtime-validation-required",
            "artifact_validation": validation,
            "entry_count": len(rules),
            "entries": reports,
        },
        "expected_writes": {
            **base_manifest.get("expected_writes", {}),
            "minigame_rule_text": {
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
    manifest = build_minigame_rule_patch(
        file_build_dir=args.file_build_dir,
        workset_path=args.workset,
        translation_path=args.translation,
        source_allbin_path=args.source_allbin,
        output_dir=args.output_dir,
    )
    print(
        f"rule_entries={manifest['minigame_rule_text']['entry_count']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
