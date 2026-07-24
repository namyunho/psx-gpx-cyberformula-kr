#!/usr/bin/env python3
"""Find statically constant calls to the main PS1 scheduled-file loader.

The boot executable calls ``sub_80041294(descriptor_index)``.  On MIPS the
constant argument is commonly assigned either immediately before the call or
in its delay slot.  This scanner reports only locally provable constants and
leaves register-derived arguments unresolved.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from capstone import CS_ARCH_MIPS, CS_MODE_LITTLE_ENDIAN, CS_MODE_MIPS32, Cs

try:
    from scripts.psx_layout import PsxExe
except ModuleNotFoundError:  # Direct execution from the repository root.
    from psx_layout import PsxExe


LOADER_ADDRESS = 0x80041294
ARGUMENT_PATTERN = re.compile(
    r"^\$a0,\s*(?:\$zero,\s*)?(?P<value>-?0x[0-9a-f]+|-?\d+)$"
)


def direct_a0_constant(mnemonic: str, operands: str) -> int | None:
    if mnemonic not in {"addiu", "ori", "li"}:
        return None
    match = ARGUMENT_PATTERN.match(operands)
    if match is None:
        return None
    return int(match.group("value"), 0) & 0xFFFFFFFF


def scan_loader_calls(
    code: bytes,
    base_address: int,
    *,
    loader_address: int = LOADER_ADDRESS,
) -> list[dict[str, Any]]:
    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    decoder.skipdata = True
    instructions = list(decoder.disasm(code, base_address))
    result = []
    for index, instruction in enumerate(instructions):
        if (
            instruction.mnemonic != "jal"
            or int(instruction.op_str, 0) != loader_address
        ):
            continue
        candidates = []
        if index + 1 < len(instructions):
            candidates.append(instructions[index + 1])
        candidates.extend(reversed(instructions[max(0, index - 5) : index]))
        descriptor_index = None
        proof_address = None
        for candidate in candidates:
            descriptor_index = direct_a0_constant(
                candidate.mnemonic, candidate.op_str
            )
            if descriptor_index is not None:
                proof_address = candidate.address
                break
        result.append(
            {
                "call_address": instruction.address,
                "descriptor_index": descriptor_index,
                "argument_proof_address": proof_address,
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "exe",
        nargs="?",
        type=Path,
        default=Path("work/disc1/full/SLPS_019.58"),
    )
    parser.add_argument("--descriptor", type=lambda value: int(value, 0))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    exe = PsxExe(args.exe.read_bytes())
    code = exe.read(exe.load_address, exe.text_size)
    calls = scan_loader_calls(code, exe.load_address)
    if args.descriptor is not None:
        calls = [
            call
            for call in calls
            if call["descriptor_index"] == args.descriptor
        ]
    if args.json:
        print(json.dumps(calls, indent=2))
        return
    for call in calls:
        descriptor = call["descriptor_index"]
        rendered = "unresolved" if descriptor is None else str(descriptor)
        proof = call["argument_proof_address"]
        proof_text = "" if proof is None else f" proof=0x{proof:08X}"
        print(
            f"call=0x{call['call_address']:08X} "
            f"descriptor={rendered}{proof_text}"
        )


if __name__ == "__main__":
    main()
