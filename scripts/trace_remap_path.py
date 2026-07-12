#!/usr/bin/env python3
"""Trace the dialogue remap/display-buffer state from a PS1 RAM dump.

The script is intentionally read-only. It consumes RAM dumps and extracted
executables from the local analysis workspace and writes only derived reports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
from typing import Iterable


RAM_BASE = 0x80000000
DEFAULT_TEXT_ROOT_SLOT = 0x80061158
DEFAULT_CURSOR_ROOT_SLOT = 0x80060FA0
DEFAULT_DIALOGUE_RAM = 0x800A8054
DEFAULT_DIALOGUE_TOKENS = 34
DEFAULT_WATCH_ADDRESSES = (
    DEFAULT_TEXT_ROOT_SLOT,
    DEFAULT_CURSOR_ROOT_SLOT,
    0x8001425A,
    0x8001426C,
    DEFAULT_DIALOGUE_RAM,
)

REG_NAMES = [
    "zero",
    "at",
    "v0",
    "v1",
    "a0",
    "a1",
    "a2",
    "a3",
    "t0",
    "t1",
    "t2",
    "t3",
    "t4",
    "t5",
    "t6",
    "t7",
    "s0",
    "s1",
    "s2",
    "s3",
    "s4",
    "s5",
    "s6",
    "s7",
    "t8",
    "t9",
    "k0",
    "k1",
    "gp",
    "sp",
    "fp",
    "ra",
]


def signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def read_exe(path: Path, raw_base: int | None = None) -> tuple[bytes, int, dict[str, int | str]]:
    data = path.read_bytes()
    if data[:8] == b"PS-X EXE":
        entry, gp, load_address, text_size = struct.unpack_from("<4I", data, 0x10)
        return data[0x800 : 0x800 + text_size], load_address, {
            "path": str(path),
            "entry": entry,
            "gp": gp,
            "load_address": load_address,
            "text_size": text_size,
            "format": "PS-X EXE",
        }
    base = 0 if raw_base is None else raw_base
    return data, base, {
        "path": str(path),
        "load_address": base,
        "text_size": len(data),
        "format": "raw",
    }


class RamView:
    def __init__(self, data: bytes, base: int = RAM_BASE) -> None:
        self.data = data
        self.base = base

    def offset(self, address: int, size: int = 1) -> int:
        offset = address - self.base
        if not 0 <= offset <= len(self.data) - size:
            raise ValueError(f"RAM address 0x{address:08X} is outside the dump")
        return offset

    def contains(self, address: int, size: int = 1) -> bool:
        try:
            self.offset(address, size)
        except ValueError:
            return False
        return True

    def u16(self, address: int) -> int:
        return struct.unpack_from("<H", self.data, self.offset(address, 2))[0]

    def u32(self, address: int) -> int:
        return struct.unpack_from("<I", self.data, self.offset(address, 4))[0]

    def u16_list(self, address: int, count: int) -> list[int]:
        return [self.u16(address + index * 2) for index in range(count)]


def token_hex(token: int) -> str:
    return f"0x{token:04X}"


def address_hex(address: int | None) -> str | None:
    return None if address is None else f"0x{address:08X}"


def safe_u16_list(ram: RamView, address: int | None, count: int) -> list[int] | None:
    if address is None or not ram.contains(address, count * 2):
        return None
    return ram.u16_list(address, count)


def trace_ram_state(
    ram: RamView,
    *,
    text_root_slot: int = DEFAULT_TEXT_ROOT_SLOT,
    cursor_root_slot: int = DEFAULT_CURSOR_ROOT_SLOT,
    dialogue_ram: int = DEFAULT_DIALOGUE_RAM,
    dialogue_tokens: int = DEFAULT_DIALOGUE_TOKENS,
    remap_preview: int = 48,
) -> dict[str, object]:
    text_state = ram.u32(text_root_slot)
    cursor_state = ram.u32(cursor_root_slot)
    source_base = ram.u32(text_state) if ram.contains(text_state, 4) else None
    cursor_value = ram.u16(cursor_state) if ram.contains(cursor_state, 2) else None
    cursor_target = (
        source_base + cursor_value * 2
        if source_base is not None and cursor_value is not None
        else None
    )

    source_tokens = safe_u16_list(ram, dialogue_ram, dialogue_tokens)
    state_tokens = safe_u16_list(ram, text_state, remap_preview)
    cursor_tokens = safe_u16_list(ram, cursor_state, min(16, remap_preview))
    remap_entries = safe_u16_list(ram, text_state + 4, dialogue_tokens) if source_base else None

    rows = []
    if source_tokens is not None:
        for index, source_token in enumerate(source_tokens):
            remap_entry = None if remap_entries is None else remap_entries[index]
            rows.append(
                {
                    "index": index,
                    "source_address": address_hex(dialogue_ram + index * 2),
                    "source_token": token_hex(source_token),
                    "candidate_remap_address": address_hex(text_state + 4 + index * 2)
                    if source_base
                    else None,
                    "candidate_remap_entry": None if remap_entry is None else token_hex(remap_entry),
                    "same_as_source": None if remap_entry is None else remap_entry == source_token,
                }
            )

    return {
        "text_root_slot": address_hex(text_root_slot),
        "text_state": address_hex(text_state),
        "cursor_root_slot": address_hex(cursor_root_slot),
        "cursor_state": address_hex(cursor_state),
        "source_base_from_text_state": address_hex(source_base),
        "expected_dialogue_ram": address_hex(dialogue_ram),
        "source_base_matches_expected": source_base == dialogue_ram,
        "cursor_value_u16": None if cursor_value is None else token_hex(cursor_value),
        "cursor_target_from_source_base": address_hex(cursor_target),
        "cursor_target_delta_bytes": None
        if cursor_target is None
        else cursor_target - dialogue_ram,
        "source_tokens": None if source_tokens is None else [token_hex(value) for value in source_tokens],
        "text_state_preview_u16": None
        if state_tokens is None
        else [token_hex(value) for value in state_tokens],
        "cursor_state_preview_u16": None
        if cursor_tokens is None
        else [token_hex(value) for value in cursor_tokens],
        "token_rows": rows,
    }


def instruction_fields(word: int) -> dict[str, int]:
    return {
        "op": (word >> 26) & 0x3F,
        "rs": (word >> 21) & 0x1F,
        "rt": (word >> 16) & 0x1F,
        "rd": (word >> 11) & 0x1F,
        "imm": word & 0xFFFF,
        "funct": word & 0x3F,
    }


def watch_hit(address: int, watch_addresses: Iterable[int], window: int) -> int | None:
    for watched in watch_addresses:
        if watched - window <= address <= watched + window:
            return watched
    return None


def scan_mips_references(
    code: bytes,
    base: int,
    watch_addresses: Iterable[int],
    *,
    window: int = 0,
) -> list[dict[str, object]]:
    watch = tuple(watch_addresses)
    register_values: list[int | None] = [None] * 32
    hits: list[dict[str, object]] = []

    for offset in range(0, len(code) - 3, 4):
        pc = base + offset
        word = struct.unpack_from("<I", code, offset)[0]
        fields = instruction_fields(word)
        op = fields["op"]
        rs = fields["rs"]
        rt = fields["rt"]
        imm = fields["imm"]

        kind = None
        effective = None

        if op == 0x0F:  # lui
            effective = imm << 16
            register_values[rt] = effective
            kind = "load-upper"
        elif op in (0x0D, 0x09):  # ori, addiu
            base_value = register_values[rs]
            if base_value is not None:
                immediate = imm if op == 0x0D else signed16(imm)
                effective = (base_value + immediate) & 0xFFFFFFFF
                kind = "compose-address"
            register_values[rt] = effective
        elif op in (0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B):  # load/store
            base_value = register_values[rs]
            if base_value is not None:
                effective = (base_value + signed16(imm)) & 0xFFFFFFFF
                kind = "memory-access"
            if op in (0x20, 0x21, 0x23, 0x24, 0x25):
                register_values[rt] = None
        elif op == 0 and fields["funct"] in (0x21, 0x23):  # addu/subu
            register_values[fields["rd"]] = None

        if effective is not None:
            watched = watch_hit(effective, watch, window)
            if watched is not None:
                hits.append(
                    {
                        "pc": address_hex(pc),
                        "word": f"0x{word:08X}",
                        "kind": kind,
                        "effective_address": address_hex(effective),
                        "watched_address": address_hex(watched),
                        "register": REG_NAMES[rt],
                    }
                )

    return hits


def parse_address_list(values: list[str] | None) -> list[int]:
    if not values:
        return list(DEFAULT_WATCH_ADDRESSES)
    return [int(value, 0) for value in values]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ram", type=Path, help="2 MiB PS1 RAM dump captured on the first dialogue")
    parser.add_argument("--ram-base", type=lambda value: int(value, 0), default=RAM_BASE)
    parser.add_argument("--text-root-slot", type=lambda value: int(value, 0), default=DEFAULT_TEXT_ROOT_SLOT)
    parser.add_argument("--cursor-root-slot", type=lambda value: int(value, 0), default=DEFAULT_CURSOR_ROOT_SLOT)
    parser.add_argument("--dialogue-ram", type=lambda value: int(value, 0), default=DEFAULT_DIALOGUE_RAM)
    parser.add_argument("--dialogue-tokens", type=int, default=DEFAULT_DIALOGUE_TOKENS)
    parser.add_argument("--remap-preview", type=int, default=48)
    parser.add_argument("--binary", type=Path, action="append", default=[])
    parser.add_argument("--raw-base", type=lambda value: int(value, 0))
    parser.add_argument("--watch", action="append")
    parser.add_argument("--watch-window", type=lambda value: int(value, 0), default=0x40)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result: dict[str, object] = {"watch_addresses": [address_hex(value) for value in parse_address_list(args.watch)]}

    if args.ram:
        ram = RamView(args.ram.read_bytes(), args.ram_base)
        result["ram"] = {
            "path": str(args.ram),
            "base": address_hex(args.ram_base),
            "size": len(ram.data),
            "state": trace_ram_state(
                ram,
                text_root_slot=args.text_root_slot,
                cursor_root_slot=args.cursor_root_slot,
                dialogue_ram=args.dialogue_ram,
                dialogue_tokens=args.dialogue_tokens,
                remap_preview=args.remap_preview,
            ),
        }

    binary_results = []
    watch_addresses = parse_address_list(args.watch)
    for path in args.binary:
        code, base, metadata = read_exe(path, args.raw_base)
        binary_results.append(
            {
                **metadata,
                "references": scan_mips_references(
                    code,
                    base,
                    watch_addresses,
                    window=args.watch_window,
                ),
            }
        )
    if binary_results:
        result["binaries"] = binary_results

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"output={args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
