from __future__ import annotations

from pathlib import Path
import unittest

from scripts.build_dialogue_chapter_patch import FONT_OFFSET
from scripts.build_minigame_rule_graphics_patch import (
    BOTTOM_LABEL_TAIL_RECT,
    CLEAR_BANDS,
    EXPECTED_BOTTOM_LABEL_TAIL_SHA256,
    EXPECTED_MINI_G3_SHA256,
    EXPECTED_RUNTIME_OVERLAP_SHA256,
    LABELS,
    RUNTIME_OVERLAP_RECT,
    RULE_CACHE_ORIGIN,
    _packed_rect,
    _rect_indices,
    patch_rule_label_graphics,
)
from scripts.build_special_screen_patch import sha256_bytes
from scripts.psx_font import GLYPH_SIZE, HEIGHT, WIDTH, pack_glyph


ROOT = Path(__file__).resolve().parents[1]


class MinigameRuleGraphicsPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.disc1_path = ROOT / "work/extracted/disc1/iso/MINI_G3.BIN"
        self.disc2_path = ROOT / "work/extracted/disc2/iso/MINI_G3.BIN"
        if not self.disc1_path.is_file() or not self.disc2_path.is_file():
            self.skipTest("Disc 1/2 MINI_G3 extractions are unavailable")

    @staticmethod
    def _synthetic_font() -> tuple[bytes, dict[str, int]]:
        characters = sorted({character for entry in LABELS for character in entry["ko"]})
        mapping = {character: index for index, character in enumerate(characters)}
        start = bytearray(FONT_OFFSET + len(characters) * GLYPH_SIZE)
        for character, index in mapping.items():
            pixels = [0] * (WIDTH * HEIGHT)
            if character != " ":
                for coordinate in range(1, 11):
                    pixels[coordinate * WIDTH + coordinate] = 1
                    pixels[coordinate * WIDTH + coordinate + 1] = 6
                pixels[12 * WIDTH + 12] = 1
                pixels[12 * WIDTH + 13] = 6
            offset = FONT_OFFSET + index * GLYPH_SIZE
            start[offset : offset + GLYPH_SIZE] = pack_glyph(pixels)
        return bytes(start), mapping

    def test_original_discs_share_runtime_linked_source(self) -> None:
        disc1 = self.disc1_path.read_bytes()
        disc2 = self.disc2_path.read_bytes()
        self.assertEqual(disc1, disc2)
        self.assertEqual(sha256_bytes(disc1), EXPECTED_MINI_G3_SHA256)
        self.assertEqual(
            sha256_bytes(_packed_rect(disc1, RUNTIME_OVERLAP_RECT)),
            EXPECTED_RUNTIME_OVERLAP_SHA256,
        )

    def test_patch_preserves_cyan_guard_and_is_deterministic(self) -> None:
        source = self.disc1_path.read_bytes()
        start, mapping = self._synthetic_font()
        first, reports, allowed, _clut = patch_rule_label_graphics(
            source=source, base=source, start_bin=start, mapping=mapping
        )
        second = patch_rule_label_graphics(
            source=source, base=source, start_bin=start, mapping=mapping
        )[0]
        self.assertEqual(first, second)
        self.assertEqual(len(reports), len(LABELS) + 2)
        self.assertGreaterEqual(len(allowed), sum(rect[3] for rect in CLEAR_BANDS))
        self.assertNotEqual(
            _rect_indices(source, RUNTIME_OVERLAP_RECT),
            _rect_indices(first, RUNTIME_OVERLAP_RECT),
        )

        cache_x, cache_y = RULE_CACHE_ORIGIN
        cyan_guard = (cache_x + 240, cache_y, 32, 48)
        self.assertEqual(
            _rect_indices(source, cyan_guard),
            _rect_indices(first, cyan_guard),
        )

    def test_bottom_rule_titles_remove_only_verified_original_tail_pixels(self) -> None:
        self.assertEqual(CLEAR_BANDS[2], (16, 33, 224, 14))
        bottom = {
            entry["id"]: entry for entry in LABELS if entry["band"] == 2
        }
        self.assertEqual(set(bottom), {"catch_henri", "blackjack"})
        self.assertTrue(
            all(entry["vertical_shift_px"] == 2 for entry in bottom.values())
        )
        self.assertEqual(bottom["catch_henri"].get("horizontal_shift_px", 0), 0)
        self.assertEqual(bottom["blackjack"]["horizontal_shift_px"], 2)

        source = self.disc1_path.read_bytes()
        start, mapping = self._synthetic_font()
        patched, reports, _allowed, _clut = patch_rule_label_graphics(
            source=source, base=source, start_bin=start, mapping=mapping
        )
        report_by_id = {report["id"]: report for report in reports}
        self.assertEqual(report_by_id["catch_henri"]["vertical_shift_px"], 2)
        self.assertEqual(report_by_id["blackjack"]["vertical_shift_px"], 2)
        self.assertEqual(report_by_id["blackjack"]["horizontal_shift_px"], 2)
        cleanup = report_by_id["bottom_label_tail_cleanup"]
        self.assertEqual(cleanup["cache_rect"], list(BOTTOM_LABEL_TAIL_RECT))
        self.assertEqual(
            cleanup["source_indices_sha256"], EXPECTED_BOTTOM_LABEL_TAIL_SHA256
        )
        self.assertEqual(cleanup["removed_nontransparent_pixel_count"], 69)

        cache_x, cache_y = RULE_CACHE_ORIGIN
        # The final cache row is the last scanline of the two Japanese titles,
        # not a fourth item. Clear its frozen nontransparent source pixels,
        # then draw only the shifted Korean tail ink.
        source_tail = _rect_indices(source, (cache_x + 16, cache_y + 47, 224, 1))
        patched_tail = _rect_indices(patched, (cache_x + 16, cache_y + 47, 224, 1))
        self.assertNotEqual(source_tail, bytes(len(source_tail)))
        permitted_x: set[int] = set()
        for entry in bottom.values():
            rel_x, _rel_y = entry["position"]
            shift_x = entry.get("horizontal_shift_px", 0)
            for position, character in enumerate(entry["ko"]):
                if character == " ":
                    continue
                permitted_x.update(
                    {
                        rel_x + shift_x + position * WIDTH + 12,
                        rel_x + shift_x + position * WIDTH + 13,
                    }
                )
        for rel_x, (before, after) in enumerate(zip(source_tail, patched_tail), start=16):
            if rel_x not in permitted_x:
                self.assertEqual(after, 0, f"old title tail remains at x={rel_x}")

        left_border = (cache_x, cache_y + 47, 16, 1)
        cyan_guard_tail = (cache_x + 240, cache_y + 47, 32, 1)
        self.assertEqual(
            _rect_indices(patched, left_border), _rect_indices(source, left_border)
        )
        self.assertEqual(
            _rect_indices(patched, cyan_guard_tail),
            _rect_indices(source, cyan_guard_tail),
        )


if __name__ == "__main__":
    unittest.main()
