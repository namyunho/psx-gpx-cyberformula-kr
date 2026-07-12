#!/usr/bin/env python3
"""Find structurally valid PlayStation TIM images and optionally render them."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import struct

from PIL import Image


@dataclass(frozen=True)
class TimImage:
    offset: int
    flags: int
    bpp: int
    image_x: int
    image_y: int
    width_words: int
    height: int
    image_data_offset: int
    image_data_size: int
    clut_data_offset: int | None
    clut_colors: int
    clut_count: int
    end_offset: int

    @property
    def pixel_width(self) -> int:
        return self.width_words * {4: 4, 8: 2, 16: 1, 24: 2 / 3}[self.bpp]


def parse_tim(data: bytes, offset: int) -> TimImage | None:
    if offset < 0 or offset + 20 > len(data):
        return None
    magic, flags = struct.unpack_from("<II", data, offset)
    if magic != 0x10 or flags & ~0xF:
        return None
    mode = flags & 7
    if mode not in {0, 1, 2, 3}:
        return None
    bpp = {0: 4, 1: 8, 2: 16, 3: 24}[mode]
    has_clut = bool(flags & 8)
    if bpp in {4, 8} and not has_clut:
        return None

    position = offset + 8
    clut_data_offset = None
    clut_colors = 0
    clut_count = 0
    if has_clut:
        if position + 12 > len(data):
            return None
        block_size, _, _, clut_colors, clut_count = struct.unpack_from(
            "<I4H", data, position
        )
        if block_size != 12 + clut_colors * clut_count * 2:
            return None
        if clut_colors == 0 or clut_count == 0 or position + block_size > len(data):
            return None
        clut_data_offset = position + 12
        position += block_size

    if position + 12 > len(data):
        return None
    block_size, image_x, image_y, width_words, height = struct.unpack_from(
        "<I4H", data, position
    )
    image_data_size = width_words * height * 2
    if width_words == 0 or height == 0 or block_size != 12 + image_data_size:
        return None
    if position + block_size > len(data):
        return None
    pixel_width = width_words * {4: 4, 8: 2, 16: 1, 24: 2 / 3}[bpp]
    if int(pixel_width) != pixel_width or pixel_width > 4096 or height > 4096:
        return None
    return TimImage(
        offset=offset,
        flags=flags,
        bpp=bpp,
        image_x=image_x,
        image_y=image_y,
        width_words=width_words,
        height=height,
        image_data_offset=position + 12,
        image_data_size=image_data_size,
        clut_data_offset=clut_data_offset,
        clut_colors=clut_colors,
        clut_count=clut_count,
        end_offset=position + block_size,
    )


def scan_tims(data: bytes):
    start = 0
    magic = b"\x10\x00\x00\x00"
    while True:
        offset = data.find(magic, start)
        if offset < 0:
            return
        candidate = parse_tim(data, offset)
        if candidate is not None:
            yield candidate
            start = candidate.end_offset
        else:
            start = offset + 1


def color_555(value: int) -> tuple[int, int, int, int]:
    red = (value & 0x1F) * 255 // 31
    green = ((value >> 5) & 0x1F) * 255 // 31
    blue = ((value >> 10) & 0x1F) * 255 // 31
    alpha = 0 if value == 0 else 255
    return red, green, blue, alpha


def render_tim(data: bytes, tim: TimImage) -> Image.Image:
    width = int(tim.pixel_width)
    raw = data[tim.image_data_offset : tim.image_data_offset + tim.image_data_size]
    if tim.bpp in {4, 8}:
        assert tim.clut_data_offset is not None
        palette_size = 16 if tim.bpp == 4 else 256
        if tim.clut_colors < palette_size:
            raise ValueError("CLUT has fewer colors than the image mode requires")
        values = struct.unpack_from(
            f"<{palette_size}H", data, tim.clut_data_offset
        )
        palette = [color_555(value) for value in values]
        indices = []
        if tim.bpp == 4:
            for value in raw:
                indices.extend((value & 0xF, value >> 4))
        else:
            indices = list(raw)
        image = Image.new("RGBA", (width, tim.height))
        image.putdata([palette[index] for index in indices[: width * tim.height]])
        return image
    if tim.bpp == 16:
        values = struct.unpack(f"<{len(raw) // 2}H", raw)
        image = Image.new("RGBA", (width, tim.height))
        image.putdata([color_555(value) for value in values])
        return image
    pixels = []
    for index in range(0, len(raw) - 2, 3):
        red, green, blue = raw[index : index + 3]
        pixels.append((red, green, blue, 255))
    image = Image.new("RGBA", (width, tim.height))
    image.putdata(pixels[: width * tim.height])
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--render")
    args = parser.parse_args()

    output = Path(args.render) if args.render else None
    if output:
        output.mkdir(parents=True, exist_ok=True)
    results = []
    for name in args.inputs:
        path = Path(name)
        data = path.read_bytes()
        for index, tim in enumerate(scan_tims(data)):
            item = {"file": str(path), **asdict(tim), "pixel_width": tim.pixel_width}
            results.append(item)
            if output:
                render_tim(data, tim).save(
                    output / f"{path.stem}_{index:04d}_{tim.offset:08X}.png"
                )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
