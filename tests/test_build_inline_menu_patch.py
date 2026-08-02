from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

from scripts.build_character_name_patch import load_built_primary_mapping
from scripts.build_inline_menu_patch import (
    INLINE_CANCEL_GLYPH_CAPACITY,
    INLINE_CANCEL_OFFSET,
    ORIGINAL_CANCEL_TOKENS,
    load_cancel_translation,
    patch_inline_cancel,
)


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "work/extracted/disc1/iso/ALLBIN.BIN"
FILE_BUILD = ROOT / "work/build/dialogue-all-reviewed-font-text-shadow-name-4x4-origin-graphics-garage-menu-2026-08-01"


class InlineMenuPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not BASE.is_file() or not FILE_BUILD.is_dir():
            raise unittest.SkipTest("inline menu build inputs unavailable")
        cls.source = BASE.read_bytes()
        cls.mapping = load_built_primary_mapping(
            FILE_BUILD / "primary-korean-glyph-map.json"
        )
        cls.translation = load_cancel_translation(
            ROOT / "data/translations/disc1-inline-menu-ko.json"
        )

    def test_source_slot_is_the_runtime_observed_cancel_literal(self) -> None:
        actual = struct.unpack_from("<5H", self.source, INLINE_CANCEL_OFFSET)
        self.assertEqual(actual, ORIGINAL_CANCEL_TOKENS)

    def test_patch_preserves_exact_fixed_slot(self) -> None:
        patched, report, allowed = patch_inline_cancel(
            self.source,
            self.mapping,
            self.translation,
        )
        changed = {
            index
            for index, (before, after) in enumerate(zip(self.source, patched))
            if before != after
        }
        permitted = set(range(*allowed[0]))
        self.assertTrue(changed)
        self.assertTrue(changed <= permitted)
        tokens = struct.unpack_from("<5H", patched, INLINE_CANCEL_OFFSET)
        self.assertEqual(tokens[:2], tuple(self.mapping[c] for c in "취소"))
        self.assertEqual(tokens[2:], (0, 0, 0))
        self.assertEqual(report["slot_glyphs"], INLINE_CANCEL_GLYPH_CAPACITY)


if __name__ == "__main__":
    unittest.main()
