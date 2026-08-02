#!/usr/bin/env python3
"""Edit every confirmed font-rendered Korean string in a protected GUI.

The default workspace combines story dialogue, pointerless pages, mini-games,
course and machine-setting text, UI literals, and character names. Baked
graphical text is deliberately excluded. Each edit is written back to its
own canonical translation artifact; stable IDs, Japanese source text, layout
limits, and every other protected value stay read-only. Existing output files
receive a recoverable ``.bak`` copy before an atomic replacement.
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
FULL_GLYPH_ADVANCE_PX = 14
HALFWIDTH_GLYPH_ADVANCE_PX = 8
HALFWIDTH_CHARACTERS = frozenset({" ", "!", "(", ")", ",", ".", "?"})
DEFAULT_INPUT = Path(
    "work/translations/disc1-dialogue-ko-candidate.json"
)
DEFAULT_WORKSET = Path("work/translations/disc1-dialogue.json")
DEFAULT_SAFE_SLOTS = Path(
    "work/analysis/disc1-dialogue-safe-slots.json"
)
DEFAULT_POINTERLESS_TRANSLATION = Path(
    "data/translations/disc1-pointerless-pages-u00-u21-ko.json"
)
DEFAULT_POINTERLESS_WORKSET = Path(
    "work/translations/disc1-pointerless-pages-u00-u21.json"
)
DEFAULT_SPECIAL_TRANSLATION = Path(
    "data/translations/disc1-special-screen-ko.json"
)
DEFAULT_SPECIAL_WORKSET = Path(
    "work/translations/disc1-special-screen-text.json"
)
DEFAULT_UNINDEXED_TRANSLATION = Path(
    "data/translations/disc1-unindexed-font-ko.json"
)
DEFAULT_UNINDEXED_WORKSET = Path(
    "work/translations/disc1-unindexed-font-text.json"
)
DEFAULT_UI_TRANSLATION = Path("data/translations/disc1-ui-ko.json")
DEFAULT_UI_WORKSET = Path("work/translations/disc1-ui.json")
DEFAULT_CHARACTER_NAMES = Path(
    "data/translations/disc1-character-names.json"
)
WORKSPACE_DISPLAY_PATH = Path("통합-폰트-번역-작업공간")
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
    "original-stream-size-reference": (
        "원본 스트림 크기 기준(공용 재배치·확장 미검증)"
    ),
}
SOURCE_GROUP_LABELS = {
    "story_dialogue": "본편 대사",
    "pointerless_page": "무포인터 선택·대사",
    "sequential_dialogue": "추가 분기·순차 대사",
    "race_dialogue": "추가 경기 대사",
    "minigame": "미니게임",
    "course_information": "코스 설명",
    "machine_setting": "머신 설정",
    "garage_menu": "차고 선택 메뉴",
    "save_system": "저장·불러오기",
    "font_ui": "폰트 UI",
    "character_name": "캐릭터 이름",
}
SOURCE_GROUP_ORDER = tuple(SOURCE_GROUP_LABELS)
UI_JAPANESE_TEXT = {
    "disc1/allbin/u40/font_rendered_ui/e047": (
        "名前を\n入力してください。\n"
        "名前をローマ字で\n入力してください。\n"
        "出身を\n選択してください。"
    ),
    "disc1/allbin/u40/font_rendered_ui/e048": (
        "このままでよろしいですか？"
    ),
    "disc1/allbin/u40/font_rendered_ui/e055": "名前\n　\n　\n出身",
    "disc1/allbin/u40/font_rendered_ui/e056": (
        "草レース\nテストサーキット\nラリー"
    ),
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
class EditorLayoutProfile:
    columns: int
    rows: int
    row_policy: str = "maximum"
    label: str = "고정 셀"

    def __post_init__(self) -> None:
        if self.columns <= 0 or self.rows <= 0:
            raise DialogueEditorError("layout columns/rows must be positive")
        if self.row_policy not in {"maximum", "exact", "automatic"}:
            raise DialogueEditorError(
                f"unsupported row policy: {self.row_policy}"
            )

    @property
    def capacity(self) -> int:
        return self.columns * self.rows


@dataclass(frozen=True)
class TranslationBinding:
    source_path: Path
    value_path: tuple[str | int, ...]
    source_group: str
    source_label: str


@dataclass(frozen=True)
class LiteralReplacementChange:
    index: int
    entry_id: str
    occurrence_count: int
    before: str
    after: str


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
    line_pixel_widths: tuple[int, ...]
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
    def pixel_capacity_per_line(self) -> int:
        return self.columns * FULL_GLYPH_ADVANCE_PX

    @property
    def visual_pixel_overflow_rows(self) -> tuple[int, ...]:
        """Rows wider than the original 14px-per-cell visual envelope.

        This is informational. The game still wraps at the logical column
        count, so a visually narrow 18-character row remains invalid.
        """
        return tuple(
            index + 1
            for index, width in enumerate(self.line_pixel_widths)
            if width > self.pixel_capacity_per_line
        )

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


def glyph_advance_px(character: str) -> int:
    """Return the patched renderer's horizontal advance for one glyph."""
    if not isinstance(character, str) or len(character) != 1:
        raise DialogueEditorError("glyph measurement requires one character")
    if character in HALFWIDTH_CHARACTERS:
        return HALFWIDTH_GLYPH_ADVANCE_PX
    return FULL_GLYPH_ADVANCE_PX


def line_pixel_width(text: str) -> int:
    """Measure one displayed row without changing its logical glyph count."""
    if not isinstance(text, str):
        raise DialogueEditorError("line measurement requires a string")
    return sum(glyph_advance_px(character) for character in text)


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
    pixel_widths = tuple(line_pixel_width(line) for line in lines)
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
        line_pixel_widths=pixel_widths,
        visible_glyph_count=sum(widths),
        occupied_positions=occupied,
        columns=columns,
        rows=rows,
    )


def measure_runtime_auto_layout(
    text: str,
    *,
    columns: int,
    rows: int,
) -> LayoutMeasurement:
    """Measure a stream whose renderer wraps without stored align tokens."""
    if not isinstance(text, str):
        raise DialogueEditorError("dialogue text must be a string")
    display = expand_display_tokens(text.replace("\r\n", "\n").replace("\r", "\n"))
    if "\n" in display:
        # Explicit line breaks would add control words and violate the fixed
        # offsets in these sequential branch streams.
        lines = tuple(display.split("\n"))
    else:
        lines = tuple(
            display[offset : offset + columns]
            for offset in range(0, len(display), columns)
        ) or ("",)
    widths = tuple(len(line) for line in lines)
    pixel_widths = tuple(line_pixel_width(line) for line in lines)
    return LayoutMeasurement(
        source_text=text,
        display_text=display,
        lines=lines,
        line_widths=widths,
        line_pixel_widths=pixel_widths,
        visible_glyph_count=sum(widths),
        occupied_positions=sum(widths),
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


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DialogueEditorError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise DialogueEditorError(f"{path}: JSON root must be an object")
    return value


def _set_json_path_value(
    document: dict[str, Any],
    value_path: tuple[str | int, ...],
    value: str,
) -> None:
    if not value_path:
        raise DialogueEditorError("translation value path cannot be empty")
    target: Any = document
    for component in value_path[:-1]:
        try:
            target = target[component]
        except (KeyError, IndexError, TypeError) as error:
            raise DialogueEditorError(
                f"invalid translation value path: {value_path!r}"
            ) from error
    try:
        target[value_path[-1]] = value
    except (KeyError, IndexError, TypeError) as error:
        raise DialogueEditorError(
            f"invalid translation value path: {value_path!r}"
        ) from error


def _default_control_markup(kind: str, raw: str) -> str:
    if kind == "speaker_style":
        return f"{{speaker_style:{int(raw, 16) & 0x0FFF:03X}}}"
    if kind == "voice_transition":
        return f"{{voice_transition:{raw}}}"
    if kind in CONTROL_VISUAL_LABELS:
        return "{" + kind + "}"
    return f"{{control:{raw}}}"


def _context_from_workset_entry(
    entry: dict[str, Any],
    *,
    entry_id: str,
) -> DialogueControlContext | None:
    """Build a display/size context from an extracted font stream.

    Older pointerless and special-screen worksets predate the explicit
    ``markup``/``policy`` fields. Their raw token index, value, and kind are
    still sufficient to reconstruct the immutable shell. A stream containing
    an immutable control between two editable text segments is returned as
    ``None`` here and is represented as separate workspace segment entries.
    """
    original = entry.get("original")
    if not isinstance(original, dict):
        return None
    raw_tokens = original.get("tokens")
    raw_controls = original.get("control_tokens")
    if not isinstance(raw_tokens, list) or not isinstance(
        raw_controls, list
    ):
        return None
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
        if (
            not isinstance(token_index, int)
            or not 0 <= token_index < len(tokens)
            or not isinstance(raw, str)
            or not re.fullmatch(r"[0-9A-Fa-f]{4}", raw)
            or not isinstance(kind, str)
            or not kind
        ):
            raise DialogueEditorError(
                f"{entry_id}: invalid control token metadata"
            )
        markup = raw_control.get("markup")
        policy = raw_control.get("policy")
        if not isinstance(markup, str) or not markup:
            markup = _default_control_markup(kind, raw)
        if not isinstance(policy, str) or not policy:
            policy = (
                "movable-layout-in-story-only"
                if kind in MOVABLE_INTERNAL_CONTROL_KINDS
                else "preserve"
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
        if (controls[index].kind if index in controls else "glyph")
        in CONTROL_CONTENT_KINDS
    ]
    if not content_indices:
        return None
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
    if any(
        control.kind not in MOVABLE_INTERNAL_CONTROL_KINDS
        for control in internal
    ):
        return None
    if any(index not in controls for index in range(first_content)):
        return None
    if any(
        index not in controls
        for index in range(last_content + 1, len(tokens))
    ):
        return None
    return DialogueControlContext(
        entry_id=entry_id,
        original_stream_bytes=len(tokens) * 2,
        leading=leading,
        internal_movable=internal,
        trailing=trailing,
    )


def _source_size_slot(
    entry: dict[str, Any],
    *,
    entry_id: str,
) -> SafeSlotRecord | None:
    source = entry.get("source")
    if not isinstance(source, dict):
        return None
    file_offset = source.get("file_offset")
    unit_offset = source.get("unit_offset")
    byte_size = source.get("byte_size")
    unit_index = source.get("unit_index")
    subsystem = source.get("subsystem", entry.get("classification", "font"))
    if (
        not isinstance(file_offset, str)
        or not re.fullmatch(r"0x[0-9A-Fa-f]+", file_offset)
        or not isinstance(unit_offset, str)
        or not re.fullmatch(r"0x[0-9A-Fa-f]+", unit_offset)
        or not isinstance(byte_size, int)
        or byte_size <= 0
        or byte_size % 2
        or not isinstance(unit_index, int)
    ):
        return None
    file_end = int(file_offset, 16) + byte_size
    unit_end = int(unit_offset, 16) + byte_size
    return SafeSlotRecord(
        entry_id=entry_id,
        unit_index=unit_index,
        subsystem=str(subsystem),
        file_offset=f"0x{int(file_offset, 16):06X}",
        unit_offset=f"0x{int(unit_offset, 16):04X}",
        safe_end_file_offset=f"0x{file_end:06X}",
        safe_end_unit_offset=f"0x{unit_end:04X}",
        original_stream_bytes=byte_size,
        safe_slot_bytes=byte_size,
        safe_slot_words=byte_size // 2,
        additional_zero_gap_bytes=0,
        boundary_kind="original-stream-size-reference",
        next_physical_entry_id=None,
        protected_target="original stream end",
    )


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


def _entries_by_id(
    document: dict[str, Any],
    *,
    path: Path,
    container: str,
    id_field: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    raw_entries = document.get(container)
    if not isinstance(raw_entries, list) or not all(
        isinstance(entry, dict) for entry in raw_entries
    ):
        raise DialogueEditorError(
            f"{path}: {container} must be an object array"
        )
    result: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(raw_entries):
        entry_id = entry.get(id_field)
        if not isinstance(entry_id, str) or not entry_id:
            raise DialogueEditorError(
                f"{path}: {container}[{index}].{id_field} is invalid"
            )
        if entry_id in result:
            raise DialogueEditorError(
                f"{path}: duplicate stable ID {entry_id}"
            )
        result[entry_id] = entry
    return list(raw_entries), result


def _source_japanese(entry: dict[str, Any]) -> str:
    original = entry.get("original")
    if not isinstance(original, dict):
        return ""
    display = original.get("display_text")
    if isinstance(display, str):
        return display
    japanese = original.get("japanese")
    if isinstance(japanese, dict):
        display = japanese.get("display_text", japanese.get("text"))
        if isinstance(display, str):
            return display
    return ""


def _source_unit(entry: dict[str, Any]) -> int | None:
    source = entry.get("source")
    if not isinstance(source, dict):
        return None
    value = source.get("unit_index")
    return value if isinstance(value, int) else None


def _normalized_workspace_entry(
    *,
    entry_id: str,
    jp: str,
    ko: str,
    source_group: str,
    source_file: Path,
    classification: str,
    status: str,
    layout: EditorLayoutProfile,
    unit_index: int | None = None,
    source_id: str | None = None,
    renderer: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": entry_id,
        "jp": jp,
        "ko": ko,
        "source_group": source_group,
        "source_file": str(source_file),
        "classification": classification,
        "status": status,
        "max_glyphs": layout.capacity,
        "editor_layout": {
            "columns": layout.columns,
            "rows": layout.rows,
            "row_policy": layout.row_policy,
            "label": layout.label,
        },
    }
    if unit_index is not None:
        entry["unit_index"] = unit_index
    if source_id is not None:
        entry["source_id"] = source_id
    if renderer is not None:
        entry["renderer"] = renderer
    if notes is not None:
        entry["notes"] = notes
    return entry


def _pointerless_mutable_parts(
    entry: dict[str, Any],
) -> list[list[tuple[int, str | None]]]:
    original = entry.get("original")
    if not isinstance(original, dict):
        return []
    raw_tokens = original.get("tokens")
    raw_controls = original.get("control_tokens")
    if not isinstance(raw_tokens, list) or not isinstance(
        raw_controls, list
    ):
        return []
    controls = {
        int(control["token_index"]): str(control["kind"])
        for control in raw_controls
        if isinstance(control, dict)
        and isinstance(control.get("token_index"), int)
        and isinstance(control.get("kind"), str)
    }
    parts: list[list[tuple[int, str | None]]] = []
    current: list[tuple[int, str | None]] = []
    current_mutable: bool | None = None
    for index, raw in enumerate(raw_tokens):
        try:
            token = int(str(raw), 16)
        except ValueError as error:
            raise DialogueEditorError(
                f"{entry.get('entry_id')}: invalid pointerless token"
            ) from error
        kind = controls.get(index)
        mutable = kind is None or kind in MOVABLE_INTERNAL_CONTROL_KINDS
        if current_mutable is not None and mutable != current_mutable:
            if current_mutable:
                parts.append(current)
            current = []
        current_mutable = mutable
        current.append((token, kind))
    if current and current_mutable:
        parts.append(current)
    return parts


def _split_pointerless_japanese(
    entry: dict[str, Any],
    mutable_parts: list[list[tuple[int, str | None]]],
) -> list[str]:
    display = _source_japanese(entry)
    cursor = 0
    segments: list[str] = []
    for part in mutable_parts:
        output: list[str] = []
        for _token, kind in part:
            if kind == "align":
                while cursor < len(display) and display[cursor] != "\n":
                    cursor += 1
                if cursor < len(display):
                    cursor += 1
                output.append("\n")
            elif kind in {"name_surname", "name_given"}:
                output.append(
                    "{name:surname}"
                    if kind == "name_surname"
                    else "{name:given}"
                )
            elif kind is None:
                while cursor < len(display) and display[cursor] == "\n":
                    cursor += 1
                if cursor < len(display):
                    output.append(display[cursor])
                    cursor += 1
        segments.append("".join(output))
    if segments and not any(segments):
        return [display for _part in mutable_parts]
    return segments


def _pointerless_segment_contexts(
    entry: dict[str, Any],
    *,
    entry_ids: list[str],
) -> list[DialogueControlContext | None]:
    """Expose each editable segment's surrounding immutable controls."""
    original = entry.get("original")
    if not isinstance(original, dict):
        return [None] * len(entry_ids)
    raw_tokens = original.get("tokens")
    raw_controls = original.get("control_tokens")
    if not isinstance(raw_tokens, list) or not isinstance(
        raw_controls, list
    ):
        return [None] * len(entry_ids)
    controls_by_index: dict[int, ProtectedControlToken] = {}
    kinds: dict[int, str] = {}
    for control in raw_controls:
        if not isinstance(control, dict):
            continue
        index = control.get("token_index")
        raw = control.get("raw")
        kind = control.get("kind")
        if (
            not isinstance(index, int)
            or not isinstance(raw, str)
            or not isinstance(kind, str)
        ):
            continue
        kinds[index] = kind
        controls_by_index[index] = ProtectedControlToken(
            token_index=index,
            raw=raw.upper(),
            kind=kind,
            markup=(
                str(control["markup"])
                if isinstance(control.get("markup"), str)
                else _default_control_markup(kind, raw)
            ),
            policy=(
                str(control["policy"])
                if isinstance(control.get("policy"), str)
                else (
                    "movable-layout-in-story-only"
                    if kind in MOVABLE_INTERNAL_CONTROL_KINDS
                    else "preserve"
                )
            ),
        )

    mutable_ranges: list[tuple[int, int]] = []
    range_start: int | None = None
    for index in range(len(raw_tokens)):
        kind = kinds.get(index)
        mutable = kind is None or kind in MOVABLE_INTERNAL_CONTROL_KINDS
        if mutable and range_start is None:
            range_start = index
        if not mutable and range_start is not None:
            mutable_ranges.append((range_start, index))
            range_start = None
    if range_start is not None:
        mutable_ranges.append((range_start, len(raw_tokens)))
    if len(mutable_ranges) != len(entry_ids):
        return [None] * len(entry_ids)

    leading: list[list[ProtectedControlToken]] = [
        [] for _entry_id in entry_ids
    ]
    trailing: list[list[ProtectedControlToken]] = [
        [] for _entry_id in entry_ids
    ]
    internal: list[list[ProtectedControlToken]] = [
        [] for _entry_id in entry_ids
    ]
    trailing_kinds = {
        "voice_transition",
        "page_end",
        "stream_end",
        "style_off",
    }
    for segment_index, (start, end) in enumerate(mutable_ranges):
        internal[segment_index].extend(
            controls_by_index[index]
            for index in range(start, end)
            if index in controls_by_index
        )
        previous_end = (
            mutable_ranges[segment_index - 1][1]
            if segment_index
            else 0
        )
        for index in range(previous_end, start):
            control = controls_by_index.get(index)
            if control is None:
                continue
            if segment_index and control.kind in trailing_kinds:
                trailing[segment_index - 1].append(control)
            else:
                leading[segment_index].append(control)
    last_end = mutable_ranges[-1][1]
    trailing[-1].extend(
        controls_by_index[index]
        for index in range(last_end, len(raw_tokens))
        if index in controls_by_index
    )

    result: list[DialogueControlContext | None] = []
    for segment_index, entry_id in enumerate(entry_ids):
        start, end = mutable_ranges[segment_index]
        original_words = (
            end
            - start
            + len(leading[segment_index])
            + len(trailing[segment_index])
        )
        result.append(
            DialogueControlContext(
                entry_id=entry_id,
                original_stream_bytes=original_words * 2,
                leading=tuple(leading[segment_index]),
                internal_movable=tuple(internal[segment_index]),
                trailing=tuple(trailing[segment_index]),
            )
        )
    return result


def _special_source_group(classification: str) -> str:
    if classification == "course_information_dialogue":
        return "course_information"
    if classification in {
        "machine_setting_dialogue",
        "machine_setting_sequential_dialogue",
        "machine_setting_confirmation_choice",
    }:
        return "machine_setting"
    if classification == "garage_action_menu":
        return "garage_menu"
    return "minigame"


def _unindexed_source_group(classification: str) -> str:
    groups = {
        "sequential_event_page": "sequential_dialogue",
        "indexed_race_page": "race_dialogue",
        "indexed_minigame_page": "minigame",
        "save_ui_stream": "save_system",
    }
    try:
        return groups[classification]
    except KeyError as error:
        raise DialogueEditorError(
            f"unsupported unindexed-font classification {classification!r}"
        ) from error


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

    @property
    def workspace_mode(self) -> bool:
        return False

    @property
    def supports_save_as(self) -> bool:
        return True

    @property
    def display_path(self) -> Path:
        return self.path

    def source_group(self, index: int) -> str:
        value = self.entries[index].get("source_group")
        return value if isinstance(value, str) else "story_dialogue"

    def source_group_label(self, index: int) -> str:
        group = self.source_group(index)
        return SOURCE_GROUP_LABELS.get(group, group)

    def source_groups(self) -> tuple[tuple[str, str], ...]:
        present = {self.source_group(index) for index in range(len(self))}
        ordered = [
            group for group in SOURCE_GROUP_ORDER if group in present
        ]
        ordered.extend(sorted(present - set(ordered)))
        return tuple(
            (group, SOURCE_GROUP_LABELS.get(group, group))
            for group in ordered
        )

    def layout_profile(self, index: int) -> EditorLayoutProfile:
        raw = self.entries[index].get("editor_layout")
        if not isinstance(raw, dict):
            return EditorLayoutProfile(COLUMNS, ROWS, label="대사창")
        columns = raw.get("columns", COLUMNS)
        rows = raw.get("rows", ROWS)
        row_policy = raw.get("row_policy", "maximum")
        label = raw.get("label", "고정 셀")
        if (
            not isinstance(columns, int)
            or not isinstance(rows, int)
            or not isinstance(row_policy, str)
            or not isinstance(label, str)
        ):
            raise DialogueEditorError(
                f"{self.ids[index]}: invalid editor layout profile"
            )
        return EditorLayoutProfile(
            columns=columns,
            rows=rows,
            row_policy=row_policy,
            label=label,
        )

    def layout_measurement(
        self,
        index: int,
        text: str | None = None,
    ) -> LayoutMeasurement:
        profile = self.layout_profile(index)
        value = self.value(index) if text is None else text
        if profile.row_policy == "automatic":
            return measure_runtime_auto_layout(
                value,
                columns=profile.columns,
                rows=profile.rows,
            )
        return measure_layout(value, columns=profile.columns, rows=profile.rows)

    def layout_policy_violated(self, index: int) -> bool:
        profile = self.layout_profile(index)
        measurement = self.layout_measurement(index)
        return measurement.exceeds_limits or (
            profile.row_policy == "exact"
            and len(measurement.lines) != profile.rows
        )

    def _validate_dirty_row_policies(self) -> None:
        for index in self.dirty_indices:
            profile = self.layout_profile(index)
            measurement = self.layout_measurement(index)
            line_count = len(measurement.lines)
            if profile.row_policy == "exact" and line_count != profile.rows:
                raise DialogueEditorError(
                    f"{self.ids[index]}: 행 수를 {profile.rows}행으로 "
                    f"보존해야 합니다(현재 {line_count}행)."
                )
            if profile.row_policy == "maximum" and measurement.row_overflow:
                raise DialogueEditorError(
                    f"{profile.rows}줄을 넘는 수정 대사는 저장할 수 "
                    f"없습니다: {self.ids[index]} ({line_count}줄)"
                )
            if profile.row_policy == "automatic" and "\n" in self.value(index):
                raise DialogueEditorError(
                    f"{self.ids[index]}: 자동 줄바꿈 슬롯에는 수동 줄바꿈을 "
                    "저장할 수 없습니다."
                )
            if profile.row_policy == "automatic" and measurement.row_overflow:
                raise DialogueEditorError(
                    f"{self.ids[index]}: 런타임 자동 줄바꿈 결과가 "
                    f"{profile.rows}줄을 넘습니다(현재 {line_count}줄)."
                )

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
        if isinstance(value, int) and value > 0:
            return value
        return self.layout_profile(index).capacity

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
            "source_group": self.source_group_label(index),
            "source_file": str(entry.get("source_file", "")),
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
                self.source_group_label(index),
                self.japanese(index),
                self.value(index),
                control_text,
            )
        ).casefold()

    def layout_overflow_indices(self) -> tuple[int, ...]:
        return tuple(
            index for index in range(len(self))
            if self.layout_policy_violated(index)
        )

    def short_line_candidate_indices(self) -> tuple[int, ...]:
        return tuple(
            index for index in range(len(self))
            if self.layout_measurement(index).short_line_rows
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
        self._validate_dirty_row_policies()
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
        exact_row_mismatch = 0
        visual_pixel_overflow = 0
        maximum_line_pixel_width = 0
        storage_slot_measurable = 0
        storage_slot_exact = 0
        storage_slot_under_capacity = 0
        storage_slot_overflow = 0
        maximum_storage_overflow_bytes = 0
        empty = 0
        for index, value in enumerate(self._values):
            measurement = self.layout_measurement(index, value)
            profile = self.layout_profile(index)
            exact_mismatch = (
                profile.row_policy == "exact"
                and len(measurement.lines) != profile.rows
            )
            storage = self.storage_slot_measurement(index)
            if not value.strip():
                empty += 1
            if measurement.glyph_capacity_overflow:
                glyph_capacity_overflow += 1
            if measurement.column_overflow_rows:
                line_width_overflow += 1
            if measurement.row_overflow:
                row_count_overflow += 1
            if exact_mismatch:
                exact_row_mismatch += 1
            if measurement.visual_pixel_overflow_rows:
                visual_pixel_overflow += 1
            maximum_line_pixel_width = max(
                maximum_line_pixel_width,
                *measurement.line_pixel_widths,
            )
            if measurement.short_line_rows:
                short_line_candidates += 1
            if measurement.fits and not exact_mismatch:
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
            "workspace_mode": self.workspace_mode,
            "editable_field": self.editable_field,
            "entries": len(self),
            "source_group_counts": dict(
                sorted(
                    Counter(
                        self.source_group(index)
                        for index in range(len(self))
                    ).items()
                )
            ),
            "layout_profile_counts": dict(
                sorted(
                    Counter(
                        (
                            f"{profile.columns}x{profile.rows}:"
                            f"{profile.row_policy}"
                        )
                        for profile in (
                            self.layout_profile(index)
                            for index in range(len(self))
                        )
                    ).items()
                )
            ),
            "fits_17x3": fits,
            "layout_fits": fits,
            "layout_overflow": overflow,
            "glyph_capacity_overflow": glyph_capacity_overflow,
            "line_width_overflow": line_width_overflow,
            "row_count_overflow": row_count_overflow,
            "exact_row_mismatch": exact_row_mismatch,
            "halfwidth_renderer_enabled": True,
            "full_glyph_advance_px": FULL_GLYPH_ADVANCE_PX,
            "halfwidth_glyph_advance_px": HALFWIDTH_GLYPH_ADVANCE_PX,
            "halfwidth_characters": sorted(HALFWIDTH_CHARACTERS),
            "visual_pixel_overflow": visual_pixel_overflow,
            "maximum_line_pixel_width": maximum_line_pixel_width,
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


class FontTranslationWorkspaceDocument(DialogueDocument):
    """One protected editor view backed by several canonical JSON files."""

    def __init__(
        self,
        path: Path,
        document: dict[str, Any],
        *,
        bindings: list[TranslationBinding],
        source_documents: dict[Path, dict[str, Any]],
        control_contexts: dict[str, DialogueControlContext],
        safe_slots: dict[str, SafeSlotRecord],
        unit_storage_profiles: dict[int, UnitStorageProfile],
    ) -> None:
        if len(bindings) != len(document.get("entries", [])):
            raise DialogueEditorError(
                "workspace binding count differs from entry count"
            )
        self._bindings = tuple(bindings)
        self._source_documents = {
            source_path: copy.deepcopy(source)
            for source_path, source in source_documents.items()
        }
        super().__init__(
            path,
            document,
            editable_field="ko",
            control_contexts=control_contexts,
            safe_slots=safe_slots,
            unit_storage_profiles=unit_storage_profiles,
        )

    @property
    def workspace_mode(self) -> bool:
        return True

    @property
    def supports_save_as(self) -> bool:
        return False

    @property
    def display_path(self) -> Path:
        return WORKSPACE_DISPLAY_PATH

    @property
    def source_paths(self) -> tuple[Path, ...]:
        return tuple(self._source_documents)

    @classmethod
    def load(
        cls,
        *,
        dialogue_translation_path: Path = DEFAULT_INPUT,
        dialogue_workset_path: Path = DEFAULT_WORKSET,
        safe_slots_path: Path = DEFAULT_SAFE_SLOTS,
        pointerless_translation_path: Path = (
            DEFAULT_POINTERLESS_TRANSLATION
        ),
        pointerless_workset_path: Path = DEFAULT_POINTERLESS_WORKSET,
        special_translation_path: Path = DEFAULT_SPECIAL_TRANSLATION,
        special_workset_path: Path = DEFAULT_SPECIAL_WORKSET,
        unindexed_translation_path: Path = DEFAULT_UNINDEXED_TRANSLATION,
        unindexed_workset_path: Path = DEFAULT_UNINDEXED_WORKSET,
        ui_translation_path: Path = DEFAULT_UI_TRANSLATION,
        ui_workset_path: Path = DEFAULT_UI_WORKSET,
        character_names_path: Path = DEFAULT_CHARACTER_NAMES,
    ) -> "FontTranslationWorkspaceDocument":
        translation_paths = (
            dialogue_translation_path,
            pointerless_translation_path,
            special_translation_path,
            unindexed_translation_path,
            ui_translation_path,
            character_names_path,
        )
        source_documents = {
            path: _load_json_object(path) for path in translation_paths
        }
        dialogue_translation = source_documents[dialogue_translation_path]
        pointerless_translation = source_documents[
            pointerless_translation_path
        ]
        special_translation = source_documents[special_translation_path]
        unindexed_translation = source_documents[
            unindexed_translation_path
        ]
        ui_translation = source_documents[ui_translation_path]
        character_names = source_documents[character_names_path]

        dialogue_workset = _load_json_object(dialogue_workset_path)
        pointerless_workset = _load_json_object(pointerless_workset_path)
        special_workset = _load_json_object(special_workset_path)
        unindexed_workset = _load_json_object(unindexed_workset_path)
        ui_workset = _load_json_object(ui_workset_path)

        entries: list[dict[str, Any]] = []
        bindings: list[TranslationBinding] = []
        contexts: dict[str, DialogueControlContext] = {}
        safe_slots: dict[str, SafeSlotRecord] = {}
        entry_ids_seen: set[str] = set()

        def add_entry(
            entry: dict[str, Any],
            binding: TranslationBinding,
            *,
            context: DialogueControlContext | None = None,
            safe_slot: SafeSlotRecord | None = None,
        ) -> None:
            entry_id = str(entry["id"])
            if entry_id in entry_ids_seen:
                raise DialogueEditorError(
                    f"workspace duplicate stable ID {entry_id}"
                )
            entry_ids_seen.add(entry_id)
            entries.append(entry)
            bindings.append(binding)
            if context is not None:
                contexts[entry_id] = context
            if safe_slot is not None:
                safe_slots[entry_id] = safe_slot

        dialogue_items, _dialogue_by_id = _entries_by_id(
            dialogue_translation,
            path=dialogue_translation_path,
            container="entries",
            id_field="id",
        )
        work_items, work_by_id = _entries_by_id(
            dialogue_workset,
            path=dialogue_workset_path,
            container="entries",
            id_field="entry_id",
        )
        dialogue_ids = [str(entry["id"]) for entry in dialogue_items]
        work_ids = [str(entry["entry_id"]) for entry in work_items]
        if dialogue_ids != work_ids:
            raise DialogueEditorError(
                "main dialogue translation/workset stable ID order differs"
            )
        main_contexts = load_control_contexts(
            dialogue_workset_path,
            required_ids=dialogue_ids,
        )
        main_slots = load_safe_slot_records(
            safe_slots_path,
            required_ids=dialogue_ids,
            workset_path=dialogue_workset_path,
        )
        for index, translation in enumerate(dialogue_items):
            entry_id = str(translation["id"])
            ko = translation.get("ko")
            if not isinstance(ko, str):
                raise DialogueEditorError(
                    f"{entry_id}: main dialogue ko must be a string"
                )
            source = work_by_id[entry_id]
            add_entry(
                _normalized_workspace_entry(
                    entry_id=entry_id,
                    jp=_source_japanese(source),
                    ko=ko,
                    source_group="story_dialogue",
                    source_file=dialogue_translation_path,
                    classification=str(
                        source.get("classification", "story")
                    ),
                    status=str(
                        dialogue_translation.get("status", "")
                    ),
                    layout=EditorLayoutProfile(
                        COLUMNS,
                        ROWS,
                        label="본편 대사창",
                    ),
                    unit_index=_source_unit(source),
                ),
                TranslationBinding(
                    dialogue_translation_path,
                    ("entries", index, "ko"),
                    "story_dialogue",
                    "본편 대사",
                ),
                context=main_contexts[entry_id],
                safe_slot=main_slots[entry_id],
            )

        pointerless_items, _pointerless_translation_by_id = _entries_by_id(
            pointerless_translation,
            path=pointerless_translation_path,
            container="entries",
            id_field="id",
        )
        _pointerless_sources, pointerless_by_id = _entries_by_id(
            pointerless_workset,
            path=pointerless_workset_path,
            container="entries",
            id_field="entry_id",
        )
        pointerless_ids = {str(entry["id"]) for entry in pointerless_items}
        if pointerless_ids != set(pointerless_by_id):
            raise DialogueEditorError(
                "pointerless translation/workset stable ID set differs"
            )
        for translation_index, translation in enumerate(pointerless_items):
            source_id = str(translation["id"])
            source = pointerless_by_id[source_id]
            mutable_parts = _pointerless_mutable_parts(source)
            japanese_segments = _split_pointerless_japanese(
                source,
                mutable_parts,
            )
            raw_segments = translation.get("ko_segments")
            if (
                not mutable_parts
                and raw_segments is None
                and translation.get("ko") == ""
            ):
                # A control-only sentinel is part of the pointerless build
                # artifact but has no font-rendered translation field to edit.
                continue
            if raw_segments is None:
                ko = translation.get("ko")
                if not isinstance(ko, str):
                    raise DialogueEditorError(
                        f"{source_id}: pointerless ko is missing"
                    )
                translated_segments = [ko]
                value_paths = [
                    ("entries", translation_index, "ko")
                ]
            else:
                if not isinstance(raw_segments, list) or not all(
                    isinstance(value, str) for value in raw_segments
                ):
                    raise DialogueEditorError(
                        f"{source_id}: ko_segments must be strings"
                    )
                translated_segments = list(raw_segments)
                value_paths = [
                    (
                        "entries",
                        translation_index,
                        "ko_segments",
                        segment_index,
                    )
                    for segment_index in range(len(translated_segments))
                ]
            if len(translated_segments) != len(mutable_parts):
                raise DialogueEditorError(
                    f"{source_id}: translated/source segment count differs"
                )
            classification = str(
                source.get("classification", "pointerless_page")
            )
            editor_ids = [
                (
                    source_id
                    if len(translated_segments) == 1
                    else f"{source_id}#segment-{segment_index + 1:02d}"
                )
                for segment_index in range(len(translated_segments))
            ]
            if len(editor_ids) == 1:
                segment_contexts = [
                    _context_from_workset_entry(
                        source,
                        entry_id=source_id,
                    )
                ]
            else:
                segment_contexts = _pointerless_segment_contexts(
                    source,
                    entry_ids=editor_ids,
                )
            single_context = segment_contexts[0]
            single_slot = (
                _source_size_slot(source, entry_id=source_id)
                if single_context is not None and len(editor_ids) == 1
                else None
            )
            for segment_index, (
                ko,
                value_path,
                mutable_part,
                entry_id,
                segment_context,
            ) in enumerate(
                zip(
                    translated_segments,
                    value_paths,
                    mutable_parts,
                    editor_ids,
                    segment_contexts,
                )
            ):
                source_rows = (
                    sum(kind == "align" for _token, kind in mutable_part) + 1
                )
                is_choice = classification == "pointerless_choice"
                layout = EditorLayoutProfile(
                    COLUMNS,
                    source_rows if is_choice else ROWS,
                    row_policy="exact" if is_choice else "maximum",
                    label=(
                        "무포인터 선택지"
                        if is_choice
                        else "무포인터 대사창"
                    ),
                )
                add_entry(
                    _normalized_workspace_entry(
                        entry_id=entry_id,
                        jp=(
                            japanese_segments[segment_index]
                            if segment_index < len(japanese_segments)
                            else _source_japanese(source)
                        ),
                        ko=ko,
                        source_group="pointerless_page",
                        source_file=pointerless_translation_path,
                        classification=classification,
                        status=str(
                            pointerless_translation.get("status", "")
                        ),
                        layout=layout,
                        unit_index=_source_unit(source),
                        source_id=source_id,
                        notes=(
                            f"원본 스트림의 편집 구간 "
                            f"{segment_index + 1}/{len(translated_segments)}"
                            if len(translated_segments) > 1
                            else None
                        ),
                    ),
                    TranslationBinding(
                        pointerless_translation_path,
                        value_path,
                        "pointerless_page",
                        "무포인터 선택·대사",
                    ),
                    context=segment_context,
                    safe_slot=single_slot,
                )

        special_items, _special_translation_by_id = _entries_by_id(
            special_translation,
            path=special_translation_path,
            container="translations",
            id_field="id",
        )
        _special_sources, special_by_id = _entries_by_id(
            special_workset,
            path=special_workset_path,
            container="entries",
            id_field="entry_id",
        )
        special_ids = {str(entry["id"]) for entry in special_items}
        if special_ids != set(special_by_id):
            raise DialogueEditorError(
                "special-screen translation/workset stable ID set differs"
            )
        for index, translation in enumerate(special_items):
            entry_id = str(translation["id"])
            ko = translation.get("ko")
            if not isinstance(ko, str):
                raise DialogueEditorError(
                    f"{entry_id}: special-screen ko must be a string"
                )
            source = special_by_id[entry_id]
            classification = str(source.get("classification", "special"))
            raw_layout = source.get("layout")
            columns = (
                raw_layout.get("columns", COLUMNS)
                if isinstance(raw_layout, dict)
                else COLUMNS
            )
            rows = (
                raw_layout.get("rows", ROWS)
                if isinstance(raw_layout, dict)
                else ROWS
            )
            if not isinstance(columns, int) or not isinstance(rows, int):
                raise DialogueEditorError(
                    f"{entry_id}: invalid special-screen layout"
                )
            group = _special_source_group(classification)
            context = _context_from_workset_entry(
                source,
                entry_id=entry_id,
            )
            add_entry(
                _normalized_workspace_entry(
                    entry_id=entry_id,
                    jp=_source_japanese(source),
                    ko=ko,
                    source_group=group,
                    source_file=special_translation_path,
                    classification=classification,
                    status=str(special_translation.get("status", "")),
                    layout=EditorLayoutProfile(
                        columns,
                        rows,
                        row_policy=(
                            "automatic"
                            if isinstance(raw_layout, dict)
                            and raw_layout.get("runtime_auto_wrap", False)
                            else "maximum"
                        ),
                        label=SOURCE_GROUP_LABELS[group],
                    ),
                    unit_index=_source_unit(source),
                ),
                TranslationBinding(
                    special_translation_path,
                    ("translations", index, "ko"),
                    group,
                    SOURCE_GROUP_LABELS[group],
                ),
                context=context,
                safe_slot=(
                    _source_size_slot(source, entry_id=entry_id)
                    if context is not None
                    else None
                ),
            )

        unindexed_items, _unindexed_translation_by_id = _entries_by_id(
            unindexed_translation,
            path=unindexed_translation_path,
            container="translations",
            id_field="id",
        )
        unindexed_sources, unindexed_by_id = _entries_by_id(
            unindexed_workset,
            path=unindexed_workset_path,
            container="entries",
            id_field="entry_id",
        )
        unindexed_ids = [str(entry["id"]) for entry in unindexed_items]
        unindexed_source_ids = [
            str(entry["entry_id"]) for entry in unindexed_sources
        ]
        if unindexed_ids != unindexed_source_ids:
            raise DialogueEditorError(
                "unindexed-font translation/workset stable ID order differs"
            )
        for index, translation in enumerate(unindexed_items):
            entry_id = str(translation["id"])
            ko = translation.get("ko")
            if not isinstance(ko, str):
                raise DialogueEditorError(
                    f"{entry_id}: unindexed-font ko must be a string"
                )
            source = unindexed_by_id[entry_id]
            classification = str(source.get("classification", ""))
            group = _unindexed_source_group(classification)
            raw_layout = source.get("layout")
            columns = (
                raw_layout.get("columns", COLUMNS)
                if isinstance(raw_layout, dict)
                else COLUMNS
            )
            rows = (
                raw_layout.get("rows", ROWS)
                if isinstance(raw_layout, dict)
                else ROWS
            )
            if not isinstance(columns, int) or not isinstance(rows, int):
                raise DialogueEditorError(
                    f"{entry_id}: invalid unindexed-font layout"
                )
            context = _context_from_workset_entry(
                source,
                entry_id=entry_id,
            )
            add_entry(
                _normalized_workspace_entry(
                    entry_id=entry_id,
                    jp=_source_japanese(source),
                    ko=ko,
                    source_group=group,
                    source_file=unindexed_translation_path,
                    classification=classification,
                    status=str(
                        translation.get(
                            "review_status",
                            unindexed_translation.get("status", ""),
                        )
                    ),
                    layout=EditorLayoutProfile(
                        columns,
                        rows,
                        label=SOURCE_GROUP_LABELS[group],
                    ),
                    unit_index=_source_unit(source),
                    notes=(
                        "정적 소비자 계열은 확인했으나 실제 진입 경로와 "
                        "재삽입 위치는 별도 런타임 검증 필요"
                    ),
                ),
                TranslationBinding(
                    unindexed_translation_path,
                    ("translations", index, "ko"),
                    group,
                    SOURCE_GROUP_LABELS[group],
                ),
                context=context,
                safe_slot=(
                    _source_size_slot(source, entry_id=entry_id)
                    if context is not None
                    else None
                ),
            )

        ui_items, _ui_translation_by_id = _entries_by_id(
            ui_translation,
            path=ui_translation_path,
            container="translations",
            id_field="id",
        )
        _ui_sources, ui_by_id = _entries_by_id(
            ui_workset,
            path=ui_workset_path,
            container="entries",
            id_field="entry_id",
        )
        missing_ui = [
            str(entry["id"])
            for entry in ui_items
            if str(entry["id"]) not in ui_by_id
        ]
        if missing_ui:
            raise DialogueEditorError(
                f"UI workset is missing {missing_ui[0]}"
            )
        for index, translation in enumerate(ui_items):
            entry_id = str(translation["id"])
            ko = translation.get("ko")
            if not isinstance(ko, str):
                raise DialogueEditorError(
                    f"{entry_id}: UI ko must be a string"
                )
            source = ui_by_id[entry_id]
            original = source.get("original")
            controls = (
                original.get("control_tokens", [])
                if isinstance(original, dict)
                else []
            )
            rows = (
                sum(
                    isinstance(control, dict)
                    and control.get("kind") == "align"
                    for control in controls
                )
                + 1
            )
            context = _context_from_workset_entry(
                source,
                entry_id=entry_id,
            )
            add_entry(
                _normalized_workspace_entry(
                    entry_id=entry_id,
                    jp=UI_JAPANESE_TEXT.get(
                        entry_id,
                        _source_japanese(source),
                    ),
                    ko=ko,
                    source_group="font_ui",
                    source_file=ui_translation_path,
                    classification="font_rendered_ui",
                    status=str(translation.get("review_status", "")),
                    layout=EditorLayoutProfile(
                        COLUMNS,
                        rows,
                        row_policy="exact",
                        label="폰트 UI 고정 행",
                    ),
                    unit_index=_source_unit(source),
                    renderer=(
                        str(translation["renderer"])
                        if "renderer" in translation
                        else None
                    ),
                    notes=(
                        str(translation["notes"])
                        if "notes" in translation
                        else None
                    ),
                ),
                TranslationBinding(
                    ui_translation_path,
                    ("translations", index, "ko"),
                    "font_ui",
                    "폰트 UI",
                ),
                context=context,
                safe_slot=(
                    _source_size_slot(source, entry_id=entry_id)
                    if context is not None
                    else None
                ),
            )

        fixed = character_names.get("fixed_player_name")
        speaker_table = character_names.get("speaker_name_table")
        if (
            not isinstance(fixed, dict)
            or not isinstance(speaker_table, dict)
            or not isinstance(speaker_table.get("records"), list)
        ):
            raise DialogueEditorError(
                f"{character_names_path}: incomplete character-name artifact"
            )
        source_field_words = fixed.get("source_field_words")
        if not isinstance(source_field_words, dict):
            raise DialogueEditorError(
                f"{character_names_path}: fixed name field sizes are missing"
            )
        for field, jp, label in (
            ("surname", "司馬", "고정 주인공 성"),
            ("given_name", "誠一郎", "고정 주인공 이름"),
        ):
            ko = fixed.get(field)
            columns = source_field_words.get(field)
            if not isinstance(ko, str) or not isinstance(columns, int):
                raise DialogueEditorError(
                    f"{character_names_path}: invalid fixed {field}"
                )
            entry_id = f"disc1/character_name/fixed_player/{field}"
            add_entry(
                _normalized_workspace_entry(
                    entry_id=entry_id,
                    jp=jp,
                    ko=ko,
                    source_group="character_name",
                    source_file=character_names_path,
                    classification="fixed_player_name",
                    status=str(fixed.get("policy", "")),
                    layout=EditorLayoutProfile(
                        columns,
                        1,
                        label=label,
                    ),
                ),
                TranslationBinding(
                    character_names_path,
                    ("fixed_player_name", field),
                    "character_name",
                    label,
                ),
            )
        records = speaker_table["records"]
        safe_limit = speaker_table.get("safe_glyph_limit")
        if not isinstance(safe_limit, int) or not all(
            isinstance(record, dict) for record in records
        ):
            raise DialogueEditorError(
                f"{character_names_path}: invalid speaker-name table"
            )
        for record_index, record in enumerate(records):
            jp = record.get("jp")
            ko = record.get("ko")
            table_index = record.get("index")
            if (
                not isinstance(jp, str)
                or not isinstance(ko, str)
                or not isinstance(table_index, int)
            ):
                raise DialogueEditorError(
                    f"{character_names_path}: invalid speaker record "
                    f"{record_index}"
                )
            entry_id = (
                f"disc1/character_name/speaker/{table_index:02d}"
            )
            add_entry(
                _normalized_workspace_entry(
                    entry_id=entry_id,
                    jp=jp,
                    ko=ko,
                    source_group="character_name",
                    source_file=character_names_path,
                    classification="speaker_name",
                    status=str(character_names.get("status", "")),
                    layout=EditorLayoutProfile(
                        safe_limit,
                        1,
                        label="화자명 테이블",
                    ),
                    notes=(
                        str(record["glossary_term_id"])
                        if record.get("glossary_term_id") is not None
                        else None
                    ),
                ),
                TranslationBinding(
                    character_names_path,
                    (
                        "speaker_name_table",
                        "records",
                        record_index,
                        "ko",
                    ),
                    "character_name",
                    "캐릭터 화자명",
                ),
            )

        workspace = {
            "schema_version": 1,
            "workspace_kind": "disc1-font-rendered-translation-editor",
            "status": "editor-view-not-a-build-artifact",
            "entry_count": len(entries),
            "rules": {"editable_field": "entries[].ko"},
            "scope": {
                "included": [
                    SOURCE_GROUP_LABELS[group]
                    for group in SOURCE_GROUP_ORDER
                ],
                "excluded": [
                    "그래픽에 직접 새겨진 버튼·라벨·타이틀 문자",
                    "이름 입력용 원문 문자 팔레트와 런타임 버퍼",
                    "표시 글리프가 없는 제어 전용 센티널",
                ],
            },
            "entries": entries,
        }
        return cls(
            WORKSPACE_DISPLAY_PATH,
            workspace,
            bindings=bindings,
            source_documents=source_documents,
            control_contexts=contexts,
            safe_slots=safe_slots,
            unit_storage_profiles=build_unit_storage_profiles(main_slots),
        )

    def _validate_workspace_constraints(self) -> None:
        self._validate_dirty_row_policies()
        for index in self.dirty_indices:
            if self.source_group(index) != "character_name":
                continue
            measurement = self.layout_measurement(index)
            if measurement.exceeds_limits:
                profile = self.layout_profile(index)
                raise DialogueEditorError(
                    f"{self.ids[index]}: 이름은 {profile.columns}글리프 "
                    "안에 들어가야 합니다."
                )
        names_path = next(
            (
                path
                for path in self._source_documents
                if path.name == DEFAULT_CHARACTER_NAMES.name
            ),
            None,
        )
        if names_path is not None:
            name_output = copy.deepcopy(self._source_documents[names_path])
            for index, binding in enumerate(self._bindings):
                if binding.source_path == names_path:
                    _set_json_path_value(
                        name_output,
                        binding.value_path,
                        self.value(index),
                    )
            fixed = name_output["fixed_player_name"]
            combined = len(str(fixed["surname"])) + len(
                str(fixed["given_name"])
            )
            shared = int(fixed["runtime_shared_glyph_slots"])
            if combined > shared:
                raise DialogueEditorError(
                    f"고정 주인공명은 공유 {shared}글리프를 초과할 수 "
                    f"없습니다(현재 {combined})."
                )

    def save(
        self,
        path: Path | None = None,
    ) -> tuple[Path, ...]:
        if path is not None and path != self.path:
            raise DialogueEditorError(
                "통합 작업공간은 다른 이름으로 저장할 수 없습니다. "
                "각 수정은 원본 번역 JSON으로 되돌아갑니다."
            )
        self._validate_workspace_constraints()
        dirty = self.dirty_indices
        if not dirty:
            return ()

        changed_paths = tuple(
            dict.fromkeys(self._bindings[index].source_path for index in dirty)
        )
        outputs = {
            source_path: copy.deepcopy(self._source_documents[source_path])
            for source_path in changed_paths
        }
        for index in dirty:
            binding = self._bindings[index]
            _set_json_path_value(
                outputs[binding.source_path],
                binding.value_path,
                self.value(index),
            )

        for source_path in changed_paths:
            current = _load_json_object(source_path)
            if current != self._source_documents[source_path]:
                raise DialogueEditorError(
                    f"{source_path}: 편집기를 연 뒤 파일이 외부에서 "
                    "변경되었습니다. 덮어쓰지 않았습니다."
                )

        backups: list[Path] = []
        for source_path in changed_paths:
            backup = source_path.with_name(f"{source_path.name}.bak")
            shutil.copy2(source_path, backup)
            backups.append(backup)

        written: list[Path] = []
        try:
            for source_path in changed_paths:
                _write_json_atomic(source_path, outputs[source_path])
                written.append(source_path)
            for source_path in changed_paths:
                if _load_json_object(source_path) != outputs[source_path]:
                    raise DialogueEditorError(
                        f"{source_path}: saved JSON verification differs"
                    )
        except Exception:
            for source_path in written:
                backup = source_path.with_name(f"{source_path.name}.bak")
                shutil.copy2(backup, source_path)
            raise

        for source_path in changed_paths:
            self._source_documents[source_path] = outputs[source_path]
        for index in dirty:
            self.document["entries"][index]["ko"] = self.value(index)
        self._saved_values = list(self._values)
        return tuple(backups)

    def validation_summary(self) -> dict[str, Any]:
        summary = super().validation_summary()
        summary["source_files"] = [
            str(path) for path in self.source_paths
        ]
        summary["excluded_graphics"] = True
        return summary


def filter_entry_indices(
    document: DialogueDocument,
    *,
    query: str = "",
    source_group: str | None = None,
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
        if (source_group is None or document.source_group(index) == source_group)
        and (overflow_indices is None or index in overflow_indices)
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


def _literal_pattern(
    find_text: str,
    *,
    case_sensitive: bool,
) -> re.Pattern[str]:
    if not isinstance(find_text, str) or not find_text:
        raise DialogueEditorError("찾을 용어를 입력하세요.")
    return re.compile(
        re.escape(find_text),
        0 if case_sensitive else re.IGNORECASE,
    )


def literal_match_count(
    text: str,
    find_text: str,
    *,
    case_sensitive: bool = True,
) -> int:
    return len(
        _literal_pattern(
            find_text,
            case_sensitive=case_sensitive,
        ).findall(text)
    )


def plan_literal_replacement(
    document: DialogueDocument,
    *,
    find_text: str,
    replace_text: str,
    indices: Iterable[int] | None = None,
    case_sensitive: bool = True,
) -> tuple[LiteralReplacementChange, ...]:
    """Plan a literal Korean-field-only replacement without mutating data."""
    if not isinstance(replace_text, str):
        raise DialogueEditorError("바꿀 문자열은 문자열이어야 합니다.")
    pattern = _literal_pattern(
        find_text,
        case_sensitive=case_sensitive,
    )
    selected = (
        range(len(document))
        if indices is None
        else tuple(dict.fromkeys(indices))
    )
    changes: list[LiteralReplacementChange] = []
    for index in selected:
        if not isinstance(index, int) or not 0 <= index < len(document):
            raise DialogueEditorError(
                f"찾기/바꾸기 대상 인덱스가 잘못되었습니다: {index!r}"
            )
        before = document.value(index)
        after, count = pattern.subn(lambda _match: replace_text, before)
        if count and after != before:
            changes.append(
                LiteralReplacementChange(
                    index=index,
                    entry_id=document.ids[index],
                    occurrence_count=count,
                    before=before,
                    after=after,
                )
            )
    return tuple(changes)


def apply_literal_replacement(
    document: DialogueDocument,
    changes: Iterable[LiteralReplacementChange],
) -> tuple[LiteralReplacementChange, ...]:
    """Apply an approved replacement plan after checking it is not stale."""
    planned = tuple(changes)
    for change in planned:
        if (
            document.ids[change.index] != change.entry_id
            or document.value(change.index) != change.before
        ):
            raise DialogueEditorError(
                f"{change.entry_id}: 미리보기 이후 내용이 변경되어 "
                "일괄 바꾸기를 적용하지 않았습니다."
            )
    for change in planned:
        document.set_value(change.index, change.after)
    return planned


def undo_literal_replacement(
    document: DialogueDocument,
    changes: Iterable[LiteralReplacementChange],
) -> tuple[LiteralReplacementChange, ...]:
    """Undo one complete replacement batch unless later edits conflict."""
    planned = tuple(changes)
    for change in planned:
        if (
            document.ids[change.index] != change.entry_id
            or document.value(change.index) != change.after
        ):
            raise DialogueEditorError(
                f"{change.entry_id}: 일괄 변경 뒤 추가 수정이 있어 "
                "자동으로 되돌릴 수 없습니다."
            )
    for change in planned:
        document.set_value(change.index, change.before)
    return planned


def format_entry_metadata(
    document: DialogueDocument,
    index: int,
) -> str:
    """Format GUI metadata without depending on a live Tk window."""
    metadata = document.metadata(index)
    limit = document.maximum_glyphs(index)
    layout_profile = document.layout_profile(index)
    measurement = document.layout_measurement(index)
    reason_labels: list[str] = []
    if measurement.glyph_capacity_overflow:
        reason_labels.append(
            f"총 {measurement.visible_glyph_count}/"
            f"{layout_profile.capacity}"
        )
    if measurement.column_overflow_rows:
        rows = ",".join(
            str(row) for row in measurement.column_overflow_rows
        )
        reason_labels.append(
            f"{layout_profile.columns}자 초과 행={rows}"
        )
    if measurement.row_overflow:
        reason_labels.append(
            f"행 {len(measurement.lines)}/{layout_profile.rows}"
        )
    if (
        layout_profile.row_policy == "exact"
        and len(measurement.lines) != layout_profile.rows
    ):
        reason_labels.append(
            f"행 수 보존 {len(measurement.lines)}/{layout_profile.rows}"
        )
    limit_state = ", ".join(reason_labels) if reason_labels else "적합"

    storage = document.storage_slot_measurement(index)
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

    unit_storage = document.unit_storage_measurement(index)
    unit_storage_state = "자료 없음"
    if unit_storage is not None:
        unit_profile = unit_storage.profile
        unit_storage_state = (
            f"u{unit_profile.unit_index:02d} "
            f"{unit_storage.estimated_stream_bytes}/"
            f"{unit_profile.original_stream_capacity_bytes}B "
            + (
                (
                    f"({unit_storage.remaining_bytes}B 여유)"
                    if unit_storage.remaining_bytes
                    else "(정확히 일치)"
                )
                if unit_storage.fits
                else f"({unit_storage.overflow_bytes}B 초과·빌드 차단)"
            )
            + f" [{unit_profile.runtime_validation_label}]"
        )

    source_file = metadata["source_file"]
    source_name = Path(source_file).name if source_file else "?"
    row_policy_label = {
        "exact": "행고정",
        "automatic": "자동줄바꿈",
        "maximum": "최대",
    }[layout_profile.row_policy]
    pixel_widths = ",".join(
        str(width) for width in measurement.line_pixel_widths
    )
    return (
        f"{index + 1}/{len(document)}  "
        f"분류={metadata['source_group']}  "
        f"source={source_name}  "
        f"unit={metadata['unit'] or '?'}  "
        f"class={metadata['classification'] or '?'}  "
        f"status={metadata['status'] or '?'}  "
        f"max_glyphs={limit if limit is not None else '미확정'}  "
        f"profile={layout_profile.columns}×{layout_profile.rows}/"
        f"{row_policy_label}  "
        f"visual_px=[{pixel_widths}]/"
        f"{measurement.pixel_capacity_per_line}  "
        f"layout={limit_state}  "
        f"slot={storage_state}  "
        f"unit_pool={unit_storage_state}"
    )


def _short_entry_label(document: DialogueDocument, index: int) -> str:
    entry_id = document.ids[index]
    group_label = document.source_group_label(index)
    match = re.search(r"/u(\d+)/[^/]+/(ref\d+)$", entry_id)
    if match:
        return (
            f"{index + 1:04d}  {group_label[:6]:<6} "
            f"u{int(match.group(1)):02d}  {match.group(2)}"
        )
    return f"{index + 1:04d}  {group_label[:6]:<6} {entry_id[-34:]}"


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
            self._last_replacement_batch: tuple[
                LiteralReplacementChange, ...
            ] = ()
            self.replace_window: tk.Toplevel | None = None

            root.title("PSX 폰트 번역 편집기")
            root.geometry("1240x820")
            root.minsize(1040, 700)
            root.protocol("WM_DELETE_WINDOW", self.close)

            self.search_var = tk.StringVar()
            self.source_group_var = tk.StringVar(value="전체 폰트 문자열")
            self.source_group_by_label = {
                label: group
                for group, label in self.document.source_groups()
            }
            self.source_group_by_label["전체 폰트 문자열"] = None
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
                text="찾기/바꾸기",
                command=self.open_find_replace,
            ).pack(side=tk.LEFT, padx=(6, 0))
            self.save_as_button = ttk.Button(
                top,
                text="다른 이름으로 저장",
                command=self.save_as,
            )
            self.save_as_button.pack(side=tk.LEFT, padx=(6, 0))
            if not self.document.supports_save_as:
                self.save_as_button.configure(state=tk.DISABLED)

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

            source_filter = ttk.Frame(left)
            source_filter.pack(fill=tk.X, pady=(0, 6))
            ttk.Label(source_filter, text="분류").pack(side=tk.LEFT)
            self.source_group_combo = ttk.Combobox(
                source_filter,
                state="readonly",
                textvariable=self.source_group_var,
                values=(
                    "전체 폰트 문자열",
                    *[
                        label
                        for _group, label in self.document.source_groups()
                    ],
                ),
            )
            self.source_group_combo.pack(
                side=tk.LEFT,
                fill=tk.X,
                expand=True,
                padx=(6, 0),
            )
            self.source_group_combo.bind(
                "<<ComboboxSelected>>",
                lambda _event: self.refresh_filter(),
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
            self.ko_frame = ttk.LabelFrame(
                text_pane,
                text=f"한국어 편집 — {document.editable_field}",
                padding=6,
            )
            text_pane.add(jp_frame, weight=1)
            text_pane.add(self.ko_frame, weight=1)

            self.jp_text = tk.Text(
                jp_frame,
                height=4,
                wrap=tk.WORD,
                state=tk.DISABLED,
                font=("Apple SD Gothic Neo", 15),
            )
            self.jp_text.pack(fill=tk.BOTH, expand=True)

            self.ko_text = tk.Text(
                self.ko_frame,
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

            self.preview_frame = ttk.LabelFrame(
                right,
                text="17×3 논리 셀 + 반각 폭 미리보기 — 자형은 참고용",
                padding=8,
            )
            self.preview_frame.pack(fill=tk.X)
            ttk.Label(
                self.preview_frame,
                textvariable=self.preview_control_var,
            ).pack(anchor=tk.W, pady=(0, 3))
            ttk.Label(
                self.preview_frame,
                textvariable=self.counter_var,
            ).pack(anchor=tk.W, pady=(0, 5))
            self.cell_size = 30
            self.preview_pixel_scale = 2
            self.canvas_margin = 28
            self.canvas_marker_width = 82
            self.preview_canvas = tk.Canvas(
                self.preview_frame,
                width=(
                    self.canvas_margin
                    + COLUMNS
                    * FULL_GLYPH_ADVANCE_PX
                    * self.preview_pixel_scale
                    + self.canvas_marker_width
                    + 2
                ),
                height=ROWS * self.cell_size + 2,
                background="#163b71",
                highlightthickness=0,
            )
            self.preview_canvas.pack(anchor=tk.W)
            ttk.Label(
                self.preview_frame,
                text=(
                    "공백·! ( ) , . ?는 8px, 그 외는 14px입니다. "
                    "17 논리 글리프 자동 행 전환과 제어토큰은 그대로입니다."
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
            for sequence in ("<Command-Option-f>", "<Control-h>"):
                self.root.bind(
                    sequence,
                    lambda _event: self.open_find_replace(),
                )
            self.root.bind("<Alt-Left>", lambda _event: self.previous())
            self.root.bind("<Alt-Right>", lambda _event: self.next())

        def focus_search(self, _event: object = None) -> str:
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, tk.END)
            return "break"

        def open_find_replace(self) -> str:
            if (
                self.replace_window is not None
                and self.replace_window.winfo_exists()
            ):
                self.replace_window.deiconify()
                self.replace_window.lift()
                self.replace_find_entry.focus_set()
                return "break"

            window = tk.Toplevel(self.root)
            self.replace_window = window
            window.title("용어 찾기/바꾸기")
            window.geometry("760x470")
            window.minsize(640, 410)
            window.transient(self.root)

            self.replace_find_var = tk.StringVar()
            self.replace_with_var = tk.StringVar()
            self.replace_scope_var = tk.StringVar(
                value=self.source_group_var.get()
            )
            self.replace_case_var = tk.BooleanVar(value=True)
            self.replace_summary_var = tk.StringVar(
                value=(
                    "미리보기 후 ‘모두 바꾸기’를 누르면 "
                    "적용 전 확인 창이 나타납니다."
                )
            )

            outer = ttk.Frame(window, padding=12)
            outer.pack(fill=tk.BOTH, expand=True)
            ttk.Label(outer, text="찾을 용어").grid(
                row=0,
                column=0,
                sticky=tk.W,
            )
            self.replace_find_entry = ttk.Entry(
                outer,
                textvariable=self.replace_find_var,
            )
            self.replace_find_entry.grid(
                row=0,
                column=1,
                sticky=tk.EW,
                padx=(8, 0),
            )
            ttk.Label(outer, text="바꿀 용어").grid(
                row=1,
                column=0,
                sticky=tk.W,
                pady=(8, 0),
            )
            ttk.Entry(
                outer,
                textvariable=self.replace_with_var,
            ).grid(
                row=1,
                column=1,
                sticky=tk.EW,
                padx=(8, 0),
                pady=(8, 0),
            )
            options = ttk.Frame(outer)
            options.grid(
                row=2,
                column=0,
                columnspan=2,
                sticky=tk.EW,
                pady=(10, 8),
            )
            ttk.Label(options, text="범위").pack(side=tk.LEFT)
            ttk.Combobox(
                options,
                state="readonly",
                width=22,
                textvariable=self.replace_scope_var,
                values=(
                    "전체 폰트 문자열",
                    *[
                        label
                        for _group, label
                        in self.document.source_groups()
                    ],
                ),
            ).pack(side=tk.LEFT, padx=(6, 12))
            ttk.Checkbutton(
                options,
                text="대소문자 구분",
                variable=self.replace_case_var,
            ).pack(side=tk.LEFT)

            buttons = ttk.Frame(outer)
            buttons.grid(
                row=3,
                column=0,
                columnspan=2,
                sticky=tk.EW,
                pady=(0, 8),
            )
            ttk.Button(
                buttons,
                text="다음 항목 찾기",
                command=self.find_next_replacement_term,
            ).pack(side=tk.LEFT)
            ttk.Button(
                buttons,
                text="대상 미리보기",
                command=self.preview_literal_replacement,
            ).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Button(
                buttons,
                text="현재 항목에서 모두 바꾸기",
                command=self.replace_literal_in_current_entry,
            ).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Button(
                buttons,
                text="모두 바꾸기",
                command=self.replace_literal_in_scope,
            ).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Button(
                buttons,
                text="방금 일괄 변경 취소",
                command=self.undo_last_literal_replacement,
            ).pack(side=tk.RIGHT)

            self.replace_preview = tk.Text(
                outer,
                height=13,
                wrap=tk.WORD,
                state=tk.DISABLED,
                font=("Menlo", 11),
                padx=6,
                pady=6,
            )
            self.replace_preview.grid(
                row=4,
                column=0,
                columnspan=2,
                sticky=tk.NSEW,
            )
            ttk.Label(
                outer,
                textvariable=self.replace_summary_var,
                relief=tk.SUNKEN,
                anchor=tk.W,
                padding=(6, 3),
            ).grid(
                row=5,
                column=0,
                columnspan=2,
                sticky=tk.EW,
                pady=(8, 0),
            )
            outer.columnconfigure(1, weight=1)
            outer.rowconfigure(4, weight=1)

            def close_window() -> None:
                window.destroy()
                self.replace_window = None

            window.protocol("WM_DELETE_WINDOW", close_window)
            window.bind("<Escape>", lambda _event: close_window())
            self.replace_find_entry.focus_set()
            return "break"

        def _replacement_scope_indices(self) -> tuple[int, ...]:
            label = self.replace_scope_var.get()
            group = self.source_group_by_label.get(label)
            if group is None:
                return tuple(range(len(self.document)))
            return tuple(
                index
                for index in range(len(self.document))
                if self.document.source_group(index) == group
            )

        def _planned_literal_replacement(
            self,
            *,
            indices: Iterable[int] | None = None,
        ) -> tuple[LiteralReplacementChange, ...]:
            self.commit_current()
            return plan_literal_replacement(
                self.document,
                find_text=self.replace_find_var.get(),
                replace_text=self.replace_with_var.get(),
                indices=(
                    self._replacement_scope_indices()
                    if indices is None
                    else indices
                ),
                case_sensitive=self.replace_case_var.get(),
            )

        def _show_replacement_preview(
            self,
            changes: tuple[LiteralReplacementChange, ...],
        ) -> None:
            widget = self.replace_preview
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            total = sum(change.occurrence_count for change in changes)
            if not changes:
                widget.insert("1.0", "변경될 항목이 없습니다.")
            else:
                for change in changes[:30]:
                    widget.insert(
                        tk.END,
                        (
                            f"{change.entry_id} "
                            f"({change.occurrence_count}회)\n"
                            f"  전: {change.before.replace(chr(10), ' ↵ ')}\n"
                            f"  후: {change.after.replace(chr(10), ' ↵ ')}\n\n"
                        ),
                    )
                if len(changes) > 30:
                    widget.insert(
                        tk.END,
                        f"… 나머지 {len(changes) - 30}개 항목\n",
                    )
            widget.configure(state=tk.DISABLED)
            self.replace_summary_var.set(
                f"범위: {self.replace_scope_var.get()} · "
                f"대상 {len(changes)}개 항목 · 실제 치환 {total}회"
            )

        def preview_literal_replacement(self) -> None:
            try:
                changes = self._planned_literal_replacement()
            except DialogueEditorError as error:
                messagebox.showwarning("미리보기 불가", str(error))
                return
            self._show_replacement_preview(changes)

        def _highlight_literal_in_editor(self, find_text: str) -> None:
            self.ko_text.tag_remove("replacement_find", "1.0", tk.END)
            pattern = _literal_pattern(
                find_text,
                case_sensitive=self.replace_case_var.get(),
            )
            match = pattern.search(self.current_text())
            if match is None:
                return
            self.ko_text.tag_configure(
                "replacement_find",
                background="#ffe166",
                foreground="#111111",
            )
            start = f"1.0+{match.start()}c"
            end = f"1.0+{match.end()}c"
            self.ko_text.tag_add("replacement_find", start, end)
            self.ko_text.see(start)

        def find_next_replacement_term(self) -> None:
            try:
                pattern = _literal_pattern(
                    self.replace_find_var.get(),
                    case_sensitive=self.replace_case_var.get(),
                )
            except DialogueEditorError as error:
                messagebox.showwarning("찾기 불가", str(error))
                return
            scope = self._replacement_scope_indices()
            if not scope:
                messagebox.showinfo("찾기", "선택한 범위가 비어 있습니다.")
                return
            current = self.current_index
            start = (
                scope.index(current) + 1
                if current in scope
                else 0
            )
            ordered = (*scope[start:], *scope[:start])
            target = next(
                (
                    index
                    for index in ordered
                    if pattern.search(self.document.value(index))
                    is not None
                ),
                None,
            )
            if target is None:
                messagebox.showinfo(
                    "찾기",
                    "선택한 범위에서 용어를 찾지 못했습니다.",
                )
                return
            self.select_document_index(target)
            self._highlight_literal_in_editor(self.replace_find_var.get())
            self.replace_summary_var.set(
                f"찾음: {self.document.ids[target]}"
            )

        def _refresh_after_literal_replacement(self) -> None:
            current = self.current_index
            if current is not None:
                self._loading_editor = True
                try:
                    self.ko_text.delete("1.0", tk.END)
                    self.ko_text.insert(
                        "1.0",
                        self.document.value(current),
                    )
                    self.ko_text.edit_modified(False)
                finally:
                    self._loading_editor = False
            self.refresh_filter()
            if current is not None:
                self.select_document_index(current)
            self.update_title()

        def replace_literal_in_current_entry(self) -> None:
            if self.current_index is None:
                return
            try:
                changes = self._planned_literal_replacement(
                    indices=(self.current_index,),
                )
                if not changes:
                    messagebox.showinfo(
                        "현재 항목 바꾸기",
                        "현재 항목에서 변경할 용어를 찾지 못했습니다.",
                    )
                    return
                applied = apply_literal_replacement(
                    self.document,
                    changes,
                )
            except DialogueEditorError as error:
                messagebox.showwarning("바꾸기 불가", str(error))
                return
            self._last_replacement_batch = applied
            self._show_replacement_preview(applied)
            self._refresh_after_literal_replacement()
            self.message_var.set(
                f"현재 항목에서 "
                f"{sum(change.occurrence_count for change in applied)}회 "
                "바꿨습니다. 아직 저장하지 않았습니다."
            )

        def replace_literal_in_scope(self) -> None:
            try:
                changes = self._planned_literal_replacement()
            except DialogueEditorError as error:
                messagebox.showwarning("일괄 바꾸기 불가", str(error))
                return
            self._show_replacement_preview(changes)
            if not changes:
                messagebox.showinfo(
                    "모두 바꾸기",
                    "선택한 범위에서 변경할 용어를 찾지 못했습니다.",
                )
                return
            total = sum(change.occurrence_count for change in changes)
            sample = "\n".join(
                f"• {change.entry_id}"
                for change in changes[:6]
            )
            if len(changes) > 6:
                sample += f"\n• 외 {len(changes) - 6}개 항목"
            if not messagebox.askyesno(
                "일괄 변경 승인",
                (
                    f"찾기: {self.replace_find_var.get()!r}\n"
                    f"바꾸기: {self.replace_with_var.get()!r}\n"
                    f"범위: {self.replace_scope_var.get()}\n"
                    f"대상: {len(changes)}개 항목 / {total}회\n\n"
                    f"{sample}\n\n"
                    "한국어 편집 필드만 변경합니다. 적용 후 저장 전까지 "
                    "‘방금 일괄 변경 취소’로 되돌릴 수 있습니다.\n"
                    "이 범위와 규칙으로 일괄 변경할까요?"
                ),
            ):
                return
            try:
                applied = apply_literal_replacement(
                    self.document,
                    changes,
                )
            except DialogueEditorError as error:
                messagebox.showerror("일괄 변경 실패", str(error))
                return
            self._last_replacement_batch = applied
            self._refresh_after_literal_replacement()
            self.message_var.set(
                f"일괄 변경: {len(applied)}개 항목, {total}회. "
                "아직 저장하지 않았습니다."
            )

        def undo_last_literal_replacement(self) -> None:
            if not self._last_replacement_batch:
                messagebox.showinfo(
                    "일괄 변경 취소",
                    "되돌릴 일괄 변경이 없습니다.",
                )
                return
            try:
                undone = undo_literal_replacement(
                    self.document,
                    self._last_replacement_batch,
                )
            except DialogueEditorError as error:
                messagebox.showwarning("자동 취소 불가", str(error))
                return
            total = sum(change.occurrence_count for change in undone)
            self._last_replacement_batch = ()
            self._refresh_after_literal_replacement()
            self.replace_summary_var.set(
                f"방금 일괄 변경을 취소했습니다: "
                f"{len(undone)}개 항목 / {total}회"
            )
            self.message_var.set(
                "방금 일괄 변경을 취소했습니다."
            )

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
                source_group=self.source_group_by_label.get(
                    self.source_group_var.get()
                ),
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
                f"{self.source_group_var.get()} · "
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
                profile = self.document.layout_profile(index)
                self.ko_frame.configure(
                    text=(
                        f"한국어 편집 — "
                        f"{self.document.source_group_label(index)} · "
                        f"{profile.label}"
                    )
                )
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
            self.message_var.set(
                "한국어 문자열만 편집할 수 있으며 저장 시 원본 JSON의 "
                "해당 필드로 돌아갑니다."
            )
            self.update_title()

        def update_control_view(self, index: int) -> None:
            widget = self.control_text
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            context = self.document.control_context(index)
            if context is None:
                widget.insert(
                    "1.0",
                    "이 항목에는 개별 표시 스트림 제어 셸이 없거나, "
                    "여러 편집 구간이 하나의 스트림을 공유합니다.",
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
            self.meta_var.set(
                format_entry_metadata(self.document, index)
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
            measurement = self.document.layout_measurement(
                self.current_index
            )
            if self.document.layout_policy_violated(self.current_index):
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
            target = self.save_target or self.document.display_path
            dirty = "*" if self.document.dirty else ""
            self.root.title(f"{dirty}PSX 폰트 번역 편집기 — {target.name}")
            if self.document.workspace_mode:
                source_count = len(
                    getattr(self.document, "source_paths", ())
                )
                self.file_var.set(
                    f"{target}  |  원본 JSON {source_count}개  |  "
                    f"수정 {len(self.document.dirty_indices)}건"
                )
            else:
                self.file_var.set(
                    f"{target}  |  수정 "
                    f"{len(self.document.dirty_indices)}건"
                )

        def update_preview(self) -> None:
            if self.current_index is None:
                return
            profile = self.document.layout_profile(self.current_index)
            measurement = self.document.layout_measurement(
                self.current_index,
                self.current_text(),
            )
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
                (
                    f"{index + 1}행 {width}/{profile.columns}글리프 "
                    f"· {measurement.line_pixel_widths[index]}/"
                    f"{measurement.pixel_capacity_per_line}px"
                )
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
            if (
                profile.row_policy == "exact"
                and len(measurement.lines) != profile.rows
            ):
                reason_parts.append(f"행 수 {profile.rows} 고정")
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
                + (
                    f"  |  표시 {measurement.visible_glyph_count}/"
                    f"{profile.capacity}"
                )
                + f"  |  {state}"
                + short_line_note
            )

            canvas = self.preview_canvas
            canvas_width = (
                self.canvas_margin
                + profile.columns
                * FULL_GLYPH_ADVANCE_PX
                * self.preview_pixel_scale
                + self.canvas_marker_width
                + 2
            )
            canvas_height = profile.rows * self.cell_size + 2
            canvas.configure(
                width=canvas_width,
                height=canvas_height,
            )
            self.preview_frame.configure(
                text=(
                    f"{profile.columns}×{profile.rows} {profile.label} "
                    f"미리보기 — "
                    + (
                        "행 수 고정 · "
                        if profile.row_policy == "exact"
                        else (
                            "런타임 자동 줄바꿈 · "
                            if profile.row_policy == "automatic"
                            else ""
                        )
                    )
                    + "반각 8px/기본 14px · 자형은 참고용"
                )
            )
            canvas.delete("all")
            normal_grid = "#4e75a7"
            overflow_grid = "#f05b63"
            align_grid = "#a85d00"
            align_fill = "#4c3b22"
            automatic_grid = "#55708c"
            automatic_fill = "#263f59"
            normal_fill = "#163b71"
            glyph_fill = "#214c82"
            pixel_scale = self.preview_pixel_scale
            full_advance = FULL_GLYPH_ADVANCE_PX * pixel_scale
            grid_end = (
                self.canvas_margin + profile.columns * full_advance
            )
            normalized_text = self.current_text().replace(
                "\r\n", "\n"
            ).replace("\r", "\n")
            stored_newlines = "\n" in normalized_text
            for row in range(profile.rows):
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
                row_overflow = len(line) > profile.columns
                has_next_line = row < len(measurement.lines) - 1
                automatic_wrap = (
                    has_next_line
                    and profile.row_policy == "automatic"
                    and not stored_newlines
                )
                invalid_manual_wrap = (
                    has_next_line
                    and profile.row_policy == "automatic"
                    and stored_newlines
                )
                explicit_align = (
                    has_next_line and profile.row_policy != "automatic"
                )
                for column in range(profile.columns):
                    left = self.canvas_margin + column * full_advance
                    top = row * self.cell_size
                    if row_overflow:
                        cell_outline = overflow_grid
                        cell_width = 2
                    else:
                        cell_outline = normal_grid
                        cell_width = 1
                    canvas.create_rectangle(
                        left,
                        top,
                        left + full_advance,
                        top + self.cell_size,
                        outline=cell_outline,
                        fill=normal_fill,
                        width=cell_width,
                    )

                cursor = self.canvas_margin
                for character_index, character in enumerate(line):
                    advance = glyph_advance_px(character) * pixel_scale
                    outline = (
                        overflow_grid
                        if character_index >= profile.columns
                        else normal_grid
                    )
                    canvas.create_rectangle(
                        cursor,
                        row * self.cell_size,
                        cursor + advance,
                        (row + 1) * self.cell_size,
                        outline=outline,
                        fill=glyph_fill,
                        width=2 if row_overflow else 1,
                    )
                    if character != " ":
                        canvas.create_text(
                            cursor + advance // 2,
                            row * self.cell_size + self.cell_size // 2,
                            text=character,
                            fill="#ffffff",
                            font=(self.preview_font, 15),
                        )
                    cursor += advance

                if has_next_line and cursor < grid_end:
                    tail_outline = (
                        align_grid
                        if explicit_align
                        else automatic_grid
                    )
                    tail_fill = (
                        align_fill
                        if explicit_align
                        else automatic_fill
                    )
                    canvas.create_rectangle(
                        cursor,
                        row * self.cell_size,
                        grid_end,
                        (row + 1) * self.cell_size,
                        outline=tail_outline,
                        fill=tail_fill,
                        width=2,
                    )
                if has_next_line:
                    if explicit_align:
                        marker_text = "↵ FFFB"
                        marker_color = "#ffb34d"
                    elif automatic_wrap:
                        marker_text = "↵ AUTO 17"
                        marker_color = "#a9c4e8"
                    elif invalid_manual_wrap:
                        marker_text = "⚠ 수동 LF"
                        marker_color = overflow_grid
                    else:
                        marker_text = "↵"
                        marker_color = "#a9c4e8"
                    canvas.create_text(
                        grid_end + 7,
                        row * self.cell_size + self.cell_size // 2,
                        text=marker_text,
                        anchor=tk.W,
                        fill=marker_color,
                        font=("Menlo", 9, "bold"),
                    )
            if measurement.row_overflow:
                canvas.create_rectangle(
                    self.canvas_margin,
                    0,
                        (
                            self.canvas_margin
                            + profile.columns * full_advance
                        ),
                    profile.rows * self.cell_size,
                    outline=overflow_grid,
                    width=3,
                )

        def apply_conservative_wrap(self) -> None:
            if self.current_index is None:
                return
            profile = self.document.layout_profile(self.current_index)
            if profile.row_policy == "exact":
                messagebox.showwarning(
                    "자동 배치 제외",
                    f"이 항목은 {profile.rows}행 위치를 정확히 보존해야 "
                    "하므로 자동 배치를 적용하지 않습니다.",
                )
                return
            if profile.row_policy == "automatic":
                messagebox.showwarning(
                    "수동 줄바꿈 제외",
                    "이 항목은 게임이 자동으로 줄을 바꾸며, 저장된 수동 "
                    "줄바꿈은 제어코드 위치를 바꾸므로 적용하지 않습니다.",
                )
                return
            before = self.current_text()
            try:
                after = conservative_word_wrap(
                    before,
                    columns=profile.columns,
                    rows=profile.rows,
                )
            except DialogueEditorError as error:
                messagebox.showwarning("자동 배치 불가", str(error))
                return
            if after == before:
                self.message_var.set("현재 줄바꿈이 이미 선택 결과와 같습니다.")
                return
            before_widths = measure_layout(
                before,
                columns=profile.columns,
                rows=profile.rows,
            ).line_widths
            after_widths = measure_layout(
                after,
                columns=profile.columns,
                rows=profile.rows,
            ).line_widths
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
            target = self.save_target or self.document.display_path
            modified = len(self.document.dirty_indices)
            try:
                backup = self.document.save(
                    None if self.document.workspace_mode else target
                )
            except (OSError, DialogueEditorError) as error:
                messagebox.showerror("저장 실패", str(error))
                return "break"
            if not self.document.workspace_mode:
                self.save_target = target
            self.update_title()
            if isinstance(backup, tuple):
                backup_text = (
                    "\n백업:\n"
                    + "\n".join(str(path) for path in backup)
                    if backup
                    else ""
                )
            else:
                backup_text = f"\n백업: {backup}" if backup else ""
            messagebox.showinfo(
                "저장 완료",
                (
                    f"{target}\n수정 엔트리: {modified}건"
                    f"{backup_text}"
                ),
            )
            self.message_var.set(f"저장 완료: {target}")
            return "break"

        def save_as(self) -> str:
            self.commit_current()
            if not self.document.supports_save_as:
                messagebox.showwarning(
                    "다른 이름으로 저장 불가",
                    "통합 작업공간은 각 원본 번역 JSON에 안전하게 "
                    "되돌려 저장합니다.",
                )
                return "break"
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
        help=(
            "single dialogue JSON to edit; omitted means the complete "
            "font-translation workspace"
        ),
    )
    parser.add_argument(
        "--all-font-text",
        action="store_true",
        help=(
            "load the default complete font-translation workspace "
            "(this is already the default when --input is omitted)"
        ),
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
        "--pointerless-translation",
        type=Path,
        default=DEFAULT_POINTERLESS_TRANSLATION,
    )
    parser.add_argument(
        "--pointerless-workset",
        type=Path,
        default=DEFAULT_POINTERLESS_WORKSET,
    )
    parser.add_argument(
        "--special-translation",
        type=Path,
        default=DEFAULT_SPECIAL_TRANSLATION,
    )
    parser.add_argument(
        "--special-workset",
        type=Path,
        default=DEFAULT_SPECIAL_WORKSET,
    )
    parser.add_argument(
        "--unindexed-translation",
        type=Path,
        default=DEFAULT_UNINDEXED_TRANSLATION,
    )
    parser.add_argument(
        "--unindexed-workset",
        type=Path,
        default=DEFAULT_UNINDEXED_WORKSET,
    )
    parser.add_argument(
        "--ui-translation",
        type=Path,
        default=DEFAULT_UI_TRANSLATION,
    )
    parser.add_argument(
        "--ui-workset",
        type=Path,
        default=DEFAULT_UI_WORKSET,
    )
    parser.add_argument(
        "--character-names",
        type=Path,
        default=DEFAULT_CHARACTER_NAMES,
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
        if args.all_font_text and args.input is not None:
            raise DialogueEditorError(
                "--all-font-text and --input cannot be used together"
            )
        workspace_mode = args.input is None or args.all_font_text
        if workspace_mode:
            if args.output is not None:
                raise DialogueEditorError(
                    "--output is unavailable for the complete workspace; "
                    "edits return to their canonical source JSON"
                )
            if args.editable_field is not None:
                raise DialogueEditorError(
                    "--editable-field is only available with --input"
                )
            document = FontTranslationWorkspaceDocument.load(
                dialogue_translation_path=DEFAULT_INPUT,
                dialogue_workset_path=args.workset,
                safe_slots_path=args.safe_slots,
                pointerless_translation_path=args.pointerless_translation,
                pointerless_workset_path=args.pointerless_workset,
                special_translation_path=args.special_translation,
                special_workset_path=args.special_workset,
                unindexed_translation_path=args.unindexed_translation,
                unindexed_workset_path=args.unindexed_workset,
                ui_translation_path=args.ui_translation,
                ui_workset_path=args.ui_workset,
                character_names_path=args.character_names,
            )
        else:
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
