from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.build_special_screen_patch import (
    _base_status_with_special_screen,
    encode_special_entry,
    special_required_characters,
    validate_special_screen_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]


class BuildSpecialScreenPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workset_path = (
            ROOT / "work/translations/disc1-special-screen-text.json"
        )
        cls.translation_path = (
            ROOT / "data/translations/disc1-special-screen-ko.json"
        )
        cls.allbin_path = ROOT / "work/extracted/disc1/iso/ALLBIN.BIN"
        required = (
            cls.workset_path,
            cls.translation_path,
            cls.allbin_path,
        )
        if not all(path.is_file() for path in required):
            raise unittest.SkipTest("special-screen build inputs unavailable")
        cls.workset = json.loads(
            cls.workset_path.read_text(encoding="utf-8")
        )
        cls.translation = json.loads(
            cls.translation_path.read_text(encoding="utf-8")
        )
        (
            cls.entries,
            _by_id,
            cls.translations,
            cls.validation,
        ) = validate_special_screen_artifacts(
            cls.workset,
            cls.translation,
            workset_path=cls.workset_path,
            source_allbin=cls.allbin_path.read_bytes(),
        )

    def test_current_translation_population_fits_fixed_slots(self) -> None:
        required = special_required_characters(self.translations.values())
        mapping = {
            character: index for index, character in enumerate(required)
        }
        reports = [
            encode_special_entry(
                entry,
                self.translations[entry["entry_id"]],
                mapping,
            )[1]
            for entry in self.entries
        ]
        self.assertEqual(len(reports), 398)
        self.assertEqual(
            self.validation["layout_or_storage_issue_count"],
            0,
        )
        self.assertTrue(
            all(
                report["encoded_stream_bytes"]
                <= report["source_bytes"]
                for report in reports
            )
        )

    def test_dynamic_name_entries_store_name_as_one_control_word(self) -> None:
        required = special_required_characters(self.translations.values())
        mapping = {
            character: index for index, character in enumerate(required)
        }
        entry = next(
            entry
            for entry in self.entries
            if entry["entry_id"]
            == "disc1/allbin/u43/course_page/ref0027"
        )
        _replacement, report = encode_special_entry(
            entry,
            self.translations[entry["entry_id"]],
            mapping,
        )
        self.assertEqual(report["dynamic_name_token_count"], 1)
        self.assertLessEqual(
            report["stored_positions"],
            report["stored_capacity_positions"],
        )
        self.assertEqual(report["unused_tail_bytes"], 2)

    def test_status_requires_integrated_names_and_ui_build(self) -> None:
        status = _base_status_with_special_screen(
            "nonrelease-partial-chapter-build-with-character-names-and-ui"
        )
        self.assertTrue(status.endswith("-and-special-screen"))
        with self.assertRaisesRegex(ValueError, "unsupported base"):
            _base_status_with_special_screen(
                "nonrelease-partial-chapter-build"
            )


if __name__ == "__main__":
    unittest.main()
