import importlib.util
from pathlib import Path
import struct
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "custom_text.py"
SPEC = importlib.util.spec_from_file_location("custom_text", MODULE_PATH)
assert SPEC and SPEC.loader
custom_text = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = custom_text
SPEC.loader.exec_module(custom_text)


class CustomTextTests(unittest.TestCase):
    def test_extract_rebuild_round_trip(self):
        tokens = [0x903F, 0x005E, 0xFFFB, 0x0000, 0x0049, 0xFFFB]
        data = struct.pack("<6H", *tokens)
        entries = list(custom_text.extract_entries(data, 0, len(data)))
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["tokens"], ["903F", "005E", "FFFB"])
        self.assertEqual(custom_text.rebuild(entries), data)

    def test_decode_tokens_marks_controls_and_unknowns(self):
        decoded = custom_text.decode_tokens(
            [0x000C, 0x0058, 0x8000, 0x1234],
            {"000C": "（", "0058": "こ"},
            {"8000": "<PAGE_WAIT>"},
        )
        self.assertEqual(decoded, "（こ<PAGE_WAIT><$1234>")


if __name__ == "__main__":
    unittest.main()
