#!/usr/bin/env python3
"""Check the local PS1 analysis, patching, emulator, and MCP toolchain."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
from typing import Any

try:
    from scripts.original_media import load_manifest, resolved_paths
except ModuleNotFoundError:  # Direct execution from the repository root.
    from original_media import load_manifest, resolved_paths


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def command_check(name: str, *, required: bool = True) -> dict[str, Any]:
    path = shutil.which(name)
    return {
        "name": name,
        "kind": "command",
        "required": required,
        "ok": path is not None,
        "detail": path or "not found in PATH",
    }


def path_check(name: str, path: Path, *, required: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "path",
        "required": required,
        "ok": path.exists(),
        "detail": str(path),
    }


def module_check(import_name: str, package_name: str) -> dict[str, Any]:
    found = False
    detail = "not importable"
    try:
        importlib.import_module(import_name)
        found = True
        try:
            detail = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            detail = "importable"
    except (ImportError, OSError) as error:
        detail = str(error)
    return {
        "name": package_name,
        "kind": "python-module",
        "required": True,
        "ok": found,
        "detail": detail,
    }


def collect_checks(require_media: bool = False) -> list[dict[str, Any]]:
    checks = [
        {
            "name": "python",
            "kind": "runtime",
            "required": True,
            "ok": sys.version_info >= (3, 11),
            "detail": sys.version.split()[0],
        },
        module_check("capstone", "capstone"),
        module_check("PIL", "Pillow"),
        module_check("tkinter", "Tkinter"),
        command_check("ida-pro-mcp"),
        command_check("idalib-mcp"),
        command_check("ghidraRun"),
        command_check("kaitai-struct-compiler"),
        command_check("armips"),
        command_check("mkpsxiso"),
        command_check("dumpsxiso"),
        command_check("xdelta3"),
        command_check("flips"),
        command_check("ffmpeg"),
        command_check("ffprobe"),
        command_check("vgmstream-cli"),
        path_check(
            "IDA Professional",
            Path("/Applications/IDA Professional 9.4.app"),
        ),
        path_check(
            "PCSX-Redux",
            Path("/Applications/PCSX-Redux.app"),
        ),
        path_check(
            "Japanese PS1 BIOS (local file)",
            Path.home()
            / "Library"
            / "Application Support"
            / "DuckStation"
            / "bios"
            / "SCPH5500.BIN",
        ),
        path_check(
            "Ghidra MCP bridge",
            Path.home() / "tools/ghidra-mcp/bridge_mcp_ghidra.py",
        ),
        path_check(
            "project MCP config",
            PROJECT_ROOT / ".mcp.json",
        ),
    ]
    media_paths = resolved_paths(load_manifest())
    checks.extend(
        path_check(name, path, required=require_media)
        for name, path in media_paths.items()
    )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require-media",
        action="store_true",
        help="treat the original CUE and data track as required",
    )
    args = parser.parse_args()

    checks = collect_checks(args.require_media)
    failed = [check for check in checks if check["required"] and not check["ok"]]
    if args.json:
        print(
            json.dumps(
                {"ok": not failed, "checks": checks},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for check in checks:
            state = "OK" if check["ok"] else ("MISSING" if check["required"] else "OPTIONAL")
            print(f"{state:8} {check['name']}: {check['detail']}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
