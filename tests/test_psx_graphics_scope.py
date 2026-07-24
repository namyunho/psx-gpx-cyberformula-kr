import unittest
from collections import Counter

from scripts.psx_graphics_scope import classify_state


class PsxGraphicsScopeTests(unittest.TestCase):
    def test_start_roles_exclude_fonts_and_portraits(self) -> None:
        self.assertEqual(classify_state("START.BIN", 2)[0], "font_provider")
        self.assertEqual(classify_state("START.BIN", 40)[0], "font_provider")
        self.assertEqual(classify_state("START.BIN", 41)[0], "portrait_provider")
        self.assertEqual(
            classify_state("START.BIN", 39)[0],
            "baked_text_visual_review",
        )

    def test_course_roles_partition_visual_and_non_graphic_states(self) -> None:
        self.assertEqual(
            classify_state("COURSE.BIN", 25)[0],
            "baked_text_visual_review",
        )
        self.assertEqual(
            classify_state("COURSE.BIN", 26)[0],
            "non_graphic_course_data",
        )
        self.assertEqual(
            classify_state("COURSE.BIN", 275)[0],
            "non_graphic_course_data",
        )
        self.assertEqual(
            classify_state("COURSE.BIN", 276)[0],
            "baked_text_visual_review",
        )

    def test_full_disc_visual_denominator_has_no_unclassified_state(self) -> None:
        schedule_counts = {
            "MINI_G1.BIN": 2,
            "MINI_G2.BIN": 2,
            "MINI_G3.BIN": 3,
            "MINI_G4.BIN": 3,
            "AVM_MAP.BIN": 1334,
            "START.BIN": 65,
            "OUTSIDE.BIN": 11,
            "MACHINE.BIN": 42,
            "COURSE.BIN": 277,
        }
        roles = Counter(
            classify_state(filename, index)[0]
            for filename, count in schedule_counts.items()
            for index in range(count)
        )
        self.assertEqual(sum(roles.values()), 1739)
        self.assertEqual(
            roles,
            {
                "baked_text_visual_review": 1463,
                "font_provider": 2,
                "portrait_provider": 24,
                "non_graphic_course_data": 250,
            },
        )


if __name__ == "__main__":
    unittest.main()
