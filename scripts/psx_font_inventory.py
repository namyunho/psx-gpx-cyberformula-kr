#!/usr/bin/env python3
"""Inventory both fixed-length 14x14, 3bpp PS1 font providers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts.psx_font import GLYPH_SIZE
    from scripts.psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule
except ModuleNotFoundError:  # Direct execution from the repository root.
    from psx_font import GLYPH_SIZE
    from psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule


FONT_SPECS = (
    {
        "name": "primary_dialogue",
        "start_unit": 2,
        "ram_address": 0x80014A00,
        "selection": "default branch in sub_80032704",
    },
    {
        "name": "alternate_ui",
        "start_unit": 40,
        "ram_address": 0x80185000,
        "selection": "sub_80032704 when dword_80061140 & 0x2000",
    },
)


def inventory_font_unit(
    unit: bytes,
    *,
    name: str,
    start_unit: int,
    file_offset: int,
    ram_address: int,
    selection: str,
) -> dict[str, Any]:
    capacity = len(unit) // GLYPH_SIZE
    remainder = len(unit) % GLYPH_SIZE
    records = [
        unit[index * GLYPH_SIZE : (index + 1) * GLYPH_SIZE]
        for index in range(capacity)
    ]
    nonzero = [index for index, record in enumerate(records) if any(record)]
    if not nonzero:
        raise ValueError(f"{name} contains no nonzero glyph record")
    last_nonzero = nonzero[-1]
    defined_end = (last_nonzero + 1) * GLYPH_SIZE
    return {
        "name": name,
        "start_unit": start_unit,
        "file_offset": file_offset,
        "ram_address": ram_address,
        "selection": selection,
        "scheduled_byte_size": len(unit),
        "record_capacity": capacity,
        "record_remainder_byte_size": remainder,
        "nonzero_record_count": len(nonzero),
        "last_nonzero_record_index": last_nonzero,
        "defined_slot_count": last_nonzero + 1,
        "defined_byte_size": defined_end,
        "trailing_zero_byte_size": len(unit) - defined_end,
        "sha256": hashlib.sha256(unit).hexdigest(),
    }


def build_font_inventory(exe_path: Path, start_path: Path) -> dict[str, Any]:
    exe = PsxExe(exe_path.read_bytes())
    start_data = start_path.read_bytes()
    schedule_spec = next(
        spec for spec in SCHEDULE_SPECS if spec.filename == "START.BIN"
    )
    schedule = discover_schedule(
        exe,
        schedule_spec.table_va,
        schedule_spec.table_limit_va,
        len(start_data),
    )
    fonts = []
    for spec in FONT_SPECS:
        span = schedule[spec["start_unit"]]
        start = span["byte_offset"]
        fonts.append(
            inventory_font_unit(
                start_data[start : span["byte_end"]],
                file_offset=start,
                **spec,
            )
        )
    return {
        "schema_version": 1,
        "method": {
            "format": (
                "sub_80032704 selects index*74; sub_80032434 unpacks "
                "14x14 3bpp LSB-first pixels"
            ),
            "boundary": (
                "each provider is exactly one START.BIN scheduled unit; the "
                "last nonzero 74-byte record defines the observed slot range"
            ),
        },
        "source": {
            "exe": str(exe_path),
            "start": str(start_path),
            "start_sha256": hashlib.sha256(start_data).hexdigest(),
        },
        "glyph_format": {
            "width": 14,
            "height": 14,
            "bits_per_pixel": 3,
            "record_byte_size": GLYPH_SIZE,
        },
        "fonts": fonts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disc-root", type=Path, default=Path("work/disc1/full"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("work/analysis/disc1-fonts.json"),
    )
    args = parser.parse_args()
    report = build_font_inventory(
        args.disc_root / "SLPS_019.58",
        args.disc_root / "START.BIN",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
