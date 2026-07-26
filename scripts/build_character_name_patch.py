#!/usr/bin/env python3
"""Add the fixed Korean player name and Korean speaker labels to a file build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
from typing import Any

try:
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.korean_font import (
        crop_to_psx,
        load_font_profile,
        rasterize_ttf_glyph,
    )
    from scripts.psx_font import GLYPH_SIZE, pack_glyph
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import verify_expected_writes
    from korean_font import crop_to_psx, load_font_profile, rasterize_ttf_glyph
    from psx_font import GLYPH_SIZE, pack_glyph


EXPECTED_SLPS_SHA256 = (
    "0cbda75255e7f9edbb758ee8b815082c3dd167e7e0e709a5526c17653014fab9"
)
EXPECTED_START_SHA256 = (
    "d0b22efb4e5ea46c869f822af9bc7f207bc95a670a25acb15fc3dcd2ab3bf8cc"
)
EXPECTED_ALLBIN_SHA256 = (
    "6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e"
)

SLPS_LOAD_ADDRESS = 0x80030000
SLPS_PAYLOAD_FILE_OFFSET = 0x800
SPEAKER_STRING_START = 0x1FA50
SPEAKER_STRING_END = 0x1FB6C
SPEAKER_TABLE_OFFSET = 0x1FB6C
SPEAKER_RECORD_COUNT = 34
SPEAKER_RECORD_SIZE = 8
SLPS_GIVEN_POINTER_START_INSTRUCTION = 0x80039F04
SLPS_GIVEN_CLEAR_COUNT_INSTRUCTION = 0x8003A6EC
SLPS_GIVEN_DEFAULT_STORE_PATCHES = (
    # The surname's third initialization store already places virtual glyph
    # 0x4D0 at state+0x36. Move the existing given-name stores one u16
    # forward so they preserve that first glyph and fill through state+0x3C.
    (0x8003A918, 0x0000, 0x0002),
    (0x8003A924, 0x0002, 0x0004),
    (0x8003A938, 0x0004, 0x0006),
)

ALLBIN_UNIT40_FILE_OFFSET = 0x151800
ALLBIN_UNIT40_LOAD_ADDRESS = 0x80098000
DEFAULT_SURNAME_ADDRESS = 0x800A0714
DEFAULT_GIVEN_ADDRESS = 0x800A071C
SURNAME_BUFFER_ADDRESS = 0x8002AD8C
ORIGINAL_GIVEN_BUFFER_ADDRESS = 0x8002AE6A
KOREAN_GIVEN_BUFFER_ADDRESS = 0x8002AE20

ALTERNATE_FONT_OFFSET = 0x3D1800
ALTERNATE_FONT_RUNTIME_ADDRESS = 0x80185000
ALTERNATE_FONT_SCHEDULED_BYTE_SIZE = 124928
ALTERNATE_DEFINED_GLYPH_COUNT = 0x5CC
ALTERNATE_FIXED_NAME_CHARACTERS = "시바세이치로"
ALTERNATE_FIXED_NAME_MAPPING = {
    character: ALTERNATE_DEFINED_GLYPH_COUNT + index
    for index, character in enumerate(ALTERNATE_FIXED_NAME_CHARACTERS)
}

# Every direct name-editor reference to the original three-glyph given-name
# scratch base. The low ORI immediate is patched from 0xAE6A to 0xAE20.
GIVEN_BUFFER_REFERENCE_INSTRUCTIONS = (
    0x800992C0,
    0x80099474,
    0x800995B8,
    0x80099890,
    0x80099AAC,
    0x8009A434,
    0x8009AC78,
    0x8009AE40,
)

# Immediate-only edits in the unit 40 name editor. The tuple is
# (instruction address, expected immediate, replacement immediate).
UNIT40_IMMEDIATE_PATCHES = (
    # Empty-record scans and default loading.
    (0x8009942C, 0x0003, 0x0002),
    (0x80099438, 0x0007, 0x0003),
    (0x800994C4, 0x0003, 0x0004),
    (0x800994D0, 0x0007, 0x000F),
    (0x8009957C, 0x0003, 0x0002),
    (0x80099590, 0x0003, 0x0002),
    (0x80099620, 0x0003, 0x0004),
    (0x80099634, 0x0003, 0x0002),
    # Three character-grid input paths.
    (0x80099760, 0x0003, 0x0002),
    (0x80099884, 0x0003, 0x0004),
    (0x8009997C, 0x0003, 0x0002),
    (0x80099AA0, 0x0003, 0x0004),
    (0x8009A2EC, 0x0003, 0x0002),
    (0x8009A428, 0x0003, 0x0004),
    (0x8009A568, 0x0003, 0x0004),
    # Trailing-empty-record normalization for surname 2 / given name 4.
    (0x8009AB54, 0x0002, 0x0001),
    (0x8009AB70, 0x0094, 0x004A),
    (0x8009ABC4, 0x0003, 0x0002),
    (0x8009AC14, 0x0003, 0x0002),
    (0x8009AC2C, 0x0003, 0x0002),
    (0x8009AC6C, 0x0003, 0x0004),
    (0x8009AC74, 0x0002, 0x0003),
    (0x8009AC8C, 0xAEB4, 0xAE6A),
    (0x8009AC90, 0x0094, 0x00DE),
    (0x8009ACE4, 0x0003, 0x0004),
    (0x8009AD34, 0x0003, 0x0004),
    (0x8009AD4C, 0x0003, 0x0004),
)

# Full instruction replacements needed where one original instruction cannot
# express both component lengths.
UNIT40_WORD_PATCHES = (
    # Fill the given-length pointer load-delay slot with "li v1, 4".
    (0x80099644, 0x00000000, 0x24030004),
    # Prepare surname length 2 in the branch delay slot.
    (0x8009AB4C, 0x00000000, 0x24020002),
    # Store that prepared length instead of the editor state value 3.
    (0x8009AB50, 0xA0700000, 0xA0620000),
)


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


def slps_address_to_file_offset(address: int) -> int:
    return address - SLPS_LOAD_ADDRESS + SLPS_PAYLOAD_FILE_OFFSET


def unit40_address_to_allbin_offset(address: int) -> int:
    return (
        ALLBIN_UNIT40_FILE_OFFSET
        + address
        - ALLBIN_UNIT40_LOAD_ADDRESS
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
            f"{owner}: instruction differs at 0x{file_offset:X}: "
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
    struct.pack_into("<I", data, file_offset, (word & 0xFFFF0000) | replacement)


def load_built_primary_mapping(path: Path) -> dict[str, int]:
    document = load_object(path)
    values = document.get("mapping")
    if not isinstance(values, dict):
        raise ValueError("built primary glyph map has no mapping object")
    result: dict[str, int] = {}
    for character, value in values.items():
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError(f"invalid built glyph character: {character!r}")
        result[character] = int(value, 0) if isinstance(value, str) else int(value)
    return result


def load_original_primary_maps(
    path: Path,
) -> tuple[dict[str, int], dict[int, str]]:
    document = load_object(path)
    glyphs = document.get("tables", {}).get("primary", {}).get("glyphs")
    if not isinstance(glyphs, dict):
        raise ValueError("original primary glyph map is missing")
    by_character: dict[str, int] = {}
    by_index: dict[int, str] = {}
    for index_hex, character in glyphs.items():
        index = int(index_hex, 16)
        by_index[index] = character
        by_character.setdefault(character, index)
    return by_character, by_index


def approved_glossary_terms(path: Path) -> dict[str, dict[str, Any]]:
    document = load_object(path)
    terms = document.get("terms")
    if not isinstance(terms, list):
        raise ValueError("glossary terms must be an array")
    result: dict[str, dict[str, Any]] = {}
    for term in terms:
        term_id = term.get("term_id")
        if not isinstance(term_id, str) or term_id in result:
            raise ValueError(f"invalid or duplicate glossary term: {term_id!r}")
        result[term_id] = term
    return result


def validate_name_artifacts(
    names: dict[str, Any],
    glossary: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    fixed = names.get("fixed_player_name")
    table = names.get("speaker_name_table")
    if not isinstance(fixed, dict) or not isinstance(table, dict):
        raise ValueError("character-name artifact is incomplete")
    if (
        fixed.get("surname") != "시바"
        or fixed.get("given_name") != "세이치로"
        or fixed.get("surname_glyphs") != 2
        or fixed.get("given_name_glyphs") != 4
        or fixed.get("runtime_shared_glyph_slots") != 6
    ):
        raise ValueError("fixed player name must be 시바 / 세이치로 in 2+4 slots")
    fixed_term = glossary.get(str(fixed.get("glossary_term_id")))
    if (
        fixed_term is None
        or fixed_term.get("status") != "approved"
        or fixed_term.get("ko_candidate") != "시바 세이치로"
    ):
        raise ValueError("fixed player name is not approved in the glossary")

    records = table.get("records")
    safe_limit = table.get("safe_glyph_limit")
    if not isinstance(records, list) or not isinstance(safe_limit, int):
        raise ValueError("speaker-name table metadata is invalid")
    if [record.get("index") for record in records] != list(
        range(SPEAKER_RECORD_COUNT)
    ):
        raise ValueError("speaker-name records must cover ordered indices 0..33")

    total_glyphs = 0
    for record in records:
        original = record.get("jp")
        translated = record.get("ko")
        if not isinstance(original, str) or not original:
            raise ValueError(f"speaker {record.get('index')}: missing Japanese name")
        if not isinstance(translated, str) or not translated:
            raise ValueError(f"speaker {record.get('index')}: missing Korean name")
        if len(translated) > safe_limit:
            raise ValueError(
                f"speaker {record.get('index')}: {translated!r} exceeds "
                f"{safe_limit} safe glyphs"
            )
        total_glyphs += len(translated)
        term_id = record.get("glossary_term_id")
        if term_id is None:
            continue
        term = glossary.get(str(term_id))
        if term is None:
            raise ValueError(
                f"speaker {record.get('index')}: glossary term {term_id} "
                "does not exist"
            )
        allowed_statuses = (
            {"approved"}
            if term.get("category") == "character"
            else {"candidate", "approved"}
        )
        if term.get("status") not in allowed_statuses:
            raise ValueError(
                f"speaker {record.get('index')}: glossary term {term_id} "
                f"has unusable status {term.get('status')!r}"
            )
        candidate = str(term.get("ko_candidate", "")).replace(" ", "")
        if not candidate or (
            translated not in candidate and candidate not in translated
        ):
            raise ValueError(
                f"speaker {record.get('index')}: {translated!r} does not "
                f"match glossary term {term_id} ({candidate!r})"
            )

    capacity = SPEAKER_STRING_END - SPEAKER_STRING_START
    required_bytes = total_glyphs * 2
    if required_bytes > capacity:
        raise ValueError(
            f"speaker names require {required_bytes} bytes but only "
            f"{capacity} are available"
        )
    return fixed, records, safe_limit


def _encode_character(
    character: str,
    *,
    built_mapping: dict[str, int],
    original_mapping: dict[str, int],
) -> int:
    if character in built_mapping:
        return built_mapping[character]
    original = original_mapping.get(character)
    if original is not None and 0 <= original < 0x046:
        return original
    raise ValueError(f"speaker-name glyph is unavailable: {character!r}")


def encode_speaker_records(
    records: list[dict[str, Any]],
    *,
    built_mapping: dict[str, int],
    original_mapping: dict[str, int],
) -> tuple[list[list[int]], int]:
    encoded: list[list[int]] = []
    for record in records:
        encoded.append(
            [
                _encode_character(
                    character,
                    built_mapping=built_mapping,
                    original_mapping=original_mapping,
                )
                for character in record["ko"]
            ]
        )
    return encoded, sum(len(values) for values in encoded) * 2


def patch_speaker_table(
    source_slps: bytes,
    records: list[dict[str, Any]],
    encoded: list[list[int]],
    *,
    safe_glyph_limit: int,
    original_by_index: dict[int, str],
) -> tuple[bytes, dict[str, Any]]:
    if len(encoded) != len(records):
        raise ValueError("speaker-name encoded record count differs")
    patched = bytearray(source_slps)
    for index, record in enumerate(records):
        table_offset = SPEAKER_TABLE_OFFSET + index * SPEAKER_RECORD_SIZE
        source_length = struct.unpack_from("<H", source_slps, table_offset)[0]
        source_pointer = struct.unpack_from("<I", source_slps, table_offset + 4)[0]
        source_offset = slps_address_to_file_offset(source_pointer)
        source_codes = struct.unpack_from(
            f"<{source_length}H", source_slps, source_offset
        )
        source_text = "".join(
            original_by_index.get(code, f"<{code:04X}>")
            for code in source_codes
        )
        if source_text != record["jp"]:
            raise ValueError(
                f"speaker {index}: original table differs: "
                f"{source_text!r} != {record['jp']!r}"
            )

    cursor = SPEAKER_STRING_START
    output_records: list[dict[str, Any]] = []
    patched[SPEAKER_STRING_START:SPEAKER_STRING_END] = bytes(
        SPEAKER_STRING_END - SPEAKER_STRING_START
    )
    for index, (record, codes) in enumerate(zip(records, encoded)):
        payload = struct.pack(f"<{len(codes)}H", *codes)
        end = cursor + len(payload)
        if end > SPEAKER_STRING_END:
            raise ValueError(f"speaker {index}: packed names exceed safe region")
        patched[cursor:end] = payload
        table_offset = SPEAKER_TABLE_OFFSET + index * SPEAKER_RECORD_SIZE
        pointer = SLPS_LOAD_ADDRESS + cursor - SLPS_PAYLOAD_FILE_OFFSET
        struct.pack_into("<H", patched, table_offset, len(codes))
        struct.pack_into("<H", patched, table_offset + 2, 0)
        struct.pack_into("<I", patched, table_offset + 4, pointer)
        output_records.append(
            {
                "index": index,
                "jp": record["jp"],
                "ko": record["ko"],
                "glyphs": len(codes),
                "safe_glyph_limit": safe_glyph_limit,
                "file_offset": f"0x{cursor:X}",
                "runtime_pointer": f"0x{pointer:08X}",
                "codes": [f"0x{code:03X}" for code in codes],
            }
        )
        cursor = end

    # The first pointer of the given-name code array moves one u16 word back:
    # surname [0,1], given [2,3,4,5]. The main renderer uses the first pointer
    # as a contiguous base, so no seventh glyph slot or extra pointer is needed.
    pointer_instruction_offset = slps_address_to_file_offset(
        SLPS_GIVEN_POINTER_START_INSTRUCTION
    )
    _patch_immediate(
        patched,
        file_offset=pointer_instruction_offset,
        expected=0x0038,
        replacement=0x0036,
        owner="SLPS given-name code-array base",
    )
    clear_count_offset = slps_address_to_file_offset(
        SLPS_GIVEN_CLEAR_COUNT_INSTRUCTION
    )
    _patch_immediate(
        patched,
        file_offset=clear_count_offset,
        expected=0x0003,
        replacement=0x0004,
        owner="SLPS given-name code-array clear count",
    )
    for instruction_address, expected, replacement in (
        SLPS_GIVEN_DEFAULT_STORE_PATCHES
    ):
        _patch_immediate(
            patched,
            file_offset=slps_address_to_file_offset(instruction_address),
            expected=expected,
            replacement=replacement,
            owner="SLPS given-name default virtual-glyph stores",
        )

    report = {
        "record_count": len(records),
        "safe_glyph_limit": safe_glyph_limit,
        "max_output_glyphs": max(len(values) for values in encoded),
        "string_region": {
            "start": f"0x{SPEAKER_STRING_START:X}",
            "end_exclusive": f"0x{SPEAKER_STRING_END:X}",
            "capacity_bytes": SPEAKER_STRING_END - SPEAKER_STRING_START,
            "used_bytes": cursor - SPEAKER_STRING_START,
            "free_bytes": SPEAKER_STRING_END - cursor,
        },
        "records": output_records,
        "given_name_code_array_base_patch": {
            "instruction_address": (
                f"0x{SLPS_GIVEN_POINTER_START_INSTRUCTION:08X}"
            ),
            "old_state_offset": "0x38",
            "new_state_offset": "0x36",
            "layout": "surname[2] + given[4] in existing six u16 codes",
        },
        "given_name_code_array_clear_patch": {
            "instruction_address": (
                f"0x{SLPS_GIVEN_CLEAR_COUNT_INSTRUCTION:08X}"
            ),
            "old_count": 3,
            "new_count": 4,
        },
        "given_name_default_store_patch_count": len(
            SLPS_GIVEN_DEFAULT_STORE_PATCHES
        ),
    }
    return bytes(patched), report


def _render_name_glyphs(
    source_start: bytes,
    *,
    font_profile_path: Path,
) -> tuple[bytes, dict[str, Any]]:
    patched = bytearray(source_start)
    profile = load_font_profile(font_profile_path)
    from PIL import ImageFont

    ttf = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    slots: list[dict[str, Any]] = []
    allowed_ranges: list[tuple[int, int]] = []
    for character, index in ALTERNATE_FIXED_NAME_MAPPING.items():
        offset = ALTERNATE_FONT_OFFSET + index * GLYPH_SIZE
        end = offset + GLYPH_SIZE
        if end > ALTERNATE_FONT_OFFSET + ALTERNATE_FONT_SCHEDULED_BYTE_SIZE:
            raise ValueError(
                f"alternate glyph 0x{index:03X} exceeds the scheduled load"
            )
        if any(source_start[offset:end]):
            raise ValueError(
                f"alternate glyph 0x{index:03X} is not in the verified zero tail"
            )
        pixels = rasterize_ttf_glyph(
            ttf,
            character,
            x_offset=profile.x_offset_px,
            y_offset=profile.y_offset_px,
        )
        retained = crop_to_psx(pixels, intensity=profile.intensity)
        record = pack_glyph(retained)
        if not any(record):
            raise ValueError(f"alternate name glyph is empty: {character!r}")
        patched[offset:end] = record
        allowed_ranges.append((offset, end))
        slots.append(
            {
                "character": character,
                "index": f"0x{index:03X}",
                "file_offset": f"0x{offset:X}",
                "record_sha256": sha256_bytes(record),
            }
        )
    scheduled_end = (
        ALTERNATE_FONT_RUNTIME_ADDRESS + ALTERNATE_FONT_SCHEDULED_BYTE_SIZE
    )
    last_allocated_end = (
        ALTERNATE_FONT_RUNTIME_ADDRESS
        + (max(ALTERNATE_FIXED_NAME_MAPPING.values()) + 1) * GLYPH_SIZE
    )
    return bytes(patched), {
        "provider": "START.BIN alternate UI font",
        "font_offset": f"0x{ALTERNATE_FONT_OFFSET:X}",
        "runtime_address": f"0x{ALTERNATE_FONT_RUNTIME_ADDRESS:08X}",
        "scheduled_byte_size": ALTERNATE_FONT_SCHEDULED_BYTE_SIZE,
        "scheduled_end_exclusive": f"0x{scheduled_end:08X}",
        "first_verified_zero_tail_index": (
            f"0x{ALTERNATE_DEFINED_GLYPH_COUNT:03X}"
        ),
        "last_allocated_end_exclusive": f"0x{last_allocated_end:08X}",
        "allocated_glyph_count": len(slots),
        "slots": slots,
        "allowed_ranges": allowed_ranges,
    }


def patch_unit40_name_editor(
    source_allbin: bytes,
    fixed: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    patched = bytearray(source_allbin)
    allowed_ranges: list[tuple[int, int]] = []

    for instruction_address in GIVEN_BUFFER_REFERENCE_INSTRUCTIONS:
        file_offset = unit40_address_to_allbin_offset(
            instruction_address + 4
        )
        _patch_immediate(
            patched,
            file_offset=file_offset,
            expected=ORIGINAL_GIVEN_BUFFER_ADDRESS & 0xFFFF,
            replacement=KOREAN_GIVEN_BUFFER_ADDRESS & 0xFFFF,
            owner="unit40 given-name scratch base",
        )
        allowed_ranges.append((file_offset, file_offset + 4))

    for instruction_address, expected, replacement in UNIT40_IMMEDIATE_PATCHES:
        file_offset = unit40_address_to_allbin_offset(instruction_address)
        _patch_immediate(
            patched,
            file_offset=file_offset,
            expected=expected,
            replacement=replacement,
            owner="unit40 2+4 name editor",
        )
        allowed_ranges.append((file_offset, file_offset + 4))

    for instruction_address, expected, replacement in UNIT40_WORD_PATCHES:
        file_offset = unit40_address_to_allbin_offset(instruction_address)
        _patch_word(
            patched,
            file_offset=file_offset,
            expected=expected,
            replacement=replacement,
            owner="unit40 2+4 name editor",
        )
        allowed_ranges.append((file_offset, file_offset + 4))

    surname = str(fixed["surname"])
    given = str(fixed["given_name"])
    surname_values = [
        *(ALTERNATE_FIXED_NAME_MAPPING[character] for character in surname),
        0,
        0,
    ]
    given_values = [
        ALTERNATE_FIXED_NAME_MAPPING[character] for character in given
    ]
    surname_offset = unit40_address_to_allbin_offset(DEFAULT_SURNAME_ADDRESS)
    given_offset = unit40_address_to_allbin_offset(DEFAULT_GIVEN_ADDRESS)
    original_surname = struct.unpack_from("<4H", source_allbin, surname_offset)
    original_given = struct.unpack_from("<4H", source_allbin, given_offset)
    if original_surname != (0x0285, 0x045A, 0, 0):
        raise ValueError("unit40 original default surname is not 司馬")
    if original_given != (0x0350, 0x00FC, 0x0584, 0):
        raise ValueError("unit40 original default given name is not 誠一郎")
    struct.pack_into("<4H", patched, surname_offset, *surname_values)
    struct.pack_into("<4H", patched, given_offset, *given_values)
    allowed_ranges.extend(
        (
            (surname_offset, surname_offset + 8),
            (given_offset, given_offset + 8),
        )
    )

    report = {
        "overlay_unit": 40,
        "overlay_file_offset": f"0x{ALLBIN_UNIT40_FILE_OFFSET:X}",
        "overlay_load_address": f"0x{ALLBIN_UNIT40_LOAD_ADDRESS:08X}",
        "original_layout": {
            "surname_glyphs": 3,
            "given_name_glyphs": 3,
            "surname_buffer": f"0x{SURNAME_BUFFER_ADDRESS:08X}",
            "given_name_buffer": (
                f"0x{ORIGINAL_GIVEN_BUFFER_ADDRESS:08X}"
            ),
        },
        "patched_layout": {
            "surname_glyphs": 2,
            "given_name_glyphs": 4,
            "surname_buffer": f"0x{SURNAME_BUFFER_ADDRESS:08X}",
            "given_name_buffer": f"0x{KOREAN_GIVEN_BUFFER_ADDRESS:08X}",
            "end_exclusive": "0x8002AF48",
            "extra_runtime_bytes": 0,
        },
        "default_source": {
            "surname": surname,
            "given_name": given,
            "surname_file_offset": f"0x{surname_offset:X}",
            "given_name_file_offset": f"0x{given_offset:X}",
            "alternate_codes": {
                character: f"0x{index:03X}"
                for character, index in ALTERNATE_FIXED_NAME_MAPPING.items()
            },
        },
        "given_buffer_reference_patch_count": len(
            GIVEN_BUFFER_REFERENCE_INSTRUCTIONS
        ),
        "immediate_patch_count": len(UNIT40_IMMEDIATE_PATCHES),
        "word_patch_count": len(UNIT40_WORD_PATCHES),
        "allowed_ranges": allowed_ranges,
    }
    return bytes(patched), report


def _base_status_with_names(status: str) -> str:
    values = {
        "nonrelease-partial-chapter-build": (
            "nonrelease-partial-chapter-build-with-character-names"
        ),
        "nonrelease-fixed-original-offset-overflow-diagnostic": (
            "nonrelease-fixed-original-offset-overflow-diagnostic-"
            "with-character-names"
        ),
    }
    if status not in values:
        raise ValueError(f"unsupported base file-build status: {status}")
    return values[status]


def build_character_name_patch(
    *,
    file_build_dir: Path,
    slps_path: Path,
    names_path: Path,
    glossary_path: Path,
    original_glyph_map_path: Path,
    font_profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    base_status = str(base_manifest.get("status"))
    output_status = _base_status_with_names(base_status)

    input_start = (file_build_dir / "START.BIN").read_bytes()
    input_allbin = (file_build_dir / "ALLBIN.BIN").read_bytes()
    built_map_path = file_build_dir / "primary-korean-glyph-map.json"
    for name, payload in (
        ("START.BIN", input_start),
        ("ALLBIN.BIN", input_allbin),
    ):
        expected = base_manifest["outputs"][name]["sha256"]
        if sha256_bytes(payload) != expected:
            raise ValueError(f"{name}: base file-build hash differs")

    source_paths = {
        name: Path(base_manifest["sources"][name]["path"])
        for name in ("START.BIN", "ALLBIN.BIN")
    }
    source_start = source_paths["START.BIN"].read_bytes()
    source_allbin = source_paths["ALLBIN.BIN"].read_bytes()
    source_slps = slps_path.read_bytes()
    for name, payload, expected in (
        ("START.BIN", source_start, EXPECTED_START_SHA256),
        ("ALLBIN.BIN", source_allbin, EXPECTED_ALLBIN_SHA256),
        ("SLPS_019.58", source_slps, EXPECTED_SLPS_SHA256),
    ):
        if sha256_bytes(payload) != expected:
            raise ValueError(f"{name}: verified original hash differs")

    names = load_object(names_path)
    glossary = approved_glossary_terms(glossary_path)
    fixed, records, safe_limit = validate_name_artifacts(names, glossary)
    built_mapping = load_built_primary_mapping(built_map_path)
    original_mapping, original_by_index = load_original_primary_maps(
        original_glyph_map_path
    )
    encoded_records, speaker_bytes = encode_speaker_records(
        records,
        built_mapping=built_mapping,
        original_mapping=original_mapping,
    )

    patched_start, alternate_report = _render_name_glyphs(
        input_start,
        font_profile_path=font_profile_path,
    )
    patched_allbin, editor_report = patch_unit40_name_editor(
        input_allbin,
        fixed,
    )
    patched_slps, speaker_report = patch_speaker_table(
        source_slps,
        records,
        encoded_records,
        safe_glyph_limit=safe_limit,
        original_by_index=original_by_index,
    )

    start_expected = verify_expected_writes(
        input_start,
        patched_start,
        allowed_ranges=alternate_report.pop("allowed_ranges"),
        owner="alternate fixed-name glyphs",
    )
    allbin_expected = verify_expected_writes(
        input_allbin,
        patched_allbin,
        allowed_ranges=editor_report.pop("allowed_ranges"),
        owner="unit40 fixed Korean name editor",
    )
    slps_expected = verify_expected_writes(
        source_slps,
        patched_slps,
        allowed_ranges=[
            (SPEAKER_STRING_START, SPEAKER_STRING_END),
            (
                SPEAKER_TABLE_OFFSET,
                SPEAKER_TABLE_OFFSET
                + SPEAKER_RECORD_COUNT * SPEAKER_RECORD_SIZE,
            ),
            (
                slps_address_to_file_offset(
                    SLPS_GIVEN_POINTER_START_INSTRUCTION
                ),
                slps_address_to_file_offset(
                    SLPS_GIVEN_POINTER_START_INSTRUCTION
                )
                + 4,
            ),
            (
                slps_address_to_file_offset(
                    SLPS_GIVEN_CLEAR_COUNT_INSTRUCTION
                ),
                slps_address_to_file_offset(
                    SLPS_GIVEN_CLEAR_COUNT_INSTRUCTION
                )
                + 4,
            ),
            *[
                (
                    slps_address_to_file_offset(instruction_address),
                    slps_address_to_file_offset(instruction_address) + 4,
                )
                for instruction_address, _, _ in (
                    SLPS_GIVEN_DEFAULT_STORE_PATCHES
                )
            ],
        ],
        owner="SLPS Korean speaker names and 2+4 name-code layout",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "START.BIN": patched_start,
        "ALLBIN.BIN": patched_allbin,
        "SLPS_019.58": patched_slps,
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
            "SLPS_019.58": {
                "path": str(slps_path.resolve()),
                "sha256": sha256_bytes(source_slps),
            },
            "base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
            "character_names": {
                "path": str(names_path.resolve()),
                "sha256": sha256_file(names_path),
            },
            "glossary": {
                "path": str(glossary_path.resolve()),
                "sha256": sha256_file(glossary_path),
            },
        },
        "character_names": {
            "status": "statically-verified-runtime-validation-required",
            "fixed_player_name": {
                "surname": fixed["surname"],
                "given_name": fixed["given_name"],
                "layout": "2+4 in the original six scratch glyphs",
            },
            "speaker_name_count": len(records),
            "speaker_safe_glyph_limit": safe_limit,
            "speaker_max_output_glyphs": max(
                len(record["ko"]) for record in records
            ),
            "speaker_string_bytes": speaker_bytes,
            "alternate_font": alternate_report,
            "name_editor": editor_report,
            "speaker_table": speaker_report,
        },
        "expected_writes": {
            **base_manifest.get("expected_writes", {}),
            "character_names": {
                "START.BIN_relative_to_base_build": start_expected,
                "ALLBIN.BIN_relative_to_base_build": allbin_expected,
                "SLPS_019.58_relative_to_original": slps_expected,
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
        "--slps",
        type=Path,
        default=Path("work/extracted/disc1/iso/SLPS_019.58"),
    )
    parser.add_argument(
        "--names",
        type=Path,
        default=Path("data/translations/disc1-character-names.json"),
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        default=Path(
            "data/translations/disc1-glossary-candidates.json"
        ),
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
    manifest = build_character_name_patch(
        file_build_dir=args.file_build_dir,
        slps_path=args.slps,
        names_path=args.names,
        glossary_path=args.glossary,
        original_glyph_map_path=args.glyph_map,
        font_profile_path=args.font_profile,
        output_dir=args.output_dir,
    )
    names = manifest["character_names"]
    print(
        f"fixed={names['fixed_player_name']['surname']}/"
        f"{names['fixed_player_name']['given_name']} "
        f"speakers={names['speaker_name_count']} "
        f"max={names['speaker_max_output_glyphs']} "
        f"SLPS={manifest['outputs']['SLPS_019.58']['sha256']}"
    )


if __name__ == "__main__":
    main()
