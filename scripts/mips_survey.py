#!/usr/bin/env python3
"""Survey PS1 MIPS binaries for ASCII anchors and direct BIOS call stubs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct

from capstone import CS_ARCH_MIPS, CS_MODE_LITTLE_ENDIAN, CS_MODE_MIPS32, Cs


def load_code(path: Path, raw_base: int | None) -> tuple[bytes, int, dict[str, int]]:
    data = path.read_bytes()
    if data[:8] == b"PS-X EXE":
        entry, gp, load_address, text_size = struct.unpack_from("<4I", data, 0x10)
        code = data[0x800 : 0x800 + text_size]
        return code, load_address, {
            "entry": entry,
            "gp": gp,
            "load_address": load_address,
            "text_size": text_size,
        }
    if raw_base is None:
        raw_base = 0
    return data, raw_base, {"load_address": raw_base, "text_size": len(data)}


def ascii_strings(data: bytes, minimum: int) -> list[dict[str, object]]:
    pattern = rb"[ -~]{" + str(minimum).encode("ascii") + rb",}"
    return [
        {"offset": match.start(), "text": match.group().decode("ascii")}
        for match in re.finditer(pattern, data)
    ]


def bios_b_stubs(code: bytes, base: int) -> list[dict[str, object]]:
    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    decoder.skipdata = True
    instructions = list(decoder.disasm(code, base))
    result = []
    for index, instruction in enumerate(instructions):
        if instruction.mnemonic != "addiu" or instruction.op_str != "$t2, $zero, 0xb0":
            continue
        for candidate in instructions[index : index + 4]:
            prefix = "$t1, $zero, "
            if candidate.mnemonic == "addiu" and candidate.op_str.startswith(prefix):
                result.append(
                    {
                        "address": instruction.address,
                        "function": int(candidate.op_str[len(prefix) :], 0),
                    }
                )
                break
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("--base", type=lambda value: int(value, 0))
    parser.add_argument("--min-string", type=int, default=8)
    args = parser.parse_args()

    path = Path(args.binary)
    code, base, metadata = load_code(path, args.base)
    result = {
        "path": str(path),
        **metadata,
        "bios_b_stubs": bios_b_stubs(code, base),
        "ascii_strings": ascii_strings(path.read_bytes(), args.min_string),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
