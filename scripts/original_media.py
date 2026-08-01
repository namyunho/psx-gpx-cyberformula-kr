#!/usr/bin/env python3
"""Resolve and verify the project's untracked original PS1 media.

Tracked defaults live in ``config/original-media.json``. A machine may override
them with ``config/original-media.local.json`` or per-disc environment variables
such as ``PSX_DISC1_CUE`` / ``PSX_DISC1_TRACK1`` and their Disc 2 equivalents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
import zlib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "config" / "original-media.json"
LOCAL_MANIFEST = PROJECT_ROOT / "config" / "original-media.local.json"


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_manifest(
    path: Path = DEFAULT_MANIFEST,
    local_path: Path | None = LOCAL_MANIFEST,
) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"unsupported original-media schema: {manifest.get('schema_version')!r}")
    if local_path is not None and local_path.exists():
        manifest = deep_merge(
            manifest,
            json.loads(local_path.read_text(encoding="utf-8")),
        )
    return manifest


def resolve_path(value: str, root: Path = PROJECT_ROOT) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    return expanded if expanded.is_absolute() else root / expanded


def resolved_paths(
    manifest: Mapping[str, Any],
    *,
    root: Path = PROJECT_ROOT,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    disc_keys = sorted(
        key for key in manifest if re.fullmatch(r"disc\d+", str(key))
    )
    if not disc_keys:
        raise ValueError("original-media manifest contains no disc entries")
    for disc_key in disc_keys:
        disc = manifest[disc_key]
        track = disc["data_track"]
        env_prefix = f"PSX_{disc_key.upper()}"
        result[f"{disc_key}_cue"] = resolve_path(
            environ.get(f"{env_prefix}_CUE", disc["cue"]),
            root,
        )
        result[f"{disc_key}_track1"] = resolve_path(
            environ.get(f"{env_prefix}_TRACK1", track["path"]),
            root,
        )
        for audio_track in disc.get("audio_tracks", []):
            track_number = int(audio_track["track"])
            result[f"{disc_key}_track{track_number}"] = resolve_path(
                environ.get(
                    f"{env_prefix}_TRACK{track_number}",
                    audio_track["path"],
                ),
                root,
            )
    return result


def file_hashes(path: Path) -> dict[str, str | int]:
    crc32 = 0
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            crc32 = zlib.crc32(chunk, crc32)
            md5.update(chunk)
            sha256.update(chunk)
    return {
        "size": path.stat().st_size,
        "crc32": f"{crc32 & 0xFFFFFFFF:08X}",
        "md5": md5.hexdigest(),
        "sha256": sha256.hexdigest(),
    }


def verify_track(
    path: Path,
    expected: Mapping[str, Any],
    *,
    label: str = "data track",
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    actual = file_hashes(path)
    mismatches = {
        key: {"expected": expected[key], "actual": actual[key]}
        for key in ("size", "crc32", "md5", "sha256")
        if str(actual[key]).lower() != str(expected[key]).lower()
    }
    if mismatches:
        raise ValueError(
            f"{label} does not match the supported revision:\n"
            + json.dumps(mismatches, ensure_ascii=False, indent=2)
        )
    return {"path": str(path), **actual, "verified": True}


def read_cue_tracks(path: Path) -> list[str]:
    text = read_cue_text(path)
    return [
        match.group(1).upper()
        for match in re.finditer(r"(?im)^\s*TRACK\s+\d+\s+(\S+)", text)
    ]


def read_cue_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"CUE not found: {path}")
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "shift_jis", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 always succeeds
        raise ValueError(f"unable to decode CUE: {path}")
    return text


def read_cue_files(path: Path) -> list[str]:
    text = read_cue_text(path)
    return [
        quoted or unquoted
        for quoted, unquoted in re.findall(
            r'(?im)^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+\S+',
            text,
        )
    ]


def verify_cue(path: Path, expected_tracks: list[str]) -> dict[str, Any]:
    actual_tracks = read_cue_tracks(path)
    normalized_expected = [track.upper() for track in expected_tracks]
    if actual_tracks != normalized_expected:
        raise ValueError(
            f"CUE track layout mismatch: expected {normalized_expected}, got {actual_tracks}"
        )
    referenced_files = read_cue_files(path)
    missing_files = [
        name for name in referenced_files if not (path.parent / name).is_file()
    ]
    if missing_files:
        raise FileNotFoundError(
            "CUE references missing track file(s): " + ", ".join(missing_files)
        )
    return {
        "path": str(path),
        "tracks": actual_tracks,
        "files": referenced_files,
        "verified": True,
    }


def path_report(manifest: Mapping[str, Any]) -> dict[str, Any]:
    paths = resolved_paths(manifest)
    return {
        name: {"path": str(path), "exists": path.exists()}
        for name, path in paths.items()
    }


def cmd_prepare(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    paths = resolved_paths(manifest)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(path_report(manifest), ensure_ascii=False, indent=2))


def cmd_paths(args: argparse.Namespace) -> None:
    print(
        json.dumps(
            path_report(load_manifest(args.manifest)),
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_verify(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    paths = resolved_paths(manifest)
    disc_key = args.disc.lower()
    if disc_key not in manifest:
        raise ValueError(f"unsupported disc key: {disc_key}")
    result = {
        f"{disc_key}_track1": verify_track(
            paths[f"{disc_key}_track1"],
            manifest[disc_key]["data_track"],
            label=f"{disc_key} data track",
        )
    }
    if args.cue:
        result[f"{disc_key}_cue"] = verify_cue(
            paths[f"{disc_key}_cue"],
            manifest[disc_key]["expected_tracks"],
        )
        for expected in manifest[disc_key].get("audio_tracks", []):
            track_number = int(expected["track"])
            result[f"{disc_key}_track{track_number}"] = verify_track(
                paths[f"{disc_key}_track{track_number}"],
                expected,
                label=f"{disc_key} audio track {track_number}",
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="create ignored media directories")
    prepare.set_defaults(func=cmd_prepare)

    paths = subparsers.add_parser("paths", help="show resolved paths and existence")
    paths.set_defaults(func=cmd_paths)

    verify = subparsers.add_parser("verify", help="verify the supported data track")
    verify.add_argument(
        "--disc",
        default="disc1",
        help="manifest disc key to verify (default: disc1)",
    )
    verify.add_argument("--cue", action="store_true", help="also require the 4-track CUE")
    verify.set_defaults(func=cmd_verify)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, KeyError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
