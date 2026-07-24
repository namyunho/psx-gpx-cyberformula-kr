from pathlib import Path
import struct
import tempfile
import unittest

from scripts.build_ida_db import psx_exe_metadata


class BuildIdaDbTests(unittest.TestCase):
    def test_reads_psx_exe_mapping(self) -> None:
        image = bytearray(0x808)
        image[:8] = b"PS-X EXE"
        struct.pack_into("<4I", image, 0x10, 0x80041C18, 0, 0x80030000, 8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SLPS_TEST"
            path.write_bytes(image)
            metadata = psx_exe_metadata(path)
        self.assertEqual(metadata["entry"], 0x80041C18)
        self.assertEqual(metadata["load_address"], 0x80030000)
        self.assertEqual(metadata["text_size"], 8)

    def test_rejects_truncated_payload(self) -> None:
        image = bytearray(0x800)
        image[:8] = b"PS-X EXE"
        struct.pack_into("<4I", image, 0x10, 0x80041C18, 0, 0x80030000, 8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SLPS_TEST"
            path.write_bytes(image)
            with self.assertRaisesRegex(ValueError, "truncated"):
                psx_exe_metadata(path)


if __name__ == "__main__":
    unittest.main()
