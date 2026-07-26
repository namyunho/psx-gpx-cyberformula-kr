#!/usr/bin/env python3
"""Create reversible direct-pointer Disc 1 worksets without translating text.

The extractor consumes the proven direct-pointer font-stream inventory instead
of searching for new strings. Original bytes, u16 tokens, pointer
relationships, table-scoped Japanese decoding, and story-page layout
measurements are protected fields. Full and abbreviated Korean fields are
emitted empty so another tool or reviewer can work from the same immutable
pointer-target baseline.

This is not the final physical page population. Runtime fall-through after
0x8000 reaches pointerless continuation pages; unit 0 alone has five known
pages that this extractor does not yet promote to standalone workset entries.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Iterable


EXPECTED_ALLBIN_SHA256 = (
    "6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e"
)
EXPECTED_FONT_STREAM_COUNT = 5843
EXPECTED_DIALOGUE_STREAM_COUNT = 5783
EXPECTED_UI_STREAM_COUNT = 60
DEFAULT_BATCH_SIZE = 100

STORY_COLUMNS = 17
STORY_ROWS = 3
STORY_CAPACITY = STORY_COLUMNS * STORY_ROWS
STORY_GLYPH_WIDTH = 14
STORY_GLYPH_HEIGHT = 14
STORY_ROW_STRIDE = 16
STORY_UPLOAD_WIDTH_HALFWORDS = 63
STORY_UPLOAD_WIDTH_BYTES = STORY_UPLOAD_WIDTH_HALFWORDS * 2
STORY_UPLOAD_HEIGHT = STORY_ROWS * STORY_ROW_STRIDE
STORY_WORK_BUFFER_ADDRESS = 0x8002D000
STORY_WORK_BUFFER_SIZE = 0x3000

NAME_PROFILES = {
    "original_japanese": {
        0x4000: 2,  # 司馬
        0x6000: 3,  # 誠一郎
    },
    "korean_fixed": {
        0x4000: 2,  # 시바
        0x6000: 4,  # 세이치로
    },
}

TOKEN_SPEC = {
    "glyph": {
        "range": "0000..3FFF",
        "markup": "mapped character or {glyph:XXXX}",
        "policy": "editable-through-translation",
    },
    "name_surname": {
        "code": "4000",
        "markup": "{name:surname}",
        "policy": "preserve",
    },
    "name_given": {
        "code": "6000",
        "markup": "{name:given}",
        "policy": "preserve",
    },
    "page_end": {
        "code": "8000",
        "markup": "{page_end}",
        "policy": "preserve",
    },
    "speaker_style": {
        "pattern": "9xxx",
        "markup": "{speaker_style:XXX}",
        "policy": "preserve",
    },
    "style_off": {
        "pattern": "Axxx",
        "markup": "{style_off:XXX}",
        "policy": "preserve",
    },
    "delay": {
        "pattern": "Cxxx",
        "markup": "{delay:XXX}",
        "policy": "forbidden-until-semantics-confirmed",
    },
    "voice_transition": {
        "pattern": "Dxxx",
        "markup": "{voice_transition:XXX}",
        "policy": "preserve",
    },
    "audio": {
        "pattern": "Exxx",
        "markup": "{audio:XXX}",
        "policy": "preserve",
    },
    "align": {
        "code": "FFFB",
        "markup": "{align}",
        "policy": "movable-layout-in-story-only",
    },
    "pause": {
        "code": "FFFC",
        "markup": "{pause}",
        "policy": "preserve",
    },
    "pace": {
        "code": "FFFD",
        "markup": "{pace}",
        "policy": "preserve",
    },
    "stream_end": {
        "code": "FFFF",
        "markup": "{stream_end}",
        "policy": "preserve",
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def offset_hex(value: int, *, width: int = 6) -> str:
    return f"0x{value:0{width}X}"


def address_hex(value: int) -> str:
    return f"0x{value:08X}"


def token_hex(value: int) -> str:
    return f"{value:04X}"


def tokens_from_bytes(raw: bytes) -> list[int]:
    if len(raw) % 2:
        raise ValueError("u16 token stream has an odd byte size")
    return list(struct.unpack(f"<{len(raw) // 2}H", raw))


def decode_glyph_object(glyphs: Any, *, label: str) -> dict[int, str]:
    if not isinstance(glyphs, dict):
        raise ValueError(f"{label} requires a glyphs object")
    result: dict[int, str] = {}
    for key, value in glyphs.items():
        if not isinstance(key, str) or len(key) != 4:
            raise ValueError(f"invalid {label} glyph key: {key!r}")
        index = int(key, 16)
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid {label} glyph value for {key}")
        result[index] = value
    return result


def load_glyph_tables(path: Path) -> tuple[dict[str, dict[int, str]], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tables = data.get("tables")
    result: dict[str, dict[int, str]] = {}
    if isinstance(tables, dict):
        for table_id in ("primary", "alternate"):
            table = tables.get(table_id)
            if not isinstance(table, dict):
                raise ValueError(f"glyph map requires table {table_id!r}")
            result[table_id] = decode_glyph_object(
                table.get("glyphs"),
                label=table_id,
            )
            declared_count = table.get("glyph_count")
            if declared_count != len(result[table_id]):
                raise ValueError(
                    f"{table_id} glyph_count differs from glyphs population"
                )
    else:
        # Read the historical flat map so older evidence snapshots remain
        # inspectable. New extraction must use the table-scoped schema.
        flat = decode_glyph_object(data.get("glyphs"), label="legacy")
        result = {"primary": flat, "alternate": flat}
    status = data.get("status", "partial-screen-proven-only")
    if not isinstance(status, str) or not status:
        raise ValueError("glyph map status must be a nonempty string")
    return result, status


def token_kind_and_markup(
    token: int,
    glyphs: dict[int, str],
) -> tuple[str, str, str]:
    if token < 0x4000:
        character = glyphs.get(token)
        return (
            "glyph",
            character if character is not None else f"{{glyph:{token:04X}}}",
            "editable-through-translation",
        )
    if token == 0x4000:
        return "name_surname", "{name:surname}", "preserve"
    if token == 0x6000:
        return "name_given", "{name:given}", "preserve"
    if token < 0x8000:
        return (
            "substitution_unknown",
            f"{{substitution:{token:04X}}}",
            "forbidden-until-semantics-confirmed",
        )
    if token == 0x8000:
        return "page_end", "{page_end}", "preserve"
    if token == 0xFFFB:
        return "align", "{align}", "movable-layout-in-story-only"
    if token == 0xFFFC:
        return "pause", "{pause}", "preserve"
    if token == 0xFFFD:
        return "pace", "{pace}", "preserve"
    if token == 0xFFFE:
        return (
            "reserved_fffe",
            "{reserved_fffe}",
            "forbidden-until-semantics-confirmed",
        )
    if token == 0xFFFF:
        return "stream_end", "{stream_end}", "preserve"

    argument = token & 0x0FFF
    prefix = token >> 12
    names = {
        0x8: "control_8",
        0x9: "speaker_style",
        0xA: "style_off",
        0xB: "control_b",
        0xC: "delay",
        0xD: "voice_transition",
        0xE: "audio",
        0xF: "control_f",
    }
    kind = names[prefix]
    policy = (
        "preserve"
        if prefix in {0x9, 0xA, 0xD, 0xE}
        else "forbidden-until-semantics-confirmed"
    )
    return kind, f"{{{kind}:{argument:03X}}}", policy


def decode_original(
    tokens: Iterable[int],
    glyphs: dict[int, str],
) -> dict[str, Any]:
    reversible: list[str] = []
    display: list[str] = []
    unmapped: set[int] = set()
    mapped_count = 0
    controls = []
    token_kinds: Counter[str] = Counter()

    for index, token in enumerate(tokens):
        kind, markup, policy = token_kind_and_markup(token, glyphs)
        token_kinds[kind] += 1
        reversible.append(markup)
        display.append("\n" if token == 0xFFFB else markup)
        if token < 0x4000:
            if token in glyphs:
                mapped_count += 1
            else:
                unmapped.add(token)
        else:
            controls.append(
                {
                    "token_index": index,
                    "raw": token_hex(token),
                    "kind": kind,
                    "markup": markup,
                    "policy": policy,
                }
            )

    return {
        "text": "".join(reversible),
        "display_text": "".join(display),
        "mapping_complete": not unmapped,
        "mapped_glyph_count": mapped_count,
        "unmapped_glyphs": [token_hex(value) for value in sorted(unmapped)],
        "token_kind_counts": dict(sorted(token_kinds.items())),
        "control_tokens": controls,
    }


def token_width(token: int, name_profile: dict[int, int]) -> int:
    if token < 0x4000:
        return 1
    if token < 0x8000:
        if token not in name_profile:
            raise ValueError(f"unknown substitution width for token {token:04X}")
        return name_profile[token]
    return 0


def measure_story_layout(
    tokens: Iterable[int],
    *,
    name_profile: dict[int, int],
    columns: int = STORY_COLUMNS,
    rows: int = STORY_ROWS,
) -> dict[str, Any]:
    cursor = 0
    glyph_positions = 0
    alignment_padding = 0
    row_occupied = [0] * rows
    overflow_glyph_positions = 0

    for token in tokens:
        if token == 0xFFFB:
            padding = (-cursor) % columns
            cursor += padding
            alignment_padding += padding
            continue
        width = token_width(token, name_profile)
        for _ in range(width):
            row = cursor // columns
            if row < rows:
                row_occupied[row] += 1
            else:
                overflow_glyph_positions += 1
            cursor += 1
            glyph_positions += 1

    capacity = columns * rows
    return {
        "positions": cursor,
        "glyph_positions": glyph_positions,
        "alignment_padding": alignment_padding,
        "rows_used": (cursor + columns - 1) // columns if cursor else 0,
        "row_occupied": row_occupied,
        "overflow_positions": max(0, cursor - capacity),
        "overflow_glyph_positions": overflow_glyph_positions,
        "fits": cursor <= capacity and overflow_glyph_positions == 0,
    }


def classification_for_unit(
    unit_index: int,
    *,
    embedded: bool = False,
    ui: bool = False,
) -> tuple[str, str]:
    if ui:
        return "font_rendered_ui", "direct_or_shared_ui"
    if embedded:
        if unit_index == 30:
            return "diagnostic_test", "diagnostic_path"
        return "dormant_unreachable", "dormant_unreachable"
    if unit_index <= 20:
        return "story", "main_path"
    if unit_index == 21:
        return "general_race", "main_path"
    return "diagnostic_test", "diagnostic_path"


def pointer_table_references(
    unit: dict[str, Any],
    unit_data: bytes,
) -> dict[int, list[dict[str, Any]]]:
    table_offset = unit["pointer_table_offset"]
    count_offset = unit["pointer_table_count_offset"]
    count = (count_offset - table_offset) // 4
    pointers = struct.unpack_from(f"<{count}I", unit_data, table_offset)
    references: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, pointer in enumerate(pointers):
        storage_unit_offset = table_offset + index * 4
        references[pointer].append(
            {
                "reference_index": index,
                "storage_file_offset": offset_hex(
                    unit["file_offset"] + storage_unit_offset
                ),
                "storage_unit_offset": offset_hex(storage_unit_offset, width=4),
                "width_bits": 32,
                "endian": "little",
                "basis": "runtime_absolute",
                "base": address_hex(unit["load_address"]),
                "raw_value": address_hex(pointer),
            }
        )
    return references


def translation_slots() -> dict[str, Any]:
    return {
        "full": {
            "text": "",
            "status": "untranslated",
            "notes": None,
        },
        "abbreviated": {
            "text": "",
            "status": "untranslated",
            "notes": None,
            "use_only_when": "approved full translation cannot satisfy layout",
        },
    }


def build_entry(
    *,
    entry_id: str,
    entry: dict[str, Any],
    unit: dict[str, Any],
    allbin: bytes,
    glyphs: dict[int, str],
    classification: str,
    reachability: str,
    pointer_references: list[dict[str, Any]],
    layout_profile: str | None,
) -> dict[str, Any]:
    file_offset = entry["file_offset"]
    raw = allbin[file_offset : file_offset + entry["byte_size"]]
    if len(raw) != entry["byte_size"]:
        raise ValueError(f"{entry_id}: source range exceeds ALLBIN")
    if sha256_bytes(raw) != entry["sha256"]:
        raise ValueError(f"{entry_id}: inventory SHA-256 differs from ALLBIN")
    tokens = tokens_from_bytes(raw)
    decoded = decode_original(tokens, glyphs)
    japanese = {
        key: decoded[key]
        for key in (
            "text",
            "display_text",
            "mapping_complete",
            "mapped_glyph_count",
            "unmapped_glyphs",
        )
    }

    flags = []
    if not japanese["mapping_complete"]:
        flags.append("mapping_incomplete")
    if entry.get("reference_count", 1) > 1:
        flags.append("shared_by_multiple_references")
    if classification == "diagnostic_test":
        flags.append("diagnostic_only")
    if classification == "dormant_unreachable":
        flags.append("dormant_unreachable")

    layout = None
    if layout_profile is not None:
        original_layout = measure_story_layout(
            tokens,
            name_profile=NAME_PROFILES["original_japanese"],
        )
        korean_name_layout = measure_story_layout(
            tokens,
            name_profile=NAME_PROFILES["korean_fixed"],
        )
        if not korean_name_layout["fits"]:
            flags.append("korean_fixed_name_requires_reflow")
        layout = {
            "profile": layout_profile,
            "original_japanese_names": original_layout,
            "korean_fixed_names_without_reflow": korean_name_layout,
        }

    source = {
        "container": "ALLBIN.BIN",
        "unit_index": unit["unit_index"],
        "subsystem": unit["subsystem"],
        "file_offset": offset_hex(file_offset),
        "unit_offset": offset_hex(entry["unit_offset"], width=4),
        "runtime_pointer": address_hex(entry["pointer"]),
        "byte_size": entry["byte_size"],
        "sha256": entry["sha256"],
        "terminal": token_hex(entry["terminal"]),
        "reference_count": entry.get("reference_count", 1),
        "pointer_references": pointer_references,
    }
    if "reference_proof" in entry:
        source["reference_proof"] = entry["reference_proof"]

    return {
        "entry_id": entry_id,
        "classification": classification,
        "reachability": reachability,
        "source": source,
        "original": {
            "raw_hex": raw.hex().upper(),
            "tokens": [token_hex(token) for token in tokens],
            "japanese": japanese,
            "token_kind_counts": decoded["token_kind_counts"],
            "control_tokens": decoded["control_tokens"],
        },
        "layout": layout,
        "translation": translation_slots(),
        "flags": sorted(flags),
    }


def workset_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    classifications = Counter(entry["classification"] for entry in entries)
    reachability = Counter(entry["reachability"] for entry in entries)
    content_hashes = {entry["source"]["sha256"] for entry in entries}
    return {
        "entry_count": len(entries),
        "pointer_reference_count": sum(
            entry["source"]["reference_count"] for entry in entries
        ),
        "unique_encoded_content_count": len(content_hashes),
        "raw_byte_count": sum(entry["source"]["byte_size"] for entry in entries),
        "mapping_complete_entry_count": sum(
            entry["original"]["japanese"]["mapping_complete"] for entry in entries
        ),
        "mapping_incomplete_entry_count": sum(
            not entry["original"]["japanese"]["mapping_complete"]
            for entry in entries
        ),
        "classification_counts": dict(sorted(classifications.items())),
        "reachability_counts": dict(sorted(reachability.items())),
        "full_translation_status_counts": {"untranslated": len(entries)},
        "abbreviated_translation_status_counts": {"untranslated": len(entries)},
        "generated_translation_count": 0,
    }


def workset_document(
    *,
    workset_kind: str,
    entries: list[dict[str, Any]],
    inventory_path: Path,
    allbin_path: Path,
    allbin_sha256: str,
    glyph_map_path: Path,
    glyph_map_sha256: str,
    glyph_map_status: str,
    glyph_table_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "schema": "data/dialogue-extraction-schema.json",
        "workset_kind": workset_kind,
        "baseline_id": f"disc1-allbin-{allbin_sha256[:16]}",
        "translation_generated": False,
        "scope": {
            "game": "Future GPX Cyber Formula - Aratanaru Chousensha",
            "platform": "PlayStation",
            "disc": 1,
            "revision": "Japan",
            "source_inventory": display_path(inventory_path),
            "source_allbin": display_path(allbin_path),
            "source_allbin_sha256": allbin_sha256,
            "glyph_map": display_path(glyph_map_path),
            "glyph_map_sha256": glyph_map_sha256,
            "glyph_map_status": glyph_map_status,
            "glyph_table": glyph_table_id,
            "population_status": (
                "direct-pointer-target-baseline-known-incomplete"
                if workset_kind == "dialogue"
                else "explicit-ui-roots"
            ),
            "known_population_limitation": (
                "Pointerless continuation pages after 0x8000 are not yet "
                "standalone entries; unit 0 has five confirmed pages."
                if workset_kind == "dialogue"
                else None
            ),
        },
        "field_policy": {
            "protected": [
                "baseline_id",
                "scope",
                "entries[].entry_id",
                "entries[].classification",
                "entries[].reachability",
                "entries[].source",
                "entries[].original",
                "entries[].layout",
                "entries[].flags",
            ],
            "editable": [
                "entries[].translation.full",
                "entries[].translation.abbreviated",
            ],
            "merge_rule": (
                "Never accept changes to protected fields from a translation "
                "tool or AI response; conflicts in editable fields require review."
            ),
        },
        "token_spec": TOKEN_SPEC,
        "layout_profiles": {
            "story-dialogue-17x3": {
                "columns": STORY_COLUMNS,
                "rows": STORY_ROWS,
                "capacity_positions": STORY_CAPACITY,
                "glyph_cell_px": [STORY_GLYPH_WIDTH, STORY_GLYPH_HEIGHT],
                "horizontal_stride_px": STORY_GLYPH_WIDTH,
                "vertical_stride_px": STORY_ROW_STRIDE,
                "align_token": "FFFB",
                "page_end_token": "8000",
                "overflow_policy": "fail",
            }
        },
        "summary": workset_summary(entries),
        "entries": entries,
    }


def batch_documents(
    document: dict[str, Any],
    *,
    maximum_entries: int,
) -> list[dict[str, Any]]:
    if maximum_entries < 1:
        raise ValueError("batch size must be positive")

    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in document["entries"]:
        source = entry["source"]
        grouped[(source["unit_index"], source["subsystem"])].append(entry)

    batches = []
    ordinal = 0
    for (unit_index, subsystem), entries in sorted(grouped.items()):
        for part_index, start in enumerate(range(0, len(entries), maximum_entries), 1):
            ordinal += 1
            chunk = entries[start : start + maximum_entries]
            batch_id = (
                f"{document['workset_kind']}-u{unit_index:02d}-"
                f"part{part_index:03d}"
            )
            batch = {
                key: value
                for key, value in document.items()
                if key not in {"summary", "entries"}
            }
            batch["batch"] = {
                "batch_id": batch_id,
                "ordinal": ordinal,
                "unit_index": unit_index,
                "subsystem": subsystem,
                "part_index": part_index,
                "maximum_entries": maximum_entries,
                "first_entry_id": chunk[0]["entry_id"],
                "last_entry_id": chunk[-1]["entry_id"],
            }
            batch["summary"] = workset_summary(chunk)
            batch["entries"] = chunk
            batches.append(batch)
    return batches


def validate_workset(document: dict[str, Any], allbin: bytes) -> None:
    if document.get("schema_version") != 2:
        raise ValueError("workset schema_version must be 2")
    if document.get("translation_generated") is not False:
        raise ValueError("extraction workset must not claim generated translation")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError("workset entries must be a list")

    entry_ids = [entry.get("entry_id") for entry in entries]
    if any(not isinstance(entry_id, str) or not entry_id for entry_id in entry_ids):
        raise ValueError("every workset entry requires a nonempty entry_id")
    if len(set(entry_ids)) != len(entry_ids):
        raise ValueError("workset entry_id values are not unique")

    for entry in entries:
        entry_id = entry["entry_id"]
        source = entry["source"]
        original = entry["original"]
        japanese = original.get("japanese")
        if not isinstance(japanese, dict):
            raise ValueError(f"{entry_id}: original.japanese is missing")
        unmapped = japanese.get("unmapped_glyphs")
        if not isinstance(unmapped, list):
            raise ValueError(
                f"{entry_id}: original.japanese.unmapped_glyphs is invalid"
            )
        if japanese.get("mapping_complete") is not (not unmapped):
            raise ValueError(
                f"{entry_id}: Japanese mapping completeness differs"
            )
        if japanese["mapping_complete"] and "{glyph:" in japanese.get("text", ""):
            raise ValueError(
                f"{entry_id}: complete Japanese text retains a glyph placeholder"
            )
        raw = bytes.fromhex(original["raw_hex"])
        tokens = tokens_from_bytes(raw)
        if [token_hex(token) for token in tokens] != original["tokens"]:
            raise ValueError(f"{entry_id}: tokens do not rebuild raw_hex")
        if len(raw) != source["byte_size"]:
            raise ValueError(f"{entry_id}: byte_size differs from raw_hex")
        if sha256_bytes(raw) != source["sha256"]:
            raise ValueError(f"{entry_id}: raw_hex SHA-256 differs")
        file_offset = int(source["file_offset"], 16)
        if allbin[file_offset : file_offset + len(raw)] != raw:
            raise ValueError(f"{entry_id}: raw_hex differs from current ALLBIN")
        for variant in ("full", "abbreviated"):
            translation = entry["translation"][variant]
            if translation["text"] != "" or translation["status"] != "untranslated":
                raise ValueError(
                    f"{entry_id}: extractor must leave {variant} translation empty"
                )

    summary = document["summary"]
    if summary["entry_count"] != len(entries):
        raise ValueError("workset summary entry_count differs")
    if summary["generated_translation_count"] != 0:
        raise ValueError("workset contains generated translations")


def pointer_unit_storage(
    unit: dict[str, Any],
    allbin: bytes,
) -> dict[str, Any]:
    entries = sorted(unit["entries"], key=lambda entry: entry["unit_offset"])
    if not entries:
        raise ValueError(f"unit {unit['unit_index']} has no entries")
    first_start = entries[0]["unit_offset"]
    last_end = max(entry["end_offset"] for entry in entries)
    gaps = sum(
        max(0, right["unit_offset"] - left["end_offset"])
        for left, right in zip(entries, entries[1:])
    )
    unique_text_bytes = sum(entry["byte_size"] for entry in entries)
    table_offset = unit["pointer_table_offset"]
    count_end = unit["pointer_table_count_offset"] + 4
    unit_start = unit["file_offset"]
    unit_data = allbin[unit_start : unit_start + unit["byte_size"]]
    trailing = unit_data[count_end:]
    if any(trailing):
        raise ValueError(f"unit {unit['unit_index']} trailing padding is not zero")
    if last_end > table_offset:
        raise ValueError(f"unit {unit['unit_index']} text overlaps pointer table")

    return {
        "unit_index": unit["unit_index"],
        "subsystem": unit["subsystem"],
        "scheduled_bytes": unit["byte_size"],
        "unique_text_bytes": unique_text_bytes,
        "prefix_before_first_text_bytes": first_start,
        "inter_entry_gap_bytes": gaps,
        "after_last_text_before_pointer_table_bytes": table_offset - last_end,
        "pointer_table_and_count_bytes": count_end - table_offset,
        "trailing_zero_padding_bytes": len(trailing),
        "trailing_zero_verified": True,
        "space_policy": {
            "prefix_and_gaps": "preserve-unclassified",
            "trailing_zero_padding": "candidate-unproven-do-not-use",
        },
    }


def storage_group_summary(
    name: str,
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    fields = (
        "scheduled_bytes",
        "unique_text_bytes",
        "prefix_before_first_text_bytes",
        "inter_entry_gap_bytes",
        "after_last_text_before_pointer_table_bytes",
        "pointer_table_and_count_bytes",
        "trailing_zero_padding_bytes",
    )
    result = {"name": name, "unit_count": len(units)}
    result.update({field: sum(unit[field] for unit in units) for field in fields})
    return result


def layout_histogram(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    histogram = Counter(
        entry["layout"][key]["rows_used"]
        for entry in entries
        if entry["layout"] is not None
    )
    return {str(rows): count for rows, count in sorted(histogram.items())}


def build_layout_storage_report(
    *,
    dialogue_entries: list[dict[str, Any]],
    inventory: dict[str, Any],
    allbin: bytes,
    allbin_path: Path,
) -> dict[str, Any]:
    story_entries = [
        entry for entry in dialogue_entries if entry["classification"] == "story"
    ]
    unit_reports = [
        pointer_unit_storage(unit, allbin) for unit in inventory["units"]
    ]
    event_units = [unit for unit in unit_reports if unit["unit_index"] <= 20]
    voice_units = [unit for unit in unit_reports if unit["unit_index"] >= 21]
    group_reports = [
        storage_group_summary("event_page_units_0_20", event_units),
        storage_group_summary("voice_event_units_21_29", voice_units),
    ]
    totals = storage_group_summary("pointer_units_0_29", unit_reports)

    original_layouts = [
        entry["layout"]["original_japanese_names"] for entry in story_entries
    ]
    korean_layouts = [
        entry["layout"]["korean_fixed_names_without_reflow"]
        for entry in story_entries
    ]
    korean_overflow_entries = [
        {
            "entry_id": entry["entry_id"],
            "file_offset": entry["source"]["file_offset"],
            "original": entry["layout"]["original_japanese_names"],
            "korean_fixed_names_without_reflow": entry["layout"][
                "korean_fixed_names_without_reflow"
            ],
        }
        for entry in story_entries
        if not entry["layout"]["korean_fixed_names_without_reflow"]["fits"]
    ]

    upload_bytes = STORY_UPLOAD_WIDTH_BYTES * STORY_UPLOAD_HEIGHT
    return {
        "schema_version": 1,
        "source": {
            "allbin": display_path(allbin_path),
            "allbin_sha256": sha256_bytes(allbin),
            "evidence": [
                "IDA sub_80032D34 xrefs and exact addresses",
                "Ghidra sub_80032D34 control-flow decompilation",
                "work/analysis/ram-first-dialogue.bin runtime state",
            ],
        },
        "story_dialogue_layout": {
            "status": "confirmed",
            "columns": STORY_COLUMNS,
            "rows": STORY_ROWS,
            "capacity_positions": STORY_CAPACITY,
            "glyph_cell_px": [STORY_GLYPH_WIDTH, STORY_GLYPH_HEIGHT],
            "horizontal_stride_px": STORY_GLYPH_WIDTH,
            "vertical_stride_px": STORY_ROW_STRIDE,
            "vram_upload": {
                "width_halfwords": STORY_UPLOAD_WIDTH_HALFWORDS,
                "width_bytes": STORY_UPLOAD_WIDTH_BYTES,
                "height_px": STORY_UPLOAD_HEIGHT,
                "byte_size": upload_bytes,
            },
            "original_corpus": {
                "page_count": len(story_entries),
                "maximum_positions": max(layout["positions"] for layout in original_layouts),
                "exactly_full_page_count": sum(
                    layout["positions"] == STORY_CAPACITY
                    for layout in original_layouts
                ),
                "overflow_page_count": sum(
                    not layout["fits"] for layout in original_layouts
                ),
                "rows_used_histogram": layout_histogram(
                    story_entries, "original_japanese_names"
                ),
                "maximum_occupied_per_physical_row": [
                    max(layout["row_occupied"][row] for layout in original_layouts)
                    for row in range(STORY_ROWS)
                ],
            },
            "fixed_korean_name_simulation_without_reflow": {
                "surname": "시바",
                "surname_positions": 2,
                "given_name": "세이치로",
                "given_name_positions": 4,
                "overflow_page_count": sum(not layout["fits"] for layout in korean_layouts),
                "overflow_entries": korean_overflow_entries,
                "decision": (
                    "Reflow the affected translated page; do not preserve the "
                    "original align-token placement mechanically."
                ),
            },
            "overflow_behavior": {
                "explicit_capacity_check": False,
                "positions_52_and_above": (
                    "written into rows not included in the 3-row VRAM upload"
                ),
                "continued_overflow_risk": (
                    "eventually crosses 0x80030000 into executable memory"
                ),
                "build_policy": "fail when any translated page exceeds 51 positions",
            },
        },
        "runtime_work_buffer": {
            "start": address_hex(STORY_WORK_BUFFER_ADDRESS),
            "end_exclusive": address_hex(
                STORY_WORK_BUFFER_ADDRESS + STORY_WORK_BUFFER_SIZE
            ),
            "byte_size": STORY_WORK_BUFFER_SIZE,
            "active_story_upload_bytes": upload_bytes,
            "bytes_outside_active_story_upload": STORY_WORK_BUFFER_SIZE - upload_bytes,
            "clear_behavior": "all 0x3000 bytes are cleared on each page reset",
            "decision": "preserve",
            "reason": (
                "The whole buffer is live renderer workspace; bytes outside the "
                "current upload are not proven free storage."
            ),
        },
        "allbin_pointer_unit_storage": {
            "groups": group_reports,
            "total": totals,
            "units": unit_reports,
            "decision": {
                "prefix_and_inter_entry_gaps": (
                    "preserve-physical-fallthrough-pointerless-pages-confirmed"
                ),
                "after_last_text_before_pointer_table": "preserve-unclassified",
                "trailing_zero_padding": "candidate-unproven-do-not-use",
                "cross_unit_growth": "forbidden-without-loader-and-schedule-proof",
                "recommended_next_step": (
                    "Measure approved Korean text, then build a reference-complete "
                    "per-unit repacker inside proven bounds."
                ),
            },
        },
    }


def extract_documents(
    *,
    inventory_path: Path,
    allbin_path: Path,
    glyph_map_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    allbin = allbin_path.read_bytes()
    allbin_hash = sha256_bytes(allbin)
    if allbin_hash != EXPECTED_ALLBIN_SHA256:
        raise ValueError(
            f"unsupported ALLBIN.BIN SHA-256: {allbin_hash}; "
            f"expected {EXPECTED_ALLBIN_SHA256}"
        )
    if inventory["source"]["allbin_sha256"] != allbin_hash:
        raise ValueError("text inventory and ALLBIN.BIN baselines differ")
    if inventory["summary"]["all_font_stream_entry_count"] != EXPECTED_FONT_STREAM_COUNT:
        raise ValueError("text inventory font-stream population differs")

    glyph_tables, glyph_map_status = load_glyph_tables(glyph_map_path)
    primary_glyphs = glyph_tables["primary"]
    alternate_glyphs = glyph_tables["alternate"]
    glyph_map_hash = sha256_file(glyph_map_path)
    dialogue_entries: list[dict[str, Any]] = []
    ui_entries: list[dict[str, Any]] = []

    for unit in inventory["units"]:
        start = unit["file_offset"]
        unit_data = allbin[start : start + unit["byte_size"]]
        references = pointer_table_references(unit, unit_data)
        classification, reachability = classification_for_unit(unit["unit_index"])
        for entry in unit["entries"]:
            pointer_refs = references[entry["pointer"]]
            first_reference = pointer_refs[0]["reference_index"]
            entry_id = (
                f"disc1/allbin/u{unit['unit_index']:02d}/"
                f"{unit['subsystem']}/ref{first_reference:04d}"
            )
            dialogue_entries.append(
                build_entry(
                    entry_id=entry_id,
                    entry=entry,
                    unit=unit,
                    allbin=allbin,
                    glyphs=primary_glyphs,
                    classification=classification,
                    reachability=reachability,
                    pointer_references=pointer_refs,
                    layout_profile=(
                        "story-dialogue-17x3"
                        if classification == "story"
                        else None
                    ),
                )
            )

    for unit in inventory["embedded_race_units"]:
        classification, reachability = classification_for_unit(
            unit["unit_index"], embedded=True
        )
        for index, entry in enumerate(unit["entries"]):
            pointer_refs = [
                {
                    "reference_index": reference_index,
                    "storage_file_offset": offset_hex(
                        unit["file_offset"] + reference_offset
                    ),
                    "storage_unit_offset": offset_hex(reference_offset, width=4),
                    "width_bits": 32,
                    "endian": "little",
                    "basis": "runtime_absolute",
                    "base": address_hex(unit["load_address"]),
                    "raw_value": address_hex(entry["pointer"]),
                }
                for reference_index, reference_offset in enumerate(
                    entry["reference_unit_offsets"]
                )
            ]
            entry_id = (
                f"disc1/allbin/u{unit['unit_index']:02d}/"
                f"embedded_race/e{index:04d}"
            )
            dialogue_entries.append(
                build_entry(
                    entry_id=entry_id,
                    entry=entry,
                    unit=unit,
                    allbin=allbin,
                    glyphs=primary_glyphs,
                    classification=classification,
                    reachability=reachability,
                    pointer_references=pointer_refs,
                    layout_profile=None,
                )
            )

    ui_unit = inventory["overlay_ui"]
    classification, reachability = classification_for_unit(
        ui_unit["unit_index"], ui=True
    )
    for index, entry in enumerate(ui_unit["entries"]):
        entry_id = f"disc1/allbin/u40/font_rendered_ui/e{index:03d}"
        ui_entries.append(
            build_entry(
                entry_id=entry_id,
                entry=entry,
                unit=ui_unit,
                allbin=allbin,
                glyphs=alternate_glyphs,
                classification=classification,
                reachability=reachability,
                pointer_references=[],
                layout_profile=None,
            )
        )

    if len(dialogue_entries) != EXPECTED_DIALOGUE_STREAM_COUNT:
        raise ValueError(
            f"dialogue population differs: {len(dialogue_entries)} "
            f"!= {EXPECTED_DIALOGUE_STREAM_COUNT}"
        )
    if len(ui_entries) != EXPECTED_UI_STREAM_COUNT:
        raise ValueError(
            f"UI population differs: {len(ui_entries)} != {EXPECTED_UI_STREAM_COUNT}"
        )

    dialogue = workset_document(
        workset_kind="dialogue",
        entries=dialogue_entries,
        inventory_path=inventory_path,
        allbin_path=allbin_path,
        allbin_sha256=allbin_hash,
        glyph_map_path=glyph_map_path,
        glyph_map_sha256=glyph_map_hash,
        glyph_map_status=glyph_map_status,
        glyph_table_id="primary",
    )
    ui = workset_document(
        workset_kind="font-rendered-ui",
        entries=ui_entries,
        inventory_path=inventory_path,
        allbin_path=allbin_path,
        allbin_sha256=allbin_hash,
        glyph_map_path=glyph_map_path,
        glyph_map_sha256=glyph_map_hash,
        glyph_map_status=glyph_map_status,
        glyph_table_id="alternate",
    )
    validate_workset(dialogue, allbin)
    validate_workset(ui, allbin)
    layout_storage = build_layout_storage_report(
        dialogue_entries=dialogue_entries,
        inventory=inventory,
        allbin=allbin,
        allbin_path=allbin_path,
    )
    return dialogue, ui, layout_storage


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_dialogue_batches(
    *,
    document: dict[str, Any],
    allbin: bytes,
    output_dir: Path,
    maximum_entries: int,
    source_workset_path: Path,
) -> dict[str, Any]:
    batches = batch_documents(document, maximum_entries=maximum_entries)
    manifest_entries = []
    for batch in batches:
        validate_workset(batch, allbin)
        batch_id = batch["batch"]["batch_id"]
        batch_path = output_dir / f"{batch_id}.json"
        write_json(batch_path, batch)
        manifest_entries.append(
            {
                **batch["batch"],
                "path": display_path(batch_path),
                "entry_count": batch["summary"]["entry_count"],
                "sha256": sha256_file(batch_path),
            }
        )

    manifest = {
        "schema_version": 1,
        "baseline_id": document["baseline_id"],
        "translation_generated": False,
        "source_workset": display_path(source_workset_path),
        "source_workset_sha256": sha256_file(source_workset_path),
        "batch_policy": {
            "maximum_entries": maximum_entries,
            "unit_boundaries_preserved": True,
            "ordering": "unit_index, subsystem, source order",
            "merge_key": "entry_id",
            "protected_fields": document["field_policy"]["protected"],
            "editable_fields": document["field_policy"]["editable"],
        },
        "summary": {
            "batch_count": len(batches),
            "entry_count": sum(
                batch["summary"]["entry_count"] for batch in batches
            ),
            "generated_translation_count": 0,
        },
        "batches": manifest_entries,
    }
    if manifest["summary"]["entry_count"] != len(document["entries"]):
        raise ValueError("batch manifest does not cover every dialogue entry")
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("work/analysis/disc1-text.json"),
    )
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
        "--dialogue-output",
        type=Path,
        default=Path("work/translations/disc1-dialogue.json"),
    )
    parser.add_argument(
        "--ui-output",
        type=Path,
        default=Path("work/translations/disc1-ui.json"),
    )
    parser.add_argument(
        "--layout-output",
        type=Path,
        default=Path("work/analysis/disc1-dialogue-layout.json"),
    )
    parser.add_argument(
        "--batch-output-dir",
        type=Path,
        default=Path("work/translations/disc1-dialogue-batches"),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
    )
    args = parser.parse_args()

    dialogue, ui, layout_storage = extract_documents(
        inventory_path=args.inventory,
        allbin_path=args.allbin,
        glyph_map_path=args.glyph_map,
    )
    write_json(args.dialogue_output, dialogue)
    write_json(args.ui_output, ui)
    write_json(args.layout_output, layout_storage)
    allbin = args.allbin.read_bytes()
    batch_manifest = write_dialogue_batches(
        document=dialogue,
        allbin=allbin,
        output_dir=args.batch_output_dir,
        maximum_entries=args.batch_size,
        source_workset_path=args.dialogue_output,
    )
    print(
        json.dumps(
            {
                "translation_generated": False,
                "dialogue": {
                    "path": str(args.dialogue_output),
                    **dialogue["summary"],
                },
                "ui": {
                    "path": str(args.ui_output),
                    **ui["summary"],
                },
                "layout_storage_report": str(args.layout_output),
                "dialogue_batches": {
                    "manifest": str(args.batch_output_dir / "manifest.json"),
                    **batch_manifest["summary"],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
