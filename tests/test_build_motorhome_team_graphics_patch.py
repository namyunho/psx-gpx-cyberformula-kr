from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

from scripts.build_motorhome_team_graphics_patch import (
    CONSUMER_DESCRIPTORS,
    EXPECTED_AVM_MAP_SHA256,
    FOREGROUND_INDEX,
    SHADOW_INDEX,
    _rect_indices,
    patch_consumer_layout,
    patch_motorhome_team_labels,
)
from scripts.build_special_screen_patch import sha256_file


ROOT = Path(__file__).resolve().parents[1]


class MotorhomeTeamGraphicsPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_path = ROOT / "work/extracted/disc1/iso/AVM_MAP.BIN"
        self.allbin_path = ROOT / "work/extracted/disc1/iso/ALLBIN.BIN"
        if not self.source_path.is_file() or not self.allbin_path.is_file():
            self.skipTest("Disc 1 extraction is unavailable")
        self.translation_path = (
            ROOT / "data/translations/disc1-motorhome-team-graphics-ko.json"
        )
        self.font_profile = ROOT / "config/font-profile.json"

    def _patch(self) -> tuple[bytes, list[dict], list[tuple[int, int]], list[dict]]:
        translation = json.loads(self.translation_path.read_text(encoding="utf-8"))
        return patch_motorhome_team_labels(
            self.source_path.read_bytes(),
            translation,
            font_profile_path=self.font_profile,
            consumer_allbin=self.allbin_path.read_bytes(),
        )

    def test_source_consumers_and_nine_fragments(self) -> None:
        self.assertEqual(sha256_file(self.source_path), EXPECTED_AVM_MAP_SHA256)
        source = self.source_path.read_bytes()
        translation = json.loads(self.translation_path.read_text(encoding="utf-8"))
        patched, reports, allowed, consumers = self._patch()
        self.assertEqual(len(reports), 9)
        self.assertEqual(len(consumers), 9)
        self.assertEqual(len(allowed), 9 * 16)
        self.assertEqual(len(patched), len(source))
        for entry in translation["fragments"]:
            rect = tuple(entry["texture_rect"])
            before = _rect_indices(source, rect)
            after = _rect_indices(patched, rect)
            self.assertNotEqual(before, after)
            self.assertIn(FOREGROUND_INDEX, after)
            self.assertIn(SHADOW_INDEX, after)

    def test_patch_is_deterministic(self) -> None:
        first = self._patch()[0]
        second = self._patch()[0]
        self.assertEqual(first, second)

    def test_split_words_have_no_transparent_boundary_column(self) -> None:
        patched = self._patch()[0]
        translation = json.loads(self.translation_path.read_text(encoding="utf-8"))
        entries = {entry["id"]: entry for entry in translation["fragments"]}
        for left_id, right_id in (
            ("sturm-prefix", "sturm-remainder"),
            ("aoi-zip-formula-prefix", "aoi-zip-formula-remainder"),
        ):
            left = entries[left_id]
            right = entries[right_id]
            left_indices = _rect_indices(patched, tuple(left["texture_rect"]))
            right_indices = _rect_indices(patched, tuple(right["texture_rect"]))
            left_width = int(left["texture_rect"][2])
            right_width = int(right["texture_rect"][2])
            self.assertTrue(
                any(left_indices[row * left_width + left_width - 1] for row in range(16))
            )
            self.assertTrue(
                any(right_indices[row * right_width] for row in range(16))
            )

    def test_two_short_captions_shift_right_by_one_fullwidth_cell(self) -> None:
        source = self.allbin_path.read_bytes()
        translation = json.loads(self.translation_path.read_text(encoding="utf-8"))
        patched, reports, allowed = patch_consumer_layout(source, translation)
        self.assertEqual(len(reports), 2)
        self.assertEqual(len(allowed), 4)
        expected = {
            0x1018D0: (-64, -52),
            0x1018DC: (-16, -4),
            0x10190C: (-24, -12),
            0x101918: (-72, -60),
        }
        for offset, (old_x, new_x) in expected.items():
            self.assertEqual(struct.unpack_from("<h", source, offset + 8)[0], old_x)
            self.assertEqual(struct.unpack_from("<h", patched, offset + 8)[0], new_x)
        for offset, _ in CONSUMER_DESCRIPTORS:
            if offset not in expected:
                self.assertEqual(source[offset : offset + 12], patched[offset : offset + 12])


if __name__ == "__main__":
    unittest.main()
