from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_minigame_graphics_patch import (
    EXPECTED_MINI_G3_SHA256,
    _rect_indices,
    patch_minigame_buttons,
)
from scripts.build_special_screen_patch import sha256_file


ROOT = Path(__file__).resolve().parents[1]


class MinigameGraphicsPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_path = ROOT / "work/extracted/disc1/iso/MINI_G3.BIN"
        if not self.source_path.is_file():
            self.skipTest("Disc 1 extraction is unavailable")
        self.translation_path = (
            ROOT / "data/translations/disc1-minigame-graphics-ko.json"
        )
        self.font_profile = ROOT / "config/font-profile.json"

    def test_source_revision_and_eight_runtime_button_sprites(self) -> None:
        self.assertEqual(sha256_file(self.source_path), EXPECTED_MINI_G3_SHA256)
        translation = json.loads(self.translation_path.read_text(encoding="utf-8"))
        source = self.source_path.read_bytes()
        patched, reports, allowed = patch_minigame_buttons(
            source, translation, font_profile_path=self.font_profile
        )
        self.assertEqual(len(reports), 8)
        self.assertEqual(len(allowed), 128)
        self.assertEqual(len(patched), len(source))
        for entry in translation["entries"]:
            rect = tuple(entry["texture_rect"])
            self.assertNotEqual(_rect_indices(source, rect), _rect_indices(patched, rect))
        for report in reports:
            source_bounds = report["source_visible_bounds"]
            replacement_bounds = report["replacement_visible_bounds"]
            self.assertLessEqual(
                abs(
                    source_bounds[0]
                    + source_bounds[2]
                    - replacement_bounds[0]
                    - replacement_bounds[2]
                ),
                1,
                report["id"],
            )
            self.assertLessEqual(
                abs(
                    source_bounds[1]
                    + source_bounds[3]
                    - replacement_bounds[1]
                    - replacement_bounds[3]
                ),
                1,
                report["id"],
            )

    def test_patch_is_deterministic(self) -> None:
        translation = json.loads(self.translation_path.read_text(encoding="utf-8"))
        source = self.source_path.read_bytes()
        first = patch_minigame_buttons(
            source, translation, font_profile_path=self.font_profile
        )[0]
        second = patch_minigame_buttons(
            source, translation, font_profile_path=self.font_profile
        )[0]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
