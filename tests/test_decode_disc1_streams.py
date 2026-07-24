from pathlib import Path
import tempfile
import unittest
import wave

from scripts.decode_disc1_streams import wav_report


class DecodeDisc1StreamsTests(unittest.TestCase):
    def test_reports_pcm16_wav(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "test.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(8000)
                wav.writeframes(b"\0\0" * 80)
            report = wav_report(path, root)
        self.assertEqual(report["sample_rate"], 8000)
        self.assertEqual(report["frame_count"], 80)
        self.assertEqual(report["duration_seconds"], 0.01)


if __name__ == "__main__":
    unittest.main()
