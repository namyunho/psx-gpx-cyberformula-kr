#!/usr/bin/env python3
"""Extract font-rendered mini-game, course, and machine-setting text.

This extractor intentionally excludes baked graphical labels and buttons.  Its
tables and population assertions are backed by the complementary IDA/Ghidra
consumer survey in ``scripts/ghidra/AnalyzeSpecialScreenText.java``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Iterable

try:
    from scripts.build_dialogue_chapter_patch import EXPECTED_ALLBIN_SHA256
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import EXPECTED_ALLBIN_SHA256


BASELINE_ID = f"disc1-allbin-{EXPECTED_ALLBIN_SHA256[:16]}"

UNIT_PROFILES = {
    38: {
        "file_offset": 0x12B000,
        "byte_size": 0x20000,
        "runtime_base": 0x80098000,
        "sha256": (
            "533f5e8585504a70d704ee64e2c41a48"
            "fb29e17f1e5ed4803ade1072c0ee5a6f"
        ),
    },
    43: {
        "file_offset": 0x169000,
        "byte_size": 0x5800,
        "runtime_base": 0x800A8000,
        "sha256": (
            "6bb12d3f6bb4b44e0ecbfe9c9944eb1"
            "56b94f2d48ceef9cee10e5fd9373a0cd2"
        ),
    },
}

# These seven tables are selected by the course/state switch in the u43
# consumer.  States 4..6 and 9..13 intentionally share tables.
COURSE_POINTER_TABLES = (
    {"table_offset": 0x546C, "pointer_count": 11, "states": [1]},
    {"table_offset": 0x5498, "pointer_count": 7, "states": [2]},
    {"table_offset": 0x54B4, "pointer_count": 5, "states": [3]},
    {"table_offset": 0x54C8, "pointer_count": 13, "states": [4, 5, 6]},
    {"table_offset": 0x54FC, "pointer_count": 8, "states": [7]},
    {"table_offset": 0x551C, "pointer_count": 6, "states": [8]},
    {
        "table_offset": 0x5534,
        "pointer_count": 7,
        "states": [9, 10, 11, 12, 13],
    },
)

MACHINE_SETTING_STARTS = (
    (0x4068, "tire_a"),
    (0x40C8, "tire_b"),
    (0x4120, "tire_c"),
    (0x417C, "strategy_b_then_c"),
    (0x41B0, "strategy_b_only"),
    (0x41D4, "strategy_c_then_b"),
    (0x4208, "wing_wide_angle"),
    (0x4268, "wing_narrow_angle"),
    (0x42C8, "wing_normal"),
    (0x4320, "boost_short"),
    (0x4384, "boost_hyper"),
    (0x43E4, "boost_normal"),
)

# Runtime-observed garage action menus.  Unlike the adjacent course and
# machine-setting pages, these fixed three-choice streams terminate with the
# event transition token D003.  PCSX-Redux RAM/VRAM capture connected the two
# source ranges to the on-screen garage menu on 2026-08-01.
GARAGE_ACTION_MENU_STARTS = (
    (0x3E34, "race_available"),
    (0x3E70, "rest_available"),
)

# The rule-page heading and the four mini-game titles are stored immediately
# before the pointer-backed rule body.  PCSX-Redux VRAM inspection on
# 2026-08-01 confirmed that these are font-rendered strings, not baked pixels.
U38_RULE_LABELS = (
    (0x18214, "heading", "minigame_rule_heading"),
    (0x18224, "catch", "minigame_rule_title"),
    (0x1823C, "camera", "minigame_rule_title"),
    (0x18254, "cooking", "minigame_rule_title"),
    (0x1826C, "blackjack", "minigame_rule_title"),
)

# Direct renderer/string consumer addresses proved independently by IDA and
# Ghidra.  Three entries are physical prefixes of another callable entry; the
# explicit end keeps those shared suffixes non-overlapping in the workset.
U38_DIRECT_DIALOGUE = (
    (0x1833C, "rules_catch_end", None),
    (0x18508, "rules_camera_end", None),
    (0x18768, "rules_cooking_end", None),
    (0x18B98, "rules_blackjack_end", None),
    (0x18C64, "blackjack_limit_warning", None),
    (0x18D00, "blackjack_replace_prompt", 0x18D3C),
    (0x18D3C, "blackjack_draw_game", None),
    (0x1CE94, "camera_shutter_chance", 0x1CEB0),
    (0x1CEB0, "camera_timing_scold", None),
    (0x1CED0, "camera_result_question", None),
    (0x1CF04, "camera_good_result", None),
    (0x1CF30, "camera_photo_choice", None),
    (0x1CF7C, "camera_first_photo", None),
    (0x1CFAC, "camera_second_photo", None),
    (0x1D8E4, "cooking_mix_instruction", None),
    (0x1D940, "cooking_cheer", 0x1D954),
    (0x1D954, "cooking_pan_instruction", None),
    (0x1D9A8, "cooking_complete", None),
    (0x1D9C0, "cooking_confidence", None),
    (0x1D9E8, "cooking_favorite_prefix", None),
    (0x1DA14, "cooking_taste_start", None),
    (0x1DA58, "cooking_reaction_00", None),
    (0x1DA94, "cooking_reaction_01", None),
    (0x1DAF4, "cooking_reaction_02", None),
    (0x1DB60, "cooking_reaction_03", None),
    (0x1DBB4, "cooking_reaction_04", None),
    (0x1DC08, "cooking_reaction_05", None),
    (0x1DC4C, "cooking_reaction_06", None),
    (0x1DCAC, "cooking_reaction_07", None),
    (0x1DD10, "cooking_reaction_08", None),
    (0x1DD38, "cooking_reaction_09", None),
    (0x1DDA8, "cooking_reaction_10", None),
    (0x1DDE0, "cooking_reaction_11", None),
    (0x1DE34, "cooking_reaction_12", None),
    (0x1DE70, "cooking_reaction_13", None),
    (0x1DEFC, "cooking_reaction_14", None),
    (0x1DF50, "cooking_reaction_15", None),
    (0x1DFB0, "cooking_reaction_16", None),
    (0x1E000, "cooking_reaction_17", None),
)

# Runtime-selected words are written to the cooking result consumer through
# two switch tables.  They are font strings, not baked image labels.
U38_COOKING_WORDS = (
    (0x1E0D8, "dish_00"),
    (0x1E0E4, "dish_01"),
    (0x1E0F4, "dish_02"),
    (0x1E104, "dish_03"),
    (0x1E110, "dish_04"),
    (0x1E11C, "dish_05"),
    (0x1E128, "dish_06"),
    (0x1E134, "dish_07"),
    (0x1E144, "dish_08"),
    (0x1E150, "dish_09"),
    (0x1E15C, "dish_10"),
    (0x1E16C, "dish_11"),
    (0x1E17C, "dish_12"),
    (0x1E188, "dish_13"),
    (0x1E198, "dish_14"),
    (0x1E1A4, "dish_15"),
    (0x1E1B0, "condition_00"),
    (0x1E1B8, "condition_01"),
    (0x1E1C4, "condition_02"),
    (0x1E1D0, "condition_03"),
    (0x1E1E0, "condition_04"),
    (0x1E1EC, "condition_05"),
    (0x1E1F4, "condition_06"),
)

U38_POINTER_TARGET_MIN = 0x18214
U38_POINTER_TARGET_MAX_EXCLUSIVE = 0x1ED7C
EXPECTED_U38_POINTER_PAGE_COUNT = 260
EXPECTED_U38_DIRECT_DIALOGUE_COUNT = len(U38_DIRECT_DIALOGUE)
EXPECTED_U38_COOKING_WORD_COUNT = len(U38_COOKING_WORDS)
EXPECTED_COURSE_PAGE_COUNT = 57
EXPECTED_MACHINE_SETTING_COUNT = len(MACHINE_SETTING_STARTS)
EXPECTED_GARAGE_ACTION_MENU_COUNT = len(GARAGE_ACTION_MENU_STARTS)
EXPECTED_U38_RULE_LABEL_COUNT = len(U38_RULE_LABELS)

# The u43 machine-setting consumer also advances through two pointerless
# dialogue spans around the twelve directly addressed explanation strings.
# Speaker-style words delimit the individual slots.  The confirmation choice
# keeps FFFD and D002 at fixed offsets, so it is split into prompt and choice
# records instead of being treated as one relocatable string.
U43_MACHINE_SEQUENTIAL_SLOTS = (
    (0x03EA8, 0x03EF0, "tutorial_ready", 3),
    (0x03EF0, 0x03F20, "tutorial_doubt", 3),
    (0x03F20, 0x03F64, "tutorial_request", 3),
    (0x03F64, 0x04068, "tutorial_categories", 4),
    (0x04444, 0x0447C, "knowledge_question", 3),
    (0x0447C, 0x044C8, "rena_boast", 3),
    (0x044C8, 0x044D4, "stare", 1),
    (0x044D4, 0x0453C, "rulebook_confession", 4),
    (0x0453C, 0x04544, "surprise", 1),
    (0x04544, 0x04574, "rulebook_detail", 3),
    (0x04574, 0x045C4, "basics_tease", 3),
    (0x045C4, 0x045D4, "rena_reaction", 1),
    (0x045D4, 0x04670, "save_reminder", 4),
    (0x04670, 0x0468C, "acknowledge", 1),
    (0x0468C, 0x046D4, "begin_setting", 3),
    (0x046D4, 0x046E4, "choose_setting", 1),
    (0x046E4, 0x04712, "confirm_prompt", 3),
    (0x04712, 0x04724, "confirm_choice", 2),
    (0x04724, 0x04758, "setting_complete", 3),
    (0x04758, 0x04784, "setting_retry", 3),
)
EXPECTED_U43_MACHINE_SEQUENTIAL_COUNT = len(U43_MACHINE_SEQUENTIAL_SLOTS)

TERMINALS = frozenset({0x8000, 0xFFFF})


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
    if 0xA000 <= token <= 0xAFFF:
        return "style_off"
    if 0xC000 <= token <= 0xCFFF:
        return "delay"
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
    return (token in glyphs) if kind is None else kind != "unknown"


def decode_visible_text(tokens: Iterable[int], glyphs: dict[int, str]) -> str:
    output: list[str] = []
    for token in tokens:
        kind = control_kind(token)
        if kind is None:
            try:
                output.append(glyphs[token])
            except KeyError as error:
                raise ValueError(f"unmapped primary glyph 0x{token:04X}") from error
        elif kind == "align":
            output.append("\n")
        elif kind == "name_surname":
            output.append("{name:surname}")
        elif kind == "name_given":
            output.append("{name:given}")
    return "".join(output)


def parse_tokens(
    data: bytes,
    start: int,
    *,
    glyphs: dict[int, str],
    end_exclusive: int | None = None,
    terminal: int | None = None,
    max_bytes: int = 0x300,
) -> tuple[list[int], int]:
    if start % 2:
        raise ValueError(f"unaligned text start 0x{start:X}")
    limit = (
        end_exclusive
        if end_exclusive is not None
        else min(len(data), start + max_bytes)
    )
    if not start < limit <= len(data) or (limit - start) % 2:
        raise ValueError(f"invalid text range 0x{start:X}:0x{limit:X}")
    tokens: list[int] = []
    end = start
    while end < limit:
        token = struct.unpack_from("<H", data, end)[0]
        if not token_is_supported(token, glyphs):
            raise ValueError(
                f"unsupported token 0x{token:04X} at unit offset 0x{end:X}"
            )
        tokens.append(token)
        end += 2
        if end_exclusive is None and (
            token == terminal if terminal is not None else token in TERMINALS
        ):
            break
    if end_exclusive is not None:
        if end != end_exclusive:
            raise AssertionError("fixed fragment did not reach its boundary")
    else:
        expected = {terminal} if terminal is not None else TERMINALS
        if not tokens or tokens[-1] not in expected:
            raise ValueError(f"unterminated text at unit offset 0x{start:X}")
    return tokens, end


def control_records(tokens: Iterable[int]) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for index, token in enumerate(tokens):
        kind = control_kind(token)
        if kind is not None:
            controls.append(
                {
                    "token_index": index,
                    "raw": f"{token:04X}",
                    "kind": kind,
                }
            )
    return controls


def unit_payload(allbin: bytes, unit_index: int) -> bytes:
    profile = UNIT_PROFILES[unit_index]
    start = int(profile["file_offset"])
    size = int(profile["byte_size"])
    payload = allbin[start : start + size]
    if len(payload) != size:
        raise ValueError(f"ALLBIN unit {unit_index} is truncated")
    if sha256_bytes(payload) != profile["sha256"]:
        raise ValueError(f"ALLBIN unit {unit_index} hash differs")
    return payload


def make_entry(
    *,
    unit_index: int,
    unit_data: bytes,
    start: int,
    end: int,
    tokens: list[int],
    glyphs: dict[int, str],
    entry_id: str,
    classification: str,
    consumer: dict[str, Any],
    layout_rows: int,
    layout_columns: int = 17,
    fixed_control_offsets: bool = False,
    runtime_auto_wrap: bool = False,
) -> dict[str, Any]:
    profile = UNIT_PROFILES[unit_index]
    raw = unit_data[start:end]
    controls = control_records(tokens)
    return {
        "entry_id": entry_id,
        "classification": classification,
        "source": {
            "container": "ALLBIN.BIN",
            "unit_index": unit_index,
            "file_offset": f"0x{int(profile['file_offset']) + start:X}",
            "unit_offset": f"0x{start:05X}",
            "runtime_pointer": (
                f"0x{int(profile['runtime_base']) + start:08X}"
            ),
            "byte_size": len(raw),
            "sha256": sha256_bytes(raw),
            "terminal": (
                f"{tokens[-1]:04X}"
                if tokens[-1] in TERMINALS
                or 0xD000 <= tokens[-1] <= 0xDFFF
                else None
            ),
        },
        "consumer": consumer,
        "original": {
            "raw_hex": raw.hex().upper(),
            "tokens": [f"{token:04X}" for token in tokens],
            "control_tokens": controls,
            "display_text": decode_visible_text(tokens, glyphs),
        },
        "layout": {
            "columns": layout_columns,
            "rows": layout_rows,
            "capacity_positions": layout_columns * layout_rows,
            "fixed_control_offsets": fixed_control_offsets,
            "runtime_auto_wrap": runtime_auto_wrap,
        },
    }


def extract_u38_rule_labels(
    unit_data: bytes,
    glyphs: dict[int, str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for start, name, classification in U38_RULE_LABELS:
        tokens, end = parse_tokens(
            unit_data,
            start,
            glyphs=glyphs,
            terminal=0xFFFF,
        )
        entries.append(
            make_entry(
                unit_index=38,
                unit_data=unit_data,
                start=start,
                end=end,
                tokens=tokens,
                glyphs=glyphs,
                entry_id=f"disc1/allbin/u38/rule_label/{name}",
                classification=classification,
                consumer={
                    "kind": "fixed_rule_page_label",
                    "consumer_validation": (
                        "pcsx-redux-runtime-vram-and-static-range-cross-check"
                    ),
                },
                layout_rows=1,
                layout_columns=13,
            )
        )
    if len(entries) != EXPECTED_U38_RULE_LABEL_COUNT:
        raise AssertionError("u38 rule-label population changed")
    return entries


def scan_u38_pointer_pages(
    unit_data: bytes,
    glyphs: dict[int, str],
) -> list[dict[str, Any]]:
    references_by_target: dict[int, list[int]] = defaultdict(list)
    runtime_base = int(UNIT_PROFILES[38]["runtime_base"])
    for storage in range(0, len(unit_data) - 3, 4):
        pointer = struct.unpack_from("<I", unit_data, storage)[0]
        target = pointer - runtime_base
        if not U38_POINTER_TARGET_MIN <= target < U38_POINTER_TARGET_MAX_EXCLUSIVE:
            continue
        try:
            parse_tokens(unit_data, target, glyphs=glyphs)
        except ValueError:
            continue
        references_by_target[target].append(storage)

    if len(references_by_target) != EXPECTED_U38_POINTER_PAGE_COUNT:
        raise ValueError(
            "u38 pointer-page population changed: "
            f"{len(references_by_target)} != {EXPECTED_U38_POINTER_PAGE_COUNT}"
        )
    if any(len(references) != 1 for references in references_by_target.values()):
        raise ValueError("u38 pointer-page reference multiplicity changed")

    pages: list[dict[str, Any]] = []
    ranges: list[tuple[int, int]] = []
    for ordinal, (start, references) in enumerate(
        sorted(references_by_target.items())
    ):
        tokens, end = parse_tokens(unit_data, start, glyphs=glyphs)
        if any(start < other_end and end > other_start for other_start, other_end in ranges):
            raise ValueError(f"overlapping u38 pointer page at 0x{start:X}")
        ranges.append((start, end))
        if start < 0x18C28:
            classification = "minigame_rule_page"
            rows = min(
                4,
                max(3, decode_visible_text(tokens, glyphs).count("\n") + 1),
            )
        elif start < 0x1CE34:
            classification = "minigame_blackjack_dialogue"
            rows = 3
        elif start < 0x1D84C:
            classification = "minigame_camera_dialogue"
            rows = 3
        else:
            classification = "minigame_cooking_dialogue"
            rows = 3
        pages.append(
            make_entry(
                unit_index=38,
                unit_data=unit_data,
                start=start,
                end=end,
                tokens=tokens,
                glyphs=glyphs,
                entry_id=(
                    f"disc1/allbin/u38/minigame_page/ref{ordinal:04d}"
                ),
                classification=classification,
                consumer={
                    "kind": "event_pointer",
                    "pointer_reference_unit_offsets": [
                        f"0x{storage:05X}" for storage in references
                    ],
                    "consumer_validation": "ida-ghidra-static-cross-check",
                },
                layout_rows=rows,
                layout_columns=(13 if classification == "minigame_rule_page" else 17),
            )
        )
    return pages


def extract_u38_direct_entries(
    unit_data: bytes,
    glyphs: dict[int, str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for start, name, fixed_end in U38_DIRECT_DIALOGUE:
        tokens, end = parse_tokens(
            unit_data,
            start,
            glyphs=glyphs,
            end_exclusive=fixed_end,
        )
        classification = (
            "minigame_cooking_dialogue"
            if start >= 0x1D84C
            else (
                "minigame_camera_dialogue"
                if start >= 0x1CE34
                else (
                    "minigame_blackjack_dialogue"
                    if start >= 0x18C28
                    else "minigame_rule_page"
                )
            )
        )
        rows = (
            min(
                4,
                max(3, decode_visible_text(tokens, glyphs).count("\n") + 1),
            )
            if classification == "minigame_rule_page"
            else 3
        )
        entries.append(
            make_entry(
                unit_index=38,
                unit_data=unit_data,
                start=start,
                end=end,
                tokens=tokens,
                glyphs=glyphs,
                entry_id=f"disc1/allbin/u38/direct/{name}",
                classification=classification,
                consumer={
                    "kind": (
                        "direct_renderer_fragment"
                        if fixed_end is not None
                        else "direct_renderer_string"
                    ),
                    "consumer_validation": "ida-ghidra-static-cross-check",
                    "continues_at": (
                        f"0x{fixed_end:05X}" if fixed_end is not None else None
                    ),
                },
                layout_rows=rows,
                layout_columns=(13 if classification == "minigame_rule_page" else 17),
            )
        )

    if len(entries) != EXPECTED_U38_DIRECT_DIALOGUE_COUNT:
        raise AssertionError("u38 direct-dialogue population changed")

    for start, name in U38_COOKING_WORDS:
        tokens, end = parse_tokens(
            unit_data,
            start,
            glyphs=glyphs,
            terminal=0xFFFF,
        )
        entries.append(
            make_entry(
                unit_index=38,
                unit_data=unit_data,
                start=start,
                end=end,
                tokens=tokens,
                glyphs=glyphs,
                entry_id=f"disc1/allbin/u38/cooking_word/{name}",
                classification="minigame_cooking_runtime_word",
                consumer={
                    "kind": "runtime_selected_string",
                    "consumer_validation": "ida-ghidra-static-cross-check",
                },
                layout_rows=1,
            )
        )
    if (
        sum(
            entry["classification"] == "minigame_cooking_runtime_word"
            for entry in entries
        )
        != EXPECTED_U38_COOKING_WORD_COUNT
    ):
        raise AssertionError("u38 cooking-word population changed")
    return entries


def extract_u43_course(
    unit_data: bytes,
    glyphs: dict[int, str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_targets: set[int] = set()
    ordinal = 0
    runtime_base = int(UNIT_PROFILES[43]["runtime_base"])
    for table_index, table in enumerate(COURSE_POINTER_TABLES):
        table_offset = int(table["table_offset"])
        for page_index in range(int(table["pointer_count"])):
            storage = table_offset + page_index * 4
            pointer = struct.unpack_from("<I", unit_data, storage)[0]
            start = pointer - runtime_base
            if not 0x2D40 <= start < 0x3E32:
                raise ValueError(
                    f"u43 course pointer target out of range: 0x{pointer:08X}"
                )
            if start in seen_targets:
                raise ValueError(f"duplicate u43 course target 0x{start:X}")
            seen_targets.add(start)
            tokens, end = parse_tokens(
                unit_data,
                start,
                glyphs=glyphs,
                terminal=0x8000,
            )
            entries.append(
                make_entry(
                    unit_index=43,
                    unit_data=unit_data,
                    start=start,
                    end=end,
                    tokens=tokens,
                    glyphs=glyphs,
                    entry_id=(
                        f"disc1/allbin/u43/course_page/ref{ordinal:04d}"
                    ),
                    classification="course_information_dialogue",
                    consumer={
                        "kind": "course_state_pointer_table",
                        "table_index": table_index,
                        "table_unit_offset": f"0x{table_offset:04X}",
                        "page_index": page_index,
                        "states": table["states"],
                        "pointer_reference_unit_offset": f"0x{storage:04X}",
                        "consumer_validation": "ida-ghidra-static-cross-check",
                    },
                    layout_rows=3,
                )
            )
            ordinal += 1
    if len(entries) != EXPECTED_COURSE_PAGE_COUNT:
        raise ValueError(
            f"u43 course population changed: {len(entries)} "
            f"!= {EXPECTED_COURSE_PAGE_COUNT}"
        )
    return entries


def extract_u43_machine(
    unit_data: bytes,
    glyphs: dict[int, str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for start, name in MACHINE_SETTING_STARTS:
        tokens, end = parse_tokens(
            unit_data,
            start,
            glyphs=glyphs,
            terminal=0xFFFF,
        )
        entries.append(
            make_entry(
                unit_index=43,
                unit_data=unit_data,
                start=start,
                end=end,
                tokens=tokens,
                glyphs=glyphs,
                entry_id=f"disc1/allbin/u43/machine_setting/{name}",
                classification="machine_setting_dialogue",
                consumer={
                    "kind": "direct_code_address",
                    "consumer_validation": "ida-ghidra-static-cross-check",
                },
                layout_rows=3,
            )
        )
    if len(entries) != EXPECTED_MACHINE_SETTING_COUNT:
        raise AssertionError("u43 machine-setting population changed")
    return entries


def extract_u43_garage_action_menus(
    unit_data: bytes,
    glyphs: dict[int, str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for start, name in GARAGE_ACTION_MENU_STARTS:
        tokens, end = parse_tokens(
            unit_data,
            start,
            glyphs=glyphs,
            terminal=0xD003,
        )
        entries.append(
            make_entry(
                unit_index=43,
                unit_data=unit_data,
                start=start,
                end=end,
                tokens=tokens,
                glyphs=glyphs,
                entry_id=f"disc1/allbin/u43/garage_action_menu/{name}",
                classification="garage_action_menu",
                consumer={
                    "kind": "runtime_selected_fixed_action_menu",
                    "consumer_validation": (
                        "pcsx-redux-runtime-address-and-screen-cross-check"
                    ),
                },
                layout_rows=3,
            )
        )
    if len(entries) != EXPECTED_GARAGE_ACTION_MENU_COUNT:
        raise AssertionError("u43 garage-action-menu population changed")
    return entries


def extract_u43_machine_sequential(
    unit_data: bytes,
    glyphs: dict[int, str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for start, end, name, rows in U43_MACHINE_SEQUENTIAL_SLOTS:
        tokens, parsed_end = parse_tokens(
            unit_data,
            start,
            glyphs=glyphs,
            end_exclusive=end,
        )
        if parsed_end != end:
            raise AssertionError("u43 sequential slot boundary changed")
        classification = (
            "machine_setting_confirmation_choice"
            if name == "confirm_choice"
            else "machine_setting_sequential_dialogue"
        )
        entries.append(
            make_entry(
                unit_index=43,
                unit_data=unit_data,
                start=start,
                end=end,
                tokens=tokens,
                glyphs=glyphs,
                entry_id=(
                    f"disc1/allbin/u43/machine_setting_sequence/{name}"
                ),
                classification=classification,
                consumer={
                    "kind": "pointerless-sequential-machine-setting-slot",
                    "consumer_validation": (
                        "adjacent-control-stream-static-cross-check; "
                        "runtime-path-review-required"
                    ),
                    "fixed_control_offsets": True,
                },
                layout_rows=rows,
                fixed_control_offsets=True,
                runtime_auto_wrap=True,
            )
        )
    if len(entries) != EXPECTED_U43_MACHINE_SEQUENTIAL_COUNT:
        raise AssertionError("u43 sequential machine population changed")
    return entries


def extract_special_screen_text(
    *,
    allbin_path: Path,
    glyph_map_path: Path,
) -> dict[str, Any]:
    allbin = allbin_path.read_bytes()
    if sha256_bytes(allbin) != EXPECTED_ALLBIN_SHA256:
        raise ValueError("ALLBIN.BIN hash differs from the verified original")
    glyph_map = load_object(glyph_map_path)
    source_glyphs = (
        glyph_map.get("tables", {}).get("primary", {}).get("glyphs")
    )
    if not isinstance(source_glyphs, dict):
        raise ValueError("primary glyph map is missing")
    glyphs = {int(index, 16): character for index, character in source_glyphs.items()}

    u38 = unit_payload(allbin, 38)
    u43 = unit_payload(allbin, 43)
    entries = [
        *scan_u38_pointer_pages(u38, glyphs),
        *extract_u38_direct_entries(u38, glyphs),
        *extract_u43_course(u43, glyphs),
        *extract_u43_machine(u43, glyphs),
        *extract_u43_garage_action_menus(u43, glyphs),
        # Append newly discovered entries so historical translation batches
        # keep their stable order and remain mergeable.
        *extract_u38_rule_labels(u38, glyphs),
        *extract_u43_machine_sequential(u43, glyphs),
    ]
    ids = [entry["entry_id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("special-screen entry IDs are not unique")
    ranges_by_unit: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    for entry in entries:
        unit_index = int(entry["source"]["unit_index"])
        start = int(entry["source"]["unit_offset"], 16)
        end = start + int(entry["source"]["byte_size"])
        for other_start, other_end, other_id in ranges_by_unit[unit_index]:
            if start < other_end and end > other_start:
                raise ValueError(
                    f"overlapping physical entries: {entry['entry_id']} and "
                    f"{other_id}"
                )
        ranges_by_unit[unit_index].append((start, end, entry["entry_id"]))

    counts: dict[str, int] = defaultdict(int)
    for entry in entries:
        counts[entry["classification"]] += 1
    return {
        "schema_version": 1,
        "status": "verified-original-special-screen-text-workset",
        "baseline_id": BASELINE_ID,
        "scope": {
            "included": [
                "u38 font-rendered mini-game dialogue and runtime words",
                "u38 font-rendered mini-game rule heading and titles",
                "u43 font-rendered Course Information dialogue",
                "u43 font-rendered Machine Setting dialogue",
                "u43 font-rendered garage action menus",
                "u43 pointerless machine-setting dialogue and choices",
            ],
            "excluded": [
                "baked graphical buttons",
                "baked graphical labels and title assets",
            ],
            "source_allbin": str(allbin_path.resolve()),
            "source_allbin_sha256": EXPECTED_ALLBIN_SHA256,
            "glyph_map": str(glyph_map_path.resolve()),
            "glyph_map_sha256": sha256_bytes(glyph_map_path.read_bytes()),
            "consumer_validation": {
                "ida": [
                    "work/ida/ALLBIN-unit38.psx.i64",
                    "work/ida/ALLBIN-unit43.psx.i64",
                ],
                "ghidra_script": (
                    "scripts/ghidra/AnalyzeSpecialScreenText.java"
                ),
                "status": "static-cross-check-complete",
            },
        },
        "summary": {
            "entry_count": len(entries),
            "u38_pointer_page_count": EXPECTED_U38_POINTER_PAGE_COUNT,
            "u38_rule_label_count": EXPECTED_U38_RULE_LABEL_COUNT,
            "u38_direct_dialogue_count": EXPECTED_U38_DIRECT_DIALOGUE_COUNT,
            "u38_cooking_runtime_word_count": EXPECTED_U38_COOKING_WORD_COUNT,
            "u43_course_page_count": EXPECTED_COURSE_PAGE_COUNT,
            "u43_machine_setting_count": EXPECTED_MACHINE_SETTING_COUNT,
            "u43_garage_action_menu_count": (
                EXPECTED_GARAGE_ACTION_MENU_COUNT
            ),
            "u43_machine_sequential_count": (
                EXPECTED_U43_MACHINE_SEQUENTIAL_COUNT
            ),
            "classification_counts": dict(sorted(counts.items())),
        },
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allbin",
        type=Path,
        default=Path("work/extracted/disc1/iso/ALLBIN.BIN"),
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
            "work/translations/disc1-special-screen-text.json"
        ),
    )
    args = parser.parse_args()
    document = extract_special_screen_text(
        allbin_path=args.allbin,
        glyph_map_path=args.glyph_map,
    )
    write_json(args.output, document)
    print(
        f"entries={document['summary']['entry_count']} "
        f"u38_pointer={document['summary']['u38_pointer_page_count']} "
        f"course={document['summary']['u43_course_page_count']} "
        f"machine={document['summary']['u43_machine_setting_count']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
