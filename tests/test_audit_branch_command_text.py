from __future__ import annotations

from pathlib import Path
import unittest

from scripts.audit_branch_command_text import (
    DEFAULT_KNOWN_WORKSETS,
    audit_branch_commands,
)


ROOT = Path(__file__).resolve().parents[1]


class BranchCommandTextAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = (
            ROOT / "work/disc1/SLPS_019.58",
            ROOT / "work/disc1/ALLBIN.BIN",
            *(ROOT / path for path in DEFAULT_KNOWN_WORKSETS),
        )
        if not all(path.is_file() for path in required):
            raise unittest.SkipTest("verified Disc 1 audit inputs unavailable")
        cls.report = audit_branch_commands(
            exe_path=required[0],
            allbin_path=required[1],
            glyph_map_path=ROOT / "data/glyph-map.json",
            known_workset_paths=required[2:],
            inline_translation_path=(
                ROOT / "data/translations/disc1-inline-menu-ko.json"
            ),
        )

    def test_only_confirmed_missing_command_is_translated_cancel(self) -> None:
        self.assertEqual(
            self.report["summary"],
            {
                "confirmed_missing_command_count": 1,
                "confirmed_translated_command_count": 1,
                "new_unresolved_command_count": 0,
                "reviewed_false_positive_count": 9,
                "all_branch_terminals_covered": True,
            },
        )
        command = self.report["confirmed_missing_commands"][0]
        self.assertEqual(command["jp"], "キャンセル")
        self.assertEqual(command["ko"], "취소")

    def test_all_branch_terminals_are_in_stable_worksets(self) -> None:
        for token in ("D002", "D003"):
            self.assertEqual(self.report["control_coverage"][token]["uncovered"], 0)


if __name__ == "__main__":
    unittest.main()
