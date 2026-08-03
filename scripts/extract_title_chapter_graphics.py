#!/usr/bin/env python3
"""Extract the shared title screen and chapter-card textures from START.BIN.

The output keeps the stored texture canvas intact.  PNGs ending in
``-purple.png`` composite transparent texels over #FF00FF so the otherwise
invisible, fixed-size canvas is obvious while editing.  Exact index and CLUT
payloads are exported beside the review PNGs for later lossless reinsertion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

try:
    from scripts.original_media import (
        load_manifest,
        resolved_paths,
        verify_track,
    )
    from scripts.psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule
    from scripts.psx_vram_render import (
        bgr555_color,
        decode_indexed,
        palette_words,
        unit_records,
    )
except ModuleNotFoundError:  # Direct execution from the repository root.
    from original_media import load_manifest, resolved_paths, verify_track
    from psx_layout import PsxExe, SCHEDULE_SPECS, discover_schedule
    from psx_vram_render import (
        bgr555_color,
        decode_indexed,
        palette_words,
        unit_records,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PURPLE = (255, 0, 255)
SCREEN_CROP = (0, 0, 320, 240)
CHAPTER_SCREEN_SEGMENTS = ((0, 240), (256, 336))

# Hashes are for complete scheduled units from the supported original revision.
EXPECTED_UNIT_SHA256 = {
    8: "8553b2804884b5a345eda677e3976c413e44bcfbaf651111e2387f8bab639f3e",
    24: "a800c0ecc5d189364080aa1ad61916898bea3f415e13eb30d23c2b8394ebc5e0",
    25: "07b4e91682cf4e68e6f22fcf9d9c79d501eefc8fe25e2c2e9ac8f60258942ea9",
    26: "b3ba07cfb9d6422a5990f070663aab238502a40de929e26555723b4be70aabb7",
    27: "263f9a37aeacdabde0df03ea009b6780b04ec4e10468c2c7f6e66ff9c03f189f",
    28: "03217a322453ef86dadad86797a8dbcaf7690a038cca246d1237e532093d681d",
    29: "ec9cc58c8b61c1160b6f6688c558461c6f56940f18df45e4f60b50b6806dc139",
    30: "b3f8152f1a7cf23f969dfbfbea0dada3018bf995a98f8bda031e9125743674f6",
    31: "c7f7d9fd6996de04a3318b4f0db082d60507402da57dcc9c40a5464b33723191",
    32: "3369648f8eecb3848544f015472f62d411af044074929a960c0160ac7a550b2c",
    33: "c08146ea498c1916acc683380360a9bd0ca903f65715607a5f025aab0b6b241c",
    34: "1bbfc3cf92cb520901fa31e73c53df0a7edc65056ee193d1b878cf0b285aa379",
}

ASSETS = (
    {
        "asset_id": "title-screen",
        "unit": 8,
        "palette_child": 4,
        "image_child": 5,
        "category": "title",
        "jp_label": "ゲームタイトル画面",
    },
    {
        "asset_id": "chapter-01-sugou-test-circuit",
        "unit": 24,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "スゴウテストサーキット",
    },
    {
        "asset_id": "chapter-02-school",
        "unit": 25,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "学校",
    },
    {
        "asset_id": "chapter-03-party-venue",
        "unit": 26,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "パーティー会場",
    },
    {
        "asset_id": "chapter-04-race-1",
        "unit": 27,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "第1戦",
    },
    {
        "asset_id": "chapter-05-race-2",
        "unit": 28,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "第2戦",
    },
    {
        "asset_id": "chapter-06-race-3",
        "unit": 29,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "第3戦",
    },
    {
        "asset_id": "chapter-07-travel-day",
        "unit": 30,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "移動日",
    },
    {
        "asset_id": "chapter-08-race-4",
        "unit": 31,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "第4戦",
    },
    {
        "asset_id": "chapter-09-race-5",
        "unit": 32,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "第5戦",
    },
    {
        "asset_id": "chapter-10-race-6",
        "unit": 33,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "第6戦",
    },
    {
        "asset_id": "chapter-11-race-7",
        "unit": 34,
        "palette_child": 0,
        "image_child": 1,
        "category": "chapter",
        "jp_label": "第7戦",
    },
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def start_schedule(disc_root: Path, boot_exe: str) -> list[dict[str, int]]:
    spec = next(spec for spec in SCHEDULE_SPECS if spec.filename == "START.BIN")
    data_size = (disc_root / spec.filename).stat().st_size
    exe = PsxExe((disc_root / boot_exe).read_bytes())
    return discover_schedule(exe, spec.table_va, spec.table_limit_va, data_size)


def target_units(
    disc_root: Path, boot_exe: str
) -> tuple[bytes, dict[int, bytes], list[dict[str, int]]]:
    start = (disc_root / "START.BIN").read_bytes()
    schedule = start_schedule(disc_root, boot_exe)
    units: dict[int, bytes] = {}
    for unit_index, expected_hash in EXPECTED_UNIT_SHA256.items():
        span = schedule[unit_index]
        unit = start[span["byte_offset"] : span["byte_end"]]
        actual_hash = sha256_bytes(unit)
        if actual_hash != expected_hash:
            raise ValueError(
                f"START.BIN unit {unit_index} mismatch: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        units[unit_index] = unit
    return start, units, schedule


def purple_composite(image: Image.Image) -> Image.Image:
    background = Image.new("RGBA", image.size, (*PURPLE, 255))
    background.alpha_composite(image)
    return background.convert("RGB")


def assemble_chapter_screen(image: Image.Image) -> Image.Image:
    """Remove the stored 16-pixel wrap gap from a chapter-card texture.

    The GPU-visible 320-pixel row is stored as x=0..239 followed by x=256..335.
    The intervening x=240..255 columns are transparent VRAM-page padding.
    """
    if image.width < 336 or image.height < 240:
        raise ValueError("chapter texture is smaller than the wrapped 320x240 screen")
    screen = Image.new(image.mode, (320, 240), 0)
    destination_x = 0
    for source_left, source_right in CHAPTER_SCREEN_SEGMENTS:
        segment = image.crop((source_left, 0, source_right, 240))
        screen.paste(segment, (destination_x, 0))
        destination_x += source_right - source_left
    if destination_x != 320:
        raise AssertionError("chapter screen segment widths do not total 320 pixels")
    return screen


def palette_sheet(words: list[int]) -> Image.Image:
    sheet = Image.new("RGB", (256, 256), PURPLE)
    pixels = sheet.load()
    for index, word in enumerate(words):
        red, green, blue, _alpha = bgr555_color(word)
        x0 = (index % 16) * 16
        y0 = (index // 16) * 16
        for y in range(y0, y0 + 16):
            for x in range(x0, x0 + 16):
                pixels[x, y] = (red, green, blue)
    return sheet


def export_asset(
    asset: dict[str, Any], unit: bytes, output_root: Path
) -> dict[str, Any]:
    records = {record.child_index: record for record in unit_records(unit, asset["unit"])}
    palette_record = records[asset["palette_child"]]
    image_record = records[asset["image_child"]]
    words = palette_words(palette_record)
    if len(words) != 256:
        raise ValueError(f"{asset['asset_id']}: expected one 256-color CLUT")
    image = decode_indexed(image_record, words, 8)
    if image.width < SCREEN_CROP[2] or image.height < SCREEN_CROP[3]:
        raise ValueError(f"{asset['asset_id']}: texture is smaller than 320x240")

    category_dir = "title" if asset["category"] == "title" else "chapters"
    destination = output_root / category_dir / asset["asset_id"]
    destination.mkdir(parents=True, exist_ok=True)

    texture_path = destination / "original-texture.png"
    purple_texture_path = destination / "edit-template-purple.png"
    screen_path = destination / "original-screen-320x240.png"
    purple_screen_path = destination / "screen-320x240-purple.png"
    alpha_mask_path = destination / "transparent-mask.png"
    index_map_path = destination / "index-map.png"
    palette_path = destination / "palette.png"
    palette_bin_path = destination / "palette-bgr555.bin"
    indices_bin_path = destination / "indices.bin"

    image.save(texture_path)
    purple_composite(image).save(purple_texture_path)
    screen = (
        assemble_chapter_screen(image)
        if asset["category"] == "chapter"
        else image.crop(SCREEN_CROP)
    )
    screen.save(screen_path)
    purple_composite(screen).save(purple_screen_path)
    image.getchannel("A").point(lambda value: 255 if value == 0 else 0).save(
        alpha_mask_path
    )
    Image.frombytes("L", image.size, image_record.payload).save(index_map_path)
    palette_sheet(words).save(palette_path)
    palette_bin_path.write_bytes(palette_record.payload)
    indices_bin_path.write_bytes(image_record.payload)

    assembled_files: dict[str, Path] = {}
    if asset["category"] == "chapter":
        assembled_original_path = destination / "assembled-original-320x240.png"
        assembled_purple_path = destination / "assembled-preview-purple-320x240.png"
        assembled_indexed_path = destination / "assembled-indexed-320x240.png"
        screen.save(assembled_original_path)
        purple_composite(screen).save(assembled_purple_path)

        stored_indices = Image.frombytes("P", image.size, image_record.payload)
        assembled_indices = assemble_chapter_screen(stored_indices)
        png_palette: list[int] = []
        png_alpha: list[int] = []
        for word in words:
            red, green, blue, alpha = bgr555_color(word)
            png_palette.extend((red, green, blue))
            png_alpha.append(alpha)
        assembled_indices.putpalette(png_palette)
        assembled_indices.save(
            assembled_indexed_path,
            transparency=bytes(png_alpha),
        )
        assembled_files = {
            "assembled_original": assembled_original_path,
            "assembled_preview_purple": assembled_purple_path,
            "assembled_indexed": assembled_indexed_path,
        }

    opaque_bbox = image.getchannel("A").getbbox()
    relative = lambda path: str(path.relative_to(output_root))
    return {
        **asset,
        "source": {
            "file": "START.BIN",
            "unit_sha256": sha256_bytes(unit),
            "palette_child": asset["palette_child"],
            "image_child": asset["image_child"],
            "bits_per_pixel": 8,
            "palette_vram": {
                "x": palette_record.x,
                "y": palette_record.y,
                "width_halfwords": palette_record.width_halfwords,
                "height": palette_record.height,
            },
            "image_vram": {
                "x": image_record.x,
                "y": image_record.y,
                "width_halfwords": image_record.width_halfwords,
                "height": image_record.height,
            },
        },
        "canvas": {
            "stored_width": image.width,
            "stored_height": image.height,
            "screen_crop": list(SCREEN_CROP),
            **(
                {
                    "screen_assembly": {
                        "output_size": [320, 240],
                        "source_x_segments": [
                            list(segment) for segment in CHAPTER_SCREEN_SEGMENTS
                        ],
                        "excluded_transparent_gap": [240, 256],
                    }
                }
                if asset["category"] == "chapter"
                else {}
            ),
            "opaque_bbox": list(opaque_bbox) if opaque_bbox else None,
            "transparent_preview_color": "#FF00FF",
        },
        "layer_status": {
            "background_and_text": "baked_into_one_index_plane",
            "separate_text_layer_available": False,
            "palette_and_indices_exported_separately": True,
        },
        "files": {
            "original_texture": relative(texture_path),
            "edit_template_purple": relative(purple_texture_path),
            "original_screen": relative(screen_path),
            "screen_purple": relative(purple_screen_path),
            "transparent_mask": relative(alpha_mask_path),
            "index_map": relative(index_map_path),
            "palette_preview": relative(palette_path),
            "palette_bgr555": relative(palette_bin_path),
            "indices": relative(indices_bin_path),
            **{
                key: relative(path) for key, path in assembled_files.items()
            },
        },
    }


def write_overview(
    exported: list[dict[str, Any]],
    output_root: Path,
    *,
    purple: bool,
    prefix: str = "overview",
) -> Path:
    columns = 3
    cell_width = 320
    image_height = 240
    label_height = 24
    rows = (len(exported) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * cell_width, rows * (image_height + label_height)),
        (24, 24, 28),
    )
    draw = ImageDraw.Draw(sheet)
    file_key = "screen_purple" if purple else "original_screen"
    for index, asset in enumerate(exported):
        image = Image.open(output_root / asset["files"][file_key]).convert("RGB")
        x = (index % columns) * cell_width
        y = (index // columns) * (image_height + label_height)
        sheet.paste(image, (x, y))
        draw.text(
            (x + 5, y + image_height + 5),
            asset["asset_id"],
            fill=(240, 240, 240),
        )
    suffix = "purple" if purple else "original"
    path = output_root / f"{prefix}-{suffix}.png"
    sheet.save(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--disc1-root",
        type=Path,
        default=PROJECT_ROOT / "work/extracted/disc1/iso",
    )
    parser.add_argument(
        "--disc2-root",
        type=Path,
        default=PROJECT_ROOT / "work/extracted/disc2/iso",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "work/graphics/title-chapter",
    )
    args = parser.parse_args()

    media_manifest = load_manifest()
    media_paths = resolved_paths(media_manifest)
    verifications = {}
    per_disc_units = {}
    per_disc_schedule = {}
    for disc_key, disc_root in (("disc1", args.disc1_root), ("disc2", args.disc2_root)):
        disc = media_manifest[disc_key]
        verifications[disc_key] = verify_track(
            media_paths[f"{disc_key}_track1"],
            disc["data_track"],
            label=f"{disc_key} data track",
        )
        _start, units, schedule = target_units(disc_root, disc["boot_exe"])
        per_disc_units[disc_key] = units
        per_disc_schedule[disc_key] = schedule

    for unit_index in EXPECTED_UNIT_SHA256:
        if per_disc_units["disc1"][unit_index] != per_disc_units["disc2"][unit_index]:
            raise ValueError(f"shared START.BIN unit {unit_index} differs between discs")

    args.output.mkdir(parents=True, exist_ok=True)
    exported = [
        export_asset(asset, per_disc_units["disc1"][asset["unit"]], args.output)
        for asset in ASSETS
    ]
    overview_original = write_overview(exported, args.output, purple=False)
    overview_purple = write_overview(exported, args.output, purple=True)
    chapter_assets = [item for item in exported if item["category"] == "chapter"]
    chapter_overview_original = write_overview(
        chapter_assets,
        args.output,
        purple=False,
        prefix="chapters-assembled-overview",
    )
    chapter_overview_purple = write_overview(
        chapter_assets,
        args.output,
        purple=True,
        prefix="chapters-assembled-overview",
    )
    manifest = {
        "schema_version": 1,
        "scope": "shared-disc1-disc2-title-and-chapter-card-graphics",
        "source_verification": verifications,
        "shared_unit_equality": True,
        "policy": {
            "transparent_preview_color": "#FF00FF",
            "purple_is_preview_only": True,
            "stored_texture_dimensions_preserved": True,
            "screen_crop_is_review_only": True,
            "roundtrip_source_payloads": ["palette-bgr555.bin", "indices.bin"],
        },
        "asset_count": len(exported),
        "overview_files": {
            "original": str(overview_original.relative_to(args.output)),
            "purple": str(overview_purple.relative_to(args.output)),
        },
        "chapter_assembled_overview_files": {
            "original": str(chapter_overview_original.relative_to(args.output)),
            "purple": str(chapter_overview_purple.relative_to(args.output)),
        },
        "assets": exported,
    }
    write_json(args.output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "asset_count": len(exported),
                "title_count": sum(item["category"] == "title" for item in exported),
                "chapter_count": sum(item["category"] == "chapter" for item in exported),
                "shared_disc1_disc2": True,
                "purple": "#FF00FF",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
