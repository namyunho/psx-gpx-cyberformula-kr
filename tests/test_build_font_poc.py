import struct
import unittest

from io import BytesIO

from scripts.build_font_poc import (
    RAW_SECTOR_SIZE,
    USER_DATA_OFFSET,
    patch_poc_files,
    patch_raw_fragment,
)
from scripts.psx_font import GLYPH_SIZE


class BuildFontPocTests(unittest.TestCase):
    def test_patches_only_glyph_and_token(self) -> None:
        start = bytes(200)
        allbin = bytearray(32)
        struct.pack_into("<H", allbin, 10, 0x1234)
        glyph = bytes(range(GLYPH_SIZE))

        patched_start, patched_allbin = patch_poc_files(
            start,
            bytes(allbin),
            glyph,
            font_offset=20,
            glyph_index=1,
            token_offset=10,
            expected_token=0x1234,
        )

        self.assertEqual(patched_start[20 + GLYPH_SIZE : 20 + 2 * GLYPH_SIZE], glyph)
        self.assertEqual(struct.unpack_from("<H", patched_allbin, 10)[0], 1)
        self.assertEqual(len(patched_start), len(start))
        self.assertEqual(len(patched_allbin), len(allbin))

    def test_rejects_nonblank_slot(self) -> None:
        with self.assertRaises(ValueError):
            patch_poc_files(
                bytes([1]) * GLYPH_SIZE,
                struct.pack("<H", 2),
                bytes(GLYPH_SIZE),
                font_offset=0,
                glyph_index=0,
                token_offset=0,
                expected_token=2,
            )

    def test_patches_mode2_form1_user_data(self) -> None:
        sector = bytearray(RAW_SECTOR_SIZE)
        sector[15] = 2
        image = BytesIO(sector)

        changed = patch_raw_fragment(
            image,
            file_lba=0,
            file_offset=7,
            expected=b"\0\0",
            replacement=b"\x12\x34",
        )

        self.assertEqual(changed, {0})
        patched = image.getvalue()
        self.assertEqual(
            patched[USER_DATA_OFFSET + 7 : USER_DATA_OFFSET + 9], b"\x12\x34"
        )


if __name__ == "__main__":
    unittest.main()
