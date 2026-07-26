from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

from scripts.build_character_name_patch import (
    ALTERNATE_FIXED_NAME_MAPPING,
    ALTERNATE_FONT_RUNTIME_ADDRESS,
    ALTERNATE_FONT_SCHEDULED_BYTE_SIZE,
    SLPS_GIVEN_CLEAR_COUNT_INSTRUCTION,
    SLPS_GIVEN_DEFAULT_STORE_PATCHES,
    SLPS_GIVEN_POINTER_START_INSTRUCTION,
    SPEAKER_STRING_END,
    SPEAKER_STRING_START,
    _patch_immediate,
    _patch_word,
    approved_glossary_terms,
    encode_speaker_records,
    validate_name_artifacts,
)
from scripts.psx_font import GLYPH_SIZE


ROOT = Path(__file__).resolve().parent.parent
NAMES_PATH = ROOT / "data/translations/disc1-character-names.json"
GLOSSARY_PATH = (
    ROOT / "data/translations/disc1-glossary-candidates.json"
)


class CharacterNamePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.names = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
        cls.glossary = approved_glossary_terms(GLOSSARY_PATH)

    def test_tracked_names_fit_verified_slots(self) -> None:
        fixed, records, safe_limit = validate_name_artifacts(
            self.names,
            self.glossary,
        )
        self.assertEqual(
            (fixed["surname"], fixed["given_name"]),
            ("시바", "세이치로"),
        )
        self.assertEqual(
            fixed["surname_glyphs"] + fixed["given_name_glyphs"],
            fixed["runtime_shared_glyph_slots"],
        )
        self.assertEqual(len(records), 34)
        self.assertEqual([record["index"] for record in records], list(range(34)))
        self.assertLessEqual(
            max(len(record["ko"]) for record in records),
            safe_limit,
        )
        self.assertEqual(
            sum(len(record["ko"]) for record in records) * 2,
            212,
        )
        self.assertLessEqual(
            212,
            SPEAKER_STRING_END - SPEAKER_STRING_START,
        )

    def test_every_character_glossary_reference_is_approved(self) -> None:
        records = self.names["speaker_name_table"]["records"]
        for record in records:
            term_id = record.get("glossary_term_id")
            if term_id is None:
                continue
            term = self.glossary[term_id]
            if term["category"] == "character":
                self.assertEqual(
                    term["status"],
                    "approved",
                    msg=f"{term_id} is used by speaker {record['index']}",
                )

    def test_fixed_alternate_glyphs_fit_scheduled_unit(self) -> None:
        last_end = (
            ALTERNATE_FONT_RUNTIME_ADDRESS
            + (max(ALTERNATE_FIXED_NAME_MAPPING.values()) + 1) * GLYPH_SIZE
        )
        scheduled_end = (
            ALTERNATE_FONT_RUNTIME_ADDRESS
            + ALTERNATE_FONT_SCHEDULED_BYTE_SIZE
        )
        self.assertEqual(last_end, 0x8019FEB4)
        self.assertEqual(scheduled_end, 0x801A3800)
        self.assertLessEqual(last_end, scheduled_end)

    def test_main_name_array_patches_cover_four_given_glyphs(self) -> None:
        self.assertEqual(SLPS_GIVEN_POINTER_START_INSTRUCTION, 0x80039F04)
        self.assertEqual(SLPS_GIVEN_CLEAR_COUNT_INSTRUCTION, 0x8003A6EC)
        self.assertEqual(
            SLPS_GIVEN_DEFAULT_STORE_PATCHES,
            (
                (0x8003A918, 0x0000, 0x0002),
                (0x8003A924, 0x0002, 0x0004),
                (0x8003A938, 0x0004, 0x0006),
            ),
        )

    def test_all_speaker_labels_are_encodable(self) -> None:
        records = self.names["speaker_name_table"]["records"]
        characters = sorted(
            {
                character
                for record in records
                for character in record["ko"]
            }
        )
        mapping = {
            character: index
            for index, character in enumerate(characters)
        }
        encoded, byte_count = encode_speaker_records(
            records,
            built_mapping=mapping,
            original_mapping={},
        )
        self.assertEqual(
            [len(values) for values in encoded],
            [len(record["ko"]) for record in records],
        )
        self.assertEqual(byte_count, 212)

    def test_instruction_patches_require_exact_source(self) -> None:
        immediate = bytearray(struct.pack("<I", 0x24030038))
        _patch_immediate(
            immediate,
            file_offset=0,
            expected=0x0038,
            replacement=0x0036,
            owner="test",
        )
        self.assertEqual(struct.unpack("<I", immediate)[0], 0x24030036)
        with self.assertRaisesRegex(ValueError, "immediate differs"):
            _patch_immediate(
                immediate,
                file_offset=0,
                expected=0x0038,
                replacement=0x0036,
                owner="test",
            )

        word = bytearray(struct.pack("<I", 0))
        _patch_word(
            word,
            file_offset=0,
            expected=0,
            replacement=0x24030004,
            owner="test",
        )
        self.assertEqual(struct.unpack("<I", word)[0], 0x24030004)
        with self.assertRaisesRegex(ValueError, "instruction differs"):
            _patch_word(
                word,
                file_offset=0,
                expected=0,
                replacement=0x24030004,
                owner="test",
            )


if __name__ == "__main__":
    unittest.main()
