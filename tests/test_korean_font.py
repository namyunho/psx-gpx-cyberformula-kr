import unittest

from scripts.korean_font import (
    SOURCE_GLYPH_SIZE,
    crop_to_psx,
    rasterize_ttf_glyph,
    unpack_mono_glyph,
)
from scripts.psx_font import PIXEL_COUNT


class KoreanFontTests(unittest.TestCase):
    def test_unpack_big_endian_rows(self) -> None:
        source = bytes.fromhex("8001") + bytes(SOURCE_GLYPH_SIZE - 2)
        pixels = unpack_mono_glyph(source)

        self.assertEqual(pixels[:16], [1] + [0] * 14 + [1])

    def test_crop_removes_one_pixel_border(self) -> None:
        source = [0] * 256
        source[0] = 1
        source[1 * 16 + 1] = 1
        cropped = crop_to_psx(source)

        self.assertEqual(len(cropped), PIXEL_COUNT)
        self.assertEqual(sum(cropped), 7)
        self.assertEqual(cropped[0], 7)

    def test_ttf_rasterizer_rejects_multiple_characters(self) -> None:
        with self.assertRaises(ValueError):
            rasterize_ttf_glyph(object(), "가나")


if __name__ == "__main__":
    unittest.main()
