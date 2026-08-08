#!/usr/bin/env python3
"""Build non-release Korean dialogue files for selected ALLBIN story units.

The primary font mapping is deterministic for the selected dialogue plus the
integrated Korean name/UI artifacts. Unselected units are not compatible with
the replaced font and must not be treated as playable content in a partial
build.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Iterable

try:
    from scripts.build_dialogue_safe_slots import (
        fixed_original_safe_slots,
        physical_entry_ranges,
    )
    from scripts.korean_font import (
        crop_profile_glyph,
        load_font_profile,
        rasterize_ttf_glyph,
    )
    from scripts.psx_font import GLYPH_SIZE, pack_glyph
    from scripts.unindexed_font_common import (
        encode_unindexed_entry,
        unindexed_translation_texts,
        validate_unindexed_artifacts,
    )
except ModuleNotFoundError:
    from build_dialogue_safe_slots import (
        fixed_original_safe_slots,
        physical_entry_ranges,
    )
    from korean_font import (
        crop_profile_glyph,
        load_font_profile,
        rasterize_ttf_glyph,
    )
    from psx_font import GLYPH_SIZE, pack_glyph
    from unindexed_font_common import (
        encode_unindexed_entry,
        unindexed_translation_texts,
        validate_unindexed_artifacts,
    )


EXPECTED_START_SHA256 = (
    "d0b22efb4e5ea46c869f822af9bc7f207bc95a670a25acb15fc3dcd2ab3bf8cc"
)
EXPECTED_ALLBIN_SHA256 = (
    "6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e"
)
FONT_OFFSET = 0x1A000
FONT_GLYPH_COUNT = 0x4CD
# These slots are part of the original symbols/digits/Latin region, plus the
# trailing non-Japanese ν/heart symbols. They are never Hangul allocation
# targets, even when a particular character is unused by the translated
# corpus.
PROTECTED_ORIGINAL_GLYPH_RANGES = (
    (0x000, 0x046),
    (0x0E4, 0x0E6),
)
PROTECTED_ORIGINAL_GLYPH_INDICES = frozenset(
    index
    for start, end in PROTECTED_ORIGINAL_GLYPH_RANGES
    for index in range(start, end)
)
NAME_WIDTHS = {
    "{name:surname}": 4,
    "{name:given}": 4,
}
NAME_PATTERN = re.compile(r"\{name:(surname|given)\}")
NAME_KIND_BY_GROUP = {
    "surname": "name_surname",
    "given": "name_given",
}
UNKNOWN_MARKUP_PATTERN = re.compile(r"\{[^{}]+\}")
CONTROL_CONTENT_KINDS = {"glyph", "name_surname", "name_given"}
REMOVABLE_INTERNAL_KINDS = {"align", "name_surname", "name_given"}
UNIT_SHARED_POOL_REFERENCE_PROFILES = {
    0: {
        "scheduled_bytes": 0x3000,
        "reference_count": 189,
        "entry_start_reference_count": 183,
        "gap_reference_count": 6,
        "catalog_sha256": (
            "5829e12496562e919811f93cfb7fdd1d68fc5d2e69272deddcac7770f9b67d1e"
        ),
        "runtime_validation": {
            "status": "passed",
            "date": "2026-07-27",
            "scope": "full-u00-then-u21-chapter-replay",
            "track1_sha256": (
                "39da4bc7eb8d49944be5ad95f4acd73364d1ca1172f186772ca884c15a024b3f"
            ),
        },
    },
    1: {
        "scheduled_bytes": 0x1800,
        "reference_count": 92,
        "entry_start_reference_count": 88,
        "gap_reference_count": 4,
        "catalog_sha256": (
            "612c1b45af94768af4a92abb2af58e65e41fab5d2c5d0d791027f46f3efb75f1"
        ),
    },
    2: {
        "scheduled_bytes": 0x8800,
        "reference_count": 590,
        "entry_start_reference_count": 590,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "53910a9eb313de0cea3cb8c305e92d68015c5ef9e6c01f0718e86909233f6520"
        ),
    },
    3: {
        "scheduled_bytes": 0x3800,
        "reference_count": 183,
        "entry_start_reference_count": 180,
        "gap_reference_count": 3,
        "catalog_sha256": (
            "3de6c56afb7ed54923dbbe932d4466a6aad13b24c1d6f945e926f0b6f69271e0"
        ),
    },
    4: {
        "scheduled_bytes": 0x3800,
        "reference_count": 228,
        "entry_start_reference_count": 226,
        "gap_reference_count": 2,
        "catalog_sha256": (
            "f2d872aa08e723c9d7e60b6c35a72d3deadc0a86a11af4ce02e238465868d5d4"
        ),
    },
    5: {
        "scheduled_bytes": 0x6800,
        "reference_count": 436,
        "entry_start_reference_count": 412,
        "gap_reference_count": 24,
        "catalog_sha256": (
            "8ba15409ad3e13bde91e3179f2c1e9325122c210179c4388a55feb98b888702a"
        ),
    },
    6: {
        "scheduled_bytes": 0x5000,
        "reference_count": 328,
        "entry_start_reference_count": 325,
        "gap_reference_count": 3,
        "catalog_sha256": (
            "83af234eff96e16cfa7f17b69df96bbfd705a942eab412794cbd92ccf7df78e5"
        ),
    },
    7: {
        "scheduled_bytes": 0x6800,
        "reference_count": 453,
        "entry_start_reference_count": 450,
        "gap_reference_count": 3,
        "catalog_sha256": (
            "89788af5df009f714d829623b3f9027c1822149774cf4b96f38736a7ac4e763c"
        ),
    },
    8: {
        "scheduled_bytes": 0x4800,
        "reference_count": 306,
        "entry_start_reference_count": 306,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "ef3bea769fd9961aec6f2cc7a5d871934da2a775c4124117b3bc5accfc3e603c"
        ),
    },
    9: {
        "scheduled_bytes": 0xC000,
        "reference_count": 800,
        "entry_start_reference_count": 788,
        "gap_reference_count": 12,
        "catalog_sha256": (
            "0d199f29ffe2284e0db74b7d288e2cdf3e516377128868ebb629a088ca13aa0d"
        ),
    },
    10: {
        "scheduled_bytes": 0x5800,
        "reference_count": 311,
        "entry_start_reference_count": 310,
        "gap_reference_count": 1,
        "catalog_sha256": (
            "d0816ea6e9207d7e5c215f5e7cad961895bf4e5976ada37315e47271dbc5ee65"
        ),
    },
    11: {
        "scheduled_bytes": 0x2800,
        "reference_count": 141,
        "entry_start_reference_count": 139,
        "gap_reference_count": 2,
        "catalog_sha256": (
            "1dca7ac50cecaf096f63c087ce8e88321fac9c7c4135df1c85e7903782e49299"
        ),
    },
    12: {
        "scheduled_bytes": 0x9000,
        "reference_count": 669,
        "entry_start_reference_count": 664,
        "gap_reference_count": 5,
        "catalog_sha256": (
            "610b7c323b9cd7fc0e550952fde72606b13f2c4e651846d8627fb9aa7a47e9f8"
        ),
    },
    13: {
        "scheduled_bytes": 0x4800,
        "reference_count": 299,
        "entry_start_reference_count": 298,
        "gap_reference_count": 1,
        "catalog_sha256": (
            "09d798d8789e20cee27bcb455a7740d6bb6ee6d8e78920569c8affab5ef73a66"
        ),
    },
    14: {
        "scheduled_bytes": 0xD000,
        "reference_count": 977,
        "entry_start_reference_count": 977,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "4c8b2d565e109dda127aba6ac068c9c3babcdaa710055d73034ffdbe7a47efe4"
        ),
    },
    15: {
        "scheduled_bytes": 0x4000,
        "reference_count": 290,
        "entry_start_reference_count": 290,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "265144f1311d53968637b1b2c13ed10b3a5e54ee347a5412be2694a8eb058b47"
        ),
    },
    16: {
        "scheduled_bytes": 0x8800,
        "reference_count": 582,
        "entry_start_reference_count": 564,
        "gap_reference_count": 18,
        "catalog_sha256": (
            "78bf18f8e558689a214d3fbcfe7c8d93f550f17e9033a4572637a5ac03f99a35"
        ),
    },
    17: {
        "scheduled_bytes": 0x6000,
        "reference_count": 403,
        "entry_start_reference_count": 403,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "a1d25c4469068f1df792b5101a518034650cb1135521c957197383db8e9f9b2c"
        ),
    },
    18: {
        "scheduled_bytes": 0x7800,
        "reference_count": 554,
        "entry_start_reference_count": 551,
        "gap_reference_count": 3,
        "catalog_sha256": (
            "5fc4a8fb11750f67406df2f3e2786033dc2037a060afa0a29213d04a328389bc"
        ),
    },
    19: {
        "scheduled_bytes": 0x2000,
        "reference_count": 106,
        "entry_start_reference_count": 106,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "e81ede673d6ee3ee8ee3ae5427259ce4816c8531905b1ec150f33dc024ef5a24"
        ),
    },
    20: {
        "scheduled_bytes": 0x5000,
        "reference_count": 374,
        "entry_start_reference_count": 374,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "d15da78a122e3f207a3667670e39791300cfad28a64e3a5175f54d37eb8362a7"
        ),
    },
    21: {
        "scheduled_bytes": 0x5000,
        "reference_count": 135,
        "entry_start_reference_count": 135,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "6421b4f9059af3efdbeaee89fe6981469e3232c8f1a1c66139ab69df15f2f7e5"
        ),
        "runtime_validation": {
            "status": "passed",
            "date": "2026-07-27",
            "scope": "full-u00-then-u21-chapter-replay",
            "track1_sha256": (
                "39da4bc7eb8d49944be5ad95f4acd73364d1ca1172f186772ca884c15a024b3f"
            ),
        },
    },
    22: {
        "scheduled_bytes": 0x8000,
        "reference_count": 323,
        "entry_start_reference_count": 323,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "397c6402933263e24ca057ec84c7d13371b78d4480a24a6b76f1d0091505eb3d"
        ),
    },
    23: {
        "scheduled_bytes": 0x6000,
        "reference_count": 290,
        "entry_start_reference_count": 290,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "0b71794c34962fc418a6798327eb5a3b5ada9bb1249a5cadec5cc664d0b39d39"
        ),
    },
    24: {
        "scheduled_bytes": 0x6800,
        "reference_count": 321,
        "entry_start_reference_count": 321,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "eb9c658407c14bf708a866960932cc641215919bf19d6911017fee1c9ddea1c8"
        ),
    },
    25: {
        "scheduled_bytes": 0x6800,
        "reference_count": 202,
        "entry_start_reference_count": 202,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "a0c81526ae4b41cc9dea07f77f2c803df9fff2c37790e5f5f1308fc9358a2f2b"
        ),
    },
    26: {
        "scheduled_bytes": 0x3800,
        "reference_count": 134,
        "entry_start_reference_count": 134,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "dcae579f01d9315dfee90caf25a66d724771c3446b8d4ca8f44ccafd0993344a"
        ),
    },
    27: {
        "scheduled_bytes": 0x6800,
        "reference_count": 195,
        "entry_start_reference_count": 195,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "0feaeca88e51c96af35ab4b0d4e87ac006965f8638b142f54fc170ba5ebb9c5a"
        ),
    },
    28: {
        "scheduled_bytes": 0x4800,
        "reference_count": 157,
        "entry_start_reference_count": 157,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "da56c168478148a277dfb713744841a1ca203ffdb1f8555d3b48df68cb24cae9"
        ),
    },
    29: {
        "scheduled_bytes": 0x6000,
        "reference_count": 189,
        "entry_start_reference_count": 189,
        "gap_reference_count": 0,
        "catalog_sha256": (
            "cbbd6ae681bb0558fa1fedfa890795c86c5a6798a18d87cdaf196f23b9a27107"
        ),
    },
    30: {
        "scheduled_bytes": 0xC000,
        "reference_count": 171,
        "entry_start_reference_count": 167,
        "gap_reference_count": 4,
        "catalog_sha256": (
            "6abc1ce354d0cb98fc2898e363f95a752aaba9e54572e83c95a2ef4e54d6a084"
        ),
    },
    31: {
        "scheduled_bytes": 0xA000,
        "reference_count": 169,
        "entry_start_reference_count": 165,
        "gap_reference_count": 4,
        "catalog_sha256": (
            "72c6ddb3e2aafa985dc8f4a8a7056d154b6de7eede280a1a4aeef9047e85d3eb"
        ),
    },
    32: {
        "scheduled_bytes": 0xC000,
        "reference_count": 170,
        "entry_start_reference_count": 166,
        "gap_reference_count": 4,
        "catalog_sha256": (
            "da15fc4b806bd2283e6c86de4c1b3b672ef6bab61b87b12e2eefe50f97b25cf6"
        ),
    },
    33: {
        "scheduled_bytes": 0x9800,
        "reference_count": 119,
        "entry_start_reference_count": 115,
        "gap_reference_count": 4,
        "catalog_sha256": (
            "d6eb845537c6df793016a89911bb02958fd223f998a45977e1313209aa63061a"
        ),
    },
    34: {
        "scheduled_bytes": 0xC000,
        "reference_count": 174,
        "entry_start_reference_count": 170,
        "gap_reference_count": 4,
        "catalog_sha256": (
            "6b6bb899d84d101924aece491cdfedf4c802a8c0a5fbf26236740cc47a93ade3"
        ),
    },
}

# Frozen against the same verified ALLBIN revision after promoting the
# reviewed sequential/race streams that used to sit inside unclassified gaps.
# Some consumers intentionally target +2, immediately after the preserved
# leading blank word; those anchors are relocated with their owning entry.
ADDITIONAL_UNIT_REFERENCE_PROFILES = {
    2: (0x8800, 590, 590, 0, 0, "53910a9eb313de0cea3cb8c305e92d68015c5ef9e6c01f0718e86909233f6520"),
    3: (0x3800, 183, 183, 0, 0, "3de6c56afb7ed54923dbbe932d4466a6aad13b24c1d6f945e926f0b6f69271e0"),
    4: (0x3800, 232, 229, 0, 3, "b668231d315f638241c2b0c6977945de6f96bc1611a40451f68bb7468b746f8f"),
    5: (0x6800, 438, 438, 0, 0, "5071b27af7de25dcf9f131fbca9324897fe8ea55924d2b57dc2bcd7b35f173c1"),
    6: (0x5000, 328, 328, 0, 0, "83af234eff96e16cfa7f17b69df96bbfd705a942eab412794cbd92ccf7df78e5"),
    7: (0x6800, 454, 454, 0, 0, "fb51f8e5cda38b8633fc2281a352381e1fc252f1686322c72b50c1d44439b62c"),
    8: (0x4800, 307, 307, 0, 0, "0b239a9f2c6e94b8cd7e09cb0a8f77467aa5f703fba155fe7c4aabcedef197dd"),
    9: (0xC000, 802, 800, 0, 2, "adb56fc5c15a88e0a810b82bc2a536571ef60dd0d78e7602021cc75e8a316130"),
    10: (0x5800, 311, 311, 0, 0, "d0816ea6e9207d7e5c215f5e7cad961895bf4e5976ada37315e47271dbc5ee65"),
    11: (0x2800, 141, 141, 0, 0, "1dca7ac50cecaf096f63c087ce8e88321fac9c7c4135df1c85e7903782e49299"),
    12: (0x9000, 669, 669, 0, 0, "610b7c323b9cd7fc0e550952fde72606b13f2c4e651846d8627fb9aa7a47e9f8"),
    13: (0x4800, 300, 300, 0, 0, "cc3d0f46c10557638a19fcbca37caa33ef0938a71820fb04cadb0dd6ba127abf"),
    14: (0xD000, 977, 977, 0, 0, "4c8b2d565e109dda127aba6ac068c9c3babcdaa710055d73034ffdbe7a47efe4"),
    15: (0x4000, 290, 290, 0, 0, "265144f1311d53968637b1b2c13ed10b3a5e54ee347a5412be2694a8eb058b47"),
    16: (0x8800, 582, 582, 0, 0, "78bf18f8e558689a214d3fbcfe7c8d93f550f17e9033a4572637a5ac03f99a35"),
    17: (0x6000, 404, 404, 0, 0, "40136b9cfae670915373eea79fbfea64df30f70684837a76183d00066b20c3d5"),
    18: (0x7800, 554, 554, 0, 0, "5fc4a8fb11750f67406df2f3e2786033dc2037a060afa0a29213d04a328389bc"),
    19: (0x2000, 107, 107, 0, 0, "504a934c91f64c96b9f846eb09bfc563d24a2b022eff7a07c92645099b60fe2d"),
    28: (0x4800, 166, 160, 0, 6, "c77b6f0c96fba98f7b66c2ccd59bceaf19e21ca99d703ba330341ec4ba7c70f2"),
    30: (0xC000, 185, 179, 0, 6, "360b3e283f2b2831126f51c9e1e7b560d1ab861ce6e21bbcce279c66e5c6c1bc"),
    31: (0xA000, 169, 168, 0, 1, "72c6ddb3e2aafa985dc8f4a8a7056d154b6de7eede280a1a4aeef9047e85d3eb"),
    32: (0xC000, 184, 178, 0, 6, "ca747265b128cc76ecef9ea6ccc66ae32b639ceb6e84e73f1bf983a54f2bab34"),
    33: (0x9800, 119, 118, 0, 1, "d6eb845537c6df793016a89911bb02958fd223f998a45977e1313209aa63061a"),
    34: (0xC000, 188, 182, 0, 6, "e5034841023cf22a3a6cf83f43cc5580f429cb73286bfae516f708cba2617cf5"),
}

# u11's blackjack opponent selector does not use stored u32 pointers.  Seven
# random branches construct an address with LUI+ADDIU and deliberately enter
# two strings at +2, after a leading blank word.  These reviewed code operands
# must move with the promoted sequential pages in the unit-shared pool.
SPLIT_IMMEDIATE_DIALOGUE_REFERENCE_SPECS = {
    11: (
        (0x00C0, 0x00C4, 0x3C04800B, 0x24849194,
         "disc1/allbin/u11/unindexed_font/p01192", 2),
        (0x00E4, 0x00EC, 0x3C04800B, 0x248491A4,
         "disc1/allbin/u11/unindexed_font/p011A4", 0),
        (0x0110, 0x0118, 0x3C04800B, 0x248491BC,
         "disc1/allbin/u11/unindexed_font/p011BA", 2),
        (0x013C, 0x0144, 0x3C04800B, 0x24849200,
         "disc1/allbin/u11/unindexed_font/p01200", 0),
        (0x0168, 0x0170, 0x3C04800B, 0x248491D0,
         "disc1/allbin/u11/unindexed_font/p011D0", 0),
        (0x0194, 0x019C, 0x3C04800B, 0x24849210,
         "disc1/allbin/u11/unindexed_font/p01210", 0),
        (0x01C8, 0x01CC, 0x3C04800B, 0x248491F0,
         "disc1/allbin/u11/unindexed_font/p011EE", 2),
    ),
}
ADDITIONAL_UNIT_REFERENCE_PROFILES = {
    unit: {
        "scheduled_bytes": values[0],
        "reference_count": values[1],
        "entry_start_reference_count": values[2],
        "gap_reference_count": values[3],
        "internal_anchor_reference_count": values[4],
        "catalog_sha256": values[5],
    }
    for unit, values in ADDITIONAL_UNIT_REFERENCE_PROFILES.items()
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def changed_ranges(before: bytes, after: bytes) -> list[tuple[int, int]]:
    if len(before) != len(after):
        raise ValueError("expected-write comparison requires equal file sizes")
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, (source, target) in enumerate(zip(before, after)):
        if source != target and start is None:
            start = index
        elif source == target and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(before)))
    return ranges


def merge_allowed_ranges(
    ranges: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if start < 0 or end <= start:
            raise ValueError(f"invalid expected-write range 0x{start:X}:0x{end:X}")
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def verify_expected_writes(
    before: bytes,
    after: bytes,
    *,
    allowed_ranges: Iterable[tuple[int, int]],
    owner: str,
) -> dict[str, Any]:
    allowed = merge_allowed_ranges(allowed_ranges)
    changes = changed_ranges(before, after)
    allowed_index = 0
    for start, end in changes:
        while (
            allowed_index < len(allowed)
            and allowed[allowed_index][1] <= start
        ):
            allowed_index += 1
        if (
            allowed_index == len(allowed)
            or start < allowed[allowed_index][0]
            or end > allowed[allowed_index][1]
        ):
            raise ValueError(
                f"{owner}: unexplained write 0x{start:X}:0x{end:X}"
            )
    return {
        "owner": owner,
        "source_size": len(before),
        "output_size": len(after),
        "changed_byte_count": sum(end - start for start, end in changes),
        "changed_range_count": len(changes),
        "changed_ranges": [
            {
                "start": f"0x{start:X}",
                "end_exclusive": f"0x{end:X}",
                "bytes": end - start,
            }
            for start, end in changes
        ],
        "allowed_ranges": [
            {
                "start": f"0x{start:X}",
                "end_exclusive": f"0x{end:X}",
                "bytes": end - start,
            }
            for start, end in allowed
        ],
        "verified": True,
    }


def visible_width(text: str) -> int:
    width = 0
    cursor = 0
    for match in NAME_PATTERN.finditer(text):
        width += len(text[cursor : match.start()])
        width += NAME_WIDTHS[match.group()]
        cursor = match.end()
    return width + len(text[cursor:])


def text_without_name_tokens(text: str) -> str:
    unknown = [
        markup
        for markup in UNKNOWN_MARKUP_PATTERN.findall(text)
        if not NAME_PATTERN.fullmatch(markup)
    ]
    if unknown:
        raise ValueError(f"unknown dialogue markup remains: {unknown}")
    return NAME_PATTERN.sub("", text)


def required_characters(
    overlay: dict[str, Any],
    *,
    entry_ids: Iterable[str] | None = None,
    extra_texts: Iterable[str] = (),
) -> list[str]:
    entries = overlay.get("entries")
    if not isinstance(entries, list):
        raise ValueError("reflow overlay entries must be an array")
    selected_ids = None if entry_ids is None else frozenset(entry_ids)
    characters: set[str] = set()
    for entry in entries:
        if selected_ids is not None and entry.get("id") not in selected_ids:
            continue
        texts = [
            entry.get("ko_reflowed"),
            entry.get("ko_candidate"),
        ]
        text = next((value for value in texts if isinstance(value, str)), None)
        if text is None:
            raise ValueError(f"{entry.get('id')}: no Korean candidate text")
        text = text_without_name_tokens(text)
        characters.update(character for character in text if not character.isspace())
        if any(character.isspace() for character in text):
            characters.add(" ")
    for text in extra_texts:
        text = text_without_name_tokens(text)
        characters.update(character for character in text if not character.isspace())
        if any(character.isspace() for character in text):
            characters.add(" ")
    return sorted(characters, key=ord)


def load_primary_glyph_map(path: Path) -> dict[str, int]:
    document = load_object(path)
    table = document.get("tables", {}).get("primary")
    if not isinstance(table, dict) or table.get("glyph_count") != FONT_GLYPH_COUNT:
        raise ValueError("primary glyph map has an unexpected size")
    glyphs = table.get("glyphs")
    if not isinstance(glyphs, dict):
        raise ValueError("primary glyph map requires a glyph object")
    result: dict[str, int] = {}
    for index_hex, character in glyphs.items():
        if not isinstance(character, str) or not character:
            raise ValueError(f"invalid primary glyph at {index_hex}")
        result.setdefault(character, int(index_hex, 16))
    return result


def build_static_font(
    source_start: bytes,
    overlay: dict[str, Any],
    *,
    glyph_map_path: Path,
    font_profile_path: Path,
    passthrough_original_glyph_indices: Iterable[int] = (),
    entry_ids: Iterable[str] | None = None,
    extra_texts: Iterable[str] = (),
) -> tuple[bytes, dict[str, int], dict[str, Any]]:
    font_end = FONT_OFFSET + FONT_GLYPH_COUNT * GLYPH_SIZE
    if font_end > len(source_start):
        raise ValueError("primary font region exceeds START.BIN")

    passthrough_indices = frozenset(passthrough_original_glyph_indices)
    invalid_passthrough = sorted(
        index
        for index in passthrough_indices
        if not 0 <= index < FONT_GLYPH_COUNT
    )
    if invalid_passthrough:
        raise ValueError(
            "passthrough original glyph index is outside the primary font: "
            + ", ".join(f"0x{index:X}" for index in invalid_passthrough)
        )
    byte_exact_indices = (
        PROTECTED_ORIGINAL_GLYPH_INDICES | passthrough_indices
    )

    required = required_characters(
        overlay,
        entry_ids=entry_ids,
        extra_texts=extra_texts,
    )
    original_map = load_primary_glyph_map(glyph_map_path)
    mapping: dict[str, int] = {}
    occupied = set(byte_exact_indices)

    # Preserve exact game glyphs for punctuation, Latin, digits, icons, and
    # renderer-special controller symbols whenever the original table has one.
    for character in required:
        if character in original_map:
            index = original_map[character]
            if index in mapping.values():
                raise ValueError(f"duplicate selected glyph index 0x{index:03X}")
            mapping[character] = index
            occupied.add(index)

    free_indices = (
        index
        for index in range(FONT_GLYPH_COUNT)
        if index not in occupied
    )
    for character in required:
        if character not in mapping:
            try:
                mapping[character] = next(free_indices)
            except StopIteration as error:
                raise ValueError(
                    f"primary font capacity exceeded at {character!r}"
                ) from error

    profile = load_font_profile(font_profile_path)
    from PIL import ImageFont

    ttf = ImageFont.truetype(str(profile.source_path), profile.ttf_size_px)
    records = bytearray(FONT_GLYPH_COUNT * GLYPH_SIZE)
    for index in byte_exact_indices:
        source = FONT_OFFSET + index * GLYPH_SIZE
        target = index * GLYPH_SIZE
        records[target : target + GLYPH_SIZE] = source_start[
            source : source + GLYPH_SIZE
        ]
    generated: list[str] = []
    preserved: list[str] = []
    for character, index in sorted(mapping.items(), key=lambda item: item[1]):
        target = index * GLYPH_SIZE
        if character in original_map:
            source_index = original_map[character]
            source = FONT_OFFSET + source_index * GLYPH_SIZE
            records[target : target + GLYPH_SIZE] = source_start[
                source : source + GLYPH_SIZE
            ]
            preserved.append(character)
            continue
        if character == " ":
            generated.append(character)
            continue
        pixels = rasterize_ttf_glyph(
            ttf,
            character,
            x_offset=profile.x_offset_px,
            y_offset=profile.y_offset_px,
        )
        retained = crop_profile_glyph(profile, pixels)
        if not any(retained):
            raise ValueError(
                f"Galmuri11 produced an empty retained glyph for {character!r}"
            )
        records[target : target + GLYPH_SIZE] = pack_glyph(retained)
        generated.append(character)

    patched = bytearray(source_start)
    patched[FONT_OFFSET:font_end] = records
    protected_changed = [
        index
        for index in sorted(byte_exact_indices)
        if patched[
            FONT_OFFSET + index * GLYPH_SIZE :
            FONT_OFFSET + (index + 1) * GLYPH_SIZE
        ]
        != source_start[
            FONT_OFFSET + index * GLYPH_SIZE :
            FONT_OFFSET + (index + 1) * GLYPH_SIZE
        ]
    ]
    if protected_changed:
        changed = ", ".join(f"0x{index:03X}" for index in protected_changed)
        raise ValueError(f"protected original glyph records changed: {changed}")
    report = {
        "font_offset": f"0x{FONT_OFFSET:X}",
        "glyph_count": FONT_GLYPH_COUNT,
        "record_bytes": GLYPH_SIZE,
        "required_character_count": len(required),
        "mapped_character_count": len(mapping),
        "preserved_original_character_count": len(preserved),
        "generated_galmuri11_character_count": len(generated),
        "unused_slot_count": FONT_GLYPH_COUNT - len(
            set(mapping.values()) | byte_exact_indices
        ),
        "protected_original_glyph_ranges": [
            {
                "start": f"0x{start:03X}",
                "end_exclusive": f"0x{end:03X}",
                "glyph_count": end - start,
            }
            for start, end in PROTECTED_ORIGINAL_GLYPH_RANGES
        ],
        "protected_original_glyph_count": len(
            PROTECTED_ORIGINAL_GLYPH_INDICES
        ),
        "protected_original_glyphs_byte_exact": True,
        "passthrough_original_glyph_count": len(passthrough_indices),
        "passthrough_original_glyph_indices": [
            f"0x{index:03X}" for index in sorted(passthrough_indices)
        ],
        "passthrough_original_glyphs_byte_exact": True,
        "total_byte_exact_original_glyph_count": len(byte_exact_indices),
        "dynamic_name_widths": NAME_WIDTHS,
    }
    return bytes(patched), mapping, report


def split_control_shell(entry: dict[str, Any]) -> tuple[list[int], list[int]]:
    tokens = [int(value, 16) for value in entry["original"]["tokens"]]
    controls = {
        int(control["token_index"]): str(control["kind"])
        for control in entry["original"]["control_tokens"]
    }
    content_indices = [
        index
        for index in range(len(tokens))
        if controls.get(index, "glyph") in CONTROL_CONTENT_KINDS
    ]
    if not content_indices:
        raise ValueError(f"{entry['entry_id']}: source has no display content")
    first = min(content_indices)
    last = max(content_indices)

    leading = tokens[:first]
    trailing = tokens[last + 1 :]
    if any(index not in controls for index in range(first)):
        raise ValueError(f"{entry['entry_id']}: leading shell contains a glyph")
    if any(index not in controls for index in range(last + 1, len(tokens))):
        raise ValueError(f"{entry['entry_id']}: trailing shell contains a glyph")

    for index in range(first, last + 1):
        kind = controls.get(index)
        if kind is not None and kind not in REMOVABLE_INTERNAL_KINDS:
            raise ValueError(
                f"{entry['entry_id']}: internal control {kind!r} cannot move"
            )
    return leading, trailing


def encode_entry(
    source_entry: dict[str, Any],
    reflowed_text: str,
    mapping: dict[str, int],
) -> bytes:
    leading, trailing = split_control_shell(source_entry)
    text = reflowed_text
    unknown = [
        markup
        for markup in UNKNOWN_MARKUP_PATTERN.findall(text)
        if not NAME_PATTERN.fullmatch(markup)
    ]
    if unknown:
        raise ValueError(
            f"{source_entry['entry_id']}: unknown markup {unknown}"
        )
    source_tokens = [
        int(value, 16) for value in source_entry["original"]["tokens"]
    ]
    source_name_controls = [
        (
            str(control["kind"]),
            source_tokens[int(control["token_index"])],
        )
        for control in source_entry["original"]["control_tokens"]
        if control["kind"] in {"name_surname", "name_given"}
    ]
    translated_name_kinds = [
        NAME_KIND_BY_GROUP[match.group(1)]
        for match in NAME_PATTERN.finditer(text)
    ]
    if translated_name_kinds != [
        kind for kind, _raw in source_name_controls
    ]:
        raise ValueError(
            f"{source_entry['entry_id']}: dynamic-name token order differs"
        )
    name_raw = iter(raw for _kind, raw in source_name_controls)

    lines = text.split("\n")
    if not 1 <= len(lines) <= 3:
        raise ValueError(f"{source_entry['entry_id']}: invalid reflow row count")
    if any(visible_width(line) > 17 for line in lines):
        raise ValueError(f"{source_entry['entry_id']}: reflow line exceeds 17")

    body: list[int] = []
    position = 0
    while position < len(text):
        if text[position] == "\n":
            body.append(0xFFFB)
            position += 1
            continue
        name_match = NAME_PATTERN.match(text, position)
        if name_match:
            body.append(next(name_raw))
            position = name_match.end()
            continue
        character = text[position]
        if character not in mapping:
            raise ValueError(
                f"{source_entry['entry_id']}: unmapped {character!r}"
            )
        body.append(mapping[character])
        position += 1
    tokens = [*leading, *body, *trailing]
    if any(not 0 <= token <= 0xFFFF for token in tokens):
        raise ValueError(f"{source_entry['entry_id']}: token out of range")
    return struct.pack(f"<{len(tokens)}H", *tokens)


def compact_unit_translation_spaces(
    entries: list[dict[str, Any]],
    texts: dict[str, str],
    streams: dict[str, bytes],
    mapping: dict[str, int],
    *,
    required_bytes: int,
) -> dict[str, Any]:
    """Remove only spaces, deterministically, to recover a unit byte deficit."""
    if required_bytes <= 0 or required_bytes % 2:
        raise ValueError(
            f"unit space compaction requires a positive even byte count: "
            f"{required_bytes}"
        )
    spaces_required = required_bytes // 2
    adjusted = dict(texts)
    removed_by_id: dict[str, int] = defaultdict(int)
    entry_order = {
        entry["entry_id"]: index
        for index, entry in enumerate(entries)
    }
    punctuation = frozenset(
        ".,!?…·:;'\"()[]{}<>。！？、，．：；「」『』（）"
    )

    for _ in range(spaces_required):
        candidates: list[tuple[tuple[int, int, int, int, int], str, int]] = []
        for entry in entries:
            entry_id = entry["entry_id"]
            text = adjusted[entry_id]
            space_count = text.count(" ")
            for position, character in enumerate(text):
                if character != " ":
                    continue
                previous = text[position - 1] if position else ""
                following = (
                    text[position + 1]
                    if position + 1 < len(text)
                    else ""
                )
                punctuation_adjacent = int(
                    previous not in punctuation and following not in punctuation
                )
                candidates.append(
                    (
                        (
                            punctuation_adjacent,
                            removed_by_id[entry_id],
                            -space_count,
                            entry_order[entry_id],
                            -position,
                        ),
                        entry_id,
                        position,
                    )
                )
        if not candidates:
            raise ValueError(
                "unit translation does not contain enough removable spaces "
                f"for {required_bytes} bytes"
            )
        _, entry_id, position = min(candidates)
        value = adjusted[entry_id]
        adjusted[entry_id] = value[:position] + value[position + 1 :]
        removed_by_id[entry_id] += 1

    changes: list[dict[str, Any]] = []
    for entry in entries:
        entry_id = entry["entry_id"]
        removed = removed_by_id.get(entry_id, 0)
        if not removed:
            continue
        before = texts[entry_id]
        after = adjusted[entry_id]
        if re.sub(r"\s+", "", before) != re.sub(r"\s+", "", after):
            raise ValueError(
                f"{entry_id}: unit compaction changed non-space content"
            )
        encoded = encode_entry(entry, after, mapping)
        expected_reduction = removed * 2
        actual_reduction = len(streams[entry_id]) - len(encoded)
        if actual_reduction != expected_reduction:
            raise ValueError(
                f"{entry_id}: space compaction reduced {actual_reduction} "
                f"bytes instead of {expected_reduction}"
            )
        streams[entry_id] = encoded
        changes.append(
            {
                "entry_id": entry_id,
                "removed_space_count": removed,
                "before_line_widths": [
                    visible_width(line)
                    for line in before.split("\n")
                ],
                "after_line_widths": [
                    visible_width(line)
                    for line in after.split("\n")
                ],
            }
        )

    if sum(change["removed_space_count"] for change in changes) != (
        spaces_required
    ):
        raise AssertionError("unit space compaction count differs")
    texts.clear()
    texts.update(adjusted)
    return {
        "status": "applied-nonrelease",
        "required_reduction_bytes": required_bytes,
        "removed_space_count": spaces_required,
        "actual_reduction_bytes": spaces_required * 2,
        "changed_entry_count": len(changes),
        "non_space_content_preserved": True,
        "control_shells_unchanged": True,
        "changes": changes,
    }


def pointerless_template_parts(
    source_entry: dict[str, Any],
) -> list[tuple[str, list[int]]]:
    tokens = [int(value, 16) for value in source_entry["original"]["tokens"]]
    controls = {
        int(control["token_index"]): str(control["kind"])
        for control in source_entry["original"]["control_tokens"]
    }
    parts: list[tuple[str, list[int]]] = []
    current_kind: str | None = None
    current_tokens: list[int] = []
    for index, token in enumerate(tokens):
        kind = controls.get(index)
        part_kind = (
            "mutable"
            if kind is None or kind in REMOVABLE_INTERNAL_KINDS
            else "immutable"
        )
        if current_kind is not None and part_kind != current_kind:
            parts.append((current_kind, current_tokens))
            current_tokens = []
        current_kind = part_kind
        current_tokens.append(token)
    if current_kind is not None:
        parts.append((current_kind, current_tokens))
    return parts


def encode_pointerless_entry(
    source_entry: dict[str, Any],
    translation: dict[str, Any],
    mapping: dict[str, int],
) -> tuple[bytes, dict[str, Any]]:
    parts = pointerless_template_parts(source_entry)
    mutable_parts = [
        tokens for kind, tokens in parts if kind == "mutable"
    ]
    raw_segments = translation.get("ko_segments")
    raw_text = translation.get("ko")
    if raw_segments is not None:
        if not isinstance(raw_segments, list) or not all(
            isinstance(text, str) for text in raw_segments
        ):
            raise ValueError(
                f"{source_entry['entry_id']}: ko_segments must be strings"
            )
        texts = raw_segments
    elif isinstance(raw_text, str):
        texts = [] if not mutable_parts and raw_text == "" else [raw_text]
    else:
        raise ValueError(
            f"{source_entry['entry_id']}: Korean pointerless text is missing"
        )
    if len(texts) != len(mutable_parts):
        raise ValueError(
            f"{source_entry['entry_id']}: {len(texts)} translated segments != "
            f"{len(mutable_parts)} source segments"
        )

    encoded_segments: list[list[int]] = []
    segment_reports: list[dict[str, Any]] = []
    is_choice = source_entry.get("classification") == "pointerless_choice"
    for segment_index, (source_tokens, text) in enumerate(
        zip(mutable_parts, texts)
    ):
        lines = text.split("\n")
        source_rows = source_tokens.count(0xFFFB) + 1
        if is_choice:
            if len(lines) != source_rows:
                raise ValueError(
                    f"{source_entry['entry_id']}: choice segment "
                    f"{segment_index} rows changed: "
                    f"{len(lines)} != {source_rows}"
                )
        elif not 1 <= len(lines) <= 3:
            raise ValueError(
                f"{source_entry['entry_id']}: dialogue segment row count "
                f"{len(lines)} is outside 1..3"
            )
        if any(len(line) > 17 for line in lines):
            raise ValueError(
                f"{source_entry['entry_id']}: pointerless line exceeds 17"
            )
        body: list[int] = []
        for line_index, line in enumerate(lines):
            if line_index:
                body.append(0xFFFB)
            for character in line:
                try:
                    body.append(mapping[character])
                except KeyError as error:
                    raise ValueError(
                        f"{source_entry['entry_id']}: unmapped pointerless "
                        f"character {character!r}"
                    ) from error
        encoded_segments.append(body)
        segment_reports.append(
            {
                "segment_index": segment_index,
                "source_rows": source_rows,
                "output_rows": len(lines),
                "line_widths": [len(line) for line in lines],
                "visible_glyph_count": sum(len(line) for line in lines),
            }
        )

    output_tokens: list[int] = []
    segment_cursor = 0
    immutable_tokens: list[int] = []
    for kind, tokens in parts:
        if kind == "mutable":
            output_tokens.extend(encoded_segments[segment_cursor])
            segment_cursor += 1
        else:
            output_tokens.extend(tokens)
            immutable_tokens.extend(tokens)
    encoded = struct.pack(f"<{len(output_tokens)}H", *output_tokens)
    immutable_raw = struct.pack(
        f"<{len(immutable_tokens)}H",
        *immutable_tokens,
    )
    return encoded, {
        "entry_id": source_entry["entry_id"],
        "classification": source_entry["classification"],
        "segment_count": len(mutable_parts),
        "segments": segment_reports,
        "immutable_control_token_count": len(immutable_tokens),
        "immutable_control_sha256": sha256_bytes(immutable_raw),
        "immutable_controls_preserved": True,
        "source_bytes": int(source_entry["source"]["byte_size"]),
        "encoded_bytes": len(encoded),
    }


def validate_pointerless_artifacts(
    workset: dict[str, Any],
    translations: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    expected_baseline = f"disc1-allbin-{EXPECTED_ALLBIN_SHA256[:16]}"
    if workset.get("baseline_id") != expected_baseline:
        raise ValueError("pointerless workset baseline differs")
    if translations.get("baseline_id") != expected_baseline:
        raise ValueError("pointerless translation baseline differs")
    work_entries = workset.get("entries")
    translated_entries = translations.get("entries")
    if not isinstance(work_entries, list) or not isinstance(
        translated_entries,
        list,
    ):
        raise ValueError("pointerless artifacts require entry arrays")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in work_entries:
        entry_id = entry.get("entry_id")
        if not isinstance(entry_id, str) or entry_id in by_id:
            raise ValueError(
                f"invalid or duplicate pointerless entry ID: {entry_id!r}"
            )
        by_id[entry_id] = entry
    translation_by_id: dict[str, dict[str, Any]] = {}
    for entry in translated_entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or entry_id in translation_by_id:
            raise ValueError(
                f"invalid or duplicate pointerless translation ID: "
                f"{entry_id!r}"
            )
        translation_by_id[entry_id] = entry
    if set(by_id) != set(translation_by_id):
        missing = sorted(set(by_id) - set(translation_by_id))
        extra = sorted(set(translation_by_id) - set(by_id))
        raise ValueError(
            f"pointerless stable ID mismatch: missing={missing} extra={extra}"
        )
    expected_count = translations.get("scope", {}).get(
        "expected_entry_count"
    )
    if len(by_id) != expected_count:
        raise ValueError("pointerless entry count differs from translation scope")
    return by_id, translation_by_id


def pointerless_translation_texts(
    translations: Iterable[dict[str, Any]],
) -> list[str]:
    texts: list[str] = []
    for translation in translations:
        segments = translation.get("ko_segments")
        if segments is not None:
            if not isinstance(segments, list):
                raise ValueError("pointerless ko_segments must be an array")
            texts.extend(str(text) for text in segments)
        else:
            text = translation.get("ko")
            if not isinstance(text, str):
                raise ValueError("pointerless Korean text is missing")
            if text:
                texts.append(text)
    return texts


def fit_fixed_diagnostic_candidate(
    source_entry: dict[str, Any],
    candidate_text: str,
) -> tuple[str, dict[str, Any] | None]:
    """Keep candidate glyphs exact, moving only invalid explicit line breaks.

    The diagnostic mode intentionally tests original text addresses rather
    than a release layout. Most candidate line breaks are therefore retained
    exactly. If an imported candidate itself exceeds the verified 17x3 frame,
    flatten only its newline controls and hard-wrap the unchanged visible
    glyph sequence. This is the previously approved word-split fallback, and
    is reported so it cannot be mistaken for reviewed final typography.
    """
    lines = candidate_text.split("\n")
    if 1 <= len(lines) <= 3 and all(
        visible_width(line) <= 17 for line in lines
    ):
        return candidate_text, None

    flattened = candidate_text.replace("\n", "")
    flattened_width = visible_width(flattened)
    if not 1 <= flattened_width <= 51:
        raise ValueError(
            f"{source_entry['entry_id']}: diagnostic candidate requires "
            f"{flattened_width} glyphs; fixed frame capacity is 51"
        )

    units: list[tuple[str, int]] = []
    cursor = 0
    for match in NAME_PATTERN.finditer(flattened):
        units.extend((character, 1) for character in flattened[cursor:match.start()])
        units.append((match.group(), NAME_WIDTHS[match.group()]))
        cursor = match.end()
    units.extend((character, 1) for character in flattened[cursor:])

    def fit(index: int, rows_left: int) -> tuple[str, ...] | None:
        if index == len(units):
            return ()
        if rows_left == 0:
            return None
        width = 0
        candidates: list[tuple[str, ...]] = []
        for end in range(index, len(units)):
            width += units[end][1]
            if width > 17:
                break
            tail = fit(end + 1, rows_left - 1)
            if tail is not None:
                candidates.append(
                    ("".join(value for value, _width in units[index : end + 1]), *tail)
                )
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda candidate: (
                visible_width(candidate[0]),
                tuple(visible_width(line) for line in candidate),
            ),
        )

    fitted = fit(0, 3)
    if fitted is None:
        raise ValueError(
            f"{source_entry['entry_id']}: dynamic-name token cannot fit "
            "the fixed 17x3 frame"
        )
    adjusted = "\n".join(fitted)
    return adjusted, {
        "entry_id": source_entry["entry_id"],
        "reason": "candidate-explicit-line-exceeds-17",
        "policy": "flatten-newlines-and-hard-wrap-unchanged-glyph-sequence",
        "candidate_line_widths": [visible_width(line) for line in lines],
        "output_line_widths": [
            visible_width(line) for line in adjusted.split("\n")
        ],
        "visible_glyph_sequence_preserved": True,
        "dynamic_name_tokens_preserved": True,
    }


def build_source_ordered_stream(
    unit_data: bytes,
    entries: Iterable[dict[str, Any]],
    streams: dict[str, bytes],
) -> dict[str, Any]:
    """Repack one physical text run without changing any fall-through edge.

    The renderer advances a cursor after 0x8000 and can consume the following
    bytes without loading the next pointer-table entry.  Consequently, a
    size-based allocator is invalid even when every rewritten pointer is
    correct.  Preserve the source order and copy every inter-entry byte
    verbatim; these gaps include alignment words and pointerless continuation
    pages used by choices and multi-page exposition.
    """
    ranges = physical_entry_ranges(entries)
    if not ranges:
        raise ValueError("cannot build an empty physical text stream")

    region_start = ranges[0][0]
    region_end = ranges[-1][1]
    if region_end > len(unit_data):
        raise ValueError("physical text stream exceeds its source unit")

    output = bytearray()
    placements: dict[str, int] = {}
    gaps: list[dict[str, Any]] = []
    cursor = region_start
    previous_entry_id: str | None = None
    for start, end, entry in ranges:
        entry_id = entry["entry_id"]
        if entry_id not in streams:
            raise ValueError(f"{entry_id}: encoded stream is missing")
        gap = unit_data[cursor:start]
        if len(gap) % 2:
            raise ValueError(
                f"{entry_id}: inter-entry gap has an odd byte size"
            )
        output_gap_start = region_start + len(output)
        output.extend(gap)
        gaps.append(
            {
                "after_entry_id": previous_entry_id,
                "before_entry_id": entry_id,
                "source_start": cursor,
                "source_end": start,
                "output_start": output_gap_start,
                "byte_size": len(gap),
                "nonzero_byte_count": sum(byte != 0 for byte in gap),
                "page_end_count": sum(
                    struct.unpack_from("<H", gap, index)[0] == 0x8000
                    for index in range(0, len(gap), 2)
                ),
                "raw": gap,
            }
        )
        placements[entry_id] = region_start + len(output)
        output.extend(streams[entry_id])
        cursor = end
        previous_entry_id = entry_id

    capacity = region_end - region_start
    if len(output) > capacity:
        raise ValueError(
            f"source-ordered text requires {len(output)} bytes but "
            f"the original physical run has {capacity}"
        )
    return {
        "region_start": region_start,
        "region_end": region_end,
        "capacity": capacity,
        "stream": bytes(output),
        "placements": placements,
        "gaps": gaps,
        "physical_entry_ids": [
            entry["entry_id"] for _, _, entry in ranges
        ],
    }


def reference_catalog_sha256(
    references: Iterable[dict[str, Any]],
) -> str:
    canonical = "".join(
        f"{int(reference['storage_unit_offset']):08X}:"
        f"{int(reference['source_target_unit_offset']):08X}\n"
        for reference in references
    )
    return sha256_bytes(canonical.encode("ascii"))


def scan_unit_dialogue_references(
    unit_data: bytes,
    entries: Iterable[dict[str, Any]],
    layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Enumerate every absolute pointer into the physical dialogue run.

    The supported ALLBIN revision stores both a trailing pointer table and
    event/voice operands that point at the same dialogue pages.  The original
    extractor catalogued the table but not the executable event operands.
    Search every byte of the independently loaded unit so an unaligned
    consumer cannot be silently omitted; the fixed-revision profile then
    freezes the exact resulting storage/target population by digest.
    """
    entries_by_start = {
        int(entry["source"]["unit_offset"], 16): entry
        for entry in entries
    }
    load_addresses = {
        int(entry["source"]["runtime_pointer"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for entry in entries_by_start.values()
    }
    if len(load_addresses) != 1:
        raise ValueError("unit dialogue references have mixed load addresses")
    load_address = load_addresses.pop()
    region_start = int(layout["region_start"])
    region_end = int(layout["region_end"])
    gaps = [
        gap
        for gap in layout["gaps"]
        if int(gap["source_end"]) > int(gap["source_start"])
    ]

    references: list[dict[str, Any]] = []
    for storage in range(0, len(unit_data) - 3):
        raw_value = struct.unpack_from("<I", unit_data, storage)[0]
        source_target = raw_value - load_address
        if not region_start <= source_target < region_end:
            continue
        if storage % 4:
            raise ValueError(
                "unit dialogue contains an unaligned absolute reference at "
                f"0x{storage:04X}"
            )

        source_entry = entries_by_start.get(source_target)
        if source_entry is not None:
            output_target = int(layout["placements"][
                source_entry["entry_id"]
            ])
            target_kind = "entry_start"
            target_id = source_entry["entry_id"]
            anchor_delta = 0
        else:
            gap = next(
                (
                    candidate
                    for candidate in gaps
                    if int(candidate["source_start"])
                    <= source_target
                    < int(candidate["source_end"])
                ),
                None,
            )
            if gap is None:
                containing_range = next(
                    (
                        (start, entry)
                        for start, end, entry in physical_entry_ranges(
                            entries_by_start.values()
                        )
                        if start < source_target < end
                    ),
                    None,
                )
                if containing_range is None:
                    raise ValueError(
                        f"absolute reference at 0x{storage:04X} has no "
                        f"preserved dialogue anchor for target "
                        f"0x{source_target:04X}"
                    )
                entry_start, containing_entry = containing_range
                anchor_delta = source_target - entry_start
                source_raw = bytes.fromhex(
                    containing_entry["original"]["raw_hex"]
                )
                if anchor_delta % 2 or anchor_delta >= len(source_raw):
                    raise ValueError(
                        f"{containing_entry['entry_id']}: invalid internal "
                        f"absolute anchor +0x{anchor_delta:X}"
                    )
                output_target = (
                    int(layout["placements"][containing_entry["entry_id"]])
                    + anchor_delta
                )
                target_kind = "entry_internal_anchor"
                target_id = containing_entry["entry_id"]
            else:
                anchor_delta = source_target - int(gap["source_start"])
                output_target = int(gap["output_start"]) + anchor_delta
                target_kind = "preserved_gap"
                target_id = (
                    f"{gap['after_entry_id']}->{gap['before_entry_id']}"
                )

        references.append(
            {
                "storage_unit_offset": storage,
                "raw_value": raw_value,
                "source_target_unit_offset": source_target,
                "output_target_unit_offset": output_target,
                "target_kind": target_kind,
                "target_id": target_id,
                "anchor_delta": anchor_delta,
            }
        )
    return references


def scan_unit_split_immediate_dialogue_references(
    unit_index: int,
    unit_data: bytes,
    entries: Iterable[dict[str, Any]],
    layout: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate reviewed MIPS LUI+ADDIU references into moved dialogue."""
    specs = SPLIT_IMMEDIATE_DIALOGUE_REFERENCE_SPECS.get(unit_index, ())
    if not specs:
        return []
    entries_by_id = {str(entry["entry_id"]): entry for entry in entries}
    load_addresses = {
        int(entry["source"]["runtime_pointer"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for entry in entries_by_id.values()
        if "runtime_pointer" in entry["source"]
    }
    if len(load_addresses) != 1:
        raise ValueError("split dialogue references have mixed load addresses")
    load_address = load_addresses.pop()

    references: list[dict[str, Any]] = []
    for (
        lui_offset,
        addiu_offset,
        expected_lui,
        expected_addiu,
        target_id,
        anchor_delta,
    ) in specs:
        if addiu_offset + 4 > len(unit_data):
            raise ValueError(
                f"unit {unit_index}: split reference lies outside unit"
            )
        lui_word = struct.unpack_from("<I", unit_data, lui_offset)[0]
        addiu_word = struct.unpack_from("<I", unit_data, addiu_offset)[0]
        if (lui_word, addiu_word) != (expected_lui, expected_addiu):
            raise ValueError(
                f"unit {unit_index}: split reference instructions differ "
                f"at 0x{lui_offset:04X}/0x{addiu_offset:04X}"
            )
        if lui_word >> 26 != 0x0F or addiu_word >> 26 != 0x09:
            raise ValueError("split reference is not LUI+ADDIU")
        register = (lui_word >> 16) & 0x1F
        if (
            (addiu_word >> 21) & 0x1F != register
            or (addiu_word >> 16) & 0x1F != register
        ):
            raise ValueError("split reference register flow differs")

        high = lui_word & 0xFFFF
        low = addiu_word & 0xFFFF
        signed_low = low - 0x10000 if low & 0x8000 else low
        source_runtime = ((high << 16) + signed_low) & 0xFFFFFFFF
        source_target = source_runtime - load_address
        try:
            entry = entries_by_id[target_id]
        except KeyError as error:
            raise ValueError(
                f"unit {unit_index}: split target {target_id} is missing"
            ) from error
        entry_start = int(entry["source"]["unit_offset"], 16)
        if source_target != entry_start + anchor_delta:
            raise ValueError(
                f"{target_id}: split source target differs from reviewed anchor"
            )
        output_target = int(layout["placements"][target_id]) + anchor_delta
        references.append(
            {
                "lui_storage_unit_offset": lui_offset,
                "addiu_storage_unit_offset": addiu_offset,
                "raw_lui_word": lui_word,
                "raw_addiu_word": addiu_word,
                "source_target_unit_offset": source_target,
                "output_target_unit_offset": output_target,
                "target_id": target_id,
                "anchor_delta": anchor_delta,
                "register": register,
            }
        )
    return references


def _patch_split_immediate_dialogue_reference(
    allbin: bytearray,
    *,
    unit_file_offset: int,
    load_address: int,
    reference: dict[str, Any],
) -> None:
    target = (
        load_address + int(reference["output_target_unit_offset"])
    ) & 0xFFFFFFFF
    high = ((target + 0x8000) >> 16) & 0xFFFF
    low = target & 0xFFFF
    lui_word = int(reference["raw_lui_word"])
    addiu_word = int(reference["raw_addiu_word"])
    patched_lui = (lui_word & 0xFFFF0000) | high
    patched_addiu = (addiu_word & 0xFFFF0000) | low
    lui_storage = unit_file_offset + int(
        reference["lui_storage_unit_offset"]
    )
    addiu_storage = unit_file_offset + int(
        reference["addiu_storage_unit_offset"]
    )
    if struct.unpack_from("<I", allbin, lui_storage)[0] != lui_word:
        raise ValueError("split LUI source instruction differs")
    if struct.unpack_from("<I", allbin, addiu_storage)[0] != addiu_word:
        raise ValueError("split ADDIU source instruction differs")
    struct.pack_into("<I", allbin, lui_storage, patched_lui)
    struct.pack_into("<I", allbin, addiu_storage, patched_addiu)

    actual_lui = struct.unpack_from("<I", allbin, lui_storage)[0]
    actual_addiu = struct.unpack_from("<I", allbin, addiu_storage)[0]
    actual_high = actual_lui & 0xFFFF
    actual_low = actual_addiu & 0xFFFF
    signed_low = actual_low - 0x10000 if actual_low & 0x8000 else actual_low
    actual_target = ((actual_high << 16) + signed_low) & 0xFFFFFFFF
    if actual_target != target:
        raise ValueError("relocated split dialogue reference differs")


def verify_unit_reference_profile(
    unit_index: int,
    unit_data: bytes,
    references: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    if len(unit_data) != int(profile["scheduled_bytes"]):
        raise ValueError(
            f"unit {unit_index}: scheduled size differs from the frozen "
            "reference profile"
        )
    if len(references) != int(profile["reference_count"]):
        raise ValueError(
            f"unit {unit_index}: exhaustive reference count changed: "
            f"{len(references)} != {profile['reference_count']}"
        )
    kind_counts = defaultdict(int)
    for reference in references:
        kind_counts[str(reference["target_kind"])] += 1
    for kind, profile_key in (
        ("entry_start", "entry_start_reference_count"),
        ("preserved_gap", "gap_reference_count"),
        ("entry_internal_anchor", "internal_anchor_reference_count"),
    ):
        if kind_counts[kind] != int(profile.get(profile_key, 0)):
            raise ValueError(
                f"unit {unit_index}: {kind} reference count changed: "
                f"{kind_counts[kind]} != {profile.get(profile_key, 0)}"
            )
    digest = reference_catalog_sha256(references)
    if digest != profile["catalog_sha256"]:
        raise ValueError(
            f"unit {unit_index}: exhaustive reference catalog digest changed"
        )
    return {
        "scheduled_unit_bytes": len(unit_data),
        "reference_count": len(references),
        "entry_start_reference_count": kind_counts["entry_start"],
        "preserved_gap_reference_count": kind_counts["preserved_gap"],
        "internal_anchor_reference_count": kind_counts[
            "entry_internal_anchor"
        ],
        "catalog_sha256": digest,
        "verified": True,
    }


def passthrough_gap_glyph_indices(
    allbin: bytes,
    entries_by_unit: dict[int, list[dict[str, Any]]],
) -> frozenset[int]:
    indices: set[int] = set()
    for entries in entries_by_unit.values():
        ranges = physical_entry_ranges(entries)
        unit_file_offsets = {
            int(entry["source"]["file_offset"], 16)
            - int(entry["source"]["unit_offset"], 16)
            for _, _, entry in ranges
        }
        if len(unit_file_offsets) != 1:
            raise ValueError("inconsistent source unit file offset")
        unit_file_offset = unit_file_offsets.pop()
        cursor = ranges[0][0]
        for start, end, _ in ranges:
            gap = allbin[
                unit_file_offset + cursor : unit_file_offset + start
            ]
            if len(gap) % 2:
                raise ValueError("inter-entry gap has an odd byte size")
            for index in range(0, len(gap), 2):
                token = struct.unpack_from("<H", gap, index)[0]
                if token < 0x4000:
                    indices.add(token)
            cursor = end
    return frozenset(indices)


def relink_unit_shared_pool(
    allbin: bytearray,
    entries: list[dict[str, Any]],
    reflow_by_id: dict[str, dict[str, Any]],
    mapping: dict[str, int],
    *,
    reference_profile: dict[str, Any] | None = None,
    pointerless_entries: Iterable[dict[str, Any]] = (),
    pointerless_translation_by_id: dict[str, dict[str, Any]] | None = None,
    additional_entries: Iterable[dict[str, Any]] = (),
    additional_translation_by_id: dict[str, dict[str, Any]] | None = None,
    allow_unit_capacity_space_compaction: bool = False,
) -> dict[str, Any]:
    """Repack a complete unit-local dialogue arena and relink every consumer."""
    if not entries:
        raise ValueError("cannot relink an empty unit")
    unit_index = int(entries[0]["source"]["unit_index"])
    if any(int(entry["source"]["unit_index"]) != unit_index for entry in entries):
        raise ValueError("unit shared pool received mixed units")
    pointerless_entries = list(pointerless_entries)
    additional_entries = list(additional_entries)
    promoted_entries = [*pointerless_entries, *additional_entries]
    if any(
        int(entry["source"]["unit_index"]) != unit_index
        for entry in promoted_entries
    ):
        raise ValueError("unit shared pool received mixed pointerless units")
    if promoted_entries and pointerless_translation_by_id is None:
        if pointerless_entries:
            raise ValueError("pointerless translations are required")
    if pointerless_translation_by_id is None:
        pointerless_translation_by_id = {}
    if additional_entries and additional_translation_by_id is None:
        raise ValueError("additional translations are required")
    if additional_translation_by_id is None:
        additional_translation_by_id = {}
    if reference_profile is None:
        try:
            reference_profile = (
                ADDITIONAL_UNIT_REFERENCE_PROFILES[unit_index]
                if additional_entries
                else UNIT_SHARED_POOL_REFERENCE_PROFILES[unit_index]
            )
        except KeyError as error:
            raise ValueError(
                f"unit {unit_index}: no frozen shared-pool reference profile"
            ) from error

    direct_ranges = physical_entry_ranges(entries)
    promoted_ranges = physical_entry_ranges(promoted_entries)
    unit_file_offsets = {
        int(entry["source"]["file_offset"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for _, _, entry in [*direct_ranges, *promoted_ranges]
    }
    if len(unit_file_offsets) != 1:
        raise ValueError(f"unit {unit_index}: inconsistent file offset")
    unit_file_offset = unit_file_offsets.pop()
    scheduled_bytes = int(reference_profile["scheduled_bytes"])
    source_unit = bytes(
        allbin[unit_file_offset : unit_file_offset + scheduled_bytes]
    )
    if len(source_unit) != scheduled_bytes:
        raise ValueError(f"unit {unit_index}: source ALLBIN unit is truncated")

    for _, _, entry in [*direct_ranges, *promoted_ranges]:
        offset = int(entry["source"]["unit_offset"], 16)
        raw = bytes.fromhex(entry["original"]["raw_hex"])
        if source_unit[offset : offset + len(raw)] != raw:
            raise ValueError(f"{entry['entry_id']}: source ALLBIN bytes differ")

    baseline_entries = (
        [*entries, *promoted_entries] if additional_entries else entries
    )
    original_direct_streams = {
        entry["entry_id"]: bytes.fromhex(entry["original"]["raw_hex"])
        for entry in baseline_entries
    }
    original_direct_layout = build_source_ordered_stream(
        source_unit,
        baseline_entries,
        original_direct_streams,
    )
    baseline_references = scan_unit_dialogue_references(
        source_unit,
        baseline_entries,
        original_direct_layout,
    )
    reference_report = verify_unit_reference_profile(
        unit_index,
        source_unit,
        baseline_references,
        reference_profile,
    )

    streams: dict[str, bytes] = {}
    reflow_texts: dict[str, str] = {}
    translation_input_counts: dict[str, int] = defaultdict(int)
    shell_token_count = 0
    for _, _, entry in direct_ranges:
        entry_id = entry["entry_id"]
        derived = reflow_by_id[entry_id]
        if derived.get("status") != "ready":
            raise ValueError(
                f"{entry_id}: reinsertion blocker {derived.get('status')}"
            )
        candidate_text = derived.get("ko_candidate")
        reflowed_text = derived.get("ko_reflowed")
        if not isinstance(candidate_text, str):
            raise ValueError(f"{entry_id}: missing reviewed Korean candidate")
        candidate_lines = candidate_text.split("\n")
        candidate_fits = (
            1 <= len(candidate_lines) <= 3
            and all(visible_width(line) <= 17 for line in candidate_lines)
        )
        if candidate_fits:
            text = candidate_text
            translation_input_counts["ko_candidate"] += 1
        else:
            if not isinstance(reflowed_text, str):
                raise ValueError(f"{entry_id}: missing audited Korean reflow")
            text = reflowed_text
            translation_input_counts["ko_reflowed"] += 1
        encoded = encode_entry(entry, text, mapping)
        leading, trailing = split_control_shell(entry)
        leading_raw = struct.pack(f"<{len(leading)}H", *leading)
        trailing_raw = struct.pack(f"<{len(trailing)}H", *trailing)
        if not encoded.startswith(leading_raw) or not encoded.endswith(
            trailing_raw
        ):
            raise ValueError(f"{entry_id}: protected control shell changed")
        shell_token_count += len(leading) + len(trailing)
        streams[entry_id] = encoded
        reflow_texts[entry_id] = text

    pointerless_reports: list[dict[str, Any]] = []
    for entry in pointerless_entries:
        entry_id = entry["entry_id"]
        try:
            translation = pointerless_translation_by_id[entry_id]
        except KeyError as error:
            raise ValueError(
                f"{entry_id}: pointerless translation is missing"
            ) from error
        encoded, report = encode_pointerless_entry(
            entry,
            translation,
            mapping,
        )
        streams[entry_id] = encoded
        shell_token_count += int(report["immutable_control_token_count"])
        pointerless_reports.append(report)

    additional_reports: list[dict[str, Any]] = []
    for entry in additional_entries:
        entry_id = entry["entry_id"]
        try:
            translation = additional_translation_by_id[entry_id]
        except KeyError as error:
            raise ValueError(
                f"{entry_id}: additional translation is missing"
            ) from error
        encoded, report = encode_unindexed_entry(
            entry,
            translation,
            mapping,
        )
        streams[entry_id] = encoded
        shell_token_count += (
            int(report["prefix_shell_bytes"])
            + int(report["suffix_shell_bytes"])
        ) // 2
        additional_reports.append(report)

    combined_entries = [*entries, *promoted_entries]
    ranges = physical_entry_ranges(combined_entries)
    region_start = ranges[0][0]
    region_end = ranges[-1][1]
    capacity = region_end - region_start
    cursor = region_start
    preserved_gap_bytes = 0
    for start, end, _ in ranges:
        preserved_gap_bytes += start - cursor
        cursor = end
    required_output_bytes = (
        sum(len(stream) for stream in streams.values())
        + preserved_gap_bytes
    )
    unit_capacity_space_compaction: dict[str, Any] = {
        "status": "not-needed",
        "required_reduction_bytes": 0,
        "removed_space_count": 0,
        "actual_reduction_bytes": 0,
        "changed_entry_count": 0,
        "non_space_content_preserved": True,
        "control_shells_unchanged": True,
        "changes": [],
    }
    if required_output_bytes > capacity:
        deficit = required_output_bytes - capacity
        if not allow_unit_capacity_space_compaction:
            raise ValueError(
                f"unit {unit_index}: translated arena requires "
                f"{required_output_bytes} bytes but the original physical "
                f"run has {capacity}; deficit={deficit}"
            )
        unit_capacity_space_compaction = compact_unit_translation_spaces(
            entries,
            reflow_texts,
            streams,
            mapping,
            required_bytes=deficit,
        )

    try:
        layout = build_source_ordered_stream(
            source_unit,
            combined_entries,
            streams,
        )
    except ValueError as error:
        raise ValueError(f"unit {unit_index}: {error}") from error
    region_start = int(layout["region_start"])
    region_end = int(layout["region_end"])
    capacity = int(layout["capacity"])
    packed_stream = bytes(layout["stream"])
    padding_bytes = capacity - len(packed_stream)
    if padding_bytes < 0 or padding_bytes % 2:
        raise ValueError(
            f"unit {unit_index}: invalid shared-pool padding {padding_bytes}"
        )

    references = scan_unit_dialogue_references(
        source_unit,
        combined_entries,
        layout,
    )
    split_immediate_references = (
        scan_unit_split_immediate_dialogue_references(
            unit_index,
            source_unit,
            combined_entries,
            layout,
        )
    )
    if (
        len(references) != len(baseline_references)
        or reference_catalog_sha256(references)
        != reference_catalog_sha256(baseline_references)
    ):
        raise ValueError(
            f"unit {unit_index}: promoted reference catalog changed"
        )
    known_storages = {
        int(reference["storage_unit_offset"], 16)
        for entry in entries
        for reference in entry["source"]["pointer_references"]
    }
    promoted_storages = {
        int(offset, 16)
        for entry in promoted_entries
        for offset in entry["source"].get("reference_unit_offsets", [])
    }
    known_storages.update(promoted_storages)
    catalog_storages = {
        int(reference["storage_unit_offset"])
        for reference in references
    }
    if not known_storages <= catalog_storages:
        missing = sorted(known_storages - catalog_storages)
        raise ValueError(
            f"unit {unit_index}: known pointer catalog entries disappeared: "
            + ", ".join(f"0x{offset:04X}" for offset in missing)
        )

    runtime_validation = {
        "status": "not-run",
        "reason": (
            (
                "pointerless pages were promoted, translated, and repacked; "
                "the exact output requires a new runtime replay"
            )
            if promoted_entries
            else (
                "the unit dialogue arena was repacked and all consumers were "
                "relocated; the exact output requires a runtime replay"
            )
        ),
    }
    output_region = packed_stream + bytes(padding_bytes)
    if len(output_region) != capacity:
        raise ValueError(f"unit {unit_index}: shared arena size changed")
    allbin[
        unit_file_offset + region_start :
        unit_file_offset + region_end
    ] = output_region

    load_addresses = {
        int(entry["source"]["runtime_pointer"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for entry in combined_entries
    }
    if len(load_addresses) != 1:
        raise ValueError(f"unit {unit_index}: inconsistent runtime load address")
    load_address = load_addresses.pop()
    streams_by_id = streams
    entries_by_id = {
        entry["entry_id"]: entry for entry in combined_entries
    }
    for reference in references:
        if reference["target_kind"] != "entry_internal_anchor":
            continue
        entry_id = str(reference["target_id"])
        anchor_delta = int(reference["anchor_delta"])
        source_raw = bytes.fromhex(
            entries_by_id[entry_id]["original"]["raw_hex"]
        )
        if (
            streams_by_id[entry_id][:anchor_delta]
            != source_raw[:anchor_delta]
        ):
            raise ValueError(
                f"{entry_id}: relocated internal anchor prefix changed"
            )
    for reference in split_immediate_references:
        entry_id = str(reference["target_id"])
        anchor_delta = int(reference["anchor_delta"])
        if not anchor_delta:
            continue
        source_raw = bytes.fromhex(
            entries_by_id[entry_id]["original"]["raw_hex"]
        )
        if (
            streams_by_id[entry_id][:anchor_delta]
            != source_raw[:anchor_delta]
        ):
            raise ValueError(
                f"{entry_id}: relocated split-immediate anchor prefix changed"
            )
    for reference in references:
        storage = unit_file_offset + int(reference["storage_unit_offset"])
        actual = struct.unpack_from("<I", allbin, storage)[0]
        if actual != int(reference["raw_value"]):
            raise ValueError(
                f"unit {unit_index}: reference source differs at "
                f"0x{int(reference['storage_unit_offset']):04X}"
            )
        struct.pack_into(
            "<I",
            allbin,
            storage,
            load_address + int(reference["output_target_unit_offset"]),
        )

    for reference in split_immediate_references:
        _patch_split_immediate_dialogue_reference(
            allbin,
            unit_file_offset=unit_file_offset,
            load_address=load_address,
            reference=reference,
        )

    for reference in references:
        storage = unit_file_offset + int(reference["storage_unit_offset"])
        expected = load_address + int(reference["output_target_unit_offset"])
        actual = struct.unpack_from("<I", allbin, storage)[0]
        if actual != expected:
            raise ValueError(
                f"unit {unit_index}: relocated reference differs at "
                f"0x{int(reference['storage_unit_offset']):04X}"
            )

    for _, _, entry in ranges:
        entry_id = entry["entry_id"]
        placement = int(layout["placements"][entry_id])
        stream = streams[entry_id]
        if allbin[
            unit_file_offset + placement :
            unit_file_offset + placement + len(stream)
        ] != stream:
            raise ValueError(f"{entry_id}: relocated stream verification failed")

    safe_slots = {
        record.entry_id: record
        for record in fixed_original_safe_slots(source_unit, combined_entries)
    }
    original_slot_overflows = [
        {
            "entry_id": entry["entry_id"],
            "source_unit_offset": entry["source"]["unit_offset"],
            "original_safe_slot_bytes": safe_slots[
                entry["entry_id"]
            ].safe_slot_bytes,
            "encoded_bytes": len(streams[entry["entry_id"]]),
            "overflow_bytes": (
                len(streams[entry["entry_id"]])
                - safe_slots[entry["entry_id"]].safe_slot_bytes
            ),
        }
        for _, _, entry in ranges
        if len(streams[entry["entry_id"]])
        > safe_slots[entry["entry_id"]].safe_slot_bytes
    ]

    gaps = [
        gap for gap in layout["gaps"] if gap["after_entry_id"] is not None
    ]
    return {
        "unit_index": unit_index,
        "unit_file_offset": f"0x{unit_file_offset:X}",
        "entry_count": len(ranges),
        "direct_entry_count": len(entries),
        "promoted_pointerless_entry_count": len(pointerless_entries),
        "promoted_additional_entry_count": len(additional_entries),
        "placement_policy": "unit-shared-pool",
        "translation_input_policy": (
            "preserve ko_candidate when it already fits 17x3; otherwise use "
            "audited ko_reflowed; pointerless pages use ko/ko_segments; "
            "reviewed additional streams use ko"
        ),
        "translation_input_counts": dict(
            sorted(translation_input_counts.items())
        ),
        "original_text_bytes": sum(
            int(entry["source"]["byte_size"]) for entry in combined_entries
        ),
        "encoded_text_bytes": sum(len(stream) for stream in streams.values()),
        "physical_region_start": f"0x{region_start:04X}",
        "physical_region_end_exclusive": f"0x{region_end:04X}",
        "physical_region_capacity_bytes": capacity,
        "packed_dialogue_and_other_bytes": len(packed_stream),
        "tail_padding_bytes": padding_bytes,
        "tail_padding_token": "0x0000",
        "tail_padding_position": "after-final-repacked-span",
        "tail_padding_runtime_status": (
            "no-catalogued-target-runtime-fallthrough-validation-required"
        ),
        "output_physical_region_bytes": len(output_region),
        "unit_capacity_preserved": len(output_region) == capacity,
        "original_slot_overflow_count": len(original_slot_overflows),
        "original_slot_overflows": original_slot_overflows,
        "protected_control_shell_token_count": shell_token_count,
        "protected_control_shell_entry_count": len(combined_entries),
        "protected_control_shells_byte_exact": True,
        "unit_capacity_space_compaction": unit_capacity_space_compaction,
        "inter_entry_gap_count": len(gaps),
        "inter_entry_gap_bytes": sum(int(gap["byte_size"]) for gap in gaps),
        "inter_entry_gaps_byte_exact": True,
        "pointerless_page_count": len(pointerless_entries),
        "pointerless_pages_promoted_and_translated": bool(
            pointerless_entries
        ),
        "pointerless_entries": pointerless_reports,
        "additional_entry_count": len(additional_entries),
        "additional_entries_promoted_and_translated": bool(
            additional_entries
        ),
        "additional_entries": additional_reports,
        "reference_catalog": {
            **reference_report,
            "relocated_reference_count": len(references),
            "relocated_catalog_sha256": reference_catalog_sha256(references),
            "promoted_pointerless_reference_count": len(promoted_storages),
            "known_extractor_reference_count": len(known_storages),
            "additional_event_consumer_reference_count": (
                len(references) - len(known_storages)
            ),
            "all_relocated_and_verified": True,
        },
        "split_immediate_reference_catalog": {
            "reference_count": len(split_immediate_references),
            "reviewed_exact_instruction_pairs": True,
            "all_relocated_and_verified": True,
        },
        "runtime_validation": runtime_validation,
        "references": [
            {
                "storage_unit_offset": (
                    f"0x{int(reference['storage_unit_offset']):04X}"
                ),
                "source_target_unit_offset": (
                    f"0x{int(reference['source_target_unit_offset']):04X}"
                ),
                "output_target_unit_offset": (
                    f"0x{int(reference['output_target_unit_offset']):04X}"
                ),
                "target_kind": reference["target_kind"],
                "target_id": reference["target_id"],
                "anchor_delta": int(reference["anchor_delta"]),
            }
            for reference in references
        ],
        "split_immediate_references": [
            {
                "lui_storage_unit_offset": (
                    f"0x{int(reference['lui_storage_unit_offset']):04X}"
                ),
                "addiu_storage_unit_offset": (
                    f"0x{int(reference['addiu_storage_unit_offset']):04X}"
                ),
                "source_target_unit_offset": (
                    f"0x{int(reference['source_target_unit_offset']):04X}"
                ),
                "output_target_unit_offset": (
                    f"0x{int(reference['output_target_unit_offset']):04X}"
                ),
                "target_id": reference["target_id"],
                "anchor_delta": int(reference["anchor_delta"]),
            }
            for reference in split_immediate_references
        ],
        "physical_entries": [
            {
                "entry_id": entry_id,
                "source_unit_offset": next(
                    entry["source"]["unit_offset"]
                    for entry in combined_entries
                    if entry["entry_id"] == entry_id
                ),
                "output_unit_offset": (
                    f"0x{int(layout['placements'][entry_id]):04X}"
                ),
                "encoded_bytes": len(streams[entry_id]),
            }
            for entry_id in layout["physical_entry_ids"]
        ],
        "warning": (
            "Unit-local relink: every frozen event/table reference and every "
            "reviewed split MIPS address operand is updated, and pointerless "
            "pages are promoted as translated physical entries. Post-final "
            "padding and full control flow still require runtime replay."
        ),
    }


def repack_unit(
    allbin: bytearray,
    entries: list[dict[str, Any]],
    reflow_by_id: dict[str, dict[str, Any]],
    mapping: dict[str, int],
) -> dict[str, Any]:
    if not entries:
        raise ValueError("cannot repack an empty unit")
    unit_index = int(entries[0]["source"]["unit_index"])
    if any(int(entry["source"]["unit_index"]) != unit_index for entry in entries):
        raise ValueError("repack_unit received mixed units")
    if not 0 <= unit_index <= 20:
        raise ValueError(
            f"unit {unit_index}: chapter repacker currently supports story 0..20"
        )

    for entry in entries:
        offset = int(entry["source"]["file_offset"], 16)
        raw = bytes.fromhex(entry["original"]["raw_hex"])
        if allbin[offset : offset + len(raw)] != raw:
            raise ValueError(f"{entry['entry_id']}: source ALLBIN bytes differ")

    streams: dict[str, bytes] = {}
    for entry in entries:
        derived = reflow_by_id[entry["entry_id"]]
        if derived.get("status") != "ready":
            raise ValueError(
                f"{entry['entry_id']}: reinsertion blocker "
                f"{derived.get('status')}"
            )
        text = derived.get("ko_reflowed")
        if not isinstance(text, str):
            raise ValueError(f"{entry['entry_id']}: missing reflowed text")
        streams[entry["entry_id"]] = encode_entry(entry, text, mapping)

    unit_file_offset = min(
        int(entry["source"]["file_offset"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for entry in entries
    )
    unit_data = bytes(
        allbin[
            unit_file_offset :
            unit_file_offset
            + max(
                int(entry["source"]["unit_offset"], 16)
                + int(entry["source"]["byte_size"])
                for entry in entries
            )
        ]
    )
    layout = build_source_ordered_stream(unit_data, entries, streams)
    placements = layout["placements"]
    entry_point = min(
        entries,
        key=lambda entry: int(entry["source"]["unit_offset"], 16),
    )
    entry_point_offset = int(entry_point["source"]["unit_offset"], 16)
    load_addresses = {
        int(entry["source"]["runtime_pointer"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for entry in entries
    }
    if len(load_addresses) != 1:
        raise ValueError(f"unit {unit_index}: inconsistent runtime load address")
    load_address = load_addresses.pop()

    region_start = int(layout["region_start"])
    region_end = int(layout["region_end"])
    packed_stream = bytes(layout["stream"])
    allbin[
        unit_file_offset + region_start :
        unit_file_offset + region_end
    ] = bytes(region_end - region_start)
    allbin[
        unit_file_offset + region_start :
        unit_file_offset + region_start + len(packed_stream)
    ] = packed_stream
    pointer_write_count = 0
    pointer_storages: set[int] = set()
    for entry in entries:
        entry_id = entry["entry_id"]
        unit_offset = placements[entry_id]
        stream = streams[entry_id]
        absolute = unit_file_offset + unit_offset
        allbin[absolute : absolute + len(stream)] = stream
        pointer = load_address + unit_offset
        for reference in entry["source"]["pointer_references"]:
            storage = int(reference["storage_file_offset"], 16)
            if storage in pointer_storages:
                raise ValueError(
                    f"{entry_id}: duplicate pointer storage 0x{storage:X}"
                )
            pointer_storages.add(storage)
            expected = int(reference["raw_value"], 16)
            actual = struct.unpack_from("<I", allbin, storage)[0]
            if actual != expected:
                raise ValueError(
                    f"{entry_id}: pointer source differs at 0x{storage:X}"
                )
            struct.pack_into("<I", allbin, storage, pointer)
            pointer_write_count += 1

    verified_pointer_count = 0
    for entry in entries:
        entry_id = entry["entry_id"]
        unit_offset = placements[entry_id]
        stream = streams[entry_id]
        absolute = unit_file_offset + unit_offset
        if allbin[absolute : absolute + len(stream)] != stream:
            raise ValueError(f"{entry_id}: encoded stream verification failed")
        expected_pointer = load_address + unit_offset
        for reference in entry["source"]["pointer_references"]:
            storage = int(reference["storage_file_offset"], 16)
            actual_pointer = struct.unpack_from("<I", allbin, storage)[0]
            if actual_pointer != expected_pointer:
                raise ValueError(
                    f"{entry_id}: rewritten pointer identity differs at "
                    f"0x{storage:X}"
                )
            verified_pointer_count += 1

    physical_ids = list(layout["physical_entry_ids"])
    gap_by_edge = {
        (gap["after_entry_id"], gap["before_entry_id"]): gap
        for gap in layout["gaps"]
        if gap["after_entry_id"] is not None
    }
    fallthrough_edge_count = 0
    for previous_id, next_id in zip(physical_ids, physical_ids[1:]):
        gap = gap_by_edge[(previous_id, next_id)]
        expected_next = (
            placements[previous_id]
            + len(streams[previous_id])
            + int(gap["byte_size"])
        )
        if placements[next_id] != expected_next:
            raise ValueError(
                f"{next_id}: physical fall-through edge was split after "
                f"{previous_id}"
            )
        output_gap_start = (
            unit_file_offset
            + placements[previous_id]
            + len(streams[previous_id])
        )
        raw_gap = bytes(gap["raw"])
        if allbin[
            output_gap_start : output_gap_start + len(raw_gap)
        ] != raw_gap:
            raise ValueError(
                f"{next_id}: physical fall-through gap changed after "
                f"{previous_id}"
            )
        fallthrough_edge_count += 1

    entry_point_stream = streams[entry_point["entry_id"]]
    entry_point_absolute = unit_file_offset + entry_point_offset
    entry_point_verified = (
        placements[entry_point["entry_id"]] == entry_point_offset
        and allbin[
            entry_point_absolute :
            entry_point_absolute + len(entry_point_stream)
        ]
        == entry_point_stream
    )
    if not entry_point_verified:
        raise ValueError(
            f"{entry_point['entry_id']}: fixed entry point was not preserved"
        )

    return {
        "unit_index": unit_index,
        "unit_file_offset": f"0x{unit_file_offset:X}",
        "entry_count": len(entries),
        "original_text_bytes": sum(
            int(entry["source"]["byte_size"]) for entry in entries
        ),
        "encoded_text_bytes": sum(len(stream) for stream in streams.values()),
        "physical_region_start": f"0x{region_start:04X}",
        "physical_region_end_exclusive": f"0x{region_end:04X}",
        "physical_region_capacity_bytes": int(layout["capacity"]),
        "packed_physical_stream_bytes": len(packed_stream),
        "physical_region_spare_bytes": (
            int(layout["capacity"]) - len(packed_stream)
        ),
        "pointer_write_count": pointer_write_count,
        "stable_id_stream_verification_count": len(entries),
        "pointer_identity_verification_count": verified_pointer_count,
        "physical_entry_count": len(physical_ids),
        "physical_fallthrough_edge_verification_count": (
            fallthrough_edge_count
        ),
        "inter_entry_gap_count": len(layout["gaps"]) - 1,
        "inter_entry_gap_bytes": sum(
            int(gap["byte_size"])
            for gap in layout["gaps"]
            if gap["after_entry_id"] is not None
        ),
        "pointerless_page_count": sum(
            int(gap["page_end_count"]) for gap in layout["gaps"]
        ),
        "fixed_entry_point": {
            "entry_id": entry_point["entry_id"],
            "unit_offset": f"0x{entry_point_offset:04X}",
            "encoded_bytes": len(entry_point_stream),
            "preserved": True,
        },
        "runtime_load_address": f"0x{load_address:08X}",
        "physical_entries": [
            {
                "entry_id": entry_id,
                "source_unit_offset": next(
                    entry["source"]["unit_offset"]
                    for entry in entries
                    if entry["entry_id"] == entry_id
                ),
                "output_unit_offset": f"0x{placements[entry_id]:04X}",
                "encoded_bytes": len(streams[entry_id]),
            }
            for entry_id in physical_ids
        ],
        "inter_entry_gaps": [
            {
                "after_entry_id": gap["after_entry_id"],
                "before_entry_id": gap["before_entry_id"],
                "source_unit_start": f"0x{gap['source_start']:04X}",
                "source_unit_end_exclusive": f"0x{gap['source_end']:04X}",
                "output_unit_start": f"0x{gap['output_start']:04X}",
                "bytes": gap["byte_size"],
                "nonzero_byte_count": gap["nonzero_byte_count"],
                "pointerless_page_count": gap["page_end_count"],
                "sha256": sha256_bytes(bytes(gap["raw"])),
            }
            for gap in layout["gaps"]
            if gap["after_entry_id"] is not None
        ],
    }


def write_unit_at_original_offsets_diagnostic(
    allbin: bytearray,
    entries: list[dict[str, Any]],
    reflow_by_id: dict[str, dict[str, Any]],
    mapping: dict[str, int],
) -> dict[str, Any]:
    """Write complete translated streams at immutable original entry starts.

    This deliberately permits a stream to overwrite the following entry or a
    pointerless fall-through page. Writes run from high to low addresses so
    the earlier dialogue remains complete and the first real slot overflow is
    observable at the following entry. It is a runtime diagnostic, never a
    release-capable placement policy.
    """
    if not entries:
        raise ValueError("cannot write an empty unit")
    unit_index = int(entries[0]["source"]["unit_index"])
    if any(int(entry["source"]["unit_index"]) != unit_index for entry in entries):
        raise ValueError("fixed diagnostic received mixed units")
    if not 0 <= unit_index <= 21:
        raise ValueError(
            f"unit {unit_index}: fixed diagnostic supports units 0..21"
        )

    ranges = physical_entry_ranges(entries)
    unit_file_offsets = {
        int(entry["source"]["file_offset"], 16)
        - int(entry["source"]["unit_offset"], 16)
        for _, _, entry in ranges
    }
    if len(unit_file_offsets) != 1:
        raise ValueError(f"unit {unit_index}: inconsistent file offset")
    unit_file_offset = unit_file_offsets.pop()

    for _, _, entry in ranges:
        offset = int(entry["source"]["file_offset"], 16)
        raw = bytes.fromhex(entry["original"]["raw_hex"])
        if allbin[offset : offset + len(raw)] != raw:
            raise ValueError(f"{entry['entry_id']}: source ALLBIN bytes differ")

    streams: dict[str, bytes] = {}
    layout_adjustments: list[dict[str, Any]] = []
    for _, _, entry in ranges:
        entry_id = entry["entry_id"]
        derived = reflow_by_id[entry_id]
        text = derived.get("ko_candidate")
        if not isinstance(text, str):
            raise ValueError(f"{entry_id}: missing original Korean candidate")
        fitted_text, adjustment = fit_fixed_diagnostic_candidate(entry, text)
        if adjustment is not None:
            layout_adjustments.append(adjustment)
        streams[entry_id] = encode_entry(entry, fitted_text, mapping)

    original_unit = bytes(
        allbin[unit_file_offset : unit_file_offset + ranges[-1][1]]
    )
    safe_slots = {
        record.entry_id: record
        for record in fixed_original_safe_slots(original_unit, entries)
    }
    conflicts: list[dict[str, Any]] = []
    for start, _, entry in ranges:
        entry_id = entry["entry_id"]
        safe_slot = safe_slots[entry_id]
        capacity_end = int(safe_slot.safe_end_unit_offset, 16)
        encoded_end = start + len(streams[entry_id])
        if encoded_end > capacity_end:
            conflicts.append(
                {
                    "entry_id": entry_id,
                    "original_unit_offset": f"0x{start:04X}",
                    "encoded_end_exclusive": f"0x{encoded_end:04X}",
                    "safe_end_exclusive": f"0x{capacity_end:04X}",
                    "encoded_bytes": len(streams[entry_id]),
                    "safe_bytes": capacity_end - start,
                    "overflow_bytes": encoded_end - capacity_end,
                    "overflow_glyph_tokens": (
                        encoded_end - capacity_end + 1
                    ) // 2,
                    "boundary_kind": safe_slot.boundary_kind,
                    "conflict_target": safe_slot.protected_target,
                }
            )

    # Earlier physical dialogue owns an overlap. This keeps the first
    # overflowing translation complete so runtime testing stops at the actual
    # next-entry damage instead of silently truncating the owner.
    for start, _, entry in reversed(ranges):
        stream = streams[entry["entry_id"]]
        absolute = unit_file_offset + start
        allbin[absolute : absolute + len(stream)] = stream

    pointer_verification_count = 0
    for _, _, entry in ranges:
        for reference in entry["source"]["pointer_references"]:
            storage = int(reference["storage_file_offset"], 16)
            expected = int(reference["raw_value"], 16)
            actual = struct.unpack_from("<I", allbin, storage)[0]
            if actual != expected:
                raise ValueError(
                    f"{entry['entry_id']}: fixed diagnostic changed pointer "
                    f"at 0x{storage:X}"
                )
            pointer_verification_count += 1

    intact_entries = []
    corrupted_entries = []
    for start, _, entry in ranges:
        entry_id = entry["entry_id"]
        stream = streams[entry_id]
        absolute = unit_file_offset + start
        actual = bytes(allbin[absolute : absolute + len(stream)])
        record = {
            "entry_id": entry_id,
            "unit_offset": f"0x{start:04X}",
            "encoded_bytes": len(stream),
        }
        if actual == stream:
            intact_entries.append(record)
        else:
            leading, _ = split_control_shell(entry)
            changed_token_indices = [
                token_index
                for token_index in range(len(stream) // 2)
                if actual[token_index * 2 : token_index * 2 + 2]
                != stream[token_index * 2 : token_index * 2 + 2]
            ]
            control_kind_by_index = {
                int(control["token_index"]): str(control["kind"])
                for control in entry["original"]["control_tokens"]
            }
            corrupted_leading_controls = [
                {
                    "token_index": token_index,
                    "kind": control_kind_by_index.get(
                        token_index,
                        "unknown-control",
                    ),
                    "expected": f"0x{struct.unpack_from('<H', stream, token_index * 2)[0]:04X}",
                    "actual": f"0x{struct.unpack_from('<H', actual, token_index * 2)[0]:04X}",
                }
                for token_index in changed_token_indices
                if token_index < len(leading)
            ]
            corrupted_entries.append(
                {
                    **record,
                    "changed_token_count": len(changed_token_indices),
                    "first_changed_token_index": (
                        min(changed_token_indices)
                        if changed_token_indices
                        else None
                    ),
                    "leading_control_token_count": len(leading),
                    "corrupted_leading_control_count": len(
                        corrupted_leading_controls
                    ),
                    "corrupted_leading_controls": (
                        corrupted_leading_controls
                    ),
                    "portrait_or_audio_control_corrupted": any(
                        control["kind"] in {"speaker_style", "audio"}
                        for control in corrupted_leading_controls
                    ),
                }
            )

    changed_gap_count = 0
    for (_, left_end, _), (right_start, _, _) in zip(ranges, ranges[1:]):
        original_gap = original_unit[left_end:right_start]
        output_gap = bytes(
            allbin[
                unit_file_offset + left_end :
                unit_file_offset + right_start
            ]
        )
        if output_gap != original_gap:
            changed_gap_count += 1

    region_start = ranges[0][0]
    write_end = max(
        start + len(streams[entry["entry_id"]])
        for start, _, entry in ranges
    )
    return {
        "unit_index": unit_index,
        "unit_file_offset": f"0x{unit_file_offset:X}",
        "entry_count": len(ranges),
        "placement_policy": "fixed-original-offset-diagnostic",
        "translation_input_field": "ko_candidate",
        "layout_adjustment_count": len(layout_adjustments),
        "layout_adjustments": layout_adjustments,
        "write_precedence": "lower-source-offset-wins-overlap",
        "pointer_write_count": 0,
        "pointer_identity_verification_count": pointer_verification_count,
        "original_region_start": f"0x{region_start:04X}",
        "original_region_end_exclusive": f"0x{ranges[-1][1]:04X}",
        "diagnostic_write_end_exclusive": f"0x{write_end:04X}",
        "encoded_text_bytes": sum(len(value) for value in streams.values()),
        "slot_overflow_count": len(conflicts),
        "slot_overflows": conflicts,
        "first_slot_overflow": conflicts[0] if conflicts else None,
        "intact_entry_count": len(intact_entries),
        "corrupted_by_overlap_entry_count": len(corrupted_entries),
        "corrupted_by_overlap_entries": corrupted_entries,
        "corrupted_portrait_or_audio_entry_count": sum(
            bool(entry["portrait_or_audio_control_corrupted"])
            for entry in corrupted_entries
        ),
        "changed_inter_entry_gap_count": changed_gap_count,
        "entries": intact_entries,
        "warning": (
            "Diagnostic only: complete translations stay at original starts; "
            "earlier overlong streams intentionally corrupt later content."
        ),
    }


def parse_units(values: list[str], all_story: bool) -> list[int]:
    units: set[int] = set(range(35)) if all_story else set()
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                units.add(int(part, 0))
    if not units:
        raise ValueError("select --unit or --all-story")
    if any(unit < 0 or unit > 34 for unit in units):
        raise ValueError(
            "dialogue builder supports story units 0..20 and runtime race "
            "units 21..34"
        )
    return sorted(units)


def validate_stable_id_join(
    work_entries: list[dict[str, Any]],
    derived_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    work_ids = [entry["entry_id"] for entry in work_entries]
    derived_ids = [entry["id"] for entry in derived_entries]
    if len(set(work_ids)) != len(work_ids):
        raise ValueError("workset contains duplicate stable IDs")
    if len(set(derived_ids)) != len(derived_ids):
        raise ValueError("reflow overlay contains duplicate stable IDs")
    missing = sorted(set(work_ids) - set(derived_ids))
    extra = sorted(set(derived_ids) - set(work_ids))
    if missing or extra:
        raise ValueError(
            f"reflow stable ID mismatch: missing={missing} extra={extra}"
        )
    if work_ids != derived_ids:
        mismatch_index = next(
            index
            for index, (work_id, derived_id) in enumerate(
                zip(work_ids, derived_ids)
            )
            if work_id != derived_id
        )
        raise ValueError(
            "reflow overlay changed protected workset order at "
            f"{mismatch_index}: {work_ids[mismatch_index]} != "
            f"{derived_ids[mismatch_index]}"
        )
    return {
        "entry_count": len(work_ids),
        "unique_entry_count": len(set(work_ids)),
        "stable_id_set_exact": True,
        "protected_workset_order_preserved": True,
    }


def integrated_font_extra_texts(
    character_names: dict[str, Any],
    ui_translation: dict[str, Any],
) -> list[str]:
    fixed = character_names.get("fixed_player_name")
    speaker_table = character_names.get("speaker_name_table")
    ui_items = ui_translation.get("translations")
    if (
        not isinstance(fixed, dict)
        or not isinstance(speaker_table, dict)
        or not isinstance(speaker_table.get("records"), list)
        or not isinstance(ui_items, list)
    ):
        raise ValueError("integrated name/UI font artifacts are incomplete")
    texts = [
        str(fixed.get("surname", "")),
        str(fixed.get("given_name", "")),
        *[
            str(record.get("ko", ""))
            for record in speaker_table["records"]
        ],
        *[
            str(item.get("ko", ""))
            for item in ui_items
            if item.get("renderer") == "primary"
        ],
    ]
    if any(not text for text in texts):
        raise ValueError("integrated name/UI font text is empty")
    return texts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-bin", type=Path, required=True)
    parser.add_argument("--allbin", type=Path, required=True)
    parser.add_argument(
        "--workset",
        type=Path,
        default=Path("work/translations/disc1-dialogue.json"),
    )
    parser.add_argument(
        "--reflow-overlay",
        type=Path,
        default=Path(
            "work/translations/disc1-dialogue-ko-reflowed-nonrelease.json"
        ),
    )
    parser.add_argument(
        "--reinsertion-audit",
        type=Path,
        default=Path(
            "work/analysis/disc1-translation-reinsertion-audit.json"
        ),
    )
    parser.add_argument(
        "--glyph-map",
        type=Path,
        default=Path("data/glyph-map.json"),
    )
    parser.add_argument(
        "--font-profile",
        type=Path,
        default=Path("config/font-profile.json"),
    )
    parser.add_argument(
        "--character-names",
        type=Path,
        default=Path("data/translations/disc1-character-names.json"),
        help="Korean fixed/speaker names whose primary glyphs must be mapped",
    )
    parser.add_argument(
        "--ui-translation",
        type=Path,
        default=Path("data/translations/disc1-ui-ko.json"),
        help="Korean primary-renderer UI whose glyphs must be mapped",
    )
    parser.add_argument(
        "--pointerless-workset",
        type=Path,
        default=Path(
            "work/translations/disc1-pointerless-pages-u00-u21.json"
        ),
    )
    parser.add_argument(
        "--pointerless-translation",
        type=Path,
        default=Path(
            "data/translations/disc1-pointerless-pages-u00-u21-ko.json"
        ),
    )
    parser.add_argument(
        "--unindexed-workset",
        type=Path,
        default=Path(
            "work/translations/disc1-unindexed-font-text.json"
        ),
    )
    parser.add_argument(
        "--unindexed-translation",
        type=Path,
        default=Path(
            "data/translations/disc1-unindexed-font-ko.json"
        ),
    )
    parser.add_argument(
        "--include-reviewed-unindexed-story",
        action="store_true",
        help=(
            "Promote and translate the reviewed u02..u19/u28/u30..u34 "
            "sequential and race streams; runtime route QA remains required"
        ),
    )
    parser.add_argument(
        "--unit",
        action="append",
        default=[],
        help="story unit number or comma-separated list; repeatable",
    )
    parser.add_argument(
        "--all-story",
        action="store_true",
        help="select every supported dialogue unit u00..u34",
    )
    parser.add_argument(
        "--placement-policy",
        choices=(
            "source-order-repack",
            "unit-shared-pool",
            "fixed-original-diagnostic",
        ),
        default="source-order-repack",
        help=(
            "Use unit-shared-pool for exhaustive unit-local relocation, or "
            "fixed-original-diagnostic only for intentional runtime overflow "
            "localization; the latter permits destructive entry overlap."
        ),
    )
    parser.add_argument(
        "--allow-unit-capacity-space-compaction",
        action="store_true",
        help=(
            "Non-release only: when a unit-local arena is short, remove the "
            "minimum number of spaces while preserving every non-space glyph "
            "and all control bytes"
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    try:
        units = parse_units(args.unit, args.all_story)
    except ValueError as error:
        parser.error(str(error))
    if any(unit >= 22 for unit in units) and (
        args.placement_policy != "unit-shared-pool"
    ):
        parser.error(
            "race units 22..34 require --placement-policy unit-shared-pool"
        )
    if 21 in units and args.placement_policy not in {
        "fixed-original-diagnostic",
        "unit-shared-pool",
    }:
        parser.error(
            "race unit 21 is allowed only with --placement-policy "
            "fixed-original-diagnostic or unit-shared-pool"
        )

    source_start = args.start_bin.read_bytes()
    source_allbin = args.allbin.read_bytes()
    if sha256_bytes(source_start) != EXPECTED_START_SHA256:
        raise ValueError("START.BIN hash differs from the verified original")
    if sha256_bytes(source_allbin) != EXPECTED_ALLBIN_SHA256:
        raise ValueError("ALLBIN.BIN hash differs from the verified original")

    workset = load_object(args.workset)
    overlay = load_object(args.reflow_overlay)
    audit = load_object(args.reinsertion_audit)
    character_names = load_object(args.character_names)
    ui_translation = load_object(args.ui_translation)
    pointerless_workset = load_object(args.pointerless_workset)
    pointerless_translation = load_object(args.pointerless_translation)
    pointerless_by_id, pointerless_translation_by_id = (
        validate_pointerless_artifacts(
            pointerless_workset,
            pointerless_translation,
        )
    )
    additional_entries: list[dict[str, Any]] = []
    additional_translation_by_id: dict[str, dict[str, Any]] = {}
    additional_validation: dict[str, Any] | None = None
    if args.include_reviewed_unindexed_story:
        unindexed_workset = load_object(args.unindexed_workset)
        unindexed_translation = load_object(args.unindexed_translation)
        (
            all_additional_entries,
            all_additional_translation_by_id,
            additional_validation,
        ) = validate_unindexed_artifacts(
            unindexed_workset,
            unindexed_translation,
            workset_path=args.unindexed_workset,
            source_allbin=source_allbin,
            expected_allbin_sha256=EXPECTED_ALLBIN_SHA256,
        )
        additional_entries = [
            entry
            for entry in all_additional_entries
            if entry["classification"]
            in {"sequential_event_page", "indexed_race_page"}
        ]
        additional_translation_by_id = {
            entry["entry_id"]: all_additional_translation_by_id[
                entry["entry_id"]
            ]
            for entry in additional_entries
        }
    work_entries = workset.get("entries")
    derived_entries = overlay.get("entries")
    if not isinstance(work_entries, list) or not isinstance(derived_entries, list):
        raise ValueError("workset and reflow overlay entries must be arrays")
    stable_id_join = validate_stable_id_join(work_entries, derived_entries)
    reflow_by_id = {entry["id"]: entry for entry in derived_entries}

    mismatch_ids = {
        entry["id"]
        for entry in audit["protected_structure"]["name_token_mismatches"]
    }
    selected_ids = {
        entry["entry_id"]
        for entry in work_entries
        if int(entry["source"]["unit_index"]) in units
    }
    selected_mismatches = sorted(selected_ids & mismatch_ids)
    if selected_mismatches:
        raise ValueError(
            "selected units contain protected name-token mismatches: "
            + ", ".join(selected_mismatches)
        )

    by_unit: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for entry in work_entries:
        unit_index = int(entry["source"]["unit_index"])
        if unit_index in units:
            by_unit[unit_index].append(entry)
    pointerless_by_unit: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for entry in pointerless_by_id.values():
        unit_index = int(entry["source"]["unit_index"])
        if unit_index in units:
            pointerless_by_unit[unit_index].append(entry)
    additional_by_unit: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for source_entry in additional_entries:
        unit_index = int(source_entry["source"]["unit_index"])
        if unit_index not in units:
            continue
        unit_load_addresses = {
            int(entry["source"]["runtime_pointer"], 16)
            - int(entry["source"]["unit_offset"], 16)
            for entry in by_unit[unit_index]
        }
        if len(unit_load_addresses) != 1:
            raise ValueError(
                f"unit {unit_index}: cannot derive additional runtime base"
            )
        entry = copy.deepcopy(source_entry)
        unit_offset = int(entry["source"]["unit_offset"], 16)
        runtime_pointer = unit_load_addresses.pop() + unit_offset
        entry["source"]["runtime_pointer"] = f"0x{runtime_pointer:08X}"
        entry["source"]["reference_unit_offsets"] = []
        additional_by_unit[unit_index].append(entry)
    selected_pointerless_translations = [
        pointerless_translation_by_id[entry["entry_id"]]
        for unit_index in units
        for entry in pointerless_by_unit[unit_index]
    ]
    selected_additional_translations = [
        additional_translation_by_id[entry["entry_id"]]
        for unit_index in units
        for entry in additional_by_unit[unit_index]
    ]
    gap_glyph_indices = (
        frozenset()
        if args.placement_policy == "unit-shared-pool"
        else passthrough_gap_glyph_indices(source_allbin, by_unit)
    )
    patched_start, mapping, font_report = build_static_font(
        source_start,
        overlay,
        glyph_map_path=args.glyph_map,
        font_profile_path=args.font_profile,
        passthrough_original_glyph_indices=gap_glyph_indices,
        entry_ids=selected_ids,
        extra_texts=[
            *integrated_font_extra_texts(character_names, ui_translation),
            *pointerless_translation_texts(
                selected_pointerless_translations
            ),
            *unindexed_translation_texts(
                selected_additional_translations
            ),
        ],
    )
    patched_allbin = bytearray(source_allbin)
    if args.placement_policy == "unit-shared-pool":
        unit_reports = [
            relink_unit_shared_pool(
                patched_allbin,
                by_unit[unit_index],
                reflow_by_id,
                mapping,
                pointerless_entries=pointerless_by_unit[unit_index],
                pointerless_translation_by_id=pointerless_translation_by_id,
                additional_entries=additional_by_unit[unit_index],
                additional_translation_by_id=(
                    additional_translation_by_id
                ),
                allow_unit_capacity_space_compaction=(
                    args.allow_unit_capacity_space_compaction
                ),
            )
            for unit_index in units
        ]
    else:
        unit_writer = {
            "fixed-original-diagnostic": (
                write_unit_at_original_offsets_diagnostic
            ),
            "source-order-repack": repack_unit,
        }[args.placement_policy]
        unit_reports = [
            unit_writer(
                patched_allbin,
                by_unit[unit_index],
                reflow_by_id,
                mapping,
            )
            for unit_index in units
        ]
    start_expected_writes = verify_expected_writes(
        source_start,
        patched_start,
        allowed_ranges=[
            (
                FONT_OFFSET,
                FONT_OFFSET + FONT_GLYPH_COUNT * GLYPH_SIZE,
            )
        ],
        owner="primary-static-font",
    )
    allbin_allowed_ranges: list[tuple[int, int]] = []
    for unit_index in units:
        unit_entries = by_unit[unit_index]
        unit_file_offset = min(
            int(entry["source"]["file_offset"], 16)
            - int(entry["source"]["unit_offset"], 16)
            for entry in unit_entries
        )
        entry_ranges = physical_entry_ranges(unit_entries)
        report = next(
            report
            for report in unit_reports
            if int(report["unit_index"]) == unit_index
        )
        region_end = (
            int(report["diagnostic_write_end_exclusive"], 16)
            if args.placement_policy == "fixed-original-diagnostic"
            else (
                int(report["physical_region_end_exclusive"], 16)
                if args.placement_policy == "unit-shared-pool"
                else entry_ranges[-1][1]
            )
        )
        allbin_allowed_ranges.append(
            (
                unit_file_offset
                + (
                    int(report["physical_region_start"], 16)
                    if args.placement_policy == "unit-shared-pool"
                    else entry_ranges[0][0]
                ),
                unit_file_offset + region_end,
            )
        )
        if args.placement_policy in {
            "source-order-repack",
            "unit-shared-pool",
        }:
            if args.placement_policy == "unit-shared-pool":
                allbin_allowed_ranges.extend(
                    (
                        unit_file_offset
                        + int(reference["storage_unit_offset"], 16),
                        unit_file_offset
                        + int(reference["storage_unit_offset"], 16)
                        + 4,
                    )
                    for reference in report["references"]
                )
                for reference in report["split_immediate_references"]:
                    for field in (
                        "lui_storage_unit_offset",
                        "addiu_storage_unit_offset",
                    ):
                        storage = unit_file_offset + int(
                            reference[field], 16
                        )
                        allbin_allowed_ranges.append(
                            (storage, storage + 4)
                        )
                continue
            allbin_allowed_ranges.extend(
                (
                    int(reference["storage_file_offset"], 16),
                    int(reference["storage_file_offset"], 16) + 4,
                )
                for entry in unit_entries
                for reference in entry["source"]["pointer_references"]
            )
    allbin_expected_writes = verify_expected_writes(
        source_allbin,
        bytes(patched_allbin),
        allowed_ranges=allbin_allowed_ranges,
        owner=(
            "fixed-original-offset-diagnostic-text"
            if args.placement_policy == "fixed-original-diagnostic"
            else "selected-story-unit-text-and-pointers"
        ),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    start_output = args.output_dir / "START.BIN"
    allbin_output = args.output_dir / "ALLBIN.BIN"
    map_output = args.output_dir / "primary-korean-glyph-map.json"
    manifest_output = args.output_dir / "manifest.json"
    start_output.write_bytes(patched_start)
    allbin_output.write_bytes(patched_allbin)
    write_json(
        map_output,
        {
            "schema_version": 1,
            "status": "nonrelease-selected-corpus-static-map",
            "mapping": {
                character: f"0x{index:03X}"
                for character, index in sorted(
                    mapping.items(), key=lambda item: item[1]
                )
            },
        },
    )
    manifest = {
        "schema_version": 1,
        "status": (
            "nonrelease-fixed-original-offset-overflow-diagnostic"
            if args.placement_policy == "fixed-original-diagnostic"
            else "nonrelease-partial-chapter-build"
        ),
        "placement_policy": args.placement_policy,
        "selected_story_units": units,
        "selected_entry_count": (
            len(selected_ids)
            + (
                len(selected_pointerless_translations)
                if args.placement_policy == "unit-shared-pool"
                else 0
            )
            + (
                len(selected_additional_translations)
                if args.placement_policy == "unit-shared-pool"
                else 0
            )
        ),
        "selected_direct_entry_count": len(selected_ids),
        "selected_pointerless_entry_count": (
            len(selected_pointerless_translations)
            if args.placement_policy == "unit-shared-pool"
            else 0
        ),
        "selected_additional_entry_count": (
            len(selected_additional_translations)
            if args.placement_policy == "unit-shared-pool"
            else 0
        ),
        "additional_translation_validation": additional_validation,
        "translation_status": "incomplete-user-editing-in-progress",
        "release_eligible": False,
        "unit_capacity_space_compaction": {
            "enabled": args.allow_unit_capacity_space_compaction,
            "applied_unit_count": sum(
                unit.get("unit_capacity_space_compaction", {}).get("status")
                == "applied-nonrelease"
                for unit in unit_reports
            ),
            "removed_space_count": sum(
                int(
                    unit.get(
                        "unit_capacity_space_compaction",
                        {},
                    ).get("removed_space_count", 0)
                )
                for unit in unit_reports
            ),
            "non_space_content_preserved": all(
                unit.get(
                    "unit_capacity_space_compaction",
                    {},
                ).get("non_space_content_preserved", True)
                for unit in unit_reports
            ),
        },
        "font_scope": (
            "selected-direct-pointerless-and-reviewed-additional-dialogue-"
            "plus-integrated-names-ui"
            if args.include_reviewed_unindexed_story
            else
            "selected-direct-and-pointerless-dialogue-plus-integrated-names-ui"
        ),
        "unselected_dialogue_font_compatible": False,
        "warning": (
            "Diagnostic only: translated streams stay at original starts and "
            "overlong earlier entries intentionally overwrite later content. "
            "Expect the first slot conflict to break subsequent dialogue."
            if args.placement_policy == "fixed-original-diagnostic"
            else (
                "Unit-local pool: every frozen event/table reference is "
                "relinked and each physical arena keeps its original byte "
                "capacity. Frozen references are statically verified for "
                "every selected unit. "
                + (
                    "Some units use explicitly recorded space-only "
                    "compaction; no non-space content or control shell was "
                    "removed. "
                    if args.allow_unit_capacity_space_compaction
                    else ""
                )
                + (
                    "Pointerless pages and any selected reviewed additional "
                    "streams are promoted and translated, so this exact "
                    "combined Track 1 requires a new runtime replay."
                )
                if args.placement_policy == "unit-shared-pool"
                else
                "Only selected units are encoded with the replaced global "
                "font. Do not test unselected dialogue in this partial build."
            )
        ),
        "sources": {
            "START.BIN": {
                "path": str(args.start_bin.resolve()),
                "sha256": sha256_bytes(source_start),
            },
            "ALLBIN.BIN": {
                "path": str(args.allbin.resolve()),
                "sha256": sha256_bytes(source_allbin),
            },
            "workset_sha256": sha256_file(args.workset),
            "reflow_overlay_sha256": sha256_file(args.reflow_overlay),
            "reinsertion_audit_sha256": sha256_file(args.reinsertion_audit),
            "character_names_sha256": sha256_file(args.character_names),
            "ui_translation_sha256": sha256_file(args.ui_translation),
            "pointerless_workset_sha256": sha256_file(
                args.pointerless_workset
            ),
            "pointerless_translation_sha256": sha256_file(
                args.pointerless_translation
            ),
            **(
                {
                    "unindexed_workset_sha256": sha256_file(
                        args.unindexed_workset
                    ),
                    "unindexed_translation_sha256": sha256_file(
                        args.unindexed_translation
                    ),
                }
                if args.include_reviewed_unindexed_story
                else {}
            ),
        },
        "font": font_report,
        "stable_id_join": stable_id_join,
        "units": unit_reports,
        "expected_writes": {
            "START.BIN": start_expected_writes,
            "ALLBIN.BIN": allbin_expected_writes,
        },
        "outputs": {
            "START.BIN": {
                "path": str(start_output.resolve()),
                "size": len(patched_start),
                "sha256": sha256_bytes(patched_start),
            },
            "ALLBIN.BIN": {
                "path": str(allbin_output.resolve()),
                "size": len(patched_allbin),
                "sha256": sha256_bytes(patched_allbin),
            },
            "glyph_map": {
                "path": str(map_output.resolve()),
                "sha256": sha256_file(map_output),
            },
        },
    }
    write_json(manifest_output, manifest)
    print(
        f"units={','.join(str(unit) for unit in units)} "
        f"placement={args.placement_policy} "
        f"entries={manifest['selected_entry_count']} glyphs={len(mapping)} "
        f"START={manifest['outputs']['START.BIN']['sha256']} "
        f"ALLBIN={manifest['outputs']['ALLBIN.BIN']['sha256']}"
    )


if __name__ == "__main__":
    main()
