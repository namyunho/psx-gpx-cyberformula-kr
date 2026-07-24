#!/usr/bin/env python3
"""Inventory every proven font stream in the scheduled ALLBIN units.

Units 0..29 end with an array of in-unit runtime pointers followed by an entry
count and zero sector padding.  Units 30..34 are mixed code/data race overlays:
their event records contain aligned in-unit pointers to terminal-valid font
streams.  Unit 40 contains a separately proven set of UI streams referenced by
code.  The script inventories those three evidence classes and never promotes
an unpointed byte sequence to dialogue.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

try:
    from scripts.psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule
except ModuleNotFoundError:  # Direct execution from the repository root.
    from psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule


ALLBIN_TEXT_UNIT_END = 30
EMBEDDED_RACE_UNIT_START = 30
EMBEDDED_RACE_UNIT_END = 35
EMBEDDED_RACE_LOAD_ADDRESS = 0x800AC000
EMBEDDED_RACE_MAX_STREAM_BYTES = 0x1000
OVERLAY_UI_UNIT = 40
OVERLAY_UI_LOAD_ADDRESS = 0x80098000
OVERLAY_UI_ENTRY_OFFSETS = (
    0x6ABC,
    0x6AE4,
    0x6B10,
    0x6B2C,
    0x6B60,
    0x6B8C,
    0x6C2C,
    0x6C54,
    0x6CF0,
    0x6D20,
    0x6D84,
    0x6E24,
    0x6E50,
    0x6EA0,
    0x6F40,
    0x6FE0,
    0x703C,
    0x7064,
    0x70E0,
    0x712C,
    0x7184,
    0x71CC,
    0x71F0,
    0x7234,
    0x72AC,
    0x72C8,
    0x72E0,
    0x72F0,
    0x7300,
    0x736C,
    0x73B4,
    0x73F4,
    0x7418,
    0x7470,
    0x749C,
    0x74B8,
    0x74CC,
    0x74DC,
    0x74F4,
    0x750C,
    0x7530,
    0x7554,
    0x756C,
    0x75B8,
    0x75C0,
    0x75E8,
    0x7604,
    0x7610,
    0x7684,
    0x76A0,
    0x7734,
    0x7774,
    0x7808,
    0x784C,
    0x78A4,
    0x7920,
    0x7938,
    0x7960,
    0x796C,
    0x7978,
)


@dataclass(frozen=True)
class TextSubsystem:
    name: str
    unit_start: int
    unit_end: int
    load_address: int
    terminal_tokens: tuple[int, ...]


TEXT_SUBSYSTEMS = (
    TextSubsystem(
        "event_page",
        0,
        21,
        0x800A8000,
        (0x8000,),
    ),
    TextSubsystem(
        "voice_event",
        21,
        30,
        0x800AC000,
        (0xFFFF, 0xD003),
    ),
)

EMBEDDED_RACE_ALLOWED_TOKEN_KINDS = frozenset(
    {
        "glyph",
        "substitution",
        "speaker_or_style",
        "audio_cue",
        "voice_or_transition",
        "align",
        "pace",
        "stream_end",
    }
)


def subsystem_for_unit(unit_index: int) -> TextSubsystem:
    for subsystem in TEXT_SUBSYSTEMS:
        if subsystem.unit_start <= unit_index < subsystem.unit_end:
            return subsystem
    raise ValueError(f"unit {unit_index} is outside the covered text subsystem")


def last_nonzero_u32_offset(unit: bytes) -> int:
    if len(unit) % 4:
        raise ValueError("scheduled ALLBIN unit is not 4-byte aligned")
    for offset in range(len(unit) - 4, -1, -4):
        if struct.unpack_from("<I", unit, offset)[0] != 0:
            return offset
    raise ValueError("unit contains no nonzero u32")


def discover_pointer_table(
    unit: bytes,
    *,
    load_address: int,
) -> dict[str, Any]:
    """Prove the trailing ``pointer[count]`` plus ``count`` layout."""

    count_offset = last_nonzero_u32_offset(unit)
    entry_count = struct.unpack_from("<I", unit, count_offset)[0]
    if entry_count == 0 or entry_count > 4096:
        raise ValueError(f"implausible pointer count: {entry_count}")
    table_offset = count_offset - 4 * entry_count
    if table_offset < 0:
        raise ValueError("pointer table starts before the unit")
    if any(unit[count_offset + 4 :]):
        raise ValueError("nonzero bytes follow pointer-table count")

    pointers = list(
        struct.unpack_from(f"<{entry_count}I", unit, table_offset)
    )
    unit_end = load_address + len(unit)
    invalid = [
        pointer
        for pointer in pointers
        if not load_address <= pointer < unit_end or pointer % 2
    ]
    if invalid:
        raise ValueError(
            f"{len(invalid)} pointers are outside the loaded unit or unaligned"
        )
    return {
        "table_offset": table_offset,
        "count_offset": count_offset,
        "entry_count": entry_count,
        "pointers": pointers,
    }


def token_kind(token: int) -> str:
    if token < 0x4000:
        return "glyph"
    if token < 0x8000:
        return "substitution"
    if token == 0x8000:
        return "page_boundary"
    if token == 0xFFFF:
        return "stream_end"
    if token == 0xFFFB:
        return "align"
    if token == 0xFFFC:
        return "pause"
    if token == 0xFFFD:
        return "pace"
    if token == 0xFFFE:
        return "reserved_fffe"
    return {
        0x8: "control_8",
        0x9: "speaker_or_style",
        0xA: "style_off",
        0xB: "control_b",
        0xC: "delay",
        0xD: "voice_or_transition",
        0xE: "audio_cue",
        0xF: "control_f_other",
    }[token >> 12]


def parse_entry(
    unit: bytes,
    *,
    pointer: int,
    load_address: int,
    limit_offset: int,
    terminals: tuple[int, ...],
) -> dict[str, Any]:
    start = pointer - load_address
    if start < 0 or start >= limit_offset or start % 2 or limit_offset % 2:
        raise ValueError(f"invalid text entry bounds at 0x{pointer:08X}")
    tokens: list[int] = []
    terminal = None
    for offset in range(start, limit_offset, 2):
        token = struct.unpack_from("<H", unit, offset)[0]
        tokens.append(token)
        if token in terminals:
            terminal = token
            break
    if terminal is None:
        raise ValueError(
            f"text entry at 0x{pointer:08X} has no terminal before "
            f"unit offset 0x{limit_offset:X}"
        )

    kinds = Counter(token_kind(token) for token in tokens)
    glyph_indices = [token & 0xFFF for token in tokens if token < 0x4000]
    speaker_block_indices = [
        (token & 0x0FC0) >> 6
        for token in tokens
        if token >> 12 == 0x9
    ]
    speaker_style_indices = [
        token & 0x003F
        for token in tokens
        if token >> 12 == 0x9
    ]
    encoded = struct.pack(f"<{len(tokens)}H", *tokens)
    return {
        "pointer": pointer,
        "unit_offset": start,
        "byte_size": len(encoded),
        "end_offset": start + len(encoded),
        "terminal": terminal,
        "token_count": len(tokens),
        "glyph_count": len(glyph_indices),
        "glyph_index_min": min(glyph_indices) if glyph_indices else None,
        "glyph_index_max": max(glyph_indices) if glyph_indices else None,
        "token_kinds": dict(sorted(kinds.items())),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "_glyph_indices": glyph_indices,
        "_speaker_block_indices": speaker_block_indices,
        "_speaker_style_indices": speaker_style_indices,
    }


def inventory_text_unit(
    unit: bytes,
    *,
    unit_index: int,
    file_offset: int,
) -> dict[str, Any]:
    subsystem = subsystem_for_unit(unit_index)
    table = discover_pointer_table(unit, load_address=subsystem.load_address)
    pointer_counts = Counter(table["pointers"])
    unique_pointers = sorted(pointer_counts)
    entries = []
    for index, pointer in enumerate(unique_pointers):
        next_offset = (
            unique_pointers[index + 1] - subsystem.load_address
            if index + 1 < len(unique_pointers)
            else table["table_offset"]
        )
        entry = parse_entry(
            unit,
            pointer=pointer,
            load_address=subsystem.load_address,
            limit_offset=next_offset,
            terminals=subsystem.terminal_tokens,
        )
        entry["reference_count"] = pointer_counts[pointer]
        entry["file_offset"] = file_offset + entry["unit_offset"]
        entries.append(entry)

    aggregate_kinds: Counter[str] = Counter()
    terminals: Counter[int] = Counter()
    glyph_indices: Counter[int] = Counter()
    speaker_block_indices: Counter[int] = Counter()
    speaker_style_indices: Counter[int] = Counter()
    for entry in entries:
        aggregate_kinds.update(entry["token_kinds"])
        terminals[entry["terminal"]] += 1
        glyph_indices.update(entry.pop("_glyph_indices"))
        speaker_block_indices.update(entry.pop("_speaker_block_indices"))
        speaker_style_indices.update(entry.pop("_speaker_style_indices"))
    return {
        "unit_index": unit_index,
        "subsystem": subsystem.name,
        "file_offset": file_offset,
        "byte_size": len(unit),
        "load_address": subsystem.load_address,
        "pointer_table_offset": table["table_offset"],
        "pointer_table_count_offset": table["count_offset"],
        "pointer_reference_count": table["entry_count"],
        "unique_entry_point_count": len(entries),
        "duplicate_reference_count": table["entry_count"] - len(entries),
        "terminal_counts": {
            f"0x{token:04X}": count for token, count in sorted(terminals.items())
        },
        "token_kind_counts": dict(sorted(aggregate_kinds.items())),
        "speaker_block_index_counts": {
            str(index): count
            for index, count in sorted(speaker_block_indices.items())
        },
        "speaker_style_index_counts": {
            str(index): count
            for index, count in sorted(speaker_style_indices.items())
        },
        "_glyph_index_counts": dict(glyph_indices),
        "entries": entries,
    }


def aligned_in_unit_pointer_references(
    unit: bytes,
    *,
    load_address: int,
) -> dict[int, list[int]]:
    """Return every aligned u32 reference to an even address in this unit."""

    references: dict[int, list[int]] = {}
    unit_end = load_address + len(unit)
    for offset in range(0, len(unit) - 3, 4):
        pointer = struct.unpack_from("<I", unit, offset)[0]
        if load_address <= pointer < unit_end and pointer % 2 == 0:
            references.setdefault(pointer, []).append(offset)
    return references


def looks_like_u32_value_table(tokens: list[int]) -> bool:
    """Reject u32 tables whose zero high halves mimic a short u16 stream.

    The mixed overlays contain one shared table at unit offset ``0x8280``.
    Read as u16 it eventually encounters ``0x9A00, 0xFFFF`` by accident, but
    its first 32-bit values all have zero high halves.  Real font streams do
    not exhibit that alternating-zero prefix.
    """

    sample = tokens[: min(16, max(0, len(tokens) - 1))]
    odd_halfwords = sample[1::2]
    return (
        len(odd_halfwords) >= 4
        and sum(token == 0 for token in odd_halfwords) / len(odd_halfwords)
        >= 0.75
    )


def inventory_embedded_race_text_unit(
    unit: bytes,
    *,
    unit_index: int,
    file_offset: int,
) -> dict[str, Any]:
    """Inventory pointer-backed font streams inside ALLBIN units 30..34."""

    references = aligned_in_unit_pointer_references(
        unit,
        load_address=EMBEDDED_RACE_LOAD_ADDRESS,
    )
    entries = []
    rejected_u32_value_table_count = 0
    for pointer, reference_offsets in sorted(references.items()):
        start = pointer - EMBEDDED_RACE_LOAD_ADDRESS
        limit = min(len(unit), start + EMBEDDED_RACE_MAX_STREAM_BYTES)
        try:
            entry = parse_entry(
                unit,
                pointer=pointer,
                load_address=EMBEDDED_RACE_LOAD_ADDRESS,
                limit_offset=limit,
                terminals=(0xFFFF, 0xD003),
            )
        except ValueError:
            continue

        if not set(entry["token_kinds"]) <= EMBEDDED_RACE_ALLOWED_TOKEN_KINDS:
            continue
        encoded = unit[start : entry["end_offset"]]
        tokens = list(struct.unpack(f"<{len(encoded) // 2}H", encoded))
        if not any(token >= 0x8000 for token in tokens[:-1]):
            continue
        if looks_like_u32_value_table(tokens):
            rejected_u32_value_table_count += 1
            continue

        entry["reference_count"] = len(reference_offsets)
        entry["reference_unit_offsets"] = reference_offsets
        entry["file_offset"] = file_offset + start
        entries.append(entry)

    aggregate_kinds: Counter[str] = Counter()
    terminals: Counter[int] = Counter()
    glyph_indices: Counter[int] = Counter()
    speaker_block_indices: Counter[int] = Counter()
    speaker_style_indices: Counter[int] = Counter()
    for entry in entries:
        aggregate_kinds.update(entry["token_kinds"])
        terminals[entry["terminal"]] += 1
        glyph_indices.update(entry.pop("_glyph_indices"))
        speaker_block_indices.update(entry.pop("_speaker_block_indices"))
        speaker_style_indices.update(entry.pop("_speaker_style_indices"))

    return {
        "unit_index": unit_index,
        "subsystem": "embedded_race_overlay_text",
        "file_offset": file_offset,
        "byte_size": len(unit),
        "load_address": EMBEDDED_RACE_LOAD_ADDRESS,
        "pointer_reference_count": sum(
            entry["reference_count"] for entry in entries
        ),
        "unique_entry_point_count": len(entries),
        "rejected_u32_value_table_count": rejected_u32_value_table_count,
        "terminal_counts": {
            f"0x{token:04X}": count for token, count in sorted(terminals.items())
        },
        "token_kind_counts": dict(sorted(aggregate_kinds.items())),
        "speaker_block_index_counts": {
            str(index): count
            for index, count in sorted(speaker_block_indices.items())
        },
        "speaker_style_index_counts": {
            str(index): count
            for index, count in sorted(speaker_style_indices.items())
        },
        "_glyph_index_counts": dict(glyph_indices),
        "entries": entries,
    }


def overlay_ui_reference_proof(unit_offset: int) -> str:
    if unit_offset < 0x7610:
        return "ALLBIN40 overlay code has a direct data xref to this stream"
    if unit_offset < 0x7960:
        return "main sub_8003BEA4 passes this fixed address to sub_8003907C"
    if unit_offset < 0x7978:
        return (
            "main and ALLBIN40 code pass this fixed address to the text path"
        )
    return (
        "main fills this mutable stream and ALLBIN40 code consumes the same "
        "address through the text path"
    )


def inventory_overlay_ui(unit: bytes, *, file_offset: int) -> dict[str, Any]:
    entries = []
    glyph_indices: Counter[int] = Counter()
    aggregate_kinds: Counter[str] = Counter()
    for index, unit_offset in enumerate(OVERLAY_UI_ENTRY_OFFSETS):
        next_offset = (
            OVERLAY_UI_ENTRY_OFFSETS[index + 1]
            if index + 1 < len(OVERLAY_UI_ENTRY_OFFSETS)
            else 0x7994
        )
        entry = parse_entry(
            unit,
            pointer=OVERLAY_UI_LOAD_ADDRESS + unit_offset,
            load_address=OVERLAY_UI_LOAD_ADDRESS,
            limit_offset=next_offset,
            terminals=(0xFFFF,),
        )
        entry["file_offset"] = file_offset + unit_offset
        entry["reference_proof"] = overlay_ui_reference_proof(unit_offset)
        glyph_indices.update(entry.pop("_glyph_indices"))
        entry.pop("_speaker_block_indices")
        entry.pop("_speaker_style_indices")
        aggregate_kinds.update(entry["token_kinds"])
        entries.append(entry)
    return {
        "unit_index": OVERLAY_UI_UNIT,
        "subsystem": "font_rendered_ui",
        "file_offset": file_offset,
        "byte_size": len(unit),
        "load_address": OVERLAY_UI_LOAD_ADDRESS,
        "entry_count": len(entries),
        "glyph_index_min": min(glyph_indices),
        "glyph_index_max": max(glyph_indices),
        "unique_glyph_index_count": len(glyph_indices),
        "token_kind_counts": dict(sorted(aggregate_kinds.items())),
        "glyph_index_counts": {
            f"0x{index:03X}": count
            for index, count in sorted(glyph_indices.items())
        },
        "entries": entries,
    }


def build_text_inventory(exe_path: Path, allbin_path: Path) -> dict[str, Any]:
    exe = PsxExe(exe_path.read_bytes())
    allbin = allbin_path.read_bytes()
    spec = next(spec for spec in SCHEDULE_SPECS if spec.filename == "ALLBIN.BIN")
    schedule = discover_schedule(
        exe,
        spec.table_va,
        spec.table_limit_va,
        len(allbin),
    )

    units = []
    for span in schedule[:ALLBIN_TEXT_UNIT_END]:
        start = span["byte_offset"]
        units.append(
            inventory_text_unit(
                allbin[start : span["byte_end"]],
                unit_index=span["index"],
                file_offset=start,
            )
        )

    embedded_race_units = []
    for span in schedule[EMBEDDED_RACE_UNIT_START:EMBEDDED_RACE_UNIT_END]:
        start = span["byte_offset"]
        embedded_race_units.append(
            inventory_embedded_race_text_unit(
                allbin[start : span["byte_end"]],
                unit_index=span["index"],
                file_offset=start,
            )
        )

    overlay_span = schedule[OVERLAY_UI_UNIT]
    overlay_start = overlay_span["byte_offset"]
    overlay_ui = inventory_overlay_ui(
        allbin[overlay_start : overlay_span["byte_end"]],
        file_offset=overlay_start,
    )

    pointer_reference_count = sum(
        unit["pointer_reference_count"] for unit in units
    )
    unique_entry_point_count = sum(
        unit["unique_entry_point_count"] for unit in units
    )
    aggregate_kinds: Counter[str] = Counter()
    aggregate_terminals: Counter[str] = Counter()
    content_hashes: Counter[str] = Counter()
    glyph_indices: Counter[int] = Counter()
    for unit in units:
        aggregate_kinds.update(unit["token_kind_counts"])
        aggregate_terminals.update(unit["terminal_counts"])
        content_hashes.update(entry["sha256"] for entry in unit["entries"])
        glyph_indices.update(unit.pop("_glyph_index_counts"))

    embedded_reference_count = sum(
        unit["pointer_reference_count"] for unit in embedded_race_units
    )
    embedded_entry_count = sum(
        unit["unique_entry_point_count"] for unit in embedded_race_units
    )
    all_content_hashes = content_hashes.copy()
    all_glyph_indices = glyph_indices.copy()
    for unit in embedded_race_units:
        all_content_hashes.update(entry["sha256"] for entry in unit["entries"])
        all_glyph_indices.update(unit.pop("_glyph_index_counts"))
    all_content_hashes.update(entry["sha256"] for entry in overlay_ui["entries"])
    all_glyph_indices.update(
        {
            int(index, 16): count
            for index, count in overlay_ui["glyph_index_counts"].items()
        }
    )

    return {
        "schema_version": 1,
        "method": {
            "covered_allbin_units": [0, ALLBIN_TEXT_UNIT_END - 1],
            "embedded_race_allbin_units": [
                EMBEDDED_RACE_UNIT_START,
                EMBEDDED_RACE_UNIT_END - 1,
            ],
            "pointer_table_proof": (
                "last nonzero aligned u32 is count; preceding count u32 values "
                "are aligned pointers inside the unit's runtime mapping; all "
                "following bytes are zero padding"
            ),
            "entry_proof": (
                "every distinct pointer reaches its subsystem terminal before "
                "the next pointer or pointer table"
            ),
            "scope_boundary": (
                "ALLBIN units 35..39 and 41..43 and unpointed bytes are not "
                "classified as dialogue; units 30..34 mixed-overlay streams "
                "and unit 40 UI streams are reported separately from the "
                "trailing-pointer-table dialogue counts"
            ),
            "embedded_race_proof": (
                "every units 30..34 entry has one or more aligned in-unit u32 "
                "references, uses only the established race-message token "
                "grammar, and reaches FFFF or D003 within 0x1000 bytes; the "
                "shared alternating-zero u32 value table is explicitly "
                "rejected"
            ),
            "overlay_ui_proof": (
                "60 FFFD..FFFF streams in ALLBIN unit 40 are covered by direct "
                "IDA xrefs from the overlay, fixed main-EXE renderer calls, or "
                "the proven mutable renderer buffer"
            ),
        },
        "source": {
            "exe": str(exe_path),
            "allbin": str(allbin_path),
            "allbin_sha256": hashlib.sha256(allbin).hexdigest(),
        },
        "summary": {
            "unit_count": len(units),
            "pointer_table_unit_count": len(units),
            "pointer_reference_count": pointer_reference_count,
            "unique_entry_point_count": unique_entry_point_count,
            "duplicate_reference_count": (
                pointer_reference_count - unique_entry_point_count
            ),
            "unique_encoded_content_count": len(content_hashes),
            "duplicate_encoded_content_count": (
                unique_entry_point_count - len(content_hashes)
            ),
            "glyph_index_min": min(glyph_indices),
            "glyph_index_max": max(glyph_indices),
            "unique_glyph_index_count": len(glyph_indices),
            "terminal_counts": dict(sorted(aggregate_terminals.items())),
            "token_kind_counts": dict(sorted(aggregate_kinds.items())),
            "font_rendered_ui_entry_count": overlay_ui["entry_count"],
            "embedded_race_unit_count": len(embedded_race_units),
            "embedded_race_pointer_reference_count": embedded_reference_count,
            "embedded_race_unique_entry_point_count": embedded_entry_count,
            "all_font_stream_entry_count": (
                unique_entry_point_count
                + embedded_entry_count
                + overlay_ui["entry_count"]
            ),
            "all_font_stream_unique_encoded_content_count": len(
                all_content_hashes
            ),
            "all_font_stream_duplicate_encoded_content_count": (
                unique_entry_point_count
                + embedded_entry_count
                + overlay_ui["entry_count"]
                - len(all_content_hashes)
            ),
            "all_font_stream_glyph_index_min": min(all_glyph_indices),
            "all_font_stream_glyph_index_max": max(all_glyph_indices),
            "all_font_stream_unique_glyph_index_count": len(all_glyph_indices),
        },
        "glyph_index_counts": {
            f"0x{index:03X}": count for index, count in sorted(glyph_indices.items())
        },
        "overlay_ui": overlay_ui,
        "embedded_race_units": embedded_race_units,
        "units": units,
    }


def report_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": report["schema_version"],
        "method": report["method"],
        "source": report["source"],
        "summary": report["summary"],
        "overlay_ui": {
            key: value
            for key, value in report["overlay_ui"].items()
            if key != "entries"
        },
        "embedded_race_units": [
            {key: value for key, value in unit.items() if key != "entries"}
            for unit in report["embedded_race_units"]
        ],
        "units": [
            {key: value for key, value in unit.items() if key != "entries"}
            for unit in report["units"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--disc-root",
        type=Path,
        default=Path("work/disc1/full"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    report = build_text_inventory(
        args.disc_root / "SLPS_019.58",
        args.disc_root / "ALLBIN.BIN",
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
