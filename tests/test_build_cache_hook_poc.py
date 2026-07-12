import struct
import unittest

from scripts.build_cache_hook_poc import (
    EXPECTED_HOOK_SITE,
    HANGUL_CACHE_RAM,
    HANGUL_TOKEN_PREFIX,
    HOOK_CODE_RAM,
    HOOK_PATCH_RAM,
    build_hook_code,
    build_hook_site_patch,
    exe_offset,
    patch_allbin_cache_dialogue,
    patch_slps_cache_hook,
)
from scripts.build_font_poc import (
    DIALOGUE_LINES,
    DIALOGUE_REGION_OFFSET,
    DIALOGUE_REGION_TOKENS,
    POC_GLYPH_INDEX,
)
from scripts.psx_font import GLYPH_SIZE


class BuildCacheHookPocTests(unittest.TestCase):
    def test_builds_hook_code_and_site_patch(self) -> None:
        hook = build_hook_code()
        site = build_hook_site_patch()

        self.assertEqual(len(hook), 16 * 4)
        self.assertEqual(len(site), 3 * 4)
        self.assertEqual(struct.unpack_from("<I", site, 0)[0] >> 26, 0x02)
        self.assertEqual(site[4:], bytes(8))

    def test_patches_slps_hook_and_cache(self) -> None:
        slps = bytearray(exe_offset(HOOK_CODE_RAM) + 0x100)
        slps[exe_offset(HOOK_PATCH_RAM) : exe_offset(HOOK_PATCH_RAM) + len(EXPECTED_HOOK_SITE)] = (
            EXPECTED_HOOK_SITE
        )
        hangul = [
            character
            for character in dict.fromkeys("".join(DIALOGUE_LINES))
            if "가" <= character <= "힣"
        ]
        glyphs = {
            character: bytes([index + 1]) * GLYPH_SIZE
            for index, character in enumerate(hangul)
        }

        patched, mapping = patch_slps_cache_hook(bytes(slps), glyphs)

        self.assertEqual(mapping[hangul[0]], HANGUL_TOKEN_PREFIX)
        self.assertNotEqual(
            patched[exe_offset(HOOK_PATCH_RAM) : exe_offset(HOOK_PATCH_RAM) + 4],
            EXPECTED_HOOK_SITE[:4],
        )
        self.assertEqual(
            patched[exe_offset(HANGUL_CACHE_RAM) : exe_offset(HANGUL_CACHE_RAM) + GLYPH_SIZE],
            bytes([1]) * GLYPH_SIZE,
        )
        self.assertEqual(
            patched[exe_offset(HOOK_CODE_RAM) : exe_offset(HOOK_CODE_RAM) + len(build_hook_code())],
            build_hook_code(),
        )

    def test_patches_dialogue_tokens_to_cache_range(self) -> None:
        allbin = bytearray(0x200)
        struct.pack_into("<H", allbin, DIALOGUE_REGION_OFFSET, 0x903F)
        struct.pack_into("<H", allbin, DIALOGUE_REGION_OFFSET + 16 * 2, 0xFFFB)
        struct.pack_into("<H", allbin, DIALOGUE_REGION_OFFSET + 33 * 2, 0x8000)
        hangul = [
            character
            for character in dict.fromkeys("".join(DIALOGUE_LINES))
            if "가" <= character <= "힣"
        ]
        mapping = {
            character: HANGUL_TOKEN_PREFIX + index
            for index, character in enumerate(hangul)
        }

        patched = patch_allbin_cache_dialogue(bytes(allbin), mapping)
        tokens = struct.unpack_from(
            f"<{DIALOGUE_REGION_TOKENS}H", patched, DIALOGUE_REGION_OFFSET
        )

        self.assertEqual(tokens[0], 0x903F)
        self.assertEqual(tokens[1], 0x000C)
        self.assertEqual(tokens[2], HANGUL_TOKEN_PREFIX)
        self.assertEqual(tokens[16], 0xFFFB)
        self.assertEqual(tokens[17], 0x0000)
        self.assertEqual(tokens[-1], 0x8000)
        self.assertIn(POC_GLYPH_INDEX, tokens)


if __name__ == "__main__":
    unittest.main()
