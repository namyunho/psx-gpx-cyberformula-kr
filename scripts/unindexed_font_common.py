#!/usr/bin/env python3
"""Validate and encode the reviewed additional primary-font text corpus."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any


EXPECTED_ENTRY_COUNT = 724
EXPECTED_CLASSIFICATION_COUNTS = {
    "indexed_minigame_page": 73,
    "indexed_race_page": 333,
    "save_ui_stream": 27,
    "sequential_event_page": 291,
}
NAME_PATTERN = re.compile(r"\{name:(surname|given)\}")
UNKNOWN_MARKUP_PATTERN = re.compile(r"\{[^{}]+\}")
NAME_KIND_BY_GROUP = {
    "surname": "name_surname",
    "given": "name_given",
}
PREFIX_CONTROL_KINDS = {"audio", "pace", "speaker_style"}
BODY_CONTROL_KINDS = {"align", "name_given", "name_surname"}
SUFFIX_CONTROL_KINDS = {
    "page_end",
    "stream_end",
    "voice_transition",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _visible_length(text: str) -> int:
    return len(NAME_PATTERN.sub("X", text))


def _template(
    entry: dict[str, Any],
) -> tuple[list[int], list[int], list[tuple[str, int]]]:
    tokens = [int(value, 16) for value in entry["original"]["tokens"]]
    controls = {
        int(control["token_index"]): str(control["kind"])
        for control in entry["original"]["control_tokens"]
    }
    if not tokens:
        raise ValueError(f"{entry['entry_id']}: empty source token stream")

    visible_indices = [
        index
        for index, token in enumerate(tokens)
        if index not in controls and token != 0
    ]
    if not visible_indices:
        raise ValueError(f"{entry['entry_id']}: no visible source glyph")
    first_visible = min(visible_indices)
    last_visible = max(visible_indices)

    for index in range(first_visible):
        kind = controls.get(index)
        if kind is None:
            if tokens[index] != 0:
                raise ValueError(
                    f"{entry['entry_id']}: nonzero glyph in prefix shell"
                )
        elif kind not in PREFIX_CONTROL_KINDS:
            raise ValueError(
                f"{entry['entry_id']}: unsupported prefix control {kind}"
            )

    for index in range(last_visible + 1, len(tokens)):
        kind = controls.get(index)
        if kind is None:
            if tokens[index] != 0:
                raise ValueError(
                    f"{entry['entry_id']}: nonzero glyph in suffix shell"
                )
        elif kind not in SUFFIX_CONTROL_KINDS:
            raise ValueError(
                f"{entry['entry_id']}: unsupported suffix control {kind}"
            )

    name_controls: list[tuple[str, int]] = []
    for index in range(first_visible, last_visible + 1):
        kind = controls.get(index)
        if kind is None:
            continue
        if kind not in BODY_CONTROL_KINDS:
            raise ValueError(
                f"{entry['entry_id']}: unsupported body control {kind}"
            )
        if kind in {"name_given", "name_surname"}:
            name_controls.append((kind, tokens[index]))
    return (
        tokens[:first_visible],
        tokens[last_visible + 1 :],
        name_controls,
    )


def validate_unindexed_artifacts(
    workset: dict[str, Any],
    translation: dict[str, Any],
    *,
    workset_path: Path,
    source_allbin: bytes,
    expected_allbin_sha256: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    expected_baseline = (
        f"disc1-allbin-{expected_allbin_sha256[:16]}"
    )
    if workset.get("baseline_id") != expected_baseline:
        raise ValueError("unindexed-font workset baseline differs")
    if translation.get("baseline_id") != expected_baseline:
        raise ValueError("unindexed-font translation baseline differs")
    if (
        workset.get("scope", {}).get("source_allbin_sha256")
        != expected_allbin_sha256
    ):
        raise ValueError("unindexed-font source ALLBIN hash differs")
    if translation.get("source_workset_sha256") != sha256_file(workset_path):
        raise ValueError("unindexed-font translation workset hash differs")

    entries = workset.get("entries")
    translated = translation.get("translations")
    if not isinstance(entries, list) or not isinstance(translated, list):
        raise ValueError("unindexed-font artifacts require entry arrays")
    if len(entries) != EXPECTED_ENTRY_COUNT or len(translated) != len(entries):
        raise ValueError("unindexed-font population differs")

    source_ids = [entry.get("entry_id") for entry in entries]
    translated_ids = [item.get("id") for item in translated]
    if (
        source_ids != translated_ids
        or any(not isinstance(entry_id, str) for entry_id in source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise ValueError("unindexed-font stable ID order differs")

    translations_by_id: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for entry, item in zip(entries, translated):
        entry_id = str(entry["entry_id"])
        text = item.get("ko")
        if not isinstance(text, str) or not text:
            raise ValueError(f"{entry_id}: Korean translation is empty")
        source = entry.get("source")
        original = entry.get("original")
        layout = entry.get("layout")
        if not all(
            isinstance(value, dict)
            for value in (source, original, layout)
        ):
            raise ValueError(f"{entry_id}: protected source data is missing")
        raw = bytes.fromhex(str(original.get("raw_hex", "")))
        source_size = int(source.get("byte_size", -1))
        source_offset = int(str(source.get("file_offset")), 16)
        if (
            len(raw) != source_size
            or sha256_bytes(raw) != source.get("sha256")
            or source_allbin[source_offset : source_offset + source_size]
            != raw
        ):
            raise ValueError(f"{entry_id}: verified source bytes differ")

        unknown = [
            markup
            for markup in UNKNOWN_MARKUP_PATTERN.findall(text)
            if not NAME_PATTERN.fullmatch(markup)
        ]
        if unknown:
            raise ValueError(
                f"{entry_id}: unknown translation markup {unknown}"
            )
        _leading, _trailing, name_controls = _template(entry)
        source_name_kinds = [kind for kind, _raw in name_controls]
        translated_name_kinds = [
            NAME_KIND_BY_GROUP[match.group(1)]
            for match in NAME_PATTERN.finditer(text)
        ]
        if translated_name_kinds != source_name_kinds:
            raise ValueError(f"{entry_id}: dynamic-name tokens changed")

        rows = int(layout["rows"])
        columns = int(layout["columns"])
        lines = text.split("\n")
        if not 1 <= len(lines) <= rows:
            raise ValueError(f"{entry_id}: row count exceeds layout")
        if any(_visible_length(line) > columns for line in lines):
            raise ValueError(f"{entry_id}: line width exceeds layout")

        classification = str(entry.get("classification", ""))
        counts[classification] += 1
        translations_by_id[entry_id] = item

    if dict(sorted(counts.items())) != EXPECTED_CLASSIFICATION_COUNTS:
        raise ValueError("unindexed-font classification population differs")
    return entries, translations_by_id, {
        "entry_count": len(entries),
        "stable_id_order_exact": True,
        "protected_source_bytes_exact": True,
        "classification_counts": dict(sorted(counts.items())),
        "layout_issue_count": 0,
        "dynamic_name_tokens_exact": True,
    }


def unindexed_translation_texts(
    translations: list[dict[str, Any]],
) -> list[str]:
    texts = [item.get("ko") for item in translations]
    if any(not isinstance(text, str) or not text for text in texts):
        raise ValueError("unindexed-font Korean text is missing")
    return [str(text) for text in texts]


def encode_unindexed_entry(
    entry: dict[str, Any],
    translation: dict[str, Any],
    mapping: dict[str, int],
) -> tuple[bytes, dict[str, Any]]:
    text = translation.get("ko")
    if not isinstance(text, str) or not text:
        raise ValueError(f"{entry['entry_id']}: Korean translation is empty")
    leading, trailing, name_controls = _template(entry)
    layout = entry["layout"]
    rows = int(layout["rows"])
    columns = int(layout["columns"])
    lines = text.split("\n")
    line_widths = [_visible_length(line) for line in lines]
    if not 1 <= len(lines) <= rows:
        raise ValueError(f"{entry['entry_id']}: row count exceeds layout")
    if any(width > columns for width in line_widths):
        raise ValueError(f"{entry['entry_id']}: line width exceeds layout")

    expected_name_kinds = [kind for kind, _raw in name_controls]
    actual_name_kinds = [
        NAME_KIND_BY_GROUP[match.group(1)]
        for match in NAME_PATTERN.finditer(text)
    ]
    if actual_name_kinds != expected_name_kinds:
        raise ValueError(f"{entry['entry_id']}: dynamic-name order differs")
    name_raw = iter(raw for _kind, raw in name_controls)

    body: list[int] = []
    position = 0
    while position < len(text):
        if text[position] == "\n":
            body.append(0xFFFB)
            position += 1
            continue
        name_match = NAME_PATTERN.match(text, position)
        if name_match:
            body.append(next(name_raw))
            position = name_match.end()
            continue
        character = text[position]
        try:
            body.append(mapping[character])
        except KeyError as error:
            raise ValueError(
                f"{entry['entry_id']}: unmapped character {character!r}"
            ) from error
        position += 1

    output_tokens = [*leading, *body, *trailing]
    encoded = struct.pack(f"<{len(output_tokens)}H", *output_tokens)
    source_raw = bytes.fromhex(entry["original"]["raw_hex"])
    leading_raw = struct.pack(f"<{len(leading)}H", *leading)
    trailing_raw = struct.pack(f"<{len(trailing)}H", *trailing)
    if not encoded.startswith(leading_raw) or not encoded.endswith(
        trailing_raw
    ):
        raise AssertionError(f"{entry['entry_id']}: control shell changed")
    return encoded, {
        "entry_id": entry["entry_id"],
        "classification": entry["classification"],
        "source_bytes": len(source_raw),
        "encoded_bytes": len(encoded),
        "line_widths": line_widths,
        "row_count": len(lines),
        "prefix_shell_bytes": len(leading_raw),
        "suffix_shell_bytes": len(trailing_raw),
        "dynamic_name_token_count": len(name_controls),
        "control_shells_byte_exact": True,
    }
