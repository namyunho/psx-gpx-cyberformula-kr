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
    from scripts.korean_font import load_font_profile
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
    from korean_font import load_font_profile
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
OUTSIDE_DISC_SHA256 = "26dd2ef3b83be0908572845d3e451b98f9ac33d488b8b1772199891a216fe640"
OUTSIDE_SAVE_TEXTURE_PAYLOAD = 0x36694
# The upload header width is 256 VRAM halfwords.  At 4bpp each halfword holds
# four pixels, so the stored row is 1,024 pixels / 512 bytes wide.
OUTSIDE_SAVE_TEXTURE_WIDTH = 1024
SAVE_BUTTON_LABELS = (
    ("yes", "예", 0, 232, 40, 16),
    ("no", "아니오", 40, 232, 40, 16),
)
SAVE_RENDER_POINTER_PATCHES = (
    (0x8003D670, 0x24841070, 0x2484F320),
    (0x8003DAC0, 0x24841070, 0x2484F320),
)
STATIC_CODE_POINTER_PATCHES = (
    (0x80039ED4, (0x3C028004, 0x00641021), 0x3C028005),
    (0x80039ED8, (0x3442F35C, 0xACC20000), 0x34421070),
    (0x80039F04, (0x3C028004, 0x24030036), 0x3C028005),
    (0x80039F08, (0x3442F364, 0x00C31021), 0x34421078),
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
    expected: int | tuple[int, ...],
    replacement: int,
) -> tuple[int, int]:
    offset = slps_address_to_file_offset(address)
    actual = struct.unpack_from("<I", data, offset)[0]
    expected_values = expected if isinstance(expected, tuple) else (expected,)
    if actual not in expected_values:
        raise ValueError(
            f"SLPS instruction differs at 0x{address:08X}: "
            f"0x{actual:08X} not in "
            f"{[f'0x{value:08X}' for value in expected_values]}"
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
        words.extend(range(base + 4, base + 8))
    words.extend((0xFFFB, 0xFFFF))
    expected_words = (SPEAKER_FREE_TAIL_END - SPEAKER_FREE_TAIL_START) // 2
    if len(words) > expected_words:
        raise AssertionError("save given-name stream exceeds the verified speaker tail")
    words.extend([0] * (expected_words - len(words)))
    return words


def _outside_4bpp_offset(x: int, y: int) -> tuple[int, bool]:
    if x < 0 or y < 0 or x >= OUTSIDE_SAVE_TEXTURE_WIDTH:
        raise ValueError(f"OUTSIDE 4bpp coordinate is outside the surface: {x},{y}")
    offset = OUTSIDE_SAVE_TEXTURE_PAYLOAD + y * (OUTSIDE_SAVE_TEXTURE_WIDTH // 2) + x // 2
    return offset, bool(x & 1)


def _get_outside_4bpp_pixel(data: bytes | bytearray, x: int, y: int) -> int:
    offset, high = _outside_4bpp_offset(x, y)
    return (data[offset] >> (4 if high else 0)) & 0x0F


def _set_outside_4bpp_pixel(data: bytearray, x: int, y: int, value: int) -> None:
    if not 0 <= value <= 0x0F:
        raise ValueError("4bpp palette index must be in 0..15")
    offset, high = _outside_4bpp_offset(x, y)
    mask = 0x0F if high else 0xF0
    data[offset] = (data[offset] & mask) | (value << (4 if high else 0))


def patch_save_button_labels(
    input_outside: bytes,
    source_outside: bytes,
    *,
    font_profile_path: Path,
) -> tuple[bytes, dict[str, Any], list[tuple[int, int]]]:
    """Replace only the two proven 40x16 label sprites in OUTSIDE unit 1 child 4."""
    if sha256_bytes(source_outside) != OUTSIDE_DISC_SHA256:
        raise ValueError("original OUTSIDE.BIN hash differs")
    if len(input_outside) != len(source_outside):
        raise ValueError("base and original OUTSIDE.BIN sizes differ")

    profile = load_font_profile(font_profile_path)
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    patched = bytearray(input_outside)
    allowed: list[tuple[int, int]] = []
    reports: list[dict[str, Any]] = []

    for label_id, text, x, y, width, height in SAVE_BUTTON_LABELS:
        for row in range(y, y + height):
            start, _ = _outside_4bpp_offset(x, row)
            end, _ = _outside_4bpp_offset(x + width - 1, row)
            if input_outside[start : end + 1] != source_outside[start : end + 1]:
                raise ValueError(f"{label_id} label sprite already differs from original")
            allowed.append((start, end + 1))

        mask = Image.new("1", (width, height))
        bounds = font.getbbox(text)
        ink_width = bounds[2] - bounds[0]
        ink_height = bounds[3] - bounds[1]
        text_x = (width - ink_width) // 2 - bounds[0]
        text_y = (height - ink_height) // 2 - bounds[1]
        ImageDraw.Draw(mask).text((text_x, text_y), text, font=font, fill=1)
        pixels = [1 if value else 0 for value in mask.get_flattened_data()]

        for py in range(height):
            for px in range(width):
                _set_outside_4bpp_pixel(patched, x + px, y + py, 0)
        # The existing state-specific CLUT maps index 1 to white and index 8
        # to a dark red/yellow shade.  Draw shadow first, then the white face.
        for py in range(height):
            for px in range(width):
                if pixels[py * width + px] and px + 1 < width and py + 1 < height:
                    _set_outside_4bpp_pixel(patched, x + px + 1, y + py + 1, 8)
        for py in range(height):
            for px in range(width):
                if pixels[py * width + px]:
                    _set_outside_4bpp_pixel(patched, x + px, y + py, 1)

        reports.append(
            {
                "id": label_id,
                "text": text,
                "texture_rect_pixels": [x, y, width, height],
                "main_palette_index": 1,
                "shadow_palette_index": 8,
                "centered_ink_size": [ink_width, ink_height],
            }
        )

    return bytes(patched), {
        "storage": (
            "OUTSIDE.BIN unit 1 child 4, payload +0x36694; "
            "256 VRAM halfwords = 1024 4bpp pixels per row"
        ),
        "runtime": "VRAM x=512..531, y=232..247; 4bpp tpage 0x0008",
        "labels": reports,
        "palette_and_background_preserved": True,
    }, allowed


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
    prepared_codes = struct.unpack_from("<8H", tail, 60)
    if tail[:60] != bytes(60) or prepared_codes not in (
        (0,) * len(STATIC_NAME_CODES),
        STATIC_NAME_CODES,
    ):
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
        "save_name_layout": "four slots, given name only (4 glyphs)",
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
    source_outside_path: Path,
    font_profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    input_allbin = (file_build_dir / "ALLBIN.BIN").read_bytes()
    input_slps = (file_build_dir / "SLPS_019.58").read_bytes()
    input_outside = (file_build_dir / "OUTSIDE.BIN").read_bytes()
    for name, payload in (
        ("ALLBIN.BIN", input_allbin),
        ("SLPS_019.58", input_slps),
        ("OUTSIDE.BIN", input_outside),
    ):
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
        owner="save-slot Korean metadata and given-name-only renderer",
    )
    source_outside = source_outside_path.read_bytes()
    patched_outside, button_report, outside_allowed = patch_save_button_labels(
        input_outside,
        source_outside,
        font_profile_path=font_profile_path,
    )
    outside_expected = verify_expected_writes(
        input_outside,
        patched_outside,
        allowed_ranges=outside_allowed,
        owner="save confirmation yes/no label sprites",
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
            else patched_outside if name == "OUTSIDE.BIN"
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
            "save_screen_original_outside": {
                "path": str(source_outside_path.resolve()),
                "sha256": sha256_file(source_outside_path),
            },
            "save_screen_font_profile": {
                "path": str(font_profile_path.resolve()),
                "sha256": sha256_file(font_profile_path),
            },
        },
        "save_screen": {
            "status": "static-fix-complete-runtime-validation-required",
            "u39": u39_report,
            "metadata": metadata_report,
            "confirmation_buttons": button_report,
            "artifact_validation": validation,
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "save_screen": {
                "ALLBIN.BIN_relative_to_base_build": allbin_expected,
                "SLPS_019.58_relative_to_base_build": slps_expected,
                "OUTSIDE.BIN_relative_to_base_build": outside_expected,
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
    parser.add_argument("--source-outside", type=Path, default=Path("work/extracted/disc1/iso/OUTSIDE.BIN"))
    parser.add_argument("--font-profile", type=Path, default=Path("config/font-profile.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_save_screen_patch(
        file_build_dir=args.file_build_dir,
        workset_path=args.workset,
        translation_path=args.translation,
        source_allbin_path=args.source_allbin,
        source_outside_path=args.source_outside,
        font_profile_path=args.font_profile,
        output_dir=args.output_dir,
    )
    print(
        f"save_messages={manifest['save_screen']['u39']['entry_count']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']} "
        f"SLPS={manifest['outputs']['SLPS_019.58']['sha256']}"
        f" OUTSIDE={manifest['outputs']['OUTSIDE.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
