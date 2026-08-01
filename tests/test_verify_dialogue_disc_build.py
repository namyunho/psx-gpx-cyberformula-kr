from pathlib import Path
import unittest

from scripts.verify_dialogue_disc_build import recorded_path


class VerifyDialogueDiscBuildTests(unittest.TestCase):
    def test_resolves_relative_recorded_path_from_build_directory(self) -> None:
        self.assertEqual(
            recorded_path(
                "patched.bin",
                build_dir=Path("work/build/example"),
                label="track",
            ),
            Path("work/build/example/patched.bin"),
        )

    def test_preserves_absolute_recorded_path(self) -> None:
        path = Path("/tmp/patched.bin")
        self.assertEqual(
            recorded_path(path.as_posix(), build_dir=Path("ignored"), label="track"),
            path,
        )


if __name__ == "__main__":
    unittest.main()
