#!/usr/bin/env python3
"""Replace every confirmed Japanese-text minigame button sprite on Disc 1."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from PIL import Image, ImageDraw, ImageFont

try:
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from scripts.korean_font import load_font_profile
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from korean_font import load_font_profile


EXPECTED_MINI_G3_SHA256 = (
    "f6c3b2cc05586c7381c2ce953bcb3c86a25705a751ca9476b9a0cfe40299d5f1"
)
UNIT1_IMAGE_PAYLOAD_OFFSET = 0x18818
TEXTURE_WIDTH = 512
TEXTURE_HEIGHT = 512
TRANSPARENT_INDEX = 0
FOREGROUND_INDEX = 10
SHADOW_INDEX = 13


def _visible_bounds(
    values: bytes | list[int], width: int, height: int
) -> tuple[int, int, int, int]:
    if len(values) != width * height:
        raise ValueError("button surface size differs")
    points = [
        (index % width, index // width)
        for index, value in enumerate(values)
        if value != TRANSPARENT_INDEX
    ]
    if not points:
        raise ValueError("button label has no visible pixels")
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _center_delta(
    reference: tuple[int, int, int, int],
    replacement: tuple[int, int, int, int],
) -> tuple[int, int]:
    return (
        (reference[0] + reference[2] - replacement[0] - replacement[2]) // 2,
        (reference[1] + reference[3] - replacement[1] - replacement[3]) // 2,
    )


def _pixel_offset(x: int, y: int) -> tuple[int, int]:
    if not (0 <= x < TEXTURE_WIDTH and 0 <= y < TEXTURE_HEIGHT):
        raise ValueError(f"MINI_G3 texture coordinate is out of range: {x},{y}")
    byte_offset = UNIT1_IMAGE_PAYLOAD_OFFSET + y * (TEXTURE_WIDTH // 2) + x // 2
    shift = 4 if x & 1 else 0
    return byte_offset, shift


def _get_index(data: bytes | bytearray, x: int, y: int) -> int:
    offset, shift = _pixel_offset(x, y)
    return (data[offset] >> shift) & 0xF


def _set_index(data: bytearray, x: int, y: int, value: int) -> None:
    if not 0 <= value <= 0xF:
        raise ValueError("4bpp palette index is out of range")
    offset, shift = _pixel_offset(x, y)
    mask = 0xF << shift
    data[offset] = (data[offset] & ~mask) | (value << shift)


def _rect_indices(
    data: bytes | bytearray, rect: tuple[int, int, int, int]
) -> bytes:
    x, y, width, height = rect
    return bytes(
        _get_index(data, px, py)
        for py in range(y, y + height)
        for px in range(x, x + width)
    )


def _render_label_indices(
    text: str,
    width: int,
    height: int,
    font: ImageFont.FreeTypeFont,
    *,
    reference_bounds: tuple[int, int, int, int],
) -> Image.Image:
    mask = Image.new("1", (width, height), 0)
    probe = ImageDraw.Draw(mask)
    bbox = probe.textbbox((0, 0), text, font=font)
    ink_width = bbox[2] - bbox[0]
    ink_height = bbox[3] - bbox[1]
    # One pixel at the right/bottom is reserved for the existing green shadow.
    if ink_width + 1 > width or ink_height + 1 > height:
        raise ValueError(
            f"button label {text!r} does not fit {width}x{height}: "
            f"ink={ink_width}x{ink_height}"
        )
    x = (width - (ink_width + 1)) // 2 - bbox[0]
    y = (height - (ink_height + 1)) // 2 - bbox[1]
    probe.text((x, y), text, font=font, fill=1)

    indices = Image.new("L", (width, height), TRANSPARENT_INDEX)
    shadow = Image.new("1", (width, height), 0)
    shadow.paste(mask, (1, 1))
    indices.paste(SHADOW_INDEX, mask=shadow)
    indices.paste(FOREGROUND_INDEX, mask=mask)
    replacement_bounds = _visible_bounds(
        list(indices.get_flattened_data()), width, height
    )
    dx, dy = _center_delta(reference_bounds, replacement_bounds)
    shifted = Image.new("L", (width, height), TRANSPARENT_INDEX)
    shifted.paste(indices, (dx, dy))
    shifted_bounds = _visible_bounds(
        list(shifted.get_flattened_data()), width, height
    )
    if abs(
        (reference_bounds[0] + reference_bounds[2])
        - (shifted_bounds[0] + shifted_bounds[2])
    ) > 1 or abs(
        (reference_bounds[1] + reference_bounds[3])
        - (shifted_bounds[1] + shifted_bounds[3])
    ) > 1:
        raise ValueError(f"button label {text!r} cannot match the source center")
    return shifted


def patch_minigame_buttons(
    source: bytes,
    translation: dict[str, Any],
    *,
    font_profile_path: Path,
) -> tuple[bytes, list[dict[str, Any]], list[tuple[int, int]]]:
    if sha256_bytes(source) != EXPECTED_MINI_G3_SHA256:
        raise ValueError("MINI_G3.BIN verified original hash differs")
    entries = translation.get("entries")
    if not isinstance(entries, list) or len(entries) != 8:
        raise ValueError("minigame graphics translation must contain eight buttons")
    profile = load_font_profile(font_profile_path)
    font = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    patched = bytearray(source)
    reports: list[dict[str, Any]] = []
    allowed: list[tuple[int, int]] = []
    seen: set[str] = set()
    for entry in entries:
        entry_id = str(entry["id"])
        if entry_id in seen:
            raise ValueError(f"duplicate minigame graphics id: {entry_id}")
        seen.add(entry_id)
        rect = tuple(int(value) for value in entry["texture_rect"])
        if len(rect) != 4:
            raise ValueError(f"{entry_id}: invalid texture rectangle")
        x, y, width, height = rect
        if x & 1 or width & 1 or height != 16:
            raise ValueError(f"{entry_id}: unsupported packed rectangle")
        original_indices = _rect_indices(source, rect)
        if not any(original_indices):
            raise ValueError(f"{entry_id}: original label sprite is empty")
        source_visible_bounds = _visible_bounds(original_indices, width, height)
        rendered = _render_label_indices(
            str(entry["ko"]),
            width,
            height,
            font,
            reference_bounds=source_visible_bounds,
        )
        for py in range(height):
            for px in range(width):
                _set_index(patched, x + px, y + py, rendered.getpixel((px, py)))
        replacement_indices = _rect_indices(patched, rect)
        replacement_visible_bounds = _visible_bounds(
            replacement_indices, width, height
        )
        if replacement_indices == original_indices:
            raise ValueError(f"{entry_id}: replacement did not change the sprite")
        row_ranges = []
        for py in range(y, y + height):
            start = UNIT1_IMAGE_PAYLOAD_OFFSET + py * (TEXTURE_WIDTH // 2) + x // 2
            end = start + width // 2
            allowed.append((start, end))
            row_ranges.append([f"0x{start:X}", f"0x{end:X}"])
        reports.append(
            {
                "id": entry_id,
                "jp": entry["jp"],
                "ko": entry["ko"],
                "texture_rect": list(rect),
                "screen_consumer": {
                    "primitive": "SPRT 4bpp",
                    "tpage": "0x0039",
                    "clut": "0x7D4D",
                    "runtime_uv": [
                        160 if x == 416 else 176,
                        y - 256,
                        width,
                        height,
                    ],
                },
                "source_indices_sha256": hashlib.sha256(original_indices).hexdigest(),
                "replacement_indices_sha256": hashlib.sha256(replacement_indices).hexdigest(),
                "source_visible_bounds": list(source_visible_bounds),
                "replacement_visible_bounds": list(replacement_visible_bounds),
                "packed_row_ranges": row_ranges,
            }
        )
    return bytes(patched), reports, allowed


def build_minigame_graphics_patch(
    *,
    file_build_dir: Path,
    source_minig3_path: Path,
    translation_path: Path,
    font_profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    source = source_minig3_path.read_bytes()
    translation = load_object(translation_path)
    patched, reports, allowed = patch_minigame_buttons(
        source, translation, font_profile_path=font_profile_path
    )
    expected = verify_expected_writes(
        source,
        patched,
        allowed_ranges=allowed,
        owner="MINI_G3 runtime-confirmed cooking selection button sprites",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, bytes] = {}
    for name in base_manifest["outputs"]:
        if name == "glyph_map":
            continue
        path = file_build_dir / name
        if not path.is_file():
            continue
        payload = path.read_bytes()
        if sha256_bytes(payload) != base_manifest["outputs"][name]["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")
        (output_dir / name).write_bytes(payload)
        outputs[name] = payload
    (output_dir / "MINI_G3.BIN").write_bytes(patched)
    outputs["MINI_G3.BIN"] = patched
    map_name = "primary-korean-glyph-map.json"
    if (file_build_dir / map_name).is_file():
        shutil.copyfile(file_build_dir / map_name, output_dir / map_name)

    sources = copy.deepcopy(base_manifest["sources"])
    sources["MINI_G3.BIN"] = {
        "path": str(source_minig3_path.resolve()),
        "sha256": sha256_bytes(source),
    }
    sources["minigame_graphics_translation"] = {
        "path": str(translation_path.resolve()),
        "sha256": sha256_file(translation_path),
    }
    sources["minigame_graphics_base_file_build_manifest"] = {
        "path": str(base_manifest_path.resolve()),
        "sha256": sha256_file(base_manifest_path),
    }
    manifest = {
        **base_manifest,
        "sources": sources,
        "minigame_graphics": {
            "status": "runtime-confirmed-static-injection-user-validation-required",
            "button_entry_count": len(reports),
            "font": "Galmuri11 Regular 12px",
            "palette_policy": {
                "transparent_index": TRANSPARENT_INDEX,
                "foreground_index": FOREGROUND_INDEX,
                "shadow_index": SHADOW_INDEX,
                "clut_unchanged": True,
            },
            "other_minigame_button_inventory": {
                "MINI_G1.BIN": "numeric timing HUD; no Japanese-text button",
                "MINI_G2.BIN": "shutter control has no text; progress/status graphics are not buttons",
                "MINI_G4.BIN": "numeric card/chip controls; no Japanese-text button",
            },
            "entries": reports,
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "minigame_graphics": {"MINI_G3.BIN_relative_to_original": expected},
        },
        "outputs": {
            **{
                name: {
                    "path": str((output_dir / name).resolve()),
                    "size": len(payload),
                    "sha256": sha256_bytes(payload),
                }
                for name, payload in outputs.items()
            },
            **(
                {
                    "glyph_map": {
                        "path": str((output_dir / map_name).resolve()),
                        "sha256": sha256_file(output_dir / map_name),
                    }
                }
                if (output_dir / map_name).is_file()
                else {}
            ),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-build-dir", type=Path, required=True)
    parser.add_argument(
        "--source-minig3",
        type=Path,
        default=Path("work/extracted/disc1/iso/MINI_G3.BIN"),
    )
    parser.add_argument(
        "--translation",
        type=Path,
        default=Path("data/translations/disc1-minigame-graphics-ko.json"),
    )
    parser.add_argument(
        "--font-profile", type=Path, default=Path("config/font-profile.json")
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_minigame_graphics_patch(
        file_build_dir=args.file_build_dir,
        source_minig3_path=args.source_minig3,
        translation_path=args.translation,
        font_profile_path=args.font_profile,
        output_dir=args.output_dir,
    )
    print(
        f"buttons={manifest['minigame_graphics']['button_entry_count']} "
        f"MINI_G3={manifest['outputs']['MINI_G3.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
