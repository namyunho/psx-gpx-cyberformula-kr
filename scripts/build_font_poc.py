#!/usr/bin/env python3
"""Build same-size START/ALLBIN files for the first visible Hangul PoC."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct

try:
    from scripts.korean_font import load_font_profile, pack_profile_glyphs
    from scripts.psx_font import GLYPH_SIZE, pack_glyph
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from korean_font import load_font_profile, pack_profile_glyphs
    from psx_font import GLYPH_SIZE, pack_glyph


DEFAULT_FONT_PROFILE = (
    Path(__file__).resolve().parent.parent / "config" / "font-profile.json"
)
FONT_OFFSET = 0x1A000
POC_GLYPH_INDEX = 0x4CD
TEXT_TOKEN_OFFSET = 0x6E
EXPECTED_ORIGINAL_TOKEN = 0x03B7
EXPECTED_SOURCE_START_SHA256 = (
    "D0B22EFB4E5EA46C869F822AF9BC7F207BC95A670A25ACB15FC3DCD2AB3BF8CC"
)
EXPECTED_SOURCE_ALLBIN_SHA256 = (
    "6F61295BE0CE2D7D8F38B57BADC3B1073E5C16EC3FBA5CE898F3368051336A0E"
)
START_LBA = 225
ALLBIN_LBA = 9919
RAW_SECTOR_SIZE = 2352
USER_DATA_OFFSET = 24
USER_DATA_SIZE = 2048

DIALOGUE_LINES = (
    "（드디어 여기까지 왔다…",
    "꿈의 팀 「스고 그랑프리」）",
)
DIALOGUE_REGION_OFFSET = 0x54
DIALOGUE_REGION_TOKENS = 34
DIALOGUE_GLYPH_SLOTS = (
    0x008C,
    0x004B,
    0x0088,
    0x0054,
    0x0058,
    0x0082,
    0x006B,
    0x0052,
    0x0064,
    0x03B7,
    0x0090,
    0x0072,
    0x00B5,
    0x0009,
    0x00D3,
    0x00AD,
    0x00A8,
    0x009A,
)
ORIGINAL_PUNCTUATION = {
    "（": 0x000C,
    "）": 0x000D,
    "「": 0x000E,
    "」": 0x000F,
    "…": 0x000B,
}


def patch_poc_files(
    start_data: bytes,
    allbin_data: bytes,
    glyph_data: bytes,
    *,
    font_offset: int = FONT_OFFSET,
    glyph_index: int = POC_GLYPH_INDEX,
    token_offset: int = TEXT_TOKEN_OFFSET,
    expected_token: int = EXPECTED_ORIGINAL_TOKEN,
) -> tuple[bytes, bytes]:
    if len(glyph_data) != GLYPH_SIZE:
        raise ValueError(f"glyph must be exactly {GLYPH_SIZE} bytes")
    glyph_offset = font_offset + glyph_index * GLYPH_SIZE
    glyph_end = glyph_offset + GLYPH_SIZE
    if glyph_end > len(start_data):
        raise ValueError("target glyph is outside START.BIN")
    if any(start_data[glyph_offset:glyph_end]):
        raise ValueError("target glyph slot is not blank")
    if token_offset + 2 > len(allbin_data):
        raise ValueError("target token is outside ALLBIN.BIN")
    actual_token = struct.unpack_from("<H", allbin_data, token_offset)[0]
    if actual_token != expected_token:
        raise ValueError(
            f"unexpected source token 0x{actual_token:04X}; "
            f"expected 0x{expected_token:04X}"
        )

    patched_start = bytearray(start_data)
    patched_start[glyph_offset:glyph_end] = glyph_data
    patched_allbin = bytearray(allbin_data)
    struct.pack_into("<H", patched_allbin, token_offset, glyph_index)
    return bytes(patched_start), bytes(patched_allbin)


def patch_dialogue_poc_files(
    start_data: bytes,
    allbin_data: bytes,
    glyphs: dict[str, bytes],
    *,
    font_offset: int = FONT_OFFSET,
) -> tuple[bytes, bytes, dict[str, int]]:
    unique_characters = list(dict.fromkeys("".join(DIALOGUE_LINES)))
    hangul = [character for character in unique_characters if "가" <= character <= "힣"]
    if len(hangul) > len(DIALOGUE_GLYPH_SLOTS):
        raise ValueError("translated dialogue exceeds temporary glyph slots")
    if set(glyphs) != set(hangul):
        raise ValueError("glyph set does not match translated Hangul characters")
    mapping = dict(zip(hangul, DIALOGUE_GLYPH_SLOTS))
    mapping.update(ORIGINAL_PUNCTUATION)
    mapping[" "] = POC_GLYPH_INDEX

    patched_start = bytearray(start_data)
    for character in hangul:
        glyph_data = glyphs[character]
        if len(glyph_data) != GLYPH_SIZE:
            raise ValueError(f"glyph for {character!r} must be {GLYPH_SIZE} bytes")
        offset = font_offset + mapping[character] * GLYPH_SIZE
        patched_start[offset : offset + GLYPH_SIZE] = glyph_data

    first_line = [mapping[character] for character in DIALOGUE_LINES[0]]
    second_line = [mapping[character] for character in DIALOGUE_LINES[1]]
    if len(first_line) > 15 or len(second_line) != 15:
        raise ValueError("translated dialogue must fit the original 15-column layout")
    first_line.extend([mapping[" "]] * (15 - len(first_line)))
    tokens = [0x903F, *first_line, 0xFFFB, 0x0000, *second_line, 0x8000]
    if len(tokens) != DIALOGUE_REGION_TOKENS:
        raise ValueError("translated dialogue token region changed size")
    original_tokens = struct.unpack_from(
        f"<{DIALOGUE_REGION_TOKENS}H", allbin_data, DIALOGUE_REGION_OFFSET
    )
    expected_controls = {0: 0x903F, 16: 0xFFFB, 17: 0x0000, 33: 0x8000}
    if any(original_tokens[index] != value for index, value in expected_controls.items()):
        raise ValueError("source dialogue control layout differs from the verified sample")
    patched_allbin = bytearray(allbin_data)
    struct.pack_into(
        f"<{len(tokens)}H", patched_allbin, DIALOGUE_REGION_OFFSET, *tokens
    )
    return bytes(patched_start), bytes(patched_allbin), mapping


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def patch_raw_fragment(
    image: object,
    *,
    file_lba: int,
    file_offset: int,
    expected: bytes,
    replacement: bytes,
) -> set[int]:
    """Patch same-size bytes in MODE2/Form1 user data without rebuilding ECC."""
    if len(expected) != len(replacement):
        raise ValueError("raw replacement must preserve size")
    changed_sectors: set[int] = set()
    position = 0
    while position < len(replacement):
        logical_offset = file_offset + position
        sector = file_lba + logical_offset // USER_DATA_SIZE
        within = logical_offset % USER_DATA_SIZE
        size = min(len(replacement) - position, USER_DATA_SIZE - within)
        raw_sector = sector * RAW_SECTOR_SIZE
        image.seek(raw_sector)
        header = image.read(USER_DATA_OFFSET)
        if len(header) != USER_DATA_OFFSET or header[15] != 2:
            raise ValueError(f"LBA {sector} is not a MODE2 sector")
        if header[18] & 0x20:
            raise ValueError(f"LBA {sector} is MODE2/Form2, not Form1")
        raw_offset = raw_sector + USER_DATA_OFFSET + within
        image.seek(raw_offset)
        actual = image.read(size)
        expected_part = expected[position : position + size]
        if actual != expected_part:
            raise ValueError(f"source bytes differ at raw offset 0x{raw_offset:X}")
        replacement_part = replacement[position : position + size]
        if actual != replacement_part:
            image.seek(raw_offset)
            image.write(replacement_part)
            changed_sectors.add(sector)
        position += size
    return changed_sectors


def write_poc_cue(source_cue: Path, track_output: Path, cue_output: Path) -> None:
    lines = source_cue.read_text(encoding="ascii").splitlines()
    file_number = 0
    rewritten: list[str] = []
    pattern = re.compile(r'^(\s*FILE\s+)"([^"]+)"(\s+BINARY\s*)$', re.IGNORECASE)
    for line in lines:
        match = pattern.match(line)
        if not match:
            rewritten.append(line)
            continue
        file_number += 1
        if file_number == 1:
            path = track_output.resolve()
        else:
            path = (source_cue.parent / match.group(2)).resolve()
            local_audio = cue_output.parent / path.name
            if path != local_audio.resolve():
                shutil.copyfile(path, local_audio)
            path = local_audio.resolve()
        rewritten.append(f'{match.group(1)}"{path.name}"{match.group(3)}')
    if file_number == 0:
        raise ValueError("source CUE has no FILE entries")
    cue_output.parent.mkdir(parents=True, exist_ok=True)
    cue_output.write_text("\n".join(rewritten) + "\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-bin", type=Path, required=True)
    parser.add_argument("--allbin", type=Path, required=True)
    parser.add_argument("--font-profile", type=Path, default=DEFAULT_FONT_PROFILE)
    parser.add_argument("--character", default="한")
    parser.add_argument("--full-dialogue", action="store_true")
    parser.add_argument("--intensity", type=int)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--track1", type=Path)
    parser.add_argument("--track-output", type=Path)
    parser.add_argument("--source-cue", type=Path)
    parser.add_argument("--cue-output", type=Path)
    parser.add_argument("--allow-invalid-edc", action="store_true")
    args = parser.parse_args()

    if len(args.character) != 1:
        parser.error("--character must contain exactly one code point")
    if args.intensity is not None and not 1 <= args.intensity <= 7:
        parser.error("--intensity must be between 1 and 7")

    profile = load_font_profile(args.font_profile)
    intensity = profile.intensity if args.intensity is None else args.intensity
    original_start = args.start_bin.read_bytes()
    original_allbin = args.allbin.read_bytes()
    if sha256(original_start) != EXPECTED_SOURCE_START_SHA256:
        raise ValueError("source START.BIN hash differs from the verified Disc 1 file")
    if sha256(original_allbin) != EXPECTED_SOURCE_ALLBIN_SHA256:
        raise ValueError("source ALLBIN.BIN hash differs from the verified Disc 1 file")
    if args.full_dialogue:
        hangul = list(
            dict.fromkeys(
                character
                for character in "".join(DIALOGUE_LINES)
                if "가" <= character <= "힣"
            )
        )
        glyphs = pack_profile_glyphs(profile, hangul, intensity=intensity)
        patched_start, patched_allbin, mapping = patch_dialogue_poc_files(
            original_start, original_allbin, glyphs
        )
        print(f"dialogue={DIALOGUE_LINES[0]} / {DIALOGUE_LINES[1]}")
        print(
            "mapping="
            + ",".join(f"{character}=0x{mapping[character]:03X}" for character in hangul)
        )
    else:
        glyph_data = pack_profile_glyphs(
            profile, [args.character], intensity=intensity
        )[args.character]
        patched_start, patched_allbin = patch_poc_files(
            original_start, original_allbin, glyph_data
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    start_output = args.output_dir / "START.BIN"
    allbin_output = args.output_dir / "ALLBIN.BIN"
    start_output.write_bytes(patched_start)
    allbin_output.write_bytes(patched_allbin)
    if not args.full_dialogue:
        print(
            f"character=U+{ord(args.character):04X} glyph=0x{POC_GLYPH_INDEX:03X} "
            f"font_offset=0x{FONT_OFFSET + POC_GLYPH_INDEX * GLYPH_SIZE:X} "
            f"token_offset=0x{TEXT_TOKEN_OFFSET:X}"
        )
    print(
        f"START.BIN size={len(patched_start)} sha256={sha256(patched_start)} "
        f"output={start_output}"
    )
    print(
        f"ALLBIN.BIN size={len(patched_allbin)} sha256={sha256(patched_allbin)} "
        f"output={allbin_output}"
    )
    manifest = {
        "schema_version": 1,
        "build_id": "galmuri11-dialogue-poc",
        "font_profile": {
            "profile_id": profile.profile_id,
            "path": str(profile.profile_path),
            "source": str(profile.source_path),
            "source_sha256": profile.source_sha256,
            "family": profile.family,
            "style": profile.style,
            "version": profile.version,
            "ttf_size_px": profile.ttf_size_px,
            "x_offset_px": profile.x_offset_px,
            "y_offset_px": profile.y_offset_px,
            "intensity": intensity,
            "ink_union": profile.ink_union,
        },
        "source": {
            "START.BIN": {
                "path": str(args.start_bin.resolve()),
                "sha256": sha256(original_start),
            },
            "ALLBIN.BIN": {
                "path": str(args.allbin.resolve()),
                "sha256": sha256(original_allbin),
            },
        },
        "dialogue": list(DIALOGUE_LINES) if args.full_dialogue else None,
        "mapping": (
            {character: f"0x{index:03X}" for character, index in mapping.items()}
            if args.full_dialogue
            else {args.character: f"0x{POC_GLYPH_INDEX:03X}"}
        ),
        "outputs": {
            "START.BIN": {
                "path": str(start_output.resolve()),
                "sha256": sha256(patched_start),
            },
            "ALLBIN.BIN": {
                "path": str(allbin_output.resolve()),
                "sha256": sha256(patched_allbin),
            },
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"font_profile={profile.profile_id} ttf_size={profile.ttf_size_px} "
        f"offset=({profile.x_offset_px},{profile.y_offset_px}) "
        f"intensity={intensity} manifest={manifest_path}"
    )

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
                file_lba=START_LBA,
                file_offset=0,
                expected=original_start,
                replacement=patched_start,
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
