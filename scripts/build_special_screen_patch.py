#!/usr/bin/env python3
"""Inject u38/u43 font-rendered special-screen Korean text into a file build."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
from typing import Any, Iterable

try:
    from scripts.build_character_name_patch import load_built_primary_mapping
    from scripts.build_dialogue_chapter_patch import (
        EXPECTED_ALLBIN_SHA256,
        EXPECTED_START_SHA256,
        FONT_GLYPH_COUNT,
        FONT_OFFSET,
        PROTECTED_ORIGINAL_GLYPH_INDICES,
        load_primary_glyph_map,
        verify_expected_writes,
    )
    from scripts.export_special_screen_translation_brief import (
        draft_issues,
        editable_position_capacity,
        stored_position_count,
        visible_length,
    )
    from scripts.korean_font import (
        crop_profile_glyph,
        load_font_profile,
        rasterize_ttf_glyph,
    )
    from scripts.psx_font import GLYPH_SIZE, pack_glyph
except ModuleNotFoundError:  # Support direct execution from repository root.
    from build_character_name_patch import load_built_primary_mapping
    from build_dialogue_chapter_patch import (
        EXPECTED_ALLBIN_SHA256,
        EXPECTED_START_SHA256,
        FONT_GLYPH_COUNT,
        FONT_OFFSET,
        PROTECTED_ORIGINAL_GLYPH_INDICES,
        load_primary_glyph_map,
        verify_expected_writes,
    )
    from export_special_screen_translation_brief import (
        draft_issues,
        editable_position_capacity,
        stored_position_count,
        visible_length,
    )
    from korean_font import (
        crop_profile_glyph,
        load_font_profile,
        rasterize_ttf_glyph,
    )
    from psx_font import GLYPH_SIZE, pack_glyph


EXPECTED_BASELINE_ID = f"disc1-allbin-{EXPECTED_ALLBIN_SHA256[:16]}"
EXPECTED_ENTRY_COUNT = 391
NAME_TOKEN_PATTERN = re.compile(r"\{name:(surname|given)\}")
UNKNOWN_MARKUP_PATTERN = re.compile(r"\{[^{}]+\}")
NAME_KIND_TO_MARKUP = {
    "name_surname": "{name:surname}",
    "name_given": "{name:given}",
}
NAME_MARKUP_TO_KIND = {
    markup: kind for kind, markup in NAME_KIND_TO_MARKUP.items()
}
BODY_CONTROL_KINDS = {"align", "name_surname", "name_given"}
TRAILING_CONTROL_KINDS = {
    "audio",
    "page_end",
    "pause",
    "stream_end",
    "voice_transition",
}


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


def _base_status_with_special_screen(status: str) -> str:
    values = {
        "nonrelease-partial-chapter-build-with-character-names-and-ui": (
            "nonrelease-partial-chapter-build-with-character-names-and-ui-"
            "and-special-screen"
        ),
        (
            "nonrelease-fixed-original-offset-overflow-diagnostic-"
            "with-character-names-and-ui"
        ): (
            "nonrelease-fixed-original-offset-overflow-diagnostic-"
            "with-character-names-and-ui-and-special-screen"
        ),
    }
    try:
        return values[status]
    except KeyError as error:
        raise ValueError(
            f"unsupported base file-build status: {status}"
        ) from error


def validate_special_screen_artifacts(
    workset: dict[str, Any],
    translation: dict[str, Any],
    *,
    workset_path: Path,
    source_allbin: bytes,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, Any],
]:
    if workset.get("baseline_id") != EXPECTED_BASELINE_ID:
        raise ValueError("special-screen workset baseline differs")
    if translation.get("baseline_id") != EXPECTED_BASELINE_ID:
        raise ValueError("special-screen translation baseline differs")
    if (
        workset.get("scope", {}).get("source_allbin_sha256")
        != EXPECTED_ALLBIN_SHA256
    ):
        raise ValueError("special-screen workset source ALLBIN hash differs")
    if translation.get("source_workset_sha256") != sha256_file(workset_path):
        raise ValueError("special-screen translation workset hash differs")

    entries = workset.get("entries")
    translated = translation.get("translations")
    if not isinstance(entries, list) or not isinstance(translated, list):
        raise ValueError("special-screen artifacts require entry arrays")
    if len(entries) != EXPECTED_ENTRY_COUNT or len(translated) != len(entries):
        raise ValueError("special-screen population differs")

    source_ids = [entry.get("entry_id") for entry in entries]
    translated_ids = [item.get("id") for item in translated]
    if (
        source_ids != translated_ids
        or any(not isinstance(entry_id, str) for entry_id in source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise ValueError("special-screen stable ID order differs")

    translations_by_id: dict[str, str] = {}
    issues: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for entry, item in zip(entries, translated):
        entry_id = str(entry["entry_id"])
        text = item.get("ko")
        if not isinstance(text, str) or not text:
            raise ValueError(f"{entry_id}: Korean translation is empty")
        source = entry.get("source")
        original = entry.get("original")
        if not isinstance(source, dict) or not isinstance(original, dict):
            raise ValueError(f"{entry_id}: protected source data is missing")
        raw = bytes.fromhex(str(original.get("raw_hex", "")))
        source_size = int(source.get("byte_size", -1))
        source_offset = int(str(source.get("file_offset")), 16)
        if (
            len(raw) != source_size
            or hashlib.sha256(raw).hexdigest() != source.get("sha256")
            or source_allbin[source_offset : source_offset + source_size] != raw
        ):
            raise ValueError(f"{entry_id}: verified source bytes differ")

        source_name_markups = [
            NAME_KIND_TO_MARKUP[control["kind"]]
            for control in original["control_tokens"]
            if control["kind"] in NAME_KIND_TO_MARKUP
        ]
        translated_name_markups = [
            match.group(0) for match in NAME_TOKEN_PATTERN.finditer(text)
        ]
        if translated_name_markups != source_name_markups:
            raise ValueError(f"{entry_id}: dynamic-name tokens changed")
        unknown = [
            markup
            for markup in UNKNOWN_MARKUP_PATTERN.findall(text)
            if markup not in NAME_MARKUP_TO_KIND
        ]
        if unknown:
            raise ValueError(
                f"{entry_id}: unknown translation markup {unknown}"
            )

        entry_issues = draft_issues(entry, text)
        if entry_issues:
            issues.append(
                {
                    "id": entry_id,
                    "issues": entry_issues,
                    "line_widths": [
                        visible_length(line) for line in text.split("\n")
                    ],
                    "stored_positions": stored_position_count(text),
                    "stored_capacity_positions": (
                        editable_position_capacity(entry)
                    ),
                }
            )
        translations_by_id[entry_id] = text
        counts[str(entry.get("classification", ""))] += 1

    validation = {
        "entry_count": len(entries),
        "stable_id_order_exact": True,
        "protected_source_bytes_exact": True,
        "layout_or_storage_issue_count": len(issues),
        "issues": issues,
        "classification_counts": dict(sorted(counts.items())),
    }
    if issues:
        raise ValueError(
            "special-screen translations do not fit: "
            + ", ".join(issue["id"] for issue in issues)
        )
    return entries, {str(e["entry_id"]): e for e in entries}, (
        translations_by_id
    ), validation


def special_required_characters(texts: Iterable[str]) -> list[str]:
    characters: set[str] = set()
    for text in texts:
        stripped = NAME_TOKEN_PATTERN.sub("", text)
        if UNKNOWN_MARKUP_PATTERN.search(stripped):
            raise ValueError(f"unknown markup remains in {text!r}")
        characters.update(character for character in stripped if character != "\n")
    return sorted(characters, key=ord)


def extend_primary_font(
    input_start: bytes,
    source_start: bytes,
    base_mapping: dict[str, int],
    required: Iterable[str],
    *,
    original_glyph_map_path: Path,
    font_profile_path: Path,
) -> tuple[bytes, dict[str, int], dict[str, Any], list[tuple[int, int]]]:
    font_end = FONT_OFFSET + FONT_GLYPH_COUNT * GLYPH_SIZE
    if font_end > len(input_start) or len(input_start) != len(source_start):
        raise ValueError("primary font region or START.BIN size differs")
    mapping = dict(base_mapping)
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("base primary mapping reuses a glyph index")
    if any(not 0 <= index < FONT_GLYPH_COUNT for index in mapping.values()):
        raise ValueError("base primary mapping index is outside the font")

    original_mapping = load_primary_glyph_map(original_glyph_map_path)
    required_characters = list(dict.fromkeys(required))
    missing = [
        character for character in required_characters if character not in mapping
    ]
    occupied = set(mapping.values()) | set(PROTECTED_ORIGINAL_GLYPH_INDICES)
    free = [
        index for index in range(FONT_GLYPH_COUNT) if index not in occupied
    ]
    patched = bytearray(input_start)
    allowed: list[tuple[int, int]] = []
    preserved: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []

    profile = load_font_profile(font_profile_path)
    from PIL import ImageFont

    ttf = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    for character in missing:
        source_index = original_mapping.get(character)
        if source_index is not None and source_index not in mapping.values():
            target_index = source_index
            mapping[character] = target_index
            occupied.add(target_index)
            if target_index not in PROTECTED_ORIGINAL_GLYPH_INDICES:
                start = FONT_OFFSET + target_index * GLYPH_SIZE
                end = start + GLYPH_SIZE
                patched[start:end] = source_start[start:end]
                allowed.append((start, end))
            preserved.append(
                {
                    "character": character,
                    "glyph_index": f"0x{target_index:03X}",
                    "source_glyph_index": f"0x{source_index:03X}",
                    "byte_exact_original": True,
                }
            )
            continue

        while free and free[0] in occupied:
            free.pop(0)
        if not free:
            raise ValueError(
                f"primary font capacity exceeded at {character!r}"
            )
        target_index = free.pop(0)
        mapping[character] = target_index
        occupied.add(target_index)
        start = FONT_OFFSET + target_index * GLYPH_SIZE
        end = start + GLYPH_SIZE
        if source_index is not None:
            source = FONT_OFFSET + source_index * GLYPH_SIZE
            patched[start:end] = source_start[source : source + GLYPH_SIZE]
            preserved.append(
                {
                    "character": character,
                    "glyph_index": f"0x{target_index:03X}",
                    "source_glyph_index": f"0x{source_index:03X}",
                    "byte_exact_original": True,
                }
            )
        elif character == " ":
            patched[start:end] = bytes(GLYPH_SIZE)
            generated.append(
                {
                    "character": character,
                    "glyph_index": f"0x{target_index:03X}",
                    "blank_space": True,
                }
            )
        else:
            pixels = rasterize_ttf_glyph(
                ttf,
                character,
                x_offset=profile.x_offset_px,
                y_offset=profile.y_offset_px,
            )
            retained = crop_profile_glyph(profile, pixels)
            if not any(retained):
                raise ValueError(
                    f"Galmuri11 produced an empty glyph for {character!r}"
                )
            patched[start:end] = pack_glyph(retained)
            generated.append(
                {
                    "character": character,
                    "glyph_index": f"0x{target_index:03X}",
                    "blank_space": False,
                }
            )
        allowed.append((start, end))

    unmapped = [
        character for character in required_characters if character not in mapping
    ]
    if unmapped:
        raise ValueError(f"unmapped special-screen characters: {unmapped}")
    for character in required_characters:
        if character == " ":
            continue
        index = mapping[character]
        start = FONT_OFFSET + index * GLYPH_SIZE
        if not any(patched[start : start + GLYPH_SIZE]):
            raise ValueError(
                f"mapped special-screen glyph is empty: {character!r}"
            )

    report = {
        "provider": "START.BIN primary dialogue font",
        "font_offset": f"0x{FONT_OFFSET:X}",
        "glyph_capacity": FONT_GLYPH_COUNT,
        "base_mapped_character_count": len(base_mapping),
        "special_required_character_count": len(required_characters),
        "already_mapped_character_count": (
            len(required_characters) - len(missing)
        ),
        "added_character_count": len(missing),
        "preserved_original_character_count": len(preserved),
        "generated_galmuri11_character_count": len(generated),
        "unmapped_character_count": 0,
        "unused_slot_count": FONT_GLYPH_COUNT - len(
            set(mapping.values()) | set(PROTECTED_ORIGINAL_GLYPH_INDICES)
        ),
        "preserved_original_characters": preserved,
        "generated_galmuri11_characters": generated,
    }
    return bytes(patched), mapping, report, allowed


def _special_template(
    entry: dict[str, Any],
) -> tuple[list[int], list[int], list[tuple[str, int]]]:
    tokens = [int(value, 16) for value in entry["original"]["tokens"]]
    controls = {
        int(control["token_index"]): str(control["kind"])
        for control in entry["original"]["control_tokens"]
    }
    if not tokens:
        raise ValueError(f"{entry['entry_id']}: empty source token stream")

    leading_end = 0
    while (
        leading_end < len(tokens)
        and leading_end in controls
        and controls[leading_end] not in BODY_CONTROL_KINDS
    ):
        leading_end += 1

    trailing_start = len(tokens)
    while (
        trailing_start > leading_end
        and trailing_start - 1 in controls
        and controls[trailing_start - 1] not in BODY_CONTROL_KINDS
    ):
        trailing_start -= 1

    # One verified direct fragment ends with FFFC followed by one zero pad.
    # Treat both words as immutable suffix instead of editable text.
    if trailing_start == len(tokens):
        zero_start = len(tokens)
        while zero_start > leading_end and tokens[zero_start - 1] == 0:
            zero_start -= 1
        if (
            zero_start < len(tokens)
            and zero_start > leading_end
            and controls.get(zero_start - 1) in TRAILING_CONTROL_KINDS
        ):
            trailing_start = zero_start - 1
            while (
                trailing_start > leading_end
                and trailing_start - 1 in controls
                and controls[trailing_start - 1] not in BODY_CONTROL_KINDS
            ):
                trailing_start -= 1

    body_controls: list[tuple[str, int]] = []
    for index in range(leading_end, trailing_start):
        kind = controls.get(index)
        if kind is None:
            continue
        if kind not in BODY_CONTROL_KINDS:
            raise ValueError(
                f"{entry['entry_id']}: unsupported internal control {kind}"
            )
        if kind in NAME_KIND_TO_MARKUP:
            body_controls.append((kind, tokens[index]))

    if any(index not in controls for index in range(leading_end)):
        raise ValueError(f"{entry['entry_id']}: leading shell contains glyphs")
    for index in range(trailing_start, len(tokens)):
        if index not in controls and tokens[index] != 0:
            raise ValueError(
                f"{entry['entry_id']}: trailing shell contains glyphs"
            )
    return tokens[:leading_end], tokens[trailing_start:], body_controls


def encode_special_entry(
    entry: dict[str, Any],
    text: str,
    mapping: dict[str, int],
) -> tuple[bytes, dict[str, Any]]:
    leading, trailing, name_controls = _special_template(entry)
    layout = entry["layout"]
    rows = int(layout["rows"])
    columns = int(layout["columns"])
    lines = text.split("\n")
    if not 1 <= len(lines) <= rows:
        raise ValueError(f"{entry['entry_id']}: row count exceeds layout")
    line_widths = [visible_length(line) for line in lines]
    if any(width > columns for width in line_widths):
        raise ValueError(f"{entry['entry_id']}: line width exceeds layout")
    if stored_position_count(text) > editable_position_capacity(entry):
        raise ValueError(f"{entry['entry_id']}: fixed storage slot exceeded")

    expected_name_kinds = [kind for kind, _raw in name_controls]
    actual_name_kinds = [
        NAME_MARKUP_TO_KIND[match.group(0)]
        for match in NAME_TOKEN_PATTERN.finditer(text)
    ]
    if actual_name_kinds != expected_name_kinds:
        raise ValueError(f"{entry['entry_id']}: dynamic-name order differs")
    name_raw = iter(raw for _kind, raw in name_controls)

    body: list[int] = []
    position = 0
    while position < len(text):
        if text[position] == "\n":
            body.append(0xFFFB)
            position += 1
            continue
        name_match = NAME_TOKEN_PATTERN.match(text, position)
        if name_match:
            body.append(next(name_raw))
            position = name_match.end()
            continue
        character = text[position]
        if character not in mapping:
            raise ValueError(
                f"{entry['entry_id']}: unmapped character {character!r}"
            )
        body.append(mapping[character])
        position += 1

    encoded = struct.pack(
        f"<{len(leading) + len(body) + len(trailing)}H",
        *leading,
        *body,
        *trailing,
    )
    source_raw = bytes.fromhex(entry["original"]["raw_hex"])
    if len(encoded) > len(source_raw):
        raise ValueError(
            f"{entry['entry_id']}: encoded stream is "
            f"{len(encoded) - len(source_raw)} bytes too large"
        )
    replacement = encoded + source_raw[len(encoded) :]
    report = {
        "id": entry["entry_id"],
        "classification": entry["classification"],
        "source_file_offset": entry["source"]["file_offset"],
        "source_bytes": len(source_raw),
        "encoded_stream_bytes": len(encoded),
        "unused_tail_bytes": len(source_raw) - len(encoded),
        "line_widths": line_widths,
        "stored_positions": stored_position_count(text),
        "stored_capacity_positions": editable_position_capacity(entry),
        "dynamic_name_token_count": len(name_controls),
        "fixed_slot_preserved": True,
    }
    return replacement, report


def build_special_screen_patch(
    *,
    file_build_dir: Path,
    workset_path: Path,
    translation_path: Path,
    original_glyph_map_path: Path,
    font_profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    output_status = _base_status_with_special_screen(
        str(base_manifest.get("status"))
    )

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
    entries, _entries_by_id, translations_by_id, validation = (
        validate_special_screen_artifacts(
            workset,
            translation,
            workset_path=workset_path,
            source_allbin=source_allbin,
        )
    )
    required = special_required_characters(translations_by_id.values())
    base_mapping = load_built_primary_mapping(built_map_path)
    patched_start, mapping, font_report, start_allowed = extend_primary_font(
        input_start,
        source_start,
        base_mapping,
        required,
        original_glyph_map_path=original_glyph_map_path,
        font_profile_path=font_profile_path,
    )

    patched_allbin = bytearray(input_allbin)
    entry_reports: list[dict[str, Any]] = []
    allbin_allowed: list[tuple[int, int]] = []
    unit_counts: Counter[int] = Counter()
    unit_encoded_bytes: defaultdict[int, int] = defaultdict(int)
    for entry in entries:
        entry_id = str(entry["entry_id"])
        source_offset = int(entry["source"]["file_offset"], 16)
        source_raw = bytes.fromhex(entry["original"]["raw_hex"])
        if (
            bytes(
                patched_allbin[
                    source_offset : source_offset + len(source_raw)
                ]
            )
            != source_raw
        ):
            raise ValueError(
                f"{entry_id}: base build already changed the special slot"
            )
        replacement, report = encode_special_entry(
            entry,
            translations_by_id[entry_id],
            mapping,
        )
        patched_allbin[
            source_offset : source_offset + len(replacement)
        ] = replacement
        if (
            bytes(
                patched_allbin[
                    source_offset : source_offset + len(replacement)
                ]
            )
            != replacement
        ):
            raise ValueError(f"{entry_id}: write-back verification failed")
        allbin_allowed.append(
            (source_offset, source_offset + len(source_raw))
        )
        entry_reports.append(
            {
                **report,
                "replacement_sha256": sha256_bytes(replacement),
            }
        )
        unit = int(entry["source"]["unit_index"])
        unit_counts[unit] += 1
        unit_encoded_bytes[unit] += int(report["encoded_stream_bytes"])

    start_expected = verify_expected_writes(
        input_start,
        patched_start,
        allowed_ranges=start_allowed,
        owner="primary special-screen Korean glyph extension",
    )
    allbin_expected = verify_expected_writes(
        input_allbin,
        bytes(patched_allbin),
        allowed_ranges=allbin_allowed,
        owner="u38/u43 fixed-slot Korean font text",
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

    output_map = output_dir / built_map_path.name
    write_json(
        output_map,
        {
            "schema_version": 1,
            "status": "nonrelease-all-known-font-corpus-static-map",
            "mapping": {
                character: f"0x{index:03X}"
                for character, index in sorted(
                    mapping.items(), key=lambda item: item[1]
                )
            },
            "special_screen_extension": font_report,
        },
    )

    manifest = {
        **base_manifest,
        "status": output_status,
        "sources": {
            **base_manifest["sources"],
            "base_file_build_manifest": {
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
            "original_glyph_map": {
                "path": str(original_glyph_map_path.resolve()),
                "sha256": sha256_file(original_glyph_map_path),
            },
            "font_profile": {
                "path": str(font_profile_path.resolve()),
                "sha256": sha256_file(font_profile_path),
            },
        },
        "font_scope": (
            "all-known-nongraphic-font-text-including-u38-u43"
        ),
        "special_screen": {
            "status": "statically-injected-runtime-validation-required",
            "release_eligible": False,
            "baseline_id": EXPECTED_BASELINE_ID,
            "entry_count": len(entries),
            "unit_entry_counts": {
                f"u{unit:02d}": count
                for unit, count in sorted(unit_counts.items())
            },
            "unit_encoded_stream_bytes": {
                f"u{unit:02d}": count
                for unit, count in sorted(unit_encoded_bytes.items())
            },
            "fixed_slot_overflow_count": 0,
            "layout_issue_count": 0,
            "dynamic_name_tokens_stored_as_one_u16": True,
            "validation": validation,
            "font": font_report,
            "entries": entry_reports,
            "excluded": [
                "baked graphical buttons",
                "baked graphical labels and title assets",
            ],
            "runtime_review": [
                "play all four mini-games and inspect their rules/results",
                "inspect Course Information dialogue for all course states",
                "inspect tire, strategy, wing, and boost setting dialogue",
                "confirm dynamic player-name tokens render at the expected points",
            ],
        },
        "expected_writes": {
            **base_manifest.get("expected_writes", {}),
            "special_screen": {
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
            "work/translations/disc1-special-screen-text.json"
        ),
    )
    parser.add_argument(
        "--translation",
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
    manifest = build_special_screen_patch(
        file_build_dir=args.file_build_dir,
        workset_path=args.workset,
        translation_path=args.translation,
        original_glyph_map_path=args.glyph_map,
        font_profile_path=args.font_profile,
        output_dir=args.output_dir,
    )
    special = manifest["special_screen"]
    font = special["font"]
    print(
        f"entries={special['entry_count']} "
        f"units={special['unit_entry_counts']} "
        f"required_glyphs={font['special_required_character_count']} "
        f"added_glyphs={font['added_character_count']} "
        f"unused_slots={font['unused_slot_count']} "
        f"START={manifest['outputs']['START.BIN']['sha256']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
