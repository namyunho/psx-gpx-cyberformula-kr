from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from scripts.build_dialogue_safe_slots import (
    build_safe_slot_catalog,
    fixed_original_safe_slots,
)


class DialogueSafeSlotTests(unittest.TestCase):
    @staticmethod
    def _entry(entry_id: str, start: int, raw: bytes) -> dict:
        return {
            "entry_id": entry_id,
            "source": {
                "container": "ALLBIN.BIN",
                "unit_index": 0,
                "subsystem": "event_page",
                "file_offset": f"0x{start:06X}",
                "unit_offset": f"0x{start:04X}",
                "byte_size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            "original": {"raw_hex": raw.hex()},
        }

    def test_protects_zero_and_nonzero_inter_entry_gaps(self) -> None:
        entries = [
            self._entry("first", 0x10, b"1111"),
            self._entry("second", 0x16, b"2222"),
            self._entry("third", 0x20, b"3333"),
        ]
        unit = bytearray(0x24)
        unit[0x10:0x14] = b"1111"
        unit[0x14:0x16] = b"\x00\x00"
        unit[0x16:0x1A] = b"2222"
        unit[0x1A:0x20] = b"\x34\x12\x00\x80\x00\x00"
        unit[0x20:0x24] = b"3333"

        records = fixed_original_safe_slots(bytes(unit), entries)

        self.assertEqual(records[0].safe_slot_bytes, 4)
        self.assertEqual(
            records[0].boundary_kind,
            "protected-zero-fallthrough-gap",
        )
        self.assertEqual(records[1].safe_slot_bytes, 4)
        self.assertEqual(
            records[1].boundary_kind,
            "protected-nonzero-gap",
        )
        self.assertEqual(records[1].gap_nonzero_byte_count, 3)
        self.assertEqual(records[2].safe_slot_bytes, 4)
        self.assertEqual(
            records[2].boundary_kind,
            "last-extracted-entry-original-end",
        )

    def test_catalog_verifies_allbin_and_preserves_workset_id_order(
        self,
    ) -> None:
        allbin = bytearray(0x24)
        allbin[0x10:0x14] = b"1111"
        allbin[0x14:0x16] = b"\x00\x00"
        allbin[0x16:0x1A] = b"2222"
        entries = [
            self._entry("second", 0x16, b"2222"),
            self._entry("first", 0x10, b"1111"),
        ]
        workset = {
            "baseline_id": "test",
            "scope": {
                "source_allbin_sha256": hashlib.sha256(allbin).hexdigest()
            },
            "entries": entries,
        }
        workset_bytes = json.dumps(workset).encode()

        catalog = build_safe_slot_catalog(
            workset,
            workset_bytes=workset_bytes,
            allbin=bytes(allbin),
            workset_path=Path("workset.json"),
            allbin_path=Path("ALLBIN.BIN"),
        )

        self.assertEqual(
            [entry["id"] for entry in catalog["entries"]],
            ["second", "first"],
        )
        self.assertEqual(catalog["summary"]["entry_count"], 2)
        self.assertEqual(
            catalog["summary"]["additional_verified_zero_gap_bytes"],
            0,
        )
        self.assertEqual(
            catalog["source"]["workset_sha256"],
            hashlib.sha256(workset_bytes).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
