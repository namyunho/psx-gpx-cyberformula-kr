#!/usr/bin/env python3
"""Edit Korean dialogue in a protected 17-column by 3-row GUI.

The editor changes one detected Korean text field only. Stable IDs, Japanese
source text, layout limits, and every other protected value are copied from
the loaded document when saving. Existing output files receive a recoverable
``.bak`` copy before an atomic replacement.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable


COLUMNS = 17
ROWS = 3
CAPACITY = COLUMNS * ROWS
SHORT_LINE_GLYPH_LIMIT = 6
DEFAULT_INPUT = Path(
    "work/translations/disc1-dialogue-ko-candidate.json"
)
DEFAULT_WORKSET = Path("work/translations/disc1-dialogue.json")
DEFAULT_SAFE_SLOTS = Path(
    "work/analysis/disc1-dialogue-safe-slots.json"
)
EDITABLE_FIELD_PATTERN = re.compile(r"^entries\[\]\.([A-Za-z_][A-Za-z0-9_]*)$")
WORD_PATTERN = re.compile(r"\S+")
CONTROL_CONTENT_KINDS = frozenset(
    {"glyph", "name_surname", "name_given"}
)
MOVABLE_INTERNAL_CONTROL_KINDS = frozenset(
    {"align", "name_surname", "name_given"}
)
CONTROL_VISUAL_LABELS = {
    "speaker_style": "화자·초상",
    "style_off": "화자 표시 해제",
    "audio": "음성",
    "voice_transition": "음성 전환",
    "pace": "진행 속도",
    "pause": "일시 정지",
    "delay": "대기",
    "align": "줄바꿈",
    "page_end": "페이지 끝",
    "stream_end": "스트림 끝",
}
NAME_EXPANSIONS = {
    "{name:surname}": "시바",
    "{name:given}": "세이치로",
}
PUNCTUATION_ENDINGS = frozenset("…‥.!?。！？,，:：;；)]}）］】」』’”'")
SAFE_SLOT_BOUNDARY_LABELS = {
    "adjacent-next-entry": "바로 다음 추출 대사 시작",
    "protected-zero-fallthrough-gap": "런타임 통과 0x0000 간격 보호",
    "protected-nonzero-gap": "비영(非零) 무포인터·이벤트 데이터 보호",
    "last-extracted-entry-original-end": "유닛 끝 미분류 영역 보호",
}
UNIT_SHARED_POOL_RUNTIME_VALIDATION = {
    0: {
        "status": "passed",
        "label": "실행 검증 완료",
        "entry_count": 88,
        "original_stream_capacity_bytes": 5624,
        "track1_sha256": (
            "39da4bc7eb8d49944be5ad95f4acd73364d1ca1172f186772ca884c15a024b3f"
        ),
    },
    21: {
        "status": "passed",
        "label": "실행 검증 완료",
        "entry_count": 68,
        "original_stream_capacity_bytes": 4226,
        "track1_sha256": (
            "39da4bc7eb8d49944be5ad95f4acd73364d1ca1172f186772ca884c15a024b3f"
        ),
    },
}


class DialogueEditorError(ValueError):
    """Raised when an input document or requested layout is invalid."""


@dataclass(frozen=True)
class SafeSlotRecord:
    entry_id: str
    unit_index: int
    subsystem: str
    file_offset: str
    unit_offset: str
    safe_end_file_offset: str
    safe_end_unit_offset: str
    original_stream_bytes: int
    safe_slot_bytes: int
    safe_slot_words: int
    additional_zero_gap_bytes: int
    boundary_kind: str
    next_physical_entry_id: str | None
    protected_target: str

    @property
    def boundary_label(self) -> str:
        return SAFE_SLOT_BOUNDARY_LABELS.get(
            self.boundary_kind,
            self.boundary_kind,
        )


@dataclass(frozen=True)
class StorageSlotMeasurement:
    safe_slot: SafeSlotRecord
    estimated_stream_bytes: int

    @property
    def remaining_bytes(self) -> int:
        return max(
            0,
            self.safe_slot.safe_slot_bytes - self.estimated_stream_bytes,
        )

    @property
    def overflow_bytes(self) -> int:
        return max(
            0,
            self.estimated_stream_bytes - self.safe_slot.safe_slot_bytes,
        )

    @property
    def fits(self) -> bool:
        return self.overflow_bytes == 0


@dataclass(frozen=True)
class UnitStorageProfile:
    unit_index: int
    entry_ids: tuple[str, ...]
    original_stream_capacity_bytes: int
    runtime_validation_status: str
    runtime_validation_label: str
    runtime_validation_track1_sha256: str | None

    @property
    def entry_count(self) -> int:
        return len(self.entry_ids)

    @property
    def runtime_verified(self) -> bool:
        return self.runtime_validation_status == "passed"


@dataclass(frozen=True)
class UnitStorageMeasurement:
    profile: UnitStorageProfile
    estimated_stream_bytes: int

    @property
    def remaining_bytes(self) -> int:
        return max(
            0,
            self.profile.original_stream_capacity_bytes
            - self.estimated_stream_bytes,
        )

    @property
    def overflow_bytes(self) -> int:
        return max(
            0,
            self.estimated_stream_bytes
            - self.profile.original_stream_capacity_bytes,
        )

    @property
    def fits(self) -> bool:
        return self.overflow_bytes == 0


@dataclass(frozen=True)
class ProtectedControlToken:
    token_index: int
    raw: str
    kind: str
    markup: str
    policy: str

    @property
    def description(self) -> str:
        return f"0x{self.raw} {self.markup} [{self.policy}]"


@dataclass(frozen=True)
class VisualStreamSegment:
    kind: str
    label: str
    raw: str | None
    display_glyphs: int
    stream_bytes: int

    @property
    def visual_class(self) -> str:
        if self.kind == "glyph":
            return "glyph"
        if self.kind in {"speaker_style", "style_off"}:
            return "speaker"
        if self.kind in {"audio", "voice_transition"}:
            return "audio"
        if self.kind in {"align"}:
            return "layout"
        if self.kind in {"page_end", "stream_end"}:
            return "terminal"
        return "other_control"

    @property
    def chip_text(self) -> str:
        if self.kind == "glyph":
            return self.label
        metric = (
            f"다음 행·{self.stream_bytes}B"
            if self.kind == "align"
            else f"{self.display_glyphs}칸·{self.stream_bytes}B"
        )
        return f"0x{self.raw} {self.label} {metric}"


@dataclass(frozen=True)
class DialogueControlContext:
    entry_id: str
    original_stream_bytes: int
    leading: tuple[ProtectedControlToken, ...]
    internal_movable: tuple[ProtectedControlToken, ...]
    trailing: tuple[ProtectedControlToken, ...]

    def inline_markup(self, dialogue_text: str) -> str:
        leading = "".join(token.markup for token in self.leading)
        body = dialogue_text.replace("\n", "{align}")
        trailing = "".join(token.markup for token in self.trailing)
        return f"{leading}{body}{trailing}"

    def visual_segments(
        self,
        dialogue_text: str,
    ) -> tuple[VisualStreamSegment, ...]:
        segments: list[VisualStreamSegment] = []

        def add_control(token: ProtectedControlToken) -> None:
            segments.append(
                VisualStreamSegment(
                    kind=token.kind,
                    label=CONTROL_VISUAL_LABELS.get(
                        token.kind,
                        token.kind,
                    ),
                    raw=token.raw,
                    display_glyphs=0,
                    stream_bytes=2,
                )
            )

        for token in self.leading:
            add_control(token)
        for line_index, line in enumerate(dialogue_text.split("\n")):
            if line_index:
                segments.append(
                    VisualStreamSegment(
                        kind="align",
                        label=CONTROL_VISUAL_LABELS["align"],
                        raw="FFFB",
                        display_glyphs=0,
                        stream_bytes=2,
                    )
                )
            expanded_line = expand_display_tokens(line)
            if expanded_line:
                segments.append(
                    VisualStreamSegment(
                        kind="glyph",
                        label=expanded_line,
                        raw=None,
                        display_glyphs=len(expanded_line),
                        stream_bytes=len(expanded_line) * 2,
                    )
                )
        for token in self.trailing:
            add_control(token)
        return tuple(segments)

    def compact_visual_summary(self, dialogue_text: str) -> str:
        leading = ",".join(token.raw for token in self.leading) or "없음"
        trailing = ",".join(token.raw for token in self.trailing) or "없음"
        align_count = dialogue_text.count("\n")
        return (
            f"선두 제어(0글리프) {leading}"
            f" · 줄바꿈 FFFB ×{align_count}"
            f" · 후미 제어(0글리프) {trailing}"
        )

    def estimated_stream_bytes(self, dialogue_text: str) -> int:
        align_count = dialogue_text.count("\n")
        visible_glyphs = len(
            expand_display_tokens(dialogue_text).replace("\n", "")
        )
        return 2 * (
            len(self.leading)
            + visible_glyphs
            + align_count
            + len(self.trailing)
        )

    def read_only_report(
        self,
        dialogue_text: str,
        safe_slot: SafeSlotRecord | None = None,
    ) -> str:
        leading = (
            " · ".join(token.description for token in self.leading)
            or "없음"
        )
        trailing = (
            " · ".join(token.description for token in self.trailing)
            or "없음"
        )
        align_count = dialogue_text.count("\n")
        estimated_bytes = self.estimated_stream_bytes(dialogue_text)
        if safe_slot is None:
            byte_report = (
                f"바이트: 원본 스트림 {self.original_stream_bytes}B"
                f" · 현재 예상 {estimated_bytes}B"
                " · 검증 안전 슬롯 자료 없음"
            )
            boundary_report = "슬롯 경계: 자료 없음"
        else:
            delta = safe_slot.safe_slot_bytes - estimated_bytes
            if delta > 0:
                state = f"{delta}B 미사용"
            elif delta == 0:
                state = "정확히 일치"
            else:
                state = f"{-delta}B 초과"
            byte_report = (
                f"바이트: 원본 스트림 {self.original_stream_bytes}B"
                f" · 검증 안전 슬롯 {safe_slot.safe_slot_bytes}B"
                f" · 현재 예상 {estimated_bytes}B · {state}"
            )
            boundary_report = (
                f"슬롯 경계: ALLBIN {safe_slot.file_offset}"
                f"–{safe_slot.safe_end_file_offset}"
                f" / unit {safe_slot.unit_offset}"
                f"–{safe_slot.safe_end_unit_offset}"
                f" · {safe_slot.boundary_label}"
            )
        return (
            f"{byte_report}\n"
            f"{boundary_report}\n"
            f"선두 보호: {leading}\n"
            f"조판: 줄바꿈 {align_count}개"
            " → 0xFFFB {align} [movable-layout-in-story-only]\n"
            f"후미 보호: {trailing}\n"
            f"인라인 스트림: {self.inline_markup(dialogue_text)}"
        )


@dataclass(frozen=True)
class LayoutMeasurement:
    source_text: str
    display_text: str
    lines: tuple[str, ...]
    line_widths: tuple[int, ...]
    visible_glyph_count: int
    occupied_positions: int
    columns: int = COLUMNS
    rows: int = ROWS

    @property
    def row_overflow(self) -> bool:
        return len(self.lines) > self.rows

    @property
    def column_overflow_rows(self) -> tuple[int, ...]:
        return tuple(
            index + 1
            for index, width in enumerate(self.line_widths)
            if width > self.columns
        )

    @property
    def glyph_capacity_overflow(self) -> bool:
        return self.visible_glyph_count > self.columns * self.rows

    @property
    def limit_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.glyph_capacity_overflow:
            reasons.append("total")
        if self.column_overflow_rows:
            reasons.append("line")
        if self.row_overflow:
            reasons.append("rows")
        return tuple(reasons)

    @property
    def short_line_rows(self) -> tuple[int, ...]:
        if len(self.lines) < 2:
            return ()
        return tuple(
            index + 1
            for index, width in enumerate(self.line_widths)
            if 0 < width < SHORT_LINE_GLYPH_LIMIT
        )

    @property
    def exceeds_limits(self) -> bool:
        return bool(self.limit_reasons)

    @property
    def fits(self) -> bool:
        return not self.exceeds_limits


def expand_display_tokens(text: str) -> str:
    """Expand only confirmed fixed-name placeholders for screen measurement."""
    expanded = text
    for token, replacement in NAME_EXPANSIONS.items():
        expanded = expanded.replace(token, replacement)
    return expanded


def measure_layout(
    text: str,
    *,
    columns: int = COLUMNS,
    rows: int = ROWS,
) -> LayoutMeasurement:
    """Measure explicit editor rows in the verified fixed-cell renderer."""
    if not isinstance(text, str):
        raise DialogueEditorError("dialogue text must be a string")
    display = expand_display_tokens(text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = tuple(display.split("\n"))
    widths = tuple(len(line) for line in lines)
    occupied = (
        (len(lines) - 1) * columns + widths[-1]
        if lines
        else 0
    )
    return LayoutMeasurement(
        source_text=text,
        display_text=display,
        lines=lines,
        line_widths=widths,
        visible_glyph_count=sum(widths),
        occupied_positions=occupied,
        columns=columns,
        rows=rows,
    )


def _word_boundary_layouts(
    text: str,
    *,
    columns: int,
    rows: int,
) -> list[tuple[str, ...]]:
    words = WORD_PATTERN.findall(text)
    if not words:
        return [("",)]
    layouts: list[tuple[str, ...]] = []

    def visit(word_index: int, lines: list[str]) -> None:
        if word_index == len(words):
            layouts.append(tuple(lines))
            return
        if len(lines) >= rows:
            return

        line = ""
        for end in range(word_index, len(words)):
            candidate = words[end] if not line else f"{line} {words[end]}"
            if len(expand_display_tokens(candidate)) > columns:
                break
            line = candidate
            visit(end + 1, [*lines, line])

    visit(0, [])
    return layouts


def _layout_sort_key(
    lines: tuple[str, ...],
    *,
    columns: int,
) -> tuple[Any, ...]:
    widths = tuple(len(expand_display_tokens(line)) for line in lines)
    average = sum(widths) / len(widths)
    half_row = (columns + 1) // 2
    shortfall = sum(max(0, half_row - width) for width in widths)
    raggedness = max(widths) - min(widths)
    variance = sum((width - average) ** 2 for width in widths)
    punctuation_breaks = sum(
        bool(line) and line[-1] in PUNCTUATION_ENDINGS
        for line in lines[:-1]
    )
    return (
        shortfall,
        raggedness,
        variance,
        -punctuation_breaks,
        tuple(-width for width in widths),
        lines,
    )


def conservative_word_wrap(
    text: str,
    *,
    columns: int = COLUMNS,
    rows: int = ROWS,
) -> str:
    """Return a balanced word-boundary layout without changing word content.

    Existing newlines are treated as soft whitespace. The result minimizes
    row count first, then avoids rows shorter than half the frame and reduces
    raggedness. It never splits a word; an entry that needs the separately
    approved word-split fallback remains a manual-review error.
    """
    if not isinstance(text, str):
        raise DialogueEditorError("dialogue text must be a string")
    layouts = _word_boundary_layouts(text, columns=columns, rows=rows)
    if not layouts:
        raise DialogueEditorError(
            f"띄어쓰기 경계만으로 {columns}×{rows}에 배치할 수 없습니다."
        )
    minimum_rows = min(len(layout) for layout in layouts)
    eligible = [
        layout for layout in layouts if len(layout) == minimum_rows
    ]
    return "\n".join(
        min(
            eligible,
            key=lambda layout: _layout_sort_key(
                layout,
                columns=columns,
            ),
        )
    )


def _entry_id(entry: dict[str, Any], index: int) -> str:
    value = entry.get("id", entry.get("entry_id"))
    if not isinstance(value, str) or not value:
        raise DialogueEditorError(
            f"entries[{index}]: non-empty id or entry_id is required"
        )
    return value


def _detect_editable_field(
    document: dict[str, Any],
    entries: list[dict[str, Any]],
    override: str | None,
) -> str:
    if override:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", override):
            raise DialogueEditorError(
                f"invalid editable field name: {override!r}"
            )
        return override

    rules = document.get("rules")
    if isinstance(rules, dict):
        declared = rules.get("editable_field")
        if isinstance(declared, str):
            match = EDITABLE_FIELD_PATTERN.fullmatch(declared)
            if match:
                return match.group(1)

    for candidate in ("ko", "ko_reflowed", "ko_candidate"):
        if any(candidate in entry for entry in entries):
            return candidate
    raise DialogueEditorError(
        "cannot detect an editable Korean field; use --editable-field"
    )


def _protected_entry(
    entry: dict[str, Any],
    editable_field: str,
) -> dict[str, Any]:
    protected = copy.deepcopy(entry)
    protected.pop(editable_field, None)
    return protected


def load_control_contexts(
    path: Path,
    *,
    required_ids: Iterable[str] | None = None,
) -> dict[str, DialogueControlContext]:
    """Load and validate the protected control shell for dialogue entries."""
    try:
        workset = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DialogueEditorError(f"{path}: {error}") from error
    entries = workset.get("entries") if isinstance(workset, dict) else None
    if not isinstance(entries, list):
        raise DialogueEditorError(f"{path}: workset requires an entries list")

    contexts: dict[str, DialogueControlContext] = {}
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise DialogueEditorError(
                f"{path}: entries[{entry_index}] must be an object"
            )
        entry_id = _entry_id(entry, entry_index)
        if entry_id in contexts:
            raise DialogueEditorError(
                f"{path}: duplicate workset ID {entry_id}"
            )
        original = entry.get("original")
        if not isinstance(original, dict):
            raise DialogueEditorError(
                f"{entry_id}: missing protected original data"
            )
        raw_tokens = original.get("tokens")
        raw_controls = original.get("control_tokens")
        if not isinstance(raw_tokens, list) or not isinstance(
            raw_controls, list
        ):
            raise DialogueEditorError(
                f"{entry_id}: missing token/control arrays"
            )
        try:
            tokens = tuple(int(str(raw), 16) for raw in raw_tokens)
        except ValueError as error:
            raise DialogueEditorError(
                f"{entry_id}: invalid raw token"
            ) from error

        controls: dict[int, ProtectedControlToken] = {}
        for raw_control in raw_controls:
            if not isinstance(raw_control, dict):
                raise DialogueEditorError(
                    f"{entry_id}: control token must be an object"
                )
            token_index = raw_control.get("token_index")
            raw = raw_control.get("raw")
            kind = raw_control.get("kind")
            markup = raw_control.get("markup")
            policy = raw_control.get("policy")
            if (
                not isinstance(token_index, int)
                or not 0 <= token_index < len(tokens)
                or not isinstance(raw, str)
                or not re.fullmatch(r"[0-9A-Fa-f]{4}", raw)
                or not isinstance(kind, str)
                or not kind
                or not isinstance(markup, str)
                or not markup
                or not isinstance(policy, str)
                or not policy
            ):
                raise DialogueEditorError(
                    f"{entry_id}: invalid control token metadata"
                )
            if token_index in controls:
                raise DialogueEditorError(
                    f"{entry_id}: duplicate control index {token_index}"
                )
            if tokens[token_index] != int(raw, 16):
                raise DialogueEditorError(
                    f"{entry_id}: control raw value differs at "
                    f"token {token_index}"
                )
            controls[token_index] = ProtectedControlToken(
                token_index=token_index,
                raw=raw.upper(),
                kind=kind,
                markup=markup,
                policy=policy,
            )

        content_indices = [
            index
            for index in range(len(tokens))
            if (
                controls[index].kind
                if index in controls
                else "glyph"
            )
            in CONTROL_CONTENT_KINDS
        ]
        if not content_indices:
            raise DialogueEditorError(
                f"{entry_id}: source stream has no display content"
            )
        first_content = min(content_indices)
        last_content = max(content_indices)
        leading = tuple(
            control
            for index, control in sorted(controls.items())
            if index < first_content
        )
        internal = tuple(
            control
            for index, control in sorted(controls.items())
            if first_content <= index <= last_content
        )
        trailing = tuple(
            control
            for index, control in sorted(controls.items())
            if index > last_content
        )
        unsupported_internal = [
            control
            for control in internal
            if control.kind not in MOVABLE_INTERNAL_CONTROL_KINDS
        ]
        if unsupported_internal:
            kinds = ", ".join(
                control.kind for control in unsupported_internal
            )
            raise DialogueEditorError(
                f"{entry_id}: protected internal control cannot move: {kinds}"
            )
        if any(index not in controls for index in range(first_content)):
            raise DialogueEditorError(
                f"{entry_id}: leading control shell contains a glyph"
            )
        if any(
            index not in controls
            for index in range(last_content + 1, len(tokens))
        ):
            raise DialogueEditorError(
                f"{entry_id}: trailing control shell contains a glyph"
            )
        contexts[entry_id] = DialogueControlContext(
            entry_id=entry_id,
            original_stream_bytes=len(tokens) * 2,
            leading=leading,
            internal_movable=internal,
            trailing=trailing,
        )

    if required_ids is not None:
        required = tuple(required_ids)
        missing = [
            entry_id
            for entry_id in required
            if entry_id not in contexts
        ]
        if missing:
            raise DialogueEditorError(
                f"{path}: workset is missing {len(missing)} editor IDs; "
                f"first={missing[0]}"
            )
        return {entry_id: contexts[entry_id] for entry_id in required}
    return contexts


def load_safe_slot_records(
    path: Path,
    *,
    required_ids: Iterable[str] | None = None,
    workset_path: Path | None = None,
) -> dict[str, SafeSlotRecord]:
    """Load and validate fixed-original physical write budgets."""
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DialogueEditorError(f"{path}: {error}") from error
    if not isinstance(catalog, dict):
        raise DialogueEditorError(f"{path}: safe-slot catalog must be an object")
    if catalog.get("schema_version") != 1 or catalog.get("catalog_kind") != (
        "disc1-fixed-original-dialogue-safe-slots"
    ):
        raise DialogueEditorError(f"{path}: unsupported safe-slot catalog")
    if catalog.get("status") != (
        "verified-physical-boundaries-runtime-qa-required"
    ):
        raise DialogueEditorError(f"{path}: safe-slot catalog is not verified")

    source = catalog.get("source")
    if not isinstance(source, dict):
        raise DialogueEditorError(f"{path}: safe-slot source is missing")
    if workset_path is not None:
        try:
            actual_workset_hash = hashlib.sha256(
                workset_path.read_bytes()
            ).hexdigest()
        except OSError as error:
            raise DialogueEditorError(f"{workset_path}: {error}") from error
        if source.get("workset_sha256") != actual_workset_hash:
            raise DialogueEditorError(
                f"{path}: safe-slot catalog was generated from a different "
                "protected workset"
            )

    raw_entries = catalog.get("entries")
    if not isinstance(raw_entries, list):
        raise DialogueEditorError(f"{path}: safe-slot entries are missing")
    records: dict[str, SafeSlotRecord] = {}
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise DialogueEditorError(
                f"{path}: entries[{index}] must be an object"
            )
        try:
            entry_id = raw["id"]
            unit_index = raw["unit_index"]
            subsystem = raw["subsystem"]
            file_offset = raw["file_offset"]
            unit_offset = raw["unit_offset"]
            safe_end_file_offset = raw["safe_end_file_offset"]
            safe_end_unit_offset = raw["safe_end_unit_offset"]
            original_stream_bytes = raw["original_stream_bytes"]
            safe_slot_bytes = raw["safe_slot_bytes"]
            safe_slot_words = raw["safe_slot_words"]
            additional_zero_gap_bytes = raw["additional_zero_gap_bytes"]
            boundary_kind = raw["boundary_kind"]
            next_physical_entry_id = raw["next_physical_entry_id"]
            protected_target = raw["protected_target"]
        except KeyError as error:
            raise DialogueEditorError(
                f"{path}: entries[{index}] is missing {error.args[0]}"
            ) from error
        hex_fields = (
            file_offset,
            unit_offset,
            safe_end_file_offset,
            safe_end_unit_offset,
        )
        if (
            not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(unit_index, int)
            or not isinstance(subsystem, str)
            or not subsystem
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"0x[0-9A-Fa-f]+", value)
                for value in hex_fields
            )
            or not isinstance(original_stream_bytes, int)
            or original_stream_bytes <= 0
            or original_stream_bytes % 2
            or not isinstance(safe_slot_bytes, int)
            or safe_slot_bytes < original_stream_bytes
            or safe_slot_bytes % 2
            or not isinstance(safe_slot_words, int)
            or safe_slot_words * 2 != safe_slot_bytes
            or not isinstance(additional_zero_gap_bytes, int)
            or additional_zero_gap_bytes != (
                safe_slot_bytes - original_stream_bytes
            )
            or boundary_kind not in SAFE_SLOT_BOUNDARY_LABELS
            or (
                next_physical_entry_id is not None
                and not isinstance(next_physical_entry_id, str)
            )
            or not isinstance(protected_target, str)
            or not protected_target
        ):
            raise DialogueEditorError(
                f"{path}: entries[{index}] has invalid safe-slot metadata"
            )
        if (
            int(safe_end_file_offset, 16) - int(file_offset, 16)
            != safe_slot_bytes
            or int(safe_end_unit_offset, 16) - int(unit_offset, 16)
            != safe_slot_bytes
        ):
            raise DialogueEditorError(
                f"{entry_id}: safe-slot coordinates differ from byte size"
            )
        if entry_id in records:
            raise DialogueEditorError(
                f"{path}: duplicate safe-slot ID {entry_id}"
            )
        records[entry_id] = SafeSlotRecord(
            entry_id=entry_id,
            unit_index=unit_index,
            subsystem=subsystem,
            file_offset=file_offset,
            unit_offset=unit_offset,
            safe_end_file_offset=safe_end_file_offset,
            safe_end_unit_offset=safe_end_unit_offset,
            original_stream_bytes=original_stream_bytes,
            safe_slot_bytes=safe_slot_bytes,
            safe_slot_words=safe_slot_words,
            additional_zero_gap_bytes=additional_zero_gap_bytes,
            boundary_kind=boundary_kind,
            next_physical_entry_id=next_physical_entry_id,
            protected_target=protected_target,
        )

    if required_ids is not None:
        required = tuple(required_ids)
        missing = [entry_id for entry_id in required if entry_id not in records]
        if missing:
            raise DialogueEditorError(
                f"{path}: safe-slot catalog is missing {len(missing)} editor "
                f"IDs; first={missing[0]}"
            )
        return {entry_id: records[entry_id] for entry_id in required}
    return records


def build_unit_storage_profiles(
    safe_slots: dict[str, SafeSlotRecord],
) -> dict[int, UnitStorageProfile]:
    """Derive immutable unit dialogue capacities from the protected catalog."""
    entries_by_unit: dict[int, list[SafeSlotRecord]] = {}
    for record in safe_slots.values():
        entries_by_unit.setdefault(record.unit_index, []).append(record)

    profiles: dict[int, UnitStorageProfile] = {}
    for unit_index, records in sorted(entries_by_unit.items()):
        ordered = sorted(
            records,
            key=lambda record: int(record.unit_offset, 16),
        )
        capacity = sum(
            record.original_stream_bytes for record in ordered
        )
        candidate_validation = UNIT_SHARED_POOL_RUNTIME_VALIDATION.get(
            unit_index,
            {},
        )
        validation = (
            candidate_validation
            if (
                candidate_validation.get("entry_count") == len(ordered)
                and candidate_validation.get(
                    "original_stream_capacity_bytes"
                )
                == capacity
            )
            else {}
        )
        profiles[unit_index] = UnitStorageProfile(
            unit_index=unit_index,
            entry_ids=tuple(record.entry_id for record in ordered),
            original_stream_capacity_bytes=capacity,
            runtime_validation_status=str(
                validation.get("status", "not-verified")
            ),
            runtime_validation_label=str(
                validation.get("label", "공용 재배치 미검증")
            ),
            runtime_validation_track1_sha256=(
                str(validation["track1_sha256"])
                if "track1_sha256" in validation
                else None
            ),
        )
    return profiles


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        parsed = json.loads(temporary.read_text(encoding="utf-8"))
        if parsed != value:
            raise DialogueEditorError(
                f"{path}: atomic JSON verification differs"
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class DialogueDocument:
    """Protected in-memory view of one supported dialogue JSON document."""

    def __init__(
        self,
        path: Path,
        document: dict[str, Any],
        *,
        editable_field: str | None = None,
        control_contexts: dict[str, DialogueControlContext] | None = None,
        safe_slots: dict[str, SafeSlotRecord] | None = None,
        unit_storage_profiles: dict[int, UnitStorageProfile] | None = None,
    ) -> None:
        if not isinstance(document, dict):
            raise DialogueEditorError("dialogue JSON root must be an object")
        raw_entries = document.get("entries")
        if not isinstance(raw_entries, list):
            raise DialogueEditorError("dialogue JSON requires an entries list")
        if not raw_entries:
            raise DialogueEditorError("dialogue JSON entries list is empty")
        if not all(isinstance(entry, dict) for entry in raw_entries):
            raise DialogueEditorError("every dialogue entry must be an object")

        entries = list(raw_entries)
        field = _detect_editable_field(document, entries, editable_field)
        ids = [_entry_id(entry, index) for index, entry in enumerate(entries)]
        id_counts = Counter(ids)
        duplicates = sorted(
            entry_id
            for entry_id, count in id_counts.items()
            if count > 1
        )
        if duplicates:
            raise DialogueEditorError(
                "duplicate dialogue IDs: " + ", ".join(duplicates[:10])
            )

        declared_count = document.get("entry_count")
        if declared_count is not None and declared_count != len(entries):
            raise DialogueEditorError(
                f"entry_count={declared_count} but entries={len(entries)}"
            )

        values: list[str] = []
        for index, entry in enumerate(entries):
            value = entry.get(field, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise DialogueEditorError(
                    f"{ids[index]}: {field} must be a string or null"
                )
            values.append(value)

        self.path = path
        self.document = copy.deepcopy(document)
        self.editable_field = field
        self.ids = ids
        self._index_by_id = {
            entry_id: index for index, entry_id in enumerate(ids)
        }
        self._saved_values = list(values)
        self._values = list(values)
        self._control_contexts = dict(control_contexts or {})
        self._safe_slots = dict(safe_slots or {})
        self._unit_storage_profiles = dict(
            unit_storage_profiles
            if unit_storage_profiles is not None
            else build_unit_storage_profiles(self._safe_slots)
        )
        unknown_context_ids = sorted(set(self._control_contexts) - set(ids))
        if unknown_context_ids:
            raise DialogueEditorError(
                "control context contains unknown editor IDs: "
                + ", ".join(unknown_context_ids[:10])
            )
        unknown_safe_slot_ids = sorted(set(self._safe_slots) - set(ids))
        if unknown_safe_slot_ids:
            raise DialogueEditorError(
                "safe-slot catalog contains unknown editor IDs: "
                + ", ".join(unknown_safe_slot_ids[:10])
            )
        for entry_id in set(self._control_contexts) & set(self._safe_slots):
            context = self._control_contexts[entry_id]
            safe_slot = self._safe_slots[entry_id]
            if context.original_stream_bytes != (
                safe_slot.original_stream_bytes
            ):
                raise DialogueEditorError(
                    f"{entry_id}: control stream and safe-slot original "
                    "byte sizes differ"
                )

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        editable_field: str | None = None,
        workset_path: Path | None = None,
        safe_slots_path: Path | None = None,
    ) -> "DialogueDocument":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DialogueEditorError(f"{path}: {error}") from error
        raw_entries = (
            document.get("entries")
            if isinstance(document, dict)
            else None
        )
        required_ids = (
            [_entry_id(entry, index) for index, entry in enumerate(raw_entries)]
            if isinstance(raw_entries, list)
            and all(isinstance(entry, dict) for entry in raw_entries)
            else None
        )
        contexts = (
            load_control_contexts(
                workset_path,
                required_ids=required_ids,
            )
            if workset_path is not None and required_ids is not None
            else None
        )
        all_safe_slots = (
            load_safe_slot_records(
                safe_slots_path,
                workset_path=workset_path,
            )
            if safe_slots_path is not None and required_ids is not None
            else None
        )
        if all_safe_slots is None or required_ids is None:
            safe_slots = None
            unit_storage_profiles = None
        else:
            missing = [
                entry_id
                for entry_id in required_ids
                if entry_id not in all_safe_slots
            ]
            if missing:
                raise DialogueEditorError(
                    f"{safe_slots_path}: safe-slot catalog is missing "
                    f"{len(missing)} editor IDs; first={missing[0]}"
                )
            safe_slots = {
                entry_id: all_safe_slots[entry_id]
                for entry_id in required_ids
            }
            unit_storage_profiles = build_unit_storage_profiles(
                all_safe_slots
            )
        return cls(
            path,
            document,
            editable_field=editable_field,
            control_contexts=contexts,
            safe_slots=safe_slots,
            unit_storage_profiles=unit_storage_profiles,
        )

    def __len__(self) -> int:
        return len(self.ids)

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self.document["entries"]

    @property
    def dirty_indices(self) -> tuple[int, ...]:
        return tuple(
            index
            for index, (saved, current) in enumerate(
                zip(self._saved_values, self._values)
            )
            if saved != current
        )

    @property
    def dirty(self) -> bool:
        return bool(self.dirty_indices)

    def value(self, index: int) -> str:
        return self._values[index]

    def saved_value(self, index: int) -> str:
        return self._saved_values[index]

    def set_value(self, index: int, value: str) -> None:
        if not isinstance(value, str):
            raise DialogueEditorError("edited dialogue must be a string")
        self._values[index] = value.replace("\r\n", "\n").replace("\r", "\n")

    def control_context(
        self,
        index: int,
    ) -> DialogueControlContext | None:
        return self._control_contexts.get(self.ids[index])

    def control_report(self, index: int) -> str:
        context = self.control_context(index)
        if context is None:
            return "보호 workset이 연결되지 않아 제어코드를 표시할 수 없습니다."
        return context.read_only_report(
            self.value(index),
            self.safe_slot(index),
        )

    def safe_slot(self, index: int) -> SafeSlotRecord | None:
        return self._safe_slots.get(self.ids[index])

    def estimated_stream_bytes(self, index: int) -> int | None:
        context = self.control_context(index)
        if context is None:
            return None
        return context.estimated_stream_bytes(self.value(index))

    def storage_slot_measurement(
        self,
        index: int,
    ) -> StorageSlotMeasurement | None:
        safe_slot = self.safe_slot(index)
        estimated = self.estimated_stream_bytes(index)
        if safe_slot is None or estimated is None:
            return None
        return StorageSlotMeasurement(
            safe_slot=safe_slot,
            estimated_stream_bytes=estimated,
        )

    def unit_index(self, index: int) -> int | None:
        safe_slot = self.safe_slot(index)
        if safe_slot is not None:
            return safe_slot.unit_index
        entry = self.entries[index]
        value = entry.get("unit_index")
        if isinstance(value, int):
            return value
        source = entry.get("source")
        if isinstance(source, dict):
            value = source.get("unit_index")
            if isinstance(value, int):
                return value
        return None

    def unit_storage_measurements(
        self,
    ) -> dict[int, UnitStorageMeasurement]:
        measurements: dict[int, UnitStorageMeasurement] = {}
        for unit_index, profile in self._unit_storage_profiles.items():
            if any(
                entry_id not in self._index_by_id
                or entry_id not in self._control_contexts
                for entry_id in profile.entry_ids
            ):
                continue
            estimated = sum(
                self._control_contexts[entry_id].estimated_stream_bytes(
                    self._values[self._index_by_id[entry_id]]
                )
                for entry_id in profile.entry_ids
            )
            measurements[unit_index] = UnitStorageMeasurement(
                profile=profile,
                estimated_stream_bytes=estimated,
            )
        return measurements

    def unit_storage_measurement(
        self,
        index: int,
    ) -> UnitStorageMeasurement | None:
        unit_index = self.unit_index(index)
        if unit_index is None:
            return None
        return self.unit_storage_measurements().get(unit_index)

    def japanese(self, index: int) -> str:
        entry = self.entries[index]
        value = entry.get("jp")
        if isinstance(value, str):
            return value
        original = entry.get("original")
        if isinstance(original, dict):
            japanese = original.get("japanese")
            if isinstance(japanese, dict):
                display = japanese.get("display_text", japanese.get("text"))
                if isinstance(display, str):
                    return display
        return ""

    def maximum_glyphs(self, index: int) -> int | None:
        value = self.entries[index].get("max_glyphs")
        return value if isinstance(value, int) and value > 0 else None

    def metadata(self, index: int) -> dict[str, str]:
        entry = self.entries[index]
        unit = self.unit_index(index)
        status = entry.get(
            "reinsertion_status",
            entry.get("status", ""),
        )
        classification = entry.get("classification", "")
        return {
            "unit": "" if unit is None else str(unit),
            "status": "" if status is None else str(status),
            "classification": (
                "" if classification is None else str(classification)
            ),
        }

    def searchable_text(self, index: int) -> str:
        context = self.control_context(index)
        control_text = (
            context.inline_markup(self.value(index))
            if context is not None
            else ""
        )
        return "\n".join(
            (
                self.ids[index],
                self.japanese(index),
                self.value(index),
                control_text,
            )
        ).casefold()

    def layout_overflow_indices(self) -> tuple[int, ...]:
        return tuple(
            index
            for index, value in enumerate(self._values)
            if measure_layout(value).exceeds_limits
        )

    def short_line_candidate_indices(self) -> tuple[int, ...]:
        return tuple(
            index
            for index, value in enumerate(self._values)
            if measure_layout(value).short_line_rows
        )

    def storage_slot_overflow_indices(self) -> tuple[int, ...]:
        return tuple(
            index
            for index in range(len(self))
            if (
                (measurement := self.storage_slot_measurement(index))
                is not None
                and not measurement.fits
            )
        )

    def unit_storage_overflow_indices(self) -> tuple[int, ...]:
        overflow_units = {
            unit_index
            for unit_index, measurement in (
                self.unit_storage_measurements().items()
            )
            if not measurement.fits
        }
        return tuple(
            index
            for index in range(len(self))
            if self.unit_index(index) in overflow_units
        )

    def output_document(self) -> dict[str, Any]:
        output = copy.deepcopy(self.document)
        output_entries = output["entries"]
        for index, value in enumerate(self._values):
            output_entries[index][self.editable_field] = value

        source_entries = self.document["entries"]
        if len(output_entries) != len(source_entries):
            raise DialogueEditorError("entry count changed while saving")
        for index, (source, target) in enumerate(
            zip(source_entries, output_entries)
        ):
            if _protected_entry(source, self.editable_field) != (
                _protected_entry(target, self.editable_field)
            ):
                raise DialogueEditorError(
                    f"{self.ids[index]}: protected fields changed"
                )
        return output

    def save(self, path: Path | None = None) -> Path | None:
        target = self.path if path is None else path
        dirty_row_overflows = [
            index
            for index in self.dirty_indices
            if measure_layout(self._values[index]).row_overflow
        ]
        if dirty_row_overflows:
            first = dirty_row_overflows[0]
            raise DialogueEditorError(
                "3줄을 넘는 수정 대사는 저장할 수 없습니다: "
                f"{self.ids[first]} "
                f"({len(measure_layout(self._values[first]).lines)}줄)"
            )
        output = self.output_document()
        backup: Path | None = None
        if target.exists():
            backup = target.with_name(f"{target.name}.bak")
            shutil.copy2(target, backup)
        _write_json_atomic(target, output)

        verified = json.loads(target.read_text(encoding="utf-8"))
        if verified != output:
            raise DialogueEditorError(
                f"{target}: saved JSON verification differs"
            )
        self.path = target
        self.document = output
        self._saved_values = list(self._values)
        return backup

    def validation_summary(self) -> dict[str, Any]:
        fits = 0
        overflow = 0
        short_line_candidates = 0
        glyph_capacity_overflow = 0
        line_width_overflow = 0
        row_count_overflow = 0
        storage_slot_measurable = 0
        storage_slot_exact = 0
        storage_slot_under_capacity = 0
        storage_slot_overflow = 0
        maximum_storage_overflow_bytes = 0
        empty = 0
        for index, value in enumerate(self._values):
            measurement = measure_layout(value)
            storage = self.storage_slot_measurement(index)
            if not value.strip():
                empty += 1
            if measurement.glyph_capacity_overflow:
                glyph_capacity_overflow += 1
            if measurement.column_overflow_rows:
                line_width_overflow += 1
            if measurement.row_overflow:
                row_count_overflow += 1
            if measurement.short_line_rows:
                short_line_candidates += 1
            if measurement.fits:
                fits += 1
            else:
                overflow += 1
            if storage is not None:
                storage_slot_measurable += 1
                if storage.estimated_stream_bytes == (
                    storage.safe_slot.safe_slot_bytes
                ):
                    storage_slot_exact += 1
                elif storage.fits:
                    storage_slot_under_capacity += 1
                else:
                    storage_slot_overflow += 1
                    maximum_storage_overflow_bytes = max(
                        maximum_storage_overflow_bytes,
                        storage.overflow_bytes,
                    )
        unit_measurements = self.unit_storage_measurements()
        unit_storage_overflow = [
            measurement
            for measurement in unit_measurements.values()
            if not measurement.fits
        ]
        return {
            "path": str(self.path),
            "editable_field": self.editable_field,
            "entries": len(self),
            "fits_17x3": fits,
            "layout_overflow": overflow,
            "glyph_capacity_overflow": glyph_capacity_overflow,
            "line_width_overflow": line_width_overflow,
            "row_count_overflow": row_count_overflow,
            "short_line_candidates": short_line_candidates,
            "control_context_entries": len(self._control_contexts),
            "safe_slot_entries": len(self._safe_slots),
            "storage_slot_measurable": storage_slot_measurable,
            "storage_slot_exact": storage_slot_exact,
            "storage_slot_under_capacity": storage_slot_under_capacity,
            "storage_slot_overflow": storage_slot_overflow,
            "maximum_storage_overflow_bytes": (
                maximum_storage_overflow_bytes
            ),
            "unit_storage_measurable": len(unit_measurements),
            "unit_storage_fits": (
                len(unit_measurements) - len(unit_storage_overflow)
            ),
            "unit_storage_overflow": len(unit_storage_overflow),
            "maximum_unit_storage_overflow_bytes": max(
                (
                    measurement.overflow_bytes
                    for measurement in unit_storage_overflow
                ),
                default=0,
            ),
            "runtime_verified_unit_shared_pool_units": sorted(
                measurement.profile.unit_index
                for measurement in unit_measurements.values()
                if measurement.profile.runtime_verified
            ),
            "leading_control_tokens": sum(
                len(context.leading)
                for context in self._control_contexts.values()
            ),
            "movable_internal_control_tokens": sum(
                len(context.internal_movable)
                for context in self._control_contexts.values()
            ),
            "trailing_control_tokens": sum(
                len(context.trailing)
                for context in self._control_contexts.values()
            ),
            "empty": empty,
            "dirty": len(self.dirty_indices),
        }


def filter_entry_indices(
    document: DialogueDocument,
    *,
    query: str = "",
    overflow_only: bool = False,
    storage_overflow_only: bool = False,
    unit_storage_overflow_only: bool = False,
    short_line_only: bool = False,
) -> list[int]:
    """Return stable document indices matching search and layout filters."""
    normalized_query = query.strip().casefold()
    overflow_indices = (
        set(document.layout_overflow_indices())
        if overflow_only
        else None
    )
    storage_overflow_indices = (
        set(document.storage_slot_overflow_indices())
        if storage_overflow_only
        else None
    )
    unit_storage_overflow_indices = (
        set(document.unit_storage_overflow_indices())
        if unit_storage_overflow_only
        else None
    )
    short_line_indices = (
        set(document.short_line_candidate_indices())
        if short_line_only
        else None
    )
    return [
        index
        for index in range(len(document))
        if (overflow_indices is None or index in overflow_indices)
        and (
            storage_overflow_indices is None
            or index in storage_overflow_indices
        )
        and (
            unit_storage_overflow_indices is None
            or index in unit_storage_overflow_indices
        )
        and (short_line_indices is None or index in short_line_indices)
        and (
            not normalized_query
            or normalized_query in document.searchable_text(index)
        )
    ]


def _short_entry_label(document: DialogueDocument, index: int) -> str:
    entry_id = document.ids[index]
    match = re.search(r"/u(\d+)/[^/]+/(ref\d+)$", entry_id)
    if match:
        return f"{index + 1:04d}  u{int(match.group(1)):02d}  {match.group(2)}"
    return f"{index + 1:04d}  {entry_id[-42:]}"


def run_gui(
    document: DialogueDocument,
    *,
    save_target: Path | None = None,
    initial_entry_id: str | None = None,
) -> None:
    """Run the Tk application. Kept separate so tests stay headless."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter import font as tkfont

    class DialogueLayoutEditor:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.document = document
            self.save_target = save_target
            self.current_index: int | None = None
            self.filtered_indices = list(range(len(document)))
            self.overflow_indices = set(document.layout_overflow_indices())
            self.storage_overflow_indices = set(
                document.storage_slot_overflow_indices()
            )
            self.unit_storage_overflow_indices = set(
                document.unit_storage_overflow_indices()
            )
            self.short_line_indices = set(
                document.short_line_candidate_indices()
            )
            self._loading_editor = False

            root.title("PSX 대사 17×3 편집기")
            root.geometry("1180x760")
            root.minsize(980, 660)
            root.protocol("WM_DELETE_WINDOW", self.close)

            self.search_var = tk.StringVar()
            self.overflow_only_var = tk.BooleanVar(value=False)
            self.storage_overflow_only_var = tk.BooleanVar(value=False)
            self.unit_storage_overflow_only_var = tk.BooleanVar(value=False)
            self.short_line_only_var = tk.BooleanVar(value=False)
            self.filter_summary_var = tk.StringVar()
            self.id_var = tk.StringVar()
            self.meta_var = tk.StringVar()
            self.counter_var = tk.StringVar()
            self.preview_control_var = tk.StringVar()
            self.file_var = tk.StringVar()
            self.message_var = tk.StringVar()

            self._build_widgets()
            self._bind_shortcuts()
            self.refresh_filter()

            target_index = 0
            if initial_entry_id is not None:
                try:
                    target_index = document.ids.index(initial_entry_id)
                except ValueError as error:
                    raise DialogueEditorError(
                        f"unknown initial entry ID: {initial_entry_id}"
                    ) from error
            self.select_document_index(target_index)
            self.update_title()

        def _build_widgets(self) -> None:
            outer = ttk.Frame(self.root, padding=10)
            outer.pack(fill=tk.BOTH, expand=True)

            top = ttk.Frame(outer)
            top.pack(fill=tk.X, pady=(0, 8))
            ttk.Label(top, text="파일:").pack(side=tk.LEFT)
            ttk.Label(
                top,
                textvariable=self.file_var,
                anchor=tk.W,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 8))
            ttk.Button(top, text="저장", command=self.save).pack(side=tk.LEFT)
            ttk.Button(
                top,
                text="다른 이름으로 저장",
                command=self.save_as,
            ).pack(side=tk.LEFT, padx=(6, 0))

            pane = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
            pane.pack(fill=tk.BOTH, expand=True)

            left = ttk.Frame(pane, padding=(0, 0, 8, 0))
            right = ttk.Frame(pane)
            pane.add(left, weight=1)
            pane.add(right, weight=3)

            search = ttk.Frame(left)
            search.pack(fill=tk.X, pady=(0, 6))
            ttk.Label(search, text="검색").pack(side=tk.LEFT)
            self.search_entry = ttk.Entry(
                search,
                textvariable=self.search_var,
            )
            self.search_entry.pack(
                side=tk.LEFT,
                fill=tk.X,
                expand=True,
                padx=(6, 0),
            )
            self.search_var.trace_add(
                "write",
                lambda *_: self.refresh_filter(),
            )

            filter_bar = ttk.Frame(left)
            filter_bar.pack(fill=tk.X, pady=(0, 6))
            ttk.Checkbutton(
                filter_bar,
                text="한도 초과만",
                variable=self.overflow_only_var,
                command=self.refresh_filter,
            ).pack(side=tk.LEFT)
            ttk.Checkbutton(
                filter_bar,
                text="6자 미만 행만",
                variable=self.short_line_only_var,
                command=self.refresh_filter,
            ).pack(side=tk.LEFT, padx=(6, 0))
            storage_filter_bar = ttk.Frame(left)
            storage_filter_bar.pack(fill=tk.X, pady=(0, 6))
            ttk.Checkbutton(
                storage_filter_bar,
                text="안전 슬롯 초과만",
                variable=self.storage_overflow_only_var,
                command=self.refresh_filter,
            ).pack(side=tk.LEFT)
            ttk.Checkbutton(
                storage_filter_bar,
                text="유닛 총량 초과만",
                variable=self.unit_storage_overflow_only_var,
                command=self.refresh_filter,
            ).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Button(
                storage_filter_bar,
                text="목록 갱신",
                command=self.refresh_filter,
            ).pack(side=tk.RIGHT)
            ttk.Label(
                left,
                textvariable=self.filter_summary_var,
            ).pack(anchor=tk.W, pady=(0, 6))

            nav = ttk.Frame(left)
            nav.pack(fill=tk.X, pady=(0, 6))
            ttk.Button(nav, text="◀ 이전", command=self.previous).pack(
                side=tk.LEFT,
                fill=tk.X,
                expand=True,
            )
            ttk.Button(nav, text="다음 ▶", command=self.next).pack(
                side=tk.LEFT,
                fill=tk.X,
                expand=True,
                padx=(6, 0),
            )

            list_frame = ttk.Frame(left)
            list_frame.pack(fill=tk.BOTH, expand=True)
            self.entry_list = tk.Listbox(
                list_frame,
                exportselection=False,
                activestyle="none",
                font=("Menlo", 12),
            )
            list_scroll = ttk.Scrollbar(
                list_frame,
                orient=tk.VERTICAL,
                command=self.entry_list.yview,
            )
            self.entry_list.configure(yscrollcommand=list_scroll.set)
            self.entry_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            self.entry_list.bind("<<ListboxSelect>>", self.on_list_select)

            metadata = ttk.LabelFrame(right, text="보호 정보", padding=8)
            metadata.pack(fill=tk.X)
            ttk.Label(
                metadata,
                textvariable=self.id_var,
                font=("TkDefaultFont", 12, "bold"),
            ).pack(anchor=tk.W)
            ttk.Label(metadata, textvariable=self.meta_var).pack(anchor=tk.W)

            control_frame = ttk.LabelFrame(
                right,
                text="실제 이벤트 스트림 제어 — 읽기 전용",
                padding=6,
            )
            control_frame.pack(fill=tk.X, pady=(8, 0))
            self.control_text = tk.Text(
                control_frame,
                height=7,
                wrap=tk.WORD,
                state=tk.DISABLED,
                font=("Menlo", 11),
                padx=5,
                pady=5,
            )
            self.control_text.tag_configure(
                "stream_speaker",
                background="#7045a0",
                foreground="#ffffff",
            )
            self.control_text.tag_configure(
                "stream_audio",
                background="#246a93",
                foreground="#ffffff",
            )
            self.control_text.tag_configure(
                "stream_layout",
                background="#a85d00",
                foreground="#ffffff",
            )
            self.control_text.tag_configure(
                "stream_terminal",
                background="#8d3b4b",
                foreground="#ffffff",
            )
            self.control_text.tag_configure(
                "stream_other_control",
                background="#555b66",
                foreground="#ffffff",
            )
            self.control_text.tag_configure(
                "stream_glyph",
                background="#e8eef6",
                foreground="#17253a",
            )
            self.control_text.tag_configure(
                "stream_heading",
                foreground="#3e4d63",
                font=("Menlo", 10, "bold"),
            )
            self.control_text.pack(fill=tk.X)
            self.slot_canvas = tk.Canvas(
                control_frame,
                height=24,
                background="#d8dee8",
                highlightthickness=0,
            )
            self.slot_canvas.pack(fill=tk.X, pady=(5, 0))
            self.slot_canvas.bind(
                "<Configure>",
                lambda _event: self.update_slot_meter(
                    self.current_index
                ),
            )
            self.unit_canvas = tk.Canvas(
                control_frame,
                height=24,
                background="#d8dee8",
                highlightthickness=0,
            )
            self.unit_canvas.pack(fill=tk.X, pady=(4, 0))
            self.unit_canvas.bind(
                "<Configure>",
                lambda _event: self.update_unit_meter(
                    self.current_index
                ),
            )

            text_pane = ttk.Panedwindow(right, orient=tk.VERTICAL)
            text_pane.pack(fill=tk.BOTH, expand=True, pady=(8, 8))

            jp_frame = ttk.LabelFrame(
                text_pane,
                text="일본어 원문 — 읽기 전용",
                padding=6,
            )
            ko_frame = ttk.LabelFrame(
                text_pane,
                text=f"한국어 편집 — {document.editable_field}",
                padding=6,
            )
            text_pane.add(jp_frame, weight=1)
            text_pane.add(ko_frame, weight=1)

            self.jp_text = tk.Text(
                jp_frame,
                height=4,
                wrap=tk.WORD,
                state=tk.DISABLED,
                font=("Apple SD Gothic Neo", 15),
            )
            self.jp_text.pack(fill=tk.BOTH, expand=True)

            self.ko_text = tk.Text(
                ko_frame,
                height=5,
                wrap=tk.NONE,
                undo=True,
                maxundo=-1,
                font=("Apple SD Gothic Neo", 16),
            )
            self.ko_text.pack(fill=tk.BOTH, expand=True)
            self.ko_text.bind("<<Modified>>", self.on_editor_modified)

            action = ttk.Frame(right)
            action.pack(fill=tk.X, pady=(0, 8))
            ttk.Button(
                action,
                text="보수적 자동 배치",
                command=self.apply_conservative_wrap,
            ).pack(side=tk.LEFT)
            ttk.Button(
                action,
                text="저장본으로 되돌리기",
                command=self.restore_saved,
            ).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Label(
                action,
                text="자동 배치는 띄어쓰기 경계만 사용하며 단어를 쪼개지 않습니다.",
            ).pack(side=tk.RIGHT)

            preview = ttk.LabelFrame(
                right,
                text="17×3 고정 셀 미리보기 — 자형은 참고용",
                padding=8,
            )
            preview.pack(fill=tk.X)
            ttk.Label(
                preview,
                textvariable=self.preview_control_var,
            ).pack(anchor=tk.W, pady=(0, 3))
            ttk.Label(
                preview,
                textvariable=self.counter_var,
            ).pack(anchor=tk.W, pady=(0, 5))
            self.cell_size = 30
            self.canvas_margin = 28
            self.canvas_marker_width = 64
            self.preview_canvas = tk.Canvas(
                preview,
                width=(
                    self.canvas_margin
                    + COLUMNS * self.cell_size
                    + self.canvas_marker_width
                    + 2
                ),
                height=ROWS * self.cell_size + 2,
                background="#163b71",
                highlightthickness=0,
            )
            self.preview_canvas.pack(anchor=tk.W)
            ttk.Label(
                preview,
                text=(
                    "주황 셀은 FFFB 줄바꿈이 건너뛴 위치이며, "
                    "제어토큰 자체는 글리프 셀을 차지하지 않습니다."
                ),
            ).pack(anchor=tk.W, pady=(4, 0))
            available_fonts = set(tkfont.families())
            self.preview_font = next(
                (
                    family
                    for family in (
                        "Galmuri11",
                        "Apple SD Gothic Neo",
                        "Arial Unicode MS",
                    )
                    if family in available_fonts
                ),
                "TkFixedFont",
            )

            ttk.Label(
                outer,
                textvariable=self.message_var,
                relief=tk.SUNKEN,
                anchor=tk.W,
                padding=(6, 3),
            ).pack(fill=tk.X, pady=(8, 0))

        def _bind_shortcuts(self) -> None:
            for sequence in ("<Command-s>", "<Control-s>"):
                self.root.bind(sequence, lambda _event: self.save())
            for sequence in ("<Command-Shift-S>", "<Control-Shift-S>"):
                self.root.bind(sequence, lambda _event: self.save_as())
            for sequence in ("<Command-f>", "<Control-f>"):
                self.root.bind(sequence, self.focus_search)
            self.root.bind("<Alt-Left>", lambda _event: self.previous())
            self.root.bind("<Alt-Right>", lambda _event: self.next())

        def focus_search(self, _event: object = None) -> str:
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, tk.END)
            return "break"

        def current_text(self) -> str:
            return self.ko_text.get("1.0", "end-1c")

        def commit_current(self) -> None:
            if self.current_index is not None and not self._loading_editor:
                self.document.set_value(
                    self.current_index,
                    self.current_text(),
                )

        def refresh_filter(self) -> None:
            self.commit_current()
            self.overflow_indices = set(
                self.document.layout_overflow_indices()
            )
            self.storage_overflow_indices = set(
                self.document.storage_slot_overflow_indices()
            )
            self.unit_storage_overflow_indices = set(
                self.document.unit_storage_overflow_indices()
            )
            self.short_line_indices = set(
                self.document.short_line_candidate_indices()
            )
            self.filtered_indices = filter_entry_indices(
                self.document,
                query=self.search_var.get(),
                overflow_only=self.overflow_only_var.get(),
                storage_overflow_only=(
                    self.storage_overflow_only_var.get()
                ),
                unit_storage_overflow_only=(
                    self.unit_storage_overflow_only_var.get()
                ),
                short_line_only=self.short_line_only_var.get(),
            )
            self.update_filter_summary()

            current = self.current_index
            self.entry_list.delete(0, tk.END)
            dirty_indices = set(self.document.dirty_indices)
            for index in self.filtered_indices:
                marker = "*" if index in dirty_indices else " "
                overflow_marker = (
                    "!" if index in self.overflow_indices else " "
                )
                storage_marker = (
                    "B"
                    if index in self.storage_overflow_indices
                    else " "
                )
                unit_storage_marker = (
                    "U"
                    if index in self.unit_storage_overflow_indices
                    else " "
                )
                short_line_marker = (
                    "~" if index in self.short_line_indices else " "
                )
                self.entry_list.insert(
                    tk.END,
                    f"{marker}{overflow_marker}{storage_marker}"
                    f"{unit_storage_marker}"
                    f"{short_line_marker} "
                    f"{_short_entry_label(self.document, index)}",
                )
            if current in self.filtered_indices:
                self._select_list_position(
                    self.filtered_indices.index(current)
                )
            elif self.filtered_indices:
                self.select_document_index(self.filtered_indices[0])
            else:
                self.message_var.set("검색 결과가 없습니다.")
            self.update_title()

        def update_filter_summary(self) -> None:
            self.filter_summary_var.set(
                f"목록 {len(self.filtered_indices)}건"
                f" / 한도 초과 {len(self.overflow_indices)}건"
                f" / 슬롯 초과 {len(self.storage_overflow_indices)}건"
                f" / 유닛 초과 {len(self.unit_storage_overflow_indices)}건"
                f" / 짧은 행 {len(self.short_line_indices)}건"
            )

        def _select_list_position(self, position: int) -> None:
            self.entry_list.selection_clear(0, tk.END)
            self.entry_list.selection_set(position)
            self.entry_list.activate(position)
            self.entry_list.see(position)

        def select_document_index(self, index: int) -> None:
            if not 0 <= index < len(self.document):
                return
            self.commit_current()
            self.current_index = index
            if index in self.filtered_indices:
                self._select_list_position(
                    self.filtered_indices.index(index)
                )

            self._loading_editor = True
            try:
                self.id_var.set(self.document.ids[index])
                self.update_metadata(index)
                self.jp_text.configure(state=tk.NORMAL)
                self.jp_text.delete("1.0", tk.END)
                self.jp_text.insert("1.0", self.document.japanese(index))
                self.jp_text.configure(state=tk.DISABLED)
                self.ko_text.delete("1.0", tk.END)
                self.ko_text.insert("1.0", self.document.value(index))
                self.ko_text.edit_modified(False)
            finally:
                self._loading_editor = False
            self.update_control_view(index)
            self.update_preview()
            self.message_var.set("한국어 필드만 편집할 수 있습니다.")
            self.update_title()

        def update_control_view(self, index: int) -> None:
            widget = self.control_text
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            context = self.document.control_context(index)
            if context is None:
                widget.insert(
                    "1.0",
                    "보호 workset이 연결되지 않아 제어코드를 "
                    "표시할 수 없습니다.",
                )
                widget.configure(state=tk.DISABLED)
                self.update_slot_meter(index)
                self.update_unit_meter(index)
                return

            report_lines = context.read_only_report(
                self.document.value(index),
                self.document.safe_slot(index),
            ).splitlines()
            widget.insert(tk.END, report_lines[0] + "\n")
            widget.insert(
                tk.END,
                " / ".join(report_lines[1:5]) + "\n",
            )
            widget.insert(
                tk.END,
                "색상: ",
                "stream_heading",
            )
            legend = (
                ("화자·초상", "stream_speaker"),
                ("음성", "stream_audio"),
                ("줄바꿈", "stream_layout"),
                ("종료", "stream_terminal"),
                ("기타 제어", "stream_other_control"),
                ("표시 글리프", "stream_glyph"),
            )
            for label, tag in legend:
                widget.insert(tk.END, f" {label} ", tag)
                widget.insert(tk.END, " ")
            widget.insert(tk.END, "\n")
            widget.insert(tk.END, "실제 스트림: ", "stream_heading")
            for segment in context.visual_segments(
                self.document.value(index)
            ):
                tag = f"stream_{segment.visual_class}"
                widget.insert(tk.END, f" {segment.chip_text} ", tag)
                widget.insert(tk.END, " ")
            widget.configure(state=tk.DISABLED)
            self.update_slot_meter(index)
            self.update_unit_meter(index)

        def update_slot_meter(self, index: int | None) -> None:
            canvas = self.slot_canvas
            canvas.delete("all")
            width = max(100, canvas.winfo_width())
            height = max(20, canvas.winfo_height())
            measurement = (
                self.document.storage_slot_measurement(index)
                if index is not None
                else None
            )
            if measurement is None:
                canvas.create_text(
                    width // 2,
                    height // 2,
                    text="검증 안전 슬롯 자료 또는 제어 셸 없음",
                    fill="#3e4d63",
                )
                return

            safe_bytes = measurement.safe_slot.safe_slot_bytes
            current_bytes = measurement.estimated_stream_bytes
            scale_bytes = max(safe_bytes, current_bytes, 1)
            used_end = int(width * min(current_bytes, safe_bytes) / scale_bytes)
            safe_end = int(width * safe_bytes / scale_bytes)
            canvas.create_rectangle(
                0,
                0,
                width,
                height,
                fill="#d8dee8",
                outline="",
            )
            if used_end:
                canvas.create_rectangle(
                    0,
                    0,
                    used_end,
                    height,
                    fill="#3f7f6b",
                    outline="",
                )
            if measurement.overflow_bytes:
                canvas.create_rectangle(
                    safe_end,
                    0,
                    width,
                    height,
                    fill="#d88928",
                    outline="",
                )
                state = (
                    f"{measurement.overflow_bytes}B 초과 · 공용 재배치 필요"
                )
            elif measurement.remaining_bytes:
                state = f"{measurement.remaining_bytes}B 미사용"
            else:
                state = "정확히 일치"
            canvas.create_line(
                safe_end,
                0,
                safe_end,
                height,
                fill="#17253a",
                width=2,
            )
            canvas.create_text(
                width // 2,
                height // 2,
                text=(
                    f"현재 {current_bytes}B / 검증 안전 슬롯 "
                    f"{safe_bytes}B — {state}"
                ),
                fill="#101923",
                font=("TkDefaultFont", 10, "bold"),
            )

        def update_unit_meter(self, index: int | None) -> None:
            canvas = self.unit_canvas
            canvas.delete("all")
            width = max(100, canvas.winfo_width())
            height = max(20, canvas.winfo_height())
            measurement = (
                self.document.unit_storage_measurement(index)
                if index is not None
                else None
            )
            if measurement is None:
                canvas.create_text(
                    width // 2,
                    height // 2,
                    text="완전한 유닛 대사·제어 자료가 없어 공용 총량 계산 불가",
                    fill="#3e4d63",
                )
                return

            capacity = measurement.profile.original_stream_capacity_bytes
            current = measurement.estimated_stream_bytes
            scale_bytes = max(capacity, current, 1)
            used_end = int(width * min(current, capacity) / scale_bytes)
            capacity_end = int(width * capacity / scale_bytes)
            canvas.create_rectangle(
                0,
                0,
                width,
                height,
                fill="#d8dee8",
                outline="",
            )
            if used_end:
                canvas.create_rectangle(
                    0,
                    0,
                    used_end,
                    height,
                    fill="#3f7f6b",
                    outline="",
                )
            if measurement.overflow_bytes:
                canvas.create_rectangle(
                    capacity_end,
                    0,
                    width,
                    height,
                    fill="#c74747",
                    outline="",
                )
                state = f"{measurement.overflow_bytes}B 초과 · 빌드 차단"
            elif measurement.remaining_bytes:
                state = f"{measurement.remaining_bytes}B 공용 여유"
            else:
                state = "정확히 일치"
            canvas.create_line(
                capacity_end,
                0,
                capacity_end,
                height,
                fill="#17253a",
                width=2,
            )
            profile = measurement.profile
            canvas.create_text(
                width // 2,
                height // 2,
                text=(
                    f"u{profile.unit_index:02d} 공용 {current}B / "
                    f"{capacity}B — {state} · "
                    f"{profile.runtime_validation_label}"
                ),
                fill="#101923",
                font=("TkDefaultFont", 10, "bold"),
            )

        def update_metadata(self, index: int) -> None:
            metadata = self.document.metadata(index)
            limit = self.document.maximum_glyphs(index)
            measurement = measure_layout(self.document.value(index))
            reason_labels: list[str] = []
            if measurement.glyph_capacity_overflow:
                reason_labels.append(
                    f"총 {measurement.visible_glyph_count}/{CAPACITY}"
                )
            if measurement.column_overflow_rows:
                rows = ",".join(
                    str(row)
                    for row in measurement.column_overflow_rows
                )
                reason_labels.append(f"17자 초과 행={rows}")
            if measurement.row_overflow:
                reason_labels.append(
                    f"행 {len(measurement.lines)}/{ROWS}"
                )
            limit_state = (
                ", ".join(reason_labels) if reason_labels else "적합"
            )
            storage = self.document.storage_slot_measurement(index)
            storage_state = "자료 없음"
            if storage is not None:
                storage_state = (
                    f"{storage.estimated_stream_bytes}/"
                    f"{storage.safe_slot.safe_slot_bytes}B "
                    + (
                        (
                            f"({storage.remaining_bytes}B 미사용)"
                            if storage.remaining_bytes
                            else "(정확히 일치)"
                        )
                        if storage.fits
                        else f"({storage.overflow_bytes}B 초과)"
                    )
                )
            unit_storage = self.document.unit_storage_measurement(index)
            unit_storage_state = "자료 없음"
            if unit_storage is not None:
                profile = unit_storage.profile
                unit_storage_state = (
                    f"u{profile.unit_index:02d} "
                    f"{unit_storage.estimated_stream_bytes}/"
                    f"{profile.original_stream_capacity_bytes}B "
                    + (
                        (
                            f"({unit_storage.remaining_bytes}B 여유)"
                            if unit_storage.remaining_bytes
                            else "(정확히 일치)"
                        )
                        if unit_storage.fits
                        else (
                            f"({unit_storage.overflow_bytes}B 초과·빌드 차단)"
                        )
                    )
                    + f" [{profile.runtime_validation_label}]"
                )
            self.meta_var.set(
                f"{index + 1}/{len(self.document)}  "
                f"unit={metadata['unit'] or '?'}  "
                f"class={metadata['classification'] or '?'}  "
                f"status={metadata['status'] or '?'}  "
                f"max_glyphs={limit if limit is not None else '미확정'}  "
                f"layout={limit_state}  "
                f"slot={storage_state}  "
                f"unit_pool={unit_storage_state}"
            )

        def on_list_select(self, _event: object) -> None:
            selection = self.entry_list.curselection()
            if not selection:
                return
            position = int(selection[0])
            if 0 <= position < len(self.filtered_indices):
                index = self.filtered_indices[position]
                if index != self.current_index:
                    self.select_document_index(index)

        def on_editor_modified(self, _event: object) -> None:
            if self._loading_editor:
                self.ko_text.edit_modified(False)
                return
            if not self.ko_text.edit_modified():
                return
            self.commit_current()
            self.ko_text.edit_modified(False)
            self.update_preview()
            self.update_current_filter_state()
            self.update_title()

        def update_current_filter_state(self) -> None:
            if self.current_index is None:
                return
            measurement = measure_layout(
                self.document.value(self.current_index)
            )
            if measurement.exceeds_limits:
                self.overflow_indices.add(self.current_index)
            else:
                self.overflow_indices.discard(self.current_index)
            storage = self.document.storage_slot_measurement(
                self.current_index
            )
            if storage is not None and not storage.fits:
                self.storage_overflow_indices.add(self.current_index)
            else:
                self.storage_overflow_indices.discard(self.current_index)
            self.unit_storage_overflow_indices = set(
                self.document.unit_storage_overflow_indices()
            )
            if measurement.short_line_rows:
                self.short_line_indices.add(self.current_index)
            else:
                self.short_line_indices.discard(self.current_index)
            self.update_metadata(self.current_index)
            self.update_control_view(self.current_index)
            if self.current_index in self.filtered_indices:
                position = self.filtered_indices.index(self.current_index)
                marker = (
                    "*"
                    if self.current_index in self.document.dirty_indices
                    else " "
                )
                overflow_marker = (
                    "!"
                    if self.current_index in self.overflow_indices
                    else " "
                )
                storage_marker = (
                    "B"
                    if self.current_index in self.storage_overflow_indices
                    else " "
                )
                unit_storage_marker = (
                    "U"
                    if self.current_index
                    in self.unit_storage_overflow_indices
                    else " "
                )
                short_line_marker = (
                    "~"
                    if self.current_index in self.short_line_indices
                    else " "
                )
                self.entry_list.delete(position)
                self.entry_list.insert(
                    position,
                    f"{marker}{overflow_marker}{storage_marker}"
                    f"{unit_storage_marker}"
                    f"{short_line_marker} "
                    f"{_short_entry_label(self.document, self.current_index)}",
                )
                self._select_list_position(position)
            self.update_filter_summary()

        def update_title(self) -> None:
            target = self.save_target or self.document.path
            dirty = "*" if self.document.dirty else ""
            self.root.title(f"{dirty}PSX 대사 17×3 편집기 — {target.name}")
            self.file_var.set(
                f"{target}  |  수정 {len(self.document.dirty_indices)}건"
            )

        def update_preview(self) -> None:
            measurement = measure_layout(self.current_text())
            context = (
                self.document.control_context(self.current_index)
                if self.current_index is not None
                else None
            )
            self.preview_control_var.set(
                context.compact_visual_summary(self.current_text())
                if context is not None
                else "보호 제어코드 정보 없음"
            )
            width_parts = [
                f"{index + 1}행 {width}/{COLUMNS}"
                for index, width in enumerate(measurement.line_widths)
            ]
            reason_parts: list[str] = []
            if measurement.glyph_capacity_overflow:
                reason_parts.append("총 글리프")
            if measurement.column_overflow_rows:
                rows = ",".join(
                    str(row) for row in measurement.column_overflow_rows
                )
                reason_parts.append(f"{rows}행 폭")
            if measurement.row_overflow:
                reason_parts.append("행 수")
            short_line_note = ""
            if measurement.short_line_rows:
                rows = ",".join(
                    str(row) for row in measurement.short_line_rows
                )
                short_line_note = f"  |  6자 미만: {rows}행"
            state = (
                "적합"
                if not reason_parts
                else "초과: " + ", ".join(reason_parts)
            )
            self.counter_var.set(
                " · ".join(width_parts)
                + f"  |  표시 {measurement.visible_glyph_count}/{CAPACITY}"
                + f"  |  {state}"
                + short_line_note
            )

            canvas = self.preview_canvas
            canvas.delete("all")
            normal_grid = "#4e75a7"
            overflow_grid = "#f05b63"
            align_grid = "#a85d00"
            align_fill = "#4c3b22"
            normal_fill = "#163b71"
            grid_end = self.canvas_margin + COLUMNS * self.cell_size
            for row in range(ROWS):
                canvas.create_text(
                    self.canvas_margin // 2,
                    row * self.cell_size + self.cell_size // 2,
                    text=str(row + 1),
                    fill="#a9c4e8",
                    font=("TkDefaultFont", 10),
                )
                line = (
                    measurement.lines[row]
                    if row < len(measurement.lines)
                    else ""
                )
                row_overflow = len(line) > COLUMNS
                explicit_align = row < len(measurement.lines) - 1
                for column in range(COLUMNS):
                    left = self.canvas_margin + column * self.cell_size
                    top = row * self.cell_size
                    skipped_by_align = (
                        explicit_align and column >= len(line)
                    )
                    if row_overflow:
                        cell_outline = overflow_grid
                        cell_width = 2
                    elif skipped_by_align:
                        cell_outline = align_grid
                        cell_width = 2
                    else:
                        cell_outline = normal_grid
                        cell_width = 1
                    canvas.create_rectangle(
                        left,
                        top,
                        left + self.cell_size,
                        top + self.cell_size,
                        outline=cell_outline,
                        fill=(
                            align_fill
                            if skipped_by_align
                            else normal_fill
                        ),
                        width=cell_width,
                    )
                    if column < len(line):
                        canvas.create_text(
                            left + self.cell_size // 2,
                            top + self.cell_size // 2,
                            text=line[column],
                            fill="#ffffff",
                            font=(self.preview_font, 15),
                        )
                if explicit_align:
                    canvas.create_text(
                        grid_end + 7,
                        row * self.cell_size + self.cell_size // 2,
                        text="↵ FFFB",
                        anchor=tk.W,
                        fill="#ffb34d",
                        font=("Menlo", 9, "bold"),
                    )
            if measurement.row_overflow:
                canvas.create_rectangle(
                    self.canvas_margin,
                    0,
                    self.canvas_margin + COLUMNS * self.cell_size,
                    ROWS * self.cell_size,
                    outline=overflow_grid,
                    width=3,
                )

        def apply_conservative_wrap(self) -> None:
            before = self.current_text()
            try:
                after = conservative_word_wrap(before)
            except DialogueEditorError as error:
                messagebox.showwarning("자동 배치 불가", str(error))
                return
            if after == before:
                self.message_var.set("현재 줄바꿈이 이미 선택 결과와 같습니다.")
                return
            before_widths = measure_layout(before).line_widths
            after_widths = measure_layout(after).line_widths
            if not messagebox.askyesno(
                "보수적 자동 배치",
                "띄어쓰기 경계만 사용해 줄바꿈을 바꿉니다.\n\n"
                f"변경 전: {list(before_widths)}\n"
                f"변경 후: {list(after_widths)}\n\n"
                "대사 내용과 단어 순서는 바뀌지 않습니다. 적용할까요?",
            ):
                return
            self._loading_editor = True
            try:
                self.ko_text.delete("1.0", tk.END)
                self.ko_text.insert("1.0", after)
                self.ko_text.edit_modified(False)
            finally:
                self._loading_editor = False
            self.commit_current()
            self.update_preview()
            self.update_current_filter_state()
            self.update_title()
            self.message_var.set("자동 배치를 적용했습니다. 저장 전 검토하세요.")

        def restore_saved(self) -> None:
            if self.current_index is None:
                return
            saved = self.document.saved_value(self.current_index)
            if self.current_text() == saved:
                return
            if not messagebox.askyesno(
                "저장본 복원",
                "현재 엔트리의 편집 내용을 마지막 저장 상태로 되돌릴까요?",
            ):
                return
            self._loading_editor = True
            try:
                self.ko_text.delete("1.0", tk.END)
                self.ko_text.insert("1.0", saved)
                self.ko_text.edit_modified(False)
            finally:
                self._loading_editor = False
            self.commit_current()
            self.update_preview()
            self.update_current_filter_state()
            self.update_title()

        def previous(self) -> None:
            if not self.filtered_indices:
                return
            current = (
                self.filtered_indices.index(self.current_index)
                if self.current_index in self.filtered_indices
                else 0
            )
            self.select_document_index(
                self.filtered_indices[max(0, current - 1)]
            )

        def next(self) -> None:
            if not self.filtered_indices:
                return
            current = (
                self.filtered_indices.index(self.current_index)
                if self.current_index in self.filtered_indices
                else 0
            )
            self.select_document_index(
                self.filtered_indices[
                    min(len(self.filtered_indices) - 1, current + 1)
                ]
            )

        def save(self) -> str:
            self.commit_current()
            target = self.save_target or self.document.path
            modified = len(self.document.dirty_indices)
            try:
                backup = self.document.save(target)
            except (OSError, DialogueEditorError) as error:
                messagebox.showerror("저장 실패", str(error))
                return "break"
            self.save_target = target
            self.update_title()
            backup_text = f"\n백업: {backup}" if backup else ""
            messagebox.showinfo(
                "저장 완료",
                f"{target}\n수정 엔트리: {modified}건{backup_text}",
            )
            self.message_var.set(f"저장 완료: {target}")
            return "break"

        def save_as(self) -> str:
            self.commit_current()
            initial = self.save_target or self.document.path
            selected = filedialog.asksaveasfilename(
                title="편집한 대사 JSON 저장",
                initialdir=str(initial.parent),
                initialfile=initial.name,
                defaultextension=".json",
                filetypes=(("JSON", "*.json"), ("모든 파일", "*")),
            )
            if not selected:
                return "break"
            self.save_target = Path(selected)
            return self.save()

        def close(self) -> None:
            self.commit_current()
            if self.document.dirty:
                decision = messagebox.askyesnocancel(
                    "저장하지 않은 변경",
                    f"수정된 엔트리 {len(self.document.dirty_indices)}건을 "
                    "저장하고 종료할까요?",
                )
                if decision is None:
                    return
                if decision:
                    self.save()
                    if self.document.dirty:
                        return
            self.root.destroy()

    root = tk.Tk()
    DialogueLayoutEditor(root)
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="dialogue JSON to edit",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional default save target; input is used when omitted",
    )
    parser.add_argument(
        "--workset",
        type=Path,
        default=DEFAULT_WORKSET,
        help=(
            "protected extracted workset supplying read-only control tokens"
        ),
    )
    parser.add_argument(
        "--safe-slots",
        type=Path,
        default=DEFAULT_SAFE_SLOTS,
        help=(
            "verified fixed-original safe-slot catalog generated from ALLBIN"
        ),
    )
    parser.add_argument(
        "--editable-field",
        help="override detected Korean field, e.g. ko or ko_reflowed",
    )
    parser.add_argument(
        "--entry-id",
        help="stable ID to select on launch",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and summarize the JSON without opening a GUI",
    )
    args = parser.parse_args()

    try:
        document = DialogueDocument.load(
            args.input,
            editable_field=args.editable_field,
            workset_path=args.workset,
            safe_slots_path=args.safe_slots,
        )
        if args.check:
            print(
                json.dumps(
                    document.validation_summary(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        run_gui(
            document,
            save_target=args.output,
            initial_entry_id=args.entry_id,
        )
    except DialogueEditorError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
