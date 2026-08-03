#!/usr/bin/env python3
"""Merge reviewed new translations with matching existing Korean text."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


DEFAULT_EXISTING_PAIRS = (
    (
        Path("work/translations/disc1-dialogue.json"),
        Path("work/translations/disc1-dialogue-ko-reflowed-nonrelease.json"),
        "entries",
    ),
    (
        Path("work/translations/disc1-pointerless-pages-u00-u21.json"),
        Path("data/translations/disc1-pointerless-pages-u00-u21-ko.json"),
        "entries",
    ),
    (
        Path("work/translations/disc1-special-screen-text.json"),
        Path("data/translations/disc1-special-screen-ko.json"),
        "translations",
    ),
)

EXPECTED_WORKSET_ENTRY_COUNT = 724
EXPECTED_NEW_UNIQUE_TEXT_COUNT = 296
EXPECTED_AMBIGUOUS_PHYSICAL_ENTRY_COUNT = 23


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


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def visible_text(entry: dict[str, Any], glyphs: dict[int, str]) -> str:
    output: list[str] = []
    for raw_token in entry["original"]["tokens"]:
        token = int(raw_token, 16)
        if token < 0x4000:
            output.append(glyphs[token])
        elif token == 0x4000:
            output.append("{name:surname}")
        elif token == 0x6000:
            output.append("{name:given}")
        elif token == 0xFFFB:
            output.append("\n")
    return "".join(output)


def normalized_text(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", text)


def translation_text(item: dict[str, Any]) -> str:
    value = item.get("ko")
    if isinstance(value, str):
        return value
    reflowed = item.get("ko_reflowed")
    if isinstance(reflowed, str):
        return reflowed
    segments = item.get("ko_segments")
    if isinstance(segments, list) and all(
        isinstance(segment, str) for segment in segments
    ):
        return "\n".join(segments)
    raise ValueError(f"{item.get('id')}: Korean translation is missing")


def entries_by_id(
    items: Iterable[dict[str, Any]],
    *,
    key: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        entry_id = item.get(key)
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError(f"invalid stable ID in {item!r}")
        if entry_id in result:
            raise ValueError(f"duplicate stable ID: {entry_id}")
        result[entry_id] = item
    return result


def build_existing_translation_index(
    *,
    pairs: Iterable[tuple[Path, Path, str]],
    glyphs: dict[int, str],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for workset_path, translation_path, translation_key in pairs:
        workset = load_object(workset_path)
        translation = load_object(translation_path)
        source_by_id = entries_by_id(
            workset.get("entries", []),
            key="entry_id",
        )
        translated_by_id = entries_by_id(
            translation.get(translation_key, []),
            key="id",
        )
        missing = sorted(set(source_by_id) - set(translated_by_id))
        if missing:
            raise ValueError(
                f"{translation_path}: missing {len(missing)} source IDs"
            )
        for entry_id, source in source_by_id.items():
            key = normalized_text(visible_text(source, glyphs))
            result[key].add(
                translation_text(translated_by_id[entry_id])
            )
    return result


def build_translation(
    *,
    workset_path: Path,
    manual_path: Path,
    glyph_map_path: Path,
    existing_pairs: Iterable[tuple[Path, Path, str]] = DEFAULT_EXISTING_PAIRS,
) -> dict[str, Any]:
    workset = load_object(workset_path)
    manual = load_object(manual_path)
    glyph_map = load_object(glyph_map_path)
    glyph_strings = (
        glyph_map.get("tables", {}).get("primary", {}).get("glyphs")
    )
    if not isinstance(glyph_strings, dict):
        raise ValueError("primary glyph map is missing")
    glyphs = {int(key, 16): value for key, value in glyph_strings.items()}

    workset_entries = workset.get("entries")
    if (
        not isinstance(workset_entries, list)
        or len(workset_entries) != EXPECTED_WORKSET_ENTRY_COUNT
    ):
        raise ValueError("unindexed workset population differs")
    source_by_id = entries_by_id(workset_entries, key="entry_id")

    manual_entries = manual.get("entries")
    if not isinstance(manual_entries, list):
        raise ValueError("manual translation entries must be an array")
    manual_by_id = entries_by_id(manual_entries, key="id")
    unknown_manual_ids = sorted(set(manual_by_id) - set(source_by_id))
    if unknown_manual_ids:
        raise ValueError(
            f"manual translations contain unknown IDs: {unknown_manual_ids[:3]}"
        )

    existing_index = build_existing_translation_index(
        pairs=existing_pairs,
        glyphs=glyphs,
    )
    source_text_by_id = {
        entry_id: visible_text(entry, glyphs)
        for entry_id, entry in source_by_id.items()
    }
    normalized_by_id = {
        entry_id: normalized_text(text)
        for entry_id, text in source_text_by_id.items()
    }

    manual_by_normalized: dict[str, set[str]] = defaultdict(set)
    for entry_id, item in manual_by_id.items():
        manual_by_normalized[normalized_by_id[entry_id]].add(
            translation_text(item)
        )

    # A manual entry is required for each new unique text.  Multiple manual
    # values for one Japanese string are allowed only as exact-ID overrides.
    new_unique = {
        value
        for value in normalized_by_id.values()
        if value not in existing_index
    }
    missing_new = sorted(new_unique - set(manual_by_normalized))
    if missing_new:
        raise ValueError(
            f"manual file misses {len(missing_new)} new unique texts"
        )
    if len(new_unique) != EXPECTED_NEW_UNIQUE_TEXT_COUNT:
        raise ValueError(
            f"new unique text population changed: "
            f"{len(new_unique)} != {EXPECTED_NEW_UNIQUE_TEXT_COUNT}"
        )

    output_entries: list[dict[str, Any]] = []
    provenance_counts: Counter[str] = Counter()
    ambiguous_physical_count = 0
    for source in workset_entries:
        entry_id = source["entry_id"]
        key = normalized_by_id[entry_id]
        if entry_id in manual_by_id:
            ko = translation_text(manual_by_id[entry_id])
            provenance = "manual-context-or-new-translation"
        elif key in existing_index and len(existing_index[key]) == 1:
            ko = next(iter(existing_index[key]))
            provenance = "reused-identical-existing-japanese"
        elif key in existing_index:
            if len(manual_by_normalized[key]) == 1:
                ko = next(iter(manual_by_normalized[key]))
                provenance = "manual-existing-ambiguity-resolution"
                ambiguous_physical_count += 1
            else:
                raise ValueError(
                    f"{entry_id}: identical Japanese has conflicting existing "
                    "translations and needs an exact-ID manual override"
                )
        elif len(manual_by_normalized[key]) == 1:
            ko = next(iter(manual_by_normalized[key]))
            provenance = "reused-identical-new-japanese"
        else:
            raise ValueError(
                f"{entry_id}: new Japanese has multiple Korean decisions and "
                "needs an exact-ID manual override"
            )
        if not ko:
            raise ValueError(f"{entry_id}: Korean translation is empty")
        output_entry = {
            "id": entry_id,
            "ko": ko,
            "review_status": "needs-independent-and-runtime-review",
            "provenance": provenance,
        }
        if entry_id in manual_by_id:
            visual_width_reviewed = manual_by_id[entry_id].get(
                "layout_visual_width_reviewed",
                False,
            )
            if not isinstance(visual_width_reviewed, bool):
                raise ValueError(
                    f"{entry_id}: visual-width review flag must be boolean"
                )
            if visual_width_reviewed:
                output_entry["layout_visual_width_reviewed"] = True
            allowance = manual_by_id[entry_id].get(
                "layout_overflow_allowance_px",
                0,
            )
            if not isinstance(allowance, int) or allowance < 0:
                raise ValueError(
                    f"{entry_id}: layout overflow allowance must be a "
                    "non-negative integer"
                )
            if allowance:
                if not visual_width_reviewed:
                    raise ValueError(
                        f"{entry_id}: pixel allowance requires reviewed "
                        "visual width"
                    )
                output_entry["layout_overflow_allowance_px"] = allowance
        output_entries.append(output_entry)
        provenance_counts[provenance] += 1

    # Count the exact-ID overrides that resolve pre-existing ambiguity.
    exact_manual_ambiguous = sum(
        normalized_by_id[entry_id] in existing_index
        and len(existing_index[normalized_by_id[entry_id]]) > 1
        for entry_id in manual_by_id
    )
    resolved_ambiguous = exact_manual_ambiguous + ambiguous_physical_count
    if resolved_ambiguous != EXPECTED_AMBIGUOUS_PHYSICAL_ENTRY_COUNT:
        raise ValueError(
            "ambiguous physical-entry override population changed: "
            f"{resolved_ambiguous} != "
            f"{EXPECTED_AMBIGUOUS_PHYSICAL_ENTRY_COUNT}"
        )
    return {
        "schema_version": 1,
        "status": (
            "complete-draft-translation-needs-independent-language-and-"
            "runtime-review"
        ),
        "baseline_id": workset["baseline_id"],
        "source_workset": str(workset_path),
        "source_workset_sha256": sha256_file(workset_path),
        "manual_translation_source": str(manual_path),
        "manual_translation_source_sha256": sha256_file(manual_path),
        "scope": {
            "entry_count": len(output_entries),
            "new_unique_text_count": len(new_unique),
            "ambiguous_context_override_count": resolved_ambiguous,
            "graphics_text_excluded": True,
        },
        "policy": {
            "original_and_control_tokens": "protected-in-source-workset",
            "identical_japanese_reuse": (
                "reuse only when the existing Korean decision is unambiguous"
            ),
            "review": (
                "Codex draft; independent language review and user runtime "
                "review are required before release eligibility"
            ),
        },
        "summary": {
            "translation_count": len(output_entries),
            "empty_translation_count": 0,
            "provenance_counts": dict(sorted(provenance_counts.items())),
        },
        "translations": output_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workset",
        type=Path,
        default=Path(
            "work/translations/disc1-unindexed-font-text.json"
        ),
    )
    parser.add_argument(
        "--manual",
        type=Path,
        default=Path(
            "data/translations/disc1-unindexed-font-ko-manual.json"
        ),
    )
    parser.add_argument(
        "--glyph-map",
        type=Path,
        default=Path("data/glyph-map.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/translations/disc1-unindexed-font-ko.json"
        ),
    )
    args = parser.parse_args()
    document = build_translation(
        workset_path=args.workset,
        manual_path=args.manual,
        glyph_map_path=args.glyph_map,
    )
    write_json(args.output, document)
    print(
        f"translations={document['summary']['translation_count']} "
        f"new_unique={document['scope']['new_unique_text_count']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
