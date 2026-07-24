import unittest

from scripts.psx_loader_calls import direct_a0_constant


class PsxLoaderCallsTests(unittest.TestCase):
    def test_reads_li_alias(self) -> None:
        self.assertEqual(direct_a0_constant("li", "$a0, 0x56"), 0x56)

    def test_reads_addiu_from_zero(self) -> None:
        self.assertEqual(
            direct_a0_constant("addiu", "$a0, $zero, 0x85"),
            0x85,
        )

    def test_rejects_register_derived_argument(self) -> None:
        self.assertIsNone(direct_a0_constant("move", "$a0, $s0"))
        self.assertIsNone(direct_a0_constant("addiu", "$a0, $s0, 1"))


if __name__ == "__main__":
    unittest.main()
