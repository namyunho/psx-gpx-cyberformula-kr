from __future__ import annotations

import unittest

from scripts.psx_sector import (
    RAW_SECTOR_SIZE,
    SYNC_PATTERN,
    inspect_mode2_form1,
    rebuild_mode2_form1,
)


def synthetic_form1_sector() -> bytes:
    sector = bytearray(RAW_SECTOR_SIZE)
    sector[:12] = SYNC_PATTERN
    sector[12:16] = bytes.fromhex("00020002")
    sector[16:24] = bytes.fromhex("0000080000000800")
    sector[24:2072] = bytes(
        (index * 29 + 7) & 0xFF for index in range(2048)
    )
    return bytes(sector)


class PsxSectorTests(unittest.TestCase):
    def test_rebuilds_and_validates_mode2_form1(self) -> None:
        rebuilt = rebuild_mode2_form1(
            synthetic_form1_sector(),
            address_mode="zero",
        )
        integrity = inspect_mode2_form1(rebuilt)
        self.assertTrue(integrity.valid)
        self.assertTrue(integrity.edc_valid)
        self.assertTrue(integrity.zero_address_ecc_valid)
        self.assertFalse(integrity.sector_address_ecc_valid)

    def test_detects_user_data_corruption(self) -> None:
        rebuilt = bytearray(
            rebuild_mode2_form1(
                synthetic_form1_sector(),
                address_mode="zero",
            )
        )
        rebuilt[400] ^= 0x80
        integrity = inspect_mode2_form1(rebuilt)
        self.assertFalse(integrity.valid)
        self.assertFalse(integrity.edc_valid)

    def test_rejects_form2(self) -> None:
        sector = bytearray(synthetic_form1_sector())
        sector[18] |= 0x20
        sector[22] |= 0x20
        with self.assertRaisesRegex(ValueError, "Form2"):
            rebuild_mode2_form1(sector, address_mode="zero")

    def test_rejects_mismatched_duplicated_subheader(self) -> None:
        sector = bytearray(synthetic_form1_sector())
        sector[20] ^= 1
        with self.assertRaisesRegex(ValueError, "subheader"):
            rebuild_mode2_form1(sector, address_mode="zero")


if __name__ == "__main__":
    unittest.main()
