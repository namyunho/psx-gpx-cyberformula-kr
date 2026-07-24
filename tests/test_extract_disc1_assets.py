import unittest

from scripts.extract_disc1_assets import sector_header, xa_audio_key


class ExtractDisc1AssetsTests(unittest.TestCase):
    def test_classifies_xa_audio_sector(self) -> None:
        raw = bytearray(2352)
        raw[:12] = bytes.fromhex("00FFFFFFFFFFFFFFFFFFFF00")
        raw[15] = 2
        raw[16:20] = bytes((1, 7, 0x64, 4))
        raw[20:24] = raw[16:20]
        header = sector_header(bytes(raw))
        self.assertEqual(header["mode"], "MODE2/FORM2")
        self.assertEqual(xa_audio_key(header), (1, 7, 4))

    def test_does_not_promote_form1_or_non_audio_sector(self) -> None:
        raw = bytearray(2352)
        raw[:12] = bytes.fromhex("00FFFFFFFFFFFFFFFFFFFF00")
        raw[15] = 2
        raw[16:20] = bytes((1, 1, 0x08, 0))
        raw[20:24] = raw[16:20]
        header = sector_header(bytes(raw))
        self.assertEqual(header["mode"], "MODE2/FORM1")
        self.assertIsNone(xa_audio_key(header))


if __name__ == "__main__":
    unittest.main()
