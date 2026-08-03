#!/usr/bin/env python3
"""Extract the cooking minigame's speech-bubble components from MINI_G3.BIN.

The Japanese callouts are not baked into the burst-shaped bubble backgrounds.
MINI_G3 unit 1 stores two blank bubble sprites and the callout labels separately;
the game composes them at runtime.  This extractor therefore preserves those
storage components instead of inventing a flattened replacement texture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from PIL import Image

try:
    from scripts.psx_vram_render import bgr555_color, palette_words, unit_records
except ModuleNotFoundError:  # Direct execution from the repository root.
    from psx_vram_render import bgr555_color, palette_words, unit_records


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MINI_G3_SHA256 = (
    "f6c3b2cc05586c7381c2ce953bcb3c86a25705a751ca9476b9a0cfe40299d5f1"
)
EXPECTED_UNIT1_SHA256 = (
    "5a894dd97b15809e90ab263934bb8c118b20ae989958edcbac591452146a1c31"
)
UNIT1_RANGE = (0x18800, 0x39000)
PALETTE_CHILD = 2
REFERENCE_PALETTE_BANK = 13
PURPLE = (255, 0, 255, 255)

# Coordinates are the actual SPRT rectangles from the ALLBIN consumer table,
# translated into the decoded 512x512 4bpp unit-1 atlas.  The broad label strip
# is storage context only: it contains sprites that use different CLUTs and
# therefore has no single original-color rendering.
COMPONENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "speech-bubble-left",
        "kind": "blank-bubble-base",
        "rect": (256, 256, 80, 64),
        "palette_bank": 13,
        "runtime_clut": "0x7D4D",
        "consumer_descriptor_offset": "ALLBIN.BIN+0x1419DC",
    },
    {
        "id": "speech-bubble-right",
        "kind": "blank-bubble-base",
        "rect": (336, 256, 80, 64),
        "palette_bank": 13,
        "runtime_clut": "0x7D4D",
        "consumer_descriptor_offset": "ALLBIN.BIN+0x141A0C",
    },
    {
        "id": "callout-label-strip",
        "kind": "storage-context",
        "rect": (0, 464, 208, 32),
        "preview_palette_bank": 13,
    },
    {
        "id": "callout-yakiagare",
        "kind": "japanese-label",
        "jp": "やきあがれ",
        "rect": (0, 472, 56, 24),
        "palette_bank": 9,
        "runtime_clut": "0x7D49",
        "consumer_descriptor_offset": "ALLBIN.BIN+0x1419A0",
    },
    {
        "id": "callout-rendaa",
        "kind": "japanese-label",
        "jp": "連打!!",
        "rect": (136, 472, 48, 24),
        "palette_bank": 13,
        "runtime_clut": "0x7D4D",
        "consumer_descriptor_offset": "ALLBIN.BIN+0x1419C4",
    },
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def decode_4bpp(payload: bytes, width: int, height: int) -> bytes:
    if width % 2:
        raise ValueError("4bpp width must be even")
    if len(payload) != width * height // 2:
        raise ValueError("4bpp payload size differs from the declared canvas")
    indices = bytearray()
    for value in payload:
        indices.extend((value & 0x0F, value >> 4))
    return bytes(indices)


def pack_4bpp(indices: bytes, width: int, height: int) -> bytes:
    if len(indices) != width * height:
        raise ValueError("index plane size differs from the declared canvas")
    if any(value > 0x0F for value in indices):
        raise ValueError("4bpp index is out of range")
    return bytes(
        indices[offset] | (indices[offset + 1] << 4)
        for offset in range(0, len(indices), 2)
    )


def indexed_image(
    indices: bytes, width: int, height: int, clut_words: list[int]
) -> Image.Image:
    if len(clut_words) != 16:
        raise ValueError("4bpp CLUT must contain exactly 16 colors")
    image = Image.frombytes("P", (width, height), indices)
    rgba = [bgr555_color(value) for value in clut_words]
    palette: list[int] = []
    alpha = bytearray()
    for red, green, blue, opacity in rgba:
        palette.extend((red, green, blue))
        alpha.append(opacity)
    palette.extend((0, 0, 0) * (256 - len(clut_words)))
    alpha.extend(bytes(256 - len(clut_words)))
    image.putpalette(palette)
    image.info["transparency"] = bytes(alpha)
    return image


def purple_preview(indexed: Image.Image, scale: int = 4) -> Image.Image:
    rgba = indexed.convert("RGBA")
    background = Image.new("RGBA", rgba.size, PURPLE)
    background.alpha_composite(rgba)
    if scale != 1:
        background = background.resize(
            (background.width * scale, background.height * scale),
            Image.Resampling.NEAREST,
        )
    return background.convert("RGB")


def _crop_indices(
    indices: bytes, width: int, rect: tuple[int, int, int, int]
) -> bytes:
    x, y, crop_width, crop_height = rect
    return b"".join(
        indices[row * width + x : row * width + x + crop_width]
        for row in range(y, y + crop_height)
    )


def extract(
    *, disc1_source: Path, disc2_source: Path, output_dir: Path
) -> dict[str, Any]:
    disc1 = disc1_source.read_bytes()
    disc2 = disc2_source.read_bytes()
    for label, payload in (("Disc 1", disc1), ("Disc 2", disc2)):
        actual = sha256_bytes(payload)
        if actual != EXPECTED_MINI_G3_SHA256:
            raise ValueError(f"{label} MINI_G3.BIN hash differs: {actual}")
    if disc1 != disc2:
        raise ValueError("Disc 1 and Disc 2 MINI_G3.BIN differ")

    unit_start, unit_end = UNIT1_RANGE
    unit = disc1[unit_start:unit_end]
    if sha256_bytes(unit) != EXPECTED_UNIT1_SHA256:
        raise ValueError("MINI_G3 unit 1 hash differs")
    records = {record.child_index: record for record in unit_records(unit, 1)}
    image_record = records[0]
    palette_record = records[PALETTE_CHILD]
    width = image_record.width_halfwords * 4
    height = image_record.height
    if (width, height) != (512, 512):
        raise ValueError(f"unexpected unit-1 atlas size: {width}x{height}")
    indices = decode_4bpp(image_record.payload, width, height)
    if pack_4bpp(indices, width, height) != image_record.payload:
        raise AssertionError("4bpp decode/repack round-trip failed")
    words = palette_words(palette_record)
    cluts = {
        bank: words[bank * 16 : (bank + 1) * 16]
        for bank in range(palette_record.height)
    }
    if any(len(clut) != 16 for clut in cluts.values()):
        raise ValueError("one or more CLUT banks are incomplete")

    output_dir.mkdir(parents=True, exist_ok=True)
    atlas = indexed_image(indices, width, height, cluts[REFERENCE_PALETTE_BANK])
    atlas.save(output_dir / "unit1-atlas-indexed.png", transparency=atlas.info["transparency"])
    purple_preview(atlas, scale=1).save(output_dir / "unit1-atlas-preview-purple.png")
    (output_dir / "unit1-atlas-indices-4bpp.bin").write_bytes(image_record.payload)
    for bank in (9, 13):
        (output_dir / f"palette-child2-bank{bank}-bgr555.bin").write_bytes(
            struct.pack("<16H", *cluts[bank])
        )

    reports = []
    for component in COMPONENTS:
        x, y, crop_width, crop_height = component["rect"]
        if x + crop_width > width or y + crop_height > height:
            raise ValueError(f"{component['id']}: crop exceeds the atlas")
        crop_indices = _crop_indices(indices, width, component["rect"])
        if not any(crop_indices):
            raise ValueError(f"{component['id']}: extracted component is empty")
        palette_bank = int(
            component.get("palette_bank", component.get("preview_palette_bank", 13))
        )
        clut = cluts[palette_bank]
        crop = indexed_image(crop_indices, crop_width, crop_height, clut)
        indexed_path = output_dir / f"{component['id']}-indexed.png"
        preview_path = output_dir / f"{component['id']}-preview-purple.png"
        raw_path = output_dir / f"{component['id']}-indices.bin"
        crop.save(indexed_path, transparency=crop.info["transparency"])
        purple_preview(crop).save(preview_path)
        raw_path.write_bytes(crop_indices)
        original_clut_path = None
        original_clut_4x_path = None
        if "runtime_clut" in component:
            original_clut_path = output_dir / f"{component['id']}-original-clut.png"
            crop.save(original_clut_path, transparency=crop.info["transparency"])
            original_clut_4x_path = (
                output_dir / f"{component['id']}-original-clut-4x.png"
            )
            enlarged = crop.resize(
                (crop.width * 4, crop.height * 4), Image.Resampling.NEAREST
            )
            enlarged.save(
                original_clut_4x_path, transparency=crop.info["transparency"]
            )
        reports.append(
            {
                **component,
                "rect": list(component["rect"]),
                "applied_palette_bank": palette_bank,
                "indexed_png": indexed_path.name,
                "original_clut_png": (
                    original_clut_path.name if original_clut_path is not None else None
                ),
                "original_clut_4x_png": (
                    original_clut_4x_path.name
                    if original_clut_4x_path is not None
                    else None
                ),
                "purple_preview_png": preview_path.name,
                "decoded_indices": raw_path.name,
                "decoded_indices_sha256": sha256_bytes(crop_indices),
            }
        )

    manifest = {
        "format": "psx-gpx-cooking-speech-bubbles-v1",
        "source": {
            "disc1": str(disc1_source.resolve()),
            "disc2": str(disc2_source.resolve()),
            "sha256": EXPECTED_MINI_G3_SHA256,
            "disc_files_identical": True,
        },
        "storage": {
            "file": "MINI_G3.BIN",
            "unit": 1,
            "unit_file_range": [f"0x{unit_start:X}", f"0x{unit_end:X}"],
            "image_child": 0,
            "canvas": [width, height],
            "bits_per_pixel": 4,
            "palette_child": PALETTE_CHILD,
            "palette_banks": [9, 13],
            "palette_format": "PS1 BGR555 little-endian",
        },
        "composition": {
            "status": "separate-storage-components",
            "note": (
                "The two burst-shaped bubble bases contain no Japanese text. "
                "The game overlays the separately stored やきあがれ and 連打!! labels. "
                "Each original-clut PNG uses the CLUT identified by its ALLBIN SPRT descriptor."
            ),
        },
        "components": reports,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--disc1-source",
        type=Path,
        default=PROJECT_ROOT / "work/extracted/disc1/iso/MINI_G3.BIN",
    )
    parser.add_argument(
        "--disc2-source",
        type=Path,
        default=PROJECT_ROOT / "work/extracted/disc2/iso/MINI_G3.BIN",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "work/graphics/minigame/cooking/speech-bubbles",
    )
    args = parser.parse_args()
    manifest = extract(
        disc1_source=args.disc1_source,
        disc2_source=args.disc2_source,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.resolve()),
                "component_count": len(manifest["components"]),
                "disc_files_identical": manifest["source"]["disc_files_identical"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
