from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.dialogue_layout_editor import (
    DialogueControlContext,
    DialogueDocument,
    DialogueEditorError,
    FontTranslationWorkspaceDocument,
    ProtectedControlToken,
    SafeSlotRecord,
    TranslationBinding,
    apply_literal_replacement,
    conservative_word_wrap,
    expand_display_tokens,
    filter_entry_indices,
    format_entry_metadata,
    glyph_advance_px,
    line_pixel_width,
    literal_match_count,
    load_control_contexts,
    load_safe_slot_records,
    measure_layout,
    plan_literal_replacement,
    undo_literal_replacement,
)


class DialogueLayoutEditorTests(unittest.TestCase):
    def test_plans_applies_and_undoes_literal_term_replacement(
        self,
    ) -> None:
        source = {
            "protected": "unchanged",
            "entries": [
                {
                    "id": "entry-0",
                    "jp": "チーム",
                    "ko": "스고 팀과 스고 머신",
                    "source_group": "story_dialogue",
                },
                {
                    "id": "entry-1",
                    "jp": "別",
                    "ko": "다른 팀",
                    "source_group": "font_ui",
                },
            ],
        }
        document = DialogueDocument(Path("input.json"), source)
        changes = plan_literal_replacement(
            document,
            find_text="스고",
            replace_text="스고우",
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].occurrence_count, 2)
        self.assertEqual(document.value(0), "스고 팀과 스고 머신")
        apply_literal_replacement(document, changes)
        self.assertEqual(document.value(0), "스고우 팀과 스고우 머신")
        self.assertEqual(document.entries[0]["jp"], "チーム")
        undo_literal_replacement(document, changes)
        self.assertEqual(document.value(0), "스고 팀과 스고 머신")
        self.assertEqual(document.document["protected"], "unchanged")

    def test_literal_replacement_can_limit_group_and_ignore_case(
        self,
    ) -> None:
        source = {
            "entries": [
                {
                    "id": "story",
                    "ko": "TEAM Team team",
                    "source_group": "story_dialogue",
                },
                {
                    "id": "ui",
                    "ko": "TEAM",
                    "source_group": "font_ui",
                },
            ]
        }
        document = DialogueDocument(Path("input.json"), source)
        story_indices = filter_entry_indices(
            document,
            source_group="story_dialogue",
        )
        changes = plan_literal_replacement(
            document,
            find_text="team",
            replace_text="팀",
            indices=story_indices,
            case_sensitive=False,
        )

        self.assertEqual(literal_match_count(
            document.value(0),
            "team",
            case_sensitive=False,
        ), 3)
        self.assertEqual(
            [(change.entry_id, change.occurrence_count) for change in changes],
            [("story", 3)],
        )
        apply_literal_replacement(document, changes)
        self.assertEqual(document.value(0), "팀 팀 팀")
        self.assertEqual(document.value(1), "TEAM")

    def test_replacement_plan_refuses_stale_batch(self) -> None:
        document = DialogueDocument(
            Path("input.json"),
            {"entries": [{"id": "entry", "ko": "스고"}]},
        )
        changes = plan_literal_replacement(
            document,
            find_text="스고",
            replace_text="스고우",
        )
        document.set_value(0, "수동 수정")
        with self.assertRaisesRegex(
            DialogueEditorError,
            "미리보기 이후 내용이 변경",
        ):
            apply_literal_replacement(document, changes)

    def test_complete_workspace_loads_every_font_translation_group(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        required = (
            root / "work/translations/disc1-dialogue-ko-candidate.json",
            root / "work/translations/disc1-dialogue.json",
            root / "work/analysis/disc1-dialogue-safe-slots.json",
            root
            / "work/translations/disc1-pointerless-pages-u00-u21.json",
            root / "work/translations/disc1-special-screen-text.json",
            root / "work/translations/disc1-unindexed-font-text.json",
            root / "work/translations/disc1-ui.json",
            root
            / "data/translations/disc1-pointerless-pages-u00-u21-ko.json",
            root / "data/translations/disc1-special-screen-ko.json",
            root / "data/translations/disc1-unindexed-font-ko.json",
            root / "data/translations/disc1-ui-ko.json",
            root / "data/translations/disc1-character-names.json",
        )
        if not all(path.is_file() for path in required):
            self.skipTest("complete local translation workspace unavailable")

        document = FontTranslationWorkspaceDocument.load(
            dialogue_translation_path=required[0],
            dialogue_workset_path=required[1],
            safe_slots_path=required[2],
            pointerless_workset_path=required[3],
            special_workset_path=required[4],
            unindexed_workset_path=required[5],
            ui_workset_path=required[6],
            pointerless_translation_path=required[7],
            special_translation_path=required[8],
            unindexed_translation_path=required[9],
            ui_translation_path=required[10],
            character_names_path=required[11],
        )

        summary = document.validation_summary()
        self.assertEqual(len(document), 7059)
        self.assertEqual(
            summary["source_group_counts"],
            {
                "character_name": 36,
                "course_information": 57,
                "font_ui": 4,
                "garage_menu": 2,
                "machine_setting": 32,
                "minigame": 405,
                "pointerless_page": 84,
                "race_dialogue": 334,
                "save_system": 27,
                "sequential_dialogue": 295,
                "story_dialogue": 5783,
            },
        )
        self.assertTrue(summary["excluded_graphics"])
        minigame_index = document.ids.index(
            "disc1/allbin/u38/minigame_page/ref0000"
        )
        self.assertEqual(
            document.source_group(minigame_index),
            "minigame",
        )
        self.assertEqual(
            document.layout_profile(minigame_index).rows,
            3,
        )
        sequential_setting_index = document.ids.index(
            "disc1/allbin/u43/machine_setting_sequence/confirm_prompt"
        )
        sequential_setting_profile = document.layout_profile(
            sequential_setting_index
        )
        self.assertEqual(
            document.source_group(sequential_setting_index),
            "machine_setting",
        )
        self.assertEqual(
            sequential_setting_profile.row_policy,
            "automatic",
        )
        self.assertLessEqual(
            len(document.layout_measurement(sequential_setting_index).lines),
            sequential_setting_profile.rows,
        )
        self.assertIn(
            "자동줄바꿈",
            format_entry_metadata(document, sequential_setting_index),
        )
        save_index = document.ids.index(
            "disc1/allbin/u39/unindexed_font/p05F98"
        )
        self.assertEqual(
            document.source_group(save_index),
            "save_system",
        )
        self.assertEqual(
            document.layout_profile(save_index).columns,
            17,
        )
        ui_index = document.ids.index(
            "disc1/allbin/u40/font_rendered_ui/e047"
        )
        ui_profile = document.layout_profile(ui_index)
        self.assertEqual((ui_profile.columns, ui_profile.rows), (17, 6))
        self.assertEqual(ui_profile.row_policy, "exact")
        self.assertIn("名前を", document.japanese(ui_index))
        speaker_index = document.ids.index(
            "disc1/character_name/speaker/00"
        )
        self.assertEqual(
            document.layout_profile(speaker_index).columns,
            6,
        )
        first_metadata = format_entry_metadata(document, 0)
        self.assertIn("profile=17×3/최대", first_metadata)
        self.assertIn("unit_pool=u00", first_metadata)
        ui_metadata = format_entry_metadata(document, ui_index)
        self.assertIn("profile=17×6/행고정", ui_metadata)

    def test_workspace_saves_each_value_back_to_its_source_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_path = root / "first.json"
            second_path = root / "second.json"
            first = {
                "protected": "first",
                "entries": [{"id": "a", "ko": "하나", "jp": "一"}],
            }
            second = {
                "protected": "second",
                "translations": [{"id": "b", "ko": "둘"}],
            }
            first_path.write_text(
                json.dumps(first, ensure_ascii=False),
                encoding="utf-8",
            )
            second_path.write_text(
                json.dumps(second, ensure_ascii=False),
                encoding="utf-8",
            )
            editor_document = {
                "entry_count": 2,
                "entries": [
                    {
                        "id": "a",
                        "jp": "一",
                        "ko": "하나",
                        "source_group": "story_dialogue",
                    },
                    {
                        "id": "b",
                        "jp": "二",
                        "ko": "둘",
                        "source_group": "font_ui",
                        "editor_layout": {
                            "columns": 17,
                            "rows": 1,
                            "row_policy": "exact",
                            "label": "UI",
                        },
                    },
                ],
            }
            document = FontTranslationWorkspaceDocument(
                Path("workspace"),
                editor_document,
                bindings=[
                    TranslationBinding(
                        first_path,
                        ("entries", 0, "ko"),
                        "story_dialogue",
                        "story",
                    ),
                    TranslationBinding(
                        second_path,
                        ("translations", 0, "ko"),
                        "font_ui",
                        "ui",
                    ),
                ],
                source_documents={
                    first_path: first,
                    second_path: second,
                },
                control_contexts={},
                safe_slots={},
                unit_storage_profiles={},
            )
            document.set_value(0, "수정 하나")
            document.set_value(1, "수정 둘")
            backups = document.save()

            self.assertEqual(
                backups,
                (
                    first_path.with_name("first.json.bak"),
                    second_path.with_name("second.json.bak"),
                ),
            )
            saved_first = json.loads(first_path.read_text(encoding="utf-8"))
            saved_second = json.loads(
                second_path.read_text(encoding="utf-8")
            )
            self.assertEqual(saved_first["entries"][0]["ko"], "수정 하나")
            self.assertEqual(saved_second["translations"][0]["ko"], "수정 둘")
            self.assertEqual(saved_first["protected"], "first")
            self.assertEqual(saved_second["protected"], "second")
            self.assertFalse(document.dirty)

    def test_measures_explicit_17_by_3_layout(self) -> None:
        measurement = measure_layout(
            "가" * 17 + "\n" + "나" * 17 + "\n" + "다" * 17
        )
        self.assertTrue(measurement.fits)
        self.assertEqual(measurement.line_widths, (17, 17, 17))
        self.assertEqual(measurement.line_pixel_widths, (238, 238, 238))
        self.assertEqual(measurement.pixel_capacity_per_line, 238)
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

    def test_measures_halfwidth_visual_advance_without_relaxing_slots(
        self,
    ) -> None:
        measurement = measure_layout("가 나!?")
        self.assertEqual(measurement.line_widths, (5,))
        self.assertEqual(measurement.line_pixel_widths, (52,))
        self.assertEqual(measurement.visual_pixel_overflow_rows, ())
        self.assertEqual(glyph_advance_px("가"), 14)
        self.assertEqual(glyph_advance_px(" "), 8)
        self.assertEqual(line_pixel_width("!(),.?"), 48)

        visually_narrow_overflow = measure_layout(" " * 18)
        self.assertEqual(visually_narrow_overflow.line_widths, (18,))
        self.assertEqual(visually_narrow_overflow.line_pixel_widths, (144,))
        self.assertFalse(visually_narrow_overflow.fits)
        self.assertEqual(
            visually_narrow_overflow.column_overflow_rows,
            (1,),
        )
        self.assertEqual(
            visually_narrow_overflow.visual_pixel_overflow_rows,
            (),
        )

    def test_expands_dynamic_name_placeholders_to_maximum_width(self) -> None:
        self.assertEqual(
            expand_display_tokens(
                "{name:surname} {name:given} {unknown}"
            ),
            "시바□□ 세이치로 {unknown}",
        )
        measurement = measure_layout("{name:surname}\n{name:given}")
        self.assertEqual(measurement.line_widths, (4, 4))
        self.assertEqual(measurement.line_pixel_widths, (56, 56))

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
