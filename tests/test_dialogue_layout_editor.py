from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.dialogue_layout_editor import (
    DialogueDocument,
    DialogueEditorError,
    conservative_word_wrap,
    expand_display_tokens,
    filter_entry_indices,
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
