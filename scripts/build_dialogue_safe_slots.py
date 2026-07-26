#!/usr/bin/env python3
"""Build verified fixed-original dialogue safe-slot metadata.

The catalog records the largest encoded stream that can start at each
original ALLBIN address without consuming any inter-entry bytes. It is a
physical placement constraint, independent from the renderer's 17-column by
3-row display constraint.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_WORKSET = Path("work/translations/disc1-dialogue.json")
DEFAULT_ALLBIN = Path("work/extracted/disc1/iso/ALLBIN.BIN")
DEFAULT_OUTPUT = Path("work/analysis/disc1-dialogue-safe-slots.json")
DEFAULT_CSV_OUTPUT = Path("work/analysis/disc1-dialogue-safe-slots.csv")


@dataclass(frozen=True)
class FixedOriginalSafeSlot:
    """One immutable-start stream budget derived from original ALLBIN bytes."""

    entry_id: str
    unit_index: int
    subsystem: str
    physical_order_index: int
    file_offset: str
    unit_offset: str
    original_end_file_offset: str
    original_end_unit_offset: str
    safe_end_file_offset: str
    safe_end_unit_offset: str
    original_stream_bytes: int
    safe_slot_bytes: int
    safe_slot_words: int
    additional_zero_gap_bytes: int
    gap_after_original_bytes: int
    gap_nonzero_byte_count: int
    boundary_kind: str
    next_physical_entry_id: str | None
    protected_target: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def physical_entry_ranges(
    entries: Iterable[dict[str, Any]],
) -> list[tuple[int, int, dict[str, Any]]]:
    """Return non-overlapping entry ranges in physical unit order."""
    ranges = []
    ordered = sorted(
        entries,
        key=lambda entry: int(entry["source"]["unit_offset"], 16),
    )
    for entry in ordered:
        start = int(entry["source"]["unit_offset"], 16)
        size = int(entry["source"]["byte_size"])
        if start < 0 or size <= 0 or start % 2 or size % 2:
            raise ValueError(
                f"{entry['entry_id']}: source range must be positive "
                "and 16-bit aligned"
            )
        end = start + size
        if ranges and start < ranges[-1][1]:
            raise ValueError(f"{entry['entry_id']}: source text ranges overlap")
        ranges.append((start, end, entry))
    return ranges


def fixed_original_safe_slots(
    unit_data: bytes,
    entries: Iterable[dict[str, Any]],
) -> list[FixedOriginalSafeSlot]:
    """Measure fixed-start capacity without consuming protected bytes."""
    ranges = physical_entry_ranges(entries)
    if not ranges:
        raise ValueError("cannot calculate safe slots for an empty unit")
    unit_index = int(ranges[0][2]["source"]["unit_index"])
    if any(
        int(entry["source"]["unit_index"]) != unit_index
        for _, _, entry in ranges
    ):
        raise ValueError("safe-slot calculation received mixed units")
    if ranges[-1][1] > len(unit_data):
        raise ValueError(f"unit {unit_index}: source entry exceeds unit data")

    records: list[FixedOriginalSafeSlot] = []
    for physical_index, (start, end, entry) in enumerate(ranges):
        next_entry_id: str | None = None
        gap = b""
        if physical_index + 1 < len(ranges):
            next_start, _, next_entry = ranges[physical_index + 1]
            next_entry_id = str(next_entry["entry_id"])
            gap = unit_data[end:next_start]
            safe_end = end
            if any(gap):
                boundary_kind = "protected-nonzero-gap"
                protected_target = "pointerless-fallthrough-or-event-data"
            elif gap:
                boundary_kind = "protected-zero-fallthrough-gap"
                protected_target = "runtime-fallthrough-zero-word"
            else:
                safe_end = next_start
                boundary_kind = "adjacent-next-entry"
                protected_target = next_entry_id
        else:
            safe_end = end
            boundary_kind = "last-extracted-entry-original-end"
            protected_target = "unclassified-unit-tail"

        source = entry["source"]
        unit_file_offset = (
            int(source["file_offset"], 16)
            - int(source["unit_offset"], 16)
        )
        safe_bytes = safe_end - start
        records.append(
            FixedOriginalSafeSlot(
                entry_id=str(entry["entry_id"]),
                unit_index=unit_index,
                subsystem=str(source.get("subsystem", "unknown")),
                physical_order_index=physical_index,
                file_offset=f"0x{unit_file_offset + start:06X}",
                unit_offset=f"0x{start:04X}",
                original_end_file_offset=f"0x{unit_file_offset + end:06X}",
                original_end_unit_offset=f"0x{end:04X}",
                safe_end_file_offset=f"0x{unit_file_offset + safe_end:06X}",
                safe_end_unit_offset=f"0x{safe_end:04X}",
                original_stream_bytes=end - start,
                safe_slot_bytes=safe_bytes,
                safe_slot_words=safe_bytes // 2,
                additional_zero_gap_bytes=safe_end - end,
                gap_after_original_bytes=len(gap),
                gap_nonzero_byte_count=sum(byte != 0 for byte in gap),
                boundary_kind=boundary_kind,
                next_physical_entry_id=next_entry_id,
                protected_target=protected_target,
            )
        )
    return records


def _load_workset(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        raise ValueError(f"{path}: dialogue workset requires an entries list")
    return value, raw


def build_safe_slot_catalog(
    workset: dict[str, Any],
    *,
    workset_bytes: bytes,
    allbin: bytes,
    workset_path: Path,
    allbin_path: Path,
) -> dict[str, Any]:
    """Validate source evidence and produce one record per stable ID."""
    entries = workset["entries"]
    if not entries or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("dialogue workset entries must be nonempty objects")

    expected_allbin_hash = (
        workset.get("scope", {}).get("source_allbin_sha256")
        if isinstance(workset.get("scope"), dict)
        else None
    )
    actual_allbin_hash = sha256_bytes(allbin)
    if (
        not isinstance(expected_allbin_hash, str)
        or expected_allbin_hash != actual_allbin_hash
    ):
        raise ValueError(
            "ALLBIN hash differs from the dialogue workset baseline: "
            f"expected={expected_allbin_hash} actual={actual_allbin_hash}"
        )

    by_unit: dict[int, list[dict[str, Any]]] = defaultdict(list)
    ids: set[str] = set()
    for entry in entries:
        entry_id = entry.get("entry_id")
        source = entry.get("source")
        original = entry.get("original")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError("dialogue workset contains an invalid stable ID")
        if entry_id in ids:
            raise ValueError(f"duplicate dialogue stable ID: {entry_id}")
        ids.add(entry_id)
        if not isinstance(source, dict) or not isinstance(original, dict):
            raise ValueError(f"{entry_id}: missing protected source/original data")
        if source.get("container") != "ALLBIN.BIN":
            raise ValueError(f"{entry_id}: unsupported source container")
        try:
            unit_index = int(source["unit_index"])
            file_offset = int(source["file_offset"], 16)
            unit_offset = int(source["unit_offset"], 16)
            byte_size = int(source["byte_size"])
            raw = bytes.fromhex(original["raw_hex"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{entry_id}: invalid source coordinates") from error
        if byte_size != len(raw):
            raise ValueError(f"{entry_id}: byte_size differs from original raw")
        if file_offset < 0 or file_offset + byte_size > len(allbin):
            raise ValueError(f"{entry_id}: source range exceeds ALLBIN")
        if allbin[file_offset : file_offset + byte_size] != raw:
            raise ValueError(f"{entry_id}: source ALLBIN bytes differ")
        source_hash = source.get("sha256")
        if source_hash != sha256_bytes(raw):
            raise ValueError(f"{entry_id}: source raw hash differs")
        if file_offset - unit_offset < 0:
            raise ValueError(f"{entry_id}: invalid unit base")
        by_unit[unit_index].append(entry)

    records_by_id: dict[str, FixedOriginalSafeSlot] = {}
    for unit_index, unit_entries in sorted(by_unit.items()):
        unit_bases = {
            int(entry["source"]["file_offset"], 16)
            - int(entry["source"]["unit_offset"], 16)
            for entry in unit_entries
        }
        if len(unit_bases) != 1:
            raise ValueError(f"unit {unit_index}: inconsistent ALLBIN base")
        unit_base = unit_bases.pop()
        ranges = physical_entry_ranges(unit_entries)
        unit_end = ranges[-1][1]
        unit_data = allbin[unit_base : unit_base + unit_end]
        for record in fixed_original_safe_slots(unit_data, unit_entries):
            records_by_id[record.entry_id] = record

    if set(records_by_id) != ids:
        raise ValueError("safe-slot catalog IDs differ from workset IDs")
    ordered_records = [records_by_id[entry["entry_id"]] for entry in entries]
    boundary_counts = Counter(record.boundary_kind for record in ordered_records)
    total_original = sum(
        record.original_stream_bytes for record in ordered_records
    )
    total_safe = sum(record.safe_slot_bytes for record in ordered_records)

    return {
        "schema_version": 1,
        "catalog_kind": "disc1-fixed-original-dialogue-safe-slots",
        "status": "verified-physical-boundaries-runtime-qa-required",
        "source": {
            "workset": str(workset_path),
            "workset_sha256": sha256_bytes(workset_bytes),
            "baseline_id": workset.get("baseline_id"),
            "allbin": str(allbin_path),
            "allbin_sha256": actual_allbin_hash,
            "source_entry_bytes_verified": len(entries),
        },
        "policy": {
            "placement": "fixed-original-entry-start",
            "encoded_size_includes": (
                "visible glyphs, line-break controls, leading controls, "
                "and terminal controls"
            ),
            "zero_gap": (
                "protected because the runtime cursor traverses the physical "
                "inter-entry stream; zero-valued bytes are not promoted to "
                "allocator padding"
            ),
            "nonzero_gap": (
                "protected as pointerless fall-through or event data; "
                "safe slot ends at the original stream end"
            ),
            "last_entry": (
                "no unclassified unit-tail bytes are borrowed; safe slot "
                "ends at the original stream end"
            ),
            "display_constraint": (
                "17x3 is checked separately and does not allocate 51 words "
                "to every entry"
            ),
            "runtime_note": (
                "This proves conservative physical write boundaries. "
                "Portrait, branch, and sequential runtime behavior still "
                "requires emulator execution QA."
            ),
        },
        "summary": {
            "entry_count": len(ordered_records),
            "unit_count": len(by_unit),
            "original_stream_bytes": total_original,
            "safe_slot_bytes": total_safe,
            "additional_verified_zero_gap_bytes": total_safe - total_original,
            "entries_with_additional_zero_gap": sum(
                record.additional_zero_gap_bytes > 0
                for record in ordered_records
            ),
            "protected_zero_gap_bytes": sum(
                record.gap_after_original_bytes
                for record in ordered_records
                if record.boundary_kind
                == "protected-zero-fallthrough-gap"
            ),
            "entries_with_protected_zero_gap": sum(
                record.boundary_kind
                == "protected-zero-fallthrough-gap"
                for record in ordered_records
            ),
            "minimum_safe_slot_bytes": min(
                record.safe_slot_bytes for record in ordered_records
            ),
            "maximum_safe_slot_bytes": max(
                record.safe_slot_bytes for record in ordered_records
            ),
            "boundary_kind_counts": dict(sorted(boundary_counts.items())),
        },
        "entries": [
            {
                "id": record.entry_id,
                **{
                    key: value
                    for key, value in asdict(record).items()
                    if key != "entry_id"
                },
            }
            for record in ordered_records
        ],
    }


def write_catalog_json(path: Path, catalog: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_catalog_csv(path: Path, catalog: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = catalog["entries"]
    fieldnames = [
        "id",
        "unit_index",
        "subsystem",
        "physical_order_index",
        "file_offset",
        "unit_offset",
        "original_end_file_offset",
        "original_end_unit_offset",
        "safe_end_file_offset",
        "safe_end_unit_offset",
        "original_stream_bytes",
        "safe_slot_bytes",
        "safe_slot_words",
        "additional_zero_gap_bytes",
        "gap_after_original_bytes",
        "gap_nonzero_byte_count",
        "boundary_kind",
        "next_physical_entry_id",
        "protected_target",
    ]
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow({field: entry.get(field) for field in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workset", type=Path, default=DEFAULT_WORKSET)
    parser.add_argument("--allbin", type=Path, default=DEFAULT_ALLBIN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    args = parser.parse_args()

    workset, workset_bytes = _load_workset(args.workset)
    catalog = build_safe_slot_catalog(
        workset,
        workset_bytes=workset_bytes,
        allbin=args.allbin.read_bytes(),
        workset_path=args.workset,
        allbin_path=args.allbin,
    )
    write_catalog_json(args.output, catalog)
    write_catalog_csv(args.csv_output, catalog)
    print(
        json.dumps(
            {
                "json": str(args.output),
                "csv": str(args.csv_output),
                **catalog["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
