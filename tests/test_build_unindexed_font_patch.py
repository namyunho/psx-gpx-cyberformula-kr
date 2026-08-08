from __future__ import annotations

import struct
import unittest

from scripts.build_unindexed_font_patch import _pack_paged_stream_segment


def words(*values: int) -> bytes:
    return struct.pack(f"<{len(values)}H", *values)


class BuildUnindexedFontPatchTests(unittest.TestCase):
    def test_paged_stream_keeps_one_final_ffff_and_clears_old_tail(self) -> None:
        source = words(
            0x0010,
            0x8000,
            0x0020,
            0x8000,
            0x0030,
            0x8000,
            0xFFFF,
            0x0000,
        )
        output, report = _pack_paged_stream_segment(
            entry_id="cooking-test",
            source_segment=source,
            encoded_pages=[
                words(0x0100, 0x8000),
                words(0x0200, 0x8000),
                words(0x0300, 0x8000),
            ],
        )

        self.assertEqual(
            output,
            words(
                0x0100,
                0x8000,
                0x0200,
                0x8000,
                0x0300,
                0x8000,
                0xFFFF,
                0x0000,
            ),
        )
        self.assertEqual(report["source_page_count"], 3)
        self.assertEqual(report["encoded_page_count"], 3)
        self.assertEqual(report["stream_end_count"], 1)

    def test_paged_stream_rejects_dropped_page(self) -> None:
        with self.assertRaisesRegex(ValueError, "page count"):
            _pack_paged_stream_segment(
                entry_id="cooking-test",
                source_segment=words(
                    0x0010,
                    0x8000,
                    0x0020,
                    0x8000,
                    0xFFFF,
                ),
                encoded_pages=[words(0x0100, 0x8000)],
            )

    def test_paged_stream_rejects_missing_final_ffff(self) -> None:
        with self.assertRaisesRegex(ValueError, "no final 0xFFFF"):
            _pack_paged_stream_segment(
                entry_id="cooking-test",
                source_segment=words(0x0010, 0x8000, 0x0000),
                encoded_pages=[words(0x0100, 0x8000)],
            )


if __name__ == "__main__":
    unittest.main()
