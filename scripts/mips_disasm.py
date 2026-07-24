#!/usr/bin/env python3
"""Linear little-endian MIPS disassembly for PS-X EXE payloads and raw overlays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from capstone import CS_ARCH_MIPS, CS_MODE_LITTLE_ENDIAN, CS_MODE_MIPS32, Cs

try:
    from scripts.mips_survey import load_code
except ModuleNotFoundError:  # Direct execution from the repository root.
    from mips_survey import load_code


DELAY_SLOT_MNEMONICS = {
    "b",
    "bal",
    "beq",
    "beql",
    "bgez",
    "bgezal",
    "bgezall",
    "bgezl",
    "bgtz",
    "bgtzl",
    "blez",
    "blezl",
    "bltz",
    "bltzal",
    "bltzall",
    "bltzl",
    "bne",
    "bnel",
    "j",
    "jal",
    "jalr",
    "jr",
}


def has_delay_slot(mnemonic: str) -> bool:
    return mnemonic in DELAY_SLOT_MNEMONICS


def disassemble(
    code: bytes,
    address: int,
    *,
    file_offset: int = 0,
) -> list[dict[str, Any]]:
    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    decoder.skipdata = True
    rows: list[dict[str, Any]] = []
    next_is_delay_slot = False
    for instruction in decoder.disasm(code, address):
        rows.append(
            {
                "address": f"0x{instruction.address:08X}",
                "file_offset": f"0x{file_offset + instruction.address - address:X}",
                "bytes": instruction.bytes.hex().upper(),
                "mnemonic": instruction.mnemonic,
                "operands": instruction.op_str,
                "delay_slot": next_is_delay_slot,
            }
        )
        next_is_delay_slot = has_delay_slot(instruction.mnemonic)
    return rows


def disassemble_binary(
    path: Path,
    *,
    raw_base: int | None = None,
    start_address: int | None = None,
    start_offset: int | None = None,
    count: int = 0x100,
) -> dict[str, Any]:
    code, base, metadata = load_code(path, raw_base)
    if start_address is not None and start_offset is not None:
        raise ValueError("choose either start_address or start_offset")
    offset = start_offset if start_offset is not None else 0
    if start_address is not None:
        offset = start_address - base
    if offset < 0 or offset >= len(code):
        raise ValueError(f"start is outside loaded code: offset=0x{offset:X}")
    if count <= 0:
        raise ValueError("count must be positive")

    with path.open("rb") as source:
        payload_file_offset = 0x800 if source.read(8) == b"PS-X EXE" else 0
    window = code[offset : offset + count]
    address = base + offset
    return {
        "path": str(path),
        **metadata,
        "start_address": address,
        "start_file_offset": payload_file_offset + offset,
        "requested_bytes": count,
        "decoded_bytes": len(window),
        "instructions": disassemble(
            window,
            address,
            file_offset=payload_file_offset + offset,
        ),
    }


def print_listing(result: dict[str, Any]) -> None:
    print(
        f"{result['path']}: address=0x{result['start_address']:08X} "
        f"file=0x{result['start_file_offset']:X}"
    )
    for row in result["instructions"]:
        delay = " [delay]" if row["delay_slot"] else ""
        print(
            f"{row['address']}  {row['file_offset']:>10}  {row['bytes']:<10}  "
            f"{row['mnemonic']:<8} {row['operands']}{delay}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--base", type=lambda value: int(value, 0))
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--address", type=lambda value: int(value, 0))
    start.add_argument("--offset", type=lambda value: int(value, 0))
    parser.add_argument("--count", type=lambda value: int(value, 0), default=0x100)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = disassemble_binary(
            args.binary,
            raw_base=args.base,
            start_address=args.address,
            start_offset=args.offset,
            count=args.count,
        )
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_listing(result)


if __name__ == "__main__":
    main()
