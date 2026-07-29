from __future__ import annotations

import re
import unittest

from scripts.audit_dialogue_reinsertion import (
    MAX_GLYPHS,
    chapter_label,
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
        self.assertEqual(visible_width("{name:surname}"), 4)
        self.assertEqual(visible_width("{name:given}"), 4)
        result = wrap_words("{name:given}와 함께 출발한다")
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.lines, ("{name:given}와 함께 출발한다",))

    def test_existing_newlines_are_reflowable_whitespace(self) -> None:
        result = wrap_words("첫째 줄은\n둘째 줄과 다시 계산")
        self.assertEqual(result.status, "ready")
        self.assertNotIn("\n", "".join(result.lines))

    def test_drops_only_spaces_when_non_space_text_fits_17x3(self) -> None:
        text = (
            "말도 안 돼…!\n"
            "이렇게 짧은 기간에 저런 기술을…?\n"
            "대체 어떤 내비게이션 시스템을 싣고 있는 거야!?"
        )
        result = wrap_words(text)
        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.wrap_mode,
            "space-drop-word-split-fallback",
        )
        self.assertLessEqual(len(result.lines), 3)
        self.assertTrue(
            all(visible_width(line) <= 17 for line in result.lines)
        )
        self.assertEqual(
            re.sub(r"\s+", "", text),
            re.sub(r"\s+", "", result.text),
        )

    def test_runtime_unit_labels_distinguish_test_drive_and_races(self) -> None:
        self.assertEqual(chapter_label(20, "story"), "story-u20")
        self.assertEqual(chapter_label(21, "test_drive"), "test-drive-u21")
        self.assertEqual(chapter_label(22, "race"), "race-u22")
        self.assertEqual(chapter_label(29, "race"), "race-u29")
        self.assertEqual(
            chapter_label(30, "embedded_race"),
            "embedded-race-u30",
        )
        self.assertEqual(
            chapter_label(34, "embedded_race"),
            "embedded-race-u34",
        )


if __name__ == "__main__":
    unittest.main()
