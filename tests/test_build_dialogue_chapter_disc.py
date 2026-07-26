from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.build_dialogue_chapter_disc import (
    apply_sector_mutations,
    compact_integer_ranges,
    plan_file_mutations,
    recorded_runtime_validation,
    write_local_cue,
)
from scripts.psx_sector import (
    RAW_SECTOR_SIZE,
    SYNC_PATTERN,
    inspect_mode2_form1,
    rebuild_mode2_form1,
)


def valid_sector() -> bytes:
    sector = bytearray(RAW_SECTOR_SIZE)
    sector[:12] = SYNC_PATTERN
    sector[12:16] = bytes.fromhex("00020002")
    sector[16:24] = bytes.fromhex("0000080000000800")
    return rebuild_mode2_form1(sector, address_mode="zero")


class DialogueChapterDiscTests(unittest.TestCase):
    def test_plans_and_rebuilds_changed_form1_sector(self) -> None:
        source = bytes(4096)
        replacement = bytearray(source)
        replacement[2047:2050] = b"abc"
        plan = plan_file_mutations(
            owner="TEST.BIN",
            file_lba=10,
            source=source,
            replacement=bytes(replacement),
        )
        self.assertEqual(set(plan), {10, 11})

        first, report = apply_sector_mutations(valid_sector(), plan[10])
        self.assertTrue(inspect_mode2_form1(first).valid)
        self.assertEqual(first[24 + 2047], ord("a"))
        self.assertEqual(report["ecc_address_mode"], "zero")

    def test_compacts_lba_ranges(self) -> None:
        self.assertEqual(
            compact_integer_ranges([4, 5, 6, 9]),
            [
                {"start": 4, "end_inclusive": 6, "count": 3},
                {"start": 9, "end_inclusive": 9, "count": 1},
            ],
        )

    def test_runtime_evidence_requires_exact_units_and_track_hash(self) -> None:
        manifest = {
            "units": [
                {
                    "unit_index": unit_index,
                    "runtime_validation": {
                        "status": "passed",
                        "date": "2026-07-27",
                        "scope": "chapter-replay",
                        "track1_sha256": "verified-track",
                    },
                }
                for unit_index in (0, 21)
            ]
        }
        report = recorded_runtime_validation(
            manifest,
            selected_units=[0, 21],
            output_track_sha256="verified-track",
        )
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report["status"], "passed-user-reported")
        self.assertEqual(
            [unit["unit_index"] for unit in report["units"]],
            [0, 21],
        )
        self.assertIsNone(
            recorded_runtime_validation(
                manifest,
                selected_units=[0, 21],
                output_track_sha256="different-track",
            )
        )
        self.assertIsNone(
            recorded_runtime_validation(
                manifest,
                selected_units=[0],
                output_track_sha256="verified-track",
            )
        )

    def test_writes_cue_with_original_audio_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            (source / "track1.bin").touch()
            (source / "track2.bin").touch()
            source_cue = source / "disc.cue"
            source_cue.write_text(
                'FILE "track1.bin" BINARY\n'
                "  TRACK 01 MODE2/2352\n"
                'FILE "track2.bin" BINARY\n'
                "  TRACK 02 AUDIO\n",
                encoding="ascii",
            )
            output_track = output / "patched.bin"
            output_track.touch()
            output_cue = output / "patched.cue"
            write_local_cue(
                source_cue,
                output_track=output_track,
                output_cue=output_cue,
            )
            text = output_cue.read_text(encoding="utf-8")
            self.assertIn('FILE "patched.bin" BINARY', text)
            self.assertIn('FILE "../source/track2.bin" BINARY', text)


if __name__ == "__main__":
    unittest.main()
