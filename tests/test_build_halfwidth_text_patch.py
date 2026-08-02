from pathlib import Path
import tempfile
import unittest

from scripts.build_halfwidth_text_patch import (
    EXE_FILE_BASE,
    HALFWIDTH_GLYPHS,
    RENDERER_END,
    RENDERER_START,
    patch_renderer,
)
from scripts.mips_disasm import disassemble_binary


ROOT = Path(__file__).resolve().parents[1]


class HalfwidthTextPatchTests(unittest.TestCase):
    def test_requested_glyph_ids_are_stable(self) -> None:
        self.assertEqual(
            HALFWIDTH_GLYPHS,
            {
                " ": 0x046,
                "!": 0x047,
                "(": 0x04B,
                ")": 0x04C,
                ",": 0x04D,
                ".": 0x04F,
                "?": 0x050,
            },
        )

    def test_armips_patch_is_confined_to_renderer(self) -> None:
        source = ROOT / "work/extracted/disc1/iso/SLPS_019.58"
        if not source.is_file():
            self.skipTest("verified extracted executable is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "SLPS_019.58"
            result = patch_renderer(
                source,
                output,
                ROOT / "asm/halfwidth-dialogue-renderer.asm",
            )
            self.assertGreater(result["changed_byte_count"], 0)
            before = source.read_bytes()
            after = output.read_bytes()
            start = RENDERER_START - EXE_FILE_BASE
            end = RENDERER_END - EXE_FILE_BASE
            self.assertEqual(before[:start], after[:start])
            self.assertEqual(before[end:], after[end:])

            instructions = {
                row["address"]: row
                for row in disassemble_binary(
                    output,
                    start_address=RENDERER_START,
                    count=RENDERER_END - RENDERER_START,
                )["instructions"]
            }
            self.assertEqual(
                instructions["0x8003285C"]["mnemonic"],
                "nop",
            )
            name_state_branch = instructions["0x80032918"]
            self.assertEqual(name_state_branch["mnemonic"], "beqz")
            self.assertEqual(
                name_state_branch["operands"],
                "$s3, 0x80032950",
            )

    def test_complete_build_keeps_dialogue_outputs_byte_exact(self) -> None:
        base = ROOT / "work/build" / (
            "dialogue-all-reviewed-font-text-shadow-name-4x4-origin-graphics-"
            "garage-menu-inline-menu-save-2026-08-02"
        )
        if not base.is_dir():
            self.skipTest("latest complete file build is unavailable")
        for name in ("START.BIN", "ALLBIN.BIN", "OUTSIDE.BIN"):
            self.assertTrue((base / name).is_file())


if __name__ == "__main__":
    unittest.main()
