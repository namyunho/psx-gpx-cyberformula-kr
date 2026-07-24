import unittest

from scripts.psx_portrait_inventory import (
    PALETTE_SIZE,
    PORTRAIT_BLOCK_SIZE,
    decode_portrait,
    inventory_unit,
    occupied_block_count,
)


class PsxPortraitInventoryTests(unittest.TestCase):
    def test_finds_blocks_before_sector_padding(self) -> None:
        unit = bytearray(PORTRAIT_BLOCK_SIZE * 2 + 0x500)
        unit[0] = 1
        unit[PORTRAIT_BLOCK_SIZE + 10] = 2
        self.assertEqual(occupied_block_count(bytes(unit)), 2)

    def test_preserves_zero_block_inside_occupied_range(self) -> None:
        unit = bytearray(PORTRAIT_BLOCK_SIZE * 3)
        unit[0] = 1
        unit[PORTRAIT_BLOCK_SIZE * 2] = 2
        report = inventory_unit(bytes(unit), unit_index=41, file_offset=0x1000)
        self.assertEqual(report["occupied_block_count"], 3)
        self.assertTrue(report["records"][1]["all_zero"])

    def test_decodes_48_by_56_4bpp_image(self) -> None:
        block = bytearray(PORTRAIT_BLOCK_SIZE)
        block[2:4] = (0x001F).to_bytes(2, "little")
        block[PALETTE_SIZE:] = bytes([0x11]) * (
            PORTRAIT_BLOCK_SIZE - PALETTE_SIZE
        )
        image = decode_portrait(bytes(block), unit_index=41, block_index=0)
        self.assertEqual(image.size, (48, 56))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))


if __name__ == "__main__":
    unittest.main()
