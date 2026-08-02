#!/usr/bin/env python3
"""Audit fixed and branched ALLBIN font commands outside known worksets.

This is deliberately narrower than a raw glyph scan.  It enumerates the
control words used by the proved selection consumers, subtracts every stable
workset interval, and reviews only ``FFFD`` records followed by a plausible
primary-font run.  A matching glyph run is still not consumer proof: the
small reviewed false-positive catalogue below records code/table bytes that
happen to decode as Japanese.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct
from typing import Any, Iterable

try:
    from scripts.build_dialogue_chapter_patch import EXPECTED_ALLBIN_SHA256
    from scripts.extract_unindexed_font_text import (
        known_intervals_by_unit,
        load_object,
        sha256_bytes,
        write_json,
    )
    from scripts.psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import EXPECTED_ALLBIN_SHA256
    from extract_unindexed_font_text import (
        known_intervals_by_unit,
        load_object,
        sha256_bytes,
        write_json,
    )
    from psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule


DEFAULT_KNOWN_WORKSETS = (
    Path("work/translations/disc1-dialogue.json"),
    Path("work/translations/disc1-pointerless-pages-u00-u21.json"),
    Path("work/translations/disc1-special-screen-text.json"),
    Path("work/translations/disc1-unindexed-font-text.json"),
    Path("work/translations/disc1-ui.json"),
)

EXPECTED_CONTROL_COUNTS = {
    0xFFFD: {"total": 480, "covered": 371, "uncovered": 109},
    0xD002: {"total": 24, "covered": 24, "uncovered": 0},
    0xD003: {"total": 185, "covered": 185, "uncovered": 0},
}

# These are the only uncovered FFFD records followed by at least two valid
# primary-font glyphs.  Only u09 is a runtime-confirmed consumer.  The others
# sit in coordinate/animation/code tables and fail the surrounding stream
# grammar and consumer checks.
REVIEWED_CANDIDATES: dict[tuple[int, int], tuple[str, str]] = {
    (9, 0x5DEA): ("confirmed-fixed-command", "주크박스 취소 고정 슬롯"),
    (24, 0x299E): ("false-positive", "좌표/패딩 데이터"),
    (24, 0x29BE): ("false-positive", "좌표/패딩 데이터"),
    (24, 0x29DE): ("false-positive", "좌표/패딩 데이터"),
    (26, 0x1C6A): ("false-positive", "좌표/패딩 데이터"),
    (38, 0x1EB12): ("false-positive", "미니게임 애니메이션 데이터"),
    (38, 0x1EB76): ("false-positive", "미니게임 애니메이션 데이터"),
    (38, 0x1EB8A): ("false-positive", "미니게임 애니메이션 데이터"),
    (38, 0x1EC3E): ("false-positive", "미니게임 애니메이션 데이터"),
    (39, 0x49DC): ("false-positive", "MIPS 명령/인접 테이블 데이터"),
}

EXPECTED_INLINE_COMMAND_ID = "disc1/allbin/u09/inline_menu/cancel"
EXPECTED_INLINE_SOURCE = "キャンセル"
EXPECTED_INLINE_TRANSLATION = "취소"
EXPECTED_INLINE_FILE_OFFSET = 0x305F0


def load_primary_glyphs(path: Path) -> dict[int, str]:
    document = load_object(path)
    raw = document.get("tables", {}).get("primary", {}).get("glyphs")
    if not isinstance(raw, dict):
        raise ValueError("primary glyph map is missing")
    return {int(key, 16): str(value) for key, value in raw.items()}


def interval_contains(
    intervals: Iterable[tuple[int, int]],
    offset: int,
) -> bool:
    return any(start <= offset < end for start, end in intervals)


def validate_inline_translation(path: Path) -> dict[str, Any]:
    document = load_object(path)
    translations = document.get("translations")
    if not isinstance(translations, list) or len(translations) != 1:
        raise ValueError("inline command translation population differs")
    entry = translations[0]
    expected = {
        "id": EXPECTED_INLINE_COMMAND_ID,
        "jp": EXPECTED_INLINE_SOURCE,
        "ko": EXPECTED_INLINE_TRANSLATION,
    }
    for key, value in expected.items():
        if entry.get(key) != value:
            raise ValueError(f"inline command {key} differs")
    if int(entry.get("visible_glyph_capacity", -1)) != 5:
        raise ValueError("inline command fixed capacity differs")
    return entry


def audit_branch_commands(
    *,
    exe_path: Path,
    allbin_path: Path,
    glyph_map_path: Path,
    known_workset_paths: Iterable[Path],
    inline_translation_path: Path,
) -> dict[str, Any]:
    allbin = allbin_path.read_bytes()
    if sha256_bytes(allbin) != EXPECTED_ALLBIN_SHA256:
        raise ValueError("ALLBIN.BIN hash differs from the verified original")
    glyphs = load_primary_glyphs(glyph_map_path)
    inline_translation = validate_inline_translation(inline_translation_path)

    exe = PsxExe(exe_path.read_bytes())
    spec = next(item for item in SCHEDULE_SPECS if item.filename == "ALLBIN.BIN")
    schedule = discover_schedule(
        exe,
        spec.table_va,
        spec.table_limit_va,
        len(allbin),
    )
    intervals_by_unit = known_intervals_by_unit(known_workset_paths)

    control_counts: dict[int, Counter[str]] = {
        token: Counter() for token in EXPECTED_CONTROL_COUNTS
    }
    candidates: list[dict[str, Any]] = []
    literal_hits: list[dict[str, Any]] = []

    encoded_cancel = struct.pack(
        "<5H",
        *(next(index for index, glyph in glyphs.items() if glyph == char)
          for char in EXPECTED_INLINE_SOURCE),
    )

    for span in schedule:
        unit_index = int(span["index"])
        unit_file_offset = int(span["byte_offset"])
        unit = allbin[unit_file_offset : int(span["byte_end"])]
        intervals = intervals_by_unit.get(unit_index, ())

        for offset in range(0, len(unit) - 1, 2):
            token = struct.unpack_from("<H", unit, offset)[0]
            if token not in control_counts:
                continue
            coverage = "covered" if interval_contains(intervals, offset) else "uncovered"
            control_counts[token]["total"] += 1
            control_counts[token][coverage] += 1

            if token != 0xFFFD or coverage != "uncovered":
                continue
            cursor = offset + 2
            visible: list[str] = []
            while cursor + 2 <= len(unit):
                glyph_token = struct.unpack_from("<H", unit, cursor)[0]
                glyph = glyphs.get(glyph_token)
                if glyph is None:
                    break
                visible.append(glyph)
                cursor += 2
            if len(visible) < 2:
                continue
            key = (unit_index, offset)
            if key not in REVIEWED_CANDIDATES:
                raise ValueError(
                    "new uncovered FFFD glyph candidate requires review: "
                    f"u{unit_index:02d}+0x{offset:X}"
                )
            classification, reason = REVIEWED_CANDIDATES[key]
            candidates.append(
                {
                    "unit_index": unit_index,
                    "unit_offset": f"0x{offset:X}",
                    "file_offset": f"0x{unit_file_offset + offset:X}",
                    "following_glyph_count": len(visible),
                    "following_display_text": "".join(visible),
                    "classification": classification,
                    "reason": reason,
                }
            )

        search_offset = 0
        while True:
            hit = unit.find(encoded_cancel, search_offset)
            if hit < 0:
                break
            literal_hits.append(
                {
                    "unit_index": unit_index,
                    "unit_offset": f"0x{hit:X}",
                    "file_offset": f"0x{unit_file_offset + hit:X}",
                    "known_workset": interval_contains(intervals, hit),
                }
            )
            search_offset = hit + 2

    if set((entry["unit_index"], int(entry["unit_offset"], 16)) for entry in candidates) != set(REVIEWED_CANDIDATES):
        raise ValueError("reviewed uncovered FFFD candidate population differs")

    rendered_counts: dict[str, dict[str, int]] = {}
    for token, expected in EXPECTED_CONTROL_COUNTS.items():
        actual = {
            "total": control_counts[token]["total"],
            "covered": control_counts[token]["covered"],
            "uncovered": control_counts[token]["uncovered"],
        }
        if actual != expected:
            raise ValueError(
                f"{token:04X} coverage changed: {actual!r} != {expected!r}"
            )
        rendered_counts[f"{token:04X}"] = actual

    if len(literal_hits) != 2:
        raise ValueError("キャンセル literal population differs")
    uncovered_cancel = [hit for hit in literal_hits if not hit["known_workset"]]
    if len(uncovered_cancel) != 1 or int(uncovered_cancel[0]["file_offset"], 16) != EXPECTED_INLINE_FILE_OFFSET:
        raise ValueError("uncovered キャンセル literal location differs")

    return {
        "schema_version": 1,
        "scope": "Disc 1 ALLBIN selection/branch font command controls",
        "status": "static-complete-runtime-spot-check-complete",
        "source": {
            "allbin": str(allbin_path),
            "sha256": sha256_bytes(allbin),
            "known_worksets": [str(path) for path in known_workset_paths],
        },
        "control_coverage": rendered_counts,
        "uncovered_fffd_glyph_candidates": candidates,
        "cancel_literal_hits": literal_hits,
        "confirmed_missing_commands": [
            {
                "id": inline_translation["id"],
                "unit_index": 9,
                "unit_offset": "0x5DF0",
                "file_offset": f"0x{EXPECTED_INLINE_FILE_OFFSET:X}",
                "jp": inline_translation["jp"],
                "ko": inline_translation["ko"],
                "slot_glyphs": inline_translation["visible_glyph_capacity"],
                "consumer_evidence": "PCSX-Redux RAM 0x800ADDF0 and static control shell",
            }
        ],
        "summary": {
            "confirmed_missing_command_count": 1,
            "confirmed_translated_command_count": 1,
            "new_unresolved_command_count": 0,
            "reviewed_false_positive_count": 9,
            "all_branch_terminals_covered": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=Path("work/disc1/SLPS_019.58"))
    parser.add_argument("--allbin", type=Path, default=Path("work/disc1/ALLBIN.BIN"))
    parser.add_argument("--glyph-map", type=Path, default=Path("data/glyph-map.json"))
    parser.add_argument(
        "--known-workset",
        type=Path,
        action="append",
        default=[],
        help="override the default stable worksets; repeat for each JSON",
    )
    parser.add_argument(
        "--inline-translation",
        type=Path,
        default=Path("data/translations/disc1-inline-menu-ko.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("work/analysis/disc1-branch-command-audit.json"),
    )
    args = parser.parse_args()
    known_worksets = tuple(args.known_workset) or DEFAULT_KNOWN_WORKSETS
    report = audit_branch_commands(
        exe_path=args.exe,
        allbin_path=args.allbin,
        glyph_map_path=args.glyph_map,
        known_workset_paths=known_worksets,
        inline_translation_path=args.inline_translation,
    )
    write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
