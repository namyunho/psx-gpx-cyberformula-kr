#!/usr/bin/env python3
"""Verify the complete Disc 1 extraction and decompression corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

try:
    from scripts.original_media import load_manifest, resolved_paths, verify_track
    from scripts.psx_disc import PsxDisc
except ModuleNotFoundError:  # Direct execution from the repository root.
    from original_media import load_manifest, resolved_paths, verify_track
    from psx_disc import PsxDisc


STREAM_FILES = {"CYBER_XA.STR", "MOVIE.STR", "MOVIE2.STR"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def hash_raw_extent(disc: PsxDisc, lba: int, block_count: int) -> str:
    digest = hashlib.sha256()
    for relative_lba in range(block_count):
        digest.update(disc.read_raw_sector(lba + relative_lba))
    return digest.hexdigest()


def expected_xa_frames(sector_count: int, coding: int) -> int:
    """Return PCM frames from Sony XA 4-bit ADPCM sectors used by this disc."""

    stereo = bool(coding & 0x01)
    return sector_count * (2016 if stereo else 4032)


def probe_frame_counts(ffprobe: str, path: Path, *, psxstr: bool) -> list[dict[str, Any]]:
    command = [ffprobe, "-v", "error"]
    if psxstr:
        command.extend(["-f", "psxstr"])
    command.extend(
        [
            "-count_frames",
            "-show_entries",
            (
                "stream=index,codec_name,codec_type,width,height,"
                "sample_rate,channels,nb_read_frames"
            ),
            "-of",
            "json",
            str(path),
        ]
    )
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"ffprobe failed for {path}:\n{result.stderr}")
    return json.loads(result.stdout)["streams"]


def write_report(path: Path, report: dict[str, Any]) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("work/extracted/disc1"),
    )
    parser.add_argument(
        "--disc-root",
        type=Path,
        default=Path("work/disc1/full"),
    )
    args = parser.parse_args()
    root = args.root
    extraction = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    schedules = json.loads(
        (root / extraction["manifests"]["schedules"]).read_text(encoding="utf-8")
    )
    decompressed = json.loads(
        (root / "manifests" / "decompressed-streams.json").read_text(
            encoding="utf-8"
        )
    )
    sound = json.loads(
        (root / extraction["manifests"]["sound"]).read_text(encoding="utf-8")
    )

    media_manifest = load_manifest()
    media_paths = resolved_paths(media_manifest)
    original = verify_track(
        media_paths["disc1_track1"],
        media_manifest["disc1"]["data_track"],
    )

    normal_iso = []
    raw_streams = []
    entry_by_name = {
        item["name"]: item
        for item in extraction["iso_files"]
        if item["status"] == "extracted"
    }
    with PsxDisc(media_paths["disc1_track1"]) as disc:
        for name, item in entry_by_name.items():
            iso_path = root / item["iso_path"]
            if (
                iso_path.stat().st_size != item["iso_byte_size"]
                or sha256_file(iso_path) != item["iso_sha256"]
            ):
                raise ValueError(f"ISO extraction hash mismatch: {name}")
            if name not in STREAM_FILES:
                source = args.disc_root / name
                if (
                    source.stat().st_size != iso_path.stat().st_size
                    or sha256_file(source) != sha256_file(iso_path)
                ):
                    raise ValueError(f"Form 1 ISO source mismatch: {name}")
                normal_iso.append(name)
            else:
                raw_path = root / item["raw2352_path"]
                expected = hash_raw_extent(
                    disc,
                    item["lba"],
                    item["logical_block_count"],
                )
                if sha256_file(raw_path) != expected:
                    raise ValueError(f"raw stream extent mismatch: {name}")
                raw_streams.append(name)

    schedule_reports = []
    for filename, file_report in schedules["files"].items():
        digest = hashlib.sha256()
        total = 0
        expected_index = 0
        for state in file_report["states"]:
            if state["state_index"] != expected_index:
                raise ValueError(f"state index gap in {filename}")
            path = root / state["path"]
            if (
                path.stat().st_size != state["byte_size"]
                or sha256_file(path) != state["sha256"]
            ):
                raise ValueError(
                    f"scheduled state mismatch: {filename} "
                    f"{state['state_index']}"
                )
            data = path.read_bytes()
            digest.update(data)
            total += len(data)
            for child in state["children"]:
                child_path = root / child["path"]
                if (
                    child_path.stat().st_size != child["byte_size"]
                    or sha256_file(child_path) != child["sha256"]
                ):
                    raise ValueError(
                        f"scheduled child mismatch: {filename} "
                        f"{state['state_index']}:{child['child_index']}"
                    )
            expected_index += 1
        source = args.disc_root / filename
        if total != source.stat().st_size or digest.hexdigest() != sha256_file(source):
            raise ValueError(f"scheduled state recombination mismatch: {filename}")
        schedule_reports.append(
            {
                "filename": filename,
                "state_count": expected_index,
                "byte_size": total,
                "sha256": digest.hexdigest(),
                "recombined_exactly": True,
            }
        )

    xa_sources = {item["path"]: item for item in extraction["xa_audio_streams"]}
    for decoded in decompressed["xa"]:
        source = xa_sources[decoded["source"]]
        coding = int(source["coding"], 16)
        expected = expected_xa_frames(source["sector_count"], coding)
        if decoded["frame_count"] != expected:
            raise ValueError(
                f"XA PCM frame mismatch: {decoded['source']} "
                f"{decoded['frame_count']} != {expected}"
            )

    bank_sources = {item["vab_path"]: item for item in sound["vab_banks"]}
    for bank in decompressed["vab"]:
        expected = bank_sources[bank["source"]]["vag_count"]
        if bank["sample_count"] != expected:
            raise ValueError(f"VAB sample count mismatch: {bank['source']}")
        for sample in bank["samples"]:
            path = root / sample["path"]
            if sha256_file(path) != sample["sha256"]:
                raise ValueError(f"VAB PCM hash mismatch: {path}")

    cdda_sources = {
        item["path"]: item for item in extraction["cdda_tracks"]
    }
    for track in decompressed["cdda"]:
        source = cdda_sources[track["source"]]
        if (
            track["channels"] != 2
            or track["sample_rate"] != 44100
            or track["frame_count"] != source["byte_size"] // 4
        ):
            raise ValueError(f"CDDA PCM mismatch: track {track['track']}")

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise FileNotFoundError("ffprobe is required for movie verification")
    movie_reports = []
    for movie in decompressed["movies"]:
        source = root / movie["source"]
        output = root / movie["path"]
        input_streams = probe_frame_counts(ffprobe, source, psxstr=True)
        output_streams = probe_frame_counts(ffprobe, output, psxstr=False)
        input_video = next(
            stream for stream in input_streams if stream["codec_type"] == "video"
        )
        output_video = next(
            stream for stream in output_streams if stream["codec_type"] == "video"
        )
        if output_video["codec_name"] != "ffv1":
            raise ValueError(f"movie output is not FFV1: {output}")
        if (
            input_video["width"] != output_video["width"]
            or input_video["height"] != output_video["height"]
            or input_video["nb_read_frames"] != output_video["nb_read_frames"]
        ):
            raise ValueError(f"movie frame mismatch: {output}")
        input_audio = [
            stream for stream in input_streams if stream["codec_type"] == "audio"
        ]
        output_audio = [
            stream for stream in output_streams if stream["codec_type"] == "audio"
        ]
        if len(input_audio) != len(output_audio):
            raise ValueError(f"movie audio stream mismatch: {output}")
        movie_reports.append(
            {
                "source": movie["source"],
                "output": movie["path"],
                "width": input_video["width"],
                "height": input_video["height"],
                "video_frame_count": int(input_video["nb_read_frames"]),
                "audio_stream_count": len(input_audio),
                "lossless_codec": "ffv1",
                "frame_count_equal": True,
            }
        )

    report = {
        "schema_version": 1,
        "status": "passed",
        "source": original,
        "checks": {
            "normal_form1_iso_file_count": len(normal_iso),
            "raw_stream_extent_count": len(raw_streams),
            "scheduled_file_count": len(schedule_reports),
            "scheduled_state_count": sum(
                item["state_count"] for item in schedule_reports
            ),
            "xa_pcm_stream_count": len(decompressed["xa"]),
            "vab_bank_count": len(decompressed["vab"]),
            "vab_pcm_sample_count": sum(
                item["sample_count"] for item in decompressed["vab"]
            ),
            "cdda_pcm_track_count": len(decompressed["cdda"]),
            "mdec_movie_count": len(movie_reports),
        },
        "scheduled_recombination": schedule_reports,
        "movies": movie_reports,
    }
    write_report(root / "manifests" / "verification.json", report)
    print(root / "manifests" / "verification.json")
    print(json.dumps(report["checks"], indent=2))


if __name__ == "__main__":
    main()
