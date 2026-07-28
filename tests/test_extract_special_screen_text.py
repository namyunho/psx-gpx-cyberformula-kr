from pathlib import Path
import unittest

from scripts.extract_special_screen_text import (
    EXPECTED_COURSE_PAGE_COUNT,
    EXPECTED_MACHINE_SETTING_COUNT,
    EXPECTED_U38_COOKING_WORD_COUNT,
    EXPECTED_U38_DIRECT_DIALOGUE_COUNT,
    EXPECTED_U38_POINTER_PAGE_COUNT,
    extract_special_screen_text,
)


ROOT = Path(__file__).resolve().parents[1]


class ExtractSpecialScreenTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        allbin = ROOT / "work/extracted/disc1/iso/ALLBIN.BIN"
        if not allbin.is_file():
            raise unittest.SkipTest("verified extracted ALLBIN.BIN is unavailable")
        cls.document = extract_special_screen_text(
            allbin_path=allbin,
            glyph_map_path=ROOT / "data/glyph-map.json",
        )

    def test_expected_populations(self) -> None:
        summary = self.document["summary"]
        self.assertEqual(
            summary["u38_pointer_page_count"],
            EXPECTED_U38_POINTER_PAGE_COUNT,
        )
        self.assertEqual(
            summary["u38_direct_dialogue_count"],
            EXPECTED_U38_DIRECT_DIALOGUE_COUNT,
        )
        self.assertEqual(
            summary["u38_cooking_runtime_word_count"],
            EXPECTED_U38_COOKING_WORD_COUNT,
        )
        self.assertEqual(
            summary["u43_course_page_count"],
            EXPECTED_COURSE_PAGE_COUNT,
        )
        self.assertEqual(
            summary["u43_machine_setting_count"],
            EXPECTED_MACHINE_SETTING_COUNT,
        )

    def test_scope_excludes_graphical_assets(self) -> None:
        excluded = self.document["scope"]["excluded"]
        self.assertIn("baked graphical buttons", excluded)
        self.assertIn("baked graphical labels and title assets", excluded)

    def test_physical_ranges_do_not_overlap(self) -> None:
        by_unit: dict[int, list[tuple[int, int]]] = {}
        for entry in self.document["entries"]:
            unit = int(entry["source"]["unit_index"])
            start = int(entry["source"]["unit_offset"], 16)
            end = start + int(entry["source"]["byte_size"])
            by_unit.setdefault(unit, []).append((start, end))
        for ranges in by_unit.values():
            ranges.sort()
            for left, right in zip(ranges, ranges[1:]):
                self.assertLessEqual(left[1], right[0])


if __name__ == "__main__":
    unittest.main()
