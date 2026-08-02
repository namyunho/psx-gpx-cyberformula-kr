from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

from scripts.build_save_screen_patch import (
    SAVE_CACHE_CODE_BASES,
    SAVE_METADATA_END,
    SAVE_METADATA_START,
    SPEAKER_FREE_TAIL_END,
    SPEAKER_FREE_TAIL_START,
    SAVE_BUTTON_LABELS,
    _metadata_words,
    _outside_4bpp_offset,
    _save_name_words,
    patch_save_button_labels,
)


ROOT = Path(__file__).resolve().parent.parent


class SaveScreenPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document = json.loads(
            (
                ROOT
                / "work/build/dialogue-all-reviewed-font-text-shadow-name-4x4-origin-graphics-garage-menu-2026-08-01/primary-korean-glyph-map.json"
            ).read_text(encoding="utf-8")
        )
        cls.mapping = {
            character: int(value, 0)
            for character, value in document["mapping"].items()
        }

    def test_metadata_keeps_exact_original_region_size(self) -> None:
        words = _metadata_words(self.mapping)
        self.assertEqual(
            len(struct.pack(f"<{len(words)}H", *words)),
            SAVE_METADATA_END - SAVE_METADATA_START,
        )

    def test_save_name_stream_uses_only_four_given_name_glyphs(self) -> None:
        words = _save_name_words()
        self.assertEqual(
            len(struct.pack(f"<{len(words)}H", *words)),
            SPEAKER_FREE_TAIL_END - SPEAKER_FREE_TAIL_START,
        )
        for base in SAVE_CACHE_CODE_BASES:
            self.assertNotIn(base, words)
            self.assertNotIn(base + 3, words)
            self.assertIn(base + 4, words)
            self.assertIn(base + 7, words)
        terminal = words.index(0xFFFF)
        self.assertTrue(all(word == 0 for word in words[terminal + 1 :]))

    def test_button_patch_changes_only_proven_label_rectangles(self) -> None:
        original = (ROOT / "work/extracted/disc1/iso/OUTSIDE.BIN").read_bytes()
        patched, report, allowed = patch_save_button_labels(
            original,
            original,
            font_profile_path=ROOT / "config/font-profile.json",
        )
        changed = {
            index
            for index, (before, after) in enumerate(zip(original, patched))
            if before != after
        }
        permitted: set[int] = set()
        for start, end in allowed:
            permitted.update(range(start, end))
        self.assertTrue(changed)
        self.assertTrue(changed <= permitted)
        self.assertEqual([item["text"] for item in report["labels"]], ["예", "아니오"])
        self.assertEqual(len(allowed), len(SAVE_BUTTON_LABELS) * 16)
        for _, _, x, y, width, height in SAVE_BUTTON_LABELS:
            for row in range(y, y + height):
                start, _ = _outside_4bpp_offset(x, row)
                end, _ = _outside_4bpp_offset(x + width - 1, row)
                self.assertIn((start, end + 1), allowed)

    def test_outside_4bpp_rows_use_vram_halfword_width(self) -> None:
        row_zero, _ = _outside_4bpp_offset(0, 0)
        row_one, _ = _outside_4bpp_offset(0, 1)
        self.assertEqual(row_one - row_zero, 512)


if __name__ == "__main__":
    unittest.main()
