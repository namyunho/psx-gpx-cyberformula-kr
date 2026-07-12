import unittest

from scripts.ram_map import build_ram_index, find_mappings, summarize_mappings


class RamMapTests(unittest.TestCase):
    def test_finds_and_groups_loaded_fragment(self) -> None:
        source = bytes(range(128)) * 2
        ram = bytearray(b"\x00" * 1024)
        ram[300:428] = source[64:192]
        ram = bytes(ram)

        index = build_ram_index(ram, sample_size=32, stride=4)
        matches = find_mappings(
            ram,
            source,
            index,
            sample_size=32,
            source_stride=4,
            min_unique=8,
        )
        groups = summarize_mappings(matches)

        self.assertIn((236, 25, 64, 160), groups)


if __name__ == "__main__":
    unittest.main()
