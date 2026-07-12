import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "gdb_dump.py"
SPEC = importlib.util.spec_from_file_location("gdb_dump", MODULE_PATH)
assert SPEC and SPEC.loader
gdb_dump = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gdb_dump
SPEC.loader.exec_module(gdb_dump)


class FakeClient:
    def __init__(self):
        self.connect_count = 0

    def connect(self):
        self.connect_count += 1

    def read_memory(self, address, size, retries=3):
        return bytes((address + index) & 0xFF for index in range(size))


class DumpTests(unittest.TestCase):
    def test_chunking_and_reconnect(self):
        client = FakeClient()
        data = gdb_dump.dump_memory(client, 0x1000, 10, 4, 2)
        self.assertEqual(data, bytes(range(10)))
        self.assertEqual(client.connect_count, 1)


if __name__ == "__main__":
    unittest.main()
