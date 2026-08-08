from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from scripts.extract_unindexed_font_text import (
    DEFAULT_KNOWN_WORKSETS,
    EXPECTED_DISCOVERY_CANDIDATE_COUNT,
    EXPECTED_ENTRY_COUNT,
    EXPECTED_FALSE_POSITIVE_COUNT,
    MIRRORED_FINALE_ALIAS_IDS,
    MIRRORED_FINALE_END,
    MIRRORED_FINALE_POOL_SHA256,
    MIRRORED_FINALE_START,
    MIRRORED_FINALE_UNITS,
    REVIEWED_SHORT_RACE_ALIASES,
    build_workset,
)


ROOT = Path(__file__).resolve().parents[1]


class ExtractUnindexedFontTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        disc_root = ROOT / "work/disc1/full"
        cls.allbin_path = disc_root / "ALLBIN.BIN"
        exe_path = disc_root / "SLPS_019.58"
        known = tuple(ROOT / path for path in DEFAULT_KNOWN_WORKSETS)
        required = (
            cls.allbin_path,
            exe_path,
            ROOT / "data/glyph-map.json",
            *known,
        )
        if not all(path.is_file() for path in required):
            raise unittest.SkipTest(
                "verified unindexed-font extraction inputs unavailable"
            )
        cls.document = build_workset(
            exe_path=exe_path,
            allbin_path=cls.allbin_path,
            glyph_map_path=ROOT / "data/glyph-map.json",
            known_workset_paths=known,
        )

    def test_reviewed_population_is_exact(self) -> None:
        summary = self.document["summary"]
        self.assertEqual(
            summary["discovery_candidate_count"],
            EXPECTED_DISCOVERY_CANDIDATE_COUNT,
        )
        self.assertEqual(
            summary["reviewed_false_positive_count"],
            EXPECTED_FALSE_POSITIVE_COUNT,
        )
        self.assertEqual(summary["entry_count"], EXPECTED_ENTRY_COUNT)

    def test_each_entry_preserves_original_allbin_bytes(self) -> None:
        allbin = self.allbin_path.read_bytes()
        for entry in self.document["entries"]:
            source = entry["source"]
            start = int(source["file_offset"], 16)
            end = start + source["byte_size"]
            raw = allbin[start:end]
            self.assertEqual(raw.hex().upper(), entry["original"]["raw_hex"])
            self.assertEqual(
                hashlib.sha256(raw).hexdigest(),
                source["sha256"],
            )

    def test_cooking_punctuation_only_fallthrough_page_is_included(self) -> None:
        entry = next(
            entry
            for entry in self.document["entries"]
            if entry["entry_id"]
            == "disc1/allbin/u38/unindexed_font/p1DA50"
        )
        self.assertEqual(entry["original"]["display_text"], "…。")
        self.assertEqual(entry["source"]["terminal"], "8000")

    def test_reviewed_short_reaction_pages_are_included(self) -> None:
        entries = {
            entry["entry_id"]: entry for entry in self.document["entries"]
        }
        expected = {
            "disc1/allbin/u04/unindexed_font/p00D86": "\u3000…。",
            "disc1/allbin/u16/unindexed_font/p0127A": "\u3000へ？",
            "disc1/allbin/u16/unindexed_font/p015B2": "\u3000…？",
            "disc1/allbin/u18/unindexed_font/p01F72": (
                "\u3000…{name:given}。"
            ),
            "disc1/allbin/u28/unindexed_font/p01008": "……。",
        }
        for entry_id, display_text in expected.items():
            self.assertEqual(
                entries[entry_id]["original"]["display_text"],
                display_text,
            )

        for (unit_index, start), alias_id in (
            REVIEWED_SHORT_RACE_ALIASES.items()
        ):
            entry_id = (
                f"disc1/allbin/u{unit_index:02d}/"
                f"unindexed_font/p{start:05X}"
            )
            self.assertEqual(
                entries[entry_id]["translation_alias_id"], alias_id
            )
            self.assertEqual(
                entries[entry_id]["original"]["display_text"], "…。"
            )

    def test_finale_mirror_is_exact_and_aliased(self) -> None:
        allbin = self.allbin_path.read_bytes()
        entries = self.document["entries"]
        for unit_index in MIRRORED_FINALE_UNITS:
            mirrored = [
                entry
                for entry in entries
                if int(entry["source"]["unit_index"]) == unit_index
                and entry["entry_id"].startswith(
                    f"disc1/allbin/u{unit_index:02d}/"
                    "unindexed_font/finale_ref"
                )
            ]
            self.assertEqual(len(mirrored), len(MIRRORED_FINALE_ALIAS_IDS))
            self.assertEqual(
                [entry["translation_alias_id"] for entry in mirrored],
                list(MIRRORED_FINALE_ALIAS_IDS),
            )
            pool_start = int(mirrored[0]["source"]["file_offset"], 16)
            pool = allbin[
                pool_start :
                pool_start + MIRRORED_FINALE_END - MIRRORED_FINALE_START
            ]
            self.assertEqual(hashlib.sha256(pool).hexdigest(), MIRRORED_FINALE_POOL_SHA256)
            self.assertTrue(all(entry["source"]["terminal"] == "8000" for entry in mirrored))


if __name__ == "__main__":
    unittest.main()
