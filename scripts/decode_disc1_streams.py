#!/usr/bin/env python3
"""Decode all proven disc audio/video streams losslessly.

Inputs come from :mod:`scripts.extract_disc1_assets`.  The historical script
name is retained for compatibility; ``--root`` may point at either disc:

* 33 CD-XA ADPCM streams -> PCM16 WAV
* 81 Sony VAB banks -> one PCM16 WAV per VAG subsong
* three CDDA tracks -> PCM16 WAV (container/endian conversion)
* two MDEC streams -> FFV1 video with PCM audio where present

Sony SEQ files are already uncompressed event streams. They remain byte-exact
``.seq`` files and are not mislabeled as compressed audio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any
import wave


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def write_json(path: Path, value: Any) -> None:
    rendered = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    digest = hashlib.sha256(rendered).hexdigest()
    if path.exists():
        if (
            path.stat().st_size != len(rendered)
            or sha256_file(path) != digest
        ):
            raise ValueError(f"existing decode manifest differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(rendered)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"required decoder is not installed: {name}")
    return path


def tool_banner(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"tool produced no version/help banner: {command[0]}")
    return lines[0]


def run(command: list[str]) -> None:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"decoder failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}"
        )


def wav_report(path: Path, root: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        compression = wav.getcomptype()
    if compression != "NONE" or sample_width != 2:
        raise ValueError(f"decoded WAV is not PCM16: {path}")
    return {
        "path": relative(path, root),
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
        "duration_seconds": frame_count / sample_rate,
    }


def ffprobe_report(ffprobe: str, path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"ffprobe failed for {path}:\n{result.stderr}")
    return json.loads(result.stdout)


def decode_xa(
    vgmstream: str,
    root: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    results = []
    for index, stream in enumerate(manifest["xa_audio_streams"], start=1):
        source = root / stream["path"]
        output = (
            root
            / "decompressed"
            / "xa"
            / f"{source.stem}.pcm16.wav"
        )
        if not output.exists():
            output.parent.mkdir(parents=True, exist_ok=True)
            run([vgmstream, "-i", "-o", str(output), str(source)])
        item = {
            "source": stream["path"],
            "source_sha256": stream["sha256"],
            **wav_report(output, root),
        }
        results.append(item)
        print(f"XA {index:02d}/{len(manifest['xa_audio_streams'])}: {output}")
    return results


def decode_vab(
    vgmstream: str,
    root: Path,
    sound_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    results = []
    banks = sound_manifest["vab_banks"]
    for bank_number, bank in enumerate(banks, start=1):
        source = root / bank["vab_path"]
        bank_dir = root / "decompressed" / "vab" / source.stem
        expected_count = bank["vag_count"]
        outputs = [
            bank_dir / f"sample-{index:03d}.pcm16.wav"
            for index in range(1, expected_count + 1)
        ]
        existing_count = sum(path.exists() for path in outputs)
        if existing_count not in {0, expected_count}:
            raise ValueError(
                f"partial VAB decode exists for {source}: "
                f"{existing_count}/{expected_count}"
            )
        if existing_count == 0:
            bank_dir.mkdir(parents=True, exist_ok=True)
            pattern = bank_dir / "sample-?s.pcm16.wav"
            run(
                [
                    vgmstream,
                    "-i",
                    "-s",
                    "1",
                    "-S",
                    "0",
                    "-o",
                    str(pattern),
                    str(source),
                ]
            )
            generated = sorted(bank_dir.glob("sample-*.pcm16.wav"))
            # vgmstream does not pad ?s; normalize only newly generated files.
            for path in generated:
                raw_index = int(path.name.split("-", 1)[1].split(".", 1)[0])
                normalized = bank_dir / f"sample-{raw_index:03d}.pcm16.wav"
                if normalized != path:
                    if normalized.exists():
                        raise ValueError(f"VAB sample path collision: {normalized}")
                    path.rename(normalized)
        if not all(path.exists() for path in outputs):
            actual = sorted(bank_dir.glob("sample-*.pcm16.wav"))
            raise ValueError(
                f"VAB stream count mismatch for {source}: "
                f"{len(actual)} != {expected_count}"
            )
        samples = [wav_report(path, root) for path in outputs]
        results.append(
            {
                "source": bank["vab_path"],
                "source_sha256": bank["combined_sha256"],
                "sample_count": len(samples),
                "samples": samples,
            }
        )
        print(f"VAB {bank_number:02d}/{len(banks)}: {len(samples)} samples")
    return results


def decode_cdda(
    ffmpeg: str,
    root: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    results = []
    for track in manifest["cdda_tracks"]:
        source = root / track["path"]
        output = (
            root
            / "decompressed"
            / "cdda"
            / f"track-{track['track']:02d}.pcm16.wav"
        )
        if not output.exists():
            output.parent.mkdir(parents=True, exist_ok=True)
            run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-n",
                    "-f",
                    "s16be",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-i",
                    str(source),
                    "-c:a",
                    "pcm_s16le",
                    str(output),
                ]
            )
        results.append(
            {
                "track": track["track"],
                "source": track["path"],
                "source_sha256": track["sha256"],
                **wav_report(output, root),
            }
        )
        print(f"CDDA track {track['track']:02d}: {output}")
    return results


def decode_movies(
    ffmpeg: str,
    ffprobe: str,
    root: Path,
) -> list[dict[str, Any]]:
    results = []
    for filename in ("MOVIE.STR", "MOVIE2.STR"):
        source = root / "streams" / "raw" / f"{filename}.raw2352"
        output = (
            root
            / "decompressed"
            / "video"
            / f"{filename.rsplit('.', 1)[0]}.ffv1-pcm.mkv"
        )
        if not output.exists():
            output.parent.mkdir(parents=True, exist_ok=True)
            run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-n",
                    "-f",
                    "psxstr",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "ffv1",
                    "-level",
                    "3",
                    "-g",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(output),
                ]
            )
        probe = ffprobe_report(ffprobe, output)
        streams = probe.get("streams", [])
        if not any(stream.get("codec_name") == "ffv1" for stream in streams):
            raise ValueError(f"lossless movie output has no FFV1 stream: {output}")
        results.append(
            {
                "source": relative(source, root),
                "source_sha256": sha256_file(source),
                "path": relative(output, root),
                "byte_size": output.stat().st_size,
                "sha256": sha256_file(output),
                "probe": probe,
            }
        )
        print(f"MDEC: {output}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("work/extracted/disc1"),
    )
    args = parser.parse_args()
    root = args.root
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    sound_manifest = json.loads(
        (root / manifest["manifests"]["sound"]).read_text(encoding="utf-8")
    )
    ffmpeg = require_tool("ffmpeg")
    ffprobe = require_tool("ffprobe")
    vgmstream = require_tool("vgmstream-cli")

    xa = decode_xa(vgmstream, root, manifest)
    vab = decode_vab(vgmstream, root, sound_manifest)
    cdda = decode_cdda(ffmpeg, root, manifest)
    movies = decode_movies(ffmpeg, ffprobe, root)
    report = {
        "schema_version": 1,
        "tools": {
            "ffmpeg": tool_banner([ffmpeg, "-version"]),
            "vgmstream": tool_banner([vgmstream, "-h"]),
        },
        "policy": {
            "xa_adpcm": "decoded to PCM16 WAV with vgmstream",
            "vab_adpcm": "every VAG subsong decoded once to PCM16 WAV",
            "cdda": "uncompressed source converted from CD big-endian PCM to WAV",
            "mdec": "decoded to FFV1 lossless video and PCM audio",
            "seq": "already-uncompressed event stream; preserved as .seq",
        },
        "summary": {
            "xa_stream_count": len(xa),
            "vab_bank_count": len(vab),
            "vab_sample_count": sum(item["sample_count"] for item in vab),
            "cdda_track_count": len(cdda),
            "movie_count": len(movies),
        },
        "xa": xa,
        "vab": vab,
        "cdda": cdda,
        "movies": movies,
    }
    write_json(root / "manifests" / "decompressed-streams.json", report)
    print(root / "manifests" / "decompressed-streams.json")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
