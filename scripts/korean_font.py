#!/usr/bin/env python3
"""Inspect and convert 16x16, 1bpp Korean glyphs for the PS1 font."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.psx_font import HEIGHT, WIDTH, pack_glyph
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from psx_font import HEIGHT, WIDTH, pack_glyph


SOURCE_WIDTH = 16
SOURCE_HEIGHT = 16
SOURCE_GLYPH_SIZE = 32


def unpack_mono_glyph(data: bytes, *, byte_order: str = "big") -> list[int]:
    """Decode one 16x16 glyph stored as two bytes per row, MSB first."""
    if len(data) != SOURCE_GLYPH_SIZE:
        raise ValueError(f"glyph must be exactly {SOURCE_GLYPH_SIZE} bytes")
    if byte_order not in {"big", "little"}:
        raise ValueError("byte_order must be 'big' or 'little'")

    pixels: list[int] = []
    for row in range(SOURCE_HEIGHT):
        word = int.from_bytes(data[row * 2 : row * 2 + 2], byte_order)
        pixels.extend((word >> (15 - column)) & 1 for column in range(SOURCE_WIDTH))
    return pixels


def crop_to_psx(pixels: list[int], *, intensity: int = 7) -> list[int]:
    """Remove the one-pixel border and convert 1bpp pixels to game 3bpp."""
    if len(pixels) != SOURCE_WIDTH * SOURCE_HEIGHT:
        raise ValueError("source glyph must contain exactly 256 pixels")
    if not 1 <= intensity <= 7:
        raise ValueError("intensity must be between 1 and 7")
    return [
        pixels[row * SOURCE_WIDTH + column] * intensity
        for row in range(1, HEIGHT + 1)
        for column in range(1, WIDTH + 1)
    ]


def bounding_box(pixels: list[int]) -> tuple[int, int, int, int] | None:
    points = [
        (index % SOURCE_WIDTH, index // SOURCE_WIDTH)
        for index, value in enumerate(pixels)
        if value
    ]
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def render_preview(
    glyphs: list[tuple[str, list[int]]], output: Path, scale: int = 8
) -> None:
    from PIL import Image, ImageDraw

    cell_width = SOURCE_WIDTH * scale + 16
    cell_height = SOURCE_HEIGHT * scale + 38
    sheet = Image.new("RGB", (cell_width * len(glyphs), cell_height), "#202020")
    draw = ImageDraw.Draw(sheet)
    for position, (character, pixels) in enumerate(glyphs):
        glyph = Image.new("L", (SOURCE_WIDTH, SOURCE_HEIGHT))
        glyph.putdata([value * 255 for value in pixels])
        glyph = glyph.resize(
            (SOURCE_WIDTH * scale, SOURCE_HEIGHT * scale),
            Image.Resampling.NEAREST,
        ).convert("RGB")
        x = position * cell_width + 8
        draw.text((x, 4), character, fill="white")
        sheet.paste(glyph, (x, 26))
        # The red rectangle is the retained 14x14 game area.
        draw.rectangle(
            (x + scale - 1, 26 + scale - 1, x + 15 * scale, 26 + 15 * scale),
            outline="#ff4040",
            width=2,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--glyph-map", type=Path, required=True)
    parser.add_argument("--text", default="시바세이치로")
    parser.add_argument("--byte-order", choices=("big", "little"), default="big")
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--packed-output", type=Path)
    args = parser.parse_args()

    source = args.input.read_bytes()
    mapping = json.loads(args.glyph_map.read_text(encoding="utf-8"))
    if len(source) % SOURCE_GLYPH_SIZE:
        parser.error("input size is not a multiple of 32 bytes")

    glyphs: list[tuple[str, list[int]]] = []
    packed = bytearray()
    for character in args.text:
        if character not in mapping:
            parser.error(f"character is absent from glyph map: {character!r}")
        index = int(mapping[character])
        start = index * SOURCE_GLYPH_SIZE
        pixels = unpack_mono_glyph(
            source[start : start + SOURCE_GLYPH_SIZE], byte_order=args.byte_order
        )
        glyphs.append((character, pixels))
        packed.extend(pack_glyph(crop_to_psx(pixels)))
        print(
            f"U+{ord(character):04X} index={index} bbox={bounding_box(pixels)}"
        )

    if args.preview:
        render_preview(glyphs, args.preview)
    if args.packed_output:
        args.packed_output.parent.mkdir(parents=True, exist_ok=True)
        args.packed_output.write_bytes(packed)
    print(
        f"glyphs={len(glyphs)} source=16x16/1bpp output=14x14/3bpp "
        f"packed_bytes={len(packed)}"
    )


if __name__ == "__main__":
    main()
