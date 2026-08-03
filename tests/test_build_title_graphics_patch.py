from __future__ import annotations

from pathlib import Path
import unittest

from PIL import Image

from scripts.build_special_screen_patch import sha256_file
from scripts.build_title_graphics_patch import (
    EXPECTED_START_SHA256,
    IMAGE_ROW_BYTES,
    PURPLE,
    TITLE_ROW_BYTE_OFFSET,
    TITLE_SIZE,
    _authoring_bank,
    _component_labels,
    _pack_title_page,
    _palette_colors,
    _title_records,
    remap_edited_title,
)


ROOT = Path(__file__).resolve().parents[1]


class TitleGraphicsPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_root = ROOT / "work/extracted/disc1/iso"
        self.start_path = self.source_root / "START.BIN"
        if not self.start_path.is_file():
            self.skipTest("Disc 1 extraction is unavailable")
        source = self.start_path.read_bytes()
        (
            self.payload_start,
            self.payload_end,
            self.palette,
            self.image_payload,
            self.indices,
        ) = _title_records(source, self.source_root, "SLPS_019.58")

    def _original_rgba(self) -> Image.Image:
        colors = _palette_colors(self.palette)
        labels, boxes = _component_labels(self.indices)
        pixels = []
        for position, local_index in enumerate(self.indices):
            if local_index == 0:
                pixels.append((*PURPLE, 0))
                continue
            x = position % TITLE_SIZE[0]
            label = labels[position]
            box = boxes[label] if label >= 0 else None
            bank = _authoring_bank(x, local_index, box)
            pixels.append((*colors[bank * 16 + local_index], 255))
        image = Image.new("RGBA", TITLE_SIZE)
        image.putdata(pixels)
        return image

    def test_original_revision_and_payload_range(self) -> None:
        self.assertEqual(sha256_file(self.start_path), EXPECTED_START_SHA256)
        self.assertEqual(self.payload_end - self.payload_start, 512 * 256)
        self.assertEqual(len(self.indices), 256 * 256)

    def test_visual_roundtrip_preserves_local_4bpp_indices(self) -> None:
        remapped, report = remap_edited_title(
            self._original_rgba(),
            palette_payload=self.palette,
            original_indices=self.indices,
        )
        self.assertEqual(remapped, self.indices)
        self.assertEqual(report["visually_changed_pixel_count"], 0)

    def test_pack_roundtrip_preserves_unrelated_vram_columns(self) -> None:
        packed = _pack_title_page(self.image_payload, self.indices)
        self.assertEqual(packed, self.image_payload)
        for y in range(TITLE_SIZE[1]):
            row = y * IMAGE_ROW_BYTES
            self.assertEqual(
                packed[row : row + TITLE_ROW_BYTE_OFFSET],
                self.image_payload[row : row + TITLE_ROW_BYTE_OFFSET],
            )

    def test_purple_clears_an_opaque_pixel_in_editable_region(self) -> None:
        image = self._original_rgba()
        position = next(
            index
            for index, value in enumerate(self.indices)
            if value != 0
            and (
                (0 <= index % 256 < 137 and 2 <= index // 256 < 32)
                or (0 <= index % 256 < 220 and 56 <= index // 256 < 96)
            )
        )
        image.putpixel((position % 256, position // 256), (*PURPLE, 255))
        remapped, report = remap_edited_title(
            image,
            palette_payload=self.palette,
            original_indices=self.indices,
        )
        self.assertEqual(remapped[position], 0)
        self.assertEqual(report["visually_changed_pixel_count"], 1)

    def test_change_outside_title_text_regions_is_rejected(self) -> None:
        image = self._original_rgba()
        position = next(
            index
            for index, value in enumerate(self.indices)
            if value != 0 and index // 256 > 180 and index // 256 < 230
        )
        image.putpixel((position % 256, position // 256), (1, 2, 3, 255))
        with self.assertRaisesRegex(ValueError, "protected"):
            remap_edited_title(
                image,
                palette_payload=self.palette,
                original_indices=self.indices,
            )


if __name__ == "__main__":
    unittest.main()
