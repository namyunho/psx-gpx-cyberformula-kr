#!/usr/bin/env python3
"""Insert the edited 384x256 title index plane into a shared file build.

The purple editing color is converted back to the original transparent CLUT
entry.  All other pixels are mapped by exact PS1 BGR555-expanded RGB values;
the edited PNG's palette indices are never copied directly.
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from PIL import Image

try:
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from scripts.extract_title_chapter_graphics import (
        EXPECTED_UNIT_SHA256,
        start_schedule,
    )
    from scripts.psx_layout import classify_child, parse_offset_directory
    from scripts.psx_vram_render import bgr555_color, palette_words, record_from_bytes
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from extract_title_chapter_graphics import EXPECTED_UNIT_SHA256, start_schedule
    from psx_layout import classify_child, parse_offset_directory
    from psx_vram_render import bgr555_color, palette_words, record_from_bytes


EXPECTED_START_SHA256 = (
    "d0b22efb4e5ea46c869f822af9bc7f207bc95a670a25acb15fc3dcd2ab3bf8cc"
)
TITLE_UNIT = 8
PALETTE_CHILD = 4
IMAGE_CHILD = 5
TITLE_SIZE = (384, 256)
PURPLE = (255, 0, 255)
TRANSPARENT_INDEX = 0


def _title_records(
    source_start: bytes, source_root: Path, boot_exe_name: str
) -> tuple[int, int, bytes, bytes]:
    schedule = start_schedule(source_root, boot_exe_name)
    span = schedule[TITLE_UNIT]
    unit = source_start[span["byte_offset"] : span["byte_end"]]
    digest = sha256_bytes(unit)
    if digest != EXPECTED_UNIT_SHA256[TITLE_UNIT]:
        raise ValueError(
            f"START.BIN title unit mismatch: expected "
            f"{EXPECTED_UNIT_SHA256[TITLE_UNIT]}, got {digest}"
        )
    offsets = parse_offset_directory(unit)
    if offsets is None or len(offsets) <= IMAGE_CHILD:
        raise ValueError("START.BIN title unit has no expected child directory")
    palette_raw = unit[offsets[PALETTE_CHILD] : offsets[IMAGE_CHILD]]
    image_end = len(unit)
    image_raw = unit[offsets[IMAGE_CHILD] : image_end]
    palette_record = record_from_bytes(palette_raw, TITLE_UNIT, PALETTE_CHILD)
    image_record = record_from_bytes(image_raw, TITLE_UNIT, IMAGE_CHILD)
    if (image_record.width_halfwords * 2, image_record.height) != TITLE_SIZE:
        raise ValueError("START.BIN title image dimensions differ")
    if len(palette_words(palette_record)) != 256:
        raise ValueError("START.BIN title CLUT is not 256 colors")
    payload_start = span["byte_offset"] + offsets[IMAGE_CHILD] + 8
    payload_end = payload_start + len(image_record.payload)
    return payload_start, payload_end, palette_record.payload, image_record.payload


def remap_edited_title(
    edited_image: Image.Image,
    *,
    palette_payload: bytes,
    original_indices: bytes,
) -> tuple[bytes, dict[str, Any]]:
    if edited_image.size != TITLE_SIZE:
        raise ValueError(
            f"edited title must be {TITLE_SIZE[0]}x{TITLE_SIZE[1]}, "
            f"got {edited_image.width}x{edited_image.height}"
        )
    rgba = edited_image.convert("RGBA")
    pixels = list(rgba.get_flattened_data())
    if len(pixels) != len(original_indices):
        raise ValueError("edited title pixel count differs from original index plane")

    words = palette_words(
        record_from_bytes(
            b"\x00\x00\x00\x00\x00\x01\x01\x00" + palette_payload,
            TITLE_UNIT,
            PALETTE_CHILD,
        )
    )
    colors = [bgr555_color(word)[:3] for word in words]
    candidates: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, color in enumerate(colors):
        candidates[color].append(index)

    # Indexed editors commonly compact/reorder the palette on export.  Learn
    # the safest duplicate-color mapping from visually unchanged coordinates,
    # while retaining the original index byte exactly at those coordinates.
    source_indices = (
        list(edited_image.get_flattened_data())
        if edited_image.mode == "P"
        else None
    )
    source_votes: dict[int, Counter[int]] = defaultdict(Counter)
    if source_indices is not None:
        for source_index, pixel, original_index in zip(
            source_indices, pixels, original_indices
        ):
            rgb = pixel[:3]
            if pixel[3] and rgb != PURPLE and rgb == colors[original_index]:
                source_votes[source_index][original_index] += 1

    output = bytearray(len(original_indices))
    transparent_count = 0
    visually_changed_count = 0
    ambiguous_fallback_count = 0
    for position, (pixel, original_index) in enumerate(zip(pixels, original_indices)):
        rgb = pixel[:3]
        if pixel[3] == 0 or rgb == PURPLE:
            output[position] = TRANSPARENT_INDEX
            transparent_count += 1
            if original_index != TRANSPARENT_INDEX:
                visually_changed_count += 1
            continue
        if rgb == colors[original_index]:
            output[position] = original_index
            continue
        matches = candidates.get(rgb, [])
        if not matches:
            x = position % TITLE_SIZE[0]
            y = position // TITLE_SIZE[0]
            raise ValueError(
                f"edited title uses color {rgb} outside the original CLUT at {x},{y}"
            )
        chosen: int | None = None
        if source_indices is not None:
            votes = source_votes.get(source_indices[position])
            if votes:
                for candidate, _count in votes.most_common():
                    if candidate in matches:
                        chosen = candidate
                        break
        if chosen is None:
            chosen = matches[0]
            if len(matches) > 1:
                ambiguous_fallback_count += 1
        output[position] = chosen
        visually_changed_count += 1

    return bytes(output), {
        "canvas": [*TITLE_SIZE],
        "source_mode": edited_image.mode,
        "purple_rgb": "#FF00FF",
        "purple_or_alpha_transparent_pixel_count": transparent_count,
        "visually_changed_pixel_count": visually_changed_count,
        "ambiguous_color_fallback_pixel_count": ambiguous_fallback_count,
        "palette_policy": "original-256-color-bgr555-clut-byte-exact",
        "unchanged_pixel_policy": "preserve-original-index-byte",
    }


def build_title_graphics_patch(
    *,
    file_build_dir: Path,
    source_root: Path,
    boot_exe_name: str,
    edited_image_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    source_start_path = source_root / "START.BIN"
    source_start = source_start_path.read_bytes()
    if sha256_bytes(source_start) != EXPECTED_START_SHA256:
        raise ValueError("verified original START.BIN hash differs")
    input_start = (file_build_dir / "START.BIN").read_bytes()
    if sha256_bytes(input_start) != base_manifest["outputs"]["START.BIN"]["sha256"]:
        raise ValueError("base file-build START.BIN hash differs")

    payload_start, payload_end, palette_payload, original_indices = _title_records(
        source_start, source_root, boot_exe_name
    )
    if input_start[payload_start:payload_end] != original_indices:
        raise ValueError("base file build already changes the title index payload")
    with Image.open(edited_image_path) as edited:
        replacement, report = remap_edited_title(
            edited,
            palette_payload=palette_payload,
            original_indices=original_indices,
        )
    patched_start = bytearray(input_start)
    patched_start[payload_start:payload_end] = replacement
    patched_start = bytes(patched_start)
    expected = verify_expected_writes(
        input_start,
        patched_start,
        allowed_ranges=[(payload_start, payload_end)],
        owner="START.BIN title-screen 8bpp index payload",
    )
    if not expected["changed_byte_count"]:
        raise ValueError("edited title does not change the source title image")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, bytes] = {}
    for name, metadata in base_manifest["outputs"].items():
        if name == "glyph_map":
            continue
        source_path = file_build_dir / name
        if not source_path.is_file():
            continue
        payload = source_path.read_bytes()
        if sha256_bytes(payload) != metadata["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")
        if name == "START.BIN":
            payload = patched_start
        (output_dir / name).write_bytes(payload)
        outputs[name] = payload
    map_name = "primary-korean-glyph-map.json"
    if (file_build_dir / map_name).is_file():
        shutil.copyfile(file_build_dir / map_name, output_dir / map_name)

    sources = copy.deepcopy(base_manifest["sources"])
    sources["title_graphics_edit"] = {
        "path": str(edited_image_path.resolve()),
        "sha256": sha256_file(edited_image_path),
    }
    sources["title_graphics_base_file_build_manifest"] = {
        "path": str(base_manifest_path.resolve()),
        "sha256": sha256_file(base_manifest_path),
    }
    manifest = {
        **base_manifest,
        "sources": sources,
        "title_graphics": {
            "status": "static-injection-user-runtime-validation-required",
            "unit": TITLE_UNIT,
            "palette_child": PALETTE_CHILD,
            "image_child": IMAGE_CHILD,
            "payload_range": [f"0x{payload_start:X}", f"0x{payload_end:X}"],
            "replacement_indices_sha256": hashlib.sha256(replacement).hexdigest(),
            "clut_unchanged": True,
            **report,
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "title_graphics": {"START.BIN_relative_to_base": expected},
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
        "--source-root", type=Path, default=Path("work/extracted/disc1/iso")
    )
    parser.add_argument("--boot-exe", default="SLPS_019.58")
    parser.add_argument(
        "--image",
        type=Path,
        default=Path(
            "work/graphics/title-chapter/title/title-screen/"
            "edit-template-purple-import.png"
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_title_graphics_patch(
        file_build_dir=args.file_build_dir,
        source_root=args.source_root,
        boot_exe_name=args.boot_exe,
        edited_image_path=args.image,
        output_dir=args.output_dir,
    )
    title = manifest["title_graphics"]
    print(
        f"changed_pixels={title['visually_changed_pixel_count']} "
        f"START={manifest['outputs']['START.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
