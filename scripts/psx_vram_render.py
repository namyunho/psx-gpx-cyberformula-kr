#!/usr/bin/env python3
"""Render structurally compatible raw PS1 VRAM records as review sheets.

The renderer uses the structural inventory from :mod:`scripts.psx_layout`.
Whole-unit rectangles are decoded as direct 16-bit BGR555.  Container images
are paired with 256x1 CLUTs as 8bpp or with 16x16 CLUT banks as 4bpp.  It does
not guess a palette when no structurally compatible CLUT exists.  These sheets
are visual triage evidence; they do not by themselves prove a runtime consumer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Iterable

from PIL import Image, ImageDraw

try:
    from scripts.psx_layout import (
        PsxExe,
        EMBEDDED_SCHEDULE_SPECS,
        SCHEDULE_SPECS,
        classify_child,
        discover_schedule,
        discover_schedule_bytes,
        parse_offset_directory,
    )
except ModuleNotFoundError:  # Direct execution from the repository root.
    from psx_layout import (
        PsxExe,
        EMBEDDED_SCHEDULE_SPECS,
        SCHEDULE_SPECS,
        classify_child,
        discover_schedule,
        discover_schedule_bytes,
        parse_offset_directory,
    )


@dataclass(frozen=True)
class VramRecord:
    unit_index: int
    child_index: int | None
    x: int
    y: int
    width_halfwords: int
    height: int
    payload: bytes


@dataclass
class Preview:
    label: str
    image: Image.Image


def bgr555_color(value: int) -> tuple[int, int, int, int]:
    red = (value & 0x1F) * 255 // 31
    green = ((value >> 5) & 0x1F) * 255 // 31
    blue = ((value >> 10) & 0x1F) * 255 // 31
    alpha = 0 if value & 0x7FFF == 0 else 255
    return red, green, blue, alpha


def decode_direct16(record: VramRecord) -> Image.Image:
    expected = record.width_halfwords * record.height * 2
    if len(record.payload) != expected:
        raise ValueError(f"direct16 payload mismatch: {len(record.payload)} != {expected}")
    colors = [
        bgr555_color(value)
        for (value,) in struct.iter_unpack("<H", record.payload)
    ]
    image = Image.new("RGBA", (record.width_halfwords, record.height))
    image.putdata(colors)
    return image


def decode_indexed(
    record: VramRecord, palette_words: list[int], bits_per_pixel: int
) -> Image.Image:
    if bits_per_pixel == 8:
        width = record.width_halfwords * 2
        indices = list(record.payload)
        required_colors = 256
    elif bits_per_pixel == 4:
        width = record.width_halfwords * 4
        indices = []
        for value in record.payload:
            indices.extend((value & 0xF, value >> 4))
        required_colors = 16
    else:
        raise ValueError(f"unsupported indexed depth: {bits_per_pixel}")
    if len(palette_words) != required_colors:
        raise ValueError(
            f"{bits_per_pixel}bpp palette has {len(palette_words)} colors, "
            f"expected {required_colors}"
        )
    expected = width * record.height
    if len(indices) != expected:
        raise ValueError(f"indexed payload mismatch: {len(indices)} != {expected}")
    palette = [bgr555_color(value) for value in palette_words]
    image = Image.new("RGBA", (width, record.height))
    image.putdata([palette[index] for index in indices])
    return image


def record_from_bytes(
    raw: bytes, unit_index: int, child_index: int | None
) -> VramRecord:
    classified = classify_child(raw)
    if classified["kind"] != "raw_vram_rectangle":
        raise ValueError("record did not pass the raw VRAM structural check")
    rect = classified["rect"]
    payload_size = classified["payload_size"]
    return VramRecord(
        unit_index=unit_index,
        child_index=child_index,
        x=rect["x"],
        y=rect["y"],
        width_halfwords=rect["width_halfwords"],
        height=rect["height"],
        payload=raw[8 : 8 + payload_size],
    )


def unit_records(unit: bytes, unit_index: int) -> list[VramRecord]:
    whole = classify_child(unit)
    if whole["kind"] == "raw_vram_rectangle":
        return [record_from_bytes(unit, unit_index, None)]
    offsets = parse_offset_directory(unit)
    if offsets is None:
        return []
    result = []
    for child_index, (start, end) in enumerate(
        zip(offsets, offsets[1:] + [len(unit)])
    ):
        raw = unit[start:end]
        if classify_child(raw)["kind"] == "raw_vram_rectangle":
            result.append(record_from_bytes(raw, unit_index, child_index))
    return result


def palette_words(record: VramRecord) -> list[int]:
    return [value for (value,) in struct.iter_unpack("<H", record.payload)]


def render_unit(records: list[VramRecord]) -> list[Preview]:
    if not records:
        return []
    if len(records) == 1 and records[0].child_index is None:
        record = records[0]
        return [
            Preview(
                f"u{record.unit_index:04d} root 16bpp "
                f"{record.width_halfwords}x{record.height}",
                decode_direct16(record),
            )
        ]

    palettes_8 = [
        record
        for record in records
        if record.width_halfwords == 256 and 1 <= record.height <= 16
    ]
    palettes_4 = [
        record
        for record in records
        if record.width_halfwords == 16 and 1 <= record.height <= 16
    ]
    images = [record for record in records if record.height > 16]
    previews = []
    for image_record in images:
        for palette_record in palettes_8:
            words = palette_words(palette_record)
            for row in range(palette_record.height):
                previews.append(
                    Preview(
                        f"u{image_record.unit_index:04d} c{image_record.child_index} "
                        f"8bpp p{palette_record.child_index}:{row}",
                        decode_indexed(
                            image_record,
                            words[row * 256 : (row + 1) * 256],
                            8,
                        ),
                    )
                )
        for palette_record in palettes_4:
            words = palette_words(palette_record)
            for bank in range(palette_record.height):
                previews.append(
                    Preview(
                        f"u{image_record.unit_index:04d} c{image_record.child_index} "
                        f"4bpp p{palette_record.child_index}:{bank}",
                        decode_indexed(
                            image_record, words[bank * 16 : (bank + 1) * 16], 4
                        ),
                    )
                )
    return previews


def iter_file_previews(
    data: bytes, schedule: list[dict[str, int]]
) -> Iterable[Preview]:
    for span in schedule:
        unit = data[span["byte_offset"] : span["byte_end"]]
        yield from render_unit(unit_records(unit, span["index"]))


def fit_preview(image: Image.Image, width: int, height: int) -> Image.Image:
    background = Image.new("RGB", (width, height), (32, 32, 36))
    opaque = Image.new("RGBA", image.size, (0, 0, 0, 255))
    opaque.alpha_composite(image)
    opaque.thumbnail((width, height), Image.Resampling.NEAREST)
    x = (width - opaque.width) // 2
    y = (height - opaque.height) // 2
    background.paste(opaque.convert("RGB"), (x, y))
    return background


def write_contact_sheets(
    previews: Iterable[Preview],
    output: Path,
    stem: str,
    page_size: int,
    columns: int,
    cell_width: int,
    cell_height: int,
) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    rows = (page_size + columns - 1) // columns
    label_height = 22
    page: list[Preview] = []
    paths = []

    def flush() -> None:
        if not page:
            return
        sheet = Image.new(
            "RGB",
            (columns * cell_width, rows * (cell_height + label_height)),
            (18, 18, 20),
        )
        draw = ImageDraw.Draw(sheet)
        for index, preview in enumerate(page):
            column = index % columns
            row = index // columns
            x = column * cell_width
            y = row * (cell_height + label_height)
            sheet.paste(fit_preview(preview.image, cell_width, cell_height), (x, y))
            draw.text((x + 3, y + cell_height + 3), preview.label, fill=(235, 235, 235))
        path = output / f"{stem}-page-{len(paths) + 1:03d}.png"
        sheet.save(path)
        paths.append(path)
        page.clear()

    for preview in previews:
        page.append(preview)
        if len(page) == page_size:
            flush()
    flush()
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disc-root", type=Path, default=Path("work/disc1/full"))
    parser.add_argument("--output", type=Path, default=Path("work/analysis/vram"))
    parser.add_argument(
        "--file",
        action="append",
        help="scheduled filename to render; repeatable (default: all except SOUND/ALLBIN)",
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--columns", type=int, default=10)
    parser.add_argument("--cell-width", type=int, default=192)
    parser.add_argument("--cell-height", type=int, default=144)
    args = parser.parse_args()

    if args.page_size <= 0 or args.columns <= 0:
        parser.error("page size and columns must be positive")
    exe = PsxExe((args.disc_root / "SLPS_019.58").read_bytes())
    selected = (
        {name.upper() for name in args.file}
        if args.file
        else {
            spec.filename
            for spec in (*SCHEDULE_SPECS, *EMBEDDED_SCHEDULE_SPECS)
            if spec.filename not in {"SOUND.BIN", "ALLBIN.BIN"}
        }
    )
    for spec in SCHEDULE_SPECS:
        if spec.filename.upper() not in selected:
            continue
        path = args.disc_root / spec.filename
        data = path.read_bytes()
        schedule = discover_schedule(
            exe, spec.table_va, spec.table_limit_va, len(data)
        )
        paths = write_contact_sheets(
            iter_file_previews(data, schedule),
            args.output,
            spec.filename.rsplit(".", 1)[0],
            args.page_size,
            args.columns,
            args.cell_width,
            args.cell_height,
        )
        print(f"{spec.filename}: {len(paths)} contact sheets")
        for output_path in paths:
            print(output_path)
    for spec in EMBEDDED_SCHEDULE_SPECS:
        if spec.filename.upper() not in selected:
            continue
        path = args.disc_root / spec.filename
        data = path.read_bytes()
        container = (args.disc_root / spec.container_filename).read_bytes()
        start = spec.table_file_offset
        end = start + spec.maximum_entries * 4
        schedule = discover_schedule_bytes(
            container[start:end],
            len(data),
            maximum_entries=spec.maximum_entries,
        )
        paths = write_contact_sheets(
            iter_file_previews(data, schedule),
            args.output,
            spec.filename.rsplit(".", 1)[0],
            args.page_size,
            args.columns,
            args.cell_width,
            args.cell_height,
        )
        print(f"{spec.filename}: {len(paths)} contact sheets")
        for output_path in paths:
            print(output_path)


if __name__ == "__main__":
    main()
