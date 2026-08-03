from __future__ import annotations

from pathlib import Path
import unittest

from PIL import Image

from scripts.build_cooking_callout_graphics_patch import (
    CALLOUT_IDS,
    EDIT_FILENAMES,
    PROJECT_ROOT,
    _get_index,
    _set_index,
)


class CookingCalloutGraphicsPatchTests(unittest.TestCase):
    def test_packed_index_write_preserves_neighbor_nibble(self) -> None:
        payload = bytearray(b"\x00" * (0x18818 + 512 * 512 // 2))
        _set_index(payload, 0, 472, 0xA)
        _set_index(payload, 1, 472, 0x5)
        self.assertEqual(_get_index(payload, 0, 472), 0xA)
        self.assertEqual(_get_index(payload, 1, 472), 0x5)
        offset = 0x18818 + 472 * (512 // 2)
        self.assertEqual(payload[offset], 0x5A)

    def test_user_exports_remain_indexed_4bpp_sized(self) -> None:
        root = PROJECT_ROOT / "work/graphics/minigame/cooking/speech-bubbles"
        expected_sizes = {
            "callout-yakiagare": (56, 24),
            "callout-rendaa": (48, 24),
        }
        for component_id in CALLOUT_IDS:
            path = root / EDIT_FILENAMES[component_id]
            if not path.is_file():
                self.skipTest("cooking callout export inputs are unavailable")
            with Image.open(path) as image:
                self.assertEqual(image.mode, "P")
                self.assertEqual(image.size, expected_sizes[component_id])
                self.assertLessEqual(max(image.get_flattened_data()), 15)


if __name__ == "__main__":
    unittest.main()
