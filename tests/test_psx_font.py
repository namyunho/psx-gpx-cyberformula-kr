import unittest

from scripts.psx_font import GLYPH_SIZE, PIXEL_COUNT, pack_glyph, unpack_glyph


class PsxFontTests(unittest.TestCase):
    def test_pack_unpack_round_trip(self) -> None:
        pixels = [(index * 5 + index // 14) & 7 for index in range(PIXEL_COUNT)]
        packed = pack_glyph(pixels)

        self.assertEqual(len(packed), GLYPH_SIZE)
        self.assertEqual(unpack_glyph(packed), pixels)

    def test_rejects_invalid_pixel(self) -> None:
        with self.assertRaises(ValueError):
            pack_glyph([8] + [0] * (PIXEL_COUNT - 1))


if __name__ == "__main__":
    unittest.main()
