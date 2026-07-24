#!/usr/bin/env python3
"""Render label-free OCR atlases from the game's packed PS1 fonts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

try:
    from scripts.psx_font import GLYPH_SIZE, HEIGHT, WIDTH, unpack_glyph
except ModuleNotFoundError:
    from psx_font import GLYPH_SIZE, HEIGHT, WIDTH, unpack_glyph


@dataclass(frozen=True)
class FontTable:
    table_id: str
    offset: int
    glyph_count: int


FONT_TABLES = (
    FontTable("primary", 0x1A000, 0x04CD),
    FontTable("alternate", 0x3D1800, 0x05CC),
)


def render_ocr_atlas(
    source: bytes,
    table: FontTable,
    *,
    columns: int,
    scale: int,
) -> Image.Image:
    """Render all slots with no text, borders, or reference glyphs."""
    cell_width = WIDTH + 2
    cell_height = HEIGHT + 2
    rows = (table.glyph_count + columns - 1) // columns
    atlas = Image.new(
        "L",
        (columns * cell_width, rows * cell_height),
        0,
    )

    for index in range(table.glyph_count):
        begin = table.offset + index * GLYPH_SIZE
        end = begin + GLYPH_SIZE
        if end > len(source):
            raise ValueError(
                f"{table.table_id} glyph 0x{index:04X} exceeds input"
            )
        glyph = Image.new("L", (WIDTH, HEIGHT))
        glyph.putdata(
            [value * 36 for value in unpack_glyph(source[begin:end])]
        )
        x = (index % columns) * cell_width + 1
        y = (index // columns) * cell_height + 1
        atlas.paste(glyph, (x, y))

    return atlas.resize(
        (atlas.width * scale, atlas.height * scale),
        Image.Resampling.NEAREST,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-bin", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=32)
    parser.add_argument("--scale", type=int, default=4)
    args = parser.parse_args()

    if not args.start_bin.is_file():
        parser.error(f"input file does not exist: {args.start_bin}")
    if args.columns < 1 or args.scale < 1:
        parser.error("--columns and --scale must be positive")

    source = args.start_bin.read_bytes()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for table in FONT_TABLES:
        atlas = render_ocr_atlas(
            source,
            table,
            columns=args.columns,
            scale=args.scale,
        )
        output = args.output_dir / f"{table.table_id}-glyphs-only.png"
        atlas.save(output, optimize=True)
        print(
            f"{table.table_id}: glyphs={table.glyph_count} "
            f"columns={args.columns} scale={args.scale} "
            f"size={atlas.width}x{atlas.height} output={output}"
        )


if __name__ == "__main__":
    main()
