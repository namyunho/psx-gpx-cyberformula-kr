import tempfile
import unittest
from pathlib import Path

from scripts.build_font_poc import FONT_OFFSET
from scripts.psx_font import GLYPH_SIZE, pack_glyph
from scripts.render_font_poc_preview import render_preview


class RenderFontPocPreviewTests(unittest.TestCase):
    def test_renders_inserted_glyph_record(self) -> None:
        start = bytearray(FONT_OFFSET + GLYPH_SIZE)
        pixels = [0] * (14 * 14)
        pixels[1 * 14 + 1] = 1
        start[FONT_OFFSET : FONT_OFFSET + GLYPH_SIZE] = pack_glyph(pixels)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview.png"
            render_preview(
                bytes(start),
                ["가", "가"],
                {"가": "0x000"},
                output,
                scale=2,
            )

            from PIL import Image

            image = Image.open(output)
            self.assertEqual(image.size, (28, 56))
            self.assertEqual(image.getpixel((3, 3)), (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
