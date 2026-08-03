#!/usr/bin/env python3
"""Expand the player-name bitmap path from six glyphs to a 4+4 PoC."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from typing import Any, Iterable

try:
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.psx_font import GLYPH_SIZE
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import verify_expected_writes
    from psx_font import GLYPH_SIZE


SLPS_LOAD_ADDRESS = 0x80030000
SLPS_PAYLOAD_FILE_OFFSET = 0x800

ALLBIN_UNIT_OFFSETS = {
    35: 0x0E6000,
    39: 0x14B000,
    40: 0x151800,
}
ALLBIN_UNIT_LOAD_ADDRESSES = {
    35: 0x8006D000,
    39: 0x80098000,
    40: 0x80098000,
}

NAME_GLYPH_COUNT = 8
NAME_BITMAP_BYTES = NAME_GLYPH_COUNT * GLYPH_SIZE
NAME_BITMAP_DWORDS = NAME_BITMAP_BYTES // 4
NAME_BITMAP_FORWARD_LIMIT = NAME_BITMAP_DWORDS
NAME_BITMAP_BACKWARD_INITIAL = NAME_BITMAP_DWORDS - 1
DYNAMIC_NAME_WIDTHS = {
    "{name:surname}": 4,
    "{name:given}": 4,
}

LIVE_NAME_BUFFER = 0x8002AD8C
GIVEN_NAME_BUFFER_4X4 = LIVE_NAME_BUFFER + 4 * GLYPH_SIZE
LIVE_NAME_END = LIVE_NAME_BUFFER + NAME_BITMAP_BYTES

CACHE_BASES_4X4 = (
    LIVE_NAME_END,
    LIVE_NAME_END + NAME_BITMAP_BYTES,
    LIVE_NAME_END + 2 * NAME_BITMAP_BYTES,
    LIVE_NAME_END + 3 * NAME_BITMAP_BYTES,
)
CACHE_ENDS_INCLUSIVE_4X4 = tuple(
    base + NAME_BITMAP_BYTES - 4 for base in CACHE_BASES_4X4
)
CACHE_REGION_END = CACHE_BASES_4X4[-1] + NAME_BITMAP_BYTES

SAVE_SLOT_STRIDE = 0x700
SAVE_NAME_BASE_4X4 = 0x801F07B0
SAVE_NAME_BASES_4X4 = tuple(
    SAVE_NAME_BASE_4X4 + index * SAVE_SLOT_STRIDE for index in range(4)
)
SAVE_SLOT_HEADER_BASES = tuple(
    0x801F0300 + index * SAVE_SLOT_STRIDE for index in range(4)
)
SAVE_SLOT_NEXT_HEADER_BASES = tuple(
    base + SAVE_SLOT_STRIDE for base in SAVE_SLOT_HEADER_BASES
)

STATIC_NAME_CODE_FILE_OFFSET = 0x1FB5C
STATIC_SURNAME_CODE_ADDRESS = 0x8004F35C
STATIC_GIVEN_CODE_ADDRESS = 0x8004F364
STATIC_NAME_CODES = tuple(range(0x4CE, 0x4D6))

# The final 16 bytes of the verified 76-byte free tail in the repacked
# speaker-label string region. The speaker record table begins at 0x1FB6C.
STATIC_NAME_CODE_END_FILE_OFFSET = 0x1FB6C

UNIT40_GIVEN_POINTER_ORI_ADDRESSES = tuple(
    address + 4
    for address in (
        0x800992C0,
        0x80099474,
        0x800995B8,
        0x80099890,
        0x80099AAC,
        0x8009A434,
        0x8009AC78,
        0x8009AE40,
    )
)

# Edits are relative to the already verified 2+4 build.
UNIT40_IMMEDIATE_PATCHES = (
    (0x8009942C, 0x0002, 0x0004),
    (0x80099438, 0x0003, 0x000F),
    (0x8009957C, 0x0002, 0x0004),
    (0x80099590, 0x0002, 0x0004),
    (0x80099634, 0x0002, 0x0004),
    (0x80099760, 0x0002, 0x0004),
    (0x8009997C, 0x0002, 0x0004),
    (0x8009A2EC, 0x0002, 0x0004),
    (0x8009AB4C, 0x0002, 0x0004),
    (0x8009AB54, 0x0001, 0x0003),
    (0x8009AB70, 0x004A, 0x00DE),
    (0x8009ABC4, 0x0002, 0x0004),
    (0x8009AC14, 0x0002, 0x0004),
    (0x8009AC2C, 0x0002, 0x0004),
    (0x8009AC8C, 0xAE6A, 0xAEFE),
)

UNIT40_NAME_DISPLAY_STREAM_PATCHES = (
    (
        0x8009F960,
        bytes.fromhex("FD FF CE 04 CF 04 D0 04 FF FF 00 00"),
        bytes.fromhex("FD FF CE 04 CF 04 D0 04 D1 04 FF FF"),
    ),
    (
        0x8009F96C,
        bytes.fromhex("FD FF D1 04 D2 04 D3 04 FF FF 00 00"),
        bytes.fromhex("FD FF D2 04 D3 04 D4 04 D5 04 FF FF"),
    ),
)

UNIT40_TRANSLATED_ORIGIN_UI_STREAMS = (
    (
        "disc1/allbin/u40/font_rendered_ui/e047",
        0x8009F610,
        114,
    ),
    (
        "disc1/allbin/u40/font_rendered_ui/e048",
        0x8009F684,
        26,
    ),
    (
        "disc1/allbin/u40/font_rendered_ui/e055",
        0x8009F920,
        22,
    ),
    (
        "disc1/allbin/u40/font_rendered_ui/e056",
        0x8009F938,
        38,
    ),
)

UNIT40_SIZE = 0x1D000
UNIT40_INPUT_FORM_ASM = (
    Path(__file__).resolve().parent / "asm" / "name_input_4x4_form.asm"
)
UNIT40_INPUT_FORM_HELPER_START = 0x800A09BC
UNIT40_INPUT_FORM_HELPER_END = 0x800A0B90
UNIT40_INPUT_FORM_SOURCE_WORDS = (
    (
        0x80098370,
        (0x24020003,),
    ),
    (
        0x8009A574,
        (0x3C028006,),
    ),
    (
        0x8009B594,
        (0x2403008F, 0xA4432080, 0xA4432100),
    ),
    (
        0x8009C138,
        (0x2403008F, 0xA4432080, 0xA4432100),
    ),
    (
        0x8009B68C,
        (
            0x8E041214,
            0x0C00E2F9,
            0x24842080,
            0x8E041214,
            0x0C00E2F9,
            0x24842100,
            0x08026DF7,
            0x3C028006,
        ),
    ),
    (
        0x8009D1A8,
        (0x3C028006, 0x94421024),
    ),
    (
        0x8009DCDC,
        (
            0x94421024,
            0x24630954,
            0x2442FFD0,
            0x00021040,
            0x00431021,
        ),
    ),
)
UNIT40_INPUT_FORM_FRAME_SOURCES = (
    (
        0x8009E92C,
        bytes.fromhex("1C 00 40 7F 00 80 2C 10 14 00 08 00"),
    ),
    (
        0x8009E938,
        bytes.fromhex("1C 00 40 7F 00 90 2C 10 4C 00 08 00"),
    ),
    (
        0x8009E98C,
        bytes.fromhex("1C 00 40 7F 00 80 2C 10 14 00 08 00"),
    ),
    (
        0x8009E998,
        bytes.fromhex("1C 00 40 7F 00 90 2C 10 4C 00 08 00"),
    ),
    (
        0x8009E9EC,
        bytes.fromhex("1C 00 40 7F 00 80 2C 10 14 00 08 00"),
    ),
    (
        0x8009E9F8,
        bytes.fromhex("1C 00 40 7F 00 90 2C 10 4C 00 08 00"),
    ),
    (
        0x8009EA1C,
        bytes.fromhex(
            "1C 00 40 7F 00 80 2C 10 18 00 08 00 "
            "FF FF 00 00 00 00 00 00 00 00 00 00"
        ),
    ),
    (
        0x8009EA34,
        bytes.fromhex(
            "1C 00 40 7F 00 90 2C 10 50 00 08 00 "
            "FF FF 00 00 00 00 00 00 00 00 00 00"
        ),
    ),
)
UNIT40_INPUT_FORM_ALLOWED_ADDRESS_RANGES = (
    (0x80098370, 0x80098374),
    (0x8009A574, 0x8009A578),
    (0x8009B594, 0x8009B5A0),
    (0x8009C138, 0x8009C144),
    (0x8009B68C, 0x8009B6AC),
    (0x8009D1A8, 0x8009D1B0),
    (0x8009DCDC, 0x8009DCF0),
    (0x8009E932, 0x8009E933),
    (0x8009E934, 0x8009E936),
    (0x8009E93E, 0x8009E93F),
    (0x8009E940, 0x8009E942),
    (0x8009E992, 0x8009E993),
    (0x8009E994, 0x8009E996),
    (0x8009E99E, 0x8009E99F),
    (0x8009E9A0, 0x8009E9A2),
    (0x8009E9F2, 0x8009E9F3),
    (0x8009E9F4, 0x8009E9F6),
    (0x8009E9FE, 0x8009E9FF),
    (0x8009EA00, 0x8009EA02),
    (0x8009EA22, 0x8009EA23),
    (0x8009EA24, 0x8009EA26),
    (0x8009EA3A, 0x8009EA3B),
    (0x8009EA3C, 0x8009EA3E),
    (UNIT40_INPUT_FORM_HELPER_START, UNIT40_INPUT_FORM_HELPER_END),
)

UNIT35_FORWARD_LIMIT_ADDRESSES = (0x8006E0D0,)
UNIT35_SAVE_POINTER_TABLE_ADDRESS = 0x80087814
UNIT35_ORIGINAL_SAVE_POINTERS = (
    0x801F0800,
    0x801F0F00,
    0x801F1600,
    0x801F1D00,
)

UNIT39_FORWARD_LIMIT_ADDRESSES = (
    0x800991DC,
    0x8009920C,
    0x8009923C,
    0x8009926C,
    0x8009929C,
    0x800993E0,
    0x80099410,
    0x80099440,
    0x80099470,
    0x800994A0,
    0x800999B8,
    0x800999E8,
    0x80099A18,
    0x80099A48,
    0x8009A6B4,
    0x8009A6E4,
    0x8009A714,
    0x8009A744,
    0x8009A9E8,
)

UNIT39_CACHE_BASE_ORI_PATCHES = tuple(
    zip(
        (
            0x800991F0,
            0x80099220,
            0x80099250,
            0x80099280,
            0x800993F4,
            0x80099424,
            0x80099454,
            0x80099484,
            0x8009999C,
            0x800999CC,
            0x800999FC,
            0x80099A2C,
            0x8009A698,
            0x8009A6C8,
            0x8009A6F8,
            0x8009A728,
        ),
        (
            0xAF48,
            0xB104,
            0xB2C0,
            0xB47C,
        )
        * 4,
        tuple(address & 0xFFFF for address in CACHE_BASES_4X4) * 4,
    )
)

UNIT39_SAVE_BASE_ORI_PATCHES = tuple(
    zip(
        (
            0x800991A8,
            0x800991F8,
            0x80099228,
            0x80099258,
            0x80099288,
            0x80099388,
            0x800993FC,
            0x8009942C,
            0x8009945C,
            0x8009948C,
            0x800999A4,
            0x800999D4,
            0x80099A04,
            0x80099A34,
            0x8009A6A0,
            0x8009A6D0,
            0x8009A700,
            0x8009A730,
            0x8009A9B4,
        ),
        (
            0x0800,
            0x0800,
            0x0F00,
            0x1600,
            0x1D00,
            0x0800,
            0x0800,
            0x0F00,
            0x1600,
            0x1D00,
            0x0800,
            0x0F00,
            0x1600,
            0x1D00,
            0x0800,
            0x0F00,
            0x1600,
            0x1D00,
            0x0800,
        ),
        (
            0x07B0,
            0x07B0,
            0x0EB0,
            0x15B0,
            0x1CB0,
            0x07B0,
            0x07B0,
            0x0EB0,
            0x15B0,
            0x1CB0,
            0x07B0,
            0x0EB0,
            0x15B0,
            0x1CB0,
            0x07B0,
            0x0EB0,
            0x15B0,
            0x1CB0,
            0x07B0,
        ),
    )
)

UNIT39_CACHE_CLEAR_PATCHES = tuple(
    zip(
        (
            0x80098DFC,
            0x80098E18,
            0x80098E34,
            0x80098E50,
            0x8009A3D0,
            0x8009A3EC,
            0x8009A408,
            0x8009A424,
        ),
        (
            0x80098E04,
            0x80098E20,
            0x80098E3C,
            0x80098E58,
            0x8009A3D8,
            0x8009A3F4,
            0x8009A410,
            0x8009A42C,
        ),
        (
            0xB100,
            0xB2BC,
            0xB478,
            0xB634,
        )
        * 2,
        tuple(address & 0xFFFF for address in CACHE_ENDS_INCLUSIVE_4X4) * 2,
    )
)

SLPS_SURNAME_POINTER_BLOCK = (
    (0x80039ED4, 0x00641021, 0x3C028004),
    (0x80039ED8, 0xACC20000, 0x3442F35C),
    (0x80039EDC, 0x24C60004, 0xACC20000),
    (0x80039EE0, 0x24A50001, 0x00000000),
    (0x80039EE4, 0x28A20003, 0x00000000),
    (0x80039EE8, 0x1440FFFA, 0x00000000),
    (0x80039EEC, 0x24840002, 0x00000000),
)

SLPS_GIVEN_POINTER_BLOCK = (
    (0x80039F04, 0x24030036, 0x3C028004),
    (0x80039F08, 0x00C31021, 0x3442F364),
    (0x80039F0C, 0xAC820000, 0xAC820000),
    (0x80039F10, 0x24840004, 0x00000000),
    (0x80039F14, 0x24A50001, 0x00000000),
    (0x80039F18, 0x28A20003, 0x00000000),
    (0x80039F1C, 0x1440FFFA, 0x00000000),
    (0x80039F20, 0x24630002, 0x00000000),
)

SLPS_NAME_CODE_WRITE_NOPS = (
    (0x8003A6C0, 0xA4400000),
    (0x8003A6E8, 0xA4400000),
    (0x8003A8F0, 0xA4820000),
    (0x8003A8FC, 0xA4820002),
    (0x8003A908, 0xA4620004),
    (0x8003A918, 0xA4820002),
    (0x8003A924, 0xA4820004),
    (0x8003A938, 0xA4620006),
)

SLPS_CACHE_CLEAR_PATCHES = tuple(
    zip(
        (
            0x8003D5DC,
            0x8003D614,
            0x8003D630,
            0x8003D64C,
            0x8003DA2C,
            0x8003DA64,
            0x8003DA80,
            0x8003DA9C,
        ),
        (
            0x8003D5EC,
            0x8003D61C,
            0x8003D638,
            0x8003D654,
            0x8003DA3C,
            0x8003DA6C,
            0x8003DA88,
            0x8003DAA4,
        ),
        (
            0xB100,
            0xB2BC,
            0xB478,
            0xB634,
        )
        * 2,
        tuple(address & 0xFFFF for address in CACHE_ENDS_INCLUSIVE_4X4) * 2,
    )
)

SLPS_LIVE_NAME_CLEAR_LIMIT_ADDRESS = 0x8003E9A0
SLPS_ROMAN_POINTER_BLOCK = (0x80039F24, 0x80039F58)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def slps_address_to_file_offset(address: int) -> int:
    return address - SLPS_LOAD_ADDRESS + SLPS_PAYLOAD_FILE_OFFSET


def unit_address_to_allbin_offset(unit: int, address: int) -> int:
    return (
        ALLBIN_UNIT_OFFSETS[unit]
        + address
        - ALLBIN_UNIT_LOAD_ADDRESSES[unit]
    )


def _patch_word(
    data: bytearray,
    *,
    file_offset: int,
    expected: int,
    replacement: int,
    owner: str,
) -> None:
    actual = struct.unpack_from("<I", data, file_offset)[0]
    if actual != expected:
        raise ValueError(
            f"{owner}: word differs at 0x{file_offset:X}: "
            f"0x{actual:08X} != 0x{expected:08X}"
        )
    struct.pack_into("<I", data, file_offset, replacement)


def _patch_immediate(
    data: bytearray,
    *,
    file_offset: int,
    expected: int,
    replacement: int,
    owner: str,
) -> None:
    word = struct.unpack_from("<I", data, file_offset)[0]
    if word & 0xFFFF != expected:
        raise ValueError(
            f"{owner}: immediate differs at 0x{file_offset:X}: "
            f"0x{word & 0xFFFF:04X} != 0x{expected:04X}"
        )
    struct.pack_into(
        "<I",
        data,
        file_offset,
        (word & 0xFFFF0000) | replacement,
    )


def _append_word_range(ranges: list[tuple[int, int]], offset: int) -> None:
    ranges.append((offset, offset + 4))


def _patch_unit40_input_form_with_armips(
    unit40: bytes,
) -> tuple[bytes, dict[str, Any]]:
    if len(unit40) != UNIT40_SIZE:
        raise ValueError(
            f"unit40 size differs: {len(unit40)} != {UNIT40_SIZE}"
        )

    for address, expected_words in UNIT40_INPUT_FORM_SOURCE_WORDS:
        offset = address - ALLBIN_UNIT_LOAD_ADDRESSES[40]
        actual = struct.unpack_from(
            f"<{len(expected_words)}I",
            unit40,
            offset,
        )
        if actual != expected_words:
            raise ValueError(
                "unit40 input-form source differs at "
                f"0x{address:08X}: {actual!r} != {expected_words!r}"
            )

    for address, expected in UNIT40_INPUT_FORM_FRAME_SOURCES:
        offset = address - ALLBIN_UNIT_LOAD_ADDRESSES[40]
        actual = unit40[offset : offset + len(expected)]
        if actual != expected:
            raise ValueError(
                "unit40 input-form frame differs at "
                f"0x{address:08X}: {actual.hex()} != {expected.hex()}"
            )

    helper_start = (
        UNIT40_INPUT_FORM_HELPER_START - ALLBIN_UNIT_LOAD_ADDRESSES[40]
    )
    helper_end = (
        UNIT40_INPUT_FORM_HELPER_END - ALLBIN_UNIT_LOAD_ADDRESSES[40]
    )
    helper_source = unit40[helper_start:helper_end]
    if helper_source != b"\x00" * len(helper_source):
        raise ValueError("unit40 input-form helper range is not zero")

    armips = shutil.which("armips")
    if armips is None:
        raise RuntimeError("armips is required for the 4+4 input form")
    if not UNIT40_INPUT_FORM_ASM.is_file():
        raise FileNotFoundError(UNIT40_INPUT_FORM_ASM)

    with tempfile.TemporaryDirectory(prefix="cyberformula-name-4x4-") as temp:
        temp_dir = Path(temp)
        overlay_path = temp_dir / "unit40.bin"
        overlay_path.write_bytes(unit40)
        completed = subprocess.run(
            [armips, str(UNIT40_INPUT_FORM_ASM)],
            cwd=temp_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "armips failed for the 4+4 input form:\n"
                f"{completed.stdout}{completed.stderr}"
            )
        patched = overlay_path.read_bytes()

    if len(patched) != len(unit40):
        raise ValueError(
            "armips changed unit40 size: "
            f"{len(patched)} != {len(unit40)}"
        )

    relative_ranges = [
        (
            start - ALLBIN_UNIT_LOAD_ADDRESSES[40],
            end - ALLBIN_UNIT_LOAD_ADDRESSES[40],
        )
        for start, end in UNIT40_INPUT_FORM_ALLOWED_ADDRESS_RANGES
    ]
    expected = verify_expected_writes(
        unit40,
        patched,
        allowed_ranges=relative_ranges,
        owner="unit40 Japanese 4+4 input-form display",
    )
    return patched, {
        "assembler": str(Path(armips).resolve()),
        "assembly_source": str(UNIT40_INPUT_FORM_ASM),
        "helper_start": f"0x{UNIT40_INPUT_FORM_HELPER_START:08X}",
        "helper_end_exclusive": f"0x{UNIT40_INPUT_FORM_HELPER_END:08X}",
        "helper_source_was_zero": True,
        "japanese_slot_count": 8,
        "roman_slot_layout_unchanged": True,
        "input_kind_discriminator": {
            "pointer_address": "0x800611F8",
            "japanese_value": 2,
            "transient_state_16_supported": True,
        },
        "prompt_frame_width_pixels": 58,
        "confirmation_frame_width_pixels": 58,
        "prompt_frame_x_pixels": [13, 77],
        "confirmation_frame_x_pixels": [20, 84],
        "inter_field_gap_pixels": 6,
        "completion_state": 3,
        "reentry_surname_length": 4,
        "glyph_width_pixels": 14,
        "expected_writes": expected,
    }


def _patch_allbin(input_allbin: bytes) -> tuple[bytes, dict[str, Any]]:
    patched = bytearray(input_allbin)
    allowed_ranges: list[tuple[int, int]] = []

    for address in UNIT35_FORWARD_LIMIT_ADDRESSES:
        offset = unit_address_to_allbin_offset(35, address)
        _patch_immediate(
            patched,
            file_offset=offset,
            expected=0x006F,
            replacement=NAME_BITMAP_FORWARD_LIMIT,
            owner="unit35 4+4 live-name save copy",
        )
        _append_word_range(allowed_ranges, offset)

    pointer_offset = unit_address_to_allbin_offset(
        35,
        UNIT35_SAVE_POINTER_TABLE_ADDRESS,
    )
    actual_pointers = struct.unpack_from("<4I", patched, pointer_offset)
    if actual_pointers != UNIT35_ORIGINAL_SAVE_POINTERS:
        raise ValueError(
            "unit35 save-name pointer table differs: "
            f"{actual_pointers!r} != {UNIT35_ORIGINAL_SAVE_POINTERS!r}"
        )
    struct.pack_into("<4I", patched, pointer_offset, *SAVE_NAME_BASES_4X4)
    allowed_ranges.append((pointer_offset, pointer_offset + 16))

    for address in UNIT39_FORWARD_LIMIT_ADDRESSES:
        offset = unit_address_to_allbin_offset(39, address)
        _patch_immediate(
            patched,
            file_offset=offset,
            expected=0x006F,
            replacement=NAME_BITMAP_FORWARD_LIMIT,
            owner="unit39 4+4 name bitmap copy",
        )
        _append_word_range(allowed_ranges, offset)

    for address, expected, replacement in UNIT39_CACHE_BASE_ORI_PATCHES:
        offset = unit_address_to_allbin_offset(39, address)
        _patch_immediate(
            patched,
            file_offset=offset,
            expected=expected,
            replacement=replacement,
            owner="unit39 4+4 name cache base",
        )
        _append_word_range(allowed_ranges, offset)

    for address, expected, replacement in UNIT39_SAVE_BASE_ORI_PATCHES:
        offset = unit_address_to_allbin_offset(39, address)
        _patch_immediate(
            patched,
            file_offset=offset,
            expected=expected,
            replacement=replacement,
            owner="unit39 4+4 save-slot name base",
        )
        _append_word_range(allowed_ranges, offset)

    for (
        count_address,
        end_address,
        expected_end,
        replacement_end,
    ) in UNIT39_CACHE_CLEAR_PATCHES:
        count_offset = unit_address_to_allbin_offset(39, count_address)
        end_offset = unit_address_to_allbin_offset(39, end_address)
        _patch_immediate(
            patched,
            file_offset=count_offset,
            expected=0x006E,
            replacement=NAME_BITMAP_BACKWARD_INITIAL,
            owner="unit39 4+4 name cache clear count",
        )
        _patch_immediate(
            patched,
            file_offset=end_offset,
            expected=expected_end,
            replacement=replacement_end,
            owner="unit39 4+4 name cache clear end",
        )
        _append_word_range(allowed_ranges, count_offset)
        _append_word_range(allowed_ranges, end_offset)

    for address in UNIT40_GIVEN_POINTER_ORI_ADDRESSES:
        offset = unit_address_to_allbin_offset(40, address)
        _patch_immediate(
            patched,
            file_offset=offset,
            expected=0xAE20,
            replacement=GIVEN_NAME_BUFFER_4X4 & 0xFFFF,
            owner="unit40 4+4 given-name scratch base",
        )
        _append_word_range(allowed_ranges, offset)

    for address, expected, replacement in UNIT40_IMMEDIATE_PATCHES:
        offset = unit_address_to_allbin_offset(40, address)
        _patch_immediate(
            patched,
            file_offset=offset,
            expected=expected,
            replacement=replacement,
            owner="unit40 4+4 name editor",
        )
        _append_word_range(allowed_ranges, offset)

    for address, expected, replacement in UNIT40_NAME_DISPLAY_STREAM_PATCHES:
        offset = unit_address_to_allbin_offset(40, address)
        actual = bytes(patched[offset : offset + len(expected)])
        if actual != expected:
            raise ValueError(
                "unit40 4+4 name display stream differs at "
                f"0x{address:08X}: {actual.hex()} != {expected.hex()}"
            )
        patched[offset : offset + len(replacement)] = replacement
        allowed_ranges.append((offset, offset + len(replacement)))

    unit40_start = ALLBIN_UNIT_OFFSETS[40]
    unit40_end = unit40_start + UNIT40_SIZE
    patched_unit40, input_form_report = (
        _patch_unit40_input_form_with_armips(
            bytes(patched[unit40_start:unit40_end])
        )
    )
    patched[unit40_start:unit40_end] = patched_unit40
    allowed_ranges.extend(
        (
            unit40_start
            + start
            - ALLBIN_UNIT_LOAD_ADDRESSES[40],
            unit40_start
            + end
            - ALLBIN_UNIT_LOAD_ADDRESSES[40],
        )
        for start, end in UNIT40_INPUT_FORM_ALLOWED_ADDRESS_RANGES
    )

    protected_origin_ui = []
    for entry_id, address, size in UNIT40_TRANSLATED_ORIGIN_UI_STREAMS:
        offset = unit_address_to_allbin_offset(40, address)
        source = input_allbin[offset : offset + size]
        output = bytes(patched[offset : offset + size])
        if output != source:
            raise ValueError(
                f"{entry_id}: 4+4 patch changed translated origin UI"
            )
        protected_origin_ui.append(
            {
                "entry_id": entry_id,
                "address": f"0x{address:08X}",
                "byte_size": size,
                "sha256": sha256_bytes(source),
                "unchanged": True,
            }
        )

    return bytes(patched), {
        "allowed_ranges": allowed_ranges,
        "unit35": {
            "save_pointer_table_address": (
                f"0x{UNIT35_SAVE_POINTER_TABLE_ADDRESS:08X}"
            ),
            "save_pointer_count": len(SAVE_NAME_BASES_4X4),
            "copy_limit_patch_count": len(UNIT35_FORWARD_LIMIT_ADDRESSES),
        },
        "unit39": {
            "copy_limit_patch_count": len(
                UNIT39_FORWARD_LIMIT_ADDRESSES
            ),
            "cache_base_patch_count": len(
                UNIT39_CACHE_BASE_ORI_PATCHES
            ),
            "save_base_patch_count": len(
                UNIT39_SAVE_BASE_ORI_PATCHES
            ),
            "cache_clear_patch_count": len(
                UNIT39_CACHE_CLEAR_PATCHES
            ),
        },
        "unit40": {
            "given_base_patch_count": len(
                UNIT40_GIVEN_POINTER_ORI_ADDRESSES
            ),
            "layout_patch_count": len(UNIT40_IMMEDIATE_PATCHES),
            "display_stream_patch_count": len(
                UNIT40_NAME_DISPLAY_STREAM_PATCHES
            ),
            "input_form": input_form_report,
            "protected_translated_origin_ui": protected_origin_ui,
        },
    }


def _patch_slps(input_slps: bytes) -> tuple[bytes, dict[str, Any]]:
    patched = bytearray(input_slps)
    allowed_ranges: list[tuple[int, int]] = []

    table_source = bytes(
        patched[
            STATIC_NAME_CODE_FILE_OFFSET:STATIC_NAME_CODE_END_FILE_OFFSET
        ]
    )
    if table_source != b"\x00" * 16:
        raise ValueError("SLPS static 4+4 name-code tail is not zero")
    struct.pack_into(
        "<8H",
        patched,
        STATIC_NAME_CODE_FILE_OFFSET,
        *STATIC_NAME_CODES,
    )
    allowed_ranges.append(
        (
            STATIC_NAME_CODE_FILE_OFFSET,
            STATIC_NAME_CODE_END_FILE_OFFSET,
        )
    )

    for address, expected, replacement in (
        *SLPS_SURNAME_POINTER_BLOCK,
        *SLPS_GIVEN_POINTER_BLOCK,
    ):
        offset = slps_address_to_file_offset(address)
        _patch_word(
            patched,
            file_offset=offset,
            expected=expected,
            replacement=replacement,
            owner="SLPS static 4+4 virtual-name code pointers",
        )
        _append_word_range(allowed_ranges, offset)

    for address, expected in SLPS_NAME_CODE_WRITE_NOPS:
        offset = slps_address_to_file_offset(address)
        _patch_word(
            patched,
            file_offset=offset,
            expected=expected,
            replacement=0,
            owner="SLPS preserve static 4+4 virtual-name codes",
        )
        _append_word_range(allowed_ranges, offset)

    for (
        count_address,
        end_address,
        expected_end,
        replacement_end,
    ) in SLPS_CACHE_CLEAR_PATCHES:
        count_offset = slps_address_to_file_offset(count_address)
        end_offset = slps_address_to_file_offset(end_address)
        _patch_immediate(
            patched,
            file_offset=count_offset,
            expected=0x006E,
            replacement=NAME_BITMAP_BACKWARD_INITIAL,
            owner="SLPS 4+4 name cache clear count",
        )
        _patch_immediate(
            patched,
            file_offset=end_offset,
            expected=expected_end,
            replacement=replacement_end,
            owner="SLPS 4+4 name cache clear end",
        )
        _append_word_range(allowed_ranges, count_offset)
        _append_word_range(allowed_ranges, end_offset)

    clear_limit_offset = slps_address_to_file_offset(
        SLPS_LIVE_NAME_CLEAR_LIMIT_ADDRESS
    )
    _patch_immediate(
        patched,
        file_offset=clear_limit_offset,
        expected=0x0006,
        replacement=NAME_GLYPH_COUNT,
        owner="SLPS 4+4 live-name scratch clear",
    )
    _append_word_range(allowed_ranges, clear_limit_offset)

    roman_start = slps_address_to_file_offset(SLPS_ROMAN_POINTER_BLOCK[0])
    roman_end = slps_address_to_file_offset(SLPS_ROMAN_POINTER_BLOCK[1])
    roman_source = input_slps[roman_start:roman_end]
    roman_output = patched[roman_start:roman_end]
    if roman_source != roman_output:
        raise ValueError("SLPS Roman-name pointer block changed")

    return bytes(patched), {
        "allowed_ranges": allowed_ranges,
        "static_code_table": {
            "file_offset": f"0x{STATIC_NAME_CODE_FILE_OFFSET:X}",
            "end_exclusive": (
                f"0x{STATIC_NAME_CODE_END_FILE_OFFSET:X}"
            ),
            "surname_address": f"0x{STATIC_SURNAME_CODE_ADDRESS:08X}",
            "given_name_address": f"0x{STATIC_GIVEN_CODE_ADDRESS:08X}",
            "codes": [f"0x{value:03X}" for value in STATIC_NAME_CODES],
        },
        "pointer_instruction_count": (
            len(SLPS_SURNAME_POINTER_BLOCK)
            + len(SLPS_GIVEN_POINTER_BLOCK)
        ),
        "disabled_runtime_code_write_count": len(
            SLPS_NAME_CODE_WRITE_NOPS
        ),
        "cache_clear_patch_count": len(SLPS_CACHE_CLEAR_PATCHES),
        "live_clear_limit": NAME_GLYPH_COUNT,
        "protected_roman_pointer_block": {
            "start_address": f"0x{SLPS_ROMAN_POINTER_BLOCK[0]:08X}",
            "end_exclusive_address": (
                f"0x{SLPS_ROMAN_POINTER_BLOCK[1]:08X}"
            ),
            "sha256": sha256_bytes(roman_source),
            "unchanged": True,
        },
    }


def _hex_addresses(values: Iterable[int]) -> list[str]:
    return [f"0x{value:08X}" for value in values]


def build_name_4x4_poc(
    *,
    file_build_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    names = base_manifest.get("character_names")
    fixed = names.get("fixed_player_name") if isinstance(names, dict) else None
    if not isinstance(fixed, dict) or "2+4" not in str(fixed.get("layout")):
        raise ValueError("base build is not the verified 2+4 name layout")
    if (
        base_manifest.get("font", {}).get("dynamic_name_widths")
        != DYNAMIC_NAME_WIDTHS
    ):
        raise ValueError(
            "base build does not preserve 4+4 dynamic player-name tokens"
        )
    ui_translation = base_manifest.get("ui_translation")
    translated_ui = (
        ui_translation.get("translated_entries")
        if isinstance(ui_translation, dict)
        else None
    )
    translated_ui_ids = {
        item.get("entry_id")
        for item in translated_ui
        if isinstance(item, dict)
    } if isinstance(translated_ui, list) else set()
    required_origin_ui_ids = {
        entry_id for entry_id, _, _ in UNIT40_TRANSLATED_ORIGIN_UI_STREAMS
    }
    if not required_origin_ui_ids <= translated_ui_ids:
        raise ValueError(
            "base build does not contain the translated origin prompt/options"
        )

    inputs = {
        name: (file_build_dir / name).read_bytes()
        for name in ("START.BIN", "ALLBIN.BIN", "SLPS_019.58")
    }
    for name, payload in inputs.items():
        expected = base_manifest["outputs"][name]["sha256"]
        if sha256_bytes(payload) != expected:
            raise ValueError(f"{name}: base file-build hash differs")

    patched_allbin, allbin_report = _patch_allbin(inputs["ALLBIN.BIN"])
    patched_slps, slps_report = _patch_slps(inputs["SLPS_019.58"])
    patched_start = inputs["START.BIN"]

    allbin_expected = verify_expected_writes(
        inputs["ALLBIN.BIN"],
        patched_allbin,
        allowed_ranges=allbin_report.pop("allowed_ranges"),
        owner="ALLBIN 4+4 name bitmap and save-slot PoC",
    )
    slps_expected = verify_expected_writes(
        inputs["SLPS_019.58"],
        patched_slps,
        allowed_ranges=slps_report.pop("allowed_ranges"),
        owner="SLPS 4+4 virtual-name code and cache PoC",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "START.BIN": patched_start,
        "ALLBIN.BIN": patched_allbin,
        "SLPS_019.58": patched_slps,
    }
    for name, payload in outputs.items():
        (output_dir / name).write_bytes(payload)

    map_source = file_build_dir / "primary-korean-glyph-map.json"
    if map_source.exists():
        shutil.copyfile(map_source, output_dir / map_source.name)

    name_layout = {
        "status": "static-verification-passed-runtime-validation-required",
        "release_eligible": False,
        "scope": (
            "surname/given-name 4+4 bitmap storage, prompt/confirmation "
            "display, and dynamic dialogue substitution; Japanese input "
            "palettes are preserved"
        ),
        "field_capacity": {
            "surname_glyphs": 4,
            "given_name_glyphs": 4,
            "total_glyphs": NAME_GLYPH_COUNT,
            "default_surname": fixed.get("surname"),
            "default_given_name": fixed.get("given_name"),
        },
        "bitmap_layout": {
            "bytes_per_glyph": GLYPH_SIZE,
            "total_bytes": NAME_BITMAP_BYTES,
            "copy_dwords": NAME_BITMAP_DWORDS,
            "live_start": f"0x{LIVE_NAME_BUFFER:08X}",
            "given_name_start": f"0x{GIVEN_NAME_BUFFER_4X4:08X}",
            "live_end_exclusive": f"0x{LIVE_NAME_END:08X}",
            "cache_bases": _hex_addresses(CACHE_BASES_4X4),
            "cache_end_exclusive": f"0x{CACHE_REGION_END:08X}",
        },
        "save_slot_layout": {
            "slot_stride": f"0x{SAVE_SLOT_STRIDE:X}",
            "name_bytes_per_slot": NAME_BITMAP_BYTES,
            "name_bases": _hex_addresses(SAVE_NAME_BASES_4X4),
            "next_slot_header_bases": _hex_addresses(
                SAVE_SLOT_NEXT_HEADER_BASES
            ),
            "each_name_block_ends_at_next_slot_header": all(
                name_base + NAME_BITMAP_BYTES == next_header
                for name_base, next_header in zip(
                    SAVE_NAME_BASES_4X4,
                    SAVE_SLOT_NEXT_HEADER_BASES,
                )
            ),
            "slot_stride_unchanged": True,
        },
        "protected_paths": {
            "roman_name_stage": (
                "original 10-slot table and updater body retained; "
                "persistent input-kind values other than 2 dispatch "
                "back to the original path"
            ),
            "origin_stage": (
                "selection logic, translated prompt/options, and mutable "
                "origin buffer remain unchanged; only the three final-"
                "confirmation name-frame widths/positions are expanded"
            ),
            "japanese_input_palettes": "outside all Expected Write ranges",
            "font_assets": "START.BIN byte-for-byte unchanged",
            "direct_dialogue_name_tokens": {
                "surname": "0x4000",
                "given_name": "0x6000",
                "visible_widths": DYNAMIC_NAME_WIDTHS,
                "policy": "preserve source control words",
            },
        },
        "allbin": allbin_report,
        "slps": slps_report,
        "runtime_validation_required": [
            "enter four surname glyphs and four given-name glyphs",
            "confirm all eight glyphs render in the input prompt",
            "confirm all eight glyphs render in the final confirmation",
            "confirm the registered name appears in the nameplate",
            "confirm the registered name replaces dynamic dialogue tokens",
            "save into each of the four slots",
            "cold boot and load each slot",
            "confirm Roman-name behavior and origin selection are unchanged",
            "confirm the Korean origin prompt and all three options render",
        ],
    }

    manifest = {
        **base_manifest,
        "warning": (
            "Nonrelease 4+4 player-name structural PoC. The Japanese input "
            "palettes, Roman-name data/layout, and origin selection logic "
            "are preserved. Runtime input/save/load validation is required."
        ),
        "sources": {
            **base_manifest["sources"],
            "name_4x4_base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
        },
        "character_names": {
            **names,
            "fixed_player_name": {
                **fixed,
                "layout": (
                    "4+4 scratch capacity; fixed default remains "
                    f"{fixed.get('surname')}/{fixed.get('given_name')}"
                ),
            },
        },
        "name_4x4_poc": name_layout,
        "expected_writes": {
            **base_manifest.get("expected_writes", {}),
            "name_4x4_poc": {
                "ALLBIN.BIN_relative_to_base_build": allbin_expected,
                "SLPS_019.58_relative_to_base_build": slps_expected,
                "START.BIN_relative_to_base_build": {
                    "owner": "START.BIN protected font assets",
                    "source_size": len(patched_start),
                    "output_size": len(patched_start),
                    "changed_byte_count": 0,
                    "changed_range_count": 0,
                    "changed_ranges": [],
                    "allowed_ranges": [],
                    "verified": True,
                },
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
        },
    }
    if map_source.exists():
        manifest["outputs"]["glyph_map"] = {
            "path": str((output_dir / map_source.name).resolve()),
            "sha256": sha256_file(output_dir / map_source.name),
        }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-build-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_name_4x4_poc(
        file_build_dir=args.file_build_dir,
        output_dir=args.output_dir,
    )
    report = manifest["name_4x4_poc"]
    print(
        f"layout=4+4 bitmap_bytes={report['bitmap_layout']['total_bytes']} "
        f"save_bases={','.join(report['save_slot_layout']['name_bases'])} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']} "
        f"SLPS={manifest['outputs']['SLPS_019.58']['sha256']}"
    )


if __name__ == "__main__":
    main()
