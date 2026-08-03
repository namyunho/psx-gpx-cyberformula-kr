from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from PIL import Image

from scripts.extract_cooking_speech_bubbles import (
    COMPONENTS,
    EXPECTED_MINI_G3_SHA256,
    PROJECT_ROOT,
    decode_4bpp,
    extract,
    pack_4bpp,
    sha256_bytes,
)


class CookingSpeechBubbleExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.disc1 = PROJECT_ROOT / "work/extracted/disc1/iso/MINI_G3.BIN"
        self.disc2 = PROJECT_ROOT / "work/extracted/disc2/iso/MINI_G3.BIN"
        if not self.disc1.is_file() or not self.disc2.is_file():
            self.skipTest("verified Disc 1/2 MINI_G3 extractions are unavailable")

    def test_decode_repack_round_trip(self) -> None:
        payload = bytes(range(256))
        indices = decode_4bpp(payload, 32, 16)
        self.assertEqual(pack_4bpp(indices, 32, 16), payload)

    def test_disc_sources_match_verified_hash(self) -> None:
        disc1 = self.disc1.read_bytes()
        disc2 = self.disc2.read_bytes()
        self.assertEqual(sha256_bytes(disc1), EXPECTED_MINI_G3_SHA256)
        self.assertEqual(disc1, disc2)

    def test_extracts_indexed_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            manifest = extract(
                disc1_source=self.disc1,
                disc2_source=self.disc2,
                output_dir=output,
            )
            self.assertEqual(len(manifest["components"]), len(COMPONENTS))
            self.assertEqual(
                manifest["composition"]["status"], "separate-storage-components"
            )
            for component in manifest["components"]:
                with Image.open(output / component["indexed_png"]) as image:
                    self.assertEqual(image.mode, "P")
                    self.assertEqual(image.size, tuple(component["rect"][2:]))
                    self.assertIsNotNone(image.info.get("transparency"))
                if component.get("runtime_clut"):
                    original_clut = output / component["original_clut_png"]
                    self.assertTrue(original_clut.is_file())
                    with Image.open(
                        output / component["original_clut_4x_png"]
                    ) as enlarged:
                        self.assertEqual(
                            enlarged.size,
                            tuple(value * 4 for value in component["rect"][2:]),
                        )


if __name__ == "__main__":
    unittest.main()
