#!/usr/bin/env python3
"""Decode and render the game's packed 14x14, 3bpp font glyphs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


WIDTH = 14
HEIGHT = 14
BPP = 3
PIXEL_COUNT = WIDTH * HEIGHT
GLYPH_SIZE = (PIXEL_COUNT * BPP + 7) // 8


def unpack_glyph(data: bytes) -> list[int]:
    if len(data) != GLYPH_SIZE:
        raise ValueError(f"glyph must be exactly {GLYPH_SIZE} bytes")
    accumulator = int.from_bytes(data, "little")
    return [
        (accumulator >> (index * BPP)) & 0x7 for index in range(PIXEL_COUNT)
    ]


def pack_glyph(pixels: list[int]) -> bytes:
    if len(pixels) != PIXEL_COUNT:
        raise ValueError(f"glyph must contain exactly {PIXEL_COUNT} pixels")
    accumulator = 0
    for index, value in enumerate(pixels):
        if not 0 <= value <= 7:
            raise ValueError("3bpp pixel values must be between 0 and 7")
        accumulator |= value << (index * BPP)
    return accumulator.to_bytes(GLYPH_SIZE, "little")


def render_atlas(
    source: bytes,
    font_offset: int,
    indices: list[int],
    output: Path,
    scale: int,
    columns: int,
) -> None:
    from PIL import Image, ImageDraw

    glyph_width = WIDTH * scale
    glyph_height = HEIGHT * scale
    cell_width = max(glyph_width + 12, 88)
    cell_height = glyph_height + 28
    rows = (len(indices) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), "#202020")
    draw = ImageDraw.Draw(sheet)

    for position, index in enumerate(indices):
        start = font_offset + index * GLYPH_SIZE
        end = start + GLYPH_SIZE
        if end > len(source):
            raise ValueError(f"glyph 0x{index:04X} is outside the input")
        pixels = unpack_glyph(source[start:end])
        glyph = Image.new("L", (WIDTH, HEIGHT))
        glyph.putdata([value * 36 for value in pixels])
        glyph = glyph.resize(
            (glyph_width, glyph_height), Image.Resampling.NEAREST
        ).convert("RGB")
        cell_x = (position % columns) * cell_width
        cell_y = (position // columns) * cell_height
        draw.text((cell_x + 6, cell_y + 4), f"{index:04X}", fill="white")
        sheet.paste(glyph, (cell_x + 6, cell_y + 22))

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--offset", type=lambda value: int(value, 0), default=0x1A000)
    parser.add_argument("--glyph-map", type=Path)
    parser.add_argument("--start", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--count", type=lambda value: int(value, 0))
    parser.add_argument("--scale", type=int, default=6)
    parser.add_argument("--columns", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.scale < 1 or args.columns < 1:
        parser.error("--scale and --columns must be positive")
    if args.glyph_map:
        mapping = json.loads(args.glyph_map.read_text(encoding="utf-8"))
        indices = [int(value, 16) for value in mapping.get("glyphs", {})]
    elif args.count is not None:
        if args.count < 1:
            parser.error("--count must be positive")
        indices = list(range(args.start, args.start + args.count))
    else:
        parser.error("provide --glyph-map or --count")

    render_atlas(
        args.input.read_bytes(),
        args.offset,
        indices,
        args.output,
        args.scale,
        args.columns,
    )
    print(
        f"glyphs={len(indices)} size={WIDTH}x{HEIGHT} bpp={BPP} "
        f"font_offset=0x{args.offset:X} output={args.output}"
    )


if __name__ == "__main__":
    main()
