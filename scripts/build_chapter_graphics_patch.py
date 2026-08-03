#!/usr/bin/env python3
"""Insert all eleven edited 320x240 chapter cards into START.BIN units 24..34."""

from __future__ import annotations

import argparse
import copy
import hashlib
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
    from scripts.build_title_graphics_patch import EXPECTED_START_SHA256
    from scripts.extract_title_chapter_graphics import (
        ASSETS,
        CHAPTER_SCREEN_SEGMENTS,
        EXPECTED_UNIT_SHA256,
        assemble_chapter_screen,
        start_schedule,
    )
    from scripts.psx_layout import parse_offset_directory
    from scripts.psx_vram_render import bgr555_color, palette_words, record_from_bytes
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from build_title_graphics_patch import EXPECTED_START_SHA256
    from extract_title_chapter_graphics import (
        ASSETS,
        CHAPTER_SCREEN_SEGMENTS,
        EXPECTED_UNIT_SHA256,
        assemble_chapter_screen,
        start_schedule,
    )
    from psx_layout import parse_offset_directory
    from psx_vram_render import bgr555_color, palette_words, record_from_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHAPTER_SIZE = (320, 240)
STORED_SIZE = (512, 256)


def chapter_assets() -> tuple[dict[str, Any], ...]:
    return tuple(asset for asset in ASSETS if asset["category"] == "chapter")


def expected_png_palette(words: list[int]) -> list[int]:
    palette: list[int] = []
    for word in words:
        red, green, blue, _alpha = bgr555_color(word)
        palette.extend((red, green, blue))
    return palette


def expected_png_transparency(words: list[int]) -> bytes:
    return bytes(bgr555_color(word)[3] for word in words)


def normalized_png_transparency(value: int | bytes | None) -> bytes:
    if isinstance(value, int):
        if not 0 <= value < 256:
            raise ValueError("PNG transparent palette index is out of range")
        alpha = bytearray(b"\xFF" * 256)
        alpha[value] = 0
        return bytes(alpha)
    if isinstance(value, bytes):
        if len(value) > 256:
            raise ValueError("PNG palette transparency has more than 256 entries")
        return value + b"\xFF" * (256 - len(value))
    return b"\xFF" * 256


def scatter_chapter_screen(
    stored_indices: bytes, replacement_screen: bytes
) -> bytes:
    if len(stored_indices) != STORED_SIZE[0] * STORED_SIZE[1]:
        raise ValueError("stored chapter index plane is not 512x256")
    if len(replacement_screen) != CHAPTER_SIZE[0] * CHAPTER_SIZE[1]:
        raise ValueError("replacement chapter screen is not 320x240")
    output = bytearray(stored_indices)
    for y in range(CHAPTER_SIZE[1]):
        screen_row = y * CHAPTER_SIZE[0]
        stored_row = y * STORED_SIZE[0]
        destination_x = 0
        for source_left, source_right in CHAPTER_SCREEN_SEGMENTS:
            width = source_right - source_left
            output[
                stored_row + source_left : stored_row + source_right
            ] = replacement_screen[
                screen_row + destination_x : screen_row + destination_x + width
            ]
            destination_x += width
    return bytes(output)


def _indexed_screen_from_payload(payload: bytes, words: list[int]) -> Image.Image:
    stored = Image.frombytes("P", STORED_SIZE, payload)
    screen = assemble_chapter_screen(stored)
    screen.putpalette(expected_png_palette(words))
    screen.info["transparency"] = expected_png_transparency(words)
    return screen


def _load_edited_indices(path: Path, words: list[int]) -> tuple[bytes, str]:
    with Image.open(path) as image:
        if image.mode != "P":
            raise ValueError(f"{path}: chapter export must remain indexed mode P")
        if image.size != CHAPTER_SIZE:
            raise ValueError(
                f"{path}: chapter export must be 320x240, got {image.size}"
            )
        palette = (image.getpalette() or [])[: 256 * 3]
        if palette != expected_png_palette(words):
            raise ValueError(f"{path}: original 256-color CLUT was changed")
        if normalized_png_transparency(
            image.info.get("transparency")
        ) != expected_png_transparency(words):
            raise ValueError(f"{path}: original palette transparency was changed")
        return bytes(image.get_flattened_data()), image.mode


def build_chapter_graphics_patch(
    *,
    file_build_dir: Path,
    source_root: Path,
    boot_exe_name: str,
    edits_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    assets = chapter_assets()
    if len(assets) != 11 or [asset["unit"] for asset in assets] != list(range(24, 35)):
        raise ValueError("chapter asset population differs from units 24..34")

    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    source_start_path = source_root / "START.BIN"
    source_start = source_start_path.read_bytes()
    if sha256_bytes(source_start) != EXPECTED_START_SHA256:
        raise ValueError("verified original Disc 1 START.BIN hash differs")
    input_start = (file_build_dir / "START.BIN").read_bytes()
    if sha256_bytes(input_start) != base_manifest["outputs"]["START.BIN"]["sha256"]:
        raise ValueError("base file-build START.BIN hash differs")

    schedule = start_schedule(source_root, boot_exe_name)
    patched_start = bytearray(input_start)
    all_allowed_ranges: list[tuple[int, int]] = []
    reports: list[dict[str, Any]] = []
    edit_sources: dict[str, Any] = {}

    for asset in assets:
        unit_index = int(asset["unit"])
        span = schedule[unit_index]
        unit_start = int(span["byte_offset"])
        unit_end = int(span["byte_end"])
        source_unit = source_start[unit_start:unit_end]
        if sha256_bytes(source_unit) != EXPECTED_UNIT_SHA256[unit_index]:
            raise ValueError(f"START.BIN chapter unit {unit_index} hash differs")
        if input_start[unit_start:unit_end] != source_unit:
            raise ValueError(
                f"base file build already changes chapter unit {unit_index}"
            )

        offsets = parse_offset_directory(source_unit)
        palette_child = int(asset["palette_child"])
        image_child = int(asset["image_child"])
        if offsets is None or len(offsets) <= image_child:
            raise ValueError(f"chapter unit {unit_index} child directory differs")
        palette_raw = source_unit[offsets[palette_child] : offsets[palette_child + 1]]
        image_end = offsets[image_child + 1] if image_child + 1 < len(offsets) else len(source_unit)
        image_raw = source_unit[offsets[image_child] : image_end]
        palette_record = record_from_bytes(palette_raw, unit_index, palette_child)
        image_record = record_from_bytes(image_raw, unit_index, image_child)
        words = palette_words(palette_record)
        if len(words) != 256:
            raise ValueError(f"chapter unit {unit_index} CLUT is not 256 colors")
        if (image_record.width_halfwords * 2, image_record.height) != STORED_SIZE:
            raise ValueError(f"chapter unit {unit_index} texture is not 512x256 8bpp")

        edit_path = edits_root / str(asset["asset_id"]) / "assembled-indexed-320x240-export.png"
        if not edit_path.is_file():
            raise FileNotFoundError(f"missing chapter export: {edit_path}")
        replacement_screen, source_mode = _load_edited_indices(edit_path, words)
        original_screen_image = _indexed_screen_from_payload(image_record.payload, words)
        original_screen = bytes(original_screen_image.get_flattened_data())
        changed_pixels = sum(
            left != right for left, right in zip(original_screen, replacement_screen)
        )
        if not changed_pixels:
            raise ValueError(f"{asset['asset_id']}: export does not change the chapter")

        replacement_payload = scatter_chapter_screen(
            image_record.payload, replacement_screen
        )
        unit_payload_start = offsets[image_child] + 8
        unit_payload_end = unit_payload_start + len(image_record.payload)
        replacement_unit = bytearray(source_unit)
        replacement_unit[unit_payload_start:unit_payload_end] = replacement_payload
        payload_start = unit_start + unit_payload_start
        payload_end = payload_start + len(image_record.payload)
        patched_start[payload_start:payload_end] = replacement_payload

        unit_allowed: list[tuple[int, int]] = []
        for y in range(CHAPTER_SIZE[1]):
            row_start = payload_start + y * STORED_SIZE[0]
            unit_row_start = unit_payload_start + y * STORED_SIZE[0]
            for source_left, source_right in CHAPTER_SCREEN_SEGMENTS:
                allowed = (row_start + source_left, row_start + source_right)
                all_allowed_ranges.append(allowed)
                unit_allowed.append(
                    (unit_row_start + source_left, unit_row_start + source_right)
                )
        unit_expected = verify_expected_writes(
            source_unit,
            bytes(replacement_unit),
            allowed_ranges=unit_allowed,
            owner=f"START.BIN chapter unit {unit_index} 320x240 assembled screen",
        )

        inserted = _indexed_screen_from_payload(replacement_payload, words)
        inserted_indices = bytes(inserted.get_flattened_data())
        if inserted_indices != replacement_screen:
            raise AssertionError(f"{asset['asset_id']}: scatter/reassemble differs")
        preview_path = output_dir / f"{asset['asset_id']}-inserted-indexed.png"
        output_dir.mkdir(parents=True, exist_ok=True)
        inserted.save(preview_path, transparency=expected_png_transparency(words))

        edit_sources[str(asset["asset_id"])] = {
            "path": str(edit_path.resolve()),
            "sha256": sha256_file(edit_path),
        }
        reports.append(
            {
                "asset_id": asset["asset_id"],
                "unit": unit_index,
                "source_mode": source_mode,
                "canvas": list(CHAPTER_SIZE),
                "stored_canvas": list(STORED_SIZE),
                "screen_segments": [list(segment) for segment in CHAPTER_SCREEN_SEGMENTS],
                "protected_stored_ranges": {
                    "wrap_gap_x": [240, 256],
                    "right_remainder_x": [336, 512],
                    "bottom_rows_y": [240, 256],
                },
                "changed_pixel_count": changed_pixels,
                "replacement_screen_indices_sha256": hashlib.sha256(
                    replacement_screen
                ).hexdigest(),
                "replacement_payload_sha256": hashlib.sha256(
                    replacement_payload
                ).hexdigest(),
                "preview": {
                    "path": str(preview_path.resolve()),
                    "sha256": sha256_file(preview_path),
                },
                "clut_unchanged": True,
                "expected_writes_relative_to_base": unit_expected,
            }
        )

    patched_start_bytes = bytes(patched_start)
    expected = verify_expected_writes(
        input_start,
        patched_start_bytes,
        allowed_ranges=all_allowed_ranges,
        owner="START.BIN chapter units 24..34 assembled indexed exports",
    )

    outputs: dict[str, bytes] = {}
    output_dir.mkdir(parents=True, exist_ok=True)
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
            payload = patched_start_bytes
        (output_dir / name).write_bytes(payload)
        outputs[name] = payload
    map_name = "primary-korean-glyph-map.json"
    if (file_build_dir / map_name).is_file():
        shutil.copyfile(file_build_dir / map_name, output_dir / map_name)

    sources = copy.deepcopy(base_manifest["sources"])
    sources["chapter_graphics_edits"] = edit_sources
    sources["chapter_graphics_base_file_build_manifest"] = {
        "path": str(base_manifest_path.resolve()),
        "sha256": sha256_file(base_manifest_path),
    }
    manifest = {
        **base_manifest,
        "sources": sources,
        "chapter_graphics": {
            "status": "static-injection-user-runtime-validation-required",
            "file": "START.BIN",
            "units": [asset["unit"] for asset in assets],
            "entry_count": len(reports),
            "clut_policy": "all-original-256-color-bgr555-cluts-byte-preserved",
            "index_policy": "edited-assembled-screen-indices-scattered-to-original-storage-segments",
            "entries": reports,
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "chapter_graphics": {"START.BIN_relative_to_base": expected},
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
        "--edits-root",
        type=Path,
        default=Path("work/graphics/title-chapter/chapters"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_chapter_graphics_patch(
        file_build_dir=args.file_build_dir,
        source_root=args.source_root,
        boot_exe_name=args.boot_exe,
        edits_root=args.edits_root,
        output_dir=args.output_dir,
    )
    expected = manifest["expected_writes"]["chapter_graphics"][
        "START.BIN_relative_to_base"
    ]
    print(
        f"chapters={manifest['chapter_graphics']['entry_count']} "
        f"changed_bytes={expected['changed_byte_count']} "
        f"START={manifest['outputs']['START.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
