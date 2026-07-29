#!/usr/bin/env python3
"""Export a compact, translation-only view of the Disc 1 dialogue workset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PRESERVED_TEXT_TOKENS = {"name_surname", "name_given"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dialogue_only_text(original: dict[str, Any]) -> str:
    text = original["japanese"]["display_text"]
    for control in original["control_tokens"]:
        if control["kind"] in PRESERVED_TEXT_TOKENS:
            continue
        # {align} is already represented by a newline in display_text.
        text = text.replace(control["markup"], "")
    return text.strip()


def confirmed_max_glyphs(
    entry: dict[str, Any],
    layout_profiles: dict[str, Any],
) -> int | None:
    layout = entry.get("layout")
    if not isinstance(layout, dict):
        return None
    profile_id = layout.get("profile")
    profile = layout_profiles.get(profile_id)
    if not isinstance(profile, dict):
        raise ValueError(
            f"{entry['entry_id']}: unknown layout profile {profile_id!r}"
        )
    capacity = profile.get("capacity_positions")
    if not isinstance(capacity, int) or capacity < 1:
        raise ValueError(
            f"{entry['entry_id']}: invalid layout capacity"
        )
    return capacity


def build_brief(source: dict[str, Any], source_path: Path) -> dict[str, Any]:
    if source.get("schema_version") != 2:
        raise ValueError("expected dialogue workset schema_version 2")
    if source.get("workset_kind") != "dialogue":
        raise ValueError("input is not a dialogue workset")

    layout_profiles = source.get("layout_profiles")
    entries = source.get("entries")
    if not isinstance(layout_profiles, dict) or not isinstance(entries, list):
        raise ValueError("dialogue workset structure is invalid")

    compact_entries = []
    seen_ids: set[str] = set()
    for entry in entries:
        entry_id = entry.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError("every entry requires a stable entry_id")
        if entry_id in seen_ids:
            raise ValueError(f"duplicate entry_id: {entry_id}")
        seen_ids.add(entry_id)

        japanese = entry["original"]["japanese"]
        if not japanese["mapping_complete"] or japanese["unmapped_glyphs"]:
            raise ValueError(f"{entry_id}: Japanese glyph mapping is incomplete")

        compact_entries.append(
            {
                "id": entry_id,
                "max_glyphs": confirmed_max_glyphs(entry, layout_profiles),
                "jp": dialogue_only_text(entry["original"]),
                "ko": "",
            }
        )

    return {
        "schema_version": 1,
        "source": str(source_path),
        "source_sha256": sha256_file(source_path),
        "rules": {
            "editable_field": "entries[].ko",
            "max_glyphs": (
                "Confirmed total visible glyph positions; null means that "
                "the renderer-specific limit is not yet proven."
            ),
            "name_widths": {
                "{name:surname}": 4,
                "{name:given}": 4,
            },
        },
        "entry_count": len(compact_entries),
        "entries": compact_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("work/translations/disc1-dialogue.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "work/translations/disc1-dialogue-translation-brief.json"
        ),
    )
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    brief = build_brief(source, args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    confirmed = sum(
        entry["max_glyphs"] is not None for entry in brief["entries"]
    )
    print(
        f"output={args.output} entries={brief['entry_count']} "
        f"confirmed_limits={confirmed} "
        f"unconfirmed_limits={brief['entry_count'] - confirmed}"
    )


if __name__ == "__main__":
    main()
