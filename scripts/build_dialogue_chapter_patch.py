#!/usr/bin/env python3
"""Build non-release Korean dialogue files for selected ALLBIN story units.

The primary font mapping is global and deterministic across every candidate
entry, while the ALLBIN repack can be limited to one or more independently
loaded story units.  Unselected units are not compatible with the replaced
font and must not be treated as playable content in a partial build.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Iterable

try:
    from scripts.korean_font import (
        crop_to_psx,
        load_font_profile,
        rasterize_ttf_glyph,
    )
    from scripts.psx_font import GLYPH_SIZE, pack_glyph
except ModuleNotFoundError:
    from korean_font import crop_to_psx, load_font_profile, rasterize_ttf_glyph
    from psx_font import GLYPH_SIZE, pack_glyph


EXPECTED_START_SHA256 = (
    "d0b22efb4e5ea46c869f822af9bc7f207bc95a670a25acb15fc3dcd2ab3bf8cc"
)
EXPECTED_ALLBIN_SHA256 = (
    "6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e"
)
FONT_OFFSET = 0x1A000
FONT_GLYPH_COUNT = 0x4CD
# These slots are part of the original symbols/digits/Latin region, plus the
# trailing non-Japanese ν/heart symbols. They are never Hangul allocation
# targets, even when a particular character is unused by the translated
# corpus.
PROTECTED_ORIGINAL_GLYPH_RANGES = (
    (0x000, 0x046),
    (0x0E4, 0x0E6),
)
PROTECTED_ORIGINAL_GLYPH_INDICES = frozenset(
    index
    for start, end in PROTECTED_ORIGINAL_GLYPH_RANGES
    for index in range(start, end)
)
FIXED_NAMES = {
    "{name:surname}": "시바",
    "{name:given}": "세이치로",
}
NAME_PATTERN = re.compile(r"\{name:(?:surname|given)\}")
CONTROL_CONTENT_KINDS = {"glyph", "name_surname", "name_given"}
REMOVABLE_INTERNAL_KINDS = {"align", "name_surname", "name_given"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


def changed_ranges(before: bytes, after: bytes) -> list[tuple[int, int]]:
    if len(before) != len(after):
        raise ValueError("expected-write comparison requires equal file sizes")
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, (source, target) in enumerate(zip(before, after)):
        if source != target and start is None:
            start = index
        elif source == target and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(before)))
    return ranges


def merge_allowed_ranges(
    ranges: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if start < 0 or end <= start:
            raise ValueError(f"invalid expected-write range 0x{start:X}:0x{end:X}")
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def verify_expected_writes(
    before: bytes,
    after: bytes,
    *,
    allowed_ranges: Iterable[tuple[int, int]],
    owner: str,
) -> dict[str, Any]:
    allowed = merge_allowed_ranges(allowed_ranges)
    changes = changed_ranges(before, after)
    allowed_index = 0
    for start, end in changes:
        while (
            allowed_index < len(allowed)
            and allowed[allowed_index][1] <= start
        ):
            allowed_index += 1
        if (
            allowed_index == len(allowed)
            or start < allowed[allowed_index][0]
            or end > allowed[allowed_index][1]
        ):
            raise ValueError(
                f"{owner}: unexplained write 0x{start:X}:0x{end:X}"
            )
    return {
        "owner": owner,
        "source_size": len(before),
        "output_size": len(after),
        "changed_byte_count": sum(end - start for start, end in changes),
        "changed_range_count": len(changes),
        "changed_ranges": [
            {
                "start": f"0x{start:X}",
                "end_exclusive": f"0x{end:X}",
                "bytes": end - start,
            }
            for start, end in changes
        ],
        "allowed_ranges": [
            {
                "start": f"0x{start:X}",
                "end_exclusive": f"0x{end:X}",
                "bytes": end - start,
            }
            for start, end in allowed
        ],
        "verified": True,
    }


def expand_fixed_names(text: str) -> str:
    for token, replacement in FIXED_NAMES.items():
        text = text.replace(token, replacement)
    if NAME_PATTERN.search(text):
        raise ValueError(f"unknown name placeholder remains: {text!r}")
    return text


def required_characters(overlay: dict[str, Any]) -> list[str]:
    entries = overlay.get("entries")
    if not isinstance(entries, list):
        raise ValueError("reflow overlay entries must be an array")
    characters: set[str] = set()
    for entry in entries:
        texts = [
            entry.get("ko_reflowed"),
            entry.get("ko_candidate"),
        ]
        text = next((value for value in texts if isinstance(value, str)), None)
        if text is None:
            raise ValueError(f"{entry.get('id')}: no Korean candidate text")
        text = expand_fixed_names(text)
        characters.update(character for character in text if not character.isspace())
        if any(character.isspace() for character in text):
            characters.add(" ")
    return sorted(characters, key=ord)


def load_primary_glyph_map(path: Path) -> dict[str, int]:
    document = load_object(path)
    table = document.get("tables", {}).get("primary")
    if not isinstance(table, dict) or table.get("glyph_count") != FONT_GLYPH_COUNT:
        raise ValueError("primary glyph map has an unexpected size")
    glyphs = table.get("glyphs")
    if not isinstance(glyphs, dict):
        raise ValueError("primary glyph map requires a glyph object")
    result: dict[str, int] = {}
    for index_hex, character in glyphs.items():
        if not isinstance(character, str) or not character:
            raise ValueError(f"invalid primary glyph at {index_hex}")
        result.setdefault(character, int(index_hex, 16))
    return result


def build_static_font(
    source_start: bytes,
    overlay: dict[str, Any],
    *,
    glyph_map_path: Path,
    font_profile_path: Path,
    passthrough_original_glyph_indices: Iterable[int] = (),
) -> tuple[bytes, dict[str, int], dict[str, Any]]:
    font_end = FONT_OFFSET + FONT_GLYPH_COUNT * GLYPH_SIZE
    if font_end > len(source_start):
        raise ValueError("primary font region exceeds START.BIN")

    passthrough_indices = frozenset(passthrough_original_glyph_indices)
    invalid_passthrough = sorted(
        index
        for index in passthrough_indices
        if not 0 <= index < FONT_GLYPH_COUNT
    )
    if invalid_passthrough:
        raise ValueError(
            "passthrough original glyph index is outside the primary font: "
            + ", ".join(f"0x{index:X}" for index in invalid_passthrough)
        )
    byte_exact_indices = (
        PROTECTED_ORIGINAL_GLYPH_INDICES | passthrough_indices
    )

    required = required_characters(overlay)
    original_map = load_primary_glyph_map(glyph_map_path)
    mapping: dict[str, int] = {}
    occupied = set(byte_exact_indices)

    # Preserve exact game glyphs for punctuation, Latin, digits, icons, and
    # renderer-special controller symbols whenever the original table has one.
    for character in required:
        if character in original_map:
            index = original_map[character]
            if index in mapping.values():
                raise ValueError(f"duplicate selected glyph index 0x{index:03X}")
            mapping[character] = index
            occupied.add(index)

    free_indices = (
        index
        for index in range(FONT_GLYPH_COUNT)
        if index not in occupied
    )
    for character in required:
        if character not in mapping:
            try:
                mapping[character] = next(free_indices)
            except StopIteration as error:
                raise ValueError(
                    f"primary font capacity exceeded at {character!r}"
                ) from error

    profile = load_font_profile(font_profile_path)
    from PIL import ImageFont

    ttf = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    records = bytearray(FONT_GLYPH_COUNT * GLYPH_SIZE)
    for index in byte_exact_indices:
        source = FONT_OFFSET + index * GLYPH_SIZE
        target = index * GLYPH_SIZE
        records[target : target + GLYPH_SIZE] = source_start[
            source : source + GLYPH_SIZE
        ]
    generated: list[str] = []
    preserved: list[str] = []
    for character, index in sorted(mapping.items(), key=lambda item: item[1]):
        target = index * GLYPH_SIZE
        if character in original_map:
            source_index = original_map[character]
            source = FONT_OFFSET + source_index * GLYPH_SIZE
            records[target : target + GLYPH_SIZE] = source_start[
                source : source + GLYPH_SIZE
            ]
            preserved.append(character)
            continue
        if character == " ":
            generated.append(character)
            continue
        pixels = rasterize_ttf_glyph(
            ttf,
            character,
            x_offset=profile.x_offset_px,
            y_offset=profile.y_offset_px,
        )
        retained = crop_to_psx(pixels, intensity=profile.intensity)
        if not any(retained):
            raise ValueError(
                f"Galmuri11 produced an empty retained glyph for {character!r}"
            )
        records[target : target + GLYPH_SIZE] = pack_glyph(retained)
        generated.append(character)

    patched = bytearray(source_start)
    patched[FONT_OFFSET:font_end] = records
    protected_changed = [
        index
        for index in sorted(byte_exact_indices)
        if patched[
            FONT_OFFSET + index * GLYPH_SIZE :
            FONT_OFFSET + (index + 1) * GLYPH_SIZE
        ]
        != source_start[
            FONT_OFFSET + index * GLYPH_SIZE :
            FONT_OFFSET + (index + 1) * GLYPH_SIZE
        ]
    ]
    if protected_changed:
        changed = ", ".join(f"0x{index:03X}" for index in protected_changed)
        raise ValueError(f"protected original glyph records changed: {changed}")
    report = {
        "font_offset": f"0x{FONT_OFFSET:X}",
        "glyph_count": FONT_GLYPH_COUNT,
        "record_bytes": GLYPH_SIZE,
        "required_character_count": len(required),
        "mapped_character_count": len(mapping),
        "preserved_original_character_count": len(preserved),
        "generated_galmuri11_character_count": len(generated),
        "unused_slot_count": FONT_GLYPH_COUNT - len(
            set(mapping.values()) | byte_exact_indices
        ),
        "protected_original_glyph_ranges": [
            {
                "start": f"0x{start:03X}",
                "end_exclusive": f"0x{end:03X}",
                "glyph_count": end - start,
            }
            for start, end in PROTECTED_ORIGINAL_GLYPH_RANGES
        ],
        "protected_original_glyph_count": len(
            PROTECTED_ORIGINAL_GLYPH_INDICES
        ),
        "protected_original_glyphs_byte_exact": True,
        "passthrough_original_glyph_count": len(passthrough_indices),
        "passthrough_original_glyph_indices": [
            f"0x{index:03X}" for index in sorted(passthrough_indices)
        ],
        "passthrough_original_glyphs_byte_exact": True,
        "total_byte_exact_original_glyph_count": len(byte_exact_indices),
        "fixed_name_expansion": FIXED_NAMES,
    }
    return bytes(patched), mapping, report


def split_control_shell(entry: dict[str, Any]) -> tuple[list[int], list[int]]:
    tokens = [int(value, 16) for value in entry["original"]["tokens"]]
    controls = {
        int(control["token_index"]): str(control["kind"])
        for control in entry["original"]["control_tokens"]
    }
    content_indices = [
        index
        for index in range(len(tokens))
        if controls.get(index, "glyph") in CONTROL_CONTENT_KINDS
    ]
    if not content_indices:
        raise ValueError(f"{entry['entry_id']}: source has no display content")
    first = min(content_indices)
    last = max(content_indices)

    leading = tokens[:first]
    trailing = tokens[last + 1 :]
    if any(index not in controls for index in range(first)):
        raise ValueError(f"{entry['entry_id']}: leading shell contains a glyph")
    if any(index not in controls for index in range(last + 1, len(tokens))):
        raise ValueError(f"{entry['entry_id']}: trailing shell contains a glyph")

    for index in range(first, last + 1):
        kind = controls.get(index)
        if kind is not None and kind not in REMOVABLE_INTERNAL_KINDS:
            raise ValueError(
                f"{entry['entry_id']}: internal control {kind!r} cannot move"
            )
    return leading, trailing


def encode_entry(
    source_entry: dict[str, Any],
    reflowed_text: str,
    mapping: dict[str, int],
) -> bytes:
    leading, trailing = split_control_shell(source_entry)
    text = expand_fixed_names(reflowed_text)
    lines = text.split("\n")
    if not 1 <= len(lines) <= 3:
        raise ValueError(f"{source_entry['entry_id']}: invalid reflow row count")
    if any(len(line) > 17 for line in lines):
        raise ValueError(f"{source_entry['entry_id']}: reflow line exceeds 17")

    body: list[int] = []
    for line_index, line in enumerate(lines):
        if line_index:
            body.append(0xFFFB)
        for character in line:
            if character not in mapping:
                raise ValueError(
                    f"{source_entry['entry_id']}: unmapped {character!r}"
                )
            body.append(mapping[character])
    tokens = [*leading, *body, *trailing]
    if any(not 0 <= token <= 0xFFFF for token in tokens):
        raise ValueError(f"{source_entry['entry_id']}: token out of range")
    return struct.pack(f"<{len(tokens)}H", *tokens)


def fit_fixed_diagnostic_candidate(
    source_entry: dict[str, Any],
    candidate_text: str,
) -> tuple[str, dict[str, Any] | None]:
    """Keep candidate glyphs exact, moving only invalid explicit line breaks.

    The diagnostic mode intentionally tests original text addresses rather
    than a release layout. Most candidate line breaks are therefore retained
    exactly. If an imported candidate itself exceeds the verified 17x3 frame,
    flatten only its newline controls and hard-wrap the unchanged visible
    glyph sequence. This is the previously approved word-split fallback, and
    is reported so it cannot be mistaken for reviewed final typography.
    """
    expanded = expand_fixed_names(candidate_text)
    lines = expanded.split("\n")
    if 1 <= len(lines) <= 3 and all(len(line) <= 17 for line in lines):
        return expanded, None

    visible = expanded.replace("\n", "")
    if not 1 <= len(visible) <= 51:
        raise ValueError(
            f"{source_entry['entry_id']}: diagnostic candidate requires "
            f"{len(visible)} glyphs; fixed frame capacity is 51"
        )
    adjusted = "\n".join(
        visible[index : index + 17]
        for index in range(0, len(visible), 17)
    )
    return adjusted, {
        "entry_id": source_entry["entry_id"],
        "reason": "candidate-explicit-line-exceeds-17",
        "policy": "flatten-newlines-and-hard-wrap-unchanged-glyph-sequence",
        "candidate_line_widths": [len(line) for line in lines],
        "output_line_widths": [
            len(line) for line in adjusted.split("\n")
        ],
        "visible_glyph_sequence_preserved": True,
    }


def physical_entry_ranges(
    entries: Iterable[dict[str, Any]],
) -> list[tuple[int, int, dict[str, Any]]]:
    ranges = []
    ordered = sorted(
        entries,
        key=lambda entry: int(entry["source"]["unit_offset"], 16),
    )
    for entry in ordered:
        start = int(entry["source"]["unit_offset"], 16)
        end = start + int(entry["source"]["byte_size"])
        if ranges and start < ranges[-1][1]:
            raise ValueError(f"{entry['entry_id']}: source text ranges overlap")
        ranges.append((start, end, entry))
    return ranges


def build_source_ordered_stream(
    unit_data: bytes,
    entries: Iterable[dict[str, Any]],
    streams: dict[str, bytes],
) -> dict[str, Any]:
    """Repack one physical text run without changing any fall-through edge.

    The renderer advances a cursor after 0x8000 and can consume the following
    bytes without loading the next pointer-table entry.  Consequently, a
    size-based allocator is invalid even when every rewritten pointer is
    correct.  Preserve the source order and copy every inter-entry byte
    verbatim; these gaps include alignment words and pointerless continuation
    pages used by choices and multi-page exposition.
    """
    ranges = physical_entry_ranges(entries)
    if not ranges:
        raise ValueError("cannot build an empty physical text stream")

    region_start = ranges[0][0]
    region_end = ranges[-1][1]
    if region_end > len(unit_data):
        raise ValueError("physical text stream exceeds its source unit")

    output = bytearray()
    placements: dict[str, int] = {}
    gaps: list[dict[str, Any]] = []
    cursor = region_start
    previous_entry_id: str | None = None
    for start, end, entry in ranges:
        entry_id = entry["entry_id"]
        if entry_id not in streams:
            raise ValueError(f"{entry_id}: encoded stream is missing")
        gap = unit_data[cursor:start]
        if len(gap) % 2:
            raise ValueError(
                f"{entry_id}: inter-entry gap has an odd byte size"
            )
        output_gap_start = region_start + len(output)
        output.extend(gap)
        gaps.append(
            {
                "after_entry_id": previous_entry_id,
                "before_entry_id": entry_id,
                "source_start": cursor,
                "source_end": start,
                "output_start": output_gap_start,
                "byte_size": len(gap),
                "nonzero_byte_count": sum(byte != 0 for byte in gap),
                "page_end_count": sum(
                    struct.unpack_from("<H", gap, index)[0] == 0x8000
                    for index in range(0, len(gap), 2)
                ),
                "raw": gap,
            }
        )
        placements[entry_id] = region_start + len(output)
        output.extend(streams[entry_id])
        cursor = end
        previous_entry_id = entry_id

    capacity = region_end - region_start
    if len(output) > capacity:
        raise ValueError(
            f"source-ordered text requires {len(output)} bytes but "
            f"the original physical run has {capacity}"
        )
    return {
        "region_start": region_start,
        "region_end": region_end,
        "capacity": capacity,
        "stream": bytes(output),
        "placements": placements,
        "gaps": gaps,
        "physical_entry_ids": [
            entry["entry_id"] for _, _, entry in ranges
        ],
    }


def passthrough_gap_glyph_indices(
    allbin: bytes,
    entries_by_unit: dict[int, list[dict[str, Any]]],
) -> frozenset[int]:
    indices: set[int] = set()
    for entries in entries_by_unit.values():
        ranges = physical_entry_ranges(entries)
        unit_file_offsets = {
            int(entry["source"]["file_offset"], 16)
            - int(entry["source"]["unit_offset"], 16)
            for _, _, entry in ranges
        }
        if len(unit_file_offsets) != 1:
            raise ValueError("inconsistent source unit file offset")
        unit_file_offset = unit_file_offsets.pop()
        cursor = ranges[0][0]
        for start, end, _ in ranges:
            gap = allbin[
                unit_file_offset + cursor : unit_file_offset + start
            ]
            if len(gap) % 2:
                raise ValueError("inter-entry gap has an odd byte size")
            for index in range(0, len(gap), 2):
                token = struct.unpack_from("<H", gap, index)[0]
                if token < 0x4000:
                    indices.add(token)
            cursor = end
    return frozenset(indices)


def repack_unit(
    allbin: bytearray,
    entries: list[dict[str, Any]],
    reflow_by_id: dict[str, dict[str, Any]],
    mapping: dict[str, int],
) -> dict[str, Any]:
    if not entries:
        raise ValueError("cannot repack an empty unit")
    unit_index = int(entries[0]["source"]["unit_index"])
    if any(int(entry["source"]["unit_index"]) != unit_index for entry in entries):
        raise ValueError("repack_unit received mixed units")
    if not 0 <= unit_index <= 20:
        raise ValueError(
            f"unit {unit_index}: chapter repacker currently supports story 0..20"
        )

    for entry in entries:
        offset = int(entry["source"]["file_offset"], 16)
        raw = bytes.fromhex(entry["original"]["raw_hex"])
        if allbin[offset : offset + len(raw)] != raw:
            raise ValueError(f"{entry['entry_id']}: source ALLBIN bytes differ")

    streams: dict[str, bytes] = {}
    for entry in entries:
        derived = reflow_by_id[entry["entry_id"]]
        if derived.get("status") != "ready":
            raise ValueError(
                f"{entry['entry_id']}: reinsertion blocker "
                f"{derived.get('status')}"
            )
        text = derived.get("ko_reflowed")
        if not isinstance(text, str):
            raise ValueError(f"{entry['entry_id']}: missing reflowed text")
        streams[entry["entry_id"]] = encode_entry(entry, text, mapping)

    unit_file_offset = min(
        int(entry["source"]["file_offset"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for entry in entries
    )
    unit_data = bytes(
        allbin[
            unit_file_offset :
            unit_file_offset
            + max(
                int(entry["source"]["unit_offset"], 16)
                + int(entry["source"]["byte_size"])
                for entry in entries
            )
        ]
    )
    layout = build_source_ordered_stream(unit_data, entries, streams)
    placements = layout["placements"]
    entry_point = min(
        entries,
        key=lambda entry: int(entry["source"]["unit_offset"], 16),
    )
    entry_point_offset = int(entry_point["source"]["unit_offset"], 16)
    load_addresses = {
        int(entry["source"]["runtime_pointer"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for entry in entries
    }
    if len(load_addresses) != 1:
        raise ValueError(f"unit {unit_index}: inconsistent runtime load address")
    load_address = load_addresses.pop()

    region_start = int(layout["region_start"])
    region_end = int(layout["region_end"])
    packed_stream = bytes(layout["stream"])
    allbin[
        unit_file_offset + region_start :
        unit_file_offset + region_end
    ] = bytes(region_end - region_start)
    allbin[
        unit_file_offset + region_start :
        unit_file_offset + region_start + len(packed_stream)
    ] = packed_stream
    pointer_write_count = 0
    pointer_storages: set[int] = set()
    for entry in entries:
        entry_id = entry["entry_id"]
        unit_offset = placements[entry_id]
        stream = streams[entry_id]
        absolute = unit_file_offset + unit_offset
        allbin[absolute : absolute + len(stream)] = stream
        pointer = load_address + unit_offset
        for reference in entry["source"]["pointer_references"]:
            storage = int(reference["storage_file_offset"], 16)
            if storage in pointer_storages:
                raise ValueError(
                    f"{entry_id}: duplicate pointer storage 0x{storage:X}"
                )
            pointer_storages.add(storage)
            expected = int(reference["raw_value"], 16)
            actual = struct.unpack_from("<I", allbin, storage)[0]
            if actual != expected:
                raise ValueError(
                    f"{entry_id}: pointer source differs at 0x{storage:X}"
                )
            struct.pack_into("<I", allbin, storage, pointer)
            pointer_write_count += 1

    verified_pointer_count = 0
    for entry in entries:
        entry_id = entry["entry_id"]
        unit_offset = placements[entry_id]
        stream = streams[entry_id]
        absolute = unit_file_offset + unit_offset
        if allbin[absolute : absolute + len(stream)] != stream:
            raise ValueError(f"{entry_id}: encoded stream verification failed")
        expected_pointer = load_address + unit_offset
        for reference in entry["source"]["pointer_references"]:
            storage = int(reference["storage_file_offset"], 16)
            actual_pointer = struct.unpack_from("<I", allbin, storage)[0]
            if actual_pointer != expected_pointer:
                raise ValueError(
                    f"{entry_id}: rewritten pointer identity differs at "
                    f"0x{storage:X}"
                )
            verified_pointer_count += 1

    physical_ids = list(layout["physical_entry_ids"])
    gap_by_edge = {
        (gap["after_entry_id"], gap["before_entry_id"]): gap
        for gap in layout["gaps"]
        if gap["after_entry_id"] is not None
    }
    fallthrough_edge_count = 0
    for previous_id, next_id in zip(physical_ids, physical_ids[1:]):
        gap = gap_by_edge[(previous_id, next_id)]
        expected_next = (
            placements[previous_id]
            + len(streams[previous_id])
            + int(gap["byte_size"])
        )
        if placements[next_id] != expected_next:
            raise ValueError(
                f"{next_id}: physical fall-through edge was split after "
                f"{previous_id}"
            )
        output_gap_start = (
            unit_file_offset
            + placements[previous_id]
            + len(streams[previous_id])
        )
        raw_gap = bytes(gap["raw"])
        if allbin[
            output_gap_start : output_gap_start + len(raw_gap)
        ] != raw_gap:
            raise ValueError(
                f"{next_id}: physical fall-through gap changed after "
                f"{previous_id}"
            )
        fallthrough_edge_count += 1

    entry_point_stream = streams[entry_point["entry_id"]]
    entry_point_absolute = unit_file_offset + entry_point_offset
    entry_point_verified = (
        placements[entry_point["entry_id"]] == entry_point_offset
        and allbin[
            entry_point_absolute :
            entry_point_absolute + len(entry_point_stream)
        ]
        == entry_point_stream
    )
    if not entry_point_verified:
        raise ValueError(
            f"{entry_point['entry_id']}: fixed entry point was not preserved"
        )

    return {
        "unit_index": unit_index,
        "unit_file_offset": f"0x{unit_file_offset:X}",
        "entry_count": len(entries),
        "original_text_bytes": sum(
            int(entry["source"]["byte_size"]) for entry in entries
        ),
        "encoded_text_bytes": sum(len(stream) for stream in streams.values()),
        "physical_region_start": f"0x{region_start:04X}",
        "physical_region_end_exclusive": f"0x{region_end:04X}",
        "physical_region_capacity_bytes": int(layout["capacity"]),
        "packed_physical_stream_bytes": len(packed_stream),
        "physical_region_spare_bytes": (
            int(layout["capacity"]) - len(packed_stream)
        ),
        "pointer_write_count": pointer_write_count,
        "stable_id_stream_verification_count": len(entries),
        "pointer_identity_verification_count": verified_pointer_count,
        "physical_entry_count": len(physical_ids),
        "physical_fallthrough_edge_verification_count": (
            fallthrough_edge_count
        ),
        "inter_entry_gap_count": len(layout["gaps"]) - 1,
        "inter_entry_gap_bytes": sum(
            int(gap["byte_size"])
            for gap in layout["gaps"]
            if gap["after_entry_id"] is not None
        ),
        "pointerless_page_count": sum(
            int(gap["page_end_count"]) for gap in layout["gaps"]
        ),
        "fixed_entry_point": {
            "entry_id": entry_point["entry_id"],
            "unit_offset": f"0x{entry_point_offset:04X}",
            "encoded_bytes": len(entry_point_stream),
            "preserved": True,
        },
        "runtime_load_address": f"0x{load_address:08X}",
        "physical_entries": [
            {
                "entry_id": entry_id,
                "source_unit_offset": next(
                    entry["source"]["unit_offset"]
                    for entry in entries
                    if entry["entry_id"] == entry_id
                ),
                "output_unit_offset": f"0x{placements[entry_id]:04X}",
                "encoded_bytes": len(streams[entry_id]),
            }
            for entry_id in physical_ids
        ],
        "inter_entry_gaps": [
            {
                "after_entry_id": gap["after_entry_id"],
                "before_entry_id": gap["before_entry_id"],
                "source_unit_start": f"0x{gap['source_start']:04X}",
                "source_unit_end_exclusive": f"0x{gap['source_end']:04X}",
                "output_unit_start": f"0x{gap['output_start']:04X}",
                "bytes": gap["byte_size"],
                "nonzero_byte_count": gap["nonzero_byte_count"],
                "pointerless_page_count": gap["page_end_count"],
                "sha256": sha256_bytes(bytes(gap["raw"])),
            }
            for gap in layout["gaps"]
            if gap["after_entry_id"] is not None
        ],
    }


def write_unit_at_original_offsets_diagnostic(
    allbin: bytearray,
    entries: list[dict[str, Any]],
    reflow_by_id: dict[str, dict[str, Any]],
    mapping: dict[str, int],
) -> dict[str, Any]:
    """Write complete translated streams at immutable original entry starts.

    This deliberately permits a stream to overwrite the following entry or a
    pointerless fall-through page. Writes run from high to low addresses so
    the earlier dialogue remains complete and the first real slot overflow is
    observable at the following entry. It is a runtime diagnostic, never a
    release-capable placement policy.
    """
    if not entries:
        raise ValueError("cannot write an empty unit")
    unit_index = int(entries[0]["source"]["unit_index"])
    if any(int(entry["source"]["unit_index"]) != unit_index for entry in entries):
        raise ValueError("fixed diagnostic received mixed units")
    if not 0 <= unit_index <= 21:
        raise ValueError(
            f"unit {unit_index}: fixed diagnostic supports units 0..21"
        )

    ranges = physical_entry_ranges(entries)
    unit_file_offsets = {
        int(entry["source"]["file_offset"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for _, _, entry in ranges
    }
    if len(unit_file_offsets) != 1:
        raise ValueError(f"unit {unit_index}: inconsistent file offset")
    unit_file_offset = unit_file_offsets.pop()

    for _, _, entry in ranges:
        offset = int(entry["source"]["file_offset"], 16)
        raw = bytes.fromhex(entry["original"]["raw_hex"])
        if allbin[offset : offset + len(raw)] != raw:
            raise ValueError(f"{entry['entry_id']}: source ALLBIN bytes differ")

    streams: dict[str, bytes] = {}
    layout_adjustments: list[dict[str, Any]] = []
    for _, _, entry in ranges:
        entry_id = entry["entry_id"]
        derived = reflow_by_id[entry_id]
        text = derived.get("ko_candidate")
        if not isinstance(text, str):
            raise ValueError(f"{entry_id}: missing original Korean candidate")
        fitted_text, adjustment = fit_fixed_diagnostic_candidate(entry, text)
        if adjustment is not None:
            layout_adjustments.append(adjustment)
        streams[entry_id] = encode_entry(entry, fitted_text, mapping)

    original_unit = bytes(
        allbin[unit_file_offset : unit_file_offset + ranges[-1][1]]
    )
    conflicts: list[dict[str, Any]] = []
    for index, (start, end, entry) in enumerate(ranges):
        entry_id = entry["entry_id"]
        if index + 1 < len(ranges):
            next_start, _, next_entry = ranges[index + 1]
            gap = original_unit[end:next_start]
            if any(gap):
                capacity_end = end
                conflict_target = "pointerless-fallthrough-gap"
            else:
                capacity_end = next_start
                conflict_target = next_entry["entry_id"]
        else:
            capacity_end = end
            conflict_target = "after-last-entry"
        encoded_end = start + len(streams[entry_id])
        if encoded_end > capacity_end:
            conflicts.append(
                {
                    "entry_id": entry_id,
                    "original_unit_offset": f"0x{start:04X}",
                    "encoded_end_exclusive": f"0x{encoded_end:04X}",
                    "safe_end_exclusive": f"0x{capacity_end:04X}",
                    "encoded_bytes": len(streams[entry_id]),
                    "safe_bytes": capacity_end - start,
                    "overflow_bytes": encoded_end - capacity_end,
                    "overflow_glyph_tokens": (
                        encoded_end - capacity_end + 1
                    ) // 2,
                    "conflict_target": conflict_target,
                }
            )

    # Earlier physical dialogue owns an overlap. This keeps the first
    # overflowing translation complete so runtime testing stops at the actual
    # next-entry damage instead of silently truncating the owner.
    for start, _, entry in reversed(ranges):
        stream = streams[entry["entry_id"]]
        absolute = unit_file_offset + start
        allbin[absolute : absolute + len(stream)] = stream

    pointer_verification_count = 0
    for _, _, entry in ranges:
        for reference in entry["source"]["pointer_references"]:
            storage = int(reference["storage_file_offset"], 16)
            expected = int(reference["raw_value"], 16)
            actual = struct.unpack_from("<I", allbin, storage)[0]
            if actual != expected:
                raise ValueError(
                    f"{entry['entry_id']}: fixed diagnostic changed pointer "
                    f"at 0x{storage:X}"
                )
            pointer_verification_count += 1

    intact_entries = []
    corrupted_entries = []
    for start, _, entry in ranges:
        entry_id = entry["entry_id"]
        stream = streams[entry_id]
        absolute = unit_file_offset + start
        actual = bytes(allbin[absolute : absolute + len(stream)])
        record = {
            "entry_id": entry_id,
            "unit_offset": f"0x{start:04X}",
            "encoded_bytes": len(stream),
        }
        if actual == stream:
            intact_entries.append(record)
        else:
            leading, _ = split_control_shell(entry)
            changed_token_indices = [
                token_index
                for token_index in range(len(stream) // 2)
                if actual[token_index * 2 : token_index * 2 + 2]
                != stream[token_index * 2 : token_index * 2 + 2]
            ]
            control_kind_by_index = {
                int(control["token_index"]): str(control["kind"])
                for control in entry["original"]["control_tokens"]
            }
            corrupted_leading_controls = [
                {
                    "token_index": token_index,
                    "kind": control_kind_by_index.get(
                        token_index,
                        "unknown-control",
                    ),
                    "expected": f"0x{struct.unpack_from('<H', stream, token_index * 2)[0]:04X}",
                    "actual": f"0x{struct.unpack_from('<H', actual, token_index * 2)[0]:04X}",
                }
                for token_index in changed_token_indices
                if token_index < len(leading)
            ]
            corrupted_entries.append(
                {
                    **record,
                    "changed_token_count": len(changed_token_indices),
                    "first_changed_token_index": (
                        min(changed_token_indices)
                        if changed_token_indices
                        else None
                    ),
                    "leading_control_token_count": len(leading),
                    "corrupted_leading_control_count": len(
                        corrupted_leading_controls
                    ),
                    "corrupted_leading_controls": (
                        corrupted_leading_controls
                    ),
                    "portrait_or_audio_control_corrupted": any(
                        control["kind"] in {"speaker_style", "audio"}
                        for control in corrupted_leading_controls
                    ),
                }
            )

    changed_gap_count = 0
    for (_, left_end, _), (right_start, _, _) in zip(ranges, ranges[1:]):
        original_gap = original_unit[left_end:right_start]
        output_gap = bytes(
            allbin[
                unit_file_offset + left_end :
                unit_file_offset + right_start
            ]
        )
        if output_gap != original_gap:
            changed_gap_count += 1

    region_start = ranges[0][0]
    write_end = max(
        start + len(streams[entry["entry_id"]])
        for start, _, entry in ranges
    )
    return {
        "unit_index": unit_index,
        "unit_file_offset": f"0x{unit_file_offset:X}",
        "entry_count": len(ranges),
        "placement_policy": "fixed-original-offset-diagnostic",
        "translation_input_field": "ko_candidate",
        "layout_adjustment_count": len(layout_adjustments),
        "layout_adjustments": layout_adjustments,
        "write_precedence": "lower-source-offset-wins-overlap",
        "pointer_write_count": 0,
        "pointer_identity_verification_count": pointer_verification_count,
        "original_region_start": f"0x{region_start:04X}",
        "original_region_end_exclusive": f"0x{ranges[-1][1]:04X}",
        "diagnostic_write_end_exclusive": f"0x{write_end:04X}",
        "encoded_text_bytes": sum(len(value) for value in streams.values()),
        "slot_overflow_count": len(conflicts),
        "slot_overflows": conflicts,
        "first_slot_overflow": conflicts[0] if conflicts else None,
        "intact_entry_count": len(intact_entries),
        "corrupted_by_overlap_entry_count": len(corrupted_entries),
        "corrupted_by_overlap_entries": corrupted_entries,
        "corrupted_portrait_or_audio_entry_count": sum(
            bool(entry["portrait_or_audio_control_corrupted"])
            for entry in corrupted_entries
        ),
        "changed_inter_entry_gap_count": changed_gap_count,
        "entries": intact_entries,
        "warning": (
            "Diagnostic only: complete translations stay at original starts; "
            "earlier overlong streams intentionally corrupt later content."
        ),
    }


def parse_units(values: list[str], all_story: bool) -> list[int]:
    units: set[int] = set(range(21)) if all_story else set()
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                units.add(int(part, 0))
    if not units:
        raise ValueError("select --unit or --all-story")
    if any(unit < 0 or unit > 21 for unit in units):
        raise ValueError(
            "chapter builder currently supports story units 0..20 and "
            "general-race unit 21"
        )
    return sorted(units)


def validate_stable_id_join(
    work_entries: list[dict[str, Any]],
    derived_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    work_ids = [entry["entry_id"] for entry in work_entries]
    derived_ids = [entry["id"] for entry in derived_entries]
    if len(set(work_ids)) != len(work_ids):
        raise ValueError("workset contains duplicate stable IDs")
    if len(set(derived_ids)) != len(derived_ids):
        raise ValueError("reflow overlay contains duplicate stable IDs")
    missing = sorted(set(work_ids) - set(derived_ids))
    extra = sorted(set(derived_ids) - set(work_ids))
    if missing or extra:
        raise ValueError(
            f"reflow stable ID mismatch: missing={missing} extra={extra}"
        )
    if work_ids != derived_ids:
        mismatch_index = next(
            index
            for index, (work_id, derived_id) in enumerate(
                zip(work_ids, derived_ids)
            )
            if work_id != derived_id
        )
        raise ValueError(
            "reflow overlay changed protected workset order at "
            f"{mismatch_index}: {work_ids[mismatch_index]} != "
            f"{derived_ids[mismatch_index]}"
        )
    return {
        "entry_count": len(work_ids),
        "unique_entry_count": len(set(work_ids)),
        "stable_id_set_exact": True,
        "protected_workset_order_preserved": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-bin", type=Path, required=True)
    parser.add_argument("--allbin", type=Path, required=True)
    parser.add_argument(
        "--workset",
        type=Path,
        default=Path("work/translations/disc1-dialogue.json"),
    )
    parser.add_argument(
        "--reflow-overlay",
        type=Path,
        default=Path(
            "work/translations/disc1-dialogue-ko-reflowed-nonrelease.json"
        ),
    )
    parser.add_argument(
        "--reinsertion-audit",
        type=Path,
        default=Path(
            "work/analysis/disc1-translation-reinsertion-audit.json"
        ),
    )
    parser.add_argument(
        "--glyph-map",
        type=Path,
        default=Path("data/glyph-map.json"),
    )
    parser.add_argument(
        "--font-profile",
        type=Path,
        default=Path("config/font-profile.json"),
    )
    parser.add_argument(
        "--unit",
        action="append",
        default=[],
        help="story unit number or comma-separated list; repeatable",
    )
    parser.add_argument("--all-story", action="store_true")
    parser.add_argument(
        "--placement-policy",
        choices=("source-order-repack", "fixed-original-diagnostic"),
        default="source-order-repack",
        help=(
            "Use fixed-original-diagnostic only for intentional runtime "
            "overflow localization; it permits destructive entry overlap."
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    try:
        units = parse_units(args.unit, args.all_story)
    except ValueError as error:
        parser.error(str(error))
    if 21 in units and args.placement_policy != "fixed-original-diagnostic":
        parser.error(
            "unit 21 is currently allowed only with "
            "--placement-policy fixed-original-diagnostic"
        )

    source_start = args.start_bin.read_bytes()
    source_allbin = args.allbin.read_bytes()
    if sha256_bytes(source_start) != EXPECTED_START_SHA256:
        raise ValueError("START.BIN hash differs from the verified original")
    if sha256_bytes(source_allbin) != EXPECTED_ALLBIN_SHA256:
        raise ValueError("ALLBIN.BIN hash differs from the verified original")

    workset = load_object(args.workset)
    overlay = load_object(args.reflow_overlay)
    audit = load_object(args.reinsertion_audit)
    work_entries = workset.get("entries")
    derived_entries = overlay.get("entries")
    if not isinstance(work_entries, list) or not isinstance(derived_entries, list):
        raise ValueError("workset and reflow overlay entries must be arrays")
    stable_id_join = validate_stable_id_join(work_entries, derived_entries)
    reflow_by_id = {entry["id"]: entry for entry in derived_entries}

    mismatch_ids = {
        entry["id"]
        for entry in audit["protected_structure"]["name_token_mismatches"]
    }
    selected_ids = {
        entry["entry_id"]
        for entry in work_entries
        if int(entry["source"]["unit_index"]) in units
    }
    selected_mismatches = sorted(selected_ids & mismatch_ids)
    if selected_mismatches:
        raise ValueError(
            "selected units contain protected name-token mismatches: "
            + ", ".join(selected_mismatches)
        )

    by_unit: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for entry in work_entries:
        unit_index = int(entry["source"]["unit_index"])
        if unit_index in units:
            by_unit[unit_index].append(entry)
    gap_glyph_indices = passthrough_gap_glyph_indices(
        source_allbin,
        by_unit,
    )
    patched_start, mapping, font_report = build_static_font(
        source_start,
        overlay,
        glyph_map_path=args.glyph_map,
        font_profile_path=args.font_profile,
        passthrough_original_glyph_indices=gap_glyph_indices,
    )
    patched_allbin = bytearray(source_allbin)
    unit_writer = (
        write_unit_at_original_offsets_diagnostic
        if args.placement_policy == "fixed-original-diagnostic"
        else repack_unit
    )
    unit_reports = [
        unit_writer(
            patched_allbin,
            by_unit[unit_index],
            reflow_by_id,
            mapping,
        )
        for unit_index in units
    ]
    start_expected_writes = verify_expected_writes(
        source_start,
        patched_start,
        allowed_ranges=[
            (
                FONT_OFFSET,
                FONT_OFFSET + FONT_GLYPH_COUNT * GLYPH_SIZE,
            )
        ],
        owner="primary-static-font",
    )
    allbin_allowed_ranges: list[tuple[int, int]] = []
    for unit_index in units:
        unit_entries = by_unit[unit_index]
        unit_file_offset = min(
            int(entry["source"]["file_offset"], 16)
            - int(entry["source"]["unit_offset"], 16)
            for entry in unit_entries
        )
        entry_ranges = physical_entry_ranges(unit_entries)
        report = next(
            report
            for report in unit_reports
            if int(report["unit_index"]) == unit_index
        )
        region_end = (
            int(report["diagnostic_write_end_exclusive"], 16)
            if args.placement_policy == "fixed-original-diagnostic"
            else entry_ranges[-1][1]
        )
        allbin_allowed_ranges.append(
            (
                unit_file_offset + entry_ranges[0][0],
                unit_file_offset + region_end,
            )
        )
        if args.placement_policy == "source-order-repack":
            allbin_allowed_ranges.extend(
                (
                    int(reference["storage_file_offset"], 16),
                    int(reference["storage_file_offset"], 16) + 4,
                )
                for entry in unit_entries
                for reference in entry["source"]["pointer_references"]
            )
    allbin_expected_writes = verify_expected_writes(
        source_allbin,
        bytes(patched_allbin),
        allowed_ranges=allbin_allowed_ranges,
        owner=(
            "fixed-original-offset-diagnostic-text"
            if args.placement_policy == "fixed-original-diagnostic"
            else "selected-story-unit-text-and-pointers"
        ),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    start_output = args.output_dir / "START.BIN"
    allbin_output = args.output_dir / "ALLBIN.BIN"
    map_output = args.output_dir / "primary-korean-glyph-map.json"
    manifest_output = args.output_dir / "manifest.json"
    start_output.write_bytes(patched_start)
    allbin_output.write_bytes(patched_allbin)
    write_json(
        map_output,
        {
            "schema_version": 1,
            "status": "nonrelease-candidate-corpus-static-map",
            "mapping": {
                character: f"0x{index:03X}"
                for character, index in sorted(
                    mapping.items(), key=lambda item: item[1]
                )
            },
        },
    )
    manifest = {
        "schema_version": 1,
        "status": (
            "nonrelease-fixed-original-offset-overflow-diagnostic"
            if args.placement_policy == "fixed-original-diagnostic"
            else "nonrelease-partial-chapter-build"
        ),
        "placement_policy": args.placement_policy,
        "selected_story_units": units,
        "selected_entry_count": len(selected_ids),
        "font_scope": "all-5783-candidate-corpus",
        "unselected_dialogue_font_compatible": False,
        "warning": (
            "Diagnostic only: translated streams stay at original starts and "
            "overlong earlier entries intentionally overwrite later content. "
            "Expect the first slot conflict to break subsequent dialogue."
            if args.placement_policy == "fixed-original-diagnostic"
            else (
                "Only selected units are encoded with the replaced global "
                "font. Do not test unselected dialogue in this partial build."
            )
        ),
        "sources": {
            "START.BIN": {
                "path": str(args.start_bin.resolve()),
                "sha256": sha256_bytes(source_start),
            },
            "ALLBIN.BIN": {
                "path": str(args.allbin.resolve()),
                "sha256": sha256_bytes(source_allbin),
            },
            "workset_sha256": sha256_file(args.workset),
            "reflow_overlay_sha256": sha256_file(args.reflow_overlay),
            "reinsertion_audit_sha256": sha256_file(args.reinsertion_audit),
        },
        "font": font_report,
        "stable_id_join": stable_id_join,
        "units": unit_reports,
        "expected_writes": {
            "START.BIN": start_expected_writes,
            "ALLBIN.BIN": allbin_expected_writes,
        },
        "outputs": {
            "START.BIN": {
                "path": str(start_output.resolve()),
                "size": len(patched_start),
                "sha256": sha256_bytes(patched_start),
            },
            "ALLBIN.BIN": {
                "path": str(allbin_output.resolve()),
                "size": len(patched_allbin),
                "sha256": sha256_bytes(patched_allbin),
            },
            "glyph_map": {
                "path": str(map_output.resolve()),
                "sha256": sha256_file(map_output),
            },
        },
    }
    write_json(manifest_output, manifest)
    print(
        f"units={','.join(str(unit) for unit in units)} "
        f"placement={args.placement_policy} "
        f"entries={len(selected_ids)} glyphs={len(mapping)} "
        f"START={manifest['outputs']['START.BIN']['sha256']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
