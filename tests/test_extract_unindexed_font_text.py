from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from scripts.extract_unindexed_font_text import (
    DEFAULT_KNOWN_WORKSETS,
    EXPECTED_DISCOVERY_CANDIDATE_COUNT,
    EXPECTED_ENTRY_COUNT,
    EXPECTED_FALSE_POSITIVE_COUNT,
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


if __name__ == "__main__":
    unittest.main()
