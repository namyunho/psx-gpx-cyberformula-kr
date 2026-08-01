#!/usr/bin/env python3
"""Build a read-only structural inventory of Cyber Formula disc data.

The inventory ties the boot EXE's file records, sector schedules, and load
descriptors to byte ranges in the extracted ISO files.  It also marks
offset-directory children that are structurally compatible with raw PS1 VRAM
rectangles.  A structural match is a render candidate, not consumer proof;
known font/code providers must still be excluded by load and use tracing.
Unknown records stay unknown; prefix bytes are never treated as a file type
without a structural check.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

try:
    from scripts.original_media import load_manifest
except ModuleNotFoundError:  # Direct execution from the repository root.
    from original_media import load_manifest


SECTOR_SIZE = 0x800
EXE_FILE_RECORDS_VA = 0x80057444
EXE_FILE_RECORD_COUNT = 19
LOAD_DESCRIPTORS_VA = 0x80058FB8
LOAD_DESCRIPTOR_COUNT = 164


@dataclass(frozen=True)
class ScheduleSpec:
    file_id: int
    filename: str
    table_va: int
    table_limit_va: int


@dataclass(frozen=True)
class EmbeddedScheduleSpec:
    file_id: int
    filename: str
    container_filename: str
    table_file_offset: int
    table_ram_address: int
    maximum_entries: int


SCHEDULE_SPECS = (
    ScheduleSpec(8, "MINI_G1.BIN", 0x80057658, 0x80057660),
    ScheduleSpec(9, "MINI_G2.BIN", 0x80057660, 0x80057668),
    ScheduleSpec(10, "MINI_G3.BIN", 0x80057668, 0x80057674),
    ScheduleSpec(11, "MINI_G4.BIN", 0x80057674, 0x80057680),
    ScheduleSpec(14, "AVM_MAP.BIN", 0x80057680, 0x80058B74),
    ScheduleSpec(1, "START.BIN", 0x80058B74, 0x80058C78),
    ScheduleSpec(2, "SOUND.BIN", 0x80058C78, 0x80058ED8),
    ScheduleSpec(3, "ALLBIN.BIN", 0x80058ED8, 0x80058F88),
    ScheduleSpec(4, "OUTSIDE.BIN", 0x80058F88, 0x80058FB4),
)

EMBEDDED_SCHEDULE_SPECS = (
    EmbeddedScheduleSpec(
        13,
        "MACHINE.BIN",
        "ALLBIN.BIN",
        0x12A9D4,
        0x800AA9D4,
        42,
    ),
    EmbeddedScheduleSpec(
        12,
        "COURSE.BIN",
        "ALLBIN.BIN",
        0x12AA7C,
        0x800AAA7C,
        277,
    ),
)


class PsxExe:
    """Minimal, bounds-checked PS-X EXE virtual-address reader."""

    def __init__(self, data: bytes) -> None:
        if len(data) < 0x800 or data[:8] != b"PS-X EXE":
            raise ValueError("not a complete PS-X EXE")
        self.data = data
        self.entry, self.gp, self.load_address, self.text_size = struct.unpack_from(
            "<4I", data, 0x10
        )
        if len(data) < 0x800 + self.text_size:
            raise ValueError("truncated PS-X EXE payload")

    def read(self, address: int, size: int) -> bytes:
        relative = address - self.load_address
        if relative < 0 or relative + size > self.text_size:
            raise ValueError(
                f"virtual address outside EXE payload: 0x{address:08X}+0x{size:X}"
            )
        start = 0x800 + relative
        return self.data[start : start + size]

    def c_string(self, address: int, maximum: int = 256) -> str:
        raw = self.read(address, maximum)
        end = raw.find(b"\0")
        if end < 0:
            raise ValueError(f"unterminated string at 0x{address:08X}")
        return raw[:end].decode("ascii", "replace")


def discover_schedule(
    exe: PsxExe, table_va: int, table_limit_va: int, file_size: int
) -> list[dict[str, int]]:
    """Read a contiguous ``{u16 start_sector, u16 sector_count}`` partition."""

    table = exe.read(table_va, table_limit_va - table_va)
    return discover_schedule_bytes(table, file_size)


def discover_schedule_bytes(
    table: bytes,
    file_size: int,
    *,
    maximum_entries: int | None = None,
) -> list[dict[str, int]]:
    """Parse a schedule table and prove that it partitions an entire file."""

    if file_size % SECTOR_SIZE:
        raise ValueError(f"scheduled file is not sector aligned: 0x{file_size:X}")
    total_sectors = file_size // SECTOR_SIZE
    available_entries = len(table) // 4
    maximum = (
        available_entries
        if maximum_entries is None
        else min(maximum_entries, available_entries)
    )
    expected_start = 0
    result: list[dict[str, int]] = []
    for index in range(maximum):
        start_sector, sector_count = struct.unpack_from("<HH", table, index * 4)
        if start_sector != expected_start or sector_count == 0:
            raise ValueError(
                f"broken schedule at table offset 0x{index * 4:X}: "
                f"start={start_sector}, count={sector_count}, expected={expected_start}"
            )
        byte_offset = start_sector * SECTOR_SIZE
        byte_size = sector_count * SECTOR_SIZE
        result.append(
            {
                "index": index,
                "start_sector": start_sector,
                "sector_count": sector_count,
                "byte_offset": byte_offset,
                "byte_size": byte_size,
                "byte_end": byte_offset + byte_size,
            }
        )
        expected_start += sector_count
        if expected_start == total_sectors:
            return result
        if expected_start > total_sectors:
            break
    raise ValueError(
        f"schedule does not partition file: {expected_start} != "
        f"{total_sectors} sectors"
    )


def parse_offset_directory(unit: bytes) -> list[int] | None:
    """Return child offsets when the unit begins with a valid offset directory."""

    if len(unit) < 4:
        return None
    first_offset = struct.unpack_from("<I", unit)[0]
    if first_offset < 4 or first_offset > len(unit) or first_offset % 4:
        return None
    offsets = list(struct.unpack_from(f"<{first_offset // 4}I", unit))
    if not offsets or offsets[0] != first_offset:
        return None
    if any(offset < first_offset or offset >= len(unit) for offset in offsets):
        return None
    if any(left >= right for left, right in zip(offsets, offsets[1:])):
        return None
    return offsets


def classify_child(child: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(child).hexdigest()
    base: dict[str, Any] = {
        "byte_size": len(child),
        "sha256": digest,
    }
    if child and not any(child):
        return {**base, "kind": "zero_fill"}

    if len(child) >= 8:
        x, y, width, height = struct.unpack_from("<4H", child)
        payload_size = 2 * width * height
        record_size = 8 + payload_size
        in_vram = (
            width > 0
            and height > 0
            and x < 1024
            and y < 512
            and x + width <= 1024
            and y + height <= 512
        )
        zero_padded = record_size <= len(child) and not any(child[record_size:])
        if in_vram and zero_padded:
            return {
                **base,
                "kind": "raw_vram_rectangle",
                "rect": {"x": x, "y": y, "width_halfwords": width, "height": height},
                "payload_size": payload_size,
                "zero_padding": len(child) - record_size,
            }

    leading_u32 = struct.unpack_from("<I", child)[0] if len(child) >= 4 else None
    if leading_u32 == 0xC0000322:
        kind = "render_metadata_0x22"
    elif child[:1] == b"\x23":
        kind = "render_metadata_0x23"
    else:
        kind = "unknown"
    return {
        **base,
        "kind": kind,
        "leading_u32": leading_u32,
    }


def inventory_scheduled_file(
    data: bytes, schedule: list[dict[str, int]]
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    units: list[dict[str, Any]] = []
    for span in schedule:
        start = span["byte_offset"]
        end = span["byte_end"]
        unit = data[start:end]
        offsets = parse_offset_directory(unit)
        unit_record: dict[str, Any] = {
            **span,
            "sha256": hashlib.sha256(unit).hexdigest(),
        }
        if offsets is None:
            classified = classify_child(unit)
            if classified["kind"] == "raw_vram_rectangle":
                counts["units_raw_vram_rectangle"] += 1
                unit_record.update(classified)
            else:
                counts["units_without_offset_directory"] += 1
                unit_record["kind"] = "unknown_unit"
                unit_record["leading_u32"] = (
                    struct.unpack_from("<I", unit)[0] if len(unit) >= 4 else None
                )
        else:
            counts["units_with_offset_directory"] += 1
            unit_record["kind"] = "offset_directory"
            children = []
            for child_index, (child_start, child_end) in enumerate(
                zip(offsets, offsets[1:] + [len(unit)])
            ):
                classified = classify_child(unit[child_start:child_end])
                counts[f"children_{classified['kind']}"] += 1
                children.append(
                    {
                        "index": child_index,
                        "unit_offset": child_start,
                        "file_offset": start + child_start,
                        **classified,
                    }
                )
            unit_record["children"] = children
        units.append(unit_record)
    return {"counts": dict(sorted(counts.items())), "units": units}


def read_file_records(exe: PsxExe) -> list[dict[str, Any]]:
    records = []
    for index in range(EXE_FILE_RECORD_COUNT):
        address = EXE_FILE_RECORDS_VA + index * 28
        path_pointer = struct.unpack("<I", exe.read(address, 4))[0]
        records.append(
            {
                "file_id": index,
                "record_va": address,
                "path_pointer": path_pointer,
                "path": exe.c_string(path_pointer),
            }
        )
    return records


def read_load_descriptors(
    exe: PsxExe,
    schedules_by_pointer: dict[int, tuple[str, list[dict[str, int]]]],
) -> list[dict[str, Any]]:
    result = []
    for index in range(LOAD_DESCRIPTOR_COUNT):
        address = LOAD_DESCRIPTORS_VA + index * 12
        file_id, sub_id, schedule_pointer, destination = struct.unpack(
            "<hhII", exe.read(address, 12)
        )
        record: dict[str, Any] = {
            "index": index,
            "descriptor_va": address,
            "file_id": file_id,
            "sub_id": sub_id,
            "schedule_pointer": schedule_pointer,
            "ram_destination": destination,
        }
        scheduled = schedules_by_pointer.get(schedule_pointer)
        if scheduled is not None:
            filename, schedule = scheduled
            record["filename"] = filename
            if 0 <= sub_id < len(schedule):
                span = schedule[sub_id]
                record["source_offset"] = span["byte_offset"]
                record["source_size"] = span["byte_size"]
                record["source_end"] = span["byte_end"]
                record["load_delta"] = destination - span["byte_offset"]
            else:
                record["source_range"] = "runtime_mutated_or_out_of_range"
        elif schedule_pointer in {0x800AAA7C, 0x800AA9D4}:
            record["source_range"] = "runtime_schedule"
        else:
            record["source_range"] = "placeholder_or_unknown_schedule"
        result.append(record)
    return result


def build_inventory(exe_path: Path, disc_root: Path) -> dict[str, Any]:
    exe = PsxExe(exe_path.read_bytes())
    schedules: dict[str, dict[str, Any]] = {}
    schedules_by_pointer: dict[int, tuple[str, list[dict[str, int]]]] = {}
    for spec in SCHEDULE_SPECS:
        path = disc_root / spec.filename
        data = path.read_bytes()
        spans = discover_schedule(
            exe, spec.table_va, spec.table_limit_va, len(data)
        )
        schedules[spec.filename] = {
            "file_id": spec.file_id,
            "table_source": "boot_exe",
            "table_va": spec.table_va,
            "entry_count": len(spans),
            "file_size": len(data),
            "complete_partition": spans[-1]["byte_end"] == len(data),
            "entries": spans,
            "inventory": inventory_scheduled_file(data, spans),
        }
        schedules_by_pointer[spec.table_va] = (spec.filename, spans)

    for spec in EMBEDDED_SCHEDULE_SPECS:
        path = disc_root / spec.filename
        data = path.read_bytes()
        container = (disc_root / spec.container_filename).read_bytes()
        table_size = spec.maximum_entries * 4
        table_end = spec.table_file_offset + table_size
        if table_end > len(container):
            raise ValueError(
                f"embedded schedule exceeds {spec.container_filename}: "
                f"0x{spec.table_file_offset:X}+0x{table_size:X}"
            )
        spans = discover_schedule_bytes(
            container[spec.table_file_offset:table_end],
            len(data),
            maximum_entries=spec.maximum_entries,
        )
        schedules[spec.filename] = {
            "file_id": spec.file_id,
            "table_source": "ALLBIN_unit_37",
            "container_filename": spec.container_filename,
            "table_file_offset": spec.table_file_offset,
            "table_ram_address": spec.table_ram_address,
            "entry_count": len(spans),
            "file_size": len(data),
            "complete_partition": spans[-1]["byte_end"] == len(data),
            "entries": spans,
            "inventory": inventory_scheduled_file(data, spans),
        }
        schedules_by_pointer[spec.table_ram_address] = (spec.filename, spans)

    return {
        "schema_version": 1,
        "method": {
            "sector_size": SECTOR_SIZE,
            "raw_vram_rectangle_proof": (
                "scheduled unit or offset-directory child; positive in-bounds "
                "PS1 VRAM rectangle; "
                "payload is exactly 2*width*height bytes plus zero padding"
            ),
            "unknown_policy": "unproven records remain explicitly unknown",
        },
        "boot_exe": {
            "path": str(exe_path),
            "entry": exe.entry,
            "gp": exe.gp,
            "load_address": exe.load_address,
            "text_size": exe.text_size,
        },
        "file_records": read_file_records(exe),
        "schedules": schedules,
        "load_descriptors": read_load_descriptors(exe, schedules_by_pointer),
        "embedded_schedules": [
            {
                "filename": spec.filename,
                "file_id": spec.file_id,
                "container_filename": spec.container_filename,
                "table_file_offset": spec.table_file_offset,
                "table_ram_address": spec.table_ram_address,
                "entry_count": len(schedules[spec.filename]["entries"]),
                "status": "complete_partition_proven",
            }
            for spec in EMBEDDED_SCHEDULE_SPECS
        ],
    }


def summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "boot_exe": report["boot_exe"],
        "file_record_count": len(report["file_records"]),
        "load_descriptor_count": len(report["load_descriptors"]),
        "schedules": {
            filename: {
                "file_id": record["file_id"],
                "table_source": record["table_source"],
                "entry_count": record["entry_count"],
                "file_size": record["file_size"],
                "complete_partition": record["complete_partition"],
                "inventory_counts": record["inventory"]["counts"],
            }
            for filename, record in report["schedules"].items()
        },
        "embedded_schedules": report["embedded_schedules"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--disc",
        default="disc1",
        help="disc key used only for default paths (default: disc1)",
    )
    parser.add_argument(
        "--disc-root", type=Path
    )
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    disc_key = args.disc.lower()
    media_manifest = load_manifest()
    if disc_key not in media_manifest:
        parser.error(f"unsupported disc key: {disc_key}")
    boot_exe = media_manifest[disc_key]["boot_exe"]
    disc_root = args.disc_root or Path("work") / disc_key / "full"
    exe_path = args.exe or disc_root / boot_exe
    report = build_inventory(exe_path, disc_root)
    selected = summary(report) if args.summary else report
    rendered = json.dumps(selected, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(args.output)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
