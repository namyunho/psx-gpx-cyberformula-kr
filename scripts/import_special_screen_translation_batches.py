#!/usr/bin/env python3
"""Merge reviewed special-screen ``-ko`` batches into the canonical draft."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

try:
    from scripts.export_special_screen_translation_brief import (
        draft_issues,
        visible_length,
    )
except ModuleNotFoundError:
    from export_special_screen_translation_brief import (
        draft_issues,
        visible_length,
    )


NAME_TOKEN_PATTERN = re.compile(r"\{name:(?:surname|given)\}")
MEANINGFUL_SYMBOLS = ("◯", "♥", "💢", "💦", "💧", "♪", "ZERO")


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_batch(batch: dict[str, Any]) -> dict[str, Any]:
    protected = copy.deepcopy(batch)
    entries = protected.get("entries")
    if not isinstance(entries, list):
        raise ValueError("batch entries must be an array")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("batch entry must be an object")
        entry.pop("ko", None)
    return protected


def encoded_positions(text: str) -> int:
    lines = text.split("\n")
    return sum(visible_length(line) for line in lines) + len(lines) - 1


def merge_translation_batches(
    *,
    workset: dict[str, Any],
    canonical: dict[str, Any],
    source_batches: list[dict[str, Any]],
    translated_batches: list[dict[str, Any]],
    source_batch_paths: list[Path],
    translated_batch_paths: list[Path],
    workset_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not source_batches or len(source_batches) != len(translated_batches):
        raise ValueError("source and translated batch counts must match")
    if len(source_batches) != len(source_batch_paths) or len(
        translated_batches
    ) != len(translated_batch_paths):
        raise ValueError("batch documents and paths must match")

    baseline_id = workset.get("baseline_id")
    if (
        not isinstance(baseline_id, str)
        or canonical.get("baseline_id") != baseline_id
    ):
        raise ValueError("canonical/workset baseline differs")
    actual_workset_hash = sha256_file(workset_path)
    if canonical.get("source_workset_sha256") != actual_workset_hash:
        raise ValueError("canonical translation uses a different workset")

    work_entries = workset.get("entries")
    canonical_items = canonical.get("translations")
    if not isinstance(work_entries, list) or not isinstance(
        canonical_items, list
    ):
        raise ValueError("workset/canonical entry arrays are missing")
    work_ids = [entry.get("entry_id") for entry in work_entries]
    canonical_ids = [entry.get("id") for entry in canonical_items]
    if (
        any(not isinstance(entry_id, str) for entry_id in work_ids)
        or canonical_ids != work_ids
        or len(set(work_ids)) != len(work_ids)
    ):
        raise ValueError("canonical/workset stable ID order differs")
    work_by_id = {
        str(entry["entry_id"]): entry for entry in work_entries
    }

    translated_entries: list[dict[str, Any]] = []
    expected_start = 0
    batch_sources: list[dict[str, Any]] = []
    for source, translated, source_path, translated_path in zip(
        source_batches,
        translated_batches,
        source_batch_paths,
        translated_batch_paths,
    ):
        if protected_batch(source) != protected_batch(translated):
            raise ValueError(
                f"{translated_path}: fields other than entries[].ko changed"
            )
        if (
            source.get("baseline_id") != baseline_id
            or translated.get("baseline_id") != baseline_id
        ):
            raise ValueError(f"{translated_path}: baseline differs")
        batch = translated.get("batch")
        entries = translated.get("entries")
        if not isinstance(batch, dict) or not isinstance(entries, list):
            raise ValueError(f"{translated_path}: invalid batch structure")
        start = batch.get("start_entry_index")
        end = batch.get("end_entry_index_exclusive")
        count = batch.get("entry_count")
        total = batch.get("total_entry_count")
        if (
            start != expected_start
            or not isinstance(end, int)
            or end < start
            or count != len(entries)
            or end - start != len(entries)
            or total != len(work_ids)
        ):
            raise ValueError(
                f"{translated_path}: batch range/count differs"
            )
        expected_start = end
        translated_entries.extend(entries)
        batch_sources.append(
            {
                "source_batch": str(source_path),
                "source_batch_sha256": sha256_file(source_path),
                "translated_batch": str(translated_path),
                "translated_batch_sha256": sha256_file(translated_path),
                "entry_count": len(entries),
            }
        )
    if expected_start != len(work_ids):
        raise ValueError("translated batches do not cover the full workset")

    translated_ids = [entry.get("id") for entry in translated_entries]
    if translated_ids != work_ids or len(set(translated_ids)) != len(
        translated_ids
    ):
        raise ValueError("translated batch stable ID order differs")

    issue_counts: Counter[str] = Counter()
    issue_entries: list[dict[str, Any]] = []
    translations_by_id: dict[str, str] = {}
    for item in translated_entries:
        entry_id = item.get("id")
        text = item.get("ko")
        if (
            not isinstance(entry_id, str)
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError(f"{entry_id!r}: Korean translation is empty")
        jp = item.get("jp")
        if not isinstance(jp, str):
            raise ValueError(f"{entry_id}: Japanese source is missing")
        if set(NAME_TOKEN_PATTERN.findall(jp)) != set(
            NAME_TOKEN_PATTERN.findall(text)
        ):
            raise ValueError(f"{entry_id}: fixed-name placeholder changed")
        for symbol in MEANINGFUL_SYMBOLS:
            if symbol in jp and symbol not in text:
                raise ValueError(
                    f"{entry_id}: meaningful symbol {symbol!r} is missing"
                )
        issues = draft_issues(work_by_id[entry_id], text)
        issue_counts.update(issues)
        if issues:
            positions = encoded_positions(text)
            maximum = int(item["max_encoded_positions"])
            issue_entries.append(
                {
                    "id": entry_id,
                    "issues": issues,
                    "line_widths": [
                        visible_length(line) for line in text.split("\n")
                    ],
                    "encoded_positions": positions,
                    "max_encoded_positions": maximum,
                    "slot_overflow_positions": max(0, positions - maximum),
                }
            )
        translations_by_id[entry_id] = text

    output = copy.deepcopy(canonical)
    for item in output["translations"]:
        item["ko"] = translations_by_id[str(item["id"])]
    output["status"] = (
        "external-ai-revised-draft-static-and-runtime-review-required"
    )
    scope = output.get("translation_scope")
    if isinstance(scope, dict):
        scope["model_role"] = "external-ai-revised-draft"
        scope["human_runtime_review_required"] = True
    output["batch_import"] = {
        "status": (
            "merged-static-review-required"
            if issue_entries
            else "merged-static-layout-clean-runtime-review-required"
        ),
        "entry_count": len(translated_entries),
        "stable_id_order_exact": True,
        "protected_batch_fields_unchanged": True,
        "workset": str(workset_path),
        "workset_sha256": actual_workset_hash,
        "batches": batch_sources,
        "validation": {
            "issue_entry_count": len(issue_entries),
            "issue_counts": dict(sorted(issue_counts.items())),
            "empty_translation_count": 0,
            "placeholder_mismatch_count": 0,
            "meaningful_symbol_missing_count": 0,
            "issues": issue_entries,
        },
    }
    report = {
        "schema_version": 1,
        "status": output["batch_import"]["status"],
        "output_status": output["status"],
        "entry_count": len(translated_entries),
        "stable_id_order_exact": True,
        "protected_batch_fields_unchanged": True,
        "source": {
            "workset": str(workset_path),
            "workset_sha256": actual_workset_hash,
            "batches": batch_sources,
        },
        "validation": copy.deepcopy(
            output["batch_import"]["validation"]
        ),
    }
    return output, report


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if load_object(temporary) != value:
            raise ValueError(f"{path}: temporary JSON verification differs")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def discover_batch_pairs(
    batch_dir: Path,
) -> tuple[list[Path], list[Path]]:
    translated = sorted(batch_dir.glob("disc1-special-screen-batch-*-ko.json"))
    if not translated:
        raise ValueError(f"{batch_dir}: no translated -ko batches found")
    source = [
        path.with_name(path.name.replace("-ko.json", ".json"))
        for path in translated
    ]
    missing = [path for path in source if not path.is_file()]
    if missing:
        raise ValueError(f"source batch is missing: {missing[0]}")
    return source, translated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workset",
        type=Path,
        default=Path("work/translations/disc1-special-screen-text.json"),
    )
    parser.add_argument(
        "--canonical",
        type=Path,
        default=Path("data/translations/disc1-special-screen-ko.json"),
    )
    parser.add_argument(
        "--batch-dir",
        type=Path,
        default=Path(
            "work/translations/"
            "disc1-special-screen-translation-batches"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "work/analysis/"
            "disc1-special-screen-translation-batch-import.json"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and print the report without writing files",
    )
    args = parser.parse_args()

    try:
        source_paths, translated_paths = discover_batch_pairs(args.batch_dir)
        merged, report = merge_translation_batches(
            workset=load_object(args.workset),
            canonical=load_object(args.canonical),
            source_batches=[load_object(path) for path in source_paths],
            translated_batches=[
                load_object(path) for path in translated_paths
            ],
            source_batch_paths=source_paths,
            translated_batch_paths=translated_paths,
            workset_path=args.workset,
        )
        if args.check:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        backup = args.canonical.with_name(f"{args.canonical.name}.bak")
        shutil.copy2(args.canonical, backup)
        write_json_atomic(args.canonical, merged)
        write_json_atomic(args.report, report)
        if load_object(args.canonical) != merged:
            raise ValueError("canonical post-write verification differs")
        print(
            json.dumps(
                {
                    "canonical": str(args.canonical),
                    "backup": str(backup),
                    "report": str(args.report),
                    "entry_count": report["entry_count"],
                    "issue_entry_count": report["validation"][
                        "issue_entry_count"
                    ],
                    "issue_counts": report["validation"]["issue_counts"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
