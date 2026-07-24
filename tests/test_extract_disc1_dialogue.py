import hashlib
import struct
import unittest

from scripts.extract_disc1_dialogue import (
    NAME_PROFILES,
    STORY_CAPACITY,
    batch_documents,
    decode_original,
    measure_story_layout,
    token_hex,
    validate_workset,
)


class ExtractDisc1DialogueTests(unittest.TestCase):
    def test_decodes_known_and_unknown_glyphs_reversibly(self) -> None:
        decoded = decode_original(
            [0x000C, 0x0123, 0xFFFB, 0x8000],
            {0x000C: "（"},
        )
        self.assertEqual(
            decoded["text"],
            "（{glyph:0123}{align}{page_end}",
        )
        self.assertEqual(
            decoded["display_text"],
            "（{glyph:0123}\n{page_end}",
        )
        self.assertFalse(decoded["mapping_complete"])
        self.assertEqual(decoded["unmapped_glyphs"], ["0123"])

    def test_measures_verified_first_page_layout(self) -> None:
        tokens = (
            [0x0001] * 15
            + [0xFFFB]
            + [0x0001] * 16
            + [0x8000]
        )
        layout = measure_story_layout(
            tokens,
            name_profile=NAME_PROFILES["original_japanese"],
        )
        self.assertEqual(layout["positions"], 33)
        self.assertEqual(layout["alignment_padding"], 2)
        self.assertEqual(layout["row_occupied"], [15, 16, 0])
        self.assertTrue(layout["fits"])

    def test_exact_capacity_fits_and_next_position_fails(self) -> None:
        exact = measure_story_layout(
            [0x0001] * STORY_CAPACITY,
            name_profile=NAME_PROFILES["original_japanese"],
        )
        overflow = measure_story_layout(
            [0x0001] * (STORY_CAPACITY + 1),
            name_profile=NAME_PROFILES["original_japanese"],
        )
        self.assertTrue(exact["fits"])
        self.assertEqual(exact["row_occupied"], [17, 17, 17])
        self.assertFalse(overflow["fits"])
        self.assertEqual(overflow["overflow_positions"], 1)

    def test_align_at_column_boundary_adds_no_padding(self) -> None:
        layout = measure_story_layout(
            [0x0001] * 17 + [0xFFFB, 0x0001],
            name_profile=NAME_PROFILES["original_japanese"],
        )
        self.assertEqual(layout["alignment_padding"], 0)
        self.assertEqual(layout["positions"], 18)

    def test_fixed_korean_name_can_cross_alignment_boundary(self) -> None:
        tokens = [0x0001] * 14 + [0x6000, 0xFFFB] + [0x0001] * 24
        original = measure_story_layout(
            tokens,
            name_profile=NAME_PROFILES["original_japanese"],
        )
        korean = measure_story_layout(
            tokens,
            name_profile=NAME_PROFILES["korean_fixed"],
        )
        self.assertEqual(original["positions"], 41)
        self.assertEqual(original["alignment_padding"], 0)
        self.assertTrue(original["fits"])
        self.assertEqual(korean["positions"], 58)
        self.assertEqual(korean["alignment_padding"], 16)
        self.assertFalse(korean["fits"])

    def test_validator_rebuilds_raw_and_rejects_translation(self) -> None:
        raw = struct.pack("<2H", 0x0001, 0x8000)
        digest = hashlib.sha256(raw).hexdigest()
        document = {
            "schema_version": 2,
            "translation_generated": False,
            "summary": {
                "entry_count": 1,
                "generated_translation_count": 0,
            },
            "entries": [
                {
                    "entry_id": "disc1/allbin/u00/event_page/ref0000",
                    "source": {
                        "file_offset": "0x000000",
                        "byte_size": len(raw),
                        "sha256": digest,
                    },
                    "original": {
                        "raw_hex": raw.hex().upper(),
                        "tokens": [token_hex(0x0001), token_hex(0x8000)],
                        "japanese": {
                            "text": "、{page_end}",
                            "mapping_complete": True,
                            "unmapped_glyphs": [],
                        },
                    },
                    "translation": {
                        "full": {"text": "", "status": "untranslated"},
                        "abbreviated": {"text": "", "status": "untranslated"},
                    },
                }
            ],
        }
        validate_workset(document, raw)
        document["entries"][0]["translation"]["full"]["text"] = "번역"
        with self.assertRaisesRegex(ValueError, "leave full translation empty"):
            validate_workset(document, raw)

    def test_batches_do_not_cross_unit_boundaries(self) -> None:
        entries = []
        for unit_index, count in ((0, 3), (1, 2)):
            for index in range(count):
                entries.append(
                    {
                        "entry_id": f"unit-{unit_index}-entry-{index}",
                        "classification": "story",
                        "reachability": "main_path",
                        "source": {
                            "unit_index": unit_index,
                            "subsystem": "event_page",
                            "sha256": f"{unit_index:064x}",
                            "reference_count": 1,
                            "byte_size": 2,
                        },
                        "original": {
                            "japanese": {"mapping_complete": False}
                        },
                    }
                )
        document = {
            "workset_kind": "dialogue",
            "entries": entries,
        }
        batches = batch_documents(document, maximum_entries=2)
        self.assertEqual([len(batch["entries"]) for batch in batches], [2, 1, 2])
        self.assertEqual(
            [batch["batch"]["batch_id"] for batch in batches],
            [
                "dialogue-u00-part001",
                "dialogue-u00-part002",
                "dialogue-u01-part001",
            ],
        )
        self.assertTrue(
            all(
                len({entry["source"]["unit_index"] for entry in batch["entries"]}) == 1
                for batch in batches
            )
        )


if __name__ == "__main__":
    unittest.main()
