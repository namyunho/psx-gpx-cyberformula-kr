import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.original_media import (
    deep_merge,
    file_hashes,
    read_cue_files,
    read_cue_tracks,
    resolved_paths,
    verify_cue,
    verify_track,
)


class OriginalMediaTests(unittest.TestCase):
    def test_deep_merge_preserves_unmodified_defaults(self) -> None:
        merged = deep_merge(
            {"disc1": {"cue": "default.cue", "data_track": {"path": "a.bin"}}},
            {"disc1": {"data_track": {"path": "local.bin"}}},
        )
        self.assertEqual(merged["disc1"]["cue"], "default.cue")
        self.assertEqual(merged["disc1"]["data_track"]["path"], "local.bin")

    def test_environment_overrides_paths(self) -> None:
        manifest = {
            "disc1": {
                "cue": "roms/default.cue",
                "data_track": {"path": "roms/default.bin"},
            },
            "disc2": {
                "cue": "roms/default2.cue",
                "data_track": {"path": "roms/default2.bin"},
                "audio_tracks": [
                    {"track": 2, "path": "roms/default2-track2.bin"}
                ],
            },
        }
        with mock.patch.dict(
            os.environ,
            {
                "PSX_DISC1_CUE": "/tmp/custom.cue",
                "PSX_DISC1_TRACK1": "/tmp/custom.bin",
                "PSX_DISC2_CUE": "/tmp/custom2.cue",
                "PSX_DISC2_TRACK1": "/tmp/custom2.bin",
                "PSX_DISC2_TRACK2": "/tmp/custom2-track2.bin",
            },
        ):
            paths = resolved_paths(manifest)
        self.assertEqual(paths["disc1_cue"], Path("/tmp/custom.cue"))
        self.assertEqual(paths["disc1_track1"], Path("/tmp/custom.bin"))
        self.assertEqual(paths["disc2_cue"], Path("/tmp/custom2.cue"))
        self.assertEqual(paths["disc2_track1"], Path("/tmp/custom2.bin"))
        self.assertEqual(
            paths["disc2_track2"], Path("/tmp/custom2-track2.bin")
        )

    def test_track_hash_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "track01.bin"
            path.write_bytes(b"PS1 test track")
            expected = file_hashes(path)
            result = verify_track(path, expected)
        self.assertTrue(result["verified"])

    def test_cue_layout_verification(self) -> None:
        text = """FILE "track01.bin" BINARY
  TRACK 01 MODE2/2352
FILE "track02.bin" BINARY
  TRACK 02 AUDIO
  TRACK 03 AUDIO
  TRACK 04 AUDIO
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disc1.cue"
            path.write_text(text, encoding="ascii")
            for name in ("track01.bin", "track02.bin"):
                (path.parent / name).touch()
            self.assertEqual(
                read_cue_tracks(path),
                ["MODE2/2352", "AUDIO", "AUDIO", "AUDIO"],
            )
            self.assertEqual(
                read_cue_files(path),
                ["track01.bin", "track02.bin"],
            )
            result = verify_cue(
                path,
                ["MODE2/2352", "AUDIO", "AUDIO", "AUDIO"],
            )
        self.assertTrue(result["verified"])


if __name__ == "__main__":
    unittest.main()
