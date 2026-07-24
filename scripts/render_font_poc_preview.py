#!/usr/bin/env python3
"""Render the exact glyph records inserted by the full-dialogue font PoC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.build_font_poc import FONT_OFFSET
    from scripts.psx_font import GLYPH_SIZE, HEIGHT, WIDTH, unpack_glyph
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from build_font_poc import FONT_OFFSET
    from psx_font import GLYPH_SIZE, HEIGHT, WIDTH, unpack_glyph


def parse_slot(value: str) -> int:
    return int(value, 16)


def render_preview(
    start_data: bytes,
    dialogue: list[str],
    mapping: dict[str, str],
    output: Path,
    *,
    scale: int = 8,
) -> None:
    from PIL import Image, ImageDraw

    if len(dialogue) != 2:
        raise ValueError("PoC manifest must contain exactly two dialogue lines")
    columns = max(len(line) for line in dialogue)
    cell_width = WIDTH * scale
    cell_height = HEIGHT * scale
    image = Image.new(
        "RGB",
        (columns * cell_width, len(dialogue) * cell_height),
        "#101522",
    )
    draw = ImageDraw.Draw(image)

    for row, line in enumerate(dialogue):
        for column, character in enumerate(line):
            slot = parse_slot(mapping[character])
            begin = FONT_OFFSET + slot * GLYPH_SIZE
            glyph_data = start_data[begin : begin + GLYPH_SIZE]
            if len(glyph_data) != GLYPH_SIZE:
                raise ValueError(f"glyph slot 0x{slot:03X} is outside START.BIN")
            pixels = unpack_glyph(glyph_data)
            glyph = Image.new("L", (WIDTH, HEIGHT))
            glyph.putdata([255 if value else 0 for value in pixels])
            glyph = glyph.resize(
                (cell_width, cell_height),
                Image.Resampling.NEAREST,
            )
            white = Image.new("RGB", glyph.size, "white")
            image.paste(
                white,
                (column * cell_width, row * cell_height),
                glyph,
            )

    for row in range(len(dialogue) + 1):
        y = min(row * cell_height, image.height - 1)
        draw.line((0, y, image.width - 1, y), fill="#394154")
    for column in range(columns + 1):
        x = min(column * cell_width, image.width - 1)
        draw.line((x, 0, x, image.height - 1), fill="#394154")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-bin", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale", type=int, default=8)
    args = parser.parse_args()

    if args.scale < 1:
        parser.error("--scale must be positive")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    render_preview(
        args.start_bin.read_bytes(),
        manifest["dialogue"],
        manifest["mapping"],
        args.output,
        scale=args.scale,
    )
    print(f"output={args.output} scale={args.scale} cell={WIDTH}x{HEIGHT}")


if __name__ == "__main__":
    main()
