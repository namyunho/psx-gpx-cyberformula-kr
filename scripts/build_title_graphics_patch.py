#!/usr/bin/env python3
"""Insert an edited 256x256 retail-title atlas into START.BIN unit 21.

The retail title is the final 4bpp page of unit 21 child 4.  Its pixels store
only the low four-bit index; the GPU primitive selects one of the sixteen CLUT
banks in child 2.  Indexed image editors may compact the exported PNG palette,
so this importer compares rendered RGB and quantizes only the intentionally
edited title regions back into their original CLUT bank.
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter, deque
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
    from scripts.extract_title_chapter_graphics import start_schedule
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
    from extract_title_chapter_graphics import start_schedule
    from psx_layout import parse_offset_directory
    from psx_vram_render import bgr555_color, palette_words, record_from_bytes


EXPECTED_START_SHA256 = (
    "d0b22efb4e5ea46c869f822af9bc7f207bc95a670a25acb15fc3dcd2ab3bf8cc"
)
EXPECTED_TITLE_UNIT_SHA256 = (
    "e7ed71075b1ec88e559e552580cc7e7975a513b265bddcfe097c946b9dc11f4e"
)
TITLE_UNIT = 21
PALETTE_CHILD = 2
IMAGE_CHILD = 4
TITLE_SIZE = (256, 256)
IMAGE_ROW_BYTES = 512
TITLE_ROW_BYTE_OFFSET = 384
TITLE_ROW_BYTES = 128
PURPLE = (255, 0, 255)
TRANSPARENT_INDEX = 0

# These connected-component boxes select the CLUT used by the retail GPU
# primitives.  Other nontransparent components use neutral menu bank 8.
MAIN_TITLE_COMPONENTS = {
    (0, 58, 108, 94),
    (82, 58, 153, 94),
    (151, 58, 182, 94),
    (191, 58, 219, 65),
    (174, 68, 215, 94),
    (138, 85, 161, 94),
}
MAIN_EMBLEM_COMPONENTS = {
    (0, 96, 113, 170),
    (36, 123, 70, 199),
    (78, 124, 238, 143),
    (85, 130, 150, 147),
    (155, 130, 239, 147),
    (240, 133, 248, 142),
    (72, 152, 122, 174),
    (136, 154, 146, 166),
    (0, 164, 32, 207),
}


def _component_labels(
    local_indices: bytes,
) -> tuple[list[int], dict[int, tuple[int, int, int, int]]]:
    remaining = {index for index, value in enumerate(local_indices) if value}
    labels = [-1] * len(local_indices)
    boxes: dict[int, tuple[int, int, int, int]] = {}
    label = 0
    while remaining:
        seed = remaining.pop()
        queue = deque([seed])
        members = [seed]
        while queue:
            current = queue.popleft()
            x, y = current % TITLE_SIZE[0], current // TITLE_SIZE[0]
            for neighbor_y in range(max(0, y - 1), min(TITLE_SIZE[1], y + 2)):
                for neighbor_x in range(max(0, x - 1), min(TITLE_SIZE[0], x + 2)):
                    neighbor = neighbor_y * TITLE_SIZE[0] + neighbor_x
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        queue.append(neighbor)
                        members.append(neighbor)
        xs = [member % TITLE_SIZE[0] for member in members]
        ys = [member // TITLE_SIZE[0] for member in members]
        boxes[label] = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        for member in members:
            labels[member] = label
        label += 1
    return labels, boxes


def _authoring_bank(
    x: int,
    local_index: int,
    component_box: tuple[int, int, int, int] | None,
) -> int:
    if local_index == 0:
        return 0
    if component_box == (0, 2, 243, 32):
        return 1 if x < 137 else 2
    if component_box in MAIN_TITLE_COMPONENTS:
        return 3
    if component_box in MAIN_EMBLEM_COMPONENTS:
        return 0
    return 8


def _edited_bank(x: int, y: int) -> int | None:
    """Return the fixed CLUT bank for the four user-editable title regions."""
    if 0 <= x < 137 and 2 <= y < 32:
        return 1
    if 137 <= x < 244 and 2 <= y < 32:
        return 2
    if 0 <= x < 220 and 56 <= y < 96:
        return 3
    if 0 <= x < 96 and 238 <= y < 256:
        return 8
    return None


def _title_records(
    source_start: bytes, source_root: Path, boot_exe_name: str
) -> tuple[int, int, bytes, bytes, bytes]:
    schedule = start_schedule(source_root, boot_exe_name)
    span = schedule[TITLE_UNIT]
    unit = source_start[span["byte_offset"] : span["byte_end"]]
    digest = sha256_bytes(unit)
    if digest != EXPECTED_TITLE_UNIT_SHA256:
        raise ValueError(
            "START.BIN retail-title unit mismatch: expected "
            f"{EXPECTED_TITLE_UNIT_SHA256}, got {digest}"
        )
    offsets = parse_offset_directory(unit)
    if offsets is None or len(offsets) <= IMAGE_CHILD:
        raise ValueError("START.BIN retail-title unit has no expected child directory")
    palette_raw = unit[offsets[PALETTE_CHILD] : offsets[PALETTE_CHILD + 1]]
    image_raw = unit[offsets[IMAGE_CHILD] :]
    palette_record = record_from_bytes(palette_raw, TITLE_UNIT, PALETTE_CHILD)
    image_record = record_from_bytes(image_raw, TITLE_UNIT, IMAGE_CHILD)
    if (image_record.width_halfwords, image_record.height) != (256, 256):
        raise ValueError("START.BIN retail-title backing image dimensions differ")
    if len(palette_words(palette_record)) != 256:
        raise ValueError("START.BIN retail-title CLUT is not 16 banks of 16 colors")
    if len(image_record.payload) != IMAGE_ROW_BYTES * TITLE_SIZE[1]:
        raise ValueError("START.BIN retail-title image payload size differs")

    local_indices = bytearray()
    for y in range(TITLE_SIZE[1]):
        row_start = y * IMAGE_ROW_BYTES + TITLE_ROW_BYTE_OFFSET
        for value in image_record.payload[row_start : row_start + TITLE_ROW_BYTES]:
            local_indices.extend((value & 0x0F, value >> 4))
    if len(local_indices) != TITLE_SIZE[0] * TITLE_SIZE[1]:
        raise AssertionError("retail-title 4bpp page decode size differs")

    payload_start = span["byte_offset"] + offsets[IMAGE_CHILD] + 8
    payload_end = payload_start + len(image_record.payload)
    return (
        payload_start,
        payload_end,
        palette_record.payload,
        image_record.payload,
        bytes(local_indices),
    )


def _palette_colors(palette_payload: bytes) -> list[tuple[int, int, int]]:
    record = record_from_bytes(
        b"\x00\x00\x00\x00\x00\x01\x01\x00" + palette_payload,
        TITLE_UNIT,
        PALETTE_CHILD,
    )
    return [bgr555_color(word)[:3] for word in palette_words(record)]


def _is_transparent(pixel: tuple[int, int, int, int]) -> bool:
    return pixel[3] < 255 or pixel[:3] == PURPLE


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
    pixels = list(edited_image.convert("RGBA").get_flattened_data())
    if len(pixels) != len(original_indices):
        raise ValueError("edited title pixel count differs from original 4bpp page")

    colors = _palette_colors(palette_payload)
    labels, boxes = _component_labels(original_indices)
    output = bytearray(original_indices)
    changed_by_bank: Counter[int] = Counter()
    exact_by_bank: Counter[int] = Counter()
    nonexact_by_bank: Counter[int] = Counter()
    cleared_by_bank: Counter[int] = Counter()
    distance_sum_by_bank: Counter[int] = Counter()
    max_distance_by_bank: Counter[int] = Counter()

    for position, (pixel, original_index) in enumerate(zip(pixels, original_indices)):
        x, y = position % TITLE_SIZE[0], position // TITLE_SIZE[0]
        label = labels[position]
        box = boxes[label] if label >= 0 else None
        original_bank = _authoring_bank(x, original_index, box)
        original_transparent = original_index == 0
        edited_transparent = _is_transparent(pixel)
        if edited_transparent and original_transparent:
            continue
        original_rgb = colors[original_bank * 16 + original_index]
        if not edited_transparent and pixel[:3] == original_rgb:
            continue

        bank = _edited_bank(x, y)
        if bank is None:
            raise ValueError(
                "edited title changes a protected menu/emblem pixel at "
                f"{x},{y}: original={original_rgb}, edited={pixel}"
            )
        changed_by_bank[bank] += 1
        if edited_transparent:
            output[position] = TRANSPARENT_INDEX
            cleared_by_bank[bank] += 1
            continue

        rgb = pixel[:3]
        candidates = [
            (
                sum((rgb[channel] - colors[bank * 16 + local][channel]) ** 2 for channel in range(3)),
                local,
            )
            for local in range(1, 16)
        ]
        distance, local_index = min(candidates)
        output[position] = local_index
        distance_sum_by_bank[bank] += distance
        max_distance_by_bank[bank] = max(max_distance_by_bank[bank], distance)
        if distance == 0:
            exact_by_bank[bank] += 1
        else:
            nonexact_by_bank[bank] += 1

    bank_report: dict[str, Any] = {}
    for bank in sorted(changed_by_bank):
        opaque = exact_by_bank[bank] + nonexact_by_bank[bank]
        bank_report[str(bank)] = {
            "changed_pixels": changed_by_bank[bank],
            "cleared_pixels": cleared_by_bank[bank],
            "exact_palette_pixels": exact_by_bank[bank],
            "nearest_palette_pixels": nonexact_by_bank[bank],
            "mean_squared_rgb_distance": (
                distance_sum_by_bank[bank] / opaque if opaque else 0
            ),
            "maximum_squared_rgb_distance": max_distance_by_bank[bank],
        }

    return bytes(output), {
        "canvas": [*TITLE_SIZE],
        "source_mode": edited_image.mode,
        "purple_rgb": "#FF00FF",
        "visually_changed_pixel_count": sum(changed_by_bank.values()),
        "changed_pixels_by_clut_bank": bank_report,
        "palette_policy": "nearest-original-bgr555-color-within-fixed-clut-bank",
        "transparent_policy": "alpha-below-255-or-FF00FF-becomes-local-index-0",
        "protected_policy": "all-pixels-outside-four-title-text-regions-byte-preserved",
    }


def _pack_title_page(original_payload: bytes, local_indices: bytes) -> bytes:
    if len(local_indices) != TITLE_SIZE[0] * TITLE_SIZE[1]:
        raise ValueError("replacement local-index plane size differs")
    output = bytearray(original_payload)
    for y in range(TITLE_SIZE[1]):
        source = y * TITLE_SIZE[0]
        target = y * IMAGE_ROW_BYTES + TITLE_ROW_BYTE_OFFSET
        for x in range(0, TITLE_SIZE[0], 2):
            low = local_indices[source + x]
            high = local_indices[source + x + 1]
            if low > 15 or high > 15:
                raise ValueError("replacement contains an index outside 4bpp range")
            output[target + x // 2] = low | (high << 4)
    return bytes(output)


def _save_quantized_preview(
    path: Path,
    *,
    palette_payload: bytes,
    original_indices: bytes,
    replacement_indices: bytes,
) -> None:
    colors = _palette_colors(palette_payload)
    labels, boxes = _component_labels(original_indices)
    image = Image.new("RGB", TITLE_SIZE, PURPLE)
    rendered: list[tuple[int, int, int]] = []
    for position, local_index in enumerate(replacement_indices):
        x, y = position % TITLE_SIZE[0], position // TITLE_SIZE[0]
        if local_index == 0:
            rendered.append(PURPLE)
            continue
        edited_bank = _edited_bank(x, y)
        if edited_bank is not None and replacement_indices[position] != original_indices[position]:
            bank = edited_bank
        else:
            label = labels[position]
            box = boxes[label] if label >= 0 else None
            bank = _authoring_bank(x, original_indices[position], box)
        rendered.append(colors[bank * 16 + local_index])
    image.putdata(rendered)
    image.save(path)


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
        raise ValueError("verified original Disc 1 START.BIN hash differs")
    input_start = (file_build_dir / "START.BIN").read_bytes()
    if sha256_bytes(input_start) != base_manifest["outputs"]["START.BIN"]["sha256"]:
        raise ValueError("base file-build START.BIN hash differs")

    (
        payload_start,
        payload_end,
        palette_payload,
        original_payload,
        original_indices,
    ) = _title_records(source_start, source_root, boot_exe_name)
    if input_start[payload_start:payload_end] != original_payload:
        raise ValueError("base file build already changes the retail-title image payload")
    with Image.open(edited_image_path) as edited:
        replacement_indices, report = remap_edited_title(
            edited,
            palette_payload=palette_payload,
            original_indices=original_indices,
        )
    replacement_payload = _pack_title_page(original_payload, replacement_indices)
    patched_start = bytearray(input_start)
    patched_start[payload_start:payload_end] = replacement_payload
    patched_start = bytes(patched_start)
    allowed_ranges = [
        (
            payload_start + y * IMAGE_ROW_BYTES + TITLE_ROW_BYTE_OFFSET,
            payload_start + y * IMAGE_ROW_BYTES + TITLE_ROW_BYTE_OFFSET + TITLE_ROW_BYTES,
        )
        for y in range(TITLE_SIZE[1])
    ]
    expected = verify_expected_writes(
        input_start,
        patched_start,
        allowed_ranges=allowed_ranges,
        owner="START.BIN retail-title unit21 child4 final 4bpp page",
    )
    if not expected["changed_byte_count"]:
        raise ValueError("edited retail title does not change the source 4bpp page")

    output_dir.mkdir(parents=True, exist_ok=True)
    preview_path = output_dir / "retail-title-quantized-preview-purple.png"
    _save_quantized_preview(
        preview_path,
        palette_payload=palette_payload,
        original_indices=original_indices,
        replacement_indices=replacement_indices,
    )
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
    sources["retail_title_graphics_edit"] = {
        "path": str(edited_image_path.resolve()),
        "sha256": sha256_file(edited_image_path),
    }
    sources["retail_title_graphics_base_file_build_manifest"] = {
        "path": str(base_manifest_path.resolve()),
        "sha256": sha256_file(base_manifest_path),
    }
    manifest = {
        **base_manifest,
        "sources": sources,
        "title_graphics": {
            "status": "static-injection-user-runtime-validation-required",
            "source": "retail START.BIN unit 21 (not unit 8 TGS demo residue)",
            "unit": TITLE_UNIT,
            "palette_child": PALETTE_CHILD,
            "image_child": IMAGE_CHILD,
            "page": {"vram_x": 960, "vram_y": 0, "width": 256, "height": 256},
            "image_payload_range": [f"0x{payload_start:X}", f"0x{payload_end:X}"],
            "replacement_indices_sha256": hashlib.sha256(replacement_indices).hexdigest(),
            "replacement_payload_sha256": hashlib.sha256(replacement_payload).hexdigest(),
            "quantized_preview": {
                "path": str(preview_path.resolve()),
                "sha256": sha256_file(preview_path),
            },
            "clut_unchanged": True,
            **report,
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "retail_title_graphics": {"START.BIN_relative_to_base": expected},
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
            "work/graphics/title-chapter/title/retail-title-screen/"
            "retail-title-unified-preview-purple-export_import.png"
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
        f"changed_bytes={manifest['expected_writes']['retail_title_graphics']['START.BIN_relative_to_base']['changed_byte_count']} "
        f"START={manifest['outputs']['START.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
