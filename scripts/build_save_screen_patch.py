#!/usr/bin/env python3
"""Fix Disc 1 save messages and runtime-generated save-slot metadata."""

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
    from scripts.build_unindexed_font_patch import _pack_u39_save_stream
    from scripts.unindexed_font_common import validate_unindexed_artifacts
except ModuleNotFoundError:
    from build_character_name_patch import load_built_primary_mapping
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from build_unindexed_font_patch import _pack_u39_save_stream
    from unindexed_font_common import validate_unindexed_artifacts


SLPS_LOAD_ADDRESS = 0x80030000
SLPS_PAYLOAD_FILE_OFFSET = 0x800
SAVE_METADATA_START = 0x21800
SAVE_METADATA_END = 0x21870
OLD_SAVE_NAME_STREAM_START = 0x21870
OLD_SAVE_NAME_STREAM_END = 0x218B4
SPEAKER_FREE_TAIL_START = 0x1FB20
SPEAKER_FREE_TAIL_END = 0x1FB6C
STATIC_NAME_CODES = tuple(range(0x4CE, 0x4D6))
SAVE_CACHE_CODE_BASES = (0x4D6, 0x4DE, 0x4E6, 0x4EE)
SAVE_RENDER_POINTER_PATCHES = (
    (0x8003D670, 0x24841070, 0x2484F320),
    (0x8003DAC0, 0x24841070, 0x2484F320),
)
STATIC_CODE_POINTER_PATCHES = (
    (0x80039ED4, 0x3C028004, 0x3C028005),
    (0x80039ED8, 0x3442F35C, 0x34421070),
    (0x80039F04, 0x3C028004, 0x3C028005),
    (0x80039F08, 0x3442F364, 0x34421078),
)


def slps_address_to_file_offset(address: int) -> int:
    return address - SLPS_LOAD_ADDRESS + SLPS_PAYLOAD_FILE_OFFSET


def _encode_text(text: str, mapping: dict[str, int]) -> list[int]:
    missing = sorted({character for character in text if character not in mapping})
    if missing:
        raise ValueError(f"save metadata glyphs are unavailable: {missing}")
    return [mapping[character] for character in text]


def _patch_word(
    data: bytearray,
    *,
    address: int,
    expected: int,
    replacement: int,
) -> tuple[int, int]:
    offset = slps_address_to_file_offset(address)
    actual = struct.unpack_from("<I", data, offset)[0]
    if actual != expected:
        raise ValueError(
            f"SLPS instruction differs at 0x{address:08X}: "
            f"0x{actual:08X} != 0x{expected:08X}"
        )
    struct.pack_into("<I", data, offset, replacement)
    return offset, offset + 4


def _metadata_words(mapping: dict[str, int]) -> list[int]:
    words: list[int] = []
    for text in (
        "전야제", "제1전", "제2전", "제3전",
    ):
        words.extend(_encode_text(text, mapping))
        words.append(0)
    words.extend((0xFFFB, 0))
    for text in ("이동일", "제4전", "제5전", "제6전"):
        words.extend(_encode_text(text, mapping))
        words.append(0)
    words.extend((0xFFFB, 0))
    words.extend(_encode_text("최종전", mapping))
    words.append(0)
    words.extend(_encode_text("클리어", mapping))
    words.extend((0, 0x0004, 0))
    words.extend(_encode_text("낮", mapping))
    words.append(0)
    words.extend(_encode_text("밤", mapping))
    words.extend((0, 0xFFFB))
    words.extend(_encode_text("미사용", mapping))
    words.extend((0xFFFF, 0))
    expected_words = (SAVE_METADATA_END - SAVE_METADATA_START) // 2
    if len(words) != expected_words:
        raise AssertionError(
            f"save metadata word count differs: {len(words)} != {expected_words}"
        )
    return words


def _save_name_words() -> list[int]:
    words: list[int] = []
    for index, base in enumerate(SAVE_CACHE_CODE_BASES):
        words.append(0xFFFD if index == 0 else 0xFFFB)
        words.extend(range(base, base + 4))
        words.extend(range(base + 4, base + 8))
    words.extend((0xFFFB, 0xFFFF))
    expected_words = (SPEAKER_FREE_TAIL_END - SPEAKER_FREE_TAIL_START) // 2
    if len(words) != expected_words:
        raise AssertionError(
            f"save name stream word count differs: {len(words)} != {expected_words}"
        )
    return words


def patch_save_metadata(
    input_slps: bytes,
    mapping: dict[str, int],
) -> tuple[bytes, dict[str, Any], list[tuple[int, int]]]:
    patched = bytearray(input_slps)
    allowed: list[tuple[int, int]] = []

    source_name_stream = bytes(
        patched[OLD_SAVE_NAME_STREAM_START:OLD_SAVE_NAME_STREAM_END]
    )
    if not source_name_stream.startswith(
        bytes.fromhex("FD FF D4 04 D5 04 D6 04")
    ):
        raise ValueError("original 3+3 save-name stream differs")
    tail = bytes(patched[SPEAKER_FREE_TAIL_START:SPEAKER_FREE_TAIL_END])
    if tail[:60] != bytes(60) or struct.unpack_from("<8H", tail, 60) != STATIC_NAME_CODES:
        raise ValueError("verified speaker free tail / static name codes differ")

    metadata = struct.pack(f"<{len(_metadata_words(mapping))}H", *_metadata_words(mapping))
    patched[SAVE_METADATA_START:SAVE_METADATA_END] = metadata
    allowed.append((SAVE_METADATA_START, SAVE_METADATA_END))

    patched[OLD_SAVE_NAME_STREAM_START:OLD_SAVE_NAME_STREAM_END] = bytes(
        OLD_SAVE_NAME_STREAM_END - OLD_SAVE_NAME_STREAM_START
    )
    struct.pack_into(
        "<8H", patched, OLD_SAVE_NAME_STREAM_START, *STATIC_NAME_CODES
    )
    allowed.append((OLD_SAVE_NAME_STREAM_START, OLD_SAVE_NAME_STREAM_END))

    name_words = _save_name_words()
    struct.pack_into(
        f"<{len(name_words)}H", patched, SPEAKER_FREE_TAIL_START, *name_words
    )
    allowed.append((SPEAKER_FREE_TAIL_START, SPEAKER_FREE_TAIL_END))

    for address, expected, replacement in (
        *SAVE_RENDER_POINTER_PATCHES,
        *STATIC_CODE_POINTER_PATCHES,
    ):
        allowed.append(
            _patch_word(
                patched,
                address=address,
                expected=expected,
                replacement=replacement,
            )
        )

    return bytes(patched), {
        "metadata_range": [f"0x{SAVE_METADATA_START:X}", f"0x{SAVE_METADATA_END:X}"],
        "empty_slot_label": "미사용",
        "race_labels": ["전야제", "제1전..제6전", "최종전"],
        "save_name_layout": "four slots, surname 4 + given 4",
        "save_name_stream_address": "0x8004F320",
        "static_live_name_codes_address": "0x80051070",
        "instruction_patch_count": (
            len(SAVE_RENDER_POINTER_PATCHES) + len(STATIC_CODE_POINTER_PATCHES)
        ),
    }, allowed


def build_save_screen_patch(
    *,
    file_build_dir: Path,
    workset_path: Path,
    translation_path: Path,
    source_allbin_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    input_allbin = (file_build_dir / "ALLBIN.BIN").read_bytes()
    input_slps = (file_build_dir / "SLPS_019.58").read_bytes()
    for name, payload in (("ALLBIN.BIN", input_allbin), ("SLPS_019.58", input_slps)):
        if sha256_bytes(payload) != base_manifest["outputs"][name]["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")

    mapping_path = file_build_dir / "primary-korean-glyph-map.json"
    mapping = load_built_primary_mapping(mapping_path)
    source_allbin = source_allbin_path.read_bytes()
    entries, translations, validation = validate_unindexed_artifacts(
        load_object(workset_path),
        load_object(translation_path),
        workset_path=workset_path,
        source_allbin=source_allbin,
        expected_allbin_sha256=sha256_bytes(source_allbin),
    )
    u39 = [entry for entry in entries if int(entry["source"]["unit_index"]) == 39]
    patched_allbin = bytearray(input_allbin)
    u39_report, u39_range = _pack_u39_save_stream(
        patched_allbin=patched_allbin,
        input_allbin=source_allbin,
        entries=u39,
        translation_by_id=translations,
        mapping=mapping,
    )
    allbin_expected = verify_expected_writes(
        input_allbin,
        bytes(patched_allbin),
        allowed_ranges=[u39_range],
        owner="u39 fixed-start save messages",
    )

    patched_slps, metadata_report, slps_allowed = patch_save_metadata(
        input_slps, mapping
    )
    slps_expected = verify_expected_writes(
        input_slps,
        patched_slps,
        allowed_ranges=slps_allowed,
        owner="save-slot Korean metadata and 4+4 name renderer",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, bytes] = {}
    for name in base_manifest["outputs"]:
        if name == "glyph_map":
            continue
        source = file_build_dir / name
        if not source.is_file():
            continue
        payload = (
            bytes(patched_allbin) if name == "ALLBIN.BIN"
            else patched_slps if name == "SLPS_019.58"
            else source.read_bytes()
        )
        (output_dir / name).write_bytes(payload)
        payloads[name] = payload
    output_map = output_dir / mapping_path.name
    shutil.copyfile(mapping_path, output_map)

    manifest = {
        **base_manifest,
        "sources": {
            **base_manifest["sources"],
            "save_screen_base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
            "save_screen_translation": {
                "path": str(translation_path.resolve()),
                "sha256": sha256_file(translation_path),
            },
        },
        "save_screen": {
            "status": "static-fix-complete-runtime-validation-required",
            "u39": u39_report,
            "metadata": metadata_report,
            "artifact_validation": validation,
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "save_screen": {
                "ALLBIN.BIN_relative_to_base_build": allbin_expected,
                "SLPS_019.58_relative_to_base_build": slps_expected,
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
    parser.add_argument("--workset", type=Path, default=Path("work/translations/disc1-unindexed-font-text.json"))
    parser.add_argument("--translation", type=Path, default=Path("data/translations/disc1-unindexed-font-ko.json"))
    parser.add_argument("--source-allbin", type=Path, default=Path("work/extracted/disc1/iso/ALLBIN.BIN"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_save_screen_patch(
        file_build_dir=args.file_build_dir,
        workset_path=args.workset,
        translation_path=args.translation,
        source_allbin_path=args.source_allbin,
        output_dir=args.output_dir,
    )
    print(
        f"save_messages={manifest['save_screen']['u39']['entry_count']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']} "
        f"SLPS={manifest['outputs']['SLPS_019.58']['sha256']}"
    )


if __name__ == "__main__":
    main()
