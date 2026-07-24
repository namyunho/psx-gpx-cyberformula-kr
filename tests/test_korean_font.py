import unittest
from pathlib import Path

from scripts.korean_font import (
    SOURCE_GLYPH_SIZE,
    crop_to_psx,
    load_font_profile,
    pack_profile_glyphs,
    rasterize_ttf_glyph,
    unpack_mono_glyph,
)
from scripts.psx_font import HEIGHT, PIXEL_COUNT, WIDTH, unpack_glyph


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

    def test_galmuri11_profile_preserves_all_glyphs_inside_centered_cell(self) -> None:
        profile = load_font_profile(
            Path(__file__).resolve().parent.parent / "config" / "font-profile.json"
        )
        characters = list(profile.glyph_map)
        packed = pack_profile_glyphs(profile, characters)

        self.assertEqual(profile.family, "Galmuri11")
        self.assertEqual(profile.ttf_size_px, 12)
        self.assertEqual(len(packed), 2350)
        self.assertEqual(len(set(packed.values())), 2350)

        points: list[tuple[int, int]] = []
        for glyph in packed.values():
            pixels = unpack_glyph(glyph)
            points.extend(
                (index % WIDTH, index // WIDTH)
                for index, value in enumerate(pixels)
                if value
            )
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        self.assertEqual(
            (min(xs), min(ys), max(xs), max(ys)),
            profile.ink_union,
        )
        self.assertTrue(all(0 <= x < WIDTH and 0 <= y < HEIGHT for x, y in points))


if __name__ == "__main__":
    unittest.main()
