#!/usr/bin/env python3
"""Inspect and convert Korean bitmap/TTF glyphs for the PS1 font."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

try:
    from scripts.psx_font import HEIGHT, WIDTH, pack_glyph
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from psx_font import HEIGHT, WIDTH, pack_glyph


SOURCE_WIDTH = 16
SOURCE_HEIGHT = 16
SOURCE_GLYPH_SIZE = 32


@dataclass(frozen=True)
class FontProfile:
    profile_id: str
    profile_path: Path
    source_path: Path
    source_sha256: str
    glyph_map_path: Path
    glyph_map_sha256: str
    glyph_map: dict[str, int]
    family: str
    style: str
    version: str
    ttf_size_px: int
    x_offset_px: int
    y_offset_px: int
    intensity: int
    shadow_intensity: int | None
    shadow_x_offset_px: int
    shadow_y_offset_px: int
    ink_union: tuple[int, int, int, int]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_font_profile(path: Path) -> FontProfile:
    profile_path = path.resolve()
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("font profile schema_version must be 1")

    source = data.get("source")
    target = data.get("target")
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise ValueError("font profile requires source and target objects")
    if source.get("kind") != "truetype":
        raise ValueError("font profile source.kind must be 'truetype'")

    source_path = (profile_path.parent / source["path"]).resolve()
    glyph_map_path = (profile_path.parent / source["glyph_map_path"]).resolve()
    expected_source_hash = str(source["sha256"]).lower()
    expected_map_hash = str(source["glyph_map_sha256"]).lower()
    if sha256_file(source_path) != expected_source_hash:
        raise ValueError(f"font source SHA-256 differs: {source_path}")
    if sha256_file(glyph_map_path) != expected_map_hash:
        raise ValueError(f"font glyph map SHA-256 differs: {glyph_map_path}")

    mapping_data = json.loads(glyph_map_path.read_text(encoding="utf-8"))
    if not isinstance(mapping_data, dict):
        raise ValueError("font glyph map must be an object")
    glyph_map = {str(character): int(index) for character, index in mapping_data.items()}
    glyph_count = int(source["glyph_count"])
    if len(glyph_map) != glyph_count:
        raise ValueError(
            f"font glyph map count differs: {len(glyph_map)} != {glyph_count}"
        )
    if set(glyph_map.values()) != set(range(glyph_count)):
        raise ValueError("font glyph map indices must cover one contiguous range")

    expected_target = {
        "cell_width_px": WIDTH,
        "cell_height_px": HEIGHT,
        "bits_per_pixel": 3,
        "record_bytes": (WIDTH * HEIGHT * 3 + 7) // 8,
    }
    for key, expected in expected_target.items():
        if int(target.get(key, -1)) != expected:
            raise ValueError(f"font profile target {key} must be {expected}")
    intensity = int(target["intensity"])
    if not 1 <= intensity <= 7:
        raise ValueError("font profile target intensity must be between 1 and 7")
    shadow = target.get("shadow")
    if shadow is None:
        shadow_intensity = None
        shadow_x_offset_px = 0
        shadow_y_offset_px = 0
    elif isinstance(shadow, dict):
        shadow_intensity = int(shadow["intensity"])
        shadow_x_offset_px = int(shadow["x_offset_px"])
        shadow_y_offset_px = int(shadow["y_offset_px"])
        if not 1 <= shadow_intensity <= 7:
            raise ValueError(
                "font profile shadow intensity must be between 1 and 7"
            )
        if shadow_x_offset_px == 0 and shadow_y_offset_px == 0:
            raise ValueError("font profile shadow offset must not be zero")
    else:
        raise ValueError("font profile target.shadow must be an object")

    union = target.get("observed_ink_union")
    if not isinstance(union, dict):
        raise ValueError("font profile requires target.observed_ink_union")
    ink_union = tuple(
        int(union[key]) for key in ("x_min", "y_min", "x_max", "y_max")
    )
    if not (
        0 <= ink_union[0] <= ink_union[2] < WIDTH
        and 0 <= ink_union[1] <= ink_union[3] < HEIGHT
    ):
        raise ValueError("font profile observed ink union is outside the target cell")

    from PIL import ImageFont

    font = ImageFont.truetype(str(source_path), int(source["ttf_size_px"]))
    if tuple(font.getname()) != (source["family"], source["style"]):
        raise ValueError(
            f"font internal name differs: {font.getname()} != "
            f"{(source['family'], source['style'])}"
        )

    return FontProfile(
        profile_id=str(data["profile_id"]),
        profile_path=profile_path,
        source_path=source_path,
        source_sha256=expected_source_hash,
        glyph_map_path=glyph_map_path,
        glyph_map_sha256=expected_map_hash,
        glyph_map=glyph_map,
        family=str(source["family"]),
        style=str(source["style"]),
        version=str(source["version"]),
        ttf_size_px=int(source["ttf_size_px"]),
        x_offset_px=int(source["x_offset_px"]),
        y_offset_px=int(source["y_offset_px"]),
        intensity=intensity,
        shadow_intensity=shadow_intensity,
        shadow_x_offset_px=shadow_x_offset_px,
        shadow_y_offset_px=shadow_y_offset_px,
        ink_union=ink_union,
    )


def unpack_mono_glyph(data: bytes, *, byte_order: str = "big") -> list[int]:
    """Decode one 16x16 glyph stored as two bytes per row, MSB first."""
    if len(data) != SOURCE_GLYPH_SIZE:
        raise ValueError(f"glyph must be exactly {SOURCE_GLYPH_SIZE} bytes")
    if byte_order not in {"big", "little"}:
        raise ValueError("byte_order must be 'big' or 'little'")

    pixels: list[int] = []
    for row in range(SOURCE_HEIGHT):
        word = int.from_bytes(data[row * 2 : row * 2 + 2], byte_order)
        pixels.extend((word >> (15 - column)) & 1 for column in range(SOURCE_WIDTH))
    return pixels


def crop_to_psx(
    pixels: list[int],
    *,
    intensity: int = 7,
    shadow_intensity: int | None = None,
    shadow_x_offset_px: int = 0,
    shadow_y_offset_px: int = 0,
) -> list[int]:
    """Crop to 14x14 and optionally add a lower-priority drop shadow."""
    if len(pixels) != SOURCE_WIDTH * SOURCE_HEIGHT:
        raise ValueError("source glyph must contain exactly 256 pixels")
    if not 1 <= intensity <= 7:
        raise ValueError("intensity must be between 1 and 7")
    retained = [
        pixels[row * SOURCE_WIDTH + column]
        for row in range(1, HEIGHT + 1)
        for column in range(1, WIDTH + 1)
    ]
    result = [0] * (WIDTH * HEIGHT)
    if shadow_intensity is not None:
        if not 1 <= shadow_intensity <= 7:
            raise ValueError("shadow intensity must be between 1 and 7")
        if shadow_x_offset_px == 0 and shadow_y_offset_px == 0:
            raise ValueError("shadow offset must not be zero")
        for index, value in enumerate(retained):
            if not value:
                continue
            x = index % WIDTH + shadow_x_offset_px
            y = index // WIDTH + shadow_y_offset_px
            if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                result[y * WIDTH + x] = shadow_intensity
    for index, value in enumerate(retained):
        if value:
            result[index] = intensity
    return result


def crop_profile_glyph(profile: FontProfile, pixels: list[int]) -> list[int]:
    """Apply the profile's main ink and optional shadow to a source glyph."""
    return crop_to_psx(
        pixels,
        intensity=profile.intensity,
        shadow_intensity=profile.shadow_intensity,
        shadow_x_offset_px=profile.shadow_x_offset_px,
        shadow_y_offset_px=profile.shadow_y_offset_px,
    )


def rasterize_ttf_glyph(
    font: object,
    character: str,
    *,
    x_offset: int = -1,
    y_offset: int = -1,
) -> list[int]:
    """Rasterize one TTF glyph inside the bordered 16x16 working cell."""
    from PIL import Image, ImageDraw

    if len(character) != 1:
        raise ValueError("character must contain exactly one code point")
    image = Image.new("1", (SOURCE_WIDTH, SOURCE_HEIGHT))
    # The retained game area is x/y 1..14. Galmuri14's native 15px design
    # fits that area at target offset (-1, -1), i.e. source position (0, 0).
    ImageDraw.Draw(image).text(
        (x_offset + 1, y_offset + 1), character, font=font, fill=1
    )
    return [1 if value else 0 for value in image.get_flattened_data()]


def pack_profile_glyphs(
    profile: FontProfile,
    characters: list[str],
    *,
    intensity: int | None = None,
) -> dict[str, bytes]:
    from PIL import ImageFont

    target_intensity = profile.intensity if intensity is None else intensity
    if not 1 <= target_intensity <= 7:
        raise ValueError("intensity must be between 1 and 7")
    font = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    packed: dict[str, bytes] = {}
    for character in characters:
        if character not in profile.glyph_map:
            raise ValueError(f"character is absent from glyph map: {character!r}")
        pixels = rasterize_ttf_glyph(
            font,
            character,
            x_offset=profile.x_offset_px,
            y_offset=profile.y_offset_px,
        )
        if intensity is None:
            retained = crop_profile_glyph(profile, pixels)
        else:
            retained = crop_to_psx(pixels, intensity=target_intensity)
        packed[character] = pack_glyph(retained)
    return packed


def bounding_box(pixels: list[int]) -> tuple[int, int, int, int] | None:
    points = [
        (index % SOURCE_WIDTH, index // SOURCE_WIDTH)
        for index, value in enumerate(pixels)
        if value
    ]
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def render_preview(
    glyphs: list[tuple[str, list[int]]], output: Path, scale: int = 8
) -> None:
    from PIL import Image, ImageDraw

    cell_width = SOURCE_WIDTH * scale + 16
    cell_height = SOURCE_HEIGHT * scale + 38
    sheet = Image.new("RGB", (cell_width * len(glyphs), cell_height), "#202020")
    draw = ImageDraw.Draw(sheet)
    for position, (character, pixels) in enumerate(glyphs):
        glyph = Image.new("L", (SOURCE_WIDTH, SOURCE_HEIGHT))
        glyph.putdata([value * 255 for value in pixels])
        glyph = glyph.resize(
            (SOURCE_WIDTH * scale, SOURCE_HEIGHT * scale),
            Image.Resampling.NEAREST,
        ).convert("RGB")
        x = position * cell_width + 8
        draw.text((x, 4), character, fill="white")
        sheet.paste(glyph, (x, 26))
        # The red rectangle is the retained 14x14 game area.
        draw.rectangle(
            (x + scale - 1, 26 + scale - 1, x + 15 * scale, 26 + 15 * scale),
            outline="#ff4040",
            width=2,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--font-profile", type=Path)
    parser.add_argument("--glyph-map", type=Path)
    parser.add_argument("--text", default="시바세이치로")
    parser.add_argument("--byte-order", choices=("big", "little"), default="big")
    parser.add_argument("--ttf-size", type=int, default=15)
    parser.add_argument("--x-offset", type=int, default=-1)
    parser.add_argument("--y-offset", type=int, default=-1)
    parser.add_argument("--intensity", type=int)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--packed-output", type=Path)
    args = parser.parse_args()

    if (args.input is None) == (args.font_profile is None):
        parser.error("provide either input or --font-profile")
    if args.font_profile:
        if args.glyph_map:
            parser.error("--glyph-map is supplied by --font-profile")
        profile = load_font_profile(args.font_profile)
        mapping = profile.glyph_map
        input_path = profile.source_path
        ttf_size = profile.ttf_size_px
        x_offset = profile.x_offset_px
        y_offset = profile.y_offset_px
        intensity = profile.intensity if args.intensity is None else args.intensity
        is_ttf = True
    else:
        if not args.glyph_map:
            parser.error("--glyph-map is required with a direct input")
        profile = None
        assert args.input is not None
        mapping = json.loads(args.glyph_map.read_text(encoding="utf-8"))
        input_path = args.input
        ttf_size = args.ttf_size
        x_offset = args.x_offset
        y_offset = args.y_offset
        intensity = 7 if args.intensity is None else args.intensity
        is_ttf = input_path.suffix.lower() in {".ttf", ".otf"}
    if not 1 <= intensity <= 7:
        parser.error("--intensity must be between 1 and 7")

    if is_ttf:
        from PIL import ImageFont

        if ttf_size < 1:
            parser.error("--ttf-size must be positive")
        font = ImageFont.truetype(str(input_path), ttf_size)
        source = b""
    else:
        font = None
        source = input_path.read_bytes()
        if len(source) % SOURCE_GLYPH_SIZE:
            parser.error("input size is not a multiple of 32 bytes")

    glyphs: list[tuple[str, list[int]]] = []
    packed = bytearray()
    for character in args.text:
        if character not in mapping:
            parser.error(f"character is absent from glyph map: {character!r}")
        index = int(mapping[character])
        if font is not None:
            pixels = rasterize_ttf_glyph(
                font,
                character,
                x_offset=x_offset,
                y_offset=y_offset,
            )
        else:
            start = index * SOURCE_GLYPH_SIZE
            pixels = unpack_mono_glyph(
                source[start : start + SOURCE_GLYPH_SIZE],
                byte_order=args.byte_order,
            )
        glyphs.append((character, pixels))
        packed.extend(pack_glyph(crop_to_psx(pixels, intensity=intensity)))
        print(
            f"U+{ord(character):04X} index={index} bbox={bounding_box(pixels)}"
        )

    if args.preview:
        render_preview(glyphs, args.preview)
    if args.packed_output:
        args.packed_output.parent.mkdir(parents=True, exist_ok=True)
        args.packed_output.write_bytes(packed)
    print(
        f"glyphs={len(glyphs)} "
        f"source={'TTF' if is_ttf else '16x16/1bpp'} output=14x14/3bpp "
        f"packed_bytes={len(packed)} intensity={intensity}"
    )
    if profile:
        print(
            f"profile={profile.profile_id} family={profile.family} "
            f"version={profile.version} ttf_size={profile.ttf_size_px} "
            f"offset=({profile.x_offset_px},{profile.y_offset_px})"
        )


if __name__ == "__main__":
    main()
