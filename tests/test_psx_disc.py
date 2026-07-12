import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "psx_disc.py"
SPEC = importlib.util.spec_from_file_location("psx_disc", MODULE_PATH)
assert SPEC and SPEC.loader
psx_disc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = psx_disc
SPEC.loader.exec_module(psx_disc)


class DirectoryRecordTests(unittest.TestCase):
    def test_parse_file_record(self):
        name = b"SYSTEM.CNF;1"
        size = 33 + len(name)
        if size % 2:
            size += 1
        record = bytearray(size)
        record[0] = size
        record[2:6] = (23).to_bytes(4, "little")
        record[10:14] = (69).to_bytes(4, "little")
        record[32] = len(name)
        record[33 : 33 + len(name)] = name

        entries = list(psx_disc.parse_directory(bytes(record)))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "SYSTEM.CNF")
        self.assertEqual(entries[0].lba, 23)
        self.assertEqual(entries[0].size, 69)
        self.assertFalse(entries[0].is_directory)


if __name__ == "__main__":
    unittest.main()
