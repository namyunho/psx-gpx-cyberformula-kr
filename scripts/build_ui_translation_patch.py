#!/usr/bin/env python3
"""Add statically verified Korean name-editor UI to a partial file build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
from typing import Any, Iterable

try:
    from scripts.build_character_name_patch import (
        ALTERNATE_DEFINED_GLYPH_COUNT,
        ALTERNATE_FIXED_NAME_MAPPING,
        ALTERNATE_FONT_OFFSET,
        ALTERNATE_FONT_SCHEDULED_BYTE_SIZE,
        EXPECTED_ALLBIN_SHA256,
        EXPECTED_START_SHA256,
        load_built_primary_mapping,
    )
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.korean_font import (
        crop_to_psx,
        load_font_profile,
        rasterize_ttf_glyph,
    )
    from scripts.psx_font import GLYPH_SIZE, pack_glyph
except ModuleNotFoundError:
    from build_character_name_patch import (
        ALTERNATE_DEFINED_GLYPH_COUNT,
        ALTERNATE_FIXED_NAME_MAPPING,
        ALTERNATE_FONT_OFFSET,
        ALTERNATE_FONT_SCHEDULED_BYTE_SIZE,
        EXPECTED_ALLBIN_SHA256,
        EXPECTED_START_SHA256,
        load_built_primary_mapping,
    )
    from build_dialogue_chapter_patch import verify_expected_writes
    from korean_font import crop_to_psx, load_font_profile, rasterize_ttf_glyph
    from psx_font import GLYPH_SIZE, pack_glyph


EXPECTED_BASELINE_ID = "disc1-allbin-6f61295be0ce2d7d"
EXPECTED_UI_ENTRY_COUNT = 60
UI_PACE = 0xFFFD
UI_ALIGN = 0xFFFB
UI_END = 0xFFFF
ALTERNATE_UI_FIRST_GLYPH = max(ALTERNATE_FIXED_NAME_MAPPING.values()) + 1


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


def expand_entry_id_range(specifier: str) -> list[str]:
    if ".." not in specifier:
        raise ValueError(f"invalid UI entry range: {specifier!r}")
    first, last = specifier.split("..", 1)
    prefix, first_number = first.rsplit("e", 1)
    if not last.startswith("e"):
        raise ValueError(f"invalid UI entry range end: {specifier!r}")
    last_number = last[1:]
    if (
        len(first_number) != len(last_number)
        or not first_number.isdigit()
        or not last_number.isdigit()
    ):
        raise ValueError(f"invalid UI entry range numbers: {specifier!r}")
    start = int(first_number)
    end = int(last_number)
    if end < start:
        raise ValueError(f"reversed UI entry range: {specifier!r}")
    width = len(first_number)
    return [f"{prefix}e{index:0{width}d}" for index in range(start, end + 1)]


def validate_ui_artifacts(
    workset: dict[str, Any],
    translations: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    if workset.get("baseline_id") != EXPECTED_BASELINE_ID:
        raise ValueError("UI workset baseline differs")
    if translations.get("baseline_id") != EXPECTED_BASELINE_ID:
        raise ValueError("UI translation baseline differs")
    entries = workset.get("entries")
    coverage = translations.get("coverage")
    translated = translations.get("translations")
    if (
        not isinstance(entries, list)
        or not isinstance(coverage, list)
        or not isinstance(translated, list)
    ):
        raise ValueError("UI artifacts are incomplete")

    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        entry_id = entry.get("entry_id")
        if not isinstance(entry_id, str) or entry_id in by_id:
            raise ValueError(f"invalid or duplicate UI entry ID: {entry_id!r}")
        by_id[entry_id] = entry
    if len(by_id) != EXPECTED_UI_ENTRY_COUNT:
        raise ValueError(
            f"UI workset requires {EXPECTED_UI_ENTRY_COUNT} entries"
        )

    actions: dict[str, str] = {}
    for group in coverage:
        ids = expand_entry_id_range(str(group.get("entry_id_range")))
        if len(ids) != int(group.get("expected_count", -1)):
            raise ValueError("UI coverage count differs from its range")
        action = group.get("action")
        if not isinstance(action, str):
            raise ValueError("UI coverage action is missing")
        for entry_id in ids:
            if entry_id in actions:
                raise ValueError(f"overlapping UI coverage: {entry_id}")
            actions[entry_id] = action
    if set(actions) != set(by_id):
        missing = sorted(set(by_id) - set(actions))
        extra = sorted(set(actions) - set(by_id))
        raise ValueError(f"UI coverage mismatch: missing={missing} extra={extra}")

    translation_by_id: dict[str, dict[str, Any]] = {}
    for item in translated:
        entry_id = item.get("id")
        if (
            not isinstance(entry_id, str)
            or entry_id in translation_by_id
            or actions.get(entry_id) != "translate"
        ):
            raise ValueError(f"invalid translated UI ID: {entry_id!r}")
        if item.get("renderer") not in {"primary", "alternate"}:
            raise ValueError(f"{entry_id}: invalid renderer")
        if not isinstance(item.get("ko"), str) or not item["ko"]:
            raise ValueError(f"{entry_id}: Korean text is missing")
        translation_by_id[entry_id] = item
    expected_translated = {
        entry_id for entry_id, action in actions.items() if action == "translate"
    }
    if set(translation_by_id) != expected_translated:
        raise ValueError("UI literal translation coverage is incomplete")
    return by_id, translation_by_id, actions


def source_ui_rows(entry: dict[str, Any]) -> int:
    tokens = [int(value, 16) for value in entry["original"]["tokens"]]
    if not tokens or tokens[0] != UI_PACE or tokens[-1] != UI_END:
        raise ValueError(f"{entry['entry_id']}: unexpected UI control shell")
    if any(token >= 0x4000 for token in tokens[1:-1] if token != UI_ALIGN):
        raise ValueError(f"{entry['entry_id']}: unsupported internal UI control")
    return tokens.count(UI_ALIGN) + 1


def encode_ui_text(
    entry: dict[str, Any],
    text: str,
    mapping: dict[str, int],
) -> tuple[bytes, dict[str, Any]]:
    lines = text.split("\n")
    source_rows = source_ui_rows(entry)
    if len(lines) != source_rows:
        raise ValueError(
            f"{entry['entry_id']}: {len(lines)} output rows != "
            f"{source_rows} source rows"
        )
    body: list[int] = []
    for line_index, line in enumerate(lines):
        if line_index:
            body.append(UI_ALIGN)
        for character in line:
            try:
                body.append(mapping[character])
            except KeyError as error:
                raise ValueError(
                    f"{entry['entry_id']}: unmapped UI character "
                    f"{character!r}"
                ) from error
    tokens = [UI_PACE, *body, UI_END]
    encoded = struct.pack(f"<{len(tokens)}H", *tokens)
    capacity = int(entry["source"]["byte_size"])
    if len(encoded) > capacity:
        raise ValueError(
            f"{entry['entry_id']}: encoded UI requires {len(encoded)} bytes "
            f"but the fixed slot has {capacity}"
        )
    return encoded, {
        "entry_id": entry["entry_id"],
        "renderer": None,
        "source_rows": source_rows,
        "output_rows": len(lines),
        "source_slot_bytes": capacity,
        "encoded_bytes": len(encoded),
        "remaining_slot_bytes": capacity - len(encoded),
        "visible_glyph_count": sum(len(line) for line in lines),
        "align_token_count": len(lines) - 1,
        "control_shell_preserved": True,
    }


def alternate_ui_mapping(texts: Iterable[str]) -> dict[str, int]:
    characters: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for character in text:
            if character == "\n" or character in seen:
                continue
            seen.add(character)
            characters.append(character)
    mapping = {" ": 0x000}
    next_index = ALTERNATE_UI_FIRST_GLYPH
    for character in characters:
        if character == " ":
            continue
        mapping[character] = next_index
        next_index += 1
    return mapping


def render_alternate_ui_glyphs(
    base_start: bytes,
    original_start: bytes,
    mapping: dict[str, int],
    *,
    font_profile_path: Path,
) -> tuple[bytes, dict[str, Any], list[tuple[int, int]]]:
    profile = load_font_profile(font_profile_path)
    from PIL import ImageFont

    ttf = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    patched = bytearray(base_start)
    allowed_ranges: list[tuple[int, int]] = []
    scheduled_end = ALTERNATE_FONT_OFFSET + ALTERNATE_FONT_SCHEDULED_BYTE_SIZE
    generated: list[dict[str, Any]] = []
    for character, index in mapping.items():
        if character == " ":
            continue
        start = ALTERNATE_FONT_OFFSET + index * GLYPH_SIZE
        end = start + GLYPH_SIZE
        if end > scheduled_end:
            raise ValueError(
                f"alternate UI glyph 0x{index:03X} exceeds scheduled load"
            )
        if any(original_start[start:end]) or any(base_start[start:end]):
            raise ValueError(
                f"alternate UI glyph 0x{index:03X} is not in the zero tail"
            )
        pixels = rasterize_ttf_glyph(
            ttf,
            character,
            x_offset=profile.x_offset_px,
            y_offset=profile.y_offset_px,
        )
        retained = crop_to_psx(pixels, intensity=profile.intensity)
        if not any(retained):
            raise ValueError(
                f"Galmuri11 produced an empty UI glyph for {character!r}"
            )
        patched[start:end] = pack_glyph(retained)
        allowed_ranges.append((start, end))
        generated.append(
            {
                "character": character,
                "glyph_index": f"0x{index:03X}",
                "file_offset": f"0x{start:X}",
            }
        )
    return bytes(patched), {
        "font_offset": f"0x{ALTERNATE_FONT_OFFSET:X}",
        "record_bytes": GLYPH_SIZE,
        "first_ui_glyph_index": f"0x{ALTERNATE_UI_FIRST_GLYPH:03X}",
        "generated_glyph_count": len(generated),
        "generated_glyphs": generated,
        "space_glyph_index": "0x000",
        "original_and_base_zero_tail_verified": True,
        "scheduled_end_exclusive": f"0x{scheduled_end:X}",
    }, allowed_ranges


def _base_status_with_ui(status: str) -> str:
    values = {
        "nonrelease-partial-chapter-build-with-character-names": (
            "nonrelease-partial-chapter-build-with-character-names-and-ui"
        ),
        (
            "nonrelease-fixed-original-offset-overflow-diagnostic-"
            "with-character-names"
        ): (
            "nonrelease-fixed-original-offset-overflow-diagnostic-"
            "with-character-names-and-ui"
        ),
    }
    try:
        return values[status]
    except KeyError as error:
        raise ValueError(f"unsupported base file-build status: {status}") from error


def build_ui_translation_patch(
    *,
    file_build_dir: Path,
    workset_path: Path,
    translation_path: Path,
    font_profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    output_status = _base_status_with_ui(str(base_manifest.get("status")))

    input_start = (file_build_dir / "START.BIN").read_bytes()
    input_allbin = (file_build_dir / "ALLBIN.BIN").read_bytes()
    built_map_path = file_build_dir / "primary-korean-glyph-map.json"
    input_slps_path = file_build_dir / "SLPS_019.58"
    for name, payload in (
        ("START.BIN", input_start),
        ("ALLBIN.BIN", input_allbin),
    ):
        if sha256_bytes(payload) != base_manifest["outputs"][name]["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")
    if not input_slps_path.is_file():
        raise ValueError("UI build requires the character-name SLPS output")
    input_slps = input_slps_path.read_bytes()
    if sha256_bytes(input_slps) != base_manifest["outputs"]["SLPS_019.58"]["sha256"]:
        raise ValueError("SLPS_019.58: base file-build hash differs")

    source_start = Path(base_manifest["sources"]["START.BIN"]["path"]).read_bytes()
    source_allbin = Path(base_manifest["sources"]["ALLBIN.BIN"]["path"]).read_bytes()
    if sha256_bytes(source_start) != EXPECTED_START_SHA256:
        raise ValueError("START.BIN verified original hash differs")
    if sha256_bytes(source_allbin) != EXPECTED_ALLBIN_SHA256:
        raise ValueError("ALLBIN.BIN verified original hash differs")

    workset = load_object(workset_path)
    translations = load_object(translation_path)
    by_id, translation_by_id, actions = validate_ui_artifacts(
        workset,
        translations,
    )
    if workset.get("scope", {}).get("source_allbin_sha256") != EXPECTED_ALLBIN_SHA256:
        raise ValueError("UI workset source ALLBIN hash differs")

    primary_mapping = load_built_primary_mapping(built_map_path)
    alternate_items = [
        item
        for item in translation_by_id.values()
        if item["renderer"] == "alternate"
    ]
    alternate_mapping = alternate_ui_mapping(item["ko"] for item in alternate_items)
    patched_start, alternate_report, start_allowed = render_alternate_ui_glyphs(
        input_start,
        source_start,
        alternate_mapping,
        font_profile_path=font_profile_path,
    )

    patched_allbin = bytearray(input_allbin)
    translated_reports: list[dict[str, Any]] = []
    allbin_allowed: list[tuple[int, int]] = []
    for entry_id in sorted(translation_by_id):
        item = translation_by_id[entry_id]
        entry = by_id[entry_id]
        source_offset = int(entry["source"]["file_offset"], 16)
        source_raw = bytes.fromhex(entry["original"]["raw_hex"])
        source_size = int(entry["source"]["byte_size"])
        if len(source_raw) != source_size:
            raise ValueError(f"{entry_id}: source byte-size metadata differs")
        if source_allbin[source_offset : source_offset + source_size] != source_raw:
            raise ValueError(f"{entry_id}: verified source bytes differ")
        mapping = (
            primary_mapping
            if item["renderer"] == "primary"
            else alternate_mapping
        )
        encoded, report = encode_ui_text(entry, item["ko"], mapping)
        patched_allbin[source_offset : source_offset + len(encoded)] = encoded
        if bytes(patched_allbin[source_offset : source_offset + len(encoded)]) != encoded:
            raise ValueError(f"{entry_id}: UI write-back verification failed")
        allbin_allowed.append((source_offset, source_offset + len(encoded)))
        translated_reports.append(
            {
                **report,
                "renderer": item["renderer"],
                "output_sha256": sha256_bytes(encoded),
            }
        )

    start_expected = verify_expected_writes(
        input_start,
        patched_start,
        allowed_ranges=start_allowed,
        owner="alternate Korean UI glyphs",
    )
    allbin_expected = verify_expected_writes(
        input_allbin,
        bytes(patched_allbin),
        allowed_ranges=allbin_allowed,
        owner="fixed-slot Korean UI literals",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "START.BIN": patched_start,
        "ALLBIN.BIN": bytes(patched_allbin),
        "SLPS_019.58": input_slps,
    }
    for name, payload in outputs.items():
        (output_dir / name).write_bytes(payload)
    output_map = output_dir / built_map_path.name
    shutil.copyfile(built_map_path, output_map)

    manifest = {
        **base_manifest,
        "status": output_status,
        "sources": {
            **base_manifest["sources"],
            "base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
            "ui_workset": {
                "path": str(workset_path.resolve()),
                "sha256": sha256_file(workset_path),
            },
            "ui_translation": {
                "path": str(translation_path.resolve()),
                "sha256": sha256_file(translation_path),
            },
        },
        "ui_translation": {
            "status": "static-translation-complete-runtime-review-required",
            "release_eligible": False,
            "baseline_id": EXPECTED_BASELINE_ID,
            "total_entry_count": len(by_id),
            "translated_literal_count": len(translation_by_id),
            "preserved_input_or_runtime_count": sum(
                action != "translate" for action in actions.values()
            ),
            "translated_entries": translated_reports,
            "alternate_font": alternate_report,
            "runtime_review": [
                "name-editor prompts render in Korean",
                "name and origin labels render in Korean",
                "origin choices render and remain selectable",
                "kanji, kana, Latin, digit, and symbol input palettes remain usable",
            ],
        },
        "expected_writes": {
            **base_manifest.get("expected_writes", {}),
            "ui_translation": {
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
        default=Path("work/translations/disc1-ui.json"),
    )
    parser.add_argument(
        "--translation",
        type=Path,
        default=Path("data/translations/disc1-ui-ko.json"),
    )
    parser.add_argument(
        "--font-profile",
        type=Path,
        default=Path("config/font-profile.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_ui_translation_patch(
        file_build_dir=args.file_build_dir,
        workset_path=args.workset,
        translation_path=args.translation,
        font_profile_path=args.font_profile,
        output_dir=args.output_dir,
    )
    ui = manifest["ui_translation"]
    print(
        f"translated={ui['translated_literal_count']} "
        f"preserved={ui['preserved_input_or_runtime_count']} "
        f"alternate_glyphs="
        f"{ui['alternate_font']['generated_glyph_count']} "
        f"START={manifest['outputs']['START.BIN']['sha256']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
