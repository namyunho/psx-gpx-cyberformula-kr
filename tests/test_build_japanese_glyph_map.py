import unittest

from scripts.build_japanese_glyph_map import (
    ALTERNATE_GLYPH_COUNT,
    PRIMARY_GLYPH_COUNT,
    build_document,
    complete_table_glyphs,
    jis_level1_characters,
    structural_glyphs,
)


class BuildJapaneseGlyphMapTests(unittest.TestCase):
    def test_primary_structural_ranges_have_verified_boundaries(self) -> None:
        glyphs = structural_glyphs("primary")
        self.assertEqual(glyphs[0x0000], "　")
        self.assertEqual(glyphs[0x0007], "々")
        self.assertEqual(glyphs[0x0046], "ぁ")
        self.assertEqual(glyphs[0x0066], "ち")
        self.assertEqual(glyphs[0x0067], "っ")
        self.assertEqual(glyphs[0x0094], "ん")
        self.assertEqual(glyphs[0x0095], "ァ")
        self.assertEqual(glyphs[0x00E2], "ン")
        self.assertEqual(glyphs[0x00E4], "ヶ")
        self.assertEqual(glyphs[0x00E5], "♥")

    def test_alternate_structural_ranges_are_shifted_four_slots(self) -> None:
        primary = structural_glyphs("primary")
        alternate = structural_glyphs("alternate")
        for primary_index in range(0x001E, 0x00E6):
            self.assertEqual(
                primary[primary_index],
                alternate[primary_index - 4],
            )

    def test_complete_tables_cover_every_slot(self) -> None:
        primary = complete_table_glyphs("primary")
        alternate = complete_table_glyphs("alternate")
        self.assertEqual(set(primary), set(range(PRIMARY_GLYPH_COUNT)))
        self.assertEqual(set(alternate), set(range(ALTERNATE_GLYPH_COUNT)))
        self.assertEqual(primary[0x00E6], "愛")
        self.assertEqual(primary[0x04C4], "腕")
        self.assertEqual(primary[0x04C5], "醤")
        self.assertEqual(primary[0x04CC], "贅")
        self.assertEqual(alternate[0x00E2], "亜")
        self.assertEqual(alternate[0x0589], "鰐")
        self.assertEqual(alternate[0x058A], "弌")
        self.assertEqual(alternate[0x058B], "丼")
        self.assertEqual(alternate[0x059E], "鴎")
        self.assertEqual(alternate[0x05A0], "昴")
        self.assertEqual(alternate[0x05AB], "黎")
        self.assertEqual(alternate[0x05AC], "濱")
        self.assertEqual(alternate[0x05B1], "曝")
        self.assertEqual(alternate[0x05BB], "翔")
        self.assertEqual(alternate[0x05C5], "瓢")
        self.assertEqual(alternate[0x05CB], "ヲ")

    def test_standard_kanji_are_strict_jis_level1_subsets(self) -> None:
        positions = {
            character: index
            for index, character in enumerate(jis_level1_characters())
        }
        for table_id, begin, end in (
            ("primary", 0x00E6, 0x04C4),
            ("alternate", 0x00E2, 0x0589),
        ):
            glyphs = complete_table_glyphs(table_id)
            selected = [positions[glyphs[index]] for index in range(begin, end + 1)]
            self.assertTrue(
                all(left < right for left, right in zip(selected, selected[1:]))
            )

    def test_document_keeps_tables_scoped(self) -> None:
        document = build_document()
        self.assertEqual(document["schema_version"], 3)
        self.assertEqual(document["tables"]["primary"]["scope"], "dialogue")
        self.assertEqual(
            document["tables"]["alternate"]["scope"],
            "font-rendered-ui",
        )
        self.assertEqual(
            document["tables"]["primary"]["glyph_count"],
            PRIMARY_GLYPH_COUNT,
        )
        self.assertEqual(
            document["tables"]["alternate"]["glyph_count"],
            ALTERNATE_GLYPH_COUNT,
        )


if __name__ == "__main__":
    unittest.main()
