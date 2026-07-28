from pathlib import Path
import json
import unittest

from scripts.export_special_screen_translation_brief import build_brief


ROOT = Path(__file__).resolve().parents[1]


class SpecialScreenTranslationBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workset_path = (
            ROOT / "work/translations/disc1-special-screen-text.json"
        )
        cls.draft_path = (
            ROOT / "data/translations/disc1-special-screen-ko.json"
        )
        if not cls.workset_path.is_file() or not cls.draft_path.is_file():
            raise unittest.SkipTest("special-screen translation inputs unavailable")
        cls.workset = json.loads(cls.workset_path.read_text(encoding="utf-8"))
        cls.draft = json.loads(cls.draft_path.read_text(encoding="utf-8"))

    def test_compact_handoff_has_stable_complete_ids(self) -> None:
        brief = build_brief(
            workset=self.workset,
            translation=self.draft,
            workset_path=self.workset_path,
            translation_path=self.draft_path,
        )
        source_ids = [entry["entry_id"] for entry in self.workset["entries"]]
        brief_ids = [entry["id"] for entry in brief["entries"]]
        self.assertEqual(brief_ids, source_ids)
        self.assertEqual(brief["summary"]["entry_count"], 391)

    def test_graphics_are_explicitly_excluded(self) -> None:
        brief = build_brief(
            workset=self.workset,
            translation=self.draft,
            workset_path=self.workset_path,
            translation_path=self.draft_path,
        )
        self.assertIn("그래픽 버튼", brief["summary"]["excluded"])


if __name__ == "__main__":
    unittest.main()
