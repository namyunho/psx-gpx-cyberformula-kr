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
    _metadata_words,
    _save_name_words,
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

    def test_save_name_stream_fills_verified_speaker_tail(self) -> None:
        words = _save_name_words()
        self.assertEqual(
            len(struct.pack(f"<{len(words)}H", *words)),
            SPEAKER_FREE_TAIL_END - SPEAKER_FREE_TAIL_START,
        )
        for base in SAVE_CACHE_CODE_BASES:
            self.assertIn(base, words)
            self.assertIn(base + 7, words)


if __name__ == "__main__":
    unittest.main()
