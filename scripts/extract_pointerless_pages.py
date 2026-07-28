#!/usr/bin/env python3
"""Extract u00-u21 pages that live inside direct-entry physical gaps."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

try:
    from scripts.build_dialogue_chapter_patch import (
        EXPECTED_ALLBIN_SHA256,
        UNIT_SHARED_POOL_REFERENCE_PROFILES,
        build_source_ordered_stream,
        load_object,
        physical_entry_ranges,
        scan_unit_dialogue_references,
    )
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import (
        EXPECTED_ALLBIN_SHA256,
        UNIT_SHARED_POOL_REFERENCE_PROFILES,
        build_source_ordered_stream,
        load_object,
        physical_entry_ranges,
        scan_unit_dialogue_references,
    )


EXPECTED_PAGE_COUNT = 83


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def markup_for_control(token: int, kind: str) -> str:
    if kind == "name_surname":
        return "{name:surname}"
    if kind == "name_given":
        return "{name:given}"
    if kind == "align":
        return "\n"
    return ""


def decode_visible_text(tokens: list[int], glyphs: dict[str, str]) -> str:
    output: list[str] = []
    for token in tokens:
        kind = control_kind(token)
        if kind is None:
            try:
                output.append(glyphs[f"{token:04X}"])
            except KeyError as error:
                raise ValueError(f"unmapped primary glyph 0x{token:04X}") from error
        else:
            output.append(markup_for_control(token, kind))
    return "".join(output)


def extract_pointerless_pages(
    *,
    allbin_path: Path,
    dialogue_workset_path: Path,
    glyph_map_path: Path,
) -> dict[str, Any]:
    allbin = allbin_path.read_bytes()
    if sha256_bytes(allbin) != EXPECTED_ALLBIN_SHA256:
        raise ValueError("ALLBIN.BIN hash differs from the verified original")
    dialogue = load_object(dialogue_workset_path)
    glyph_map = load_object(glyph_map_path)
    glyphs = glyph_map.get("tables", {}).get("primary", {}).get("glyphs")
    if not isinstance(glyphs, dict):
        raise ValueError("primary glyph map is missing")

    by_unit: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for entry in dialogue.get("entries", []):
        unit_index = int(entry["source"]["unit_index"])
        if 0 <= unit_index <= 21:
            by_unit[unit_index].append(entry)

    pages: list[dict[str, Any]] = []
    for unit_index in range(22):
        entries = by_unit[unit_index]
        ranges = physical_entry_ranges(entries)
        unit_file_offsets = {
            int(entry["source"]["file_offset"], 16)
            - int(entry["source"]["unit_offset"], 16)
            for _, _, entry in ranges
        }
        if len(unit_file_offsets) != 1:
            raise ValueError(f"unit {unit_index}: mixed source file offsets")
        unit_file_offset = unit_file_offsets.pop()
        scheduled_bytes = int(
            UNIT_SHARED_POOL_REFERENCE_PROFILES[unit_index]["scheduled_bytes"]
        )
        unit_data = allbin[
            unit_file_offset : unit_file_offset + scheduled_bytes
        ]
        original_streams = {
            entry["entry_id"]: bytes.fromhex(entry["original"]["raw_hex"])
            for _, _, entry in ranges
        }
        layout = build_source_ordered_stream(
            unit_data,
            entries,
            original_streams,
        )
        references = scan_unit_dialogue_references(
            unit_data,
            entries,
            layout,
        )
        references_by_target: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for reference in references:
            if reference["target_kind"] == "preserved_gap":
                references_by_target[
                    int(reference["source_target_unit_offset"])
                ].append(reference)

        unit_page_ranges: list[tuple[int, int]] = []
        for target, target_references in sorted(references_by_target.items()):
            containing_gap = next(
                (
                    gap
                    for gap in layout["gaps"]
                    if int(gap["source_start"])
                    <= target
                    < int(gap["source_end"])
                ),
                None,
            )
            if containing_gap is None:
                raise ValueError(
                    f"unit {unit_index}: gap target 0x{target:04X} has no gap"
                )
            gap_end = int(containing_gap["source_end"])
            tokens: list[int] = []
            end = target
            while end + 2 <= gap_end:
                token = struct.unpack_from("<H", unit_data, end)[0]
                tokens.append(token)
                end += 2
                if token in {0x8000, 0xFFFF}:
                    break
            if tokens and tokens[-1] not in {0x8000, 0xFFFF}:
                final_control_index = next(
                    (
                        index
                        for index in range(len(tokens) - 1, -1, -1)
                        if 0xD000 <= tokens[index] <= 0xDFFF
                    ),
                    None,
                )
                if (
                    final_control_index is not None
                    and all(
                        token == 0x0000
                        for token in tokens[final_control_index + 1 :]
                    )
                ):
                    tokens = tokens[: final_control_index + 1]
                    end = target + len(tokens) * 2
            if (
                not tokens
                or (
                    tokens[-1] not in {0x8000, 0xFFFF}
                    and not 0xD000 <= tokens[-1] <= 0xDFFF
                )
            ):
                raise ValueError(
                    f"unit {unit_index}: unterminated gap page at 0x{target:04X}"
                )
            if any(
                target < other_end and end > other_start
                for other_start, other_end in unit_page_ranges
            ):
                raise ValueError(
                    f"unit {unit_index}: overlapping gap page at 0x{target:04X}"
                )
            unit_page_ranges.append((target, end))

            raw = unit_data[target:end]
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
            jp = decode_visible_text(tokens, glyphs)
            entry_id = (
                f"disc1/allbin/u{unit_index:02d}/"
                f"pointerless_page/p{target:04X}"
            )
            pages.append(
                {
                    "entry_id": entry_id,
                    "classification": (
                        "pointerless_choice"
                        if any(
                            control["kind"] == "voice_transition"
                            for control in controls
                        )
                        else "pointerless_dialogue"
                    ),
                    "source": {
                        "container": "ALLBIN.BIN",
                        "unit_index": unit_index,
                        "file_offset": f"0x{unit_file_offset + target:X}",
                        "unit_offset": f"0x{target:04X}",
                        "runtime_pointer": (
                            f"0x{int(entries[0]['source']['runtime_pointer'], 16) - int(entries[0]['source']['unit_offset'], 16) + target:08X}"
                        ),
                        "byte_size": len(raw),
                        "sha256": sha256_bytes(raw),
                        "terminal": f"{tokens[-1]:04X}",
                        "reference_count": len(target_references),
                        "reference_unit_offsets": [
                            f"0x{int(reference['storage_unit_offset']):04X}"
                            for reference in target_references
                        ],
                        "containing_gap": {
                            "start": f"0x{int(containing_gap['source_start']):04X}",
                            "end_exclusive": (
                                f"0x{int(containing_gap['source_end']):04X}"
                            ),
                        },
                    },
                    "original": {
                        "raw_hex": raw.hex().upper(),
                        "tokens": [f"{token:04X}" for token in tokens],
                        "control_tokens": controls,
                        "display_text": jp,
                    },
                    "layout": {
                        "columns": 17,
                        "rows": 3,
                        "capacity_positions": 51,
                    },
                }
            )

    if len(pages) != EXPECTED_PAGE_COUNT:
        raise ValueError(
            f"pointerless page population changed: "
            f"{len(pages)} != {EXPECTED_PAGE_COUNT}"
        )
    return {
        "schema_version": 1,
        "status": "verified-original-pointerless-page-workset",
        "baseline_id": f"disc1-allbin-{EXPECTED_ALLBIN_SHA256[:16]}",
        "scope": {
            "unit_range": [0, 21],
            "source_allbin": str(allbin_path.resolve()),
            "source_allbin_sha256": EXPECTED_ALLBIN_SHA256,
            "direct_dialogue_workset": str(dialogue_workset_path.resolve()),
            "direct_dialogue_workset_sha256": sha256_bytes(
                dialogue_workset_path.read_bytes()
            ),
            "glyph_map": str(glyph_map_path.resolve()),
            "glyph_map_sha256": sha256_bytes(glyph_map_path.read_bytes()),
        },
        "summary": {
            "entry_count": len(pages),
            "choice_count": sum(
                page["classification"] == "pointerless_choice"
                for page in pages
            ),
            "dialogue_count": sum(
                page["classification"] == "pointerless_dialogue"
                for page in pages
            ),
            "reference_count": sum(
                page["source"]["reference_count"] for page in pages
            ),
        },
        "entries": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allbin",
        type=Path,
        default=Path("work/extracted/disc1/iso/ALLBIN.BIN"),
    )
    parser.add_argument(
        "--dialogue-workset",
        type=Path,
        default=Path("work/translations/disc1-dialogue.json"),
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
            "work/translations/disc1-pointerless-pages-u00-u21.json"
        ),
    )
    args = parser.parse_args()
    document = extract_pointerless_pages(
        allbin_path=args.allbin,
        dialogue_workset_path=args.dialogue_workset,
        glyph_map_path=args.glyph_map,
    )
    write_json(args.output, document)
    print(
        f"entries={document['summary']['entry_count']} "
        f"choices={document['summary']['choice_count']} "
        f"dialogue={document['summary']['dialogue_count']} "
        f"references={document['summary']['reference_count']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
