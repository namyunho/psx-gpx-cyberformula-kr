import struct
import unittest

from scripts.psx_layout import (
    PsxExe,
    classify_child,
    discover_schedule,
    discover_schedule_bytes,
    inventory_scheduled_file,
    parse_offset_directory,
)


def synthetic_exe(payload: bytes, load_address: int = 0x80010000) -> PsxExe:
    header = bytearray(0x800)
    header[:8] = b"PS-X EXE"
    struct.pack_into("<4I", header, 0x10, load_address, 0, load_address, len(payload))
    return PsxExe(bytes(header) + payload)


class PsxLayoutTests(unittest.TestCase):
    def test_discovers_complete_sector_partition(self) -> None:
        payload = struct.pack("<6H", 0, 2, 2, 1, 3, 3)
        exe = synthetic_exe(payload)
        schedule = discover_schedule(
            exe, 0x80010000, 0x8001000C, 6 * 0x800
        )
        self.assertEqual([entry["byte_size"] for entry in schedule], [0x1000, 0x800, 0x1800])
        self.assertEqual(schedule[-1]["byte_end"], 6 * 0x800)

    def test_rejects_schedule_gap(self) -> None:
        payload = struct.pack("<4H", 0, 2, 3, 1)
        exe = synthetic_exe(payload)
        with self.assertRaisesRegex(ValueError, "broken schedule"):
            discover_schedule(exe, 0x80010000, 0x80010008, 3 * 0x800)

    def test_discovers_schedule_from_embedded_bytes(self) -> None:
        table = struct.pack("<6H", 0, 2, 2, 1, 3, 3)
        schedule = discover_schedule_bytes(
            table,
            6 * 0x800,
            maximum_entries=3,
        )
        self.assertEqual(len(schedule), 3)
        self.assertEqual(schedule[-1]["byte_end"], 6 * 0x800)

    def test_parses_strict_offset_directory(self) -> None:
        unit = struct.pack("<2I", 8, 12) + b"ABCD" + b"EFGH"
        self.assertEqual(parse_offset_directory(unit), [8, 12])
        duplicate = struct.pack("<2I", 8, 8) + b"ABCDEFGH"
        self.assertIsNone(parse_offset_directory(duplicate))

    def test_classifies_structurally_valid_vram_record(self) -> None:
        child = struct.pack("<4H4H", 10, 20, 2, 2, 1, 2, 3, 4) + b"\0" * 4
        result = classify_child(child)
        self.assertEqual(result["kind"], "raw_vram_rectangle")
        self.assertEqual(result["payload_size"], 8)
        self.assertEqual(result["zero_padding"], 4)

    def test_does_not_accept_zero_sized_or_nonzero_padded_rectangle(self) -> None:
        zero_width = struct.pack("<4H", 0, 0, 0, 1) + b"\0" * 8
        self.assertNotEqual(classify_child(zero_width)["kind"], "raw_vram_rectangle")
        bad_padding = struct.pack("<4H2H", 0, 0, 1, 2, 1, 2) + b"\x01"
        self.assertNotEqual(classify_child(bad_padding)["kind"], "raw_vram_rectangle")

    def test_classifies_whole_scheduled_unit_as_vram_record(self) -> None:
        unit = struct.pack("<4H4H", 10, 20, 2, 2, 1, 2, 3, 4)
        report = inventory_scheduled_file(
            unit,
            [
                {
                    "index": 0,
                    "start_sector": 0,
                    "sector_count": 1,
                    "byte_offset": 0,
                    "byte_size": len(unit),
                    "byte_end": len(unit),
                }
            ],
        )
        self.assertEqual(report["counts"]["units_raw_vram_rectangle"], 1)
        self.assertEqual(report["units"][0]["kind"], "raw_vram_rectangle")


if __name__ == "__main__":
    unittest.main()
