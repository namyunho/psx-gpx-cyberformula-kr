from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from PIL import Image

from scripts.render_chapter_graphics_overview import render_overview


class ChapterGraphicsOverviewTests(unittest.TestCase):
    def test_renders_eleven_cards_as_three_by_four_grid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = []
            for index in range(11):
                path = root / f"chapter-{index + 1:02d}.png"
                Image.new("RGBA", (320, 240), (index, 20, 30, 255)).save(path)
                entries.append(
                    {
                        "asset_id": f"chapter-{index + 1:02d}",
                        "preview": {"path": str(path)},
                    }
                )
            output = root / "overview.png"
            render_overview(entries, output)
            with Image.open(output) as overview:
                self.assertEqual(overview.mode, "RGB")
                self.assertEqual(overview.size, (960, 1080))


if __name__ == "__main__":
    unittest.main()
