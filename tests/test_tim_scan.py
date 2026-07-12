import importlib.util
from pathlib import Path
import struct
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "tim_scan.py"
SPEC = importlib.util.spec_from_file_location("tim_scan", MODULE_PATH)
assert SPEC and SPEC.loader
tim_scan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tim_scan
SPEC.loader.exec_module(tim_scan)


class TimTests(unittest.TestCase):
    def test_parse_and_render_4bpp(self):
        clut = struct.pack("<I4H", 44, 0, 0, 16, 1)
        clut += struct.pack("<16H", *range(16))
        pixels = bytes([0x10, 0x32, 0x54, 0x76])
        image = struct.pack("<I4H", 16, 0, 0, 2, 1) + pixels
        data = struct.pack("<II", 0x10, 8) + clut + image

        parsed = tim_scan.parse_tim(data, 0)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.bpp, 4)
        self.assertEqual(parsed.pixel_width, 8)
        rendered = tim_scan.render_tim(data, parsed)
        self.assertEqual(rendered.size, (8, 1))


if __name__ == "__main__":
    unittest.main()
