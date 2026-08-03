import json
from pathlib import Path
import unittest

from scripts.build_name_origin_graphics_patch import (
    TARGETS,
    centered_origin,
    decode_4bpp,
    encode_4bpp,
    layout_ink_bounds,
    validate_translations,
)


class NameOriginGraphicsPatchTests(unittest.TestCase):
    def test_4bpp_round_trip_preserves_nibble_order(self) -> None:
        payload = bytes.fromhex("10 32 FE")
        indices = decode_4bpp(payload)
        self.assertEqual(indices, [0, 1, 2, 3, 14, 15])
        self.assertEqual(encode_4bpp(indices), payload)

    def test_translation_layout_rejects_overlong_line(self) -> None:
        entries = []
        for entry_id in TARGETS:
            entries.append(
                {
                    "id": entry_id,
                    "lines": ["가"],
                    "max_columns": 1,
                    "max_rows": 1,
                }
            )
        entries[0]["lines"] = ["가나"]
        with self.assertRaisesRegex(ValueError, "exceeds 1 columns"):
            validate_translations(
                {"schema_version": 1, "translations": entries}
            )

    def test_current_translation_covers_every_declared_rectangle(self) -> None:
        path = Path("data/translations/disc1-name-origin-graphics-ko.json")
        translation = json.loads(path.read_text(encoding="utf-8"))
        entries = validate_translations(translation)
        self.assertEqual(set(entries), set(TARGETS))

    def test_declared_rectangles_do_not_overlap(self) -> None:
        targets = list(TARGETS.items())
        for index, (left_id, left) in enumerate(targets):
            lx0, ly0, lx1, ly1 = left["box"]
            self.assertEqual(lx0 % 2, 0, left_id)
            self.assertEqual(lx1 % 2, 0, left_id)
            for right_id, right in targets[index + 1 :]:
                rx0, ry0, rx1, ry1 = right["box"]
                overlaps = (
                    max(lx0, rx0) < min(lx1, rx1)
                    and max(ly0, ry0) < min(ly1, ry1)
                )
                self.assertFalse(overlaps, f"{left_id} overlaps {right_id}")

    def test_centered_layout_uses_actual_ink_and_shadow_bounds(self) -> None:
        glyph = [0] * (14 * 14)
        glyph[1 * 14 + 2] = 1
        glyph[10 * 14 + 9] = 1
        bounds = layout_ink_bounds(
            ["가가"],
            glyphs={"가": glyph},
            advance=11,
            line_pitch=16,
            shadow_x_offset=1,
            shadow_y_offset=1,
        )
        self.assertEqual(bounds, (2, 1, 21, 11))
        origin = centered_origin((100, 40, 132, 56), bounds)
        placed = (
            origin[0] + bounds[0],
            origin[1] + bounds[1],
            origin[0] + bounds[2],
            origin[1] + bounds[3],
        )
        self.assertEqual(placed, (106, 42, 125, 52))

    def test_current_palette_policy_is_bright_ink_gray_shadow(self) -> None:
        path = Path("data/translations/disc1-name-origin-graphics-ko.json")
        translation = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            translation["policy"]["palette_indices"],
            {"shadow": 6, "ink": 1},
        )


if __name__ == "__main__":
    unittest.main()
