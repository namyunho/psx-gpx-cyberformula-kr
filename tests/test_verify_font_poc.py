import unittest

from scripts.verify_font_poc import differing_offsets, expected_raw_changes


class VerifyFontPocTests(unittest.TestCase):
    def test_maps_logical_file_diff_to_raw_form1_user_data(self) -> None:
        original = bytes(2050)
        patched = bytearray(original)
        patched[2047] = 1
        patched[2048] = 2

        changes = expected_raw_changes(10, original, bytes(patched))

        self.assertEqual(
            changes,
            {
                10 * 2352 + 24 + 2047: 1,
                11 * 2352 + 24: 2,
            },
        )

    def test_reports_only_differing_offsets(self) -> None:
        self.assertEqual(differing_offsets(b"\x00\x01", b"\x02\x01"), {0})


if __name__ == "__main__":
    unittest.main()
