#!/usr/bin/env python3
"""Translate baked labels and origin descriptions in the player-name atlas."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
from typing import Any

from PIL import Image, ImageFont

try:
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.korean_font import (
        crop_to_psx,
        load_font_profile,
        rasterize_ttf_glyph,
    )
    from scripts.psx_vram_render import bgr555_color
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import verify_expected_writes
    from korean_font import crop_to_psx, load_font_profile, rasterize_ttf_glyph
    from psx_vram_render import bgr555_color


ORIGINAL_OUTSIDE_SHA256 = (
    "26dd2ef3b83be0908572845d3e451b98f9ac33d488b8b1772199891a216fe640"
)
ORIGINAL_OUTSIDE_SIZE = 1_857_536
STATE0_ATLAS_OFFSET = 0x309C
STATE0_ATLAS_RECT = (512, 0, 256, 256)
STATE0_ATLAS_PAYLOAD_SHA256 = (
    "fb4e0ca852cc0709116f8295e1218f5d3285c45e7bc1b4b14836b36052374c56"
)
STATE0_CLUT_OFFSET = 0x2A84
STATE0_CLUT_RECT = (0, 496, 16, 16)

TARGETS = {
    "name-ui/default-button": {
        "box": (256, 72, 320, 88),
        "source_sha256": (
            "ec8d91b9225c90b8daccf5ffb8ae9840b6c515dc9318fab3378717ee891769fa"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-ui/free-origin-button": {
        "box": (256, 88, 314, 104),
        "source_sha256": (
            "04a32f48d9befd949d6a75d373d4927383b6787f4aca418da04fb3bf9032e49b"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-ui/confirm-button": {
        "box": (256, 104, 320, 120),
        "source_sha256": (
            "6341d68e8cfb3c23834355f4a8b2501a5ed000d548b339772a0a520c6508f0d7"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-ui/retry-button": {
        "box": (256, 120, 320, 136),
        "source_sha256": (
            "b2a841c73dd494a11052589bab937db30b93f423b56f7c48511513f8e9989054"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-ui/hiragana-button": {
        "box": (256, 136, 320, 152),
        "source_sha256": (
            "c6e81e60b1976a99fb04db1e03457613c4996564da857d69fa6c9981b5e80f90"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-ui/katakana-button": {
        "box": (256, 152, 312, 168),
        "source_sha256": (
            "af02850053f024de30898f589df8ee01cb8777e56dd1a13f46f34de7835b2972"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-ui/kanji-button": {
        "box": (256, 168, 312, 184),
        "source_sha256": (
            "14a32c9f932561c847cd61d4f8f4e5ed82351fcb87a52f399812c947c8050fb7"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-ui/back-button": {
        "box": (256, 184, 312, 200),
        "source_sha256": (
            "74c4be16556b1dcf41d8fcbd7fab739f5e3fb0f94a8a397e07bb6a914370c1bd"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-ui/finish-button": {
        "box": (256, 200, 312, 216),
        "source_sha256": (
            "814936f1573085180ef4e0974394b267326f8a599018defaf30859d7355c18cc"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-origin/flexible-type-name": {
        "box": (312, 160, 424, 176),
        "source_sha256": (
            "dad4f240d360ea9f0fcb69ad738fdd31a75aecf26b8588aa360469e2308c2a46"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-origin/technical-type-name": {
        "box": (312, 176, 432, 192),
        "source_sha256": (
            "427c67b1630630e1854f3c086a3a1a3d130d574fb963606a6933218d67e067f6"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-origin/strength-type-name": {
        "box": (312, 192, 424, 208),
        "source_sha256": (
            "eb590c92adf5e8a4f24fc597175ee1bd5c58a12689f8cb4333c5e28a5bef975d"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-origin/type-label": {
        "box": (348, 208, 376, 224),
        "source_sha256": (
            "285a2070fa463bcfb8573312f0f269f6ab359e96b9f1b225b770bb6a576948d4"
        ),
        "alignment": "center",
        "advance": 11,
        "line_pitch": 16,
    },
    "name-origin/flexible-racer": {
        "box": (512, 0, 704, 128),
        "source_sha256": (
            "9b06a5724cba9d1f5cad0d2bae0fca67b961fa8799850a1cfa94241adf9ccffe"
        ),
        "origin": (514, 0),
        "advance": 14,
        "line_pitch": 16,
    },
    "name-origin/technical-racer": {
        "box": (512, 128, 704, 224),
        "source_sha256": (
            "58642aa816903bee9712d1521651226800ca70ef9f6363a135c2aff88930aef2"
        ),
        "origin": (514, 128),
        "advance": 14,
        "line_pitch": 16,
    },
    "name-origin/strength-racer": {
        "box": (768, 0, 960, 112),
        "source_sha256": (
            "1f7e47fe9e9c29130d71ea85700bf110e3129596bcb29578bc8a914fa41a3684"
        ),
        "origin": (770, 0),
        "advance": 14,
        "line_pitch": 16,
    },
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def decode_4bpp(payload: bytes) -> list[int]:
    result: list[int] = []
    for value in payload:
        result.extend((value & 0xF, value >> 4))
    return result


def encode_4bpp(indices: list[int]) -> bytes:
    if len(indices) % 2:
        raise ValueError("4bpp index count must be even")
    if any(not 0 <= value <= 15 for value in indices):
        raise ValueError("4bpp index is outside 0..15")
    return bytes(
        indices[index] | (indices[index + 1] << 4)
        for index in range(0, len(indices), 2)
    )


def packed_box(
    payload: bytes,
    *,
    width_pixels: int,
    box: tuple[int, int, int, int],
) -> bytes:
    x0, y0, x1, y1 = box
    if x0 % 2 or x1 % 2:
        raise ValueError("packed 4bpp boxes must start and end on byte boundaries")
    stride = width_pixels // 2
    return b"".join(
        payload[y * stride + x0 // 2 : y * stride + x1 // 2]
        for y in range(y0, y1)
    )


def allowed_file_ranges(
    *,
    width_pixels: int,
    boxes: list[tuple[int, int, int, int]],
) -> list[tuple[int, int]]:
    stride = width_pixels // 2
    payload_start = STATE0_ATLAS_OFFSET + 8
    ranges = []
    for x0, y0, x1, y1 in boxes:
        for y in range(y0, y1):
            ranges.append(
                (
                    payload_start + y * stride + x0 // 2,
                    payload_start + y * stride + x1 // 2,
                )
            )
    return ranges


def validate_translations(
    translation: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if translation.get("schema_version") != 1:
        raise ValueError("origin graphics translation schema_version must be 1")
    entries = translation.get("translations")
    if not isinstance(entries, list):
        raise ValueError("origin graphics translation requires translations")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("origin graphics translation entry is malformed")
        entry_id = entry["id"]
        if entry_id in by_id:
            raise ValueError(f"duplicate origin graphics id: {entry_id}")
        lines = entry.get("lines")
        if not isinstance(lines, list) or not all(
            isinstance(line, str) for line in lines
        ):
            raise ValueError(f"{entry_id}: lines must be strings")
        max_columns = int(entry["max_columns"])
        max_rows = int(entry["max_rows"])
        if len(lines) > max_rows:
            raise ValueError(f"{entry_id}: line count exceeds {max_rows}")
        for line in lines:
            if len(line) > max_columns:
                raise ValueError(
                    f"{entry_id}: {line!r} exceeds {max_columns} columns"
                )
        by_id[entry_id] = entry
    if set(by_id) != set(TARGETS):
        raise ValueError("origin graphics translation ids differ from targets")
    return by_id


def clear_box(
    indices: list[int],
    *,
    width: int,
    box: tuple[int, int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        indices[y * width + x0 : y * width + x1] = [0] * (x1 - x0)


def draw_glyph(
    indices: list[int],
    *,
    width: int,
    height: int,
    pixels: list[int],
    x: int,
    y: int,
    shadow_index: int,
    ink_index: int,
    shadow_x_offset: int,
    shadow_y_offset: int,
) -> None:
    if len(pixels) != 14 * 14:
        raise ValueError("Galmuri11 target glyph must be 14x14")
    for row in range(14):
        for column in range(14):
            if not pixels[row * 14 + column]:
                continue
            shadow_x = x + column + shadow_x_offset
            shadow_y = y + row + shadow_y_offset
            if 0 <= shadow_x < width and 0 <= shadow_y < height:
                indices[shadow_y * width + shadow_x] = shadow_index
    for row in range(14):
        for column in range(14):
            if not pixels[row * 14 + column]:
                continue
            target_x = x + column
            target_y = y + row
            if 0 <= target_x < width and 0 <= target_y < height:
                indices[target_y * width + target_x] = ink_index


def glyph_ink_bounds(pixels: list[int]) -> tuple[int, int, int, int]:
    """Return inclusive non-zero bounds for one 14x14 mask."""
    points = [
        (index % 14, index // 14)
        for index, value in enumerate(pixels)
        if value
    ]
    if not points:
        raise ValueError("glyph mask is empty")
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def layout_ink_bounds(
    lines: list[str],
    *,
    glyphs: dict[str, list[int]],
    advance: int,
    line_pitch: int,
    shadow_x_offset: int,
    shadow_y_offset: int,
) -> tuple[int, int, int, int]:
    """Return inclusive bounds of text and its shadow relative to the origin."""
    bounds: list[tuple[int, int, int, int]] = []
    for row, line in enumerate(lines):
        for column, character in enumerate(line):
            if character == " ":
                continue
            x0, y0, x1, y1 = glyph_ink_bounds(glyphs[character])
            x0 += column * advance
            x1 += column * advance
            y0 += row * line_pitch
            y1 += row * line_pitch
            bounds.append((x0, y0, x1, y1))
            bounds.append(
                (
                    x0 + shadow_x_offset,
                    y0 + shadow_y_offset,
                    x1 + shadow_x_offset,
                    y1 + shadow_y_offset,
                )
            )
    if not bounds:
        raise ValueError("text layout contains no visible glyphs")
    return (
        min(value[0] for value in bounds),
        min(value[1] for value in bounds),
        max(value[2] for value in bounds),
        max(value[3] for value in bounds),
    )


def centered_origin(
    box: tuple[int, int, int, int],
    ink_bounds: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Center inclusive ink bounds inside a half-open target rectangle."""
    box_x0, box_y0, box_x1, box_y1 = box
    ink_x0, ink_y0, ink_x1, ink_y1 = ink_bounds
    ink_width = ink_x1 - ink_x0 + 1
    ink_height = ink_y1 - ink_y0 + 1
    box_width = box_x1 - box_x0
    box_height = box_y1 - box_y0
    if ink_width > box_width or ink_height > box_height:
        raise ValueError(
            f"text ink {ink_width}x{ink_height} exceeds box "
            f"{box_width}x{box_height}"
        )
    return (
        box_x0 + (box_width - ink_width) // 2 - ink_x0,
        box_y0 + (box_height - ink_height) // 2 - ink_y0,
    )


def visible_bounds(
    values: list[int] | bytes,
    *,
    width: int,
    height: int,
    transparent_index: int = 0,
) -> tuple[int, int, int, int]:
    """Return inclusive nontransparent bounds in a tightly packed surface."""
    if len(values) != width * height:
        raise ValueError("surface size differs from its declared dimensions")
    points = [
        (index % width, index // width)
        for index, value in enumerate(values)
        if value != transparent_index
    ]
    if not points:
        raise ValueError("surface contains no visible pixels")
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def reference_centered_origin(
    reference_bounds: tuple[int, int, int, int],
    ink_bounds: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Place replacement ink on the original label's visual center.

    The label sprites are composited over separate button backgrounds.  Their
    visible center is therefore the stable screen-space anchor; the enclosing
    storage rectangle is only a packing boundary.
    """
    ref_x0, ref_y0, ref_x1, ref_y1 = reference_bounds
    ink_x0, ink_y0, ink_x1, ink_y1 = ink_bounds
    return (
        (ref_x0 + ref_x1 - ink_x0 - ink_x1) // 2,
        (ref_y0 + ref_y1 - ink_y0 - ink_y1) // 2,
    )


def patch_origin_atlas(
    source: bytes,
    *,
    translation: dict[str, Any],
    font_profile_path: Path,
) -> tuple[bytes, dict[str, Any]]:
    if len(source) != ORIGINAL_OUTSIDE_SIZE:
        raise ValueError("OUTSIDE.BIN size differs from the verified original")
    if sha256_bytes(source) != ORIGINAL_OUTSIDE_SHA256:
        raise ValueError("OUTSIDE.BIN hash differs from the verified original")
    x, y, width_halfwords, height = struct.unpack_from(
        "<4H", source, STATE0_ATLAS_OFFSET
    )
    if (x, y, width_halfwords, height) != STATE0_ATLAS_RECT:
        raise ValueError("OUTSIDE unit 0 atlas rectangle header differs")
    width = width_halfwords * 4
    payload_size = width_halfwords * height * 2
    payload_start = STATE0_ATLAS_OFFSET + 8
    payload_end = payload_start + payload_size
    source_payload = source[payload_start:payload_end]
    if sha256_bytes(source_payload) != STATE0_ATLAS_PAYLOAD_SHA256:
        raise ValueError("OUTSIDE unit 0 atlas payload differs")

    entries = validate_translations(translation)
    for entry_id, target in TARGETS.items():
        actual_hash = sha256_bytes(
            packed_box(
                source_payload,
                width_pixels=width,
                box=target["box"],
            )
        )
        if actual_hash != target["source_sha256"]:
            raise ValueError(f"{entry_id}: source graphics rectangle differs")

    profile = load_font_profile(font_profile_path)
    ttf = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    glyph_cache: dict[str, list[int]] = {}
    indices = decode_4bpp(source_payload)
    policy = translation["policy"]["palette_indices"]
    shadow_index = int(policy["shadow"])
    ink_index = int(policy["ink"])
    shadow_offset = translation["policy"].get("shadow_offset_px", [1, 1])
    if not (
        isinstance(shadow_offset, list)
        and len(shadow_offset) == 2
        and all(isinstance(value, int) for value in shadow_offset)
    ):
        raise ValueError("origin graphics shadow_offset_px must be [x, y]")
    shadow_x_offset, shadow_y_offset = shadow_offset
    generated = []
    for entry_id, target in TARGETS.items():
        entry = entries[entry_id]
        box = target["box"]
        box_x0, box_y0, box_x1, box_y1 = box
        box_width = box_x1 - box_x0
        box_height = box_y1 - box_y0
        source_box = [
            indices[y_pos * width + x_pos]
            for y_pos in range(box_y0, box_y1)
            for x_pos in range(box_x0, box_x1)
        ]
        source_visible_bounds = visible_bounds(
            source_box,
            width=box_width,
            height=box_height,
        )
        clear_box(indices, width=width, box=box)
        for line in entry["lines"]:
            for character in line:
                if character == " " or character in glyph_cache:
                    continue
                source_pixels = rasterize_ttf_glyph(
                    ttf,
                    character,
                    x_offset=profile.x_offset_px,
                    y_offset=profile.y_offset_px,
                )
                glyph = crop_to_psx(source_pixels, intensity=1)
                if not any(glyph):
                    raise ValueError(
                        f"{entry_id}: {character!r} rasterizes blank"
                    )
                glyph_cache[character] = glyph
        if target.get("alignment") == "center":
            bounds = layout_ink_bounds(
                entry["lines"],
                glyphs=glyph_cache,
                advance=int(target["advance"]),
                line_pitch=int(target["line_pitch"]),
                shadow_x_offset=shadow_x_offset,
                shadow_y_offset=shadow_y_offset,
            )
            relative_x, relative_y = reference_centered_origin(
                source_visible_bounds,
                bounds,
            )
            placed_bounds = (
                relative_x + bounds[0],
                relative_y + bounds[1],
                relative_x + bounds[2],
                relative_y + bounds[3],
            )
            if not (
                0 <= placed_bounds[0] <= placed_bounds[2] < box_width
                and 0 <= placed_bounds[1] <= placed_bounds[3] < box_height
            ):
                raise ValueError(
                    f"{entry_id}: source-centered replacement exceeds its box"
                )
            origin_x = box_x0 + relative_x
            origin_y = box_y0 + relative_y
        else:
            origin_x, origin_y = target["origin"]
            placed_bounds = None
        for row, line in enumerate(entry["lines"]):
            for column, character in enumerate(line):
                if character == " ":
                    continue
                x_pos = origin_x + column * int(target["advance"])
                y_pos = origin_y + row * int(target["line_pitch"])
                draw_glyph(
                    indices,
                    width=width,
                    height=height,
                    pixels=glyph_cache[character],
                    x=x_pos,
                    y=y_pos,
                    shadow_index=shadow_index,
                    ink_index=ink_index,
                    shadow_x_offset=shadow_x_offset,
                    shadow_y_offset=shadow_y_offset,
                )
        generated.append(
            {
                "id": entry_id,
                "box": list(box),
                "lines": entry["lines"],
                "max_columns": entry["max_columns"],
                "max_rows": entry["max_rows"],
                "alignment": target.get("alignment", "explicit-origin"),
                "resolved_origin": [origin_x, origin_y],
                "source_visible_bounds_relative": list(source_visible_bounds),
                **(
                    {"replacement_visible_bounds_relative": list(placed_bounds)}
                    if placed_bounds is not None
                    else {}
                ),
            }
        )

    patched_payload = encode_4bpp(indices)
    patched = bytearray(source)
    patched[payload_start:payload_end] = patched_payload
    boxes = [target["box"] for target in TARGETS.values()]
    expected = verify_expected_writes(
        source,
        bytes(patched),
        allowed_ranges=allowed_file_ranges(
            width_pixels=width,
            boxes=boxes,
        ),
        owner="OUTSIDE unit 0 baked player-name UI graphics",
    )
    return bytes(patched), {
        "status": "static-verification-passed-runtime-validation-required",
        "source_file": "OUTSIDE.BIN",
        "state_index": 0,
        "atlas_child_index": 5,
        "atlas_file_offset": f"0x{STATE0_ATLAS_OFFSET:X}",
        "vram_rectangle": {
            "x_halfwords": x,
            "y": y,
            "width_halfwords": width_halfwords,
            "height": height,
            "texture_depth": "4bpp",
        },
        "resident_vram_source_payload_sha256": STATE0_ATLAS_PAYLOAD_SHA256,
        "font_profile": str(font_profile_path.resolve()),
        "font_profile_sha256": sha256_file(font_profile_path),
        "generated": generated,
        "protected": (
            "CLUTs, render metadata, English headings, and all pixels "
            "outside the declared rectangles"
        ),
        "expected_writes": expected,
        "runtime_validation_required": [
            "inspect all three origin-description pages",
            "confirm the narrow 타입 label renders without clipping",
            "inspect every Korean name-entry button in normal/highlight states",
            "confirm 균형형/기술형/체력형 match the selected origin",
            "confirm origin selection and final confirmation still advance",
        ],
    }


def render_preview(
    outside: bytes,
    *,
    output: Path,
    palette_bank: int,
) -> None:
    x, y, width_halfwords, height = struct.unpack_from(
        "<4H", outside, STATE0_ATLAS_OFFSET
    )
    del x, y
    payload_start = STATE0_ATLAS_OFFSET + 8
    payload = outside[
        payload_start : payload_start + width_halfwords * height * 2
    ]
    indices = decode_4bpp(payload)
    clut_x, clut_y, clut_width, clut_height = struct.unpack_from(
        "<4H", outside, STATE0_CLUT_OFFSET
    )
    del clut_x, clut_y
    if (clut_width, clut_height) != STATE0_CLUT_RECT[2:]:
        raise ValueError("OUTSIDE unit 0 CLUT header differs")
    if not 0 <= palette_bank < clut_height:
        raise ValueError("palette bank is outside the CLUT")
    clut_start = STATE0_CLUT_OFFSET + 8 + palette_bank * clut_width * 2
    palette = struct.unpack_from(f"<{clut_width}H", outside, clut_start)
    image = Image.new("RGBA", (width_halfwords * 4, height))
    image.putdata([bgr555_color(palette[index]) for index in indices])
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def build_name_origin_graphics_patch(
    *,
    file_build_dir: Path,
    outside_path: Path,
    translation_path: Path,
    font_profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    if not isinstance(base_manifest.get("name_4x4_poc"), dict):
        raise ValueError("base build does not contain the 4+4 name patch")

    translation = load_object(translation_path)
    source_outside = outside_path.read_bytes()
    patched_outside, report = patch_origin_atlas(
        source_outside,
        translation=translation,
        font_profile_path=font_profile_path,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    copied_outputs: dict[str, bytes] = {}
    for name in ("START.BIN", "ALLBIN.BIN", "SLPS_019.58"):
        source_path = file_build_dir / name
        payload = source_path.read_bytes()
        if sha256_bytes(payload) != base_manifest["outputs"][name]["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")
        shutil.copyfile(source_path, output_dir / name)
        copied_outputs[name] = payload
    map_source = file_build_dir / "primary-korean-glyph-map.json"
    if map_source.exists():
        shutil.copyfile(map_source, output_dir / map_source.name)
    (output_dir / "OUTSIDE.BIN").write_bytes(patched_outside)
    render_preview(
        patched_outside,
        output=output_dir / "name-origin-atlas-gray-preview.png",
        palette_bank=0,
    )
    render_preview(
        patched_outside,
        output=output_dir / "name-origin-atlas-highlight-preview.png",
        palette_bank=13,
    )

    manifest = {
        **base_manifest,
        "warning": (
            str(base_manifest.get("warning", ""))
            + " The baked player-name buttons, origin type names, "
            "descriptions, and 타입 label are translated; runtime visual "
            "review is required."
        ).strip(),
        "sources": {
            **base_manifest["sources"],
            "OUTSIDE.BIN": {
                "path": str(outside_path.resolve()),
                "sha256": sha256_bytes(source_outside),
            },
            "name_origin_graphics_translation": {
                "path": str(translation_path.resolve()),
                "sha256": sha256_file(translation_path),
            },
            "name_origin_graphics_base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
        },
        "name_origin_graphics": report,
        "expected_writes": {
            **base_manifest.get("expected_writes", {}),
            "name_origin_graphics": {
                "OUTSIDE.BIN_relative_to_verified_original": report[
                    "expected_writes"
                ]
            },
        },
        "outputs": {
            **base_manifest["outputs"],
            **{
                name: {
                    "path": str((output_dir / name).resolve()),
                    "size": len(payload),
                    "sha256": sha256_bytes(payload),
                }
                for name, payload in copied_outputs.items()
            },
            "OUTSIDE.BIN": {
                "path": str((output_dir / "OUTSIDE.BIN").resolve()),
                "size": len(patched_outside),
                "sha256": sha256_bytes(patched_outside),
            },
        },
    }
    if map_source.exists():
        manifest["outputs"]["glyph_map"] = {
            "path": str((output_dir / map_source.name).resolve()),
            "sha256": sha256_file(output_dir / map_source.name),
        }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-build-dir", type=Path, required=True)
    parser.add_argument(
        "--outside",
        type=Path,
        default=Path("work/extracted/disc1/iso/OUTSIDE.BIN"),
    )
    parser.add_argument(
        "--translation",
        type=Path,
        default=Path(
            "data/translations/disc1-name-origin-graphics-ko.json"
        ),
    )
    parser.add_argument(
        "--font-profile",
        type=Path,
        default=Path("config/font-profile.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_name_origin_graphics_patch(
        file_build_dir=args.file_build_dir,
        outside_path=args.outside,
        translation_path=args.translation,
        font_profile_path=args.font_profile,
        output_dir=args.output_dir,
    )
    report = manifest["name_origin_graphics"]
    print(
        f"targets={len(report['generated'])} "
        f"OUTSIDE={manifest['outputs']['OUTSIDE.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
