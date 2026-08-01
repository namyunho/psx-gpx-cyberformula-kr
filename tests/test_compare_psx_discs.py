import unittest

from scripts.compare_psx_discs import (
    SYNC,
    byte_differences,
    normalized_sector_content,
)


class ComparePsxDiscsTests(unittest.TestCase):
    def test_normalized_form2_ignores_msf_and_edc(self) -> None:
        first = bytearray(2352)
        first[:12] = SYNC
        first[12:16] = bytes((1, 2, 3, 2))
        first[16:20] = bytes((1, 2, 0x24, 4))
        first[20:24] = first[16:20]
        first[24:2348] = bytes((index % 251 for index in range(2324)))
        first[2348:] = b"ABCD"
        second = bytearray(first)
        second[12:15] = bytes((9, 8, 7))
        second[2348:] = b"WXYZ"
        self.assertEqual(
            normalized_sector_content(bytes(first)),
            normalized_sector_content(bytes(second)),
        )

    def test_byte_differences_reports_offsets(self) -> None:
        self.assertEqual(
            byte_differences(b"abc", b"axz"),
            [
                {"offset": 1, "offset_hex": "0x1", "left": 98, "right": 120},
                {"offset": 2, "offset_hex": "0x2", "left": 99, "right": 122},
            ],
        )


if __name__ == "__main__":
    unittest.main()
