#!/usr/bin/env python3
"""Build the retired high-token renderer-hook PoC for reproduction."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import struct

try:
    from scripts.build_font_poc import (
        ALLBIN_LBA,
        DIALOGUE_LINES,
        DIALOGUE_REGION_OFFSET,
        DIALOGUE_REGION_TOKENS,
        ORIGINAL_PUNCTUATION,
        POC_GLYPH_INDEX,
        patch_raw_fragment,
        write_poc_cue,
    )
    from scripts.korean_font import crop_to_psx, rasterize_ttf_glyph
    from scripts.psx_font import GLYPH_SIZE, pack_glyph
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from build_font_poc import (
        ALLBIN_LBA,
        DIALOGUE_LINES,
        DIALOGUE_REGION_OFFSET,
        DIALOGUE_REGION_TOKENS,
        ORIGINAL_PUNCTUATION,
        POC_GLYPH_INDEX,
        patch_raw_fragment,
        write_poc_cue,
    )
    from korean_font import crop_to_psx, rasterize_ttf_glyph
    from psx_font import GLYPH_SIZE, pack_glyph


EXE_LOAD_ADDRESS = 0x80030000
EXE_HEADER_SIZE = 0x800
SLPS_LBA = 24
HOOK_PATCH_RAM = 0x80032804
HOOK_CODE_RAM = 0x8005BB18
HANGUL_CACHE_RAM = 0x8005B5E4
HANGUL_CACHE_READ_RAM = 0xA005B5E4
HANGUL_TOKEN_PREFIX = 0x7000
HANGUL_REMAP_POINTER_BASE_RAM = 0x800B6054
HANGUL_REMAP_POINTER_SIZE = 18 * 2

EXPECTED_SOURCE_SLPS_SHA256 = "0CBDA75255E7F9EDBB758EE8B815082C3DD167E7E0E709A5526C17653014FAB9"
EXPECTED_HOOK_SITE = bytes.fromhex("FF0F6330C010030021104300")
HOOK_SITE_REPLACEMENT_WORDS = 3


REG = {
    "zero": 0,
    "at": 1,
    "v0": 2,
    "v1": 3,
    "a0": 4,
    "a1": 5,
}


def exe_offset(ram_address: int) -> int:
    return EXE_HEADER_SIZE + (ram_address - EXE_LOAD_ADDRESS)


def i_type(opcode: int, rs: int, rt: int, immediate: int) -> int:
    return (opcode << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF)


def j_type(opcode: int, target: int) -> int:
    return (opcode << 26) | ((target >> 2) & 0x03FFFFFF)


def r_type(rs: int, rt: int, rd: int, shift: int, funct: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | (shift << 6) | funct


def encode_words(words: list[int]) -> bytes:
    return struct.pack(f"<{len(words)}I", *words)


def branch_offset(pc: int, target: int) -> int:
    offset = (target - (pc + 4)) // 4
    if target != pc + 4 + offset * 4:
        raise ValueError("branch target is not word-aligned")
    if not -0x8000 <= offset <= 0x7FFF:
        raise ValueError("branch target is outside signed 16-bit range")
    return offset


def build_hook_code() -> bytes:
    not_hangul = HOOK_CODE_RAM + 0x2C
    words = [
        # The engine remaps raw tokens by reading current_text_base + token*2
        # before this point. Recover the 0x7000 local index from that remap
        # address for the first-dialogue PoC.
        i_type(0x0F, REG["zero"], REG["a1"], HANGUL_REMAP_POINTER_BASE_RAM >> 16),
        i_type(0x0D, REG["a1"], REG["a1"], HANGUL_REMAP_POINTER_BASE_RAM & 0xFFFF),
        r_type(REG["v0"], REG["a1"], REG["at"], 0, 0x23),  # subu at, v0, a1
        i_type(0x0B, REG["at"], REG["a1"], HANGUL_REMAP_POINTER_SIZE),  # sltiu a1, at, size
        i_type(
            0x04,
            REG["a1"],
            REG["zero"],
            branch_offset(HOOK_CODE_RAM + 0x10, not_hangul),
        ),
        i_type(0x0C, REG["at"], REG["a1"], 1),  # delay slot: andi a1, at, 1
        i_type(0x05, REG["a1"], REG["zero"], branch_offset(HOOK_CODE_RAM + 0x18, not_hangul)),
        0,
        r_type(0, REG["at"], REG["v1"], 1, 0x02),  # srl v1, at, 1
        i_type(0x0F, REG["zero"], REG["a0"], HANGUL_CACHE_READ_RAM >> 16),
        i_type(0x0D, REG["a0"], REG["a0"], HANGUL_CACHE_READ_RAM & 0xFFFF),
        # Reproduce the three original instructions displaced at 0x80032804.
        i_type(0x0C, REG["v1"], REG["v1"], 0x0FFF),  # andi v1, v1, 0x0FFF
        0x000310C0,  # sll v0, v1, 3
        r_type(REG["v0"], REG["v1"], REG["v0"], 0, 0x21),  # addu v0, v0, v1
        j_type(0x02, 0x80032810),
        0,
    ]
    return encode_words(words)


def build_hook_site_patch(target: int = HOOK_CODE_RAM) -> bytes:
    return encode_words([j_type(0x02, target), 0, 0])


def patch_slps_cache_hook(
    slps_data: bytes, glyphs: dict[str, bytes], *, require_source_hash: bool = False
) -> tuple[bytes, dict[str, int]]:
    hangul = [
        character
        for character in dict.fromkeys("".join(DIALOGUE_LINES))
        if "가" <= character <= "힣"
    ]
    if set(glyphs) != set(hangul):
        raise ValueError("glyph set does not match translated Hangul characters")

    glyph_bytes = bytearray()
    mapping: dict[str, int] = {}
    for index, character in enumerate(hangul):
        glyph = glyphs[character]
        if len(glyph) != GLYPH_SIZE:
            raise ValueError(f"glyph for {character!r} must be {GLYPH_SIZE} bytes")
        mapping[character] = HANGUL_TOKEN_PREFIX + index
        glyph_bytes.extend(glyph)

    hook_code = build_hook_code()
    patched = bytearray(slps_data)
    hook_site = exe_offset(HOOK_PATCH_RAM)
    if bytes(patched[hook_site : hook_site + len(EXPECTED_HOOK_SITE)]) != EXPECTED_HOOK_SITE:
        raise ValueError("hook site bytes differ from the verified SLPS_019.58")
    if require_source_hash and sha256(slps_data) != EXPECTED_SOURCE_SLPS_SHA256:
        raise ValueError("source SLPS_019.58 hash differs from the verified Disc 1 executable")

    cache_offset = exe_offset(HANGUL_CACHE_RAM)
    cache_end = cache_offset + len(glyph_bytes)
    hook_offset = exe_offset(HOOK_CODE_RAM)
    hook_end = hook_offset + len(hook_code)
    if cache_end > hook_offset:
        raise ValueError("Hangul cache overlaps hook code")

    patched[cache_offset:cache_end] = glyph_bytes
    patched[hook_offset:hook_end] = hook_code
    patched[hook_site : hook_site + 4 * HOOK_SITE_REPLACEMENT_WORDS] = build_hook_site_patch()
    return bytes(patched), mapping


def patch_allbin_cache_dialogue(allbin_data: bytes, mapping: dict[str, int]) -> bytes:
    full_mapping = dict(ORIGINAL_PUNCTUATION)
    full_mapping.update(mapping)
    full_mapping[" "] = POC_GLYPH_INDEX

    first_line = [full_mapping[character] for character in DIALOGUE_LINES[0]]
    second_line = [full_mapping[character] for character in DIALOGUE_LINES[1]]
    if len(first_line) > 15 or len(second_line) != 15:
        raise ValueError("translated dialogue must fit the original 15-column layout")
    first_line.extend([full_mapping[" "]] * (15 - len(first_line)))
    tokens = [0x903F, *first_line, 0xFFFB, 0x0000, *second_line, 0x8000]
    if len(tokens) != DIALOGUE_REGION_TOKENS:
        raise ValueError("translated dialogue token region changed size")

    original_tokens = struct.unpack_from(
        f"<{DIALOGUE_REGION_TOKENS}H", allbin_data, DIALOGUE_REGION_OFFSET
    )
    expected_controls = {0: 0x903F, 16: 0xFFFB, 17: 0x0000, 33: 0x8000}
    if any(original_tokens[index] != value for index, value in expected_controls.items()):
        raise ValueError("source dialogue control layout differs from the verified sample")

    patched = bytearray(allbin_data)
    struct.pack_into(f"<{len(tokens)}H", patched, DIALOGUE_REGION_OFFSET, *tokens)
    return bytes(patched)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slps", type=Path, required=True)
    parser.add_argument("--allbin", type=Path, required=True)
    parser.add_argument("--ttf", type=Path, required=True)
    parser.add_argument("--intensity", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--track1", type=Path)
    parser.add_argument("--track-output", type=Path)
    parser.add_argument("--source-cue", type=Path)
    parser.add_argument("--cue-output", type=Path)
    parser.add_argument("--allow-invalid-edc", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.intensity <= 7:
        parser.error("--intensity must be between 1 and 7")

    from PIL import ImageFont

    font = ImageFont.truetype(str(args.ttf), 15)
    hangul = [
        character
        for character in dict.fromkeys("".join(DIALOGUE_LINES))
        if "가" <= character <= "힣"
    ]
    glyphs = {
        character: pack_glyph(
            crop_to_psx(rasterize_ttf_glyph(font, character), intensity=args.intensity)
        )
        for character in hangul
    }

    original_slps = args.slps.read_bytes()
    original_allbin = args.allbin.read_bytes()
    patched_slps, mapping = patch_slps_cache_hook(
        original_slps, glyphs, require_source_hash=True
    )
    patched_allbin = patch_allbin_cache_dialogue(original_allbin, mapping)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    slps_output = args.output_dir / "SLPS_019.58"
    allbin_output = args.output_dir / "ALLBIN.BIN"
    slps_output.write_bytes(patched_slps)
    allbin_output.write_bytes(patched_allbin)

    print(f"dialogue={DIALOGUE_LINES[0]} / {DIALOGUE_LINES[1]}")
    print(
        "mapping="
        + ",".join(f"{character}=0x{mapping[character]:04X}" for character in hangul)
    )
    print(
        f"hook_site=0x{HOOK_PATCH_RAM:X} hook_code=0x{HOOK_CODE_RAM:X} "
        f"cache=0x{HANGUL_CACHE_RAM:X} glyphs={len(hangul)}"
    )
    print(f"SLPS_019.58 size={len(patched_slps)} sha256={sha256(patched_slps)} output={slps_output}")
    print(f"ALLBIN.BIN size={len(patched_allbin)} sha256={sha256(patched_allbin)} output={allbin_output}")

    raw_options = (args.track1, args.track_output, args.source_cue, args.cue_output)
    if any(raw_options) and not all(raw_options):
        parser.error(
            "--track1, --track-output, --source-cue and --cue-output "
            "must be provided together"
        )
    if args.track1:
        if not args.allow_invalid_edc:
            parser.error(
                "raw PoC output leaves EDC/ECC invalid; explicitly pass "
                "--allow-invalid-edc for emulator-only use"
            )
        assert args.track_output and args.source_cue and args.cue_output
        args.track_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.track1, args.track_output)
        changed: set[int] = set()
        with args.track_output.open("r+b") as image:
            changed |= patch_raw_fragment(
                image,
                file_lba=SLPS_LBA,
                file_offset=0,
                expected=original_slps,
                replacement=patched_slps,
            )
            changed |= patch_raw_fragment(
                image,
                file_lba=ALLBIN_LBA,
                file_offset=0,
                expected=original_allbin,
                replacement=patched_allbin,
            )
        write_poc_cue(args.source_cue, args.track_output, args.cue_output)
        print(
            f"track1={args.track_output} changed_lba="
            f"{','.join(str(value) for value in sorted(changed))} "
            f"edc_ecc=invalid-emulator-only cue={args.cue_output}"
        )


if __name__ == "__main__":
    main()
