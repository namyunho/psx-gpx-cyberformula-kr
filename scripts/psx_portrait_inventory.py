#!/usr/bin/env python3
"""Inventory and render the state-selected START.BIN speaker portraits.

IDA establishes the storage-to-consumer path:

* ``sub_8003C558`` loads START unit ``41 + story_state`` at ``0x800B8000``.
* ``sub_800329B8`` selects ``0x800B8000 + 0x560 * portrait_index`` from a
  ``0x9xxx`` dialogue token.
* the consumer copies the first 16 halfwords as a CLUT, then uploads the
  remaining 0x540 bytes to a 12-halfword by 56-line VRAM rectangle.

Consequently each proven record is a 48x56 4bpp image with its own 16-color
CLUT.  Sector padding is excluded by locating the last nonzero 0x560-byte
record; zero-only records beyond it are not guessed to be portraits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule
    from scripts.psx_vram_render import (
        Preview,
        VramRecord,
        decode_indexed,
        write_contact_sheets,
    )
except ModuleNotFoundError:  # Direct execution from the repository root.
    from psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule
    from psx_vram_render import (
        Preview,
        VramRecord,
        decode_indexed,
        write_contact_sheets,
    )


START_UNIT_FIRST = 41
START_UNIT_LAST = 64
PORTRAIT_BLOCK_SIZE = 0x560
PALETTE_SIZE = 0x20
WIDTH_HALFWORDS = 12
HEIGHT = 56


def occupied_block_count(unit: bytes) -> int:
    """Return the count through the last nonzero fixed-size portrait block."""

    for block_index in range(len(unit) // PORTRAIT_BLOCK_SIZE - 1, -1, -1):
        start = block_index * PORTRAIT_BLOCK_SIZE
        if any(unit[start : start + PORTRAIT_BLOCK_SIZE]):
            return block_index + 1
    return 0


def decode_portrait(block: bytes, *, unit_index: int, block_index: int):
    if len(block) != PORTRAIT_BLOCK_SIZE:
        raise ValueError("portrait block must be exactly 0x560 bytes")
    palette = [
        int.from_bytes(block[offset : offset + 2], "little")
        for offset in range(0, PALETTE_SIZE, 2)
    ]
    record = VramRecord(
        unit_index=unit_index,
        child_index=block_index,
        x=0x380,
        y=0x180,
        width_halfwords=WIDTH_HALFWORDS,
        height=HEIGHT,
        payload=block[PALETTE_SIZE:],
    )
    return decode_indexed(record, palette, 4)


def inventory_unit(
    unit: bytes,
    *,
    unit_index: int,
    file_offset: int,
) -> dict[str, Any]:
    count = occupied_block_count(unit)
    occupied_end = count * PORTRAIT_BLOCK_SIZE
    if any(unit[occupied_end:]):
        raise ValueError("nonzero data follows the last occupied portrait block")
    records = []
    for block_index in range(count):
        start = block_index * PORTRAIT_BLOCK_SIZE
        block = unit[start : start + PORTRAIT_BLOCK_SIZE]
        if len(block) != PORTRAIT_BLOCK_SIZE:
            raise ValueError("scheduled unit ends inside a portrait block")
        records.append(
            {
                "block_index": block_index,
                "unit_offset": start,
                "file_offset": file_offset + start,
                "byte_size": len(block),
                "all_zero": not any(block),
                "sha256": hashlib.sha256(block).hexdigest(),
            }
        )
    return {
        "unit_index": unit_index,
        "story_state": unit_index - START_UNIT_FIRST,
        "file_offset": file_offset,
        "scheduled_byte_size": len(unit),
        "occupied_block_count": count,
        "occupied_byte_size": occupied_end,
        "zero_padding_byte_size": len(unit) - occupied_end,
        "records": records,
    }


def build_portrait_inventory(exe_path: Path, start_path: Path) -> dict[str, Any]:
    exe = PsxExe(exe_path.read_bytes())
    start_data = start_path.read_bytes()
    spec = next(spec for spec in SCHEDULE_SPECS if spec.filename == "START.BIN")
    schedule = discover_schedule(
        exe,
        spec.table_va,
        spec.table_limit_va,
        len(start_data),
    )
    units = []
    for span in schedule[START_UNIT_FIRST : START_UNIT_LAST + 1]:
        start = span["byte_offset"]
        units.append(
            inventory_unit(
                start_data[start : span["byte_end"]],
                unit_index=span["index"],
                file_offset=start,
            )
        )
    hashes = {
        record["sha256"]
        for unit in units
        for record in unit["records"]
    }
    return {
        "schema_version": 1,
        "method": {
            "load": (
                "sub_8003C558 loads START unit 41 + story_state to 0x800B8000"
            ),
            "select": (
                "sub_800329B8 selects 0x800B8000 + 0x560 * "
                "((token & 0x0FC0) >> 6)"
            ),
            "consume": (
                "first 0x20 bytes are a 16-color CLUT; the following 0x540 "
                "bytes are uploaded as a 12-halfword x 56-line rectangle"
            ),
            "scope_boundary": (
                "only fixed-size records through the last nonzero block are "
                "counted; sector padding and hypothetical zero-only trailing "
                "records are excluded"
            ),
        },
        "source": {
            "exe": str(exe_path),
            "start": str(start_path),
            "start_sha256": hashlib.sha256(start_data).hexdigest(),
        },
        "format": {
            "block_size": PORTRAIT_BLOCK_SIZE,
            "palette_byte_size": PALETTE_SIZE,
            "bits_per_pixel": 4,
            "width_pixels": WIDTH_HALFWORDS * 4,
            "height_pixels": HEIGHT,
            "vram_rect": {
                "x": 0x380,
                "y": 0x180,
                "width_halfwords": WIDTH_HALFWORDS,
                "height": HEIGHT,
            },
        },
        "summary": {
            "unit_count": len(units),
            "record_count": sum(
                unit["occupied_block_count"] for unit in units
            ),
            "unique_record_count": len(hashes),
            "duplicate_record_count": (
                sum(unit["occupied_block_count"] for unit in units) - len(hashes)
            ),
            "all_zero_record_count": sum(
                record["all_zero"]
                for unit in units
                for record in unit["records"]
            ),
        },
        "units": units,
    }


def iter_portrait_previews(
    start_data: bytes,
    schedule: list[dict[str, int]],
    inventory: dict[str, Any],
) -> Iterable[Preview]:
    for unit_report in inventory["units"]:
        span = schedule[unit_report["unit_index"]]
        unit = start_data[span["byte_offset"] : span["byte_end"]]
        for block_index in range(unit_report["occupied_block_count"]):
            start = block_index * PORTRAIT_BLOCK_SIZE
            block = unit[start : start + PORTRAIT_BLOCK_SIZE]
            yield Preview(
                (
                    f"state {unit_report['story_state']:02d} "
                    f"u{unit_report['unit_index']:02d} p{block_index:02d}"
                ),
                decode_portrait(
                    block,
                    unit_index=unit_report["unit_index"],
                    block_index=block_index,
                ),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disc-root", type=Path, default=Path("work/disc1/full"))
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("work/analysis/disc1-portraits.json"),
    )
    parser.add_argument(
        "--render-dir",
        type=Path,
        default=Path("work/analysis/portraits"),
    )
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    exe_path = args.disc_root / "SLPS_019.58"
    start_path = args.disc_root / "START.BIN"
    report = build_portrait_inventory(exe_path, start_path)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output_json)

    if not args.no_render:
        exe = PsxExe(exe_path.read_bytes())
        start_data = start_path.read_bytes()
        spec = next(
            spec for spec in SCHEDULE_SPECS if spec.filename == "START.BIN"
        )
        schedule = discover_schedule(
            exe,
            spec.table_va,
            spec.table_limit_va,
            len(start_data),
        )
        paths = write_contact_sheets(
            iter_portrait_previews(start_data, schedule, report),
            args.render_dir,
            "START-portraits",
            page_size=100,
            columns=10,
            cell_width=96,
            cell_height=112,
        )
        for path in paths:
            print(path)


if __name__ == "__main__":
    main()
