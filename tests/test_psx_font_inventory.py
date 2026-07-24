import unittest

from scripts.psx_font import GLYPH_SIZE
from scripts.psx_font_inventory import inventory_font_unit


class PsxFontInventoryTests(unittest.TestCase):
    def test_finds_last_nonzero_fixed_record(self) -> None:
        unit = bytearray(GLYPH_SIZE * 3 + 7)
        unit[0] = 1
        unit[GLYPH_SIZE * 2 + 1] = 2
        report = inventory_font_unit(
            bytes(unit),
            name="test",
            start_unit=2,
            file_offset=0x100,
            ram_address=0x80010000,
            selection="test",
        )
        self.assertEqual(report["record_capacity"], 3)
        self.assertEqual(report["last_nonzero_record_index"], 2)
        self.assertEqual(report["defined_slot_count"], 3)
        self.assertEqual(report["trailing_zero_byte_size"], 7)


if __name__ == "__main__":
    unittest.main()
