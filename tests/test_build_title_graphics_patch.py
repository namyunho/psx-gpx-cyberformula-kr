from __future__ import annotations

from pathlib import Path
import unittest

from PIL import Image

from scripts.build_special_screen_patch import sha256_file
from scripts.build_title_graphics_patch import (
    EXPECTED_START_SHA256,
    PURPLE,
    TITLE_SIZE,
    _title_records,
    remap_edited_title,
)
from scripts.psx_vram_render import bgr555_color, palette_words, record_from_bytes


ROOT = Path(__file__).resolve().parents[1]


class TitleGraphicsPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_root = ROOT / "work/extracted/disc1/iso"
        self.start_path = self.source_root / "START.BIN"
        if not self.start_path.is_file():
            self.skipTest("Disc 1 extraction is unavailable")
        source = self.start_path.read_bytes()
        self.payload_start, self.payload_end, self.palette, self.indices = (
            _title_records(source, self.source_root, "SLPS_019.58")
        )

    def _original_rgb(self) -> Image.Image:
        record = record_from_bytes(
            b"\x00\x00\x00\x00\x00\x01\x01\x00" + self.palette,
            8,
            4,
        )
        colors = [bgr555_color(word)[:3] for word in palette_words(record)]
        image = Image.new("RGB", TITLE_SIZE)
        image.putdata([colors[index] for index in self.indices])
        return image

    def test_original_revision_and_payload_range(self) -> None:
        self.assertEqual(sha256_file(self.start_path), EXPECTED_START_SHA256)
        self.assertEqual(self.payload_end - self.payload_start, 384 * 256)

    def test_visual_roundtrip_preserves_duplicate_indices(self) -> None:
        remapped, report = remap_edited_title(
            self._original_rgb(),
            palette_payload=self.palette,
            original_indices=self.indices,
        )
        self.assertEqual(remapped, self.indices)
        self.assertEqual(report["visually_changed_pixel_count"], 0)

    def test_purple_becomes_transparent_without_changing_size(self) -> None:
        image = self._original_rgb()
        opaque_position = next(
            index for index, value in enumerate(self.indices) if value != 0
        )
        image.putpixel(
            (opaque_position % TITLE_SIZE[0], opaque_position // TITLE_SIZE[0]),
            PURPLE,
        )
        remapped, report = remap_edited_title(
            image,
            palette_payload=self.palette,
            original_indices=self.indices,
        )
        self.assertEqual(len(remapped), len(self.indices))
        self.assertEqual(remapped[opaque_position], 0)
        self.assertGreater(report["visually_changed_pixel_count"], 0)


if __name__ == "__main__":
    unittest.main()
