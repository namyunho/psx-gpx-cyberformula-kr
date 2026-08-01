from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.build_character_name_patch import load_built_primary_mapping
from scripts.build_special_screen_patch import (
    encode_special_entry,
    validate_special_screen_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]


class GarageActionMenuPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workset_path = ROOT / "work/translations/disc1-special-screen-text.json"
        cls.translation_path = ROOT / "data/translations/disc1-special-screen-ko.json"
        cls.allbin_path = ROOT / "work/extracted/disc1/iso/ALLBIN.BIN"
        cls.mapping_path = (
            ROOT
            / "work/build/dialogue-all-reviewed-font-text-shadow-name-4x4-origin-graphics-2026-08-01"
            / "primary-korean-glyph-map.json"
        )
        if not all(
            path.is_file()
            for path in (
                cls.workset_path,
                cls.translation_path,
                cls.allbin_path,
                cls.mapping_path,
            )
        ):
            raise unittest.SkipTest("garage-menu build inputs unavailable")

    def test_two_runtime_menus_fit_their_fixed_slots(self) -> None:
        workset = json.loads(self.workset_path.read_text(encoding="utf-8"))
        translation = json.loads(self.translation_path.read_text(encoding="utf-8"))
        entries, _by_id, translations, validation = validate_special_screen_artifacts(
            workset,
            translation,
            workset_path=self.workset_path,
            source_allbin=self.allbin_path.read_bytes(),
        )
        menus = [entry for entry in entries if entry["classification"] == "garage_action_menu"]
        mapping = load_built_primary_mapping(self.mapping_path)
        reports = [
            encode_special_entry(entry, translations[entry["entry_id"]], mapping)[1]
            for entry in menus
        ]
        self.assertEqual(len(reports), 2)
        self.assertEqual(validation["layout_or_storage_issue_count"], 0)
        self.assertTrue(all(report["unused_tail_bytes"] >= 0 for report in reports))


if __name__ == "__main__":
    unittest.main()
