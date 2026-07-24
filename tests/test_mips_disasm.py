from pathlib import Path
import struct
import tempfile
import unittest

from scripts.mips_disasm import disassemble, disassemble_binary


class MipsDisasmTests(unittest.TestCase):
    def test_marks_branch_delay_slot(self) -> None:
        code = struct.pack(
            "<3I",
            0x0C000400,  # jal 0x80001000 from a KSEG0 base
            0x00000000,  # nop (delay slot)
            0x24020001,  # addiu v0, zero, 1
        )
        rows = disassemble(code, 0x80000000, file_offset=0x800)
        self.assertEqual(rows[0]["mnemonic"], "jal")
        self.assertFalse(rows[0]["delay_slot"])
        self.assertTrue(rows[1]["delay_slot"])
        self.assertEqual(rows[1]["file_offset"], "0x804")

    def test_maps_psx_exe_payload_to_load_address(self) -> None:
        image = bytearray(0x808)
        image[:8] = b"PS-X EXE"
        struct.pack_into("<4I", image, 0x10, 0x80030000, 0, 0x80030000, 8)
        struct.pack_into("<2I", image, 0x800, 0x24020001, 0x03E00008)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SLPS_TEST"
            path.write_bytes(image)
            result = disassemble_binary(path, start_offset=4, count=4)
        self.assertEqual(result["start_address"], 0x80030004)
        self.assertEqual(result["start_file_offset"], 0x804)
        self.assertEqual(result["instructions"][0]["mnemonic"], "jr")


if __name__ == "__main__":
    unittest.main()
