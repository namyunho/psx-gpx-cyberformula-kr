#!/usr/bin/env python3
"""Validate translation candidates and publish review-safe tracked artifacts."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any


JAPANESE_SCRIPT = re.compile(r"[ぁ-んァ-ヶ一-龯]")
NAME_WIDTHS = {
    "{name:surname}": 4,
    "{name:given}": 4,
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def indexed_entries(
    document: dict[str, Any],
    label: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{label}: entries must be a list")

    index: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{label}: every entry must be an object")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError(f"{label}: every entry requires a non-empty id")
        if entry_id in index:
            duplicates.append(entry_id)
        else:
            index[entry_id] = entry
    return entries, index, sorted(set(duplicates))


def visible_width(text: str) -> int:
    """Count stored glyph positions, including renderer line alignment."""
    width = 0
    for line_number, line in enumerate(text.split("\n")):
        if line_number:
            width = ((width + 16) // 17) * 17
        for token, token_width in NAME_WIDTHS.items():
            line = line.replace(token, "가" * token_width)
        width += len(line)
    return width


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_outputs(
    brief_path: Path,
    translation_path: Path,
    glossary_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    brief = load_object(brief_path)
    translation = load_object(translation_path)
    glossary = load_object(glossary_path)

    brief_entries, brief_by_id, brief_duplicates = indexed_entries(
        brief, "brief"
    )
    candidate_entries, candidate_by_id, candidate_duplicates = indexed_entries(
        translation, "translation candidate"
    )

    brief_ids = set(brief_by_id)
    candidate_ids = set(candidate_by_id)
    missing_ids = sorted(brief_ids - candidate_ids)
    extra_ids = sorted(candidate_ids - brief_ids)
    protected_mismatches: list[str] = []
    empty_korean: list[str] = []
    confirmed_overflows: list[dict[str, Any]] = []
    japanese_residue: list[str] = []

    for entry_id in sorted(brief_ids & candidate_ids):
        source = brief_by_id[entry_id]
        candidate = candidate_by_id[entry_id]
        if any(
            candidate.get(field) != source.get(field)
            for field in ("id", "jp", "max_glyphs")
        ):
            protected_mismatches.append(entry_id)

        korean = candidate.get("ko")
        if not isinstance(korean, str) or not korean.strip():
            empty_korean.append(entry_id)
            continue
        if JAPANESE_SCRIPT.search(korean):
            japanese_residue.append(entry_id)

        limit = source.get("max_glyphs")
        if limit is not None:
            if not isinstance(limit, int) or limit < 1:
                raise ValueError(f"{entry_id}: invalid max_glyphs")
            used = visible_width(korean)
            if used > limit:
                confirmed_overflows.append(
                    {
                        "id": entry_id,
                        "used_glyphs": used,
                        "max_glyphs": limit,
                    }
                )

    terms = glossary.get("terms")
    if not isinstance(terms, list):
        raise ValueError("glossary: terms must be a list")
    term_ids: set[str] = set()
    duplicate_term_ids: list[str] = []
    invalid_evidence: list[dict[str, str]] = []
    confidence_counts: Counter[str] = Counter()
    translations_by_japanese: dict[str, set[str]] = defaultdict(set)
    low_confidence_term_ids: list[str] = []

    for term in terms:
        if not isinstance(term, dict):
            raise ValueError("glossary: every term must be an object")
        term_id = term.get("term_id")
        if not isinstance(term_id, str) or not term_id:
            raise ValueError("glossary: every term requires a non-empty term_id")
        if term_id in term_ids:
            duplicate_term_ids.append(term_id)
        term_ids.add(term_id)

        confidence = term.get("confidence")
        if not isinstance(confidence, str):
            raise ValueError(f"{term_id}: confidence must be a string")
        confidence_counts[confidence] += 1
        if confidence == "low":
            low_confidence_term_ids.append(term_id)

        japanese = term.get("jp")
        korean = term.get("ko_candidate")
        if isinstance(japanese, str) and isinstance(korean, str):
            translations_by_japanese[japanese].add(korean)

        evidence_ids = term.get("evidence_ids", [])
        if not isinstance(evidence_ids, list):
            raise ValueError(f"{term_id}: evidence_ids must be a list")
        for evidence_id in evidence_ids:
            if evidence_id not in brief_ids:
                invalid_evidence.append(
                    {"term_id": term_id, "evidence_id": str(evidence_id)}
                )

    conflicting_japanese_terms = [
        {"jp": japanese, "ko_candidates": sorted(korean)}
        for japanese, korean in sorted(translations_by_japanese.items())
        if len(korean) > 1
    ]
    confirmed_limits = sum(
        entry.get("max_glyphs") is not None for entry in brief_entries
    )

    errors = {
        "brief_duplicate_ids": brief_duplicates,
        "candidate_duplicate_ids": candidate_duplicates,
        "missing_ids": missing_ids,
        "extra_ids": extra_ids,
        "protected_field_mismatches": protected_mismatches,
        "empty_korean": empty_korean,
        "confirmed_limit_overflows": confirmed_overflows,
        "japanese_script_residue": japanese_residue,
        "duplicate_term_ids": sorted(set(duplicate_term_ids)),
        "invalid_glossary_evidence_ids": invalid_evidence,
        "same_japanese_multiple_korean": conflicting_japanese_terms,
    }
    if any(errors.values()):
        raise ValueError(
            "candidate validation failed:\n"
            + json.dumps(errors, ensure_ascii=False, indent=2)
        )

    hashes = {
        "brief_sha256": sha256_file(brief_path),
        "translation_candidate_sha256": sha256_file(translation_path),
        "glossary_candidate_sha256": sha256_file(glossary_path),
    }
    overlay = {
        "schema_version": 1,
        "status": "machine-translated-candidate-needs-review",
        **hashes,
        "entry_count": len(candidate_entries),
        "entries": [
            {"id": entry["id"], "ko": entry["ko"]}
            for entry in candidate_entries
        ],
    }
    audit = {
        "schema_version": 1,
        "status": "mechanically-validated-semantic-review-required",
        **hashes,
        "mechanical_validation": {
            "entry_count": len(candidate_entries),
            "confirmed_limits": confirmed_limits,
            "unconfirmed_limits": len(brief_entries) - confirmed_limits,
            "brief_duplicate_ids": 0,
            "candidate_duplicate_ids": 0,
            "missing_ids": 0,
            "extra_ids": 0,
            "protected_field_mismatches": 0,
            "empty_korean": 0,
            "confirmed_limit_overflows": 0,
            "japanese_script_residue": 0,
        },
        "glossary_validation": {
            "term_count": len(terms),
            "confidence_counts": dict(sorted(confidence_counts.items())),
            "duplicate_term_ids": 0,
            "invalid_evidence_ids": 0,
            "same_japanese_multiple_korean": 0,
        },
        "review_queue": {
            "dialogue_entries": len(candidate_entries),
            "medium_or_low_glossary_terms": (
                confidence_counts["medium"] + confidence_counts["low"]
            ),
            "low_confidence_term_ids": sorted(low_confidence_term_ids),
            "not_mechanically_validated": [
                "translation meaning and omissions",
                "character voice and register",
                "proper-name identity and transliteration consistency",
                "renderer layout for entries whose max_glyphs is null",
            ],
        },
    }
    return overlay, glossary, audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--brief",
        type=Path,
        default=Path(
            "work/translations/disc1-dialogue-translation-brief.json"
        ),
    )
    parser.add_argument(
        "--translation",
        type=Path,
        default=Path(
            "work/translations/disc1-dialogue-ko-candidate.json"
        ),
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        default=Path(
            "work/translations/disc1-glossary-candidates.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/translations"),
    )
    args = parser.parse_args()

    overlay, glossary, audit = build_outputs(
        args.brief, args.translation, args.glossary
    )
    write_json(
        args.output_dir / "disc1-dialogue-ko-candidate.json",
        overlay,
    )
    write_json(
        args.output_dir / "disc1-glossary-candidates.json",
        glossary,
    )
    write_json(
        args.output_dir / "disc1-translation-candidate-audit.json",
        audit,
    )
    print(
        f"entries={overlay['entry_count']} "
        f"terms={audit['glossary_validation']['term_count']} "
        f"review_status={audit['status']}"
    )


if __name__ == "__main__":
    main()
