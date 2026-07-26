from __future__ import annotations

import unittest

from scripts.audit_dialogue_reinsertion import (
    MAX_GLYPHS,
    minimum_required_glyph_count,
    visible_width,
    wrap_with_word_splitting,
    wrap_words,
)


class DialogueWordWrapTests(unittest.TestCase):
    def test_wraps_only_at_whitespace(self) -> None:
        result = wrap_words("가나다라마바사아자 차카타파하거너더러")
        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.lines,
            ("가나다라마바사아자", "차카타파하거너더러"),
        )

    def test_keeps_a_word_intact_at_exact_limit(self) -> None:
        word = "가" * 17
        result = wrap_words(word)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.lines, (word,))

    def test_splits_an_oversized_word_when_it_fits_three_rows(self) -> None:
        word = "가" * 18
        result = wrap_words(word)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.wrap_mode, "word-split-fallback")
        self.assertEqual(result.lines, ("가" * 17, "가"))
        self.assertEqual(result.oversized_words, (word,))

    def test_splits_words_to_rescue_a_four_row_word_wrap(self) -> None:
        result = wrap_words("가" * 10 + " " + "나" * 10 + " " + "다" * 10 + " " + "라" * 10)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.wrap_mode, "word-split-fallback")
        self.assertEqual(len(result.lines), 3)
        self.assertTrue(all(visible_width(line) <= 17 for line in result.lines))

    def test_still_blocks_content_that_exceeds_total_capacity(self) -> None:
        word = "가" * 52
        result = wrap_words(word)
        self.assertEqual(result.status, "word-overflow")
        self.assertEqual(len(result.lines), 4)
        self.assertEqual(
            minimum_required_glyph_count(word),
            MAX_GLYPHS + 1,
        )

    def test_capacity_count_credits_two_space_line_breaks(self) -> None:
        text = "가" * 17 + " " + "나" * 17 + " " + "다" * 17
        self.assertEqual(minimum_required_glyph_count(text), MAX_GLYPHS)

    def test_hard_wrap_never_splits_a_name_placeholder(self) -> None:
        lines = wrap_with_word_splitting("가" * 15 + "{name:given}나")
        self.assertEqual(lines, ("가" * 15, "{name:given}나"))

    def test_name_placeholders_use_fixed_visible_width(self) -> None:
        self.assertEqual(visible_width("{name:surname}"), 2)
        self.assertEqual(visible_width("{name:given}"), 4)
        result = wrap_words("{name:given}와 함께 출발한다")
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.lines, ("{name:given}와 함께 출발한다",))

    def test_existing_newlines_are_reflowable_whitespace(self) -> None:
        result = wrap_words("첫째 줄은\n둘째 줄과 다시 계산")
        self.assertEqual(result.status, "ready")
        self.assertNotIn("\n", "".join(result.lines))


if __name__ == "__main__":
    unittest.main()
