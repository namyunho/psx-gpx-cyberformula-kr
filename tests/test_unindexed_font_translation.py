from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.build_dialogue_chapter_patch import (
    FONT_GLYPH_COUNT,
    PROTECTED_ORIGINAL_GLYPH_INDICES,
    expand_fixed_names,
)
from scripts.build_unindexed_font_translation import (
    EXPECTED_AMBIGUOUS_PHYSICAL_ENTRY_COUNT,
    EXPECTED_NEW_UNIQUE_TEXT_COUNT,
    EXPECTED_WORKSET_ENTRY_COUNT,
    build_translation,
)
from scripts.dialogue_layout_editor import (
    FULL_GLYPH_ADVANCE_PX,
    measure_layout,
)


ROOT = Path(__file__).resolve().parents[1]


class UnindexedFontTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workset_path = (
            ROOT / "work/translations/disc1-unindexed-font-text.json"
        )
        cls.manual_path = (
            ROOT
            / "data/translations/disc1-unindexed-font-ko-manual.json"
        )
        cls.canonical_path = (
            ROOT / "data/translations/disc1-unindexed-font-ko.json"
        )
        cls.glyph_map_path = ROOT / "data/glyph-map.json"
        cls.previous_map_path = (
            ROOT
            / "work/build/"
            "dialogue-u00-u34-all-font-current-names-ui-special/"
            "primary-korean-glyph-map.json"
        )
        required = (
            cls.workset_path,
            cls.manual_path,
            cls.canonical_path,
            cls.glyph_map_path,
        )
        if not all(path.is_file() for path in required):
            raise unittest.SkipTest(
                "complete unindexed-font translation inputs unavailable"
            )
        cls.workset = json.loads(
            cls.workset_path.read_text(encoding="utf-8")
        )
        cls.canonical = json.loads(
            cls.canonical_path.read_text(encoding="utf-8")
        )

    def test_generated_translation_is_reproducible_and_complete(self) -> None:
        generated = build_translation(
            workset_path=self.workset_path,
            manual_path=self.manual_path,
            glyph_map_path=self.glyph_map_path,
        )

        generated["source_workset"] = self.canonical["source_workset"]
        generated["manual_translation_source"] = self.canonical[
            "manual_translation_source"
        ]
        self.assertEqual(generated, self.canonical)
        self.assertEqual(
            generated["summary"]["translation_count"],
            EXPECTED_WORKSET_ENTRY_COUNT,
        )
        self.assertEqual(
            generated["scope"]["new_unique_text_count"],
            EXPECTED_NEW_UNIQUE_TEXT_COUNT,
        )
        self.assertEqual(
            generated["scope"]["ambiguous_context_override_count"],
            EXPECTED_AMBIGUOUS_PHYSICAL_ENTRY_COUNT,
        )
        self.assertEqual(
            [entry["id"] for entry in generated["translations"]],
            [
                entry["entry_id"]
                for entry in self.workset["entries"]
            ],
        )
        self.assertTrue(
            all(
                entry["ko"]
                and entry["review_status"]
                == "needs-independent-and-runtime-review"
                for entry in generated["translations"]
            )
        )

    def test_every_new_translation_fits_its_reviewed_layout(self) -> None:
        translations = self.canonical["translations"]
        self.assertEqual(len(translations), len(self.workset["entries"]))
        for source, translation in zip(
            self.workset["entries"],
            translations,
        ):
            self.assertEqual(source["entry_id"], translation["id"])
            layout = source["layout"]
            measurement = measure_layout(
                translation["ko"],
                columns=layout["columns"],
                rows=layout["rows"],
            )
            allowance = translation.get("layout_overflow_allowance_px", 0)
            visual_fits = (
                len(measurement.lines) <= layout["rows"]
                and all(
                    width
                    <= layout["columns"] * FULL_GLYPH_ADVANCE_PX + allowance
                    for width in measurement.line_pixel_widths
                )
            )
            self.assertTrue(
                visual_fits,
                (
                    translation["id"],
                    measurement.limit_reasons,
                    measurement.line_widths,
                    measurement.line_pixel_widths,
                ),
            )

    def test_font_corpus_keeps_headroom_without_replacing_old_map(self) -> None:
        if not self.previous_map_path.is_file():
            self.skipTest("previous verified integrated font map unavailable")
        previous = json.loads(
            self.previous_map_path.read_text(encoding="utf-8")
        )["mapping"]
        previous_indices = {
            int(index, 16) for index in previous.values()
        }
        required = set(previous)
        for entry in self.canonical["translations"]:
            text = expand_fixed_names(entry["ko"])
            required.update(
                character
                for character in text
                if not character.isspace()
            )
            if any(character.isspace() for character in text):
                required.add(" ")

        protected_unmapped = (
            PROTECTED_ORIGINAL_GLYPH_INDICES - previous_indices
        )
        remaining = (
            FONT_GLYPH_COUNT
            - len(required)
            - len(protected_unmapped)
        )
        self.assertGreaterEqual(remaining, 160)


if __name__ == "__main__":
    unittest.main()
