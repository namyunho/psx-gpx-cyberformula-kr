from pathlib import Path
import struct
import tempfile
import unittest

from scripts.wrap_psx_overlay import build_psx_exe, extract_range


class WrapPsxOverlayTests(unittest.TestCase):
    def test_builds_a_minimal_psx_exe(self) -> None:
        payload = bytes(range(64))
        image = build_psx_exe(
            payload,
            load_address=0x8006D000,
            entry=0x8006D010,
            title="ALLBIN unit 35",
        )
        self.assertEqual(image[:8], b"PS-X EXE")
        self.assertEqual(
            struct.unpack_from("<4I", image, 0x10),
            (0x8006D010, 0, 0x8006D000, len(payload)),
        )
        self.assertEqual(image[0x800:], payload)

    def test_rejects_entry_outside_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "entry"):
            build_psx_exe(
                b"\0" * 16,
                load_address=0x8006D000,
                entry=0x8006D010,
            )

    def test_extracts_an_exact_source_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "container.bin"
            path.write_bytes(bytes(range(32)))
            self.assertEqual(
                extract_range(path, offset=8, size=8),
                bytes(range(8, 16)),
            )

    def test_rejects_range_past_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "container.bin"
            path.write_bytes(b"\0" * 16)
            with self.assertRaisesRegex(ValueError, "exceeds"):
                extract_range(path, offset=12, size=8)


if __name__ == "__main__":
    unittest.main()
