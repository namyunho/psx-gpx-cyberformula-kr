#!/usr/bin/env python3
"""Patch runtime-confirmed fixed-slot menu literals missed by dialogue extraction."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
import shutil
import struct
from typing import Any

try:
    from scripts.build_character_name_patch import load_built_primary_mapping
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
except ModuleNotFoundError:
    from build_character_name_patch import load_built_primary_mapping
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )


EXPECTED_TRANSLATION_ID = "disc1/allbin/u09/inline_menu/cancel"
INLINE_CANCEL_OFFSET = 0x305F0
INLINE_CANCEL_GLYPH_CAPACITY = 5
ORIGINAL_CANCEL_TOKENS = (0x00A1, 0x00D6, 0x00E2, 0x00AF, 0x00DE)


def load_cancel_translation(path: Path) -> str:
    document = load_object(path)
    entries = document.get("translations")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("inline menu translation population must be exactly one")
    entry = entries[0]
    if entry.get("id") != EXPECTED_TRANSLATION_ID:
        raise ValueError("inline menu translation ID differs")
    if entry.get("jp") != "キャンセル":
        raise ValueError("inline menu protected Japanese text differs")
    if int(entry.get("visible_glyph_capacity", -1)) != INLINE_CANCEL_GLYPH_CAPACITY:
        raise ValueError("inline menu fixed-slot capacity differs")
    text = entry.get("ko")
    if not isinstance(text, str) or not text:
        raise ValueError("inline menu Korean translation is missing")
    return text


def patch_inline_cancel(
    input_allbin: bytes,
    mapping: dict[str, int],
    text: str,
) -> tuple[bytes, dict[str, Any], list[tuple[int, int]]]:
    original = struct.pack("<5H", *ORIGINAL_CANCEL_TOKENS)
    end = INLINE_CANCEL_OFFSET + len(original)
    if input_allbin[INLINE_CANCEL_OFFSET:end] != original:
        raise ValueError("u09 inline cancel source slot differs")
    if len(text) > INLINE_CANCEL_GLYPH_CAPACITY:
        raise ValueError("u09 inline cancel translation exceeds five glyphs")
    missing = sorted({character for character in text if character not in mapping})
    if missing:
        raise ValueError(f"u09 inline cancel glyphs are unavailable: {missing}")

    tokens = [mapping[character] for character in text]
    tokens.extend([0x0000] * (INLINE_CANCEL_GLYPH_CAPACITY - len(tokens)))
    patched = bytearray(input_allbin)
    struct.pack_into("<5H", patched, INLINE_CANCEL_OFFSET, *tokens)
    return bytes(patched), {
        "entry_id": EXPECTED_TRANSLATION_ID,
        "unit": 9,
        "unit_offset": "0x5DF0",
        "file_offset": f"0x{INLINE_CANCEL_OFFSET:X}",
        "source": "キャンセル",
        "translation": text,
        "slot_glyphs": INLINE_CANCEL_GLYPH_CAPACITY,
        "padding_glyphs": INLINE_CANCEL_GLYPH_CAPACITY - len(text),
        "surrounding_controls_preserved": True,
    }, [(INLINE_CANCEL_OFFSET, end)]


def build_inline_menu_patch(
    *,
    file_build_dir: Path,
    translation_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    input_allbin = (file_build_dir / "ALLBIN.BIN").read_bytes()
    if sha256_bytes(input_allbin) != base_manifest["outputs"]["ALLBIN.BIN"]["sha256"]:
        raise ValueError("ALLBIN.BIN base file-build hash differs")

    mapping_path = file_build_dir / "primary-korean-glyph-map.json"
    mapping = load_built_primary_mapping(mapping_path)
    text = load_cancel_translation(translation_path)
    patched_allbin, report, allowed = patch_inline_cancel(input_allbin, mapping, text)
    expected = verify_expected_writes(
        input_allbin,
        patched_allbin,
        allowed_ranges=allowed,
        owner="u09 runtime-confirmed inline cancel menu",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, bytes] = {}
    for name in base_manifest["outputs"]:
        if name == "glyph_map":
            continue
        source = file_build_dir / name
        if not source.is_file():
            continue
        payload = patched_allbin if name == "ALLBIN.BIN" else source.read_bytes()
        (output_dir / name).write_bytes(payload)
        payloads[name] = payload
    output_map = output_dir / mapping_path.name
    shutil.copyfile(mapping_path, output_map)

    manifest = {
        **base_manifest,
        "sources": {
            **base_manifest["sources"],
            "inline_menu_base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
            "inline_menu_translation": {
                "path": str(translation_path.resolve()),
                "sha256": sha256_file(translation_path),
            },
        },
        "inline_menu": {
            "status": "static-complete-runtime-validation-required",
            "entries": [report],
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "inline_menu": {
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
                for name, payload in payloads.items()
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
        "--translation",
        type=Path,
        default=Path("data/translations/disc1-inline-menu-ko.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_inline_menu_patch(
        file_build_dir=args.file_build_dir,
        translation_path=args.translation,
        output_dir=args.output_dir,
    )
    print(
        f"inline_menus={len(manifest['inline_menu']['entries'])} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
