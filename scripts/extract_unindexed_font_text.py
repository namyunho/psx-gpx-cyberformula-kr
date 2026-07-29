#!/usr/bin/env python3
"""Extract the manually reviewed font streams missed by pointer-only surveys.

The original dialogue inventory proves streams reached through direct absolute
pointers.  The renderer also keeps consuming ``base + cursor * 2`` after a
page boundary, and several overlays select strings through indexed tables.
Those consumers leave valid text streams in the physical gaps between the
already catalogued entries.

This script performs a discovery scan only inside those gaps, then requires the
result to match the reviewed false-positive catalogue and per-unit population
below.  New heuristic hits are never accepted silently.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Iterable

try:
    from scripts.build_dialogue_chapter_patch import EXPECTED_ALLBIN_SHA256
    from scripts.psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import EXPECTED_ALLBIN_SHA256
    from psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule


BASELINE_ID = f"disc1-allbin-{EXPECTED_ALLBIN_SHA256[:16]}"

DEFAULT_KNOWN_WORKSETS = (
    Path("work/translations/disc1-dialogue.json"),
    Path("work/translations/disc1-pointerless-pages-u00-u21.json"),
    Path("work/translations/disc1-special-screen-text.json"),
    Path("work/translations/disc1-ui.json"),
)

# Every entry is a human-reviewed false positive produced by the discovery
# grammar.  Most are executable words, pointer/index tables, or packed
# animation data that happen to decode as primary-font glyph indices.
FALSE_POSITIVE_STARTS_BY_UNIT: dict[int, frozenset[int]] = {
    0: frozenset({0x02808}),
    1: frozenset({0x016FC}),
    2: frozenset({0x04554}),
    3: frozenset({0x01504}),
    5: frozenset({0x04128}),
    7: frozenset({0x0317A}),
    9: frozenset({0x06CC0}),
    14: frozenset({0x07CEC}),
    15: frozenset({0x01FC0}),
    16: frozenset({0x041EC}),
    17: frozenset({0x03510}),
    18: frozenset({0x03AAA}),
    19: frozenset({0x00FD4}),
    20: frozenset({0x03F10}),
    21: frozenset({0x015E8}),
    22: frozenset({0x055D2, 0x05D16, 0x05FCE}),
    23: frozenset(
        {
            0x027C4,
            0x04108,
            0x043F0,
            0x0440C,
            0x04428,
            0x046B4,
            0x046D0,
            0x046EC,
        }
    ),
    24: frozenset({0x03C78, 0x046C2}),
    28: frozenset({0x030BA, 0x03ABE, 0x03CC6}),
    29: frozenset({0x03F5A, 0x040AE, 0x0422E, 0x043AE}),
    30: frozenset({0x08264, 0x087CE}),
    31: frozenset({0x08264, 0x087CE}),
    32: frozenset({0x08264, 0x087CE}),
    33: frozenset({0x08264, 0x087CE}),
    34: frozenset({0x08264, 0x087CE, 0x0993C}),
    35: frozenset(
        {
            0x14FDE,
            0x17E5A,
            0x1C9B8,
            0x1EE4A,
            0x1EE8C,
            0x1EEE6,
            0x1EF32,
            0x1EF7A,
            0x1EFC0,
            0x1F068,
        }
    ),
    38: frozenset({0x15004, 0x16D28, 0x17D08, 0x1DA02}),
}

# The first valid run in these two race overlays begins with table data.  The
# actual stream begins at the speaker token shared by the other race units.
REVIEWED_START_TRIMS = {
    (33, 0x04204): 0x04230,
    (34, 0x04204): 0x04230,
}

EXPECTED_DISCOVERY_CANDIDATE_COUNT = 776
EXPECTED_FALSE_POSITIVE_COUNT = 60
EXPECTED_ENTRY_COUNTS_BY_UNIT = {
    2: 1,
    3: 6,
    4: 9,
    5: 5,
    6: 11,
    7: 4,
    8: 2,
    9: 13,
    10: 89,
    11: 14,
    12: 1,
    13: 15,
    14: 29,
    15: 1,
    16: 32,
    17: 41,
    18: 11,
    19: 7,
    30: 55,
    31: 57,
    32: 56,
    33: 105,
    34: 52,
    38: 73,
    39: 27,
}
EXPECTED_ENTRY_COUNT = sum(EXPECTED_ENTRY_COUNTS_BY_UNIT.values())

JAPANESE_TEXT_RE = re.compile(r"[ぁ-ゖァ-ヺ一-龯々〆ヵヶ]")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def control_kind(token: int) -> str | None:
    if token < 0x4000:
        return None
    if token == 0x4000:
        return "name_surname"
    if token == 0x6000:
        return "name_given"
    if token == 0x8000:
        return "page_end"
    if 0x9000 <= token <= 0x9FFF:
        return "speaker_style"
    if 0xD000 <= token <= 0xDFFF:
        return "voice_transition"
    if 0xE000 <= token <= 0xEFFF:
        return "audio"
    return {
        0xFFFB: "align",
        0xFFFC: "pause",
        0xFFFD: "pace",
        0xFFFF: "stream_end",
    }.get(token, "unknown")


def token_is_supported(token: int, glyphs: dict[int, str]) -> bool:
    kind = control_kind(token)
    return token in glyphs if kind is None else kind != "unknown"


def decode_visible_text(tokens: Iterable[int], glyphs: dict[int, str]) -> str:
    output: list[str] = []
    for token in tokens:
        kind = control_kind(token)
        if kind is None:
            output.append(glyphs[token])
        elif kind == "align":
            output.append("\n")
        elif kind == "name_surname":
            output.append("{name:surname}")
        elif kind == "name_given":
            output.append("{name:given}")
    return "".join(output)


def terminal_tokens_for_unit(unit_index: int) -> frozenset[int]:
    if 0 <= unit_index <= 20 or unit_index == 38:
        return frozenset({0x8000})
    if 21 <= unit_index <= 34:
        return frozenset({0xFFFF, 0xD003})
    return frozenset({0x8000, 0xFFFF})


def merge_intervals(
    intervals: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if start < 0 or end <= start:
            raise ValueError(f"invalid known interval 0x{start:X}:0x{end:X}")
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def complement_intervals(
    intervals: Iterable[tuple[int, int]],
    *,
    end: int,
) -> list[tuple[int, int]]:
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start, interval_end in merge_intervals(intervals):
        if interval_end > end:
            raise ValueError("known interval ends outside its ALLBIN unit")
        if cursor < start:
            gaps.append((cursor, start))
        cursor = max(cursor, interval_end)
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def discover_gap_candidates(
    unit: bytes,
    *,
    unit_index: int,
    known_intervals: Iterable[tuple[int, int]],
    glyphs: dict[int, str],
) -> list[dict[str, Any]]:
    terminals = terminal_tokens_for_unit(unit_index)
    candidates: list[dict[str, Any]] = []
    for gap_start, gap_end in complement_intervals(
        known_intervals,
        end=len(unit),
    ):
        position = gap_start + (gap_start & 1)
        while position + 2 <= gap_end:
            token = struct.unpack_from("<H", unit, position)[0]
            if not token_is_supported(token, glyphs):
                position += 2
                continue

            stream_start = position
            tokens: list[int] = []
            while position + 2 <= gap_end:
                token = struct.unpack_from("<H", unit, position)[0]
                if not token_is_supported(token, glyphs):
                    break
                tokens.append(token)
                position += 2
                if token in terminals:
                    visible = decode_visible_text(tokens, glyphs)
                    if (
                        len(JAPANESE_TEXT_RE.findall(visible)) >= 2
                        and len(tokens) >= 3
                    ):
                        candidates.append(
                            {
                                "start": stream_start,
                                "end": position,
                                "tokens": tokens,
                                "display_text": visible,
                            }
                        )
                    stream_start = position
                    tokens = []
            if position == stream_start:
                position += 2
    return candidates


def known_intervals_by_unit(
    paths: Iterable[Path],
) -> dict[int, list[tuple[int, int]]]:
    result: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for path in paths:
        document = load_object(path)
        entries = document.get("entries")
        if not isinstance(entries, list):
            raise ValueError(f"{path}: entries must be an array")
        for entry in entries:
            source = entry.get("source")
            if not isinstance(source, dict):
                raise ValueError(f"{path}: entry source is missing")
            unit_index = int(source["unit_index"])
            start = int(source["unit_offset"], 16)
            end = start + int(source["byte_size"])
            result[unit_index].append((start, end))
    return result


def classification_for_unit(unit_index: int) -> str:
    if 0 <= unit_index <= 20:
        return "sequential_event_page"
    if 30 <= unit_index <= 34:
        return "indexed_race_page"
    if unit_index == 38:
        return "indexed_minigame_page"
    if unit_index == 39:
        return "save_ui_stream"
    raise ValueError(f"unit {unit_index} has no reviewed classification")


def consumer_evidence_for_unit(unit_index: int) -> str:
    if 0 <= unit_index <= 20:
        return (
            "IDA/Ghidra: main renderer reads *(u16 *)(base + cursor * 2); "
            "0x8000 pauses without resetting the advanced cursor"
        )
    if 30 <= unit_index <= 34:
        return (
            "reviewed race-overlay string pool selected by indexed/branch "
            "routing; terminal-valid grammar mirrors directly referenced "
            "entries in the same five overlays"
        )
    if unit_index == 38:
        return (
            "reviewed mini-game branch/result pool adjacent to the proved u38 "
            "font consumers; indexed runtime route still needs path QA"
        )
    return (
        "contiguous FFFD..FFFF save-system message table containing the "
        "runtime-observed save-complete message"
    )


def layout_for_entry(unit_index: int, display_text: str) -> dict[str, int]:
    if unit_index == 38:
        rows = max(1, min(4, display_text.count("\n") + 1))
    elif unit_index == 39:
        rows = max(1, display_text.count("\n") + 1)
    else:
        rows = 3
    return {
        "columns": 17,
        "rows": rows,
        "capacity_positions": 17 * rows,
    }


def build_workset(
    *,
    exe_path: Path,
    allbin_path: Path,
    glyph_map_path: Path,
    known_workset_paths: Iterable[Path],
) -> dict[str, Any]:
    allbin = allbin_path.read_bytes()
    if sha256_bytes(allbin) != EXPECTED_ALLBIN_SHA256:
        raise ValueError("ALLBIN.BIN hash differs from the verified original")

    glyph_map = load_object(glyph_map_path)
    glyph_strings = (
        glyph_map.get("tables", {}).get("primary", {}).get("glyphs")
    )
    if not isinstance(glyph_strings, dict):
        raise ValueError("primary glyph map is missing")
    glyphs = {int(key, 16): value for key, value in glyph_strings.items()}

    exe = PsxExe(exe_path.read_bytes())
    spec = next(
        spec for spec in SCHEDULE_SPECS if spec.filename == "ALLBIN.BIN"
    )
    schedule = discover_schedule(
        exe,
        spec.table_va,
        spec.table_limit_va,
        len(allbin),
    )
    intervals_by_unit = known_intervals_by_unit(known_workset_paths)

    discovery_count = 0
    false_positive_count = 0
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for span in schedule:
        unit_index = int(span["index"])
        unit_file_offset = int(span["byte_offset"])
        unit = allbin[unit_file_offset : int(span["byte_end"])]
        for candidate in discover_gap_candidates(
            unit,
            unit_index=unit_index,
            known_intervals=intervals_by_unit.get(unit_index, ()),
            glyphs=glyphs,
        ):
            discovery_count += 1
            discovered_start = int(candidate["start"])
            if discovered_start in FALSE_POSITIVE_STARTS_BY_UNIT.get(
                unit_index,
                frozenset(),
            ):
                false_positive_count += 1
                rejected.append(
                    {
                        "unit_index": unit_index,
                        "unit_offset": f"0x{discovered_start:05X}",
                        "reason": "reviewed-binary-data-false-positive",
                    }
                )
                continue

            reviewed_start = REVIEWED_START_TRIMS.get(
                (unit_index, discovered_start),
                discovered_start,
            )
            if reviewed_start != discovered_start:
                trim_tokens = (reviewed_start - discovered_start) // 2
                candidate["tokens"] = candidate["tokens"][trim_tokens:]
                candidate["display_text"] = decode_visible_text(
                    candidate["tokens"],
                    glyphs,
                )
                candidate["start"] = reviewed_start

            start = int(candidate["start"])
            end = int(candidate["end"])
            tokens = list(candidate["tokens"])
            raw = unit[start:end]
            controls = []
            for token_index, token in enumerate(tokens):
                kind = control_kind(token)
                if kind is not None:
                    controls.append(
                        {
                            "token_index": token_index,
                            "raw": f"{token:04X}",
                            "kind": kind,
                        }
                    )
            entry_id = (
                f"disc1/allbin/u{unit_index:02d}/"
                f"unindexed_font/p{start:05X}"
            )
            entries.append(
                {
                    "entry_id": entry_id,
                    "classification": classification_for_unit(unit_index),
                    "reachability": "static-consumer-class-runtime-path-review",
                    "source": {
                        "container": "ALLBIN.BIN",
                        "unit_index": unit_index,
                        "file_offset": f"0x{unit_file_offset + start:06X}",
                        "unit_offset": f"0x{start:05X}",
                        "byte_size": len(raw),
                        "sha256": sha256_bytes(raw),
                        "terminal": f"{tokens[-1]:04X}",
                    },
                    "consumer": {
                        "evidence": consumer_evidence_for_unit(unit_index),
                        "runtime_path_review_required": unit_index
                        not in range(0, 21),
                    },
                    "original": {
                        "raw_hex": raw.hex().upper(),
                        "tokens": [f"{token:04X}" for token in tokens],
                        "control_tokens": controls,
                        "display_text": candidate["display_text"],
                    },
                    "layout": layout_for_entry(
                        unit_index,
                        candidate["display_text"],
                    ),
                }
            )

    if discovery_count != EXPECTED_DISCOVERY_CANDIDATE_COUNT:
        raise ValueError(
            "unindexed discovery population changed: "
            f"{discovery_count} != {EXPECTED_DISCOVERY_CANDIDATE_COUNT}"
        )
    if false_positive_count != EXPECTED_FALSE_POSITIVE_COUNT:
        raise ValueError(
            "reviewed false-positive population changed: "
            f"{false_positive_count} != {EXPECTED_FALSE_POSITIVE_COUNT}"
        )
    if len(entries) != EXPECTED_ENTRY_COUNT:
        raise ValueError(
            f"reviewed entry population changed: "
            f"{len(entries)} != {EXPECTED_ENTRY_COUNT}"
        )
    counts_by_unit = Counter(
        int(entry["source"]["unit_index"]) for entry in entries
    )
    if dict(sorted(counts_by_unit.items())) != EXPECTED_ENTRY_COUNTS_BY_UNIT:
        raise ValueError(
            "reviewed per-unit population changed: "
            f"{dict(sorted(counts_by_unit.items()))!r}"
        )

    known_paths = list(known_workset_paths)
    return {
        "schema_version": 1,
        "status": "reviewed-unindexed-font-workset-runtime-path-qa-required",
        "baseline_id": BASELINE_ID,
        "scope": {
            "source_allbin": str(allbin_path.resolve()),
            "source_allbin_sha256": EXPECTED_ALLBIN_SHA256,
            "source_exe": str(exe_path.resolve()),
            "glyph_map": str(glyph_map_path.resolve()),
            "known_worksets": [str(path.resolve()) for path in known_paths],
            "included": [
                "sequential event pages in u02..u19",
                "indexed or branch-selected race pages in u30..u34",
                "additional mini-game branch/result pages in u38",
                "save-system messages in u39",
            ],
            "excluded": [
                "streams already present in the four known worksets",
                "60 reviewed binary-data false positives",
                "baked graphical text",
            ],
        },
        "method": {
            "discovery": (
                "scan terminal-valid primary-font token runs only in physical "
                "gaps outside existing worksets"
            ),
            "adoption": (
                "fixed reviewed false-positive catalogue, two reviewed start "
                "trims, exact total and per-unit population assertions"
            ),
            "completion_boundary": (
                "translation coverage for this reviewed workset does not by "
                "itself prove every indexed runtime route"
            ),
        },
        "summary": {
            "discovery_candidate_count": discovery_count,
            "reviewed_false_positive_count": false_positive_count,
            "entry_count": len(entries),
            "entry_counts_by_unit": {
                f"u{unit_index:02d}": count
                for unit_index, count in sorted(counts_by_unit.items())
            },
            "classification_counts": dict(
                sorted(Counter(e["classification"] for e in entries).items())
            ),
        },
        "reviewed_false_positives": rejected,
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--disc-root",
        type=Path,
        default=Path("work/disc1/full"),
    )
    parser.add_argument(
        "--glyph-map",
        type=Path,
        default=Path("data/glyph-map.json"),
    )
    parser.add_argument(
        "--known-workset",
        type=Path,
        action="append",
        dest="known_worksets",
        help="repeat to replace the four default known worksets",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "work/translations/disc1-unindexed-font-text.json"
        ),
    )
    args = parser.parse_args()
    known_worksets = (
        tuple(args.known_worksets)
        if args.known_worksets
        else DEFAULT_KNOWN_WORKSETS
    )
    document = build_workset(
        exe_path=args.disc_root / "SLPS_019.58",
        allbin_path=args.disc_root / "ALLBIN.BIN",
        glyph_map_path=args.glyph_map,
        known_workset_paths=known_worksets,
    )
    write_json(args.output, document)
    print(
        f"entries={document['summary']['entry_count']} "
        f"false_positives="
        f"{document['summary']['reviewed_false_positive_count']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
