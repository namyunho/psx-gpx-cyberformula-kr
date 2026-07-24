import struct
import unittest

from scripts.psx_vram_render import (
    VramRecord,
    bgr555_color,
    decode_direct16,
    decode_indexed,
    render_unit,
)


class PsxVramRenderTests(unittest.TestCase):
    def test_converts_psx_bgr555(self) -> None:
        self.assertEqual(bgr555_color(0), (0, 0, 0, 0))
        self.assertEqual(bgr555_color(0x001F), (255, 0, 0, 255))
        self.assertEqual(bgr555_color(0x03E0), (0, 255, 0, 255))
        self.assertEqual(bgr555_color(0x7C00), (0, 0, 255, 255))

    def test_decodes_direct_16bpp(self) -> None:
        record = VramRecord(0, None, 0, 0, 2, 1, struct.pack("<2H", 0x1F, 0x3E0))
        image = decode_direct16(record)
        self.assertEqual(image.size, (2, 1))
        self.assertEqual(list(image.getdata()), [(255, 0, 0, 255), (0, 255, 0, 255)])

    def test_decodes_8bpp_two_pixels_per_halfword(self) -> None:
        record = VramRecord(0, 1, 0, 0, 1, 1, b"\x01\x02")
        palette = [0] * 256
        palette[1] = 0x1F
        palette[2] = 0x3E0
        image = decode_indexed(record, palette, 8)
        self.assertEqual(image.size, (2, 1))
        self.assertEqual(list(image.getdata()), [(255, 0, 0, 255), (0, 255, 0, 255)])

    def test_decodes_4bpp_low_nibble_first(self) -> None:
        record = VramRecord(0, 1, 0, 0, 1, 1, b"\x21\x43")
        palette = [index for index in range(16)]
        image = decode_indexed(record, palette, 4)
        self.assertEqual(image.size, (4, 1))
        expected = [bgr555_color(index) for index in (1, 2, 3, 4)]
        self.assertEqual(list(image.getdata()), expected)

    def test_renders_each_row_of_an_8bpp_palette_bank(self) -> None:
        image = VramRecord(0, 1, 0, 0, 1, 17, bytes([1, 0]) * 17)
        palette_words = [0] * 512
        palette_words[1] = 0x001F
        palette_words[257] = 0x03E0
        palette = VramRecord(
            0,
            0,
            0,
            0,
            256,
            2,
            struct.pack("<512H", *palette_words),
        )
        previews = render_unit([palette, image])
        self.assertEqual(len(previews), 2)
        self.assertTrue(previews[0].label.endswith("p0:0"))
        self.assertTrue(previews[1].label.endswith("p0:1"))


if __name__ == "__main__":
    unittest.main()
