#!/usr/bin/env python3
"""Render one overview from the eleven verified reassembled chapter images."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHAPTER_SIZE = (320, 240)
GRID_COLUMNS = 3
GRID_ROWS = 4
LABEL_HEIGHT = 30
PURPLE = (255, 0, 255, 255)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_verified_entries(file_build_dir: Path) -> list[dict[str, Any]]:
    manifest_path = file_build_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("chapter_graphics", {}).get("entries")
    if not isinstance(entries, list) or len(entries) != 11:
        raise ValueError("file build does not contain eleven chapter graphics entries")
    if [int(entry["unit"]) for entry in entries] != list(range(24, 35)):
        raise ValueError("chapter overview entries are not ordered as units 24..34")
    for entry in entries:
        preview = entry.get("preview")
        if not isinstance(preview, dict):
            raise ValueError(f"{entry.get('asset_id')}: missing inserted preview record")
        path = Path(str(preview.get("path", "")))
        if not path.is_file():
            raise FileNotFoundError(f"missing inserted preview: {path}")
        if sha256_file(path) != preview.get("sha256"):
            raise ValueError(f"{entry['asset_id']}: inserted preview hash differs")
    return entries


def render_overview(entries: list[dict[str, Any]], output_path: Path) -> Path:
    if len(entries) != 11:
        raise ValueError("chapter overview requires exactly eleven entries")
    cell_width = CHAPTER_SIZE[0]
    cell_height = CHAPTER_SIZE[1] + LABEL_HEIGHT
    overview = Image.new(
        "RGB",
        (GRID_COLUMNS * cell_width, GRID_ROWS * cell_height),
        (20, 20, 22),
    )
    draw = ImageDraw.Draw(overview)
    for index, entry in enumerate(entries):
        preview_path = Path(entry["preview"]["path"])
        with Image.open(preview_path) as source:
            if source.size != CHAPTER_SIZE:
                raise ValueError(
                    f"{entry['asset_id']}: inserted preview is not 320x240"
                )
            rgba = source.convert("RGBA")
        visible = Image.new("RGBA", CHAPTER_SIZE, PURPLE)
        visible.alpha_composite(rgba)
        column = index % GRID_COLUMNS
        row = index // GRID_COLUMNS
        x = column * cell_width
        y = row * cell_height
        overview.paste(visible.convert("RGB"), (x, y))
        draw.text(
            (x + 5, y + CHAPTER_SIZE[1] + 7),
            f"{index + 1:02d}  {entry['asset_id']}",
            fill=(240, 240, 240),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    overview.save(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file-build-dir",
        type=Path,
        default=PROJECT_ROOT / "work/build/integrated-2026-08-04-13-chapters",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_ROOT
            / "work/graphics/title-chapter/chapters-assembled-overview-inserted.png"
        ),
    )
    args = parser.parse_args()
    entries = load_verified_entries(args.file_build_dir)
    output = render_overview(entries, args.output)
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "sha256": sha256_file(output),
                "chapter_count": len(entries),
                "source": str((args.file_build_dir / "manifest.json").resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
