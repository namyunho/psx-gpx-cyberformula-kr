#!/usr/bin/env python3
"""Dump an arbitrary PS1 file or RAM region as hex, text, and optional LE u16."""

from __future__ import annotations

import argparse
from pathlib import Path


def text_column(data: bytes, encoding: str) -> str:
    if encoding == "ascii":
        return "".join(chr(value) if 0x20 <= value <= 0x7E else "." for value in data)
    decoded = data.decode(encoding, errors="replace")
    return "".join(character if character.isprintable() else "." for character in decoded)


def dump_rows(
    data: bytes,
    *,
    start: int = 0,
    width: int = 16,
    encoding: str = "shift_jis",
    show_u16: bool = False,
) -> list[str]:
    if width <= 0:
        raise ValueError("width must be positive")
    rows = []
    for offset in range(0, len(data), width):
        row = data[offset : offset + width]
        hex_values = " ".join(f"{value:02X}" for value in row)
        parts = [
            f"{start + offset:08X}",
            f"{hex_values:<{width * 3 - 1}}",
            text_column(row, encoding),
        ]
        if show_u16:
            words = [
                int.from_bytes(row[index : index + 2], "little")
                for index in range(0, len(row) - 1, 2)
            ]
            parts.append(" ".join(f"{word:04X}" for word in words))
        rows.append("  ".join(parts))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--start", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--length", type=lambda value: int(value, 0))
    parser.add_argument("--width", type=int, default=16)
    parser.add_argument("--encoding", choices=("ascii", "shift_jis"), default="shift_jis")
    parser.add_argument("--u16le", action="store_true")
    args = parser.parse_args()

    with args.input.open("rb") as source:
        source.seek(args.start)
        data = source.read() if args.length is None else source.read(args.length)
    try:
        rows = dump_rows(
            data,
            start=args.start,
            width=args.width,
            encoding=args.encoding,
            show_u16=args.u16le,
        )
    except ValueError as error:
        parser.error(str(error))
    print("\n".join(rows))


if __name__ == "__main__":
    main()
