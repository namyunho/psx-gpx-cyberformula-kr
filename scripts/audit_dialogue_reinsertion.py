#!/usr/bin/env python3
"""Audit, reflow, and split Korean dialogue candidates for reinsertion.

This script deliberately does not rewrite the machine-translation candidate.
It produces a derived, non-release overlay whose lines are first wrapped at
Korean word boundaries.  If that would overflow the verified 17-column by
3-row renderer, a traceable fallback may split a word across rows.  Entries
that still cannot fit are retained as blockers.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from typing import Any


COLUMNS = 17
ROWS = 3
MAX_GLYPHS = COLUMNS * ROWS
NAME_WIDTHS = {
    "{name:surname}": 4,
    "{name:given}": 4,
}
NAME_PATTERN = re.compile(r"\{name:(?:surname|given)\}")
WORD_PATTERN = re.compile(r"\S+")
JAPANESE_SCRIPT = re.compile(r"[ぁ-んァ-ヶ一-龯]")
SOURCE_READING_SUSPECTS = {
    "ヶアスラーダ": "アスラーダ일 가능성 검토",
    "溌言": "発言일 가능성 검토",
    "皆暁いて": "皆驚いて일 가능성 검토",
    "推繊枠": "推薦枠일 가능성 검토",
}


@dataclass(frozen=True)
class WrapResult:
    status: str
    lines: tuple[str, ...]
    oversized_words: tuple[str, ...] = ()
    wrap_mode: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def visible_width(text: str) -> int:
    """Return renderer positions for plain text and fixed-name placeholders."""
    width = 0
    cursor = 0
    for match in NAME_PATTERN.finditer(text):
        width += len(text[cursor : match.start()])
        width += NAME_WIDTHS[match.group()]
        cursor = match.end()
    return width + len(text[cursor:])


def wrap_words(
    text: str,
    *,
    columns: int = COLUMNS,
    rows: int = ROWS,
) -> WrapResult:
    """Wrap at words first, then split words only to rescue a 17x3 fit."""
    words = WORD_PATTERN.findall(text)
    if not words:
        return WrapResult("empty", ())

    oversized = tuple(word for word in words if visible_width(word) > columns)
    lines: list[str] = []
    current = ""
    if not oversized:
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if visible_width(candidate) <= columns:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        if len(lines) <= rows:
            return WrapResult(
                "ready",
                tuple(lines),
                wrap_mode="word-boundary",
            )

    hard_lines = wrap_with_word_splitting(
        text,
        columns=columns,
        rows=rows,
    )
    if len(hard_lines) <= rows:
        return WrapResult(
            "ready",
            hard_lines,
            oversized_words=oversized,
            wrap_mode="word-split-fallback",
        )
    compact_lines = wrap_with_minimum_space_dropping(
        text,
        columns=columns,
        rows=rows,
    )
    if compact_lines is not None:
        return WrapResult(
            "ready",
            compact_lines,
            oversized_words=oversized,
            wrap_mode="space-drop-word-split-fallback",
        )
    if oversized:
        return WrapResult("word-overflow", hard_lines, oversized)
    return WrapResult("row-overflow", tuple(lines))


def wrap_with_word_splitting(
    text: str,
    *,
    columns: int = COLUMNS,
    rows: int = ROWS,
) -> tuple[str, ...]:
    """Find a <=rows hard wrap, or return a greedy diagnostic hard wrap."""
    normalized = " ".join(WORD_PATTERN.findall(text))
    if not normalized:
        return ()

    units: list[tuple[str, int]] = []
    cursor = 0
    for match in NAME_PATTERN.finditer(normalized):
        units.extend((character, 1) for character in normalized[cursor : match.start()])
        units.append((match.group(), NAME_WIDTHS[match.group()]))
        cursor = match.end()
    units.extend((character, 1) for character in normalized[cursor:])

    @lru_cache(maxsize=None)
    def fit(
        index: int,
        rows_left: int,
    ) -> tuple[int, int, tuple[int, ...], tuple[str, ...]] | None:
        while index < len(units) and units[index][0] == " ":
            index += 1
        if index == len(units):
            return (0, 0, (), ())
        if rows_left == 0:
            return None

        best: tuple[
            int,
            int,
            tuple[int, ...],
            tuple[str, ...],
        ] | None = None
        width = 0
        for end in range(index + 1, len(units) + 1):
            unit, unit_width = units[end - 1]
            if unit_width > columns:
                raise ValueError(
                    f"atomic display unit exceeds {columns}: {unit!r}"
                )
            width += unit_width
            if width > columns:
                break
            line = "".join(value for value, _ in units[index:end]).rstrip()
            if not line:
                continue
            line_width = visible_width(line)
            next_index = end
            while (
                next_index < len(units)
                and units[next_index][0] == " "
            ):
                next_index += 1
            tail = fit(next_index, rows_left - 1)
            if tail is None:
                continue
            split_word = (
                end < len(units)
                and next_index == end
                and units[end - 1][0] != " "
                and units[end][0] != " "
            )
            candidate = (
                tail[0] + int(split_word),
                tail[1] + 1,
                (line_width, *tail[2]),
                (line, *tail[3]),
            )
            candidate_key = (
                candidate[0],
                candidate[1],
                tuple(-value for value in candidate[2]),
            )
            best_key = (
                best[0],
                best[1],
                tuple(-value for value in best[2]),
            ) if best is not None else None
            if best_key is None or candidate_key < best_key:
                best = candidate
        return best

    fitted = fit(0, rows)
    if fitted is not None:
        return fitted[3]

    # No valid <=rows layout exists. Return a deterministic diagnostic layout
    # so the audit can show where the fixed-width renderer would overflow.
    lines: list[str] = []
    current: list[str] = []
    width = 0
    for unit, unit_width in units:
        if unit == " " and not current:
            continue
        if width + unit_width > columns:
            line = "".join(current).rstrip()
            if line:
                lines.append(line)
            current = []
            width = 0
            if unit == " ":
                continue
        if unit_width > columns:
            raise ValueError(f"atomic display unit exceeds {columns}: {unit!r}")
        current.append(unit)
        width += unit_width

    line = "".join(current).rstrip()
    if line:
        lines.append(line)
    return tuple(lines)


def wrap_with_minimum_space_dropping(
    text: str,
    *,
    columns: int = COLUMNS,
    rows: int = ROWS,
) -> tuple[str, ...] | None:
    """Fit without deleting non-space content, dropping as few spaces as possible."""
    normalized = " ".join(WORD_PATTERN.findall(text))
    if not normalized:
        return ()

    units: list[tuple[str, int, bool]] = []
    cursor = 0
    for match in NAME_PATTERN.finditer(normalized):
        units.extend(
            (character, 1, character == " ")
            for character in normalized[cursor : match.start()]
        )
        units.append((match.group(), NAME_WIDTHS[match.group()], False))
        cursor = match.end()
    units.extend(
        (character, 1, character == " ")
        for character in normalized[cursor:]
    )
    if sum(width for _, width, is_space in units if not is_space) > (
        columns * rows
    ):
        return None

    @lru_cache(maxsize=None)
    def fit(
        index: int,
        row_index: int,
        row_width: int,
    ) -> tuple[int, int, str] | None:
        if index == len(units):
            return (0, 0, "")

        candidates: list[tuple[int, int, str]] = []
        value, width, is_space = units[index]
        if is_space:
            tail = fit(index + 1, row_index, row_width)
            if tail is not None:
                candidates.append((tail[0] + 1, tail[1], tail[2]))
        if row_width + width <= columns and not (
            is_space and row_width == 0
        ):
            tail = fit(index + 1, row_index, row_width + width)
            if tail is not None:
                candidates.append((tail[0], tail[1], value + tail[2]))
        if row_width and row_index + 1 < rows:
            tail = fit(index, row_index + 1, 0)
            if tail is not None:
                split_word = (
                    index > 0
                    and not is_space
                    and not units[index - 1][2]
                )
                candidates.append(
                    (tail[0], tail[1] + int(split_word), "\n" + tail[2])
                )
        if not candidates:
            return None

        def candidate_key(candidate: tuple[int, int, str]) -> tuple[Any, ...]:
            lines = candidate[2].split("\n")
            widths = tuple(visible_width(line) for line in lines)
            return (
                candidate[0],
                candidate[1],
                len(lines),
                tuple(-width for width in widths),
                candidate[2],
            )

        return min(candidates, key=candidate_key)

    result = fit(0, 0, 0)
    if result is None or result[0] == 0:
        return None
    lines = tuple(result[2].split("\n"))
    if len(lines) > rows or any(visible_width(line) > columns for line in lines):
        raise AssertionError("minimum-space fallback produced an invalid layout")
    return lines


def minimum_required_glyph_count(
    text: str,
    *,
    rows: int = ROWS,
) -> int:
    """Return a lower bound after replacing up to rows-1 spaces with breaks."""
    normalized = " ".join(WORD_PATTERN.findall(text))
    return visible_width(normalized) - min(rows - 1, normalized.count(" "))


def normalized_for_compare(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def chapter_label(unit_index: int, classification: str) -> str:
    if unit_index <= 20:
        return f"story-u{unit_index:02d}"
    if unit_index == 21:
        return "test-drive-u21"
    if unit_index <= 29:
        return f"race-u{unit_index:02d}"
    return f"embedded-race-u{unit_index:02d}"


def build_outputs(
    workset_path: Path,
    candidate_path: Path,
    glossary_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[int, dict[str, Any]]]:
    workset = load_object(workset_path)
    candidate = load_object(candidate_path)
    glossary = load_object(glossary_path)

    work_entries = workset.get("entries")
    candidate_entries = candidate.get("entries")
    terms = glossary.get("terms")
    if not isinstance(work_entries, list) or not isinstance(candidate_entries, list):
        raise ValueError("workset and candidate entries must be arrays")
    if not isinstance(terms, list):
        raise ValueError("glossary terms must be an array")

    work_by_id = {entry["entry_id"]: entry for entry in work_entries}
    candidate_by_id = {entry["id"]: entry for entry in candidate_entries}
    if len(work_by_id) != len(work_entries):
        raise ValueError("workset contains duplicate entry IDs")
    if len(candidate_by_id) != len(candidate_entries):
        raise ValueError("candidate contains duplicate entry IDs")
    if set(work_by_id) != set(candidate_by_id):
        missing = sorted(set(work_by_id) - set(candidate_by_id))
        extra = sorted(set(candidate_by_id) - set(work_by_id))
        raise ValueError(f"candidate ID mismatch: missing={missing} extra={extra}")

    status_counts: Counter[str] = Counter()
    row_counts: Counter[str] = Counter()
    overflows: list[dict[str, Any]] = []
    capacity_overflows: list[dict[str, Any]] = []
    word_split_fallbacks: list[dict[str, Any]] = []
    protected_token_mismatches: list[dict[str, Any]] = []
    japanese_residue: list[str] = []
    source_reading_suspicions: list[dict[str, str]] = []
    exact_japanese_translations: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    derived_entries: list[dict[str, Any]] = []
    chapters: dict[int, dict[str, Any]] = {}

    source_id_order = [entry["entry_id"] for entry in work_entries]
    candidate_id_order = [entry["id"] for entry in candidate_entries]
    order_mismatches = [
        {
            "index": index,
            "source_id": source_id,
            "candidate_id": candidate_id,
        }
        for index, (source_id, candidate_id) in enumerate(
            zip(source_id_order, candidate_id_order)
        )
        if source_id != candidate_id
    ]

    # Preserve the protected workset order. Stable IDs remain the join key,
    # but derived overlays and chapter files must not invent a second sequence
    # by sorting reference labels lexicographically.
    for source in work_entries:
        entry_id = source["entry_id"]
        korean = candidate_by_id[entry_id].get("ko")
        if not isinstance(korean, str) or not korean.strip():
            raise ValueError(f"{entry_id}: Korean candidate is empty")
        result = wrap_words(korean)
        status_counts[result.status] += 1
        if result.status == "ready":
            row_counts[str(len(result.lines))] += 1

        japanese = source["original"]["japanese"]["display_text"]
        clean_japanese = re.sub(r"\{[^}]+\}", "", japanese)
        exact_japanese_translations[clean_japanese][korean].append(entry_id)
        if JAPANESE_SCRIPT.search(korean):
            japanese_residue.append(entry_id)

        source_name_counts = {
            token: clean_japanese.count(token) + japanese.count(token)
            for token in NAME_WIDTHS
        }
        # clean_japanese has markup removed, so the actual source count is the
        # count in the protected markup-bearing string.
        source_name_counts = {
            token: japanese.count(token) for token in NAME_WIDTHS
        }
        korean_name_counts = {
            token: korean.count(token) for token in NAME_WIDTHS
        }
        if source_name_counts != korean_name_counts:
            protected_token_mismatches.append(
                {
                    "id": entry_id,
                    "source": source_name_counts,
                    "candidate": korean_name_counts,
                    "jp": clean_japanese,
                    "ko": korean,
                }
            )

        for pattern, note in SOURCE_READING_SUSPECTS.items():
            if pattern in clean_japanese:
                source_reading_suspicions.append(
                    {
                        "id": entry_id,
                        "pattern": pattern,
                        "review_note": note,
                        "jp": clean_japanese,
                    }
                )

        derived = {
            "id": entry_id,
            "unit_index": source["source"]["unit_index"],
            "classification": source["classification"],
            "status": result.status,
            "wrap_mode": result.wrap_mode,
            "ko_candidate": korean,
            "ko_reflowed": result.text if result.status == "ready" else None,
            "line_widths": [visible_width(line) for line in result.lines],
            "display_glyph_count": sum(
                visible_width(line) for line in result.lines
            ),
            "minimum_required_glyph_count": minimum_required_glyph_count(
                korean
            ),
            "maximum_glyph_count": MAX_GLYPHS,
        }
        if result.wrap_mode == "space-drop-word-split-fallback":
            normalized_candidate = " ".join(WORD_PATTERN.findall(korean))
            derived["dropped_space_count"] = (
                normalized_candidate.count(" ") - result.text.count(" ")
            )
            derived["non_space_content_preserved"] = (
                re.sub(r"\s+", "", normalized_candidate)
                == re.sub(r"\s+", "", result.text)
            )
        if result.wrap_mode in {
            "word-split-fallback",
            "space-drop-word-split-fallback",
        }:
            word_split_fallbacks.append(
                {
                    "id": entry_id,
                    "unit_index": source["source"]["unit_index"],
                    "classification": source["classification"],
                    "ko_candidate": korean,
                    "ko_reflowed": result.text,
                    "line_widths": [
                        visible_width(line) for line in result.lines
                    ],
                    **(
                        {
                            "dropped_space_count": derived[
                                "dropped_space_count"
                            ],
                            "non_space_content_preserved": derived[
                                "non_space_content_preserved"
                            ],
                        }
                        if result.wrap_mode
                        == "space-drop-word-split-fallback"
                        else {}
                    ),
                }
            )
        if result.status == "word-overflow":
            derived["oversized_words"] = list(result.oversized_words)
        if result.status != "ready":
            glyph_count = int(derived["minimum_required_glyph_count"])
            overflows.append(
                {
                    **derived,
                    "proposed_lines": list(result.lines),
                }
            )
            if glyph_count > MAX_GLYPHS:
                capacity_overflows.append(
                    {
                        "id": entry_id,
                        "unit_index": source["source"]["unit_index"],
                        "classification": source["classification"],
                        "jp": clean_japanese,
                        "ko_candidate": korean,
                        "hard_wrap_lines": list(result.lines),
                        "minimum_required_glyph_count": glyph_count,
                        "maximum_glyph_count": MAX_GLYPHS,
                        "excess_glyph_count": glyph_count - MAX_GLYPHS,
                    }
                )
        derived_entries.append(derived)

        unit_index = int(source["source"]["unit_index"])
        chapter = chapters.setdefault(
            unit_index,
            {
                "schema_version": 1,
                "status": "machine-translated-candidate-needs-review",
                "chapter_id": chapter_label(
                    unit_index, str(source["classification"])
                ),
                "unit_index": unit_index,
                "classification": source["classification"],
                "entries": [],
            },
        )
        chapter["entries"].append(
            {
                "id": entry_id,
                "jp": clean_japanese,
                "ko_candidate": korean,
                "ko_reflowed": (
                    result.text if result.status == "ready" else None
                ),
                "reinsertion_status": result.status,
                "wrap_mode": result.wrap_mode,
            }
        )

    same_japanese_multiple_korean = []
    for japanese, translations in sorted(exact_japanese_translations.items()):
        if len(translations) > 1:
            same_japanese_multiple_korean.append(
                {
                    "jp": japanese,
                    "translations": [
                        {"ko": ko, "ids": ids}
                        for ko, ids in sorted(translations.items())
                    ],
                }
            )

    glossary_canonical_misses: list[dict[str, Any]] = []
    for term in terms:
        jp = term.get("jp")
        ko = term.get("ko_candidate")
        if not isinstance(jp, str) or not isinstance(ko, str):
            continue
        normalized_ko = normalized_for_compare(ko)
        for entry_id, source in work_by_id.items():
            clean_japanese = re.sub(
                r"\{[^}]+\}",
                "",
                source["original"]["japanese"]["display_text"],
            )
            if jp not in clean_japanese:
                continue
            candidate_ko = candidate_by_id[entry_id]["ko"]
            if normalized_ko not in normalized_for_compare(candidate_ko):
                glossary_canonical_misses.append(
                    {
                        "term_id": term["term_id"],
                        "jp_term": jp,
                        "ko_canonical": ko,
                        "id": entry_id,
                        "jp": clean_japanese,
                        "ko": candidate_ko,
                        "review_only": True,
                    }
                )

    for chapter in chapters.values():
        chapter["entry_count"] = len(chapter["entries"])
        chapter["ready_count"] = sum(
            entry["reinsertion_status"] == "ready"
            for entry in chapter["entries"]
        )
        chapter["blocker_count"] = (
            chapter["entry_count"] - chapter["ready_count"]
        )
        chapter["source_workset_sha256"] = sha256_file(workset_path)
        chapter["source_candidate_sha256"] = sha256_file(candidate_path)

    hashes = {
        "workset_sha256": sha256_file(workset_path),
        "candidate_sha256": sha256_file(candidate_path),
        "glossary_sha256": sha256_file(glossary_path),
    }
    overlay = {
        "schema_version": 1,
        "status": "nonrelease-derived-reflow-needs-review",
        **hashes,
        "renderer": {
            "columns": COLUMNS,
            "rows": ROWS,
            "name_widths": NAME_WIDTHS,
            "wrap_policy": (
                "word-boundary, then word-split, then minimum-space-drop "
                "fallback while preserving every non-space glyph"
            ),
        },
        "entry_count": len(derived_entries),
        "ready_count": status_counts["ready"],
        "blocker_count": len(derived_entries) - status_counts["ready"],
        "word_split_fallback_count": len(word_split_fallbacks),
        "entries": derived_entries,
    }
    audit = {
        "schema_version": 1,
        "status": (
            "reinsertion-blocked"
            if overflows or protected_token_mismatches
            else "mechanically-ready-semantic-review-required"
        ),
        **hashes,
        "renderer_validation": {
            "columns": COLUMNS,
            "rows": ROWS,
            "maximum_glyph_count": MAX_GLYPHS,
            "entry_count": len(derived_entries),
            "status_counts": dict(sorted(status_counts.items())),
            "ready_row_counts": dict(sorted(row_counts.items())),
            "word_split_fallback_count": len(word_split_fallbacks),
            "word_split_fallbacks": word_split_fallbacks,
            "capacity_overflow_count": len(capacity_overflows),
            "capacity_overflows": capacity_overflows,
            "overflow_count": len(overflows),
            "overflows": overflows,
        },
        "protected_structure": {
            "stable_id_count": len(work_by_id),
            "stable_id_set_exact": True,
            "candidate_order_matches_workset": not order_mismatches,
            "candidate_order_mismatch_count": len(order_mismatches),
            "candidate_order_mismatches": order_mismatches,
            "name_token_mismatch_count": len(protected_token_mismatches),
            "name_token_mismatches": protected_token_mismatches,
            "japanese_residue_count": len(japanese_residue),
            "japanese_residue_ids": japanese_residue,
        },
        "spelling_review": {
            "same_exact_japanese_multiple_korean_count": len(
                same_japanese_multiple_korean
            ),
            "same_exact_japanese_multiple_korean": (
                same_japanese_multiple_korean
            ),
            "glossary_canonical_miss_candidate_count": len(
                glossary_canonical_misses
            ),
            "glossary_canonical_miss_candidates": glossary_canonical_misses,
            "policy": (
                "Heuristic review candidates only; context and inflection can "
                "make a reported difference legitimate."
            ),
        },
        "source_reading_review": {
            "glyph_map_status": (
                "complete-user-recolored-atlas-ocr-cross-checked"
            ),
            "heuristic_suspicion_count": len(source_reading_suspicions),
            "heuristic_suspicions": source_reading_suspicions,
            "policy": (
                "Do not rewrite protected Japanese or glyph mappings without "
                "glyph-image and JIS-order evidence."
            ),
        },
        "chapter_split": {
            "boundary": "ALLBIN scheduled unit",
            "story_units": list(range(21)),
            "evidence": [
                "loader descriptor 4 is ALLBIN.BIN",
                "sub_8003C558 writes current progress state to descriptor sub_id",
                "sub_80041294 loads that independently scheduled unit",
            ],
            "chapters": [
                {
                    "chapter_id": chapter["chapter_id"],
                    "unit_index": unit_index,
                    "entry_count": chapter["entry_count"],
                    "ready_count": chapter["ready_count"],
                    "blocker_count": chapter["blocker_count"],
                }
                for unit_index, chapter in sorted(chapters.items())
            ],
        },
    }
    return overlay, audit, chapters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workset",
        type=Path,
        default=Path("work/translations/disc1-dialogue.json"),
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=Path("work/translations/disc1-dialogue-ko-candidate.json"),
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        default=Path("data/translations/disc1-glossary-candidates.json"),
    )
    parser.add_argument(
        "--overlay-output",
        type=Path,
        default=Path(
            "work/translations/disc1-dialogue-ko-reflowed-nonrelease.json"
        ),
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path(
            "work/analysis/disc1-translation-reinsertion-audit.json"
        ),
    )
    parser.add_argument(
        "--chapter-dir",
        type=Path,
        default=Path("work/translations/disc1-dialogue-chapters"),
    )
    parser.add_argument(
        "--abbreviation-output",
        type=Path,
        default=Path(
            "work/translations/"
            "disc1-dialogue-abbreviation-required.json"
        ),
    )
    args = parser.parse_args()

    overlay, audit, chapters = build_outputs(
        args.workset, args.candidate, args.glossary
    )
    write_json(args.overlay_output, overlay)
    write_json(args.audit_output, audit)
    capacity_overflows = audit["renderer_validation"]["capacity_overflows"]
    write_json(
        args.abbreviation_output,
        {
            "schema_version": 1,
            "status": (
                "needs-human-abbreviation"
                if capacity_overflows
                else "no-capacity-overflow"
            ),
            "source_workset_sha256": audit["workset_sha256"],
            "source_candidate_sha256": audit["candidate_sha256"],
            "renderer": {
                "columns": COLUMNS,
                "rows": ROWS,
                "maximum_glyph_count": MAX_GLYPHS,
            },
            "policy": (
                "Only entries exceeding the verified 51-glyph capacity are "
                "listed. Preserve meaning; do not overwrite ko_candidate. "
                "A human supplies ko_abbreviated."
            ),
            "entry_count": len(capacity_overflows),
            "entries": [
                {
                    **entry,
                    "ko_abbreviated": "",
                    "review_status": "needs-human-abbreviation",
                }
                for entry in capacity_overflows
            ],
        },
    )
    for unit_index, chapter in sorted(chapters.items()):
        write_json(
            args.chapter_dir / f"disc1-dialogue-u{unit_index:02d}.json",
            chapter,
        )
    manifest = {
        "schema_version": 1,
        "status": "machine-translated-candidate-needs-review",
        "chapter_boundary": "ALLBIN scheduled unit",
        "chapter_count": len(chapters),
        "chapters": [
            {
                "chapter_id": chapter["chapter_id"],
                "unit_index": unit_index,
                "path": f"disc1-dialogue-u{unit_index:02d}.json",
                "entry_count": chapter["entry_count"],
                "ready_count": chapter["ready_count"],
                "blocker_count": chapter["blocker_count"],
            }
            for unit_index, chapter in sorted(chapters.items())
        ],
    }
    write_json(args.chapter_dir / "manifest.json", manifest)
    print(
        f"entries={overlay['entry_count']} ready={overlay['ready_count']} "
        f"blockers={overlay['blocker_count']} chapters={len(chapters)} "
        f"abbreviation_required={len(capacity_overflows)} "
        f"status={audit['status']}"
    )


if __name__ == "__main__":
    main()
