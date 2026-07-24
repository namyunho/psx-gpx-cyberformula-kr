#!/usr/bin/env python3
"""Wrap a raw PS1 overlay range in a synthetic PS-X EXE header.

The wrapper is an analysis artifact only.  It lets IDA and Ghidra map an
overlay at the RAM address used by the game without changing the original
container or disc image.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import struct


PSX_EXE_HEADER_SIZE = 0x800
KSEG0_START = 0x80000000
KSEG0_END = 0x80200000


def build_psx_exe(
    payload: bytes,
    *,
    load_address: int,
    entry: int | None = None,
    title: str = "Codex analysis overlay",
) -> bytes:
    """Return ``payload`` preceded by a minimal, bounds-checked PS-X EXE header."""

    if not payload:
        raise ValueError("overlay payload is empty")
    if load_address % 4:
        raise ValueError("load address must be 4-byte aligned")
    if load_address < KSEG0_START or load_address + len(payload) > KSEG0_END:
        raise ValueError("overlay does not fit in the PS1 2 MiB KSEG0 RAM window")

    entry_address = load_address if entry is None else entry
    if not load_address <= entry_address < load_address + len(payload):
        raise ValueError("entry must point inside the overlay payload")
    if entry_address % 4:
        raise ValueError("entry must be 4-byte aligned")

    header = bytearray(PSX_EXE_HEADER_SIZE)
    header[:8] = b"PS-X EXE"
    struct.pack_into(
        "<4I",
        header,
        0x10,
        entry_address,
        0,
        load_address,
        len(payload),
    )
    encoded_title = title.encode("ascii", "replace")[: 0x800 - 0x4C - 1]
    header[0x4C : 0x4C + len(encoded_title)] = encoded_title
    return bytes(header) + payload


def extract_range(path: Path, *, offset: int, size: int) -> bytes:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if size <= 0:
        raise ValueError("size must be positive")
    with path.open("rb") as source:
        source.seek(0, 2)
        file_size = source.tell()
        if offset + size > file_size:
            raise ValueError(
                f"range exceeds input: 0x{offset:X}+0x{size:X} > 0x{file_size:X}"
            )
        source.seek(offset)
        payload = source.read(size)
    if len(payload) != size:
        raise ValueError("short read while extracting overlay")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offset", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--size", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--base", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--entry", type=lambda value: int(value, 0))
    parser.add_argument("--title", default="Codex analysis overlay")
    args = parser.parse_args()

    try:
        payload = extract_range(args.input, offset=args.offset, size=args.size)
        image = build_psx_exe(
            payload,
            load_address=args.base,
            entry=args.entry,
            title=args.title,
        )
    except ValueError as error:
        parser.error(str(error))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(args.output)


if __name__ == "__main__":
    main()
