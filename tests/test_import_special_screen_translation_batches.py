from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from scripts.import_special_screen_translation_batches import (
    discover_batch_pairs,
    load_object,
    merge_translation_batches,
)


ROOT = Path(__file__).resolve().parents[1]


class ImportSpecialScreenTranslationBatchesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workset_path = (
            ROOT / "work/translations/disc1-special-screen-text.json"
        )
        cls.canonical_path = (
            ROOT / "data/translations/disc1-special-screen-ko.json"
        )
        cls.batch_dir = (
            ROOT
            / "work/translations/disc1-special-screen-translation-batches"
        )
        required = (cls.workset_path, cls.canonical_path, cls.batch_dir)
        if not all(path.exists() for path in required):
            raise unittest.SkipTest("special-screen batch inputs unavailable")
        cls.source_paths, cls.translated_paths = discover_batch_pairs(
            cls.batch_dir
        )
        cls.workset = load_object(cls.workset_path)
        cls.canonical = load_object(cls.canonical_path)
        cls.source_batches = [
            load_object(path) for path in cls.source_paths
        ]
        cls.translated_batches = [
            load_object(path) for path in cls.translated_paths
        ]

    def merge(
        self,
        *,
        source_batches: list[dict] | None = None,
        translated_batches: list[dict] | None = None,
    ) -> tuple[dict, dict]:
        return merge_translation_batches(
            workset=self.workset,
            canonical=self.canonical,
            source_batches=(
                self.source_batches
                if source_batches is None
                else source_batches
            ),
            translated_batches=(
                self.translated_batches
                if translated_batches is None
                else translated_batches
            ),
            source_batch_paths=self.source_paths,
            translated_batch_paths=self.translated_paths,
            workset_path=self.workset_path,
        )

    def test_merges_all_ko_fields_in_stable_workset_order(self) -> None:
        merged, report = self.merge()

        work_ids = [
            entry["entry_id"] for entry in self.workset["entries"]
        ]
        merged_ids = [entry["id"] for entry in merged["translations"]]
        self.assertEqual(merged_ids, work_ids)
        self.assertEqual(len(merged_ids), 391)
        self.assertEqual(
            merged["translations"][0]["ko"],
            self.translated_batches[0]["entries"][0]["ko"],
        )
        self.assertEqual(report["validation"]["issue_entry_count"], 0)
        self.assertEqual(report["validation"]["issue_counts"], {})
        self.assertTrue(report["protected_batch_fields_unchanged"])

    def test_rejects_changes_outside_the_ko_field(self) -> None:
        translated = copy.deepcopy(self.translated_batches)
        translated[0]["entries"][0]["category"] = "changed"

        with self.assertRaisesRegex(
            ValueError,
            "fields other than entries\\[\\]\\.ko changed",
        ):
            self.merge(translated_batches=translated)


if __name__ == "__main__":
    unittest.main()
