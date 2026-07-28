from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.build_ui_translation_patch import (
    ALTERNATE_UI_FIRST_GLYPH,
    alternate_ui_mapping,
    encode_ui_text,
    validate_ui_artifacts,
)


ROOT = Path(__file__).resolve().parent.parent


class UiTranslationBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workset = json.loads(
            (ROOT / "work/translations/disc1-ui.json").read_text(
                encoding="utf-8"
            )
        )
        cls.translations = json.loads(
            (ROOT / "data/translations/disc1-ui-ko.json").read_text(
                encoding="utf-8"
            )
        )

    def test_artifacts_cover_all_sixty_entries_and_four_literals(self) -> None:
        entries, translations, actions = validate_ui_artifacts(
            self.workset,
            self.translations,
        )
        self.assertEqual(len(entries), 60)
        self.assertEqual(len(translations), 4)
        self.assertEqual(
            sum(action != "translate" for action in actions.values()),
            56,
        )

    def test_all_translations_preserve_rows_and_fit_fixed_slots(self) -> None:
        entries, translations, _ = validate_ui_artifacts(
            self.workset,
            self.translations,
        )
        alternate = alternate_ui_mapping(
            item["ko"]
            for item in translations.values()
            if item["renderer"] == "alternate"
        )
        primary_characters = {
            character
            for item in translations.values()
            if item["renderer"] == "primary"
            for character in item["ko"]
            if character != "\n"
        }
        primary = {
            character: index
            for index, character in enumerate(sorted(primary_characters))
        }
        for entry_id, item in translations.items():
            mapping = primary if item["renderer"] == "primary" else alternate
            encoded, report = encode_ui_text(
                entries[entry_id],
                item["ko"],
                mapping,
            )
            self.assertLessEqual(
                len(encoded),
                entries[entry_id]["source"]["byte_size"],
            )
            self.assertEqual(report["source_rows"], report["output_rows"])

    def test_alternate_ui_allocation_follows_fixed_name_slots(self) -> None:
        mapping = alternate_ui_mapping(["아마 레이스\n랠리"])
        self.assertEqual(mapping[" "], 0x000)
        self.assertEqual(mapping["아"], ALTERNATE_UI_FIRST_GLYPH)
        self.assertEqual(
            sorted(index for character, index in mapping.items() if character != " "),
            list(
                range(
                    ALTERNATE_UI_FIRST_GLYPH,
                    ALTERNATE_UI_FIRST_GLYPH + len(mapping) - 1,
                )
            ),
        )

    def test_missing_preserved_palette_entry_is_rejected(self) -> None:
        altered = deepcopy(self.translations)
        altered["coverage"][0]["entry_id_range"] = (
            "disc1/allbin/u40/font_rendered_ui/e001..e046"
        )
        altered["coverage"][0]["expected_count"] = 46
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            validate_ui_artifacts(self.workset, altered)


if __name__ == "__main__":
    unittest.main()
