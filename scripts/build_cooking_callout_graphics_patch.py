#!/usr/bin/env python3
"""Insert the two approved Korean cooking callout labels into MINI_G3.BIN."""

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
    from scripts.extract_cooking_speech_bubbles import (
        COMPONENTS,
        EXPECTED_MINI_G3_SHA256,
        UNIT1_RANGE,
        decode_4bpp,
        indexed_image,
    )
    from scripts.psx_vram_render import palette_words, unit_records
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from extract_cooking_speech_bubbles import (
        COMPONENTS,
        EXPECTED_MINI_G3_SHA256,
        UNIT1_RANGE,
        decode_4bpp,
        indexed_image,
    )
    from psx_vram_render import palette_words, unit_records


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNIT1_IMAGE_PAYLOAD_OFFSET = 0x18818
TEXTURE_WIDTH = 512
TEXTURE_HEIGHT = 512
CALLOUT_IDS = ("callout-yakiagare", "callout-rendaa")
EDIT_FILENAMES = {
    "callout-yakiagare": "callout-yakiagare-indexed-export.png",
    "callout-rendaa": "callout-rendaa-indexed-export.png",
}
KOREAN_LABELS = {
    "callout-yakiagare": "구워져라",
    "callout-rendaa": "연타!",
}


def _component_map() -> dict[str, dict[str, Any]]:
    return {
        str(component["id"]): component
        for component in COMPONENTS
        if component["id"] in CALLOUT_IDS
    }


def _pixel_offset(x: int, y: int) -> tuple[int, int]:
    if not (0 <= x < TEXTURE_WIDTH and 0 <= y < TEXTURE_HEIGHT):
        raise ValueError(f"MINI_G3 texture coordinate is out of range: {x},{y}")
    offset = UNIT1_IMAGE_PAYLOAD_OFFSET + y * (TEXTURE_WIDTH // 2) + x // 2
    return offset, 4 if x & 1 else 0


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


def _normalized_transparency(value: int | bytes | None) -> bytes:
    if isinstance(value, int):
        alpha = bytearray(b"\xFF" * 256)
        alpha[value] = 0
        return bytes(alpha)
    if isinstance(value, bytes):
        if len(value) > 256:
            raise ValueError("PNG palette transparency exceeds 256 entries")
        return value + b"\xFF" * (256 - len(value))
    return b"\xFF" * 256


def _original_cluts(source: bytes) -> dict[int, list[int]]:
    unit = source[slice(*UNIT1_RANGE)]
    records = {record.child_index: record for record in unit_records(unit, 1)}
    image_record = records[0]
    if (image_record.width_halfwords * 4, image_record.height) != (
        TEXTURE_WIDTH,
        TEXTURE_HEIGHT,
    ):
        raise ValueError("MINI_G3 unit-1 atlas dimensions differ")
    # Decode once here so malformed storage cannot be accepted merely because the
    # requested rectangles happen to be addressable.
    decode_4bpp(image_record.payload, TEXTURE_WIDTH, TEXTURE_HEIGHT)
    words = palette_words(records[2])
    return {bank: words[bank * 16 : (bank + 1) * 16] for bank in (9, 13)}


def _load_edit(
    path: Path,
    *,
    expected_size: tuple[int, int],
    clut_words: list[int],
) -> tuple[bytes, str]:
    expected = indexed_image(
        bytes(expected_size[0] * expected_size[1]),
        expected_size[0],
        expected_size[1],
        clut_words,
    )
    with Image.open(path) as image:
        if image.mode != "P":
            raise ValueError(f"{path}: callout export must remain indexed mode P")
        if image.size != expected_size:
            raise ValueError(
                f"{path}: callout export must be {expected_size[0]}x{expected_size[1]}"
            )
        if (image.getpalette() or [])[: 256 * 3] != expected.getpalette()[: 256 * 3]:
            raise ValueError(f"{path}: original 16-color CLUT was changed")
        if _normalized_transparency(image.info.get("transparency")) != (
            _normalized_transparency(expected.info.get("transparency"))
        ):
            raise ValueError(f"{path}: original palette transparency was changed")
        indices = bytes(image.get_flattened_data())
    if any(value > 0xF for value in indices):
        raise ValueError(f"{path}: callout uses a palette index above 15")
    return indices, "P"


def patch_callouts(
    *, source: bytes, base: bytes, edits_root: Path
) -> tuple[bytes, list[dict[str, Any]], list[tuple[int, int]], dict[str, Any]]:
    if sha256_bytes(source) != EXPECTED_MINI_G3_SHA256:
        raise ValueError("MINI_G3.BIN verified original hash differs")
    if len(base) != len(source):
        raise ValueError("base MINI_G3.BIN size differs from verified original")
    components = _component_map()
    if set(components) != set(CALLOUT_IDS):
        raise ValueError("cooking callout component inventory differs")
    cluts = _original_cluts(source)
    patched = bytearray(base)
    reports: list[dict[str, Any]] = []
    allowed: list[tuple[int, int]] = []
    edit_sources: dict[str, Any] = {}
    occupied: set[tuple[int, int]] = set()

    for component_id in CALLOUT_IDS:
        component = components[component_id]
        rect = tuple(int(value) for value in component["rect"])
        x, y, width, height = rect
        if x & 1 or width & 1:
            raise ValueError(f"{component_id}: packed rectangle must be byte-aligned")
        edit_path = edits_root / EDIT_FILENAMES[component_id]
        if not edit_path.is_file():
            raise FileNotFoundError(f"missing cooking callout export: {edit_path}")
        palette_bank = int(component["palette_bank"])
        replacement, source_mode = _load_edit(
            edit_path,
            expected_size=(width, height),
            clut_words=cluts[palette_bank],
        )
        original_indices = _rect_indices(source, rect)
        base_indices = _rect_indices(base, rect)
        if base_indices != original_indices:
            raise ValueError(
                f"{component_id}: base file build already changes this callout rectangle"
            )
        if replacement == original_indices:
            raise ValueError(f"{component_id}: export does not change the Japanese label")

        for py in range(height):
            for px in range(width):
                coordinate = (x + px, y + py)
                if coordinate in occupied:
                    raise ValueError("cooking callout rectangles overlap")
                occupied.add(coordinate)
                _set_index(patched, *coordinate, replacement[py * width + px])

        replacement_indices = _rect_indices(patched, rect)
        if replacement_indices != replacement:
            raise AssertionError(f"{component_id}: packed write round-trip differs")
        row_ranges: list[list[str]] = []
        for py in range(y, y + height):
            start = UNIT1_IMAGE_PAYLOAD_OFFSET + py * (TEXTURE_WIDTH // 2) + x // 2
            end = start + width // 2
            allowed.append((start, end))
            row_ranges.append([f"0x{start:X}", f"0x{end:X}"])

        edit_sources[component_id] = {
            "path": str(edit_path.resolve()),
            "sha256": sha256_file(edit_path),
        }
        reports.append(
            {
                "id": component_id,
                "jp": component["jp"],
                "ko": KOREAN_LABELS[component_id],
                "source_mode": source_mode,
                "texture_rect": list(rect),
                "palette_bank": palette_bank,
                "runtime_clut": component["runtime_clut"],
                "consumer_descriptor_offset": component[
                    "consumer_descriptor_offset"
                ],
                "source_indices_sha256": hashlib.sha256(
                    original_indices
                ).hexdigest(),
                "replacement_indices_sha256": hashlib.sha256(
                    replacement_indices
                ).hexdigest(),
                "changed_pixel_count": sum(
                    left != right
                    for left, right in zip(original_indices, replacement_indices)
                ),
                "packed_row_ranges": row_ranges,
                "clut_unchanged": True,
            }
        )
    return bytes(patched), reports, allowed, edit_sources


def build_cooking_callout_graphics_patch(
    *,
    file_build_dir: Path,
    source_minig3_path: Path,
    edits_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    source = source_minig3_path.read_bytes()
    base_path = file_build_dir / "MINI_G3.BIN"
    base = base_path.read_bytes()
    if sha256_bytes(base) != base_manifest["outputs"]["MINI_G3.BIN"]["sha256"]:
        raise ValueError("base file-build MINI_G3.BIN hash differs")
    patched, reports, allowed, edit_sources = patch_callouts(
        source=source, base=base, edits_root=edits_root
    )
    expected = verify_expected_writes(
        base,
        patched,
        allowed_ranges=allowed,
        owner="MINI_G3 cooking callout label sprites relative to base file build",
    )

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
        if name == "MINI_G3.BIN":
            payload = patched
        (output_dir / name).write_bytes(payload)
        outputs[name] = payload
    map_name = "primary-korean-glyph-map.json"
    if (file_build_dir / map_name).is_file():
        shutil.copyfile(file_build_dir / map_name, output_dir / map_name)

    components = _component_map()
    cluts = _original_cluts(source)
    for report in reports:
        component_id = report["id"]
        rect = tuple(components[component_id]["rect"])
        indices = _rect_indices(patched, rect)
        preview = indexed_image(indices, rect[2], rect[3], cluts[report["palette_bank"]])
        preview_path = output_dir / f"{component_id}-inserted-indexed.png"
        preview.save(preview_path, transparency=preview.info["transparency"])
        report["preview"] = {
            "path": str(preview_path.resolve()),
            "sha256": sha256_file(preview_path),
        }

    sources = copy.deepcopy(base_manifest["sources"])
    sources["cooking_callout_graphics_edits"] = edit_sources
    sources["cooking_callout_base_file_build_manifest"] = {
        "path": str(base_manifest_path.resolve()),
        "sha256": sha256_file(base_manifest_path),
    }
    manifest = {
        **base_manifest,
        "sources": sources,
        "cooking_callout_graphics": {
            "status": "static-injection-user-runtime-validation-required",
            "file": "MINI_G3.BIN",
            "unit": 1,
            "entry_count": len(reports),
            "storage_policy": "replace-only-approved-4bpp-label-rectangles",
            "palette_policy": "preserve-original-runtime-clut-banks-9-and-13",
            "entries": reports,
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "cooking_callout_graphics": {
                "MINI_G3.BIN_relative_to_base": expected
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
        "--source-minig3",
        type=Path,
        default=PROJECT_ROOT / "work/extracted/disc1/iso/MINI_G3.BIN",
    )
    parser.add_argument(
        "--edits-root",
        type=Path,
        default=PROJECT_ROOT / "work/graphics/minigame/cooking/speech-bubbles",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_cooking_callout_graphics_patch(
        file_build_dir=args.file_build_dir,
        source_minig3_path=args.source_minig3,
        edits_root=args.edits_root,
        output_dir=args.output_dir,
    )
    expected = manifest["expected_writes"]["cooking_callout_graphics"][
        "MINI_G3.BIN_relative_to_base"
    ]
    print(
        f"callouts={manifest['cooking_callout_graphics']['entry_count']} "
        f"changed_bytes={expected['changed_byte_count']} "
        f"MINI_G3={manifest['outputs']['MINI_G3.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
