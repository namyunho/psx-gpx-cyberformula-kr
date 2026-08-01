#!/usr/bin/env python3
"""Independently verify a nonrelease dialogue Disc 1 or Disc 2 build."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

try:
    from scripts.build_dialogue_chapter_disc import (
        compare_raw_tracks,
        load_object,
        sha256_file,
        verify_required_file_bytes,
        write_json,
    )
    from scripts.original_media import (
        DEFAULT_MANIFEST,
        file_hashes,
        load_manifest,
        read_cue_files,
        resolved_paths,
        verify_cue,
        verify_track,
    )
    from scripts.psx_disc import PsxDisc
    from scripts.psx_sector import inspect_mode2_form1
except ModuleNotFoundError:
    from build_dialogue_chapter_disc import (
        compare_raw_tracks,
        load_object,
        sha256_file,
        verify_required_file_bytes,
        write_json,
    )
    from original_media import (
        DEFAULT_MANIFEST,
        file_hashes,
        load_manifest,
        read_cue_files,
        resolved_paths,
        verify_cue,
        verify_track,
    )
    from psx_disc import PsxDisc
    from psx_sector import inspect_mode2_form1


def recorded_path(value: Any, *, build_dir: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: missing recorded path")
    path = Path(value)
    return path if path.is_absolute() else build_dir / path


def root_layout(disc: PsxDisc) -> list[tuple[str, int, int, bool]]:
    return [
        (entry.name.upper(), entry.lba, entry.size, entry.is_directory)
        for entry in disc.root_entries()
    ]


def verify_build(
    *,
    build_dir: Path,
    original_media_manifest: Path,
) -> dict[str, Any]:
    manifest_path = build_dir / "manifest.json"
    build = load_object(manifest_path)
    disc_key = build.get("target_disc")
    if not isinstance(disc_key, str):
        raise ValueError("build manifest has no target_disc")

    media = load_manifest(original_media_manifest)
    if disc_key not in media:
        raise ValueError(f"unsupported target disc key: {disc_key}")
    paths = resolved_paths(media)
    disc_media = media[disc_key]
    source_track = paths[f"{disc_key}_track1"]
    source_cue = paths[f"{disc_key}_cue"]
    verify_track(
        source_track,
        disc_media["data_track"],
        label=f"{disc_key} data track",
    )
    verify_cue(source_cue, disc_media["expected_tracks"])
    for expected in disc_media.get("audio_tracks", []):
        verify_track(
            paths[f"{disc_key}_track{int(expected['track'])}"],
            expected,
            label=f"{disc_key} audio track {int(expected['track'])}",
        )

    output_track = recorded_path(
        build["outputs"]["track1"].get("path"),
        build_dir=build_dir,
        label="output Track 1",
    )
    output_cue = recorded_path(
        build["outputs"]["cue"].get("path"),
        build_dir=build_dir,
        label="output CUE",
    )
    recorded_track_hashes = {
        key: build["outputs"]["track1"][key]
        for key in ("size", "crc32", "md5", "sha256")
    }
    actual_track_hashes = file_hashes(output_track)
    if actual_track_hashes != recorded_track_hashes:
        raise ValueError("output Track 1 hashes differ from build manifest")
    if sha256_file(output_cue) != build["outputs"]["cue"]["sha256"]:
        raise ValueError("output CUE hash differs from build manifest")
    verify_cue(output_cue, disc_media["expected_tracks"])
    file_build_record = build["sources"]["file_build_manifest"]
    file_build_manifest = recorded_path(
        file_build_record.get("path"),
        build_dir=build_dir,
        label="file-build manifest",
    )
    if sha256_file(file_build_manifest) != file_build_record.get("sha256"):
        raise ValueError("file-build manifest hash differs from disc build record")

    cue_files = [
        (output_cue.parent / name).resolve() for name in read_cue_files(output_cue)
    ]
    expected_cue_files = [
        output_track.resolve(),
        *[
            paths[f"{disc_key}_track{int(expected['track'])}"].resolve()
            for expected in disc_media.get("audio_tracks", [])
        ],
    ]
    if cue_files != expected_cue_files:
        raise ValueError("output CUE does not reference the target disc track set")

    planned_sectors = {
        int(lba) for lba in build["raw_expected_writes"]["sectors"]
    }
    actual_sectors = compare_raw_tracks(source_track, output_track)
    if actual_sectors != planned_sectors:
        raise ValueError("output changed-sector set differs from build manifest")

    required_rules = disc_media.get("required_file_bytes", [])
    if not isinstance(required_rules, list):
        raise ValueError(f"{disc_key}: required_file_bytes must be a list")
    required_verification: list[dict[str, Any]] = []
    file_verification: dict[str, Any] = {}
    with PsxDisc(source_track) as source_disc, PsxDisc(output_track) as output_disc:
        if root_layout(source_disc) != root_layout(output_disc):
            raise ValueError("output ISO root layout differs from target original")
        output_entries = {
            entry.name.upper(): entry
            for entry in output_disc.root_entries()
            if not entry.is_directory
        }
        for name, file_report in build["iso_files"].items():
            entry = output_entries.get(name.upper())
            if entry is None:
                raise ValueError(f"output ISO root has no {name}")
            if entry.lba != file_report["lba"] or entry.size != file_report["size"]:
                raise ValueError(f"{name}: output ISO extent differs")
            data = output_disc.read_extent(entry.lba, entry.size)
            digest = hashlib.sha256(data).hexdigest()
            if digest != build["outputs"][name]["sha256"]:
                raise ValueError(f"{name}: re-extracted output hash differs")
            required_verification.extend(
                verify_required_file_bytes(
                    filename=name,
                    data=data,
                    rules=required_rules,
                    stage="independent-reextraction",
                )
            )
            file_verification[name] = {
                "lba": entry.lba,
                "size": entry.size,
                "sha256": digest,
            }
        for lba in planned_sectors:
            if not inspect_mode2_form1(source_disc.read_raw_sector(lba)).valid:
                raise ValueError(f"source LBA {lba}: invalid EDC/ECC")
            if not inspect_mode2_form1(output_disc.read_raw_sector(lba)).valid:
                raise ValueError(f"output LBA {lba}: invalid EDC/ECC")

    if len(required_verification) != len(required_rules):
        raise ValueError("independent required-byte verification coverage differs")

    report = {
        "schema_version": 1,
        "status": "static-verification-passed-runtime-validation-required",
        "target_disc": disc_key,
        "sources": {
            "build_manifest": {
                "path": str(manifest_path.resolve()),
                "sha256": sha256_file(manifest_path),
            },
            "file_build_manifest": {
                "path": str(file_build_manifest.resolve()),
                "sha256": sha256_file(file_build_manifest),
            },
            "original_track1": str(source_track.resolve()),
            "original_cue": str(source_cue.resolve()),
        },
        "outputs": {
            "track1": {"path": str(output_track.resolve()), **actual_track_hashes},
            "cue": {
                "path": str(output_cue.resolve()),
                "sha256": sha256_file(output_cue),
            },
        },
        "iso_root_layout_equal": True,
        "files": file_verification,
        "changed_sector_count": len(actual_sectors),
        "changed_sector_set_matches_manifest": True,
        "all_changed_source_and_output_sectors_edc_ecc_valid": True,
        "required_file_bytes": required_verification,
        "runtime_validation": build.get("runtime_validation"),
    }
    write_json(build_dir / "verification.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument(
        "--original-media-manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    args = parser.parse_args()
    report = verify_build(
        build_dir=args.build_dir,
        original_media_manifest=args.original_media_manifest,
    )
    print(
        f"target={report['target_disc']} "
        f"changed_sectors={report['changed_sector_count']} "
        f"track={report['outputs']['track1']['path']}"
    )


if __name__ == "__main__":
    main()
