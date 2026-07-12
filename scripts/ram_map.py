#!/usr/bin/env python3
"""Map exact disc-file fragments found in a PS1 RAM dump."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import zlib


def build_ram_index(ram: bytes, sample_size: int, stride: int) -> dict[int, list[int]]:
    index: dict[int, list[int]] = defaultdict(list)
    for offset in range(0, len(ram) - sample_size + 1, stride):
        checksum = zlib.crc32(ram[offset : offset + sample_size])
        index[checksum].append(offset)
    return index


def find_mappings(
    ram: bytes,
    source: bytes,
    index: dict[int, list[int]],
    sample_size: int = 64,
    source_stride: int = 4,
    min_unique: int = 12,
) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    for source_offset in range(0, len(source) - sample_size + 1, source_stride):
        sample = source[source_offset : source_offset + sample_size]
        if len(set(sample)) < min_unique:
            continue
        for ram_offset in index.get(zlib.crc32(sample), ()):
            if ram[ram_offset : ram_offset + sample_size] == sample:
                matches.append((source_offset, ram_offset))
    return matches


def summarize_mappings(matches: list[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """Return (load_delta, count, first_source, last_source) groups."""
    groups: dict[int, list[int]] = defaultdict(list)
    for source_offset, ram_offset in matches:
        groups[ram_offset - source_offset].append(source_offset)
    return sorted(
        (
            (delta, len(offsets), min(offsets), max(offsets))
            for delta, offsets in groups.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ram", type=Path)
    parser.add_argument("sources", type=Path, nargs="+")
    parser.add_argument("--ram-base", type=lambda value: int(value, 0), default=0x80000000)
    parser.add_argument("--sample-size", type=int, default=64)
    parser.add_argument("--ram-stride", type=int, default=4)
    parser.add_argument("--source-stride", type=int, default=4)
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()

    ram = args.ram.read_bytes()
    index = build_ram_index(ram, args.sample_size, args.ram_stride)
    for path in args.sources:
        source = path.read_bytes()
        matches = find_mappings(
            ram,
            source,
            index,
            sample_size=args.sample_size,
            source_stride=args.source_stride,
        )
        groups = summarize_mappings(matches)
        print(f"{path.name}: matches={len(matches)} mappings={len(groups)}")
        for delta, count, first, last in groups[: args.top]:
            ram_start = args.ram_base + delta + first
            ram_end = args.ram_base + delta + last + args.sample_size
            print(
                f"  delta={delta:+#x} count={count} "
                f"source=0x{first:X}..0x{last + args.sample_size:X} "
                f"ram=0x{ram_start:08X}..0x{ram_end:08X}"
            )


if __name__ == "__main__":
    main()
