#!/usr/bin/env python3
"""Inject user-adjusted full button atlases into an integrated file build."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
from typing import Any

from PIL import Image

try:
    from scripts.build_dialogue_chapter_patch import verify_expected_writes
    from scripts.build_name_origin_graphics_patch import (
        STATE0_ATLAS_OFFSET,
        decode_4bpp,
        encode_4bpp,
    )
    from scripts.build_save_screen_patch import OUTSIDE_SAVE_TEXTURE_PAYLOAD
    from scripts.build_minigame_graphics_patch import UNIT1_IMAGE_PAYLOAD_OFFSET
    from scripts.export_button_alignment_assets import (
        MINIGAME_UNIT1_CLUT_OFFSET,
        OUTSIDE_SAVE_CLUT_OFFSET,
        _clut_palette,
        _name_palette,
    )
except ModuleNotFoundError:
    from build_dialogue_chapter_patch import verify_expected_writes
    from build_name_origin_graphics_patch import (
        STATE0_ATLAS_OFFSET,
        decode_4bpp,
        encode_4bpp,
    )
    from build_save_screen_patch import OUTSIDE_SAVE_TEXTURE_PAYLOAD
    from build_minigame_graphics_patch import UNIT1_IMAGE_PAYLOAD_OFFSET
    from export_button_alignment_assets import (
        MINIGAME_UNIT1_CLUT_OFFSET,
        OUTSIDE_SAVE_CLUT_OFFSET,
        _clut_palette,
        _name_palette,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# These are full-atlas coordinates.  They include only the established text
# surfaces plus the user-approved movement margin; all other atlas pixels stay
# byte-identical to the integrated base build.
NAME_ALLOWED_RECTS = (
    (256, 48, 320, 216),
    (312, 152, 432, 224),
    (512, 0, 704, 224),
)
SAVE_ALLOWED_RECTS = ((0, 224, 80, 248),)
COOKING_ALLOWED_RECTS = ((416, 256, 498, 384),)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _surface(
    payload: bytes,
    *,
    header_offset: int,
    expected_rect: tuple[int, int, int, int],
) -> tuple[int, int, bytes, tuple[int, int]]:
    rect = struct.unpack_from("<4H", payload, header_offset)
    if rect != expected_rect:
        raise ValueError(
            f"4bpp header differs at 0x{header_offset:X}: "
            f"{rect} != {expected_rect}"
        )
    _, _, width_halfwords, height = rect
    width = width_halfwords * 4
    packed_size = width_halfwords * height * 2
    start = header_offset + 8
    end = start + packed_size
    indices = bytes(decode_4bpp(payload[start:end]))
    if len(indices) != width * height:
        raise AssertionError("decoded 4bpp surface size differs")
    return width, height, indices, (start, end)


def _load_edited_indices(
    path: Path,
    *,
    size: tuple[int, int],
    expected_palette: list[tuple[int, int, int]],
) -> bytes:
    image = Image.open(path)
    if image.mode != "P":
        raise ValueError(f"{path}: edited atlas must remain indexed mode P")
    if image.size != size:
        raise ValueError(f"{path}: edited atlas size differs: {image.size} != {size}")
    palette = image.getpalette()
    if palette is None:
        raise ValueError(f"{path}: indexed palette is missing")
    actual_palette = [
        tuple(palette[index * 3 : index * 3 + 3]) for index in range(16)
    ]
    if actual_palette != expected_palette:
        raise ValueError(f"{path}: first 16 palette entries differ")
    indices = bytes(image.get_flattened_data())
    if any(value > 15 for value in indices):
        raise ValueError(f"{path}: edited atlas uses an index outside 0..15")
    return indices


def _inside_any(
    x: int, y: int, rects: tuple[tuple[int, int, int, int], ...]
) -> bool:
    return any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in rects)


def _validate_pixel_changes(
    source: bytes,
    edited: bytes,
    *,
    width: int,
    height: int,
    allowed_rects: tuple[tuple[int, int, int, int], ...],
    label: str,
) -> dict[str, Any]:
    if len(source) != width * height or len(edited) != len(source):
        raise ValueError(f"{label}: index plane size differs")
    changes: list[tuple[int, int, int, int]] = []
    for index, (before, after) in enumerate(zip(source, edited)):
        if before == after:
            continue
        x = index % width
        y = index // width
        if not _inside_any(x, y, allowed_rects):
            raise ValueError(
                f"{label}: changed pixel ({x},{y}) is outside the approved text areas"
            )
        changes.append((x, y, before, after))
    if not changes:
        raise ValueError(f"{label}: edited atlas changed no pixels")
    xs = [item[0] for item in changes]
    ys = [item[1] for item in changes]
    return {
        "changed_pixel_count": len(changes),
        "changed_pixel_bbox_inclusive": [min(xs), min(ys), max(xs), max(ys)],
        "allowed_rectangles_half_open": [list(rect) for rect in allowed_rects],
        "source_indices_sha256": sha256_bytes(source),
        "edited_indices_sha256": sha256_bytes(edited),
    }


def _allowed_file_ranges(
    *,
    payload_start: int,
    width: int,
    rects: tuple[tuple[int, int, int, int], ...],
) -> list[tuple[int, int]]:
    stride = width // 2
    ranges: list[tuple[int, int]] = []
    for x0, y0, x1, y1 in rects:
        if x0 % 2 or x1 % 2:
            raise ValueError("4bpp allowed rectangles must be byte-aligned")
        for y in range(y0, y1):
            ranges.append(
                (
                    payload_start + y * stride + x0 // 2,
                    payload_start + y * stride + x1 // 2,
                )
            )
    return ranges


def _replace_surface(
    payload: bytes,
    *,
    packed_range: tuple[int, int],
    edited_indices: bytes,
) -> bytes:
    packed = encode_4bpp(list(edited_indices))
    start, end = packed_range
    if len(packed) != end - start:
        raise AssertionError("repacked 4bpp surface size differs")
    result = bytearray(payload)
    result[start:end] = packed
    return bytes(result)


def build_button_alignment_asset_patch(
    *,
    file_build_dir: Path,
    edited_name_path: Path,
    edited_save_selected_path: Path,
    edited_save_unselected_path: Path,
    edited_cooking_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    input_outside = (file_build_dir / "OUTSIDE.BIN").read_bytes()
    input_minig3 = (file_build_dir / "MINI_G3.BIN").read_bytes()
    for name, payload in (
        ("OUTSIDE.BIN", input_outside),
        ("MINI_G3.BIN", input_minig3),
    ):
        if sha256_bytes(payload) != base_manifest["outputs"][name]["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")

    name_width, name_height, name_source, name_range = _surface(
        input_outside,
        header_offset=STATE0_ATLAS_OFFSET,
        expected_rect=(512, 0, 256, 256),
    )
    name_edited = _load_edited_indices(
        edited_name_path,
        size=(name_width, name_height),
        expected_palette=_name_palette(input_outside, bank=13),
    )
    name_report = _validate_pixel_changes(
        name_source,
        name_edited,
        width=name_width,
        height=name_height,
        allowed_rects=NAME_ALLOWED_RECTS,
        label="name UI atlas",
    )

    save_width, save_height, save_source, save_range = _surface(
        input_outside,
        header_offset=OUTSIDE_SAVE_TEXTURE_PAYLOAD - 8,
        expected_rect=(512, 0, 256, 256),
    )
    save_selected = _load_edited_indices(
        edited_save_selected_path,
        size=(save_width, save_height),
        expected_palette=_clut_palette(
            input_outside,
            offset=OUTSIDE_SAVE_CLUT_OFFSET,
            expected_rect=(0, 496, 16, 16),
            bank=4,
        ),
    )
    save_unselected = _load_edited_indices(
        edited_save_unselected_path,
        size=(save_width, save_height),
        expected_palette=_clut_palette(
            input_outside,
            offset=OUTSIDE_SAVE_CLUT_OFFSET,
            expected_rect=(0, 496, 16, 16),
            bank=5,
        ),
    )
    if save_selected != save_unselected:
        raise ValueError("save selected/unselected edited index planes differ")
    save_report = _validate_pixel_changes(
        save_source,
        save_selected,
        width=save_width,
        height=save_height,
        allowed_rects=SAVE_ALLOWED_RECTS,
        label="save UI atlas",
    )

    cooking_width, cooking_height, cooking_source, cooking_range = _surface(
        input_minig3,
        header_offset=UNIT1_IMAGE_PAYLOAD_OFFSET - 8,
        expected_rect=(512, 0, 128, 512),
    )
    cooking_edited = _load_edited_indices(
        edited_cooking_path,
        size=(cooking_width, cooking_height),
        expected_palette=_clut_palette(
            input_minig3,
            offset=MINIGAME_UNIT1_CLUT_OFFSET,
            expected_rect=(0, 496, 16, 16),
            bank=13,
        ),
    )
    cooking_report = _validate_pixel_changes(
        cooking_source,
        cooking_edited,
        width=cooking_width,
        height=cooking_height,
        allowed_rects=COOKING_ALLOWED_RECTS,
        label="cooking UI atlas",
    )

    patched_outside = _replace_surface(
        input_outside,
        packed_range=name_range,
        edited_indices=name_edited,
    )
    patched_outside = _replace_surface(
        patched_outside,
        packed_range=save_range,
        edited_indices=save_selected,
    )
    patched_minig3 = _replace_surface(
        input_minig3,
        packed_range=cooking_range,
        edited_indices=cooking_edited,
    )
    outside_allowed = _allowed_file_ranges(
        payload_start=name_range[0],
        width=name_width,
        rects=NAME_ALLOWED_RECTS,
    ) + _allowed_file_ranges(
        payload_start=save_range[0],
        width=save_width,
        rects=SAVE_ALLOWED_RECTS,
    )
    minig3_allowed = _allowed_file_ranges(
        payload_start=cooking_range[0],
        width=cooking_width,
        rects=COOKING_ALLOWED_RECTS,
    )
    outside_expected = verify_expected_writes(
        input_outside,
        patched_outside,
        allowed_ranges=outside_allowed,
        owner="user-adjusted full name/save button atlases",
    )
    minig3_expected = verify_expected_writes(
        input_minig3,
        patched_minig3,
        allowed_ranges=minig3_allowed,
        owner="user-adjusted full cooking button atlas",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, bytes] = {}
    for name in base_manifest["outputs"]:
        if name == "glyph_map":
            continue
        source_path = file_build_dir / name
        if not source_path.is_file():
            continue
        payload = (
            patched_outside
            if name == "OUTSIDE.BIN"
            else patched_minig3
            if name == "MINI_G3.BIN"
            else source_path.read_bytes()
        )
        (output_dir / name).write_bytes(payload)
        outputs[name] = payload
    map_name = "primary-korean-glyph-map.json"
    if (file_build_dir / map_name).is_file():
        shutil.copyfile(file_build_dir / map_name, output_dir / map_name)

    report = {
        "status": "static-injection-passed-runtime-visual-validation-required",
        "policy": (
            "full indexed atlases are accepted, but changed pixels must stay "
            "inside the approved text surfaces and movement margins"
        ),
        "name_ui": {
            **name_report,
            "edited_path": str(edited_name_path.resolve()),
            "edited_file_sha256": sha256_file(edited_name_path),
        },
        "save": {
            **save_report,
            "edited_selected_path": str(edited_save_selected_path.resolve()),
            "edited_selected_file_sha256": sha256_file(edited_save_selected_path),
            "edited_unselected_path": str(edited_save_unselected_path.resolve()),
            "edited_unselected_file_sha256": sha256_file(edited_save_unselected_path),
            "selected_unselected_indices_equal": True,
        },
        "cooking": {
            **cooking_report,
            "edited_path": str(edited_cooking_path.resolve()),
            "edited_file_sha256": sha256_file(edited_cooking_path),
        },
    }
    manifest = {
        **base_manifest,
        "warning": (
            str(base_manifest.get("warning", ""))
            + " User-adjusted full button atlases are statically injected; "
            "runtime visual review is required."
        ).strip(),
        "sources": {
            **copy.deepcopy(base_manifest["sources"]),
            "button_alignment_base_file_build_manifest": {
                "path": str(base_manifest_path.resolve()),
                "sha256": sha256_file(base_manifest_path),
            },
            "button_alignment_edited_name_atlas": {
                "path": str(edited_name_path.resolve()),
                "sha256": sha256_file(edited_name_path),
            },
            "button_alignment_edited_save_selected_atlas": {
                "path": str(edited_save_selected_path.resolve()),
                "sha256": sha256_file(edited_save_selected_path),
            },
            "button_alignment_edited_save_unselected_atlas": {
                "path": str(edited_save_unselected_path.resolve()),
                "sha256": sha256_file(edited_save_unselected_path),
            },
            "button_alignment_edited_cooking_atlas": {
                "path": str(edited_cooking_path.resolve()),
                "sha256": sha256_file(edited_cooking_path),
            },
        },
        "button_alignment_assets": report,
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "button_alignment_assets": {
                "OUTSIDE.BIN_relative_to_base": outside_expected,
                "MINI_G3.BIN_relative_to_base": minig3_expected,
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
    default_root = PROJECT_ROOT / "work/analysis/button-alignment-2026-08-09/1x/full-assets"
    parser.add_argument("--file-build-dir", type=Path, required=True)
    parser.add_argument(
        "--edited-name",
        type=Path,
        default=default_root / "name-ui-unit0-child5-atlas-indexed-1x.png",
    )
    parser.add_argument(
        "--edited-save-selected",
        type=Path,
        default=default_root
        / "save-unit1-child4-atlas-selected-clut-indexed-1x.png",
    )
    parser.add_argument(
        "--edited-save-unselected",
        type=Path,
        default=default_root
        / "save-unit1-child4-atlas-unselected-clut-indexed-1x.png",
    )
    parser.add_argument(
        "--edited-cooking",
        type=Path,
        default=default_root / "cooking-unit1-child0-atlas-indexed-1x.png",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_button_alignment_asset_patch(
        file_build_dir=args.file_build_dir,
        edited_name_path=args.edited_name,
        edited_save_selected_path=args.edited_save_selected,
        edited_save_unselected_path=args.edited_save_unselected,
        edited_cooking_path=args.edited_cooking,
        output_dir=args.output_dir,
    )
    report = manifest["button_alignment_assets"]
    print(
        f"name_pixels={report['name_ui']['changed_pixel_count']} "
        f"save_pixels={report['save']['changed_pixel_count']} "
        f"cooking_pixels={report['cooking']['changed_pixel_count']} "
        f"OUTSIDE={manifest['outputs']['OUTSIDE.BIN']['sha256']} "
        f"MINI_G3={manifest['outputs']['MINI_G3.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
