from __future__ import annotations

from pathlib import Path
import unittest

from PIL import Image

from scripts.build_chapter_graphics_patch import (
    CHAPTER_SIZE,
    PROJECT_ROOT,
    STORED_SIZE,
    chapter_assets,
    scatter_chapter_screen,
)
from scripts.extract_title_chapter_graphics import assemble_chapter_screen


class ChapterGraphicsPatchTests(unittest.TestCase):
    def test_population_is_units_24_through_34(self) -> None:
        assets = chapter_assets()
        self.assertEqual(len(assets), 11)
        self.assertEqual([asset["unit"] for asset in assets], list(range(24, 35)))

    def test_scatter_preserves_gap_remainder_and_bottom_rows(self) -> None:
        stored = bytes((index * 17 + 3) & 0xFF for index in range(512 * 256))
        replacement = bytes((index * 29 + 5) & 0xFF for index in range(320 * 240))
        patched = scatter_chapter_screen(stored, replacement)
        reassembled = assemble_chapter_screen(Image.frombytes("L", STORED_SIZE, patched))
        self.assertEqual(bytes(reassembled.get_flattened_data()), replacement)
        for y in range(240):
            row = y * 512
            self.assertEqual(patched[row + 240 : row + 256], stored[row + 240 : row + 256])
            self.assertEqual(patched[row + 336 : row + 512], stored[row + 336 : row + 512])
        self.assertEqual(patched[240 * 512 :], stored[240 * 512 :])

    def test_all_user_exports_are_indexed_320x240(self) -> None:
        root = PROJECT_ROOT / "work/graphics/title-chapter/chapters"
        for asset in chapter_assets():
            path = root / asset["asset_id"] / "assembled-indexed-320x240-export.png"
            if not path.is_file():
                self.skipTest("chapter export inputs are unavailable")
            with Image.open(path) as image:
                self.assertEqual(image.mode, "P")
                self.assertEqual(image.size, CHAPTER_SIZE)


if __name__ == "__main__":
    unittest.main()
