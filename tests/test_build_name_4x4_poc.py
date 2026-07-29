from __future__ import annotations

import struct
import unittest

from scripts.build_name_4x4_poc import (
    CACHE_BASES_4X4,
    CACHE_ENDS_INCLUSIVE_4X4,
    CACHE_REGION_END,
    DYNAMIC_NAME_WIDTHS,
    GIVEN_NAME_BUFFER_4X4,
    LIVE_NAME_BUFFER,
    LIVE_NAME_END,
    NAME_BITMAP_BACKWARD_INITIAL,
    NAME_BITMAP_BYTES,
    NAME_BITMAP_DWORDS,
    NAME_BITMAP_FORWARD_LIMIT,
    SAVE_NAME_BASES_4X4,
    SAVE_SLOT_NEXT_HEADER_BASES,
    STATIC_GIVEN_CODE_ADDRESS,
    STATIC_NAME_CODES,
    STATIC_SURNAME_CODE_ADDRESS,
    UNIT39_FORWARD_LIMIT_ADDRESSES,
    UNIT40_INPUT_FORM_FRAME_SOURCES,
    UNIT40_INPUT_FORM_HELPER_START,
    UNIT40_INPUT_FORM_SOURCE_WORDS,
    UNIT40_NAME_DISPLAY_STREAM_PATCHES,
    UNIT40_SIZE,
    _patch_immediate,
    _patch_unit40_input_form_with_armips,
    _patch_word,
)
from scripts.psx_font import GLYPH_SIZE


class Name4x4PocTests(unittest.TestCase):
    def test_live_and_cache_layout_is_contiguous(self) -> None:
        self.assertEqual(GLYPH_SIZE, 74)
        self.assertEqual(NAME_BITMAP_BYTES, 592)
        self.assertEqual(NAME_BITMAP_DWORDS, 148)
        self.assertEqual(NAME_BITMAP_FORWARD_LIMIT, 0x94)
        self.assertEqual(NAME_BITMAP_BACKWARD_INITIAL, 0x93)
        self.assertEqual(GIVEN_NAME_BUFFER_4X4, 0x8002AEB4)
        self.assertEqual(LIVE_NAME_END, 0x8002AFDC)
        self.assertEqual(
            CACHE_BASES_4X4,
            (0x8002AFDC, 0x8002B22C, 0x8002B47C, 0x8002B6CC),
        )
        self.assertEqual(
            CACHE_ENDS_INCLUSIVE_4X4,
            (0x8002B228, 0x8002B478, 0x8002B6C8, 0x8002B918),
        )
        self.assertEqual(CACHE_REGION_END, 0x8002B91C)
        self.assertEqual(
            LIVE_NAME_BUFFER + 5 * NAME_BITMAP_BYTES,
            CACHE_REGION_END,
        )

    def test_save_name_blocks_end_at_next_slot_headers(self) -> None:
        self.assertEqual(
            SAVE_NAME_BASES_4X4,
            (0x801F07B0, 0x801F0EB0, 0x801F15B0, 0x801F1CB0),
        )
        self.assertTrue(
            all(
                start + NAME_BITMAP_BYTES == next_header
                for start, next_header in zip(
                    SAVE_NAME_BASES_4X4,
                    SAVE_SLOT_NEXT_HEADER_BASES,
                )
            )
        )

    def test_static_virtual_codes_cover_all_eight_glyphs(self) -> None:
        self.assertEqual(STATIC_NAME_CODES, tuple(range(0x4CE, 0x4D6)))
        self.assertEqual(STATIC_SURNAME_CODE_ADDRESS, 0x8004F35C)
        self.assertEqual(STATIC_GIVEN_CODE_ADDRESS, 0x8004F364)
        self.assertEqual(
            STATIC_GIVEN_CODE_ADDRESS - STATIC_SURNAME_CODE_ADDRESS,
            8,
        )
        self.assertEqual(
            DYNAMIC_NAME_WIDTHS,
            {"{name:surname}": 4, "{name:given}": 4},
        )

    def test_unit39_copy_census_has_all_nineteen_loops(self) -> None:
        self.assertEqual(len(UNIT39_FORWARD_LIMIT_ADDRESSES), 19)
        self.assertEqual(len(set(UNIT39_FORWARD_LIMIT_ADDRESSES)), 19)

    def test_unit40_display_streams_use_four_plus_four_codes(self) -> None:
        self.assertEqual(
            UNIT40_NAME_DISPLAY_STREAM_PATCHES,
            (
                (
                    0x8009F960,
                    bytes.fromhex(
                        "FD FF CE 04 CF 04 D0 04 FF FF 00 00"
                    ),
                    bytes.fromhex(
                        "FD FF CE 04 CF 04 D0 04 D1 04 FF FF"
                    ),
                ),
                (
                    0x8009F96C,
                    bytes.fromhex(
                        "FD FF D1 04 D2 04 D3 04 FF FF 00 00"
                    ),
                    bytes.fromhex(
                        "FD FF D2 04 D3 04 D4 04 D5 04 FF FF"
                    ),
                ),
            ),
        )
        for _, _, replacement in UNIT40_NAME_DISPLAY_STREAM_PATCHES:
            tokens = struct.unpack("<6H", replacement)
            self.assertEqual(tokens[0], 0xFFFD)
            self.assertEqual(tokens[-1], 0xFFFF)

    def test_patch_helpers_require_exact_source(self) -> None:
        immediate = bytearray(struct.pack("<I", 0x28A2006F))
        _patch_immediate(
            immediate,
            file_offset=0,
            expected=0x006F,
            replacement=0x0094,
            owner="test",
        )
        self.assertEqual(struct.unpack("<I", immediate)[0], 0x28A20094)
        with self.assertRaisesRegex(ValueError, "immediate differs"):
            _patch_immediate(
                immediate,
                file_offset=0,
                expected=0x006F,
                replacement=0x0094,
                owner="test",
            )

        word = bytearray(struct.pack("<I", 0x00641021))
        _patch_word(
            word,
            file_offset=0,
            expected=0x00641021,
            replacement=0x3C028004,
            owner="test",
        )
        self.assertEqual(struct.unpack("<I", word)[0], 0x3C028004)
        with self.assertRaisesRegex(ValueError, "word differs"):
            _patch_word(
                word,
                file_offset=0,
                expected=0x00641021,
                replacement=0x3C028004,
                owner="test",
            )

    def test_unit40_input_form_is_assembled_as_four_plus_four(self) -> None:
        overlay = bytearray(UNIT40_SIZE)
        for address, words in UNIT40_INPUT_FORM_SOURCE_WORDS:
            struct.pack_into(
                f"<{len(words)}I",
                overlay,
                address - 0x80098000,
                *words,
            )
        for address, payload in UNIT40_INPUT_FORM_FRAME_SOURCES:
            offset = address - 0x80098000
            overlay[offset : offset + len(payload)] = payload

        patched, report = _patch_unit40_input_form_with_armips(
            bytes(overlay)
        )

        create_offset = 0x8009B594 - 0x80098000
        create_words = struct.unpack_from("<3I", patched, create_offset)
        self.assertEqual(create_words[0], 0x24030088)
        self.assertEqual(
            create_words[1],
            0x08000000
            | ((UNIT40_INPUT_FORM_HELPER_START >> 2) & 0x03FFFFFF),
        )
        self.assertEqual(create_words[2], 0xA4431B00)

        surname_frame = 0x8009EA1C - 0x80098000
        given_frame = 0x8009EA34 - 0x80098000
        self.assertEqual(patched[surname_frame + 6], 58)
        self.assertEqual(
            struct.unpack_from("<h", patched, surname_frame + 8)[0],
            10,
        )
        self.assertEqual(patched[given_frame + 6], 58)

        positions = struct.unpack_from(
            "<8h",
            patched,
            0x800A0B80 - 0x80098000,
        )
        self.assertEqual(
            positions,
            (150, 164, 178, 192, 216, 230, 244, 258),
        )
        self.assertTrue(report["roman_slot_layout_unchanged"])


if __name__ == "__main__":
    unittest.main()
