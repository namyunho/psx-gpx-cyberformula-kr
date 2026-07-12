import struct
import tempfile
import unittest
from pathlib import Path

from io import BytesIO

from scripts.build_font_poc import (
    DIALOGUE_LINES,
    DIALOGUE_REGION_OFFSET,
    DIALOGUE_REGION_TOKENS,
    RAW_SECTOR_SIZE,
    USER_DATA_OFFSET,
    patch_poc_files,
    patch_dialogue_poc_files,
    patch_raw_fragment,
    write_poc_cue,
)
from scripts.psx_font import GLYPH_SIZE


class BuildFontPocTests(unittest.TestCase):
    def test_patches_full_dialogue_in_place(self) -> None:
        start = bytes(0x40000)
        allbin = bytearray(0x200)
        struct.pack_into("<H", allbin, DIALOGUE_REGION_OFFSET, 0x903F)
        struct.pack_into("<H", allbin, DIALOGUE_REGION_OFFSET + 16 * 2, 0xFFFB)
        struct.pack_into("<H", allbin, DIALOGUE_REGION_OFFSET + 33 * 2, 0x8000)
        hangul = {
            character
            for character in "".join(DIALOGUE_LINES)
            if "가" <= character <= "힣"
        }
        glyphs = {
            character: bytes([index + 1]) * GLYPH_SIZE
            for index, character in enumerate(sorted(hangul))
        }

        patched_start, patched_allbin, mapping = patch_dialogue_poc_files(
            start, bytes(allbin), glyphs
        )

        tokens = struct.unpack_from(
            f"<{DIALOGUE_REGION_TOKENS}H", patched_allbin, DIALOGUE_REGION_OFFSET
        )
        self.assertEqual(tokens[0], 0x903F)
        self.assertEqual(tokens[16], 0xFFFB)
        self.assertEqual(tokens[17], 0x0000)
        self.assertEqual(tokens[-1], 0x8000)
        self.assertEqual(len(mapping), len(hangul) + 6)
        self.assertEqual(len(patched_start), len(start))
        self.assertEqual(len(patched_allbin), len(allbin))

    def test_patches_only_glyph_and_token(self) -> None:
        start = bytes(200)
        allbin = bytearray(32)
        struct.pack_into("<H", allbin, 10, 0x1234)
        glyph = bytes(range(GLYPH_SIZE))

        patched_start, patched_allbin = patch_poc_files(
            start,
            bytes(allbin),
            glyph,
            font_offset=20,
            glyph_index=1,
            token_offset=10,
            expected_token=0x1234,
        )

        self.assertEqual(patched_start[20 + GLYPH_SIZE : 20 + 2 * GLYPH_SIZE], glyph)
        self.assertEqual(struct.unpack_from("<H", patched_allbin, 10)[0], 1)
        self.assertEqual(len(patched_start), len(start))
        self.assertEqual(len(patched_allbin), len(allbin))

    def test_rejects_nonblank_slot(self) -> None:
        with self.assertRaises(ValueError):
            patch_poc_files(
                bytes([1]) * GLYPH_SIZE,
                struct.pack("<H", 2),
                bytes(GLYPH_SIZE),
                font_offset=0,
                glyph_index=0,
                token_offset=0,
                expected_token=2,
            )

    def test_patches_mode2_form1_user_data(self) -> None:
        sector = bytearray(RAW_SECTOR_SIZE)
        sector[15] = 2
        image = BytesIO(sector)

        changed = patch_raw_fragment(
            image,
            file_lba=0,
            file_offset=7,
            expected=b"\0\0",
            replacement=b"\x12\x34",
        )

        self.assertEqual(changed, {0})
        patched = image.getvalue()
        self.assertEqual(
            patched[USER_DATA_OFFSET + 7 : USER_DATA_OFFSET + 9], b"\x12\x34"
        )

    def test_writes_local_multitrack_cue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            (source / "track1.bin").write_bytes(b"one")
            (source / "track2.bin").write_bytes(b"two")
            source_cue = source / "disc.cue"
            source_cue.write_text(
                'FILE "track1.bin" BINARY\n  TRACK 01 MODE2/2352\n'
                'FILE "track2.bin" BINARY\n  TRACK 02 AUDIO\n',
                encoding="ascii",
            )
            track_output = output / "poc-track1.bin"
            track_output.write_bytes(b"patched")
            cue_output = output / "poc.cue"

            write_poc_cue(source_cue, track_output, cue_output)

            cue = cue_output.read_text(encoding="ascii")
            self.assertIn('FILE "poc-track1.bin" BINARY', cue)
            self.assertIn('FILE "track2.bin" BINARY', cue)
            self.assertEqual((output / "track2.bin").read_bytes(), b"two")


if __name__ == "__main__":
    unittest.main()
