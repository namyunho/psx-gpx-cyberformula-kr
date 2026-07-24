import unittest

from scripts.hex_dump import dump_rows, text_column


class HexDumpTests(unittest.TestCase):
    def test_ascii_column_replaces_controls(self) -> None:
        self.assertEqual(text_column(b"A\x00Z", "ascii"), "A.Z")

    def test_u16_rows_use_little_endian(self) -> None:
        rows = dump_rows(
            bytes.fromhex("34127856"),
            start=0x20,
            width=4,
            encoding="ascii",
            show_u16=True,
        )
        self.assertTrue(rows[0].startswith("00000020"))
        self.assertTrue(rows[0].endswith("1234 5678"))


if __name__ == "__main__":
    unittest.main()
