#!/usr/bin/env python3
"""Extract every proven Disc 1 container and decode established asset formats.

Outputs are original-derived and intentionally live below ``work/``.  The
pipeline preserves exact ISO/state/child bytes, raw 2352-byte XA/STR extents,
and then decodes only formats whose boundaries and consumers are established:

* ALLBIN font-rendered u16 streams
* START 14x14 3bpp glyph tables
* START 48x56 4bpp portraits
* structurally proven raw VRAM rectangles with in-state palettes
* SOUND VAB header/body pairs and SEQ streams

MDEC/XA/VAB audio decompression is performed by
``scripts/decode_disc1_streams.py`` after this lossless extraction stage.
Unknown records remain byte-exact raw files and are never fed to a guessed
decompressor.
"""

from __future__ import annotations

import argparse
from collections import Counter
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
from typing import Any, Iterable, Iterator

from PIL import Image

try:
    from scripts.original_media import (
        load_manifest,
        read_cue_files,
        read_cue_tracks,
        resolved_paths,
        verify_cue,
        verify_track,
    )
    from scripts.psx_disc import PsxDisc, RAW_SECTOR_SIZE
    from scripts.psx_font import HEIGHT, WIDTH, unpack_glyph
    from scripts.psx_font_inventory import build_font_inventory
    from scripts.psx_layout import build_inventory
    from scripts.psx_portrait_inventory import (
        PORTRAIT_BLOCK_SIZE,
        build_portrait_inventory,
        decode_portrait,
    )
    from scripts.psx_text_inventory import build_text_inventory
    from scripts.psx_vram_render import render_unit, unit_records
except ModuleNotFoundError:  # Direct execution from the repository root.
    from original_media import (
        load_manifest,
        read_cue_files,
        read_cue_tracks,
        resolved_paths,
        verify_cue,
        verify_track,
    )
    from psx_disc import PsxDisc, RAW_SECTOR_SIZE
    from psx_font import HEIGHT, WIDTH, unpack_glyph
    from psx_font_inventory import build_font_inventory
    from psx_layout import build_inventory
    from psx_portrait_inventory import (
        PORTRAIT_BLOCK_SIZE,
        build_portrait_inventory,
        decode_portrait,
    )
    from psx_text_inventory import build_text_inventory
    from psx_vram_render import render_unit, unit_records


STREAM_FILES = {"CYBER_XA.STR", "MOVIE.STR", "MOVIE2.STR"}
VISUAL_FILES = {
    "MINI_G1.BIN",
    "MINI_G2.BIN",
    "MINI_G3.BIN",
    "MINI_G4.BIN",
    "AVM_MAP.BIN",
    "START.BIN",
    "OUTSIDE.BIN",
    "MACHINE.BIN",
    "COURSE.BIN",
}
SYNC = bytes.fromhex("00FFFFFFFFFFFFFFFFFFFF00")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def write_checked(path: Path, data: bytes) -> dict[str, Any]:
    """Write a derived file once, rejecting an incompatible existing file."""

    digest = sha256_bytes(data)
    if path.exists():
        if path.stat().st_size != len(data) or sha256_file(path) != digest:
            raise ValueError(f"existing extraction differs: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temporary.write_bytes(data)
        os.replace(temporary, path)
    return {"byte_size": len(data), "sha256": digest}


def write_json(path: Path, value: Any) -> dict[str, Any]:
    return write_checked(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def image_png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def safe_component(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return normalized.strip("-") or "asset"


def sector_header(raw: bytes) -> dict[str, int | str]:
    if len(raw) != RAW_SECTOR_SIZE or raw[:12] != SYNC:
        raise ValueError("invalid raw sector")
    mode = raw[15]
    if mode == 1:
        return {"mode": "MODE1"}
    if mode != 2:
        raise ValueError(f"unsupported raw sector mode: {mode}")
    if raw[16:20] != raw[20:24]:
        raise ValueError("CD-XA duplicated subheader mismatch")
    file_number, channel, submode, coding = raw[16:20]
    return {
        "mode": "MODE2/FORM2" if submode & 0x20 else "MODE2/FORM1",
        "file_number": file_number,
        "channel": channel,
        "submode": submode,
        "coding": coding,
    }


def iter_raw_extent(
    disc: PsxDisc, lba: int, block_count: int
) -> Iterator[tuple[int, bytes, dict[str, int | str]]]:
    for relative_lba in range(block_count):
        raw = disc.read_raw_sector(lba + relative_lba)
        yield relative_lba, raw, sector_header(raw)


def write_iterable(path: Path, chunks: Iterable[bytes]) -> dict[str, Any]:
    """Stream a large output and compare instead of overwriting on reruns."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    digest = hashlib.sha256()
    size = 0
    with temporary.open("wb") as output:
        for chunk in chunks:
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    expected = digest.hexdigest()
    if path.exists():
        if path.stat().st_size != size or sha256_file(path) != expected:
            temporary.unlink()
            raise ValueError(f"existing extraction differs: {path}")
        temporary.unlink()
    else:
        os.replace(temporary, path)
    return {"byte_size": size, "sha256": expected}


def extract_iso_files(
    disc: PsxDisc,
    output_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    reports = []
    stream_sources: dict[str, dict[str, Any]] = {}
    for entry in disc.root_entries():
        record: dict[str, Any] = {
            "name": entry.name,
            "lba": entry.lba,
            "directory_byte_size": entry.size,
            "is_directory": entry.is_directory,
        }
        if entry.is_directory:
            record["status"] = "directory"
            reports.append(record)
            continue
        block_count = (entry.size + 2047) // 2048
        record["logical_block_count"] = block_count
        if entry.lba + block_count > disc.sector_count:
            record["status"] = "external_cdda_reference"
            reports.append(record)
            continue

        iso_path = output_root / "iso" / entry.name
        iso_result = write_iterable(
            iso_path,
            (
                payload[: min(2048, entry.size - relative_lba * 2048)]
                for relative_lba in range(block_count)
                for payload, _ in [disc.read_sector(entry.lba + relative_lba)]
            ),
        )
        record.update(
            {
                "status": "extracted",
                "iso_path": relative(iso_path, output_root),
                "iso_byte_size": iso_result["byte_size"],
                "iso_sha256": iso_result["sha256"],
            }
        )

        if entry.name in STREAM_FILES:
            raw_path = output_root / "streams" / "raw" / (
                entry.name + ".raw2352"
            )
            raw_result = write_iterable(
                raw_path,
                (
                    raw
                    for _, raw, _ in iter_raw_extent(
                        disc, entry.lba, block_count
                    )
                ),
            )
            mode_counts: Counter[str] = Counter()
            subheaders: Counter[tuple[int, int, int, int]] = Counter()
            for _, _, header in iter_raw_extent(disc, entry.lba, block_count):
                mode_counts[str(header["mode"])] += 1
                if "file_number" in header:
                    subheaders[
                        (
                            int(header["file_number"]),
                            int(header["channel"]),
                            int(header["submode"]),
                            int(header["coding"]),
                        )
                    ] += 1
            record.update(
                {
                    "raw2352_path": relative(raw_path, output_root),
                    "raw2352_byte_size": raw_result["byte_size"],
                    "raw2352_sha256": raw_result["sha256"],
                    "sector_mode_counts": dict(sorted(mode_counts.items())),
                    "xa_subheader_counts": [
                        {
                            "file_number": key[0],
                            "channel": key[1],
                            "submode": f"0x{key[2]:02X}",
                            "coding": f"0x{key[3]:02X}",
                            "sector_count": count,
                        }
                        for key, count in sorted(subheaders.items())
                    ],
                }
            )
            stream_sources[entry.name] = {
                "entry": entry,
                "block_count": block_count,
                "raw_path": raw_path,
            }
        reports.append(record)
    return reports, stream_sources


def xa_audio_key(header: dict[str, int | str]) -> tuple[int, int, int] | None:
    if header["mode"] != "MODE2/FORM2":
        return None
    submode = int(header["submode"])
    if not submode & 0x04:
        return None
    return (
        int(header["file_number"]),
        int(header["channel"]),
        int(header["coding"]),
    )


def split_xa_audio(
    disc: PsxDisc,
    stream_sources: dict[str, dict[str, Any]],
    output_root: Path,
) -> list[dict[str, Any]]:
    reports = []
    for filename in sorted(stream_sources):
        source = stream_sources[filename]
        entry = source["entry"]
        block_count = source["block_count"]
        expected: dict[tuple[int, int, int], dict[str, Any]] = {}
        for _, raw, header in iter_raw_extent(disc, entry.lba, block_count):
            key = xa_audio_key(header)
            if key is None:
                continue
            item = expected.setdefault(
                key,
                {"sector_count": 0, "digest": hashlib.sha256()},
            )
            item["sector_count"] += 1
            item["digest"].update(raw)

        missing: dict[tuple[int, int, int], tuple[Path, Path, Any]] = {}
        for key, item in expected.items():
            stem = (
                f"{filename.rsplit('.', 1)[0]}-"
                f"f{key[0]:02d}-c{key[1]:02d}-k{key[2]:02X}"
            )
            path = output_root / "streams" / "xa" / f"{stem}.xa"
            expected_size = item["sector_count"] * RAW_SECTOR_SIZE
            expected_sha256 = item["digest"].hexdigest()
            if path.exists():
                if (
                    path.stat().st_size != expected_size
                    or sha256_file(path) != expected_sha256
                ):
                    raise ValueError(f"existing XA channel differs: {path}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
                missing[key] = (path, temporary, temporary.open("wb"))
            reports.append(
                {
                    "source": filename,
                    "file_number": key[0],
                    "channel": key[1],
                    "coding": f"0x{key[2]:02X}",
                    "sector_count": item["sector_count"],
                    "byte_size": expected_size,
                    "sha256": expected_sha256,
                    "path": relative(path, output_root),
                }
            )
        if missing:
            try:
                for _, raw, header in iter_raw_extent(
                    disc, entry.lba, block_count
                ):
                    key = xa_audio_key(header)
                    if key in missing:
                        missing[key][2].write(raw)
            finally:
                for _, _, handle in missing.values():
                    handle.close()
            for path, temporary, _ in missing.values():
                os.replace(temporary, path)
    return reports


def copy_cdda_tracks(cue_path: Path, output_root: Path) -> list[dict[str, Any]]:
    files = read_cue_files(cue_path)
    track_types = read_cue_tracks(cue_path)
    if len(files) != len(track_types):
        raise ValueError("one FILE per TRACK is required for CDDA extraction")
    reports = []
    for track_index, (filename, track_type) in enumerate(
        zip(files, track_types, strict=True),
        start=1,
    ):
        if track_type != "AUDIO":
            continue
        source = cue_path.parent / filename
        destination = (
            output_root
            / "streams"
            / "cdda"
            / f"track-{track_index:02d}.raw2352"
        )
        source_size = source.stat().st_size
        source_sha256 = sha256_file(source)
        if destination.exists():
            if (
                destination.stat().st_size != source_size
                or sha256_file(destination) != source_sha256
            ):
                raise ValueError(f"existing CDDA extraction differs: {destination}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.tmp-{os.getpid()}"
            )
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        reports.append(
            {
                "track": track_index,
                "cue_file": filename,
                "path": relative(destination, output_root),
                "byte_size": source_size,
                "sha256": source_sha256,
                "pcm_format": "signed 16-bit big-endian stereo 44100 Hz",
            }
        )
    return reports


def extract_schedules(
    layout: dict[str, Any],
    disc_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    files = {}
    state_count = 0
    child_count = 0
    child_kinds: Counter[str] = Counter()
    for filename, schedule in layout["schedules"].items():
        data = (disc_root / filename).read_bytes()
        unit_reports = []
        for span, inventory in zip(
            schedule["entries"],
            schedule["inventory"]["units"],
            strict=True,
        ):
            start = span["byte_offset"]
            unit = data[start : span["byte_end"]]
            if sha256_bytes(unit) != inventory["sha256"]:
                raise ValueError(f"{filename} unit {span['index']} hash mismatch")
            unit_path = (
                output_root
                / "scheduled"
                / filename.rsplit(".", 1)[0]
                / f"unit-{span['index']:04d}.bin"
            )
            write_checked(unit_path, unit)
            children = []
            for child in inventory.get("children", []):
                child_start = child["file_offset"]
                raw = data[child_start : child_start + child["byte_size"]]
                if sha256_bytes(raw) != child["sha256"]:
                    raise ValueError(
                        f"{filename} unit {span['index']} child "
                        f"{child['index']} hash mismatch"
                    )
                child_path = (
                    output_root
                    / "children"
                    / filename.rsplit(".", 1)[0]
                    / f"unit-{span['index']:04d}"
                    / (
                        f"child-{child['index']:04d}-"
                        f"{safe_component(child['kind'])}.bin"
                    )
                )
                write_checked(child_path, raw)
                children.append(
                    {
                        "child_index": child["index"],
                        "kind": child["kind"],
                        "file_offset": child["file_offset"],
                        "byte_size": child["byte_size"],
                        "sha256": child["sha256"],
                        "path": relative(child_path, output_root),
                    }
                )
                child_count += 1
                child_kinds[child["kind"]] += 1
            unit_reports.append(
                {
                    "state_index": span["index"],
                    "file_offset": start,
                    "byte_size": len(unit),
                    "sha256": inventory["sha256"],
                    "structural_kind": inventory["kind"],
                    "path": relative(unit_path, output_root),
                    "children": children,
                }
            )
            state_count += 1
        files[filename] = {
            "state_count": len(unit_reports),
            "states": unit_reports,
        }
    return {
        "summary": {
            "file_count": len(files),
            "state_count": state_count,
            "child_count": child_count,
            "child_kind_counts": dict(sorted(child_kinds.items())),
        },
        "files": files,
    }


def extract_text(
    disc_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    report = build_text_inventory(
        disc_root / "SLPS_019.58",
        disc_root / "ALLBIN.BIN",
    )
    allbin = (disc_root / "ALLBIN.BIN").read_bytes()
    entries = []
    groups = [
        *report["units"],
        *report["embedded_race_units"],
        report["overlay_ui"],
    ]
    for unit in groups:
        subsystem = unit["subsystem"]
        for entry in unit["entries"]:
            start = entry["file_offset"]
            raw = allbin[start : start + entry["byte_size"]]
            if sha256_bytes(raw) != entry["sha256"]:
                raise ValueError(
                    f"text stream hash mismatch at ALLBIN+0x{start:X}"
                )
            unit_index = unit["unit_index"]
            unit_offset = entry["unit_offset"]
            path = (
                output_root
                / "decoded"
                / "text"
                / safe_component(subsystem)
                / f"unit-{unit_index:02d}"
                / f"entry-{unit_offset:06X}.u16le"
            )
            write_checked(path, raw)
            tokens = struct.unpack(f"<{len(raw) // 2}H", raw)
            entries.append(
                {
                    "asset_id": (
                        f"text/{subsystem}/u{unit_index:02d}/"
                        f"{unit_offset:06X}"
                    ),
                    "subsystem": subsystem,
                    "unit_index": unit_index,
                    "unit_offset": unit_offset,
                    "file_offset": start,
                    "pointer": f"0x{entry['pointer']:08X}",
                    "reference_count": entry.get("reference_count", 1),
                    "byte_size": len(raw),
                    "sha256": entry["sha256"],
                    "terminal": f"0x{entry['terminal']:04X}",
                    "tokens": [f"0x{token:04X}" for token in tokens],
                    "path": relative(path, output_root),
                }
            )
    if len(entries) != report["summary"]["all_font_stream_entry_count"]:
        raise ValueError("text stream denominator mismatch")
    result = {
        "schema_version": 1,
        "summary": report["summary"],
        "entries": entries,
    }
    write_json(output_root / "manifests" / "text.json", result)
    return result


def glyph_image(raw: bytes) -> Image.Image:
    pixels = unpack_glyph(raw)
    image = Image.new("L", (WIDTH, HEIGHT))
    image.putdata([value * 255 // 7 for value in pixels])
    return image


def extract_fonts(
    disc_root: Path,
    layout: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    report = build_font_inventory(
        disc_root / "SLPS_019.58",
        disc_root / "START.BIN",
    )
    start_data = (disc_root / "START.BIN").read_bytes()
    items = []
    for font in report["fonts"]:
        span = layout["schedules"]["START.BIN"]["entries"][font["start_unit"]]
        unit = start_data[span["byte_offset"] : span["byte_end"]]
        font_dir = output_root / "decoded" / "fonts" / font["name"]
        for index in range(font["defined_slot_count"]):
            begin = index * 74
            raw = unit[begin : begin + 74]
            raw_path = font_dir / "raw" / f"glyph-{index:04X}.3bpp"
            png_path = font_dir / "png" / f"glyph-{index:04X}.png"
            write_checked(raw_path, raw)
            png = image_png_bytes(glyph_image(raw))
            write_checked(png_path, png)
            items.append(
                {
                    "font": font["name"],
                    "glyph_index": f"0x{index:03X}",
                    "all_zero": not any(raw),
                    "raw_sha256": sha256_bytes(raw),
                    "raw_path": relative(raw_path, output_root),
                    "png_path": relative(png_path, output_root),
                }
            )
    result = {
        "schema_version": 1,
        "source_inventory": report,
        "summary": {
            "font_count": len(report["fonts"]),
            "glyph_slot_count": len(items),
        },
        "glyphs": items,
    }
    write_json(output_root / "manifests" / "fonts.json", result)
    return result


def extract_portraits(
    disc_root: Path,
    layout: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    report = build_portrait_inventory(
        disc_root / "SLPS_019.58",
        disc_root / "START.BIN",
    )
    start_data = (disc_root / "START.BIN").read_bytes()
    items = []
    for unit in report["units"]:
        span = layout["schedules"]["START.BIN"]["entries"][unit["unit_index"]]
        source = start_data[span["byte_offset"] : span["byte_end"]]
        for record in unit["records"]:
            begin = record["unit_offset"]
            block = source[begin : begin + PORTRAIT_BLOCK_SIZE]
            if sha256_bytes(block) != record["sha256"]:
                raise ValueError("portrait record hash mismatch")
            stem = (
                f"state-{unit['story_state']:02d}-"
                f"unit-{unit['unit_index']:02d}-"
                f"portrait-{record['block_index']:02d}"
            )
            raw_path = output_root / "decoded" / "portraits" / f"{stem}.bin"
            png_path = output_root / "decoded" / "portraits" / f"{stem}.png"
            write_checked(raw_path, block)
            image = decode_portrait(
                block,
                unit_index=unit["unit_index"],
                block_index=record["block_index"],
            )
            write_checked(png_path, image_png_bytes(image))
            items.append(
                {
                    "story_state": unit["story_state"],
                    "unit_index": unit["unit_index"],
                    "portrait_index": record["block_index"],
                    "all_zero": record["all_zero"],
                    "sha256": record["sha256"],
                    "raw_path": relative(raw_path, output_root),
                    "png_path": relative(png_path, output_root),
                }
            )
    if len(items) != report["summary"]["record_count"]:
        raise ValueError("portrait denominator mismatch")
    result = {
        "schema_version": 1,
        "source_inventory": report,
        "items": items,
    }
    write_json(output_root / "manifests" / "portraits.json", result)
    return result


def extract_vram_previews(
    disc_root: Path,
    layout: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    items = []
    record_count = 0
    preview_count = 0
    for filename in sorted(VISUAL_FILES):
        data = (disc_root / filename).read_bytes()
        schedule = layout["schedules"][filename]
        for span in schedule["entries"]:
            unit = data[span["byte_offset"] : span["byte_end"]]
            records = unit_records(unit, span["index"])
            record_count += len(records)
            previews = render_unit(records)
            for preview_index, preview in enumerate(previews):
                label = safe_component(preview.label)
                path = (
                    output_root
                    / "decoded"
                    / "vram"
                    / filename.rsplit(".", 1)[0]
                    / f"unit-{span['index']:04d}"
                    / f"preview-{preview_index:03d}-{label}.png"
                )
                png = image_png_bytes(preview.image)
                write_checked(path, png)
                items.append(
                    {
                        "source": filename,
                        "state_index": span["index"],
                        "label": preview.label,
                        "width": preview.image.width,
                        "height": preview.image.height,
                        "png_sha256": sha256_bytes(png),
                        "path": relative(path, output_root),
                    }
                )
                preview_count += 1
    result = {
        "schema_version": 1,
        "summary": {
            "structural_vram_record_count": record_count,
            "decoded_palette_variant_count": preview_count,
        },
        "previews": items,
    }
    write_json(output_root / "manifests" / "vram.json", result)
    return result


def extract_sound(
    disc_root: Path,
    layout: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    data = (disc_root / "SOUND.BIN").read_bytes()
    units = layout["schedules"]["SOUND.BIN"]["inventory"]["units"]
    banks = []
    sequences = []
    for unit_index, unit in enumerate(units):
        headers = []
        for child in unit.get("children", []):
            raw = data[
                child["file_offset"] : child["file_offset"] + child["byte_size"]
            ]
            if raw[:4] == b"pBAV":
                headers.append((child, raw))
            elif raw[:4] == b"pQES":
                path = (
                    output_root
                    / "decoded"
                    / "sound"
                    / "seq"
                    / (
                        f"unit-{unit_index:03d}-"
                        f"seq-{child['index']:03d}.seq"
                    )
                )
                write_checked(path, raw)
                sequences.append(
                    {
                        "unit_index": unit_index,
                        "child_index": child["index"],
                        "file_offset": child["file_offset"],
                        "byte_size": len(raw),
                        "sha256": sha256_bytes(raw),
                        "path": relative(path, output_root),
                    }
                )
        if not headers:
            continue
        if unit_index + 1 >= len(units):
            raise ValueError(f"SOUND unit {unit_index} has no VAB body unit")
        bodies = []
        for child in units[unit_index + 1].get("children", []):
            raw = data[
                child["file_offset"] : child["file_offset"] + child["byte_size"]
            ]
            if raw[:4] == b"\0\0\0\0":
                bodies.append((child, raw))
        if len(headers) != len(bodies):
            raise ValueError(
                f"SOUND VAB pair count mismatch at unit {unit_index}: "
                f"{len(headers)} != {len(bodies)}"
            )
        for bank_index, ((header_record, header), (body_record, body)) in enumerate(
            zip(headers, bodies, strict=True)
        ):
            total_size = struct.unpack_from("<I", header, 12)[0]
            body_size = total_size - len(header)
            if body_size < 0 or body_size > len(body):
                raise ValueError("VAB total size exceeds paired body child")
            if any(body[body_size:]):
                raise ValueError("nonzero bytes follow VAB body")
            body = body[:body_size]
            program_count, tone_count, vag_count = struct.unpack_from(
                "<3H", header, 18
            )
            stem = f"bank-u{unit_index:03d}-b{bank_index:02d}"
            directory = output_root / "decoded" / "sound" / "vab"
            vh_path = directory / f"{stem}.vh"
            vb_path = directory / f"{stem}.vb"
            vab_path = directory / f"{stem}.vab"
            write_checked(vh_path, header)
            write_checked(vb_path, body)
            combined = header + body
            if len(combined) != total_size:
                raise ValueError("VAB combined size mismatch")
            write_checked(vab_path, combined)
            banks.append(
                {
                    "header_unit_index": unit_index,
                    "header_child_index": header_record["index"],
                    "body_unit_index": unit_index + 1,
                    "body_child_index": body_record["index"],
                    "program_count": program_count,
                    "tone_count": tone_count,
                    "vag_count": vag_count,
                    "header_byte_size": len(header),
                    "body_byte_size": len(body),
                    "padding_byte_size": len(
                        data[
                            body_record["file_offset"] : body_record["file_offset"]
                            + body_record["byte_size"]
                        ]
                    )
                    - len(body),
                    "combined_byte_size": len(combined),
                    "combined_sha256": sha256_bytes(combined),
                    "vh_path": relative(vh_path, output_root),
                    "vb_path": relative(vb_path, output_root),
                    "vab_path": relative(vab_path, output_root),
                }
            )
    child_count = sum(len(unit.get("children", [])) for unit in units)
    if len(banks) != 81 or len(sequences) != 1738:
        raise ValueError(
            f"SOUND denominator mismatch: banks={len(banks)} "
            f"sequences={len(sequences)}"
        )
    if child_count != len(banks) * 2 + len(sequences):
        raise ValueError("unclassified SOUND child remains")
    result = {
        "schema_version": 1,
        "summary": {
            "scheduled_unit_count": len(units),
            "child_count": child_count,
            "vab_bank_count": len(banks),
            "vab_body_count": len(banks),
            "sequence_count": len(sequences),
            "unclassified_child_count": 0,
        },
        "vab_banks": banks,
        "sequences": sequences,
    }
    write_json(output_root / "manifests" / "sound.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--disc-root",
        type=Path,
        default=Path("work/disc1/full"),
        help="verified Form 1 ISO files used by the structural inventory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("work/extracted/disc1"),
    )
    args = parser.parse_args()

    media_manifest = load_manifest()
    media_paths = resolved_paths(media_manifest)
    track_verification = verify_track(
        media_paths["disc1_track1"],
        media_manifest["disc1"]["data_track"],
    )
    cue_verification = verify_cue(
        media_paths["disc1_cue"],
        media_manifest["disc1"]["expected_tracks"],
    )
    output_root = args.output
    output_root.mkdir(parents=True, exist_ok=True)

    layout = build_inventory(args.disc_root / "SLPS_019.58", args.disc_root)
    write_json(output_root / "manifests" / "layout.json", layout)
    with PsxDisc(media_paths["disc1_track1"]) as disc:
        iso_files, stream_sources = extract_iso_files(disc, output_root)
        xa_channels = split_xa_audio(disc, stream_sources, output_root)
    cdda_tracks = copy_cdda_tracks(media_paths["disc1_cue"], output_root)
    schedules = extract_schedules(layout, args.disc_root, output_root)
    write_json(output_root / "manifests" / "schedules.json", schedules)
    text = extract_text(args.disc_root, output_root)
    fonts = extract_fonts(args.disc_root, layout, output_root)
    portraits = extract_portraits(args.disc_root, layout, output_root)
    vram = extract_vram_previews(args.disc_root, layout, output_root)
    sound = extract_sound(args.disc_root, layout, output_root)

    root_report = {
        "schema_version": 1,
        "source": {
            "track1": track_verification,
            "cue": cue_verification,
        },
        "policy": {
            "original_mutated": False,
            "unknown_record_policy": (
                "preserve byte-exact raw child; do not guess a decompressor"
            ),
            "next_stage": (
                "decode_disc1_streams.py converts proven MDEC, XA ADPCM, "
                "VAB ADPCM, and CDDA inputs"
            ),
        },
        "summary": {
            "iso_entry_count": len(iso_files),
            "iso_extracted_count": sum(
                entry["status"] == "extracted" for entry in iso_files
            ),
            "external_cdda_reference_count": sum(
                entry["status"] == "external_cdda_reference"
                for entry in iso_files
            ),
            "scheduled_state_count": schedules["summary"]["state_count"],
            "scheduled_child_count": schedules["summary"]["child_count"],
            "text_stream_count": len(text["entries"]),
            "font_glyph_slot_count": fonts["summary"]["glyph_slot_count"],
            "portrait_count": len(portraits["items"]),
            "structural_vram_record_count": vram["summary"][
                "structural_vram_record_count"
            ],
            "decoded_vram_palette_variant_count": vram["summary"][
                "decoded_palette_variant_count"
            ],
            "vab_bank_count": sound["summary"]["vab_bank_count"],
            "sequence_count": sound["summary"]["sequence_count"],
            "xa_audio_stream_count": len(xa_channels),
            "cdda_track_count": len(cdda_tracks),
        },
        "iso_files": iso_files,
        "xa_audio_streams": xa_channels,
        "cdda_tracks": cdda_tracks,
        "manifests": {
            "layout": "manifests/layout.json",
            "schedules": "manifests/schedules.json",
            "text": "manifests/text.json",
            "fonts": "manifests/fonts.json",
            "portraits": "manifests/portraits.json",
            "vram": "manifests/vram.json",
            "sound": "manifests/sound.json",
        },
    }
    write_json(output_root / "manifest.json", root_report)
    print(output_root / "manifest.json")
    print(json.dumps(root_report["summary"], indent=2))


if __name__ == "__main__":
    main()
