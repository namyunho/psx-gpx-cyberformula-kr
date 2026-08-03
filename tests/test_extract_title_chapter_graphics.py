from __future__ import annotations

import unittest

from PIL import Image

from scripts.extract_title_chapter_graphics import (
    ASSETS,
    assemble_chapter_screen,
    purple_composite,
)


class TitleChapterGraphicsTests(unittest.TestCase):
    def test_expected_population_is_one_title_and_eleven_cards(self) -> None:
        self.assertEqual(len(ASSETS), 12)
        self.assertEqual(sum(asset["category"] == "title" for asset in ASSETS), 1)
        self.assertEqual(sum(asset["category"] == "chapter" for asset in ASSETS), 11)
        self.assertEqual([asset["unit"] for asset in ASSETS], [8, *range(24, 35)])

    def test_purple_preview_preserves_opaque_and_marks_transparent(self) -> None:
        source = Image.new("RGBA", (2, 1))
        source.putdata([(10, 20, 30, 255), (1, 2, 3, 0)])
        preview = purple_composite(source)
        self.assertEqual(preview.mode, "RGB")
        self.assertEqual(preview.getpixel((0, 0)), (10, 20, 30))
        self.assertEqual(preview.getpixel((1, 0)), (255, 0, 255))

    def test_chapter_screen_removes_wrap_gap_and_joins_right_80_pixels(self) -> None:
        source = Image.new("L", (512, 256), 0)
        for x in range(240):
            source.putpixel((x, 0), 1)
        for x in range(240, 256):
            source.putpixel((x, 0), 2)
        for x in range(256, 336):
            source.putpixel((x, 0), 3)
        screen = assemble_chapter_screen(source)
        self.assertEqual(screen.size, (320, 240))
        self.assertEqual(
            list(screen.crop((0, 0, 320, 1)).get_flattened_data()),
            [1] * 240 + [3] * 80,
        )


if __name__ == "__main__":
    unittest.main()
