#!/usr/bin/env python3
"""Replace the baked mini-game rule labels in MINI_G3.BIN unit 0."""

from __future__ import annotations

import argparse
import copy
import hashlib
from pathlib import Path
import shutil
from typing import Any

try:
    from scripts.build_character_name_patch import load_built_primary_mapping
    from scripts.build_dialogue_chapter_patch import FONT_OFFSET, verify_expected_writes
    from scripts.build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from scripts.extract_cooking_speech_bubbles import indexed_image
    from scripts.psx_font import GLYPH_SIZE, HEIGHT, WIDTH, unpack_glyph
    from scripts.psx_vram_render import palette_words, unit_records
except ModuleNotFoundError:
    from build_character_name_patch import load_built_primary_mapping
    from build_dialogue_chapter_patch import FONT_OFFSET, verify_expected_writes
    from build_special_screen_patch import (
        load_object,
        sha256_bytes,
        sha256_file,
        write_json,
    )
    from extract_cooking_speech_bubbles import indexed_image
    from psx_font import GLYPH_SIZE, HEIGHT, WIDTH, unpack_glyph
    from psx_vram_render import palette_words, unit_records


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MINI_G3_SHA256 = (
    "f6c3b2cc05586c7381c2ce953bcb3c86a25705a751ca9476b9a0cfe40299d5f1"
)
EXPECTED_RUNTIME_OVERLAP_SHA256 = (
    "72ae0fb2bc73e9943de8ab3c2dda593749c0ea93ba59f7bd377f2c5b25285558"
)
EXPECTED_BOTTOM_LABEL_TAIL_SHA256 = (
    "048a674bae782b4875c19cc4d95de3e1db3f2ecc4976fc1be270e7e9aaf3cfab"
)

UNIT0_RANGE = (0x00000, 0x18800)
UNIT0_IMAGE_PAYLOAD_OFFSET = 0x18
ATLAS_WIDTH = 512
ATLAS_HEIGHT = 256
ATLAS_VRAM_ORIGIN = (768, 256)
RULE_CACHE_VRAM_ORIGIN = (828, 446)
RULE_CACHE_ORIGIN = (
    (RULE_CACHE_VRAM_ORIGIN[0] - ATLAS_VRAM_ORIGIN[0]) * 4,
    RULE_CACHE_VRAM_ORIGIN[1] - ATLAS_VRAM_ORIGIN[1],
)
RUNTIME_OVERLAP_RECT = (RULE_CACHE_ORIGIN[0], RULE_CACHE_ORIGIN[1], 272, 48)
RULE_CACHE_SOURCE_SIZE = (272, 48)
BOTTOM_LABEL_TAIL_RECT = (16, 47, 224, 1)
RULE_CLUT_BANK = 7
TRANSPARENT_INDEX = 0


# Coordinates are relative to the 384x48 rule-label cache.  The clear bands
# stop immediately before the cyan cache guard at x=240; this retains the
# original guard pixels that the earlier live-VRAM PoC accidentally cleared.
CLEAR_BANDS = (
    (96, 3, 144, 14),
    (16, 18, 224, 15),
    (16, 33, 224, 14),
)

LABELS = (
    {
        "id": "cooking",
        "jp": "レナの3分クッキング",
        "ko": "레나의 3분 요리",
        "position": (104, 3),
        "band": 0,
    },
    {
        "id": "heading",
        "jp": "ルール説明",
        "ko": "규칙 설명",
        "position": (17, 18),
        "band": 1,
    },
    {
        "id": "camera",
        "jp": "ドリンク泥棒を激写",
        "ko": "음료 도둑 찍기",
        "position": (101, 18),
        "band": 1,
    },
    {
        "id": "catch_henri",
        "jp": "アンリを捕まえろ",
        "ko": "앙리를 붙잡아라",
        "position": (19, 33),
        "vertical_shift_px": 2,
        "band": 2,
    },
    {
        "id": "blackjack",
        "jp": "ブラックジャック",
        "ko": "블랙잭",
        "position": (174, 33),
        "horizontal_shift_px": 2,
        "vertical_shift_px": 2,
        "band": 2,
    },
)


def _pixel_offset(x: int, y: int) -> tuple[int, int]:
    if not (0 <= x < ATLAS_WIDTH and 0 <= y < ATLAS_HEIGHT):
        raise ValueError(f"MINI_G3 unit-0 atlas coordinate is outside bounds: {x},{y}")
    offset = UNIT0_IMAGE_PAYLOAD_OFFSET + y * (ATLAS_WIDTH // 2) + x // 2
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


def _packed_rect(data: bytes, rect: tuple[int, int, int, int]) -> bytes:
    x, y, width, height = rect
    if x & 1 or width & 1:
        raise ValueError("packed 4bpp rectangle must be byte aligned")
    return b"".join(
        data[
            UNIT0_IMAGE_PAYLOAD_OFFSET + py * (ATLAS_WIDTH // 2) + x // 2 :
            UNIT0_IMAGE_PAYLOAD_OFFSET
            + py * (ATLAS_WIDTH // 2)
            + (x + width) // 2
        ]
        for py in range(y, y + height)
    )


def _verify_source(source: bytes) -> list[int]:
    if sha256_bytes(source) != EXPECTED_MINI_G3_SHA256:
        raise ValueError("MINI_G3.BIN verified original hash differs")
    unit0 = source[slice(*UNIT0_RANGE)]
    records = {record.child_index: record for record in unit_records(unit0, 0)}
    image = records.get(0)
    if image is None or (
        image.x,
        image.y,
        image.width_halfwords * 4,
        image.height,
    ) != (768, 256, ATLAS_WIDTH, ATLAS_HEIGHT):
        raise ValueError("MINI_G3 unit-0 image record differs")
    if image.payload != source[
        UNIT0_IMAGE_PAYLOAD_OFFSET :
        UNIT0_IMAGE_PAYLOAD_OFFSET + ATLAS_WIDTH * ATLAS_HEIGHT // 2
    ]:
        raise ValueError("MINI_G3 unit-0 image payload offset differs")
    overlap = _packed_rect(source, RUNTIME_OVERLAP_RECT)
    if sha256_bytes(overlap) != EXPECTED_RUNTIME_OVERLAP_SHA256:
        raise ValueError("MINI_G3 rule cache does not match the clean-boot VRAM overlap")
    palette = records.get(2)
    if palette is None:
        raise ValueError("MINI_G3 unit-0 4bpp CLUT record is missing")
    words = palette_words(palette)
    clut = words[RULE_CLUT_BANK * 16 : (RULE_CLUT_BANK + 1) * 16]
    if len(clut) != 16 or clut[0] != 0 or clut[1] != 0x7FFF or clut[6] != 0x4210:
        raise ValueError("MINI_G3 rule-label CLUT bank 7 differs")
    return clut


def patch_rule_label_graphics(
    *, source: bytes, base: bytes, start_bin: bytes, mapping: dict[str, int]
) -> tuple[bytes, list[dict[str, Any]], list[tuple[int, int]], list[int]]:
    clut = _verify_source(source)
    if len(base) != len(source):
        raise ValueError("base MINI_G3.BIN size differs from verified original")
    original_overlap = _rect_indices(source, RUNTIME_OVERLAP_RECT)
    if _rect_indices(base, RUNTIME_OVERLAP_RECT) != original_overlap:
        raise ValueError("base file build already changes the rule-label cache")

    patched = bytearray(base)
    cache_x, cache_y = RULE_CACHE_ORIGIN
    allowed: list[tuple[int, int]] = []
    for rel_x, rel_y, width, height in CLEAR_BANDS:
        atlas_x = cache_x + rel_x
        atlas_y = cache_y + rel_y
        if atlas_x & 1 or width & 1:
            raise ValueError("rule-label clear band is not byte aligned")
        for py in range(atlas_y, atlas_y + height):
            for px in range(atlas_x, atlas_x + width):
                _set_index(patched, px, py, TRANSPARENT_INDEX)
            start = UNIT0_IMAGE_PAYLOAD_OFFSET + py * (ATLAS_WIDTH // 2) + atlas_x // 2
            allowed.append((start, start + width // 2))

    # The original Japanese bottom-row titles have one final antialias/shadow
    # scanline at cache y=47, beyond the old 14-row clear band. Freeze that
    # exact source row and remove only its nontransparent title pixels. The
    # cache border, cyan guard, and atlas rows below the runtime cache survive.
    tail_x, tail_y, tail_width, tail_height = BOTTOM_LABEL_TAIL_RECT
    source_tail = _rect_indices(
        source,
        (cache_x + tail_x, cache_y + tail_y, tail_width, tail_height),
    )
    if hashlib.sha256(source_tail).hexdigest() != EXPECTED_BOTTOM_LABEL_TAIL_SHA256:
        raise ValueError("MINI_G3 bottom rule-label tail row differs")
    removed_tail_pixel_count = 0
    for position, value in enumerate(source_tail):
        if value == TRANSPARENT_INDEX:
            continue
        target_x = cache_x + tail_x + position
        target_y = cache_y + tail_y
        _set_index(patched, target_x, target_y, TRANSPARENT_INDEX)
        byte_offset, _shift = _pixel_offset(target_x, target_y)
        allowed.append((byte_offset, byte_offset + 1))
        removed_tail_pixel_count += 1

    reports: list[dict[str, Any]] = []
    for entry in LABELS:
        text = str(entry["ko"])
        rel_x, rel_y = entry["position"]
        horizontal_shift = int(entry.get("horizontal_shift_px", 0))
        vertical_shift = int(entry.get("vertical_shift_px", 0))
        band = CLEAR_BANDS[int(entry["band"])]
        band_x, band_y, band_width, band_height = band
        if not (
            band_x <= rel_x + horizontal_shift
            and band_y <= rel_y
            and rel_x + horizontal_shift + len(text) * WIDTH
            <= band_x + band_width
        ):
            raise ValueError(f"{entry['id']}: Korean label exceeds its protected band")
        before = _rect_indices(
            source,
            (cache_x + band_x, cache_y + band_y, band_width, band_height),
        )
        used_indices: set[int] = set()
        for position, character in enumerate(text):
            if character not in mapping:
                raise ValueError(f"{entry['id']}: missing glyph mapping for {character!r}")
            glyph_index = mapping[character]
            start = FONT_OFFSET + glyph_index * GLYPH_SIZE
            end = start + GLYPH_SIZE
            if end > len(start_bin):
                raise ValueError(f"{entry['id']}: glyph 0x{glyph_index:X} is outside START.BIN")
            pixels = unpack_glyph(start_bin[start:end])
            used_indices.update(pixels)
            for gy in range(HEIGHT):
                for gx in range(WIDTH):
                    value = pixels[gy * WIDTH + gx]
                    target_y = cache_y + rel_y + vertical_shift + gy
                    band_target_y = rel_y + vertical_shift + gy
                    target_x = (
                        cache_x
                        + rel_x
                        + horizontal_shift
                        + position * WIDTH
                        + gx
                    )
                    if not band_y <= band_target_y < band_y + band_height:
                        if value == TRANSPARENT_INDEX:
                            continue
                        if not 0 <= band_target_y < RULE_CACHE_SOURCE_SIZE[1]:
                            raise ValueError(
                                f"{entry['id']}: shifted glyph ink exceeds the "
                                "runtime rule cache"
                            )
                        # The bottom-row labels need their last nontransparent
                        # glyph row at cache y=47. Authorize only the byte
                        # containing this exact shifted ink pixel.
                        byte_offset, _shift = _pixel_offset(target_x, target_y)
                        allowed.append((byte_offset, byte_offset + 1))
                    _set_index(
                        patched,
                        target_x,
                        target_y,
                        value,
                    )
        if not used_indices <= {0, 1, 3, 4, 6}:
            raise ValueError(
                f"{entry['id']}: current primary font uses unexpected CLUT indices "
                f"{sorted(used_indices)}"
            )
        after = _rect_indices(
            patched,
            (cache_x + band_x, cache_y + band_y, band_width, band_height),
        )
        reports.append(
            {
                "id": entry["id"],
                "jp": entry["jp"],
                "ko": text,
                "cache_position": list(entry["position"]),
                "horizontal_shift_px": horizontal_shift,
                "vertical_shift_px": vertical_shift,
                "protected_clear_band": list(band),
                "source_band_sha256": hashlib.sha256(before).hexdigest(),
                "replacement_band_sha256": hashlib.sha256(after).hexdigest(),
                "font_indices": sorted(used_indices),
            }
        )

    replacement_overlap = _rect_indices(patched, RUNTIME_OVERLAP_RECT)
    if replacement_overlap == original_overlap:
        raise ValueError("rule-label graphics patch made no change")
    reports.append(
        {
            "id": "bottom_label_tail_cleanup",
            "cache_rect": list(BOTTOM_LABEL_TAIL_RECT),
            "source_indices_sha256": EXPECTED_BOTTOM_LABEL_TAIL_SHA256,
            "removed_nontransparent_pixel_count": removed_tail_pixel_count,
            "border_and_cyan_guard_preserved": True,
        }
    )
    reports.append(
        {
            "id": "runtime_overlap",
            "atlas_rect": list(RUNTIME_OVERLAP_RECT),
            "vram_rect_halfwords": [828, 446, 68, 48],
            "source_indices_sha256": hashlib.sha256(original_overlap).hexdigest(),
            "replacement_indices_sha256": hashlib.sha256(replacement_overlap).hexdigest(),
            "changed_pixel_count": sum(
                left != right
                for left, right in zip(original_overlap, replacement_overlap)
            ),
        }
    )
    return bytes(patched), reports, allowed, clut


def build_minigame_rule_graphics_patch(
    *,
    file_build_dir: Path,
    source_minig3_disc1_path: Path,
    source_minig3_disc2_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    base_manifest_path = file_build_dir / "manifest.json"
    base_manifest = load_object(base_manifest_path)
    source = source_minig3_disc1_path.read_bytes()
    source_disc2 = source_minig3_disc2_path.read_bytes()
    if source_disc2 != source:
        raise ValueError("Disc 1 and Disc 2 MINI_G3.BIN differ")

    base_path = file_build_dir / "MINI_G3.BIN"
    base = base_path.read_bytes()
    if sha256_bytes(base) != base_manifest["outputs"]["MINI_G3.BIN"]["sha256"]:
        raise ValueError("base file-build MINI_G3.BIN hash differs")
    start_path = file_build_dir / "START.BIN"
    start_bin = start_path.read_bytes()
    if sha256_bytes(start_bin) != base_manifest["outputs"]["START.BIN"]["sha256"]:
        raise ValueError("base file-build START.BIN hash differs")
    map_path = file_build_dir / "primary-korean-glyph-map.json"
    mapping = load_built_primary_mapping(map_path)
    patched, reports, allowed, clut = patch_rule_label_graphics(
        source=source, base=base, start_bin=start_bin, mapping=mapping
    )
    expected = verify_expected_writes(
        base,
        patched,
        allowed_ranges=allowed,
        owner="MINI_G3 baked mini-game rule labels relative to base file build",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, bytes] = {}
    for name, metadata in base_manifest["outputs"].items():
        if name == "glyph_map":
            continue
        input_path = file_build_dir / name
        if not input_path.is_file():
            continue
        payload = input_path.read_bytes()
        if sha256_bytes(payload) != metadata["sha256"]:
            raise ValueError(f"{name}: base file-build hash differs")
        if name == "MINI_G3.BIN":
            payload = patched
        (output_dir / name).write_bytes(payload)
        outputs[name] = payload
    shutil.copyfile(map_path, output_dir / map_path.name)

    cache_x, cache_y = RULE_CACHE_ORIGIN
    preview_indices = _rect_indices(
        patched,
        (
            cache_x,
            cache_y,
            RULE_CACHE_SOURCE_SIZE[0],
            RULE_CACHE_SOURCE_SIZE[1],
        ),
    )
    preview = indexed_image(
        preview_indices,
        RULE_CACHE_SOURCE_SIZE[0],
        RULE_CACHE_SOURCE_SIZE[1],
        clut,
    )
    preview_path = output_dir / "minigame-rule-labels-inserted.png"
    preview.save(preview_path, transparency=preview.info["transparency"])

    sources = copy.deepcopy(base_manifest["sources"])
    sources["minigame_rule_graphics_base_file_build_manifest"] = {
        "path": str(base_manifest_path.resolve()),
        "sha256": sha256_file(base_manifest_path),
    }
    sources["MINI_G3.BIN_disc1_original"] = {
        "path": str(source_minig3_disc1_path.resolve()),
        "sha256": sha256_file(source_minig3_disc1_path),
    }
    sources["MINI_G3.BIN_disc2_original"] = {
        "path": str(source_minig3_disc2_path.resolve()),
        "sha256": sha256_file(source_minig3_disc2_path),
    }
    manifest = {
        **base_manifest,
        "sources": sources,
        "minigame_rule_graphics": {
            "status": "static-source-linked-clean-boot-runtime-validation-required",
            "file": "MINI_G3.BIN",
            "unit": 0,
            "entry_count": len(LABELS),
            "source_vram_rect": [768, 256, 128, 256],
            "observed_vram_overlap_rect": [828, 446, 68, 48],
            "palette_bank": RULE_CLUT_BANK,
            "palette_policy": (
                "preserve-CLUT-use-current-primary-font-indices-1-3-4-6"
            ),
            "entries": reports,
            "preview": {
                "path": str(preview_path.resolve()),
                "sha256": sha256_file(preview_path),
            },
        },
        "expected_writes": {
            **copy.deepcopy(base_manifest.get("expected_writes", {})),
            "minigame_rule_graphics": {
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
            "glyph_map": {
                "path": str((output_dir / map_path.name).resolve()),
                "sha256": sha256_file(output_dir / map_path.name),
            },
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-build-dir", type=Path, required=True)
    parser.add_argument(
        "--source-minig3-disc1",
        type=Path,
        default=PROJECT_ROOT / "work/extracted/disc1/iso/MINI_G3.BIN",
    )
    parser.add_argument(
        "--source-minig3-disc2",
        type=Path,
        default=PROJECT_ROOT / "work/extracted/disc2/iso/MINI_G3.BIN",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_minigame_rule_graphics_patch(
        file_build_dir=args.file_build_dir,
        source_minig3_disc1_path=args.source_minig3_disc1,
        source_minig3_disc2_path=args.source_minig3_disc2,
        output_dir=args.output_dir,
    )
    expected = manifest["expected_writes"]["minigame_rule_graphics"][
        "MINI_G3.BIN_relative_to_base"
    ]
    print(
        f"labels={manifest['minigame_rule_graphics']['entry_count']} "
        f"changed_bytes={expected['changed_byte_count']} "
        f"MINI_G3={manifest['outputs']['MINI_G3.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
