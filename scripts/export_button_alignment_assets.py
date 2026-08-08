#!/usr/bin/env python3
"""Export exact 1x button-label pixels from an integrated file build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from PIL import Image

try:
    from scripts.build_minigame_graphics_patch import _rect_indices
    from scripts.build_name_origin_graphics_patch import (
        STATE0_ATLAS_OFFSET,
        STATE0_CLUT_OFFSET,
        TARGETS,
        decode_4bpp,
    )
    from scripts.build_save_screen_patch import (
        SAVE_BUTTON_LABELS,
        _get_outside_4bpp_pixel,
    )
    from scripts.psx_vram_render import bgr555_color
except ModuleNotFoundError:
    from build_minigame_graphics_patch import _rect_indices
    from build_name_origin_graphics_patch import (
        STATE0_ATLAS_OFFSET,
        STATE0_CLUT_OFFSET,
        TARGETS,
        decode_4bpp,
    )
    from build_save_screen_patch import (
        SAVE_BUTTON_LABELS,
        _get_outside_4bpp_pixel,
    )
    from psx_vram_render import bgr555_color


NAME_BUTTON_ORDER = (
    "name-ui/hiragana-button",
    "name-ui/katakana-button",
    "name-ui/kanji-button",
    "name-ui/back-button",
    "name-ui/finish-button",
    "name-ui/default-button",
    "name-ui/free-origin-button",
    "name-ui/confirm-button",
    "name-ui/retry-button",
)

OUTSIDE_SAVE_CLUT_OFFSET = 0x3627C
MINIGAME_UNIT1_CLUT_OFFSET = 0x38A20


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _png_palette(colors: list[tuple[int, int, int]]) -> list[int]:
    padded = colors + [(0, 0, 0)] * (256 - len(colors))
    return [channel for color in padded for channel in color]


def _save_indexed(
    path: Path,
    *,
    width: int,
    height: int,
    indices: bytes | list[int],
    colors: list[tuple[int, int, int]],
) -> None:
    if len(indices) != width * height:
        raise ValueError(f"{path.name}: index count differs from dimensions")
    image = Image.frombytes("P", (width, height), bytes(indices))
    image.putpalette(_png_palette(colors))
    image.save(path)


def _save_purple_preview(
    path: Path,
    *,
    width: int,
    height: int,
    indices: bytes | list[int],
    colors: list[tuple[int, int, int]],
) -> None:
    if len(indices) != width * height:
        raise ValueError(f"{path.name}: index count differs from dimensions")
    preview_colors = [(255, 0, 255), *colors[1:]]
    image = Image.new("RGB", (width, height))
    image.putdata([preview_colors[index] for index in indices])
    image.save(path)


def _name_palette(outside: bytes, bank: int = 13) -> list[tuple[int, int, int]]:
    clut_x, clut_y, width, height = struct.unpack_from(
        "<4H", outside, STATE0_CLUT_OFFSET
    )
    del clut_x, clut_y
    if (width, height) != (16, 16) or not 0 <= bank < height:
        raise ValueError("name UI CLUT header or bank differs")
    start = STATE0_CLUT_OFFSET + 8 + bank * width * 2
    words = struct.unpack_from(f"<{width}H", outside, start)
    return [tuple(bgr555_color(word)[:3]) for word in words]


def _clut_palette(
    payload: bytes,
    *,
    offset: int,
    expected_rect: tuple[int, int, int, int],
    bank: int,
) -> list[tuple[int, int, int]]:
    rect = struct.unpack_from("<4H", payload, offset)
    if rect != expected_rect:
        raise ValueError(
            f"CLUT header differs at 0x{offset:X}: {rect} != {expected_rect}"
        )
    _, _, width, height = rect
    if width != 16 or not 0 <= bank < height:
        raise ValueError("requested 4bpp CLUT bank is unavailable")
    start = offset + 8 + bank * width * 2
    words = struct.unpack_from(f"<{width}H", payload, start)
    return [tuple(bgr555_color(word)[:3]) for word in words]


def _full_4bpp_surface(
    payload: bytes,
    *,
    header_offset: int,
    expected_rect: tuple[int, int, int, int],
) -> tuple[int, int, bytes]:
    rect = struct.unpack_from("<4H", payload, header_offset)
    if rect != expected_rect:
        raise ValueError(
            f"4bpp header differs at 0x{header_offset:X}: "
            f"{rect} != {expected_rect}"
        )
    _, _, width_halfwords, height = rect
    width = width_halfwords * 4
    packed_size = width_halfwords * height * 2
    packed = payload[header_offset + 8 : header_offset + 8 + packed_size]
    indices = bytes(decode_4bpp(packed))
    if len(indices) != width * height:
        raise AssertionError("decoded full-atlas index count differs")
    return width, height, indices


def _export_full_asset(
    output_dir: Path,
    *,
    stem: str,
    width: int,
    height: int,
    indices: bytes,
    colors: list[tuple[int, int, int]],
) -> dict[str, Any]:
    indexed_path = output_dir / f"{stem}-indexed-1x.png"
    preview_path = output_dir / f"{stem}-preview-purple-1x.png"
    _save_indexed(
        indexed_path,
        width=width,
        height=height,
        indices=indices,
        colors=colors,
    )
    _save_purple_preview(
        preview_path,
        width=width,
        height=height,
        indices=indices,
        colors=colors,
    )
    return {
        "size": [width, height],
        "indexed": str(indexed_path.resolve()),
        "preview_purple": str(preview_path.resolve()),
        "indices_sha256": sha256_bytes(indices),
    }


def _extract_full_assets(
    outside: bytes, minig3: bytes, output_dir: Path
) -> dict[str, Any]:
    group = output_dir / "full-assets"
    group.mkdir(parents=True, exist_ok=True)

    name_width, name_height, name_indices = _full_4bpp_surface(
        outside,
        header_offset=STATE0_ATLAS_OFFSET,
        expected_rect=(512, 0, 256, 256),
    )
    name = _export_full_asset(
        group,
        stem="name-ui-unit0-child5-atlas",
        width=name_width,
        height=name_height,
        indices=name_indices,
        colors=_name_palette(outside, bank=13),
    )
    name["storage"] = {
        "file": "OUTSIDE.BIN",
        "state": 0,
        "child": 5,
        "header_offset": "0x309C",
        "palette_child": 2,
        "preview_palette_bank": 13,
    }
    name["editable_button_boxes"] = {
        entry_id: list(TARGETS[entry_id]["box"])
        for entry_id in NAME_BUTTON_ORDER
    }

    save_width, save_height, save_indices = _full_4bpp_surface(
        outside,
        header_offset=0x3668C,
        expected_rect=(512, 0, 256, 256),
    )
    save_selected = _export_full_asset(
        group,
        stem="save-unit1-child4-atlas-selected-clut",
        width=save_width,
        height=save_height,
        indices=save_indices,
        colors=_clut_palette(
            outside,
            offset=OUTSIDE_SAVE_CLUT_OFFSET,
            expected_rect=(0, 496, 16, 16),
            bank=4,
        ),
    )
    save_unselected = _export_full_asset(
        group,
        stem="save-unit1-child4-atlas-unselected-clut",
        width=save_width,
        height=save_height,
        indices=save_indices,
        colors=_clut_palette(
            outside,
            offset=OUTSIDE_SAVE_CLUT_OFFSET,
            expected_rect=(0, 496, 16, 16),
            bank=5,
        ),
    )
    save = {
        "size": [save_width, save_height],
        "indices_sha256": sha256_bytes(save_indices),
        "selected_clut": save_selected,
        "unselected_clut": save_unselected,
        "storage": {
            "file": "OUTSIDE.BIN",
            "state": 1,
            "child": 4,
            "header_offset": "0x3668C",
            "palette_child": 2,
            "selected_preview_palette_bank": 4,
            "unselected_preview_palette_bank": 5,
        },
        "editable_button_rects": {
            entry_id: [x, y, width, height]
            for entry_id, _text, x, y, width, height in SAVE_BUTTON_LABELS
        },
    }

    cooking_width, cooking_height, cooking_indices = _full_4bpp_surface(
        minig3,
        header_offset=0x18810,
        expected_rect=(512, 0, 128, 512),
    )
    cooking = _export_full_asset(
        group,
        stem="cooking-unit1-child0-atlas",
        width=cooking_width,
        height=cooking_height,
        indices=cooking_indices,
        colors=_clut_palette(
            minig3,
            offset=MINIGAME_UNIT1_CLUT_OFFSET,
            expected_rect=(0, 496, 16, 16),
            bank=13,
        ),
    )
    cooking["storage"] = {
        "file": "MINI_G3.BIN",
        "state": 1,
        "child": 0,
        "header_offset": "0x18810",
        "palette_child": 2,
        "preview_palette_bank": 13,
    }
    return {"name_ui": name, "save": save, "cooking": cooking}


def _neutral_palette(
    *, foreground_index: int, shadow_index: int
) -> list[tuple[int, int, int]]:
    colors = [(0, 0, 0)] * 16
    colors[foreground_index] = (255, 255, 255)
    colors[shadow_index] = (96, 96, 96)
    return colors


def _extract_name_buttons(
    outside: bytes, output_dir: Path
) -> list[dict[str, Any]]:
    _, _, width_halfwords, height = struct.unpack_from(
        "<4H", outside, STATE0_ATLAS_OFFSET
    )
    width = width_halfwords * 4
    payload_start = STATE0_ATLAS_OFFSET + 8
    payload = outside[
        payload_start : payload_start + width_halfwords * height * 2
    ]
    atlas = decode_4bpp(payload)
    palette = _name_palette(outside)
    group = output_dir / "name-ui"
    group.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    contact_width = max(TARGETS[entry_id]["box"][2] - TARGETS[entry_id]["box"][0] for entry_id in NAME_BUTTON_ORDER)
    contact_indices = [0] * (contact_width * 16 * len(NAME_BUTTON_ORDER))
    for row, entry_id in enumerate(NAME_BUTTON_ORDER):
        x0, y0, x1, y1 = TARGETS[entry_id]["box"]
        target_width = x1 - x0
        target_height = y1 - y0
        indices = [
            atlas[y * width + x]
            for y in range(y0, y1)
            for x in range(x0, x1)
        ]
        stem = entry_id.rsplit("/", 1)[-1]
        indexed_path = group / f"{stem}-indexed-1x.png"
        preview_path = group / f"{stem}-preview-purple-1x.png"
        _save_indexed(
            indexed_path,
            width=target_width,
            height=target_height,
            indices=indices,
            colors=palette,
        )
        _save_purple_preview(
            preview_path,
            width=target_width,
            height=target_height,
            indices=indices,
            colors=palette,
        )
        for py in range(target_height):
            source = py * target_width
            target = (row * 16 + py) * contact_width
            contact_indices[target : target + target_width] = indices[
                source : source + target_width
            ]
        reports.append(
            {
                "id": entry_id,
                "texture_box": [x0, y0, x1, y1],
                "size": [target_width, target_height],
                "indexed": str(indexed_path.resolve()),
                "preview_purple": str(preview_path.resolve()),
                "indices_sha256": sha256_bytes(bytes(indices)),
            }
        )
    _save_indexed(
        output_dir / "name-ui-labels-contact-indexed-1x.png",
        width=contact_width,
        height=16 * len(NAME_BUTTON_ORDER),
        indices=contact_indices,
        colors=palette,
    )
    _save_purple_preview(
        output_dir / "name-ui-labels-contact-preview-purple-1x.png",
        width=contact_width,
        height=16 * len(NAME_BUTTON_ORDER),
        indices=contact_indices,
        colors=palette,
    )
    return reports


def _extract_save_buttons(
    outside: bytes, output_dir: Path
) -> list[dict[str, Any]]:
    palette = _neutral_palette(foreground_index=1, shadow_index=8)
    group = output_dir / "save"
    group.mkdir(parents=True, exist_ok=True)
    contact = [0] * (80 * 16)
    reports: list[dict[str, Any]] = []
    for column, (entry_id, text, x, y, width, height) in enumerate(
        SAVE_BUTTON_LABELS
    ):
        indices = [
            _get_outside_4bpp_pixel(outside, x + px, y + py)
            for py in range(height)
            for px in range(width)
        ]
        indexed_path = group / f"{entry_id}-indexed-1x.png"
        preview_path = group / f"{entry_id}-preview-purple-1x.png"
        _save_indexed(
            indexed_path,
            width=width,
            height=height,
            indices=indices,
            colors=palette,
        )
        _save_purple_preview(
            preview_path,
            width=width,
            height=height,
            indices=indices,
            colors=palette,
        )
        for py in range(height):
            source = py * width
            target = py * 80 + column * 40
            contact[target : target + width] = indices[source : source + width]
        reports.append(
            {
                "id": entry_id,
                "text": text,
                "texture_rect": [x, y, width, height],
                "size": [width, height],
                "indexed": str(indexed_path.resolve()),
                "preview_purple": str(preview_path.resolve()),
                "indices_sha256": sha256_bytes(bytes(indices)),
            }
        )
    _save_indexed(
        output_dir / "save-labels-contact-indexed-1x.png",
        width=80,
        height=16,
        indices=contact,
        colors=palette,
    )
    _save_purple_preview(
        output_dir / "save-labels-contact-preview-purple-1x.png",
        width=80,
        height=16,
        indices=contact,
        colors=palette,
    )
    return reports


def _extract_cooking_buttons(
    minig3: bytes, translation_path: Path, output_dir: Path
) -> list[dict[str, Any]]:
    document = json.loads(translation_path.read_text(encoding="utf-8"))
    entries = document.get("entries")
    if not isinstance(entries, list) or len(entries) != 8:
        raise ValueError("cooking button translation population differs")
    palette = _neutral_palette(foreground_index=10, shadow_index=13)
    group = output_dir / "cooking"
    group.mkdir(parents=True, exist_ok=True)
    contact = [0] * (64 * 16 * len(entries))
    reports: list[dict[str, Any]] = []
    for row, entry in enumerate(entries):
        x, y, width, height = (int(value) for value in entry["texture_rect"])
        indices = list(_rect_indices(minig3, (x, y, width, height)))
        stem = str(entry["id"]).rsplit("/", 1)[-1]
        indexed_path = group / f"{stem}-indexed-1x.png"
        preview_path = group / f"{stem}-preview-purple-1x.png"
        _save_indexed(
            indexed_path,
            width=width,
            height=height,
            indices=indices,
            colors=palette,
        )
        _save_purple_preview(
            preview_path,
            width=width,
            height=height,
            indices=indices,
            colors=palette,
        )
        for py in range(height):
            source = py * width
            target = (row * 16 + py) * 64
            contact[target : target + width] = indices[source : source + width]
        reports.append(
            {
                "id": entry["id"],
                "jp": entry["jp"],
                "ko": entry["ko"],
                "texture_rect": [x, y, width, height],
                "size": [width, height],
                "indexed": str(indexed_path.resolve()),
                "preview_purple": str(preview_path.resolve()),
                "indices_sha256": sha256_bytes(bytes(indices)),
            }
        )
    _save_indexed(
        output_dir / "cooking-labels-contact-indexed-1x.png",
        width=64,
        height=16 * len(entries),
        indices=contact,
        colors=palette,
    )
    _save_purple_preview(
        output_dir / "cooking-labels-contact-preview-purple-1x.png",
        width=64,
        height=16 * len(entries),
        indices=contact,
        colors=palette,
    )
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-build-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--cooking-translation",
        type=Path,
        default=Path("data/translations/disc1-minigame-graphics-ko.json"),
    )
    args = parser.parse_args()

    manifest_path = args.file_build_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outside = (args.file_build_dir / "OUTSIDE.BIN").read_bytes()
    minig3 = (args.file_build_dir / "MINI_G3.BIN").read_bytes()
    for name, payload in (("OUTSIDE.BIN", outside), ("MINI_G3.BIN", minig3)):
        expected = manifest["outputs"][name]["sha256"]
        if sha256_bytes(payload) != expected:
            raise ValueError(f"{name}: file-build hash differs")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "scale": "1x exact source pixels; no resizing or resampling",
        "source": {
            "file_build_manifest": str(manifest_path.resolve()),
            "file_build_manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
            "OUTSIDE.BIN_sha256": sha256_bytes(outside),
            "MINI_G3.BIN_sha256": sha256_bytes(minig3),
        },
        "format": {
            "indexed": "mode P; pixel values preserve the 4bpp indices 0..15",
            "preview_purple": "RGB view only; index 0 is shown as #FF00FF",
            "editing_input": (
                "edit only full-assets/*-indexed-1x.png without resizing; "
                "the cropped files are reference-only"
            ),
        },
        "full_assets": _extract_full_assets(outside, minig3, args.output_dir),
        "name_ui": _extract_name_buttons(outside, args.output_dir),
        "save": _extract_save_buttons(outside, args.output_dir),
        "cooking": _extract_cooking_buttons(
            minig3, args.cooking_translation, args.output_dir
        ),
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"name={len(report['name_ui'])} save={len(report['save'])} "
        f"cooking={len(report['cooking'])} output={args.output_dir.resolve()}"
    )


if __name__ == "__main__":
    main()
