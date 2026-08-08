#!/usr/bin/env python3
"""Replace the motorhome-map team-name sprites in AVM_MAP.BIN unit 0."""

from __future__ import annotations

import argparse
import copy
import hashlib
from pathlib import Path
import shutil
import struct
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_AVM_MAP_SHA256 = (
    "227cb9554f2515370aec74d4c72ffbd21c542270aed7c71db0c6b5ef039abe3c"
)
EXPECTED_UNIT0_SHA256 = (
    "5e1e117f1d0910511e7ab9065bd166c09125043c152dcc8d7f9a43881db8f2e1"
)
UNIT0_SIZE = 0x8800
UNIT0_CLUT_PAYLOAD_OFFSET = 0x10
UNIT0_IMAGE_PAYLOAD_OFFSET = 0x218
TEXTURE_WIDTH = 256
TEXTURE_HEIGHT = 256
TRANSPARENT_INDEX = 0
FOREGROUND_INDEX = 1
SHADOW_INDEX = 4

# These ALLBIN SPRT descriptors prove the exact UV fragments consumed for the
# six team captions.  Format: flag, CLUT, U, V, W, H, X, Y.
CONSUMER_DESCRIPTORS = (
    (0x1018B8, (0x000F, 0x7C80, 0, 16, 120, 16, -60, -16)),
    (0x1018D0, (0x000F, 0x7C80, 0, 16, 48, 16, -64, -16)),
    (0x1018DC, (0x000F, 0x7C80, 48, 32, 80, 16, -16, -16)),
    (0x1018F4, (0x000F, 0x7C80, 0, 0, 120, 16, -60, -16)),
    (0x10190C, (0x000F, 0x7C80, 0, 48, 96, 16, -24, -16)),
    (0x101918, (0x000F, 0x7C80, 0, 32, 48, 16, -72, -16)),
    (0x101930, (0x000F, 0x7C80, 0, 64, 120, 16, -60, -16)),
    (0x101948, (0x000F, 0x7C80, 0, 80, 120, 16, -88, -16)),
    (0x101954, (0x000F, 0x7C80, 0, 96, 56, 16, 32, -16)),
)


def _pixel_offset(x: int, y: int) -> tuple[int, int]:
    if not (0 <= x < TEXTURE_WIDTH and 0 <= y < TEXTURE_HEIGHT):
        raise ValueError(f"AVM_MAP unit-0 texture coordinate is outside the atlas: {x},{y}")
    offset = UNIT0_IMAGE_PAYLOAD_OFFSET + y * (TEXTURE_WIDTH // 2) + x // 2
    return offset, 4 if x & 1 else 0


def _get_index(data: bytes | bytearray, x: int, y: int) -> int:
    offset, shift = _pixel_offset(x, y)
    return (data[offset] >> shift) & 0xF


def _set_index(data: bytearray, x: int, y: int, value: int) -> None:
    if not 0 <= value <= 0xF:
        raise ValueError("4bpp palette index is outside 0..15")
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


def _verify_consumers(allbin: bytes) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for offset, expected in CONSUMER_DESCRIPTORS:
        actual = struct.unpack_from("<HH4Bhh", allbin, offset)
        if actual != expected:
            raise ValueError(
                f"ALLBIN motorhome consumer at 0x{offset:X} differs: "
                f"{actual!r} != {expected!r}"
            )
        reports.append(
            {
                "allbin_offset": f"0x{offset:X}",
                "flag": f"0x{actual[0]:04X}",
                "clut": f"0x{actual[1]:04X}",
                "uvwh": list(actual[2:6]),
                "xy": list(actual[6:8]),
            }
        )
    return reports


def patch_consumer_layout(
    allbin: bytes, translation: dict[str, Any]
) -> tuple[bytes, list[dict[str, Any]], list[tuple[int, int]]]:
    """Shift only the two short captions by one 12px fullwidth cell."""
    _verify_consumers(allbin)
    adjustments = translation.get("screen_layout_adjustments")
    if not isinstance(adjustments, list) or len(adjustments) != 2:
        raise ValueError("motorhome translation must contain two layout adjustments")
    expected_offsets = {0x1018D0, 0x1018DC, 0x10190C, 0x101918}
    patched = bytearray(allbin)
    reports: list[dict[str, Any]] = []
    allowed: list[tuple[int, int]] = []
    seen_offsets: set[int] = set()
    for adjustment in adjustments:
        team_id = str(adjustment["team_id"])
        shift_x = int(adjustment["shift_x_px"])
        leading_cells = int(adjustment["leading_fullwidth_cells"])
        if shift_x != 12 or leading_cells != 1:
            raise ValueError(
                f"{team_id}: layout adjustment must be one 12px fullwidth cell"
            )
        raw_offsets = adjustment.get("allbin_descriptor_offsets")
        if not isinstance(raw_offsets, list) or len(raw_offsets) != 2:
            raise ValueError(f"{team_id}: layout adjustment requires two SPRTs")
        descriptor_reports: list[dict[str, Any]] = []
        for raw_offset in raw_offsets:
            offset = int(str(raw_offset), 0)
            if offset in seen_offsets:
                raise ValueError(f"duplicate motorhome layout descriptor: 0x{offset:X}")
            seen_offsets.add(offset)
            record = struct.unpack_from("<HH4Bhh", allbin, offset)
            old_x = int(record[6])
            new_x = old_x + shift_x
            struct.pack_into("<h", patched, offset + 8, new_x)
            allowed.append((offset + 8, offset + 10))
            descriptor_reports.append(
                {
                    "allbin_offset": f"0x{offset:X}",
                    "old_x": old_x,
                    "new_x": new_x,
                    "shift_x_px": shift_x,
                    "uvwh": list(record[2:6]),
                }
            )
        reports.append(
            {
                "team_id": team_id,
                "leading_fullwidth_cells": leading_cells,
                "shift_x_px": shift_x,
                "descriptors": descriptor_reports,
            }
        )
    if seen_offsets != expected_offsets:
        raise ValueError("motorhome layout adjustment descriptor population differs")
    return bytes(patched), reports, allowed


def _render_fragment(
    text: str,
    *,
    width: int,
    height: int,
    alignment: str,
    font: ImageFont.FreeTypeFont,
) -> bytes:
    mask = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    bbox = draw.textbbox((0, 0), text, font=font)
    ink_width = bbox[2] - bbox[0]
    ink_height = bbox[3] - bbox[1]
    if ink_width + 1 > width - 2 or ink_height + 1 > height:
        raise ValueError(
            f"motorhome label fragment {text!r} does not fit {width}x{height}: "
            f"ink={ink_width}x{ink_height} plus 1px shadow"
        )
    if alignment in {"left", "left-tight"}:
        padding = 0 if alignment == "left-tight" else 2
        x = padding - bbox[0]
    elif alignment in {"right", "right-tight"}:
        padding = 0 if alignment == "right-tight" else 2
        x = width - padding - (ink_width + 1) - bbox[0]
    elif alignment == "center":
        x = (width - (ink_width + 1)) // 2 - bbox[0]
    else:
        raise ValueError(f"unsupported fragment alignment: {alignment}")
    y = (height - (ink_height + 1)) // 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=1)

    # FreeType's textbbox includes advance-side blank pixels for this font.
    # Split words must be joined by their actual rasterized ink, not by that
    # nominal box, or the consumer's adjacent SPRTs show a false word space.
    actual_bbox = mask.getbbox()
    if actual_bbox is None:
        raise ValueError(f"motorhome label fragment {text!r} rasterized empty")
    if alignment == "left-tight":
        shift_x = -actual_bbox[0]
    elif alignment == "right-tight":
        # Leave the last column for the +1px shadow of the rightmost ink.
        shift_x = (width - 1) - actual_bbox[2]
    else:
        shift_x = 0
    if shift_x:
        shifted = Image.new("1", (width, height), 0)
        shifted.paste(mask, (shift_x, 0))
        mask = shifted

    indices = bytearray(width * height)
    pixels = bytes(mask.get_flattened_data())
    for py in range(height):
        for px in range(width):
            if not pixels[py * width + px]:
                continue
            shadow_x = px + 1
            shadow_y = py + 1
            if shadow_x < width and shadow_y < height:
                indices[shadow_y * width + shadow_x] = SHADOW_INDEX
    for index, value in enumerate(pixels):
        if value:
            indices[index] = FOREGROUND_INDEX
    return bytes(indices)


def patch_motorhome_team_labels(
    source: bytes,
    translation: dict[str, Any],
    *,
    font_profile_path: Path,
    consumer_allbin: bytes,
) -> tuple[
    bytes,
    list[dict[str, Any]],
    list[tuple[int, int]],
    list[dict[str, Any]],
]:
    if sha256_bytes(source) != EXPECTED_AVM_MAP_SHA256:
        raise ValueError("AVM_MAP.BIN verified original hash differs")
    if hashlib.sha256(source[:UNIT0_SIZE]).hexdigest() != EXPECTED_UNIT0_SHA256:
        raise ValueError("AVM_MAP.BIN unit 0 hash differs")
    if source[0x210:0x218] != bytes.fromhex("c003000040000001"):
        raise ValueError("AVM_MAP unit-0 4bpp upload record differs")
    consumers = _verify_consumers(consumer_allbin)
    if translation.get("file") != "AVM_MAP.BIN" or translation.get("unit") != 0:
        raise ValueError("motorhome graphics translation targets the wrong file/unit")
    fragments = translation.get("fragments")
    if not isinstance(fragments, list) or len(fragments) != 9:
        raise ValueError("motorhome graphics translation must contain nine fragments")

    profile = load_font_profile(font_profile_path)
    font = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    patched = bytearray(source)
    reports: list[dict[str, Any]] = []
    allowed: list[tuple[int, int]] = []
    occupied: set[tuple[int, int]] = set()
    seen: set[str] = set()
    for entry in fragments:
        entry_id = str(entry["id"])
        if entry_id in seen:
            raise ValueError(f"duplicate motorhome fragment id: {entry_id}")
        seen.add(entry_id)
        rect = tuple(int(value) for value in entry["texture_rect"])
        if len(rect) != 4:
            raise ValueError(f"{entry_id}: texture rectangle must have four values")
        x, y, width, height = rect
        if x & 1 or width & 1 or height != 16:
            raise ValueError(f"{entry_id}: unsupported packed rectangle")
        for py in range(y, y + height):
            for px in range(x, x + width):
                coordinate = (px, py)
                if coordinate in occupied:
                    raise ValueError(f"{entry_id}: fragment rectangles overlap")
                occupied.add(coordinate)
        original = _rect_indices(source, rect)
        if not any(original):
            raise ValueError(f"{entry_id}: original Japanese fragment is empty")
        replacement = _render_fragment(
            str(entry["ko"]),
            width=width,
            height=height,
            alignment=str(entry["alignment"]),
            font=font,
        )
        for py in range(height):
            for px in range(width):
                _set_index(patched, x + px, y + py, replacement[py * width + px])
        if _rect_indices(patched, rect) != replacement:
            raise AssertionError(f"{entry_id}: packed 4bpp write round-trip differs")
        row_ranges: list[list[str]] = []
        for py in range(y, y + height):
            start = UNIT0_IMAGE_PAYLOAD_OFFSET + py * (TEXTURE_WIDTH // 2) + x // 2
            end = start + width // 2
            allowed.append((start, end))
            row_ranges.append([f"0x{start:X}", f"0x{end:X}"])
        reports.append(
            {
                "id": entry_id,
                "jp": entry["jp"],
                "ko": entry["ko"],
                "texture_rect": list(rect),
                "alignment": entry["alignment"],
                "source_indices_sha256": hashlib.sha256(original).hexdigest(),
                "replacement_indices_sha256": hashlib.sha256(replacement).hexdigest(),
                "changed_pixel_count": sum(
                    left != right for left, right in zip(original, replacement)
                ),
                "packed_row_ranges": row_ranges,
            }
        )
    return bytes(patched), reports, allowed, consumers


def _preview(data: bytes) -> Image.Image:
    words = struct.unpack_from("<16H", data, UNIT0_CLUT_PAYLOAD_OFFSET)
    colors = []
    for value in words:
        colors.append(
            (
                (value & 0x1F) * 255 // 31,
                ((value >> 5) & 0x1F) * 255 // 31,
                ((value >> 10) & 0x1F) * 255 // 31,
                0 if value & 0x7FFF == 0 else 255,
            )
        )
    image = Image.new("RGBA", (128, 112))
    image.putdata(
        [colors[_get_index(data, x, y)] for y in range(112) for x in range(128)]
    )
    return image


def build_motorhome_team_graphics_patch(
    *,
    file_build_dir: Path,
    source_avm_map_path: Path,
    translation_path: Path,
    font_profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    if "AVM_MAP.BIN" in base_manifest.get("outputs", {}):
        raise ValueError("base file build already contains an AVM_MAP.BIN output")
    source = source_avm_map_path.read_bytes()
    translation = load_object(translation_path)
    consumer_allbin_path = file_build_dir / "ALLBIN.BIN"
    consumer_allbin = consumer_allbin_path.read_bytes()
    if sha256_bytes(consumer_allbin) != base_manifest["outputs"]["ALLBIN.BIN"]["sha256"]:
        raise ValueError("base file-build ALLBIN.BIN hash differs")
    patched, reports, allowed, consumers = patch_motorhome_team_labels(
        source,
        translation,
        font_profile_path=font_profile_path,
        consumer_allbin=consumer_allbin,
    )
    patched_allbin, layout_reports, allbin_allowed = patch_consumer_layout(
        consumer_allbin, translation
    )
    expected = verify_expected_writes(
        source,
        patched,
        allowed_ranges=allowed,
        owner="AVM_MAP unit-0 motorhome team-name 4bpp fragments",
    )
    expected_allbin = verify_expected_writes(
        consumer_allbin,
        patched_allbin,
        allowed_ranges=allbin_allowed,
        owner="ALLBIN motorhome short-caption one-cell screen alignment",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, bytes] = {}
    for name, metadata in base_manifest["outputs"].items():
        if name == "glyph_map":
            continue
        path = file_build_dir / name
        if not path.is_file():
            continue
        payload = path.read_bytes()
        if sha256_bytes(payload) != metadata["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")
        if name == "ALLBIN.BIN":
            payload = patched_allbin
        (output_dir / name).write_bytes(payload)
        outputs[name] = payload
    (output_dir / "AVM_MAP.BIN").write_bytes(patched)
    outputs["AVM_MAP.BIN"] = patched
    map_name = "primary-korean-glyph-map.json"
    if (file_build_dir / map_name).is_file():
        shutil.copyfile(file_build_dir / map_name, output_dir / map_name)

    original_preview = output_dir / "motorhome-team-labels-original-4x.png"
    inserted_preview = output_dir / "motorhome-team-labels-inserted-4x.png"
    _preview(source).resize((512, 448), Image.Resampling.NEAREST).save(original_preview)
    _preview(patched).resize((512, 448), Image.Resampling.NEAREST).save(inserted_preview)

    sources = copy.deepcopy(base_manifest["sources"])
    sources["AVM_MAP.BIN"] = {
        "path": str(source_avm_map_path.resolve()),
        "size": len(source),
        "sha256": sha256_bytes(source),
    }
    sources["motorhome_team_graphics_translation"] = {
        "path": str(translation_path.resolve()),
        "sha256": sha256_file(translation_path),
    }
    sources["motorhome_team_graphics_font_profile"] = {
        "path": str(font_profile_path.resolve()),
        "sha256": sha256_file(font_profile_path),
    }
    sources["motorhome_team_graphics_base_file_build_manifest"] = {
        "path": str(base_manifest_path.resolve()),
        "sha256": sha256_file(base_manifest_path),
    }
    manifest = {
        **base_manifest,
        "sources": sources,
        "motorhome_team_graphics": {
            "status": "static-injection-user-runtime-validation-required",
            "file": "AVM_MAP.BIN",
            "unit": 0,
            "team_count": len(translation["teams"]),
            "fragment_count": len(reports),
            "font": "Galmuri11 Regular 12px",
            "palette_policy": {
                "transparent_index": TRANSPARENT_INDEX,
                "foreground_index": FOREGROUND_INDEX,
                "shadow_index": SHADOW_INDEX,
                "shadow_offset_px": [1, 1],
                "clut_unchanged": True,
            },
            "storage_policy": "replace-only-nine-proven-consumer-fragments",
            "consumer_descriptors": consumers,
            "screen_layout_adjustments": layout_reports,
            "teams": translation["teams"],
            "fragments": reports,
            "previews": {
                "original": {
                    "path": str(original_preview.resolve()),
                    "sha256": sha256_file(original_preview),
                },
                "inserted": {
                    "path": str(inserted_preview.resolve()),
                    "sha256": sha256_file(inserted_preview),
                },
            },
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "motorhome_team_graphics": {
                "AVM_MAP.BIN_relative_to_original": expected,
                "ALLBIN.BIN_relative_to_base": expected_allbin,
            },
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
        "--source-avm-map",
        type=Path,
        default=PROJECT_ROOT / "work/extracted/disc1/iso/AVM_MAP.BIN",
    )
    parser.add_argument(
        "--translation",
        type=Path,
        default=PROJECT_ROOT
        / "data/translations/disc1-motorhome-team-graphics-ko.json",
    )
    parser.add_argument(
        "--font-profile",
        type=Path,
        default=PROJECT_ROOT / "config/font-profile.json",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_motorhome_team_graphics_patch(
        file_build_dir=args.file_build_dir,
        source_avm_map_path=args.source_avm_map,
        translation_path=args.translation,
        font_profile_path=args.font_profile,
        output_dir=args.output_dir,
    )
    print(
        f"teams={manifest['motorhome_team_graphics']['team_count']} "
        f"fragments={manifest['motorhome_team_graphics']['fragment_count']} "
        f"AVM_MAP={manifest['outputs']['AVM_MAP.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
