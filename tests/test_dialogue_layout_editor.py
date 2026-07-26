from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.dialogue_layout_editor import (
    DialogueControlContext,
    DialogueDocument,
    DialogueEditorError,
    ProtectedControlToken,
    SafeSlotRecord,
    conservative_word_wrap,
    expand_display_tokens,
    filter_entry_indices,
    load_control_contexts,
    load_safe_slot_records,
    measure_layout,
)


class DialogueLayoutEditorTests(unittest.TestCase):
    def test_measures_explicit_17_by_3_layout(self) -> None:
        measurement = measure_layout(
            "가" * 17 + "\n" + "나" * 17 + "\n" + "다" * 17
        )
        self.assertTrue(measurement.fits)
        self.assertEqual(measurement.line_widths, (17, 17, 17))
        self.assertEqual(measurement.visible_glyph_count, 51)
        self.assertEqual(measurement.occupied_positions, 51)

        overflow = measure_layout("가" * 18)
        self.assertFalse(overflow.fits)
        self.assertEqual(overflow.column_overflow_rows, (1,))
        self.assertEqual(overflow.limit_reasons, ("line",))

        total_overflow = measure_layout(
            "가" * 13 + "\n" + "나" * 13 + "\n"
            + "다" * 13 + "\n" + "라" * 13
        )
        self.assertTrue(total_overflow.glyph_capacity_overflow)
        self.assertTrue(total_overflow.row_overflow)
        self.assertEqual(total_overflow.limit_reasons, ("total", "rows"))

    def test_expands_only_fixed_name_placeholders(self) -> None:
        self.assertEqual(
            expand_display_tokens(
                "{name:surname} {name:given} {unknown}"
            ),
            "시바 세이치로 {unknown}",
        )
        measurement = measure_layout("{name:surname}\n{name:given}")
        self.assertEqual(measurement.line_widths, (2, 4))

    def test_conservative_wrap_balances_first_dialogue(self) -> None:
        source = (
            "(드디어 여기까지 왔다…\n"
            "동경하던 팀,\n"
            "'스고 그랑프리')"
        )
        wrapped = conservative_word_wrap(source)
        self.assertEqual(
            wrapped,
            "(드디어 여기까지\n"
            "왔다… 동경하던 팀,\n"
            "'스고 그랑프리')",
        )
        self.assertEqual(measure_layout(wrapped).line_widths, (9, 11, 10))

    def test_conservative_wrap_does_not_split_words(self) -> None:
        with self.assertRaisesRegex(
            DialogueEditorError,
            "배치할 수 없습니다",
        ):
            conservative_word_wrap("가" * 18)

    def test_detects_declared_editable_field_and_preserves_protected_data(
        self,
    ) -> None:
        source = {
            "schema_version": 1,
            "entry_count": 2,
            "rules": {"editable_field": "entries[].ko"},
            "source_sha256": "protected",
            "entries": [
                {
                    "id": "entry-0",
                    "max_glyphs": 51,
                    "jp": "原文",
                    "ko": "원문",
                },
                {
                    "id": "entry-1",
                    "max_glyphs": 51,
                    "jp": "次",
                    "ko": "다음",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dialogue.json"
            path.write_text(
                json.dumps(source, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            document = DialogueDocument.load(path)
            self.assertEqual(document.editable_field, "ko")
            document.set_value(0, "수정\n대사")
            backup = document.save()

            self.assertEqual(backup, path.with_name("dialogue.json.bak"))
            self.assertTrue(backup.exists())
            self.assertEqual(
                json.loads(backup.read_text(encoding="utf-8")),
                source,
            )
            output = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(output["entries"][0]["ko"], "수정\n대사")
            self.assertEqual(output["entries"][0]["jp"], "原文")
            self.assertEqual(output["entries"][0]["max_glyphs"], 51)
            self.assertEqual(output["source_sha256"], "protected")
            self.assertFalse(document.dirty)

    def test_refuses_to_save_a_modified_four_row_dialogue(self) -> None:
        source = {
            "entries": [
                {
                    "id": "entry-0",
                    "jp": "原文",
                    "ko": "원문",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dialogue.json"
            path.write_text(
                json.dumps(source, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            document = DialogueDocument.load(path)
            document.set_value(0, "첫째\n둘째\n셋째\n넷째")
            with self.assertRaisesRegex(
                DialogueEditorError,
                "3줄을 넘는 수정 대사는 저장할 수 없습니다",
            ):
                document.save()
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                source,
            )
            self.assertFalse(path.with_name("dialogue.json.bak").exists())

    def test_filters_only_layout_overflow_entries_in_source_order(
        self,
    ) -> None:
        source = {
            "entries": [
                {"id": "entry-0", "jp": "通常", "ko": "가" * 17},
                {"id": "entry-1", "jp": "行超過", "ko": "나" * 18},
                {
                    "id": "entry-2",
                    "jp": "総数超過",
                    "ko": "\n".join(("다" * 13,) * 4),
                },
                {
                    "id": "entry-3",
                    "jp": "ちょうど",
                    "ko": "\n".join(("라" * 17,) * 3),
                },
            ]
        }
        document = DialogueDocument(Path("input.json"), source)

        self.assertEqual(document.layout_overflow_indices(), (1, 2))
        self.assertEqual(
            filter_entry_indices(document, overflow_only=True),
            [1, 2],
        )
        self.assertEqual(
            filter_entry_indices(
                document,
                query="総数",
                overflow_only=True,
            ),
            [2],
        )
        summary = document.validation_summary()
        self.assertEqual(summary["layout_overflow"], 2)
        self.assertEqual(summary["glyph_capacity_overflow"], 1)
        self.assertEqual(summary["line_width_overflow"], 1)
        self.assertEqual(summary["row_count_overflow"], 1)

    def test_filters_multiline_dialogue_with_nonempty_rows_under_six(
        self,
    ) -> None:
        source = {
            "entries": [
                {"id": "single-short", "ko": "가" * 5},
                {"id": "short-row", "ko": "나" * 5 + "\n" + "다" * 8},
                {"id": "six-row", "ko": "라" * 6 + "\n" + "마" * 8},
                {"id": "empty-row", "ko": "바" * 8 + "\n"},
                {
                    "id": "expanded-token",
                    "ko": "{name:surname}\n" + "사" * 8,
                },
                {
                    "id": "short-and-overflow",
                    "ko": "아" * 18 + "\n짧음",
                },
            ]
        }
        document = DialogueDocument(Path("input.json"), source)

        self.assertEqual(
            document.short_line_candidate_indices(),
            (1, 4, 5),
        )
        self.assertEqual(
            filter_entry_indices(document, short_line_only=True),
            [1, 4, 5],
        )
        self.assertEqual(
            filter_entry_indices(
                document,
                overflow_only=True,
                short_line_only=True,
            ),
            [5],
        )
        summary = document.validation_summary()
        self.assertEqual(summary["short_line_candidates"], 3)

    def test_filters_and_reports_verified_storage_slot_overflow(
        self,
    ) -> None:
        source = {
            "entries": [
                {"id": "fits", "ko": "가" * 3},
                {"id": "storage-only", "ko": "나" * 4},
                {"id": "layout-and-storage", "ko": "다" * 18},
            ]
        }
        terminal = ProtectedControlToken(
            token_index=4,
            raw="8000",
            kind="page_end",
            markup="{page_end}",
            policy="preserve",
        )
        contexts = {
            entry["id"]: DialogueControlContext(
                entry_id=entry["id"],
                original_stream_bytes=8,
                leading=(),
                internal_movable=(),
                trailing=(terminal,),
            )
            for entry in source["entries"]
        }

        def slot(entry_id: str, start: int) -> SafeSlotRecord:
            return SafeSlotRecord(
                entry_id=entry_id,
                unit_index=99,
                subsystem="event_page",
                file_offset=f"0x{start:06X}",
                unit_offset=f"0x{start:04X}",
                safe_end_file_offset=f"0x{start + 8:06X}",
                safe_end_unit_offset=f"0x{start + 8:04X}",
                original_stream_bytes=8,
                safe_slot_bytes=8,
                safe_slot_words=4,
                additional_zero_gap_bytes=0,
                boundary_kind="adjacent-next-entry",
                next_physical_entry_id="next",
                protected_target="next",
            )

        slots = {
            entry["id"]: slot(entry["id"], 0x10 + index * 8)
            for index, entry in enumerate(source["entries"])
        }
        document = DialogueDocument(
            Path("input.json"),
            source,
            control_contexts=contexts,
            safe_slots=slots,
        )

        self.assertEqual(
            document.storage_slot_overflow_indices(),
            (1, 2),
        )
        self.assertEqual(
            filter_entry_indices(
                document,
                storage_overflow_only=True,
            ),
            [1, 2],
        )
        self.assertEqual(
            filter_entry_indices(
                document,
                overflow_only=True,
                storage_overflow_only=True,
            ),
            [2],
        )
        report = document.control_report(1)
        self.assertIn(
            "검증 안전 슬롯 8B · 현재 예상 10B · 2B 초과",
            report,
        )
        self.assertIn("ALLBIN 0x000018–0x000020", report)
        summary = document.validation_summary()
        self.assertEqual(summary["safe_slot_entries"], 3)
        self.assertEqual(summary["storage_slot_measurable"], 3)
        self.assertEqual(summary["storage_slot_exact"], 1)
        self.assertEqual(summary["storage_slot_under_capacity"], 0)
        self.assertEqual(summary["storage_slot_overflow"], 2)
        self.assertEqual(summary["maximum_storage_overflow_bytes"], 30)
        self.assertEqual(summary["unit_storage_measurable"], 1)
        self.assertEqual(summary["unit_storage_overflow"], 1)
        self.assertEqual(summary["maximum_unit_storage_overflow_bytes"], 32)

    def test_unit_pool_allows_entry_overflow_when_unit_total_fits(
        self,
    ) -> None:
        source = {
            "entries": [
                {"id": "long", "ko": "가" * 7},
                {"id": "short-a", "ko": "나" * 2},
                {"id": "short-b", "ko": "다" * 3},
            ]
        }
        terminal = ProtectedControlToken(
            token_index=5,
            raw="8000",
            kind="page_end",
            markup="{page_end}",
            policy="preserve",
        )
        contexts = {
            entry["id"]: DialogueControlContext(
                entry_id=entry["id"],
                original_stream_bytes=12,
                leading=(),
                internal_movable=(),
                trailing=(terminal,),
            )
            for entry in source["entries"]
        }

        def slot(entry_id: str, start: int) -> SafeSlotRecord:
            return SafeSlotRecord(
                entry_id=entry_id,
                unit_index=0,
                subsystem="event_page",
                file_offset=f"0x{start:06X}",
                unit_offset=f"0x{start:04X}",
                safe_end_file_offset=f"0x{start + 12:06X}",
                safe_end_unit_offset=f"0x{start + 12:04X}",
                original_stream_bytes=12,
                safe_slot_bytes=12,
                safe_slot_words=6,
                additional_zero_gap_bytes=0,
                boundary_kind="adjacent-next-entry",
                next_physical_entry_id="next",
                protected_target="next",
            )

        slots = {
            entry["id"]: slot(entry["id"], 0x20 + index * 12)
            for index, entry in enumerate(source["entries"])
        }
        document = DialogueDocument(
            Path("input.json"),
            source,
            control_contexts=contexts,
            safe_slots=slots,
        )

        self.assertEqual(document.storage_slot_overflow_indices(), (0,))
        unit = document.unit_storage_measurement(0)
        self.assertIsNotNone(unit)
        assert unit is not None
        self.assertEqual(unit.profile.original_stream_capacity_bytes, 36)
        self.assertEqual(unit.estimated_stream_bytes, 30)
        self.assertEqual(unit.remaining_bytes, 6)
        self.assertTrue(unit.fits)
        self.assertFalse(unit.profile.runtime_verified)
        self.assertEqual(document.unit_storage_overflow_indices(), ())

        document.set_value(2, "다" * 7)
        unit = document.unit_storage_measurement(2)
        self.assertIsNotNone(unit)
        assert unit is not None
        self.assertEqual(unit.estimated_stream_bytes, 38)
        self.assertEqual(unit.overflow_bytes, 2)
        self.assertFalse(unit.fits)
        self.assertEqual(
            document.unit_storage_overflow_indices(),
            (0, 1, 2),
        )
        self.assertEqual(
            filter_entry_indices(
                document,
                unit_storage_overflow_only=True,
            ),
            [0, 1, 2],
        )

    def test_rejects_safe_slot_catalog_from_a_different_workset(
        self,
    ) -> None:
        catalog = {
            "schema_version": 1,
            "catalog_kind": "disc1-fixed-original-dialogue-safe-slots",
            "status": "verified-physical-boundaries-runtime-qa-required",
            "source": {"workset_sha256": "not-the-current-hash"},
            "entries": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            workset_path = Path(directory) / "workset.json"
            catalog_path = Path(directory) / "slots.json"
            workset_path.write_text("{}", encoding="utf-8")
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            with self.assertRaisesRegex(
                DialogueEditorError,
                "different protected workset",
            ):
                load_safe_slot_records(
                    catalog_path,
                    workset_path=workset_path,
                )

    def test_loads_protected_control_shell_and_renders_inline_stream(
        self,
    ) -> None:
        source = {
            "entries": [
                {
                    "entry_id": "entry-0",
                    "original": {
                        "tokens": [
                            "903F",
                            "0001",
                            "FFFB",
                            "0002",
                            "8000",
                        ],
                        "control_tokens": [
                            {
                                "token_index": 0,
                                "raw": "903F",
                                "kind": "speaker_style",
                                "markup": "{speaker_style:03F}",
                                "policy": "preserve",
                            },
                            {
                                "token_index": 2,
                                "raw": "FFFB",
                                "kind": "align",
                                "markup": "{align}",
                                "policy": "movable-layout-in-story-only",
                            },
                            {
                                "token_index": 4,
                                "raw": "8000",
                                "kind": "page_end",
                                "markup": "{page_end}",
                                "policy": "preserve",
                            },
                        ],
                    },
                }
            ]
        }
        candidate = {
            "entries": [
                {
                    "id": "entry-0",
                    "jp": "原文",
                    "ko": "한국어\n대사",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            workset_path = Path(directory) / "workset.json"
            workset_path.write_text(
                json.dumps(source, ensure_ascii=False),
                encoding="utf-8",
            )
            contexts = load_control_contexts(
                workset_path,
                required_ids=("entry-0",),
            )

        context = contexts["entry-0"]
        self.assertEqual(context.original_stream_bytes, 10)
        self.assertEqual(
            tuple(token.raw for token in context.leading),
            ("903F",),
        )
        self.assertEqual(
            tuple(token.raw for token in context.internal_movable),
            ("FFFB",),
        )
        self.assertEqual(
            tuple(token.raw for token in context.trailing),
            ("8000",),
        )
        visual = context.visual_segments("한국어\n대사")
        self.assertEqual(
            tuple(segment.kind for segment in visual),
            ("speaker_style", "glyph", "align", "glyph", "page_end"),
        )
        self.assertEqual(
            tuple(segment.display_glyphs for segment in visual),
            (0, 3, 0, 2, 0),
        )
        self.assertEqual(
            tuple(segment.stream_bytes for segment in visual),
            (2, 6, 2, 4, 2),
        )
        self.assertEqual(visual[0].visual_class, "speaker")
        self.assertEqual(visual[2].visual_class, "layout")
        self.assertEqual(visual[-1].visual_class, "terminal")
        self.assertEqual(
            context.compact_visual_summary("한국어\n대사"),
            (
                "선두 제어(0글리프) 903F"
                " · 줄바꿈 FFFB ×1"
                " · 후미 제어(0글리프) 8000"
            ),
        )
        document = DialogueDocument(
            Path("candidate.json"),
            candidate,
            control_contexts=contexts,
        )
        self.assertIn(
            "{speaker_style:03F}한국어{align}대사{page_end}",
            document.control_report(0),
        )
        self.assertIn(
            "원본 스트림 10B · 현재 예상 16B",
            document.control_report(0),
        )
        summary = document.validation_summary()
        self.assertEqual(summary["control_context_entries"], 1)
        self.assertEqual(summary["leading_control_tokens"], 1)
        self.assertEqual(summary["movable_internal_control_tokens"], 1)
        self.assertEqual(summary["trailing_control_tokens"], 1)

    def test_rejects_control_metadata_that_differs_from_raw_tokens(
        self,
    ) -> None:
        source = {
            "entries": [
                {
                    "entry_id": "entry-0",
                    "original": {
                        "tokens": ["903F", "0001", "8000"],
                        "control_tokens": [
                            {
                                "token_index": 0,
                                "raw": "9000",
                                "kind": "speaker_style",
                                "markup": "{speaker_style:000}",
                                "policy": "preserve",
                            },
                            {
                                "token_index": 2,
                                "raw": "8000",
                                "kind": "page_end",
                                "markup": "{page_end}",
                                "policy": "preserve",
                            },
                        ],
                    },
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            workset_path = Path(directory) / "workset.json"
            workset_path.write_text(
                json.dumps(source),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DialogueEditorError,
                "control raw value differs",
            ):
                load_control_contexts(workset_path)

    def test_rejects_duplicate_stable_ids(self) -> None:
        source = {
            "entries": [
                {"id": "same", "ko": ""},
                {"id": "same", "ko": ""},
            ]
        }
        with self.assertRaisesRegex(DialogueEditorError, "duplicate"):
            DialogueDocument(Path("input.json"), source)


if __name__ == "__main__":
    unittest.main()
