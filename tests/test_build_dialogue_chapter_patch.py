from __future__ import annotations

import json
from pathlib import Path
import struct
import unittest

from scripts.build_dialogue_chapter_patch import (
    PROTECTED_ORIGINAL_GLYPH_INDICES,
    UNIT_SHARED_POOL_REFERENCE_PROFILES,
    build_source_ordered_stream,
    changed_ranges,
    encode_entry,
    fit_fixed_diagnostic_candidate,
    passthrough_gap_glyph_indices,
    physical_entry_ranges,
    reference_catalog_sha256,
    relink_unit_shared_pool,
    repack_unit,
    scan_unit_dialogue_references,
    validate_stable_id_join,
    verify_unit_reference_profile,
    verify_expected_writes,
    write_unit_at_original_offsets_diagnostic,
)


ROOT = Path(__file__).resolve().parent.parent


class DialogueChapterBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workset = json.loads(
            (ROOT / "work/translations/disc1-dialogue.json").read_text(
                encoding="utf-8"
            )
        )
        cls.first = workset["entries"][0]
        cls.mapping = {
            character: index
            for index, character in enumerate(
                sorted(set("(드디어 여기까지 왔다…동경하던 팀,'스고 그랑프리')"))
            )
        }

    def test_encodes_control_shell_and_new_align(self) -> None:
        encoded = encode_entry(
            self.first,
            "(드디어 여기까지 왔다…\n동경하던 팀,\n'스고 그랑프리')",
            self.mapping,
        )
        tokens = struct.unpack(f"<{len(encoded) // 2}H", encoded)
        self.assertEqual(tokens[0], 0x903F)
        self.assertEqual(tokens[-1], 0x8000)
        self.assertEqual(tokens.count(0xFFFB), 2)

    def test_rejects_four_dialogue_rows_even_when_unit_has_space(self) -> None:
        mapping = {character: index for index, character in enumerate("가나다라")}
        with self.assertRaisesRegex(ValueError, "invalid reflow row count"):
            encode_entry(
                self.first,
                "가\n나\n다\n라",
                mapping,
            )

    def test_fixed_diagnostic_hard_wrap_preserves_visible_sequence(self) -> None:
        candidate = (
            "당 시스템은 주행 데이터를\n"
            "기억하고, 최적의 속도로 지원하는\n"
            "보정 프로그램을 탑재하고 있습니다."
        )
        adjusted, report = fit_fixed_diagnostic_candidate(
            self.first,
            candidate,
        )
        self.assertIsNotNone(report)
        self.assertEqual(
            adjusted.replace("\n", ""),
            candidate.replace("\n", ""),
        )
        self.assertEqual(
            [len(line) for line in adjusted.split("\n")],
            [17, 17, 17],
        )

    def test_sorts_physical_entry_ranges_without_overlap(self) -> None:
        entries = [
            {
                "entry_id": "second",
                "source": {
                    "unit_offset": "0x0014",
                    "byte_size": 6,
                }
            },
            {
                "entry_id": "first",
                "source": {
                    "unit_offset": "0x0010",
                    "byte_size": 4,
                }
            },
            {
                "entry_id": "third",
                "source": {
                    "unit_offset": "0x0020",
                    "byte_size": 2,
                }
            },
        ]
        self.assertEqual(
            [
                (start, end, entry["entry_id"])
                for start, end, entry in physical_entry_ranges(entries)
            ],
            [
                (0x10, 0x14, "first"),
                (0x14, 0x1A, "second"),
                (0x20, 0x22, "third"),
            ],
        )

    def test_source_ordered_stream_preserves_raw_fallthrough_gap(self) -> None:
        entries = [
            {
                "entry_id": "first",
                "source": {"unit_offset": "0x0010", "byte_size": 4},
            },
            {
                "entry_id": "second",
                "source": {"unit_offset": "0x0014", "byte_size": 6},
            },
            {
                "entry_id": "third",
                "source": {"unit_offset": "0x0020", "byte_size": 2},
            },
        ]
        unit = bytearray(0x22)
        unit[0x10:0x14] = b"1111"
        unit[0x14:0x1A] = b"222222"
        unit[0x1A:0x20] = b"\x34\x12\x00\x80\x00\x00"
        unit[0x20:0x22] = b"33"
        layout = build_source_ordered_stream(
            bytes(unit),
            entries,
            {
                "first": b"aa",
                "second": b"bbbb",
                "third": b"cc",
            },
        )
        self.assertEqual(
            layout["physical_entry_ids"],
            ["first", "second", "third"],
        )
        self.assertEqual(layout["placements"]["first"], 0x10)
        self.assertEqual(layout["placements"]["second"], 0x12)
        self.assertEqual(layout["placements"]["third"], 0x1C)
        self.assertEqual(
            layout["stream"],
            b"aabbbb\x34\x12\x00\x80\x00\x00cc",
        )
        self.assertEqual(layout["gaps"][-1]["page_end_count"], 1)

    def test_source_ordered_stream_rejects_capacity_overflow(self) -> None:
        entries = [
            {
                "entry_id": "first",
                "source": {"unit_offset": "0x0010", "byte_size": 4},
            },
            {
                "entry_id": "second",
                "source": {"unit_offset": "0x0014", "byte_size": 4},
            },
        ]
        with self.assertRaisesRegex(ValueError, "requires 10 bytes"):
            build_source_ordered_stream(
                bytes(0x18),
                entries,
                {"first": b"12345", "second": b"67890"},
            )

    def test_physical_entry_ranges_reject_overlap(self) -> None:
        entries = [
            {
                "entry_id": "first",
                "source": {"unit_offset": "0x0010", "byte_size": 6},
            },
            {
                "entry_id": "second",
                "source": {"unit_offset": "0x0014", "byte_size": 4},
            },
        ]
        with self.assertRaisesRegex(ValueError, "overlap"):
            physical_entry_ranges(entries)

    def test_repacker_keeps_runtime_physical_order_and_gap(self) -> None:
        def source_entry(
            entry_id: str,
            *,
            unit_offset: int,
            source_glyph: int,
            pointer_storage: int,
        ) -> dict:
            raw = struct.pack(
                "<4H",
                source_glyph,
                source_glyph,
                source_glyph,
                0x8000,
            )
            runtime_pointer = 0x800A8000 + unit_offset
            return {
                "entry_id": entry_id,
                "source": {
                    "unit_index": 0,
                    "file_offset": f"0x{unit_offset:06X}",
                    "unit_offset": f"0x{unit_offset:04X}",
                    "runtime_pointer": f"0x{runtime_pointer:08X}",
                    "byte_size": len(raw),
                    "pointer_references": [
                        {
                            "storage_file_offset": (
                                f"0x{pointer_storage:06X}"
                            ),
                            "raw_value": f"0x{runtime_pointer:08X}",
                        }
                    ],
                },
                "original": {
                    "raw_hex": raw.hex(),
                    "tokens": [
                        f"{source_glyph:04X}",
                        f"{source_glyph:04X}",
                        f"{source_glyph:04X}",
                        "8000",
                    ],
                    "control_tokens": [
                        {
                            "token_index": 3,
                            "kind": "page_end",
                        }
                    ],
                },
            }

        entries = [
            source_entry(
                "first",
                unit_offset=0x10,
                source_glyph=1,
                pointer_storage=0x80,
            ),
            source_entry(
                "second",
                unit_offset=0x18,
                source_glyph=2,
                pointer_storage=0x84,
            ),
            source_entry(
                "third",
                unit_offset=0x22,
                source_glyph=3,
                pointer_storage=0x88,
            ),
        ]
        allbin = bytearray(0x100)
        for entry in entries:
            offset = int(entry["source"]["file_offset"], 16)
            raw = bytes.fromhex(entry["original"]["raw_hex"])
            allbin[offset : offset + len(raw)] = raw
            reference = entry["source"]["pointer_references"][0]
            struct.pack_into(
                "<I",
                allbin,
                int(reference["storage_file_offset"], 16),
                int(reference["raw_value"], 16),
            )
        allbin[0x20:0x22] = b"\x00\x00"

        reflow = {
            "first": {"status": "ready", "ko_reflowed": "가나"},
            "second": {"status": "ready", "ko_reflowed": "다"},
            "third": {"status": "ready", "ko_reflowed": "라"},
        }
        mapping = {"가": 0x100, "나": 0x101, "다": 0x102, "라": 0x103}
        report = repack_unit(allbin, entries, reflow, mapping)
        first = encode_entry(entries[0], "가나", mapping)
        second = encode_entry(entries[1], "다", mapping)

        self.assertEqual(allbin[0x10 : 0x10 + len(first)], first)
        second_offset = 0x10 + len(first)
        self.assertEqual(
            allbin[second_offset : second_offset + len(second)],
            second,
        )
        self.assertEqual(
            struct.unpack_from("<I", allbin, 0x84)[0],
            0x800A8000 + second_offset,
        )
        third = encode_entry(entries[2], "라", mapping)
        third_offset = second_offset + len(second) + 2
        self.assertEqual(allbin[third_offset : third_offset + len(third)], third)
        self.assertEqual(allbin[third_offset - 2 : third_offset], b"\x00\x00")
        self.assertEqual(
            report["physical_fallthrough_edge_verification_count"],
            2,
        )

    def test_gap_glyph_indices_are_reserved_from_raw_fallthrough(self) -> None:
        entries = {
            0: [
                {
                    "entry_id": "first",
                    "source": {
                        "file_offset": "0x000010",
                        "unit_offset": "0x0010",
                        "byte_size": 4,
                    },
                },
                {
                    "entry_id": "second",
                    "source": {
                        "file_offset": "0x00001A",
                        "unit_offset": "0x001A",
                        "byte_size": 2,
                    },
                },
            ]
        }
        allbin = bytearray(0x20)
        struct.pack_into("<3H", allbin, 0x14, 0x0049, 0x8000, 0x0000)
        self.assertEqual(
            passthrough_gap_glyph_indices(bytes(allbin), entries),
            frozenset({0x0000, 0x0049}),
        )

    def test_verified_units_have_exhaustive_frozen_reference_catalogs(
        self,
    ) -> None:
        workset = json.loads(
            (ROOT / "work/translations/disc1-dialogue.json").read_text(
                encoding="utf-8"
            )
        )
        source_allbin = (
            ROOT / "work/extracted/disc1/iso/ALLBIN.BIN"
        ).read_bytes()
        for unit_index in (0, 21):
            entries = [
                entry
                for entry in workset["entries"]
                if int(entry["source"]["unit_index"]) == unit_index
            ]
            profile = UNIT_SHARED_POOL_REFERENCE_PROFILES[unit_index]
            unit_file_offset = {
                int(entry["source"]["file_offset"], 16)
                - int(entry["source"]["unit_offset"], 16)
                for entry in entries
            }.pop()
            source_unit = source_allbin[
                unit_file_offset :
                unit_file_offset + int(profile["scheduled_bytes"])
            ]
            layout = build_source_ordered_stream(
                source_unit,
                entries,
                {
                    entry["entry_id"]: bytes.fromhex(
                        entry["original"]["raw_hex"]
                    )
                    for entry in entries
                },
            )
            references = scan_unit_dialogue_references(
                source_unit,
                entries,
                layout,
            )
            report = verify_unit_reference_profile(
                unit_index,
                source_unit,
                references,
                profile,
            )
            self.assertTrue(report["verified"])
            self.assertEqual(
                report["catalog_sha256"],
                profile["catalog_sha256"],
            )

    def test_unit_shared_pool_relinks_hidden_and_gap_consumers(self) -> None:
        def entry(
            entry_id: str,
            *,
            unit_offset: int,
            glyph: int,
            pointer_storage: int,
        ) -> dict:
            raw = struct.pack("<4H", glyph, glyph, glyph, 0x8000)
            pointer = 0x800A8000 + unit_offset
            return {
                "entry_id": entry_id,
                "source": {
                    "unit_index": 0,
                    "file_offset": f"0x{unit_offset:06X}",
                    "unit_offset": f"0x{unit_offset:04X}",
                    "runtime_pointer": f"0x{pointer:08X}",
                    "byte_size": len(raw),
                    "pointer_references": [
                        {
                            "storage_file_offset": (
                                f"0x{pointer_storage:06X}"
                            ),
                            "storage_unit_offset": (
                                f"0x{pointer_storage:04X}"
                            ),
                            "raw_value": f"0x{pointer:08X}",
                        }
                    ],
                },
                "original": {
                    "raw_hex": raw.hex(),
                    "tokens": [
                        f"{glyph:04X}",
                        f"{glyph:04X}",
                        f"{glyph:04X}",
                        "8000",
                    ],
                    "control_tokens": [
                        {"token_index": 3, "kind": "page_end"}
                    ],
                },
            }

        entries = [
            entry("first", unit_offset=0x10, glyph=1, pointer_storage=0x80),
            entry("second", unit_offset=0x1A, glyph=2, pointer_storage=0x84),
        ]
        allbin = bytearray(0xA0)
        for source in entries:
            offset = int(source["source"]["unit_offset"], 16)
            raw = bytes.fromhex(source["original"]["raw_hex"])
            allbin[offset : offset + len(raw)] = raw
            reference = source["source"]["pointer_references"][0]
            struct.pack_into(
                "<I",
                allbin,
                int(reference["storage_unit_offset"], 16),
                int(reference["raw_value"], 16),
            )
        struct.pack_into("<I", allbin, 0x8C, 0x800A801A)
        struct.pack_into("<I", allbin, 0x90, 0x800A8018)

        mapping = {
            "가": 0x100,
            "나": 0x101,
            "다": 0x102,
            "라": 0x103,
            "마": 0x104,
        }
        reflow = {
            "first": {"status": "ready", "ko_candidate": "가나다라"},
            "second": {"status": "ready", "ko_candidate": "마"},
        }
        streams = {
            entry["entry_id"]: encode_entry(
                entry,
                reflow[entry["entry_id"]]["ko_candidate"],
                mapping,
            )
            for entry in entries
        }
        layout = build_source_ordered_stream(bytes(allbin), entries, streams)
        references = scan_unit_dialogue_references(
            bytes(allbin),
            entries,
            layout,
        )
        kind_counts = {
            kind: sum(
                reference["target_kind"] == kind
                for reference in references
            )
            for kind in ("entry_start", "preserved_gap")
        }
        profile = {
            "scheduled_bytes": len(allbin),
            "reference_count": len(references),
            "entry_start_reference_count": kind_counts["entry_start"],
            "gap_reference_count": kind_counts["preserved_gap"],
            "catalog_sha256": reference_catalog_sha256(references),
        }
        report = relink_unit_shared_pool(
            allbin,
            entries,
            reflow,
            mapping,
            reference_profile=profile,
        )

        first_offset = int(
            report["physical_entries"][0]["output_unit_offset"],
            16,
        )
        second_offset = int(
            report["physical_entries"][1]["output_unit_offset"],
            16,
        )
        self.assertEqual(first_offset, 0x10)
        self.assertEqual(second_offset, 0x1C)
        self.assertEqual(
            struct.unpack_from("<I", allbin, 0x84)[0],
            0x800A8000 + second_offset,
        )
        self.assertEqual(
            struct.unpack_from("<I", allbin, 0x8C)[0],
            0x800A8000 + second_offset,
        )
        self.assertEqual(
            struct.unpack_from("<I", allbin, 0x90)[0],
            0x800A801A,
        )
        self.assertEqual(report["original_slot_overflow_count"], 1)
        self.assertEqual(report["tail_padding_bytes"], 2)
        self.assertTrue(report["unit_capacity_preserved"])
        self.assertEqual(
            report["reference_catalog"][
                "additional_event_consumer_reference_count"
            ],
            2,
        )

    def test_fixed_diagnostic_preserves_earlier_overflowing_stream(self) -> None:
        def entry(
            entry_id: str,
            *,
            unit_offset: int,
            glyph: int,
            pointer_storage: int,
        ) -> dict:
            raw = struct.pack("<4H", glyph, glyph, glyph, 0x8000)
            pointer = 0x800A8000 + unit_offset
            return {
                "entry_id": entry_id,
                "source": {
                    "unit_index": 0,
                    "file_offset": f"0x{unit_offset:06X}",
                    "unit_offset": f"0x{unit_offset:04X}",
                    "runtime_pointer": f"0x{pointer:08X}",
                    "byte_size": len(raw),
                    "pointer_references": [
                        {
                            "storage_file_offset": f"0x{pointer_storage:06X}",
                            "raw_value": f"0x{pointer:08X}",
                        }
                    ],
                },
                "original": {
                    "raw_hex": raw.hex(),
                    "tokens": [
                        f"{glyph:04X}",
                        f"{glyph:04X}",
                        f"{glyph:04X}",
                        "8000",
                    ],
                    "control_tokens": [
                        {"token_index": 3, "kind": "page_end"}
                    ],
                },
            }

        entries = [
            entry("first", unit_offset=0x10, glyph=1, pointer_storage=0x80),
            entry("second", unit_offset=0x18, glyph=2, pointer_storage=0x84),
        ]
        allbin = bytearray(0x100)
        for source in entries:
            offset = int(source["source"]["file_offset"], 16)
            raw = bytes.fromhex(source["original"]["raw_hex"])
            allbin[offset : offset + len(raw)] = raw
            reference = source["source"]["pointer_references"][0]
            struct.pack_into(
                "<I",
                allbin,
                int(reference["storage_file_offset"], 16),
                int(reference["raw_value"], 16),
            )
        mapping = {
            "가": 0x100,
            "나": 0x101,
            "다": 0x102,
            "라": 0x103,
            "마": 0x104,
        }
        reflow = {
            "first": {
                "status": "ready",
                "ko_candidate": "가나다라",
            },
            "second": {"status": "ready", "ko_candidate": "마"},
        }
        report = write_unit_at_original_offsets_diagnostic(
            allbin,
            entries,
            reflow,
            mapping,
        )
        first = encode_entry(entries[0], "가나다라", mapping)
        self.assertEqual(allbin[0x10 : 0x10 + len(first)], first)
        self.assertEqual(report["slot_overflow_count"], 1)
        self.assertEqual(
            report["first_slot_overflow"]["overflow_bytes"],
            2,
        )
        self.assertEqual(report["corrupted_by_overlap_entry_count"], 1)
        self.assertEqual(
            report["corrupted_portrait_or_audio_entry_count"],
            0,
        )
        self.assertEqual(
            struct.unpack_from("<I", allbin, 0x80)[0],
            0x800A8010,
        )
        self.assertEqual(
            struct.unpack_from("<I", allbin, 0x84)[0],
            0x800A8018,
        )

    def test_latin_digit_and_symbol_slots_are_protected(self) -> None:
        self.assertTrue(
            set(range(0x000, 0x046)).issubset(
                PROTECTED_ORIGINAL_GLYPH_INDICES
            )
        )
        self.assertIn(0x0E4, PROTECTED_ORIGINAL_GLYPH_INDICES)
        self.assertIn(0x0E5, PROTECTED_ORIGINAL_GLYPH_INDICES)
        self.assertNotIn(0x046, PROTECTED_ORIGINAL_GLYPH_INDICES)

    def test_stable_id_join_requires_exact_source_order(self) -> None:
        work = [{"entry_id": "a"}, {"entry_id": "b"}]
        report = validate_stable_id_join(
            work,
            [{"id": "a"}, {"id": "b"}],
        )
        self.assertTrue(report["stable_id_set_exact"])
        self.assertTrue(report["protected_workset_order_preserved"])
        with self.assertRaisesRegex(ValueError, "protected workset order"):
            validate_stable_id_join(
                work,
                [{"id": "b"}, {"id": "a"}],
            )

    def test_expected_write_verifier_accepts_only_declared_ranges(self) -> None:
        before = bytes(16)
        after = bytearray(before)
        after[4:7] = b"abc"
        report = verify_expected_writes(
            before,
            bytes(after),
            allowed_ranges=[(4, 8)],
            owner="test",
        )
        self.assertTrue(report["verified"])
        self.assertEqual(report["changed_byte_count"], 3)
        self.assertEqual(changed_ranges(before, bytes(after)), [(4, 7)])

    def test_expected_write_verifier_rejects_unplanned_change(self) -> None:
        before = bytes(16)
        after = bytearray(before)
        after[9] = 1
        with self.assertRaisesRegex(ValueError, "unexplained write"):
            verify_expected_writes(
                before,
                bytes(after),
                allowed_ranges=[(4, 8)],
                owner="test",
            )


if __name__ == "__main__":
    unittest.main()
