#!/usr/bin/env python3
"""Build same-size START/ALLBIN files for the first visible Hangul PoC."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import struct

try:
    from scripts.korean_font import crop_to_psx, rasterize_ttf_glyph
    from scripts.psx_font import GLYPH_SIZE, pack_glyph
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from korean_font import crop_to_psx, rasterize_ttf_glyph
    from psx_font import GLYPH_SIZE, pack_glyph


FONT_OFFSET = 0x1A000
POC_GLYPH_INDEX = 0x4CD
TEXT_TOKEN_OFFSET = 0x6E
EXPECTED_ORIGINAL_TOKEN = 0x03B7
START_LBA = 225
ALLBIN_LBA = 9919
RAW_SECTOR_SIZE = 2352
USER_DATA_OFFSET = 24
USER_DATA_SIZE = 2048


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
        rewritten.append(f'{match.group(1)}"{path.as_posix()}"{match.group(3)}')
    if file_number == 0:
        raise ValueError("source CUE has no FILE entries")
    cue_output.parent.mkdir(parents=True, exist_ok=True)
    cue_output.write_text("\n".join(rewritten) + "\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-bin", type=Path, required=True)
    parser.add_argument("--allbin", type=Path, required=True)
    parser.add_argument("--ttf", type=Path, required=True)
    parser.add_argument("--character", default="한")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--track1", type=Path)
    parser.add_argument("--track-output", type=Path)
    parser.add_argument("--source-cue", type=Path)
    parser.add_argument("--cue-output", type=Path)
    parser.add_argument("--allow-invalid-edc", action="store_true")
    args = parser.parse_args()

    if len(args.character) != 1:
        parser.error("--character must contain exactly one code point")

    from PIL import ImageFont

    font = ImageFont.truetype(str(args.ttf), 15)
    pixels = rasterize_ttf_glyph(font, args.character)
    glyph_data = pack_glyph(crop_to_psx(pixels))
    original_start = args.start_bin.read_bytes()
    original_allbin = args.allbin.read_bytes()
    patched_start, patched_allbin = patch_poc_files(
        original_start, original_allbin, glyph_data
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    start_output = args.output_dir / "START.BIN"
    allbin_output = args.output_dir / "ALLBIN.BIN"
    start_output.write_bytes(patched_start)
    allbin_output.write_bytes(patched_allbin)
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
        glyph_offset = FONT_OFFSET + POC_GLYPH_INDEX * GLYPH_SIZE
        with args.track_output.open("r+b") as image:
            changed |= patch_raw_fragment(
                image,
                file_lba=START_LBA,
                file_offset=glyph_offset,
                expected=original_start[glyph_offset : glyph_offset + GLYPH_SIZE],
                replacement=patched_start[glyph_offset : glyph_offset + GLYPH_SIZE],
            )
            changed |= patch_raw_fragment(
                image,
                file_lba=ALLBIN_LBA,
                file_offset=TEXT_TOKEN_OFFSET,
                expected=original_allbin[TEXT_TOKEN_OFFSET : TEXT_TOKEN_OFFSET + 2],
                replacement=patched_allbin[TEXT_TOKEN_OFFSET : TEXT_TOKEN_OFFSET + 2],
            )
        write_poc_cue(args.source_cue, args.track_output, args.cue_output)
        print(
            f"track1={args.track_output} changed_lba="
            f"{','.join(str(value) for value in sorted(changed))} "
            f"edc_ecc=invalid-emulator-only cue={args.cue_output}"
        )


if __name__ == "__main__":
    main()
