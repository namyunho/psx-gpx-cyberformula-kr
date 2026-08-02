#!/usr/bin/env python3
"""Patch the primary PS1 text renderer with selected 8 px advances."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


RENDERER_START = 0x80032704
RENDERER_END = 0x800329B8
# The executable payload loads at 0x80030000 from file +0x800, so file offset
# zero maps to 0x8002F800 when armips patches the complete PS-X EXE.
EXE_FILE_BASE = 0x8002F800
HALFWIDTH_CHARACTERS = " !(),.?"
HALFWIDTH_GLYPHS = {
    " ": 0x046,
    "!": 0x047,
    "(": 0x04B,
    ")": 0x04C,
    ",": 0x04D,
    ".": 0x04F,
    "?": 0x050,
}
FULL_ADVANCE_PX = 14
HALF_ADVANCE_PX = 8


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def armips_string(path: Path) -> str:
    return '"' + str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"') + '"'


def patch_renderer(source: Path, output: Path, assembly: Path) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    before = output.read_bytes()
    with tempfile.TemporaryDirectory(prefix="psx-halfwidth-") as temporary:
        wrapper = Path(temporary) / "patch.asm"
        wrapper.write_text(
            f"INPUT_EXE equ {armips_string(output)}\n"
            f'.include "{assembly.resolve()}"\n',
            encoding="utf-8",
        )
        subprocess.run(
            ["armips", "-erroronwarning", str(wrapper)],
            check=True,
            cwd=assembly.parent.parent,
        )
    after = output.read_bytes()
    if len(after) != len(before):
        raise ValueError("PS-X EXE size changed")
    start = RENDERER_START - EXE_FILE_BASE
    end = RENDERER_END - EXE_FILE_BASE
    changed = [index for index, (a, b) in enumerate(zip(before, after)) if a != b]
    if not changed:
        raise ValueError("renderer patch changed no bytes")
    if min(changed) < start or max(changed) >= end:
        raise ValueError("renderer patch wrote outside sub_80032704")
    return {
        "changed_byte_count": len(changed),
        "expected_file_range": [f"0x{start:X}", f"0x{end:X}"],
        "first_changed_file_offset": f"0x{min(changed):X}",
        "last_changed_file_offset": f"0x{max(changed):X}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--assembly",
        type=Path,
        default=Path("asm/halfwidth-dialogue-renderer.asm"),
    )
    args = parser.parse_args()

    source_exe = args.input_dir / "SLPS_019.58"
    if not source_exe.is_file():
        parser.error(f"missing input executable: {source_exe}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    base_manifest_path = args.input_dir / "manifest.json"
    if not base_manifest_path.is_file():
        parser.error(f"missing input manifest: {base_manifest_path}")
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    declared_outputs = base_manifest.get("outputs", {})
    if "SLPS_019.58" not in declared_outputs:
        parser.error("input manifest does not declare SLPS_019.58")

    copy_names = set(declared_outputs)
    copy_names.add("primary-korean-glyph-map.json")
    for name in sorted(copy_names - {"SLPS_019.58"}):
        source = args.input_dir / name
        if source.exists():
            shutil.copyfile(source, args.output_dir / name)

    output_exe = args.output_dir / "SLPS_019.58"
    patch = patch_renderer(source_exe, output_exe, args.assembly)
    manifest = base_manifest
    manifest["outputs"]["SLPS_019.58"]["sha256"] = sha256(output_exe)
    manifest["halfwidth_renderer"] = {
            "status": "runtime-validation-required",
            "base_file_build": str(args.input_dir.resolve()),
            "base_manifest_sha256": sha256(base_manifest_path),
            "source_exe_sha256": sha256(source_exe),
            "output_exe_sha256": sha256(output_exe),
            "function": "sub_80032704",
            "range": [f"0x{RENDERER_START:08X}", f"0x{RENDERER_END:08X}"],
            "logical_layout_unchanged": True,
            "dialogue_source_bytes_unchanged": True,
            "explicit_line_breaks_unchanged": True,
            "name_substitution_inherits_reduction": True,
            "name_substitution_advance_px": FULL_ADVANCE_PX,
            "full_advance_px": FULL_ADVANCE_PX,
            "half_advance_px": HALF_ADVANCE_PX,
            "halfwidth_characters": list(HALFWIDTH_CHARACTERS),
            "halfwidth_glyphs": {key: f"0x{value:03X}" for key, value in HALFWIDTH_GLYPHS.items()},
            "state_address": "0x8002FFFC",
            **patch,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
