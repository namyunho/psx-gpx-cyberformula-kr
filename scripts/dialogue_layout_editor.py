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
DEFAULT_INPUT = Path(
    "work/translations/disc1-dialogue-ko-candidate.json"
)
EDITABLE_FIELD_PATTERN = re.compile(r"^entries\[\]\.([A-Za-z_][A-Za-z0-9_]*)$")
WORD_PATTERN = re.compile(r"\S+")
NAME_EXPANSIONS = {
    "{name:surname}": "시바",
    "{name:given}": "세이치로",
}
PUNCTUATION_ENDINGS = frozenset("…‥.!?。！？,，:：;；)]}）］】」』’”'")


class DialogueEditorError(ValueError):
    """Raised when an input document or requested layout is invalid."""


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
        self._saved_values = list(values)
        self._values = list(values)

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        editable_field: str | None = None,
    ) -> "DialogueDocument":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DialogueEditorError(f"{path}: {error}") from error
        return cls(path, document, editable_field=editable_field)

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
        unit = entry.get("unit_index")
        if unit is None:
            source = entry.get("source")
            if isinstance(source, dict):
                unit = source.get("unit_index")
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
        return "\n".join(
            (self.ids[index], self.japanese(index), self.value(index))
        ).casefold()

    def layout_overflow_indices(self) -> tuple[int, ...]:
        return tuple(
            index
            for index, value in enumerate(self._values)
            if measure_layout(value).exceeds_limits
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
        glyph_capacity_overflow = 0
        line_width_overflow = 0
        row_count_overflow = 0
        empty = 0
        for value in self._values:
            measurement = measure_layout(value)
            if not value.strip():
                empty += 1
            if measurement.glyph_capacity_overflow:
                glyph_capacity_overflow += 1
            if measurement.column_overflow_rows:
                line_width_overflow += 1
            if measurement.row_overflow:
                row_count_overflow += 1
            if measurement.fits:
                fits += 1
            else:
                overflow += 1
        return {
            "path": str(self.path),
            "editable_field": self.editable_field,
            "entries": len(self),
            "fits_17x3": fits,
            "layout_overflow": overflow,
            "glyph_capacity_overflow": glyph_capacity_overflow,
            "line_width_overflow": line_width_overflow,
            "row_count_overflow": row_count_overflow,
            "empty": empty,
            "dirty": len(self.dirty_indices),
        }


def filter_entry_indices(
    document: DialogueDocument,
    *,
    query: str = "",
    overflow_only: bool = False,
) -> list[int]:
    """Return stable document indices matching search and layout filters."""
    normalized_query = query.strip().casefold()
    overflow_indices = (
        set(document.layout_overflow_indices())
        if overflow_only
        else None
    )
    return [
        index
        for index in range(len(document))
        if (overflow_indices is None or index in overflow_indices)
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
            self._loading_editor = False

            root.title("PSX 대사 17×3 편집기")
            root.geometry("1180x760")
            root.minsize(980, 660)
            root.protocol("WM_DELETE_WINDOW", self.close)

            self.search_var = tk.StringVar()
            self.overflow_only_var = tk.BooleanVar(value=False)
            self.filter_summary_var = tk.StringVar()
            self.id_var = tk.StringVar()
            self.meta_var = tk.StringVar()
            self.counter_var = tk.StringVar()
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
            ttk.Button(
                filter_bar,
                text="목록 갱신",
                command=self.refresh_filter,
            ).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Label(
                filter_bar,
                textvariable=self.filter_summary_var,
            ).pack(side=tk.RIGHT)

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
                textvariable=self.counter_var,
            ).pack(anchor=tk.W, pady=(0, 5))
            self.cell_size = 30
            self.canvas_margin = 28
            self.preview_canvas = tk.Canvas(
                preview,
                width=self.canvas_margin + COLUMNS * self.cell_size + 2,
                height=ROWS * self.cell_size + 2,
                background="#163b71",
                highlightthickness=0,
            )
            self.preview_canvas.pack(anchor=tk.W)
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
            self.filtered_indices = filter_entry_indices(
                self.document,
                query=self.search_var.get(),
                overflow_only=self.overflow_only_var.get(),
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
                self.entry_list.insert(
                    tk.END,
                    f"{marker}{overflow_marker} "
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
            self.update_preview()
            self.message_var.set("한국어 필드만 편집할 수 있습니다.")
            self.update_title()

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
            self.meta_var.set(
                f"{index + 1}/{len(self.document)}  "
                f"unit={metadata['unit'] or '?'}  "
                f"class={metadata['classification'] or '?'}  "
                f"status={metadata['status'] or '?'}  "
                f"max_glyphs={limit if limit is not None else '미확정'}  "
                f"layout={limit_state}"
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
            self.update_current_overflow_state()
            self.update_title()

        def update_current_overflow_state(self) -> None:
            if self.current_index is None:
                return
            measurement = measure_layout(
                self.document.value(self.current_index)
            )
            if measurement.exceeds_limits:
                self.overflow_indices.add(self.current_index)
            else:
                self.overflow_indices.discard(self.current_index)
            self.update_metadata(self.current_index)
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
                self.entry_list.delete(position)
                self.entry_list.insert(
                    position,
                    f"{marker}{overflow_marker} "
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
            state = (
                "적합"
                if not reason_parts
                else "초과: " + ", ".join(reason_parts)
            )
            self.counter_var.set(
                " · ".join(width_parts)
                + f"  |  표시 {measurement.visible_glyph_count}/{CAPACITY}"
                + f"  |  {state}"
            )

            canvas = self.preview_canvas
            canvas.delete("all")
            normal_grid = "#4e75a7"
            overflow_grid = "#f05b63"
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
                for column in range(COLUMNS):
                    left = self.canvas_margin + column * self.cell_size
                    top = row * self.cell_size
                    canvas.create_rectangle(
                        left,
                        top,
                        left + self.cell_size,
                        top + self.cell_size,
                        outline=overflow_grid if row_overflow else normal_grid,
                        width=2 if row_overflow else 1,
                    )
                    if column < len(line):
                        canvas.create_text(
                            left + self.cell_size // 2,
                            top + self.cell_size // 2,
                            text=line[column],
                            fill="#ffffff",
                            font=(self.preview_font, 15),
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
            self.update_current_overflow_state()
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
            self.update_current_overflow_state()
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
