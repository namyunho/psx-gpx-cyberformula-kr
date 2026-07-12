import struct
import unittest

from scripts.trace_remap_path import (
    DEFAULT_CURSOR_ROOT_SLOT,
    DEFAULT_DIALOGUE_RAM,
    DEFAULT_TEXT_ROOT_SLOT,
    RAM_BASE,
    RamView,
    scan_mips_references,
    trace_ram_state,
)


def ram_address_offset(address: int) -> int:
    return address - RAM_BASE


class TraceRemapPathTests(unittest.TestCase):
    def test_traces_dialogue_pointer_chain(self) -> None:
        ram = bytearray(0x200000)
        text_state = 0x8001426C
        cursor_state = 0x8001425A
        tokens = [0x903F, 0x000C, 0x008C, 0xFFFB]

        struct.pack_into("<I", ram, ram_address_offset(DEFAULT_TEXT_ROOT_SLOT), text_state)
        struct.pack_into("<I", ram, ram_address_offset(DEFAULT_CURSOR_ROOT_SLOT), cursor_state)
        struct.pack_into("<I", ram, ram_address_offset(text_state), DEFAULT_DIALOGUE_RAM)
        struct.pack_into("<H", ram, ram_address_offset(cursor_state), len(tokens))
        struct.pack_into(f"<{len(tokens)}H", ram, ram_address_offset(DEFAULT_DIALOGUE_RAM), *tokens)
        struct.pack_into(
            f"<{len(tokens)}H",
            ram,
            ram_address_offset(text_state + 4),
            *tokens,
        )

        state = trace_ram_state(RamView(bytes(ram)), dialogue_tokens=len(tokens))

        self.assertEqual(state["text_state"], "0x8001426C")
        self.assertEqual(state["cursor_state"], "0x8001425A")
        self.assertEqual(state["source_base_from_text_state"], "0x800A8054")
        self.assertTrue(state["source_base_matches_expected"])
        self.assertEqual(state["cursor_target_from_source_base"], "0x800A805C")
        self.assertEqual(state["token_rows"][0]["candidate_remap_entry"], "0x903F")
        self.assertTrue(state["token_rows"][2]["same_as_source"])

    def test_scans_lui_memory_access_references(self) -> None:
        words = [
            0x3C028006,  # lui v0, 0x8006
            0x8C421158,  # lw v0, 0x1158(v0)
            0x3C038001,  # lui v1, 0x8001
            0x9463426C,  # lhu v1, 0x426c(v1)
        ]
        code = struct.pack(f"<{len(words)}I", *words)

        hits = scan_mips_references(
            code,
            0x80030000,
            [DEFAULT_TEXT_ROOT_SLOT, 0x8001426C],
            window=0,
        )

        self.assertEqual([hit["effective_address"] for hit in hits], ["0x80061158", "0x8001426C"])
        self.assertEqual(hits[0]["kind"], "memory-access")


if __name__ == "__main__":
    unittest.main()
