import unittest

from scripts.verify_disc1_extraction import expected_xa_frames


class VerifyDisc1ExtractionTests(unittest.TestCase):
    def test_xa_frame_count_for_mono_and_stereo(self) -> None:
        self.assertEqual(expected_xa_frames(10, 0x04), 40320)
        self.assertEqual(expected_xa_frames(10, 0x01), 20160)


if __name__ == "__main__":
    unittest.main()
