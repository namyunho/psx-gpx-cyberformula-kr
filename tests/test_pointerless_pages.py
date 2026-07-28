from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.build_dialogue_chapter_patch import (
    encode_pointerless_entry,
    validate_pointerless_artifacts,
)
from scripts.extract_pointerless_pages import extract_pointerless_pages


ROOT = Path(__file__).resolve().parent.parent


class PointerlessPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workset_path = (
            ROOT
            / "work/translations/disc1-pointerless-pages-u00-u21.json"
        )
        cls.translation_path = (
            ROOT
            / "data/translations/disc1-pointerless-pages-u00-u21-ko.json"
        )
        cls.workset = json.loads(
            cls.workset_path.read_text(encoding="utf-8")
        )
        cls.translations = json.loads(
            cls.translation_path.read_text(encoding="utf-8")
        )

    def test_extractor_freezes_complete_u00_u21_population(self) -> None:
        extracted = extract_pointerless_pages(
            allbin_path=ROOT / "work/extracted/disc1/iso/ALLBIN.BIN",
            dialogue_workset_path=(
                ROOT / "work/translations/disc1-dialogue.json"
            ),
            glyph_map_path=ROOT / "data/glyph-map.json",
        )
        self.assertEqual(
            extracted["summary"],
            {
                "entry_count": 83,
                "choice_count": 29,
                "dialogue_count": 54,
                "reference_count": 87,
            },
        )
        self.assertEqual(
            [
                entry["entry_id"]
                for entry in extracted["entries"]
            ],
            [
                entry["entry_id"]
                for entry in self.workset["entries"]
            ],
        )
        self.assertEqual(
            [
                entry["original"]["sha256"]
                if "sha256" in entry["original"]
                else entry["source"]["sha256"]
                for entry in extracted["entries"]
            ],
            [
                entry["source"]["sha256"]
                for entry in self.workset["entries"]
            ],
        )

    def test_all_pointerless_translations_encode_with_preserved_controls(
        self,
    ) -> None:
        entries, translations = validate_pointerless_artifacts(
            self.workset,
            self.translations,
        )
        characters = sorted(
            {
                character
                for translation in translations.values()
                for text in (
                    translation.get("ko_segments")
                    or [translation.get("ko", "")]
                )
                for character in text
                if character != "\n"
            }
        )
        mapping = {
            character: index
            for index, character in enumerate(characters)
        }
        for entry_id, entry in entries.items():
            encoded, report = encode_pointerless_entry(
                entry,
                translations[entry_id],
                mapping,
            )
            self.assertTrue(encoded)
            self.assertTrue(report["immutable_controls_preserved"])
            for segment in report["segments"]:
                self.assertLessEqual(max(segment["line_widths"]), 17)
                if entry["classification"] == "pointerless_choice":
                    self.assertEqual(
                        segment["source_rows"],
                        segment["output_rows"],
                    )


if __name__ == "__main__":
    unittest.main()
