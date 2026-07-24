#!/usr/bin/env python3
"""Verify the Galmuri11 dialogue PoC from files through raw Track 1 writes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

try:
    from scripts.build_font_poc import (
        DIALOGUE_REGION_OFFSET,
        DIALOGUE_REGION_TOKENS,
        FONT_OFFSET,
    )
    from scripts.korean_font import load_font_profile, pack_profile_glyphs
    from scripts.psx_disc import RAW_SECTOR_SIZE, PsxDisc
    from scripts.psx_font import GLYPH_SIZE
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from build_font_poc import (
        DIALOGUE_REGION_OFFSET,
        DIALOGUE_REGION_TOKENS,
        FONT_OFFSET,
    )
    from korean_font import load_font_profile, pack_profile_glyphs
    from psx_disc import RAW_SECTOR_SIZE, PsxDisc
    from psx_font import GLYPH_SIZE


USER_DATA_OFFSET = 24
USER_DATA_SIZE = 2048


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def differing_offsets(original: bytes, patched: bytes) -> set[int]:
    if len(original) != len(patched):
        raise ValueError("same-size PoC files changed length")
    return {
        offset
        for offset, (before, after) in enumerate(zip(original, patched))
        if before != after
    }


def expected_raw_changes(
    lba: int,
    original: bytes,
    patched: bytes,
) -> dict[int, int]:
    changes: dict[int, int] = {}
    for offset in differing_offsets(original, patched):
        sector = lba + offset // USER_DATA_SIZE
        within = offset % USER_DATA_SIZE
        raw_offset = sector * RAW_SECTOR_SIZE + USER_DATA_OFFSET + within
        changes[raw_offset] = patched[offset]
    return changes


def actual_raw_changes(original_track: Path, patched_track: Path) -> dict[int, int]:
    if original_track.stat().st_size != patched_track.stat().st_size:
        raise ValueError("patched Track 1 size differs from the original")
    changes: dict[int, int] = {}
    with original_track.open("rb") as original, patched_track.open("rb") as patched:
        sector = 0
        while True:
            before = original.read(RAW_SECTOR_SIZE)
            after = patched.read(RAW_SECTOR_SIZE)
            if not before and not after:
                break
            if len(before) != RAW_SECTOR_SIZE or len(after) != RAW_SECTOR_SIZE:
                raise ValueError("Track 1 ends in a partial raw sector")
            if before != after:
                base = sector * RAW_SECTOR_SIZE
                for within, (left, right) in enumerate(zip(before, after)):
                    if left != right:
                        changes[base + within] = right
            sector += 1
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-profile", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-start", type=Path, required=True)
    parser.add_argument("--source-allbin", type=Path, required=True)
    parser.add_argument("--patched-start", type=Path, required=True)
    parser.add_argument("--patched-allbin", type=Path, required=True)
    parser.add_argument("--original-track", type=Path, required=True)
    parser.add_argument("--patched-track", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    profile = load_font_profile(args.font_profile)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["font_profile"]["profile_id"] != profile.profile_id:
        raise ValueError("manifest and font profile IDs differ")

    source_start = args.source_start.read_bytes()
    source_allbin = args.source_allbin.read_bytes()
    patched_start = args.patched_start.read_bytes()
    patched_allbin = args.patched_allbin.read_bytes()
    for name, data, declared in (
        ("START.BIN", patched_start, manifest["outputs"]["START.BIN"]["sha256"]),
        ("ALLBIN.BIN", patched_allbin, manifest["outputs"]["ALLBIN.BIN"]["sha256"]),
    ):
        if sha256_bytes(data) != declared:
            raise ValueError(f"{name} output hash differs from the manifest")

    hangul = [
        character
        for character in manifest["mapping"]
        if "가" <= character <= "힣"
    ]
    glyphs = pack_profile_glyphs(
        profile,
        hangul,
        intensity=int(manifest["font_profile"]["intensity"]),
    )
    allowed_start_changes: set[int] = set()
    for character, glyph in glyphs.items():
        slot = int(manifest["mapping"][character], 16)
        begin = FONT_OFFSET + slot * GLYPH_SIZE
        end = begin + GLYPH_SIZE
        if patched_start[begin:end] != glyph:
            raise ValueError(f"inserted glyph differs for {character!r}")
        allowed_start_changes.update(range(begin, end))
    start_changes = differing_offsets(source_start, patched_start)
    if not start_changes <= allowed_start_changes:
        raise ValueError("START.BIN changed outside the declared Hangul glyph slots")

    dialogue_begin = DIALOGUE_REGION_OFFSET
    dialogue_end = dialogue_begin + DIALOGUE_REGION_TOKENS * 2
    allbin_changes = differing_offsets(source_allbin, patched_allbin)
    if not all(dialogue_begin <= offset < dialogue_end for offset in allbin_changes):
        raise ValueError("ALLBIN.BIN changed outside the declared dialogue token region")
    tokens = struct.unpack_from(
        f"<{DIALOGUE_REGION_TOKENS}H",
        patched_allbin,
        DIALOGUE_REGION_OFFSET,
    )
    if (tokens[0], tokens[16], tokens[17], tokens[33]) != (
        0x903F,
        0xFFFB,
        0x0000,
        0x8000,
    ):
        raise ValueError("patched dialogue controls differ from the verified layout")

    with PsxDisc(args.original_track) as original_disc, PsxDisc(
        args.patched_track
    ) as patched_disc:
        original_entries = {
            entry.name: entry
            for entry in original_disc.root_entries()
            if not entry.is_directory
        }
        patched_entries = {
            entry.name: entry
            for entry in patched_disc.root_entries()
            if not entry.is_directory
        }
        if original_entries != patched_entries:
            raise ValueError("patched Track 1 ISO directory differs from the original")
        for name, expected in (
            ("START.BIN", patched_start),
            ("ALLBIN.BIN", patched_allbin),
        ):
            entry = patched_entries[name]
            if patched_disc.read_extent(entry.lba, entry.size) != expected:
                raise ValueError(f"patched Track 1 does not contain {name} output")

    expected_changes: dict[int, int] = {}
    for name, before, after in (
        ("START.BIN", source_start, patched_start),
        ("ALLBIN.BIN", source_allbin, patched_allbin),
    ):
        entry = original_entries[name]
        for offset, value in expected_raw_changes(entry.lba, before, after).items():
            if offset in expected_changes and expected_changes[offset] != value:
                raise ValueError("overlapping expected raw writes disagree")
            expected_changes[offset] = value
    actual_changes = actual_raw_changes(args.original_track, args.patched_track)
    if actual_changes != expected_changes:
        missing = len(set(expected_changes) - set(actual_changes))
        extra = len(set(actual_changes) - set(expected_changes))
        raise ValueError(
            f"raw Track 1 diff differs from expected writes: missing={missing} extra={extra}"
        )

    changed_lbas = sorted({offset // RAW_SECTOR_SIZE for offset in actual_changes})
    report = {
        "schema_version": 1,
        "status": "passed",
        "font_profile": profile.profile_id,
        "checks": {
            "hangul_glyph_count": len(glyphs),
            "start_changed_byte_count": len(start_changes),
            "allbin_changed_byte_count": len(allbin_changes),
            "raw_changed_byte_count": len(actual_changes),
            "changed_lbas": changed_lbas,
            "iso_directory_unchanged": True,
            "raw_diff_matches_declared_file_writes": True,
            "edc_ecc": "unchanged-and-invalid-for-modified-sectors",
        },
        "hashes": {
            "patched_track_sha256": sha256_file(args.patched_track),
            "START.BIN": sha256_bytes(patched_start),
            "ALLBIN.BIN": sha256_bytes(patched_allbin),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
