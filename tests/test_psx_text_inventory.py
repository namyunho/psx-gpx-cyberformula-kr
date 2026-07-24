import struct
import unittest

from scripts.psx_text_inventory import (
    EMBEDDED_RACE_LOAD_ADDRESS,
    aligned_in_unit_pointer_references,
    discover_pointer_table,
    inventory_embedded_race_text_unit,
    inventory_text_unit,
    inventory_overlay_ui,
    parse_entry,
    token_kind,
)


class PsxTextInventoryTests(unittest.TestCase):
    def test_discovers_trailing_pointer_table(self) -> None:
        unit = bytearray(0x40)
        struct.pack_into("<2H", unit, 0, 0x903F, 0x8000)
        struct.pack_into("<2I", unit, 0x20, 0x800A8000, 0x800A8000)
        struct.pack_into("<I", unit, 0x28, 2)
        table = discover_pointer_table(bytes(unit), load_address=0x800A8000)
        self.assertEqual(table["table_offset"], 0x20)
        self.assertEqual(table["entry_count"], 2)

    def test_rejects_pointer_outside_loaded_unit(self) -> None:
        unit = bytearray(0x20)
        struct.pack_into("<I", unit, 0x10, 0x800B8000)
        struct.pack_into("<I", unit, 0x14, 1)
        with self.assertRaisesRegex(ValueError, "outside"):
            discover_pointer_table(bytes(unit), load_address=0x800A8000)

    def test_parses_to_the_first_subsystem_terminal(self) -> None:
        unit = struct.pack("<4H", 0x903F, 0x12, 0x8000, 0xFFFF)
        entry = parse_entry(
            unit,
            pointer=0x800A8000,
            load_address=0x800A8000,
            limit_offset=len(unit),
            terminals=(0x8000,),
        )
        self.assertEqual(entry["token_count"], 3)
        self.assertEqual(entry["terminal"], 0x8000)
        self.assertEqual(entry["glyph_count"], 1)

    def test_extracts_speaker_portrait_and_style_fields(self) -> None:
        unit = struct.pack("<2H", 0x9AC5, 0x8000)
        entry = parse_entry(
            unit,
            pointer=0x800A8000,
            load_address=0x800A8000,
            limit_offset=len(unit),
            terminals=(0x8000,),
        )
        self.assertEqual(entry["_speaker_block_indices"], [43])
        self.assertEqual(entry["_speaker_style_indices"], [5])

    def test_inventory_counts_duplicate_pointer_aliases(self) -> None:
        unit = bytearray(0x40)
        struct.pack_into("<2H", unit, 0, 0x20, 0x8000)
        struct.pack_into("<2I", unit, 0x20, 0x800A8000, 0x800A8000)
        struct.pack_into("<I", unit, 0x28, 2)
        report = inventory_text_unit(bytes(unit), unit_index=0, file_offset=0x100)
        self.assertEqual(report["pointer_reference_count"], 2)
        self.assertEqual(report["unique_entry_point_count"], 1)
        self.assertEqual(report["duplicate_reference_count"], 1)

    def test_classifies_static_glyph_and_substitution_separately(self) -> None:
        self.assertEqual(token_kind(0x0123), "glyph")
        self.assertEqual(token_kind(0x4123), "substitution")
        self.assertEqual(token_kind(0xD003), "voice_or_transition")
        self.assertEqual(token_kind(0xFFFD), "pace")

    def test_inventories_explicit_overlay_ui_roots(self) -> None:
        unit = bytearray(0x9000)
        from scripts.psx_text_inventory import OVERLAY_UI_ENTRY_OFFSETS

        for offset in OVERLAY_UI_ENTRY_OFFSETS:
            struct.pack_into("<3H", unit, offset, 0xFFFD, 1, 0xFFFF)
        report = inventory_overlay_ui(bytes(unit), file_offset=0x1000)
        self.assertEqual(report["entry_count"], 60)
        self.assertEqual(report["glyph_index_max"], 1)

    def test_inventories_pointer_backed_mixed_overlay_text(self) -> None:
        unit = bytearray(0x100)
        stream_offset = 0x40
        struct.pack_into(
            "<4H",
            unit,
            stream_offset,
            0x903F,
            0x0012,
            0xFFFB,
            0xFFFF,
        )
        struct.pack_into(
            "<I",
            unit,
            0x80,
            EMBEDDED_RACE_LOAD_ADDRESS + stream_offset,
        )
        report = inventory_embedded_race_text_unit(
            bytes(unit),
            unit_index=30,
            file_offset=0x1000,
        )
        self.assertEqual(report["unique_entry_point_count"], 1)
        self.assertEqual(report["pointer_reference_count"], 1)
        self.assertEqual(report["entries"][0]["file_offset"], 0x1040)

    def test_rejects_u32_table_that_mimics_font_stream(self) -> None:
        unit = bytearray(0x100)
        table_offset = 0x40
        values = [0x18, 0x1F, 0x2A, 0x25, 0x63, 0x53, 0x10, 0]
        struct.pack_into(f"<{len(values)}I", unit, table_offset, *values)
        struct.pack_into("<2H", unit, table_offset + 0x20, 0x9A00, 0xFFFF)
        struct.pack_into(
            "<I",
            unit,
            0x80,
            EMBEDDED_RACE_LOAD_ADDRESS + table_offset,
        )
        report = inventory_embedded_race_text_unit(
            bytes(unit),
            unit_index=30,
            file_offset=0,
        )
        self.assertEqual(report["unique_entry_point_count"], 0)
        self.assertEqual(report["rejected_u32_value_table_count"], 1)

    def test_finds_all_aligned_in_unit_pointer_references(self) -> None:
        unit = bytearray(0x40)
        pointer = EMBEDDED_RACE_LOAD_ADDRESS + 0x20
        struct.pack_into("<2I", unit, 0, pointer, pointer)
        references = aligned_in_unit_pointer_references(
            bytes(unit),
            load_address=EMBEDDED_RACE_LOAD_ADDRESS,
        )
        self.assertEqual(references[pointer], [0, 4])


if __name__ == "__main__":
    unittest.main()
