#!/usr/bin/env python3
"""Extract terminator-delimited custom 16-bit text streams losslessly."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct


TERMINATOR = 0xFFFB


def decode_tokens(tokens, glyphs, controls) -> str:
    output = []
    for token in tokens:
        key = f"{token:04X}"
        if key in controls:
            output.append(controls[key])
        elif key in glyphs:
            output.append(glyphs[key])
        else:
            output.append(f"<${key}>")
    return "".join(output)


def extract_entries(data: bytes, start: int, end: int):
    if start % 2 or end % 2:
        raise ValueError("16-bit stream boundaries must be even")
    if not 0 <= start <= end <= len(data):
        raise ValueError("stream boundaries are outside the input")
    position = start
    entry_id = 0
    while position < end:
        entry_start = position
        tokens = []
        terminated = False
        while position < end:
            token = struct.unpack_from("<H", data, position)[0]
            tokens.append(token)
            position += 2
            if token == TERMINATOR:
                terminated = True
                break
        raw = data[entry_start:position]
        yield {
            "entry_id": entry_id,
            "file_offset": f"0x{entry_start:X}",
            "end_offset": f"0x{position:X}",
            "raw_hex": raw.hex().upper(),
            "tokens": [f"{token:04X}" for token in tokens],
            "terminated": terminated,
            "ko": "",
            "status": "unmapped",
            "notes": None,
            "flags": [] if terminated else ["unterminated-tail"],
        }
        entry_id += 1


def rebuild(entries) -> bytes:
    return b"".join(bytes.fromhex(entry["raw_hex"]) for entry in entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--start", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--end", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--output", required=True)
    parser.add_argument("--glyph-map", type=Path)
    args = parser.parse_args()

    path = Path(args.input)
    data = path.read_bytes()
    entries = list(extract_entries(data, args.start, args.end))
    glyph_map = None
    if args.glyph_map:
        glyph_map = json.loads(args.glyph_map.read_text(encoding="utf-8"))
        glyphs = glyph_map.get("glyphs", {})
        controls = glyph_map.get("controls", {})
        for entry in entries:
            entry["jp"] = decode_tokens(
                (int(token, 16) for token in entry["tokens"]), glyphs, controls
            )
    rebuilt = rebuild(entries)
    original = data[args.start : args.end]
    if rebuilt != original:
        raise RuntimeError("extract/rebuild round-trip mismatch")
    result = {
        "source": str(path),
        "start": f"0x{args.start:X}",
        "end": f"0x{args.end:X}",
        "encoding": "unmapped-u16le",
        "terminator": f"{TERMINATOR:04X}",
        "round_trip": True,
        "glyph_map": str(args.glyph_map) if args.glyph_map else None,
        "entries": entries,
    }
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"entries={len(entries)} bytes={len(original)} round_trip=true")


if __name__ == "__main__":
    main()
