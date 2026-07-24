#!/usr/bin/env python3
"""Classify every scheduled Disc 1 visual state for localization review.

The unit of work is a scheduled state, not an individual rectangle-like
record.  Palette, image, metadata, and control children can form one runtime
asset, while font tables can coincidentally satisfy a rectangle header check.
This report therefore consumes the proven schedule inventory and assigns each
state exactly one localization role.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable


VISUAL_SCHEDULES = (
    "MINI_G1.BIN",
    "MINI_G2.BIN",
    "MINI_G3.BIN",
    "MINI_G4.BIN",
    "AVM_MAP.BIN",
    "START.BIN",
    "OUTSIDE.BIN",
    "MACHINE.BIN",
    "COURSE.BIN",
)


def in_ranges(index: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(start <= index <= end for start, end in ranges)


def classify_state(filename: str, index: int) -> tuple[str, str]:
    """Return the exclusive role and its evidence-backed reason."""

    if filename == "START.BIN":
        if index in {2, 40}:
            return (
                "font_provider",
                "sub_80032704 selects this scheduled START unit as a 74-byte "
                "14x14 3bpp glyph table",
            )
        if 41 <= index <= 64:
            return (
                "portrait_provider",
                "sub_8003C558 loads START 41+story_state and sub_800329B8 "
                "selects 0x560-byte 48x56 4bpp portrait blocks",
            )
        return (
            "baked_text_visual_review",
            "scheduled START visual/UI state; font and portrait providers are "
            "excluded explicitly",
        )

    if filename == "COURSE.BIN" and 26 <= index <= 275:
        return (
            "non_graphic_course_data",
            "one of the 250 scheduled COURSE units without an offset directory; "
            "the visual atlas states are 0..25 and 276",
        )

    if filename == "AVM_MAP.BIN":
        return (
            "baked_text_visual_review",
            "scheduled scene state: either one direct background rectangle or "
            "one indexed palette/image/metadata state",
        )

    if filename == "MACHINE.BIN":
        return (
            "baked_text_visual_review",
            "scheduled machine texture state; sponsor marks, numbers, and "
            "lettering are part of the texture atlas",
        )

    if filename == "COURSE.BIN":
        return (
            "baked_text_visual_review",
            "scheduled course/HUD visual atlas state",
        )

    return (
        "baked_text_visual_review",
        "scheduled visual/UI state with one or more structurally valid VRAM "
        "rectangle children",
    )


def visual_observation(filename: str, index: int) -> str:
    """Attach conservative contact-sheet observations without inferring text."""

    if filename == "START.BIN":
        if in_ranges(index, ((0, 1),)):
            return "title/menu UI and baked labels observed"
        if in_ranges(index, ((9, 17),)):
            return "name/character selection art and baked alphabet/UI observed"
        if in_ranges(index, ((20, 23),)):
            return "race/result/ranking UI and baked labels observed"
        if in_ranges(index, ((24, 37),)):
            return "chapter/end/credits/game-over cards with baked text observed"
        if in_ranges(index, ((38, 39),)):
            return "branding imagery observed"
    if filename == "OUTSIDE.BIN" and index in {0, 1, 2, 9, 10}:
        return "cockpit/status/options UI with baked labels observed"
    if filename == "COURSE.BIN" and index in {24, 25}:
        return "race HUD, result, or warning labels observed"
    if filename == "MACHINE.BIN":
        return "vehicle atlas with logos, numbers, and sponsor lettering observed"
    if filename.startswith("MINI_G"):
        return "HUD/menu texture state observed; text presence needs screen match"
    if filename == "AVM_MAP.BIN":
        return "scene/background state; posters, signage, or UI may contain text"
    if filename == "COURSE.BIN" and 0 <= index <= 23:
        return "course/environment atlas; track signage may contain text"
    if filename == "COURSE.BIN" and index == 276:
        return "visual effect state; no text identified in contact sheet"
    return "no text conclusion from the current contact-sheet pass"


def build_graphics_scope(layout: dict[str, Any]) -> dict[str, Any]:
    schedules = layout["schedules"]
    missing = [filename for filename in VISUAL_SCHEDULES if filename not in schedules]
    if missing:
        raise ValueError(f"layout is missing visual schedules: {', '.join(missing)}")

    states = []
    role_counts: Counter[str] = Counter()
    for filename in VISUAL_SCHEDULES:
        schedule = schedules[filename]
        entries = schedule["entries"]
        inventory_units = schedule["inventory"]["units"]
        if len(entries) != len(inventory_units):
            raise ValueError(f"{filename} schedule/inventory length mismatch")
        for entry, inventory in zip(entries, inventory_units, strict=True):
            if entry["index"] != inventory["index"]:
                raise ValueError(f"{filename} schedule/inventory index mismatch")
            role, reason = classify_state(filename, entry["index"])
            role_counts[role] += 1
            states.append(
                {
                    "filename": filename,
                    "state_index": entry["index"],
                    "file_offset": entry["byte_offset"],
                    "byte_size": entry["byte_size"],
                    "sha256": inventory["sha256"],
                    "structural_kind": inventory["kind"],
                    "role": role,
                    "role_reason": reason,
                    "visual_observation": visual_observation(
                        filename, entry["index"]
                    ),
                    "consumer_evidence": (
                        "schedule/storage boundary proven; exact screen "
                        "consumer must be traced before editing this state"
                    ),
                    "edit_status": "blocked_pending_per_target_consumer_trace",
                }
            )

    expected = sum(schedules[name]["entry_count"] for name in VISUAL_SCHEDULES)
    if len(states) != expected:
        raise ValueError(f"state denominator mismatch: {len(states)} != {expected}")
    if sum(role_counts.values()) != len(states):
        raise ValueError("role classification is not an exact partition")

    return {
        "schema_version": 1,
        "method": {
            "unit_of_work": (
                "one scheduled runtime state; child records are not independent "
                "translation assets"
            ),
            "denominator_proof": (
                "the schedule tables partition each covered file exactly; every "
                "state is assigned exactly one role"
            ),
            "consumer_policy": (
                "a structural VRAM rectangle or contact-sheet resemblance is not "
                "screen-consumer proof; trace storage->load/transform->resident "
                "VRAM->draw before editing each target"
            ),
        },
        "summary": {
            "scheduled_visual_state_denominator": len(states),
            "role_counts": dict(sorted(role_counts.items())),
            "modification_candidate_state_count": role_counts[
                "baked_text_visual_review"
            ],
            "modification_gate": "closed_pending_per_target_consumer_trace",
        },
        "states": states,
    }


def report_summary(report: dict[str, Any]) -> dict[str, Any]:
    by_file: dict[str, Counter[str]] = {}
    for state in report["states"]:
        by_file.setdefault(state["filename"], Counter())[state["role"]] += 1
    return {
        "schema_version": report["schema_version"],
        "method": report["method"],
        "summary": report["summary"],
        "files": {
            filename: dict(sorted(counts.items()))
            for filename, counts in by_file.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--layout",
        type=Path,
        default=Path("work/analysis/disc1-layout.json"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    report = build_graphics_scope(
        json.loads(args.layout.read_text(encoding="utf-8"))
    )
    selected = report_summary(report) if args.summary else report
    rendered = json.dumps(selected, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(args.output)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
