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
    UNIT40_TRANSLATED_ORIGIN_UI_STREAMS,
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

    def test_unit40_origin_prompt_and_options_are_protected(self) -> None:
        self.assertEqual(
            UNIT40_TRANSLATED_ORIGIN_UI_STREAMS,
            (
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
            ),
        )

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
            13,
        )
        self.assertEqual(patched[given_frame + 6], 58)
        self.assertEqual(
            struct.unpack_from("<h", patched, given_frame + 8)[0],
            77,
        )

        for surname_address, given_address in (
            (0x8009E92C, 0x8009E938),
            (0x8009E98C, 0x8009E998),
            (0x8009E9EC, 0x8009E9F8),
        ):
            surname = surname_address - 0x80098000
            given = given_address - 0x80098000
            self.assertEqual(patched[surname + 6], 58)
            self.assertEqual(patched[given + 6], 58)
            self.assertEqual(
                struct.unpack_from("<h", patched, surname + 8)[0],
                20,
            )
            self.assertEqual(
                struct.unpack_from("<h", patched, given + 8)[0],
                84,
            )

        completion_state = struct.unpack_from(
            "<I",
            patched,
            0x8009A574 - 0x80098000,
        )[0]
        reentry_length = struct.unpack_from(
            "<I",
            patched,
            0x80098370 - 0x80098000,
        )[0]
        self.assertEqual(completion_state, 0x24030003)
        self.assertEqual(reentry_length, 0x24020004)

        positions = struct.unpack_from(
            "<8h",
            patched,
            0x800A0B80 - 0x80098000,
        )
        self.assertEqual(
            positions,
            (153, 167, 181, 195, 214, 228, 242, 256),
        )
        select_kind_load = struct.unpack_from(
            "<I",
            patched,
            0x800A0A44 - 0x80098000,
        )[0]
        update_kind_load = struct.unpack_from(
            "<I",
            patched,
            0x800A0A84 - 0x80098000,
        )[0]
        self.assertEqual(select_kind_load, 0x8C6311F8)
        self.assertEqual(update_kind_load, 0x8D0811F8)
        self.assertEqual(report["inter_field_gap_pixels"], 6)
        self.assertEqual(report["prompt_frame_x_pixels"], [13, 77])
        self.assertEqual(
            report["confirmation_frame_x_pixels"],
            [20, 84],
        )
        self.assertEqual(report["completion_state"], 3)
        self.assertEqual(report["reentry_surname_length"], 4)
        self.assertEqual(
            report["input_kind_discriminator"],
            {
                "pointer_address": "0x800611F8",
                "japanese_value": 2,
                "transient_state_16_supported": True,
            },
        )
        self.assertTrue(report["roman_slot_layout_unchanged"])


if __name__ == "__main__":
    unittest.main()
