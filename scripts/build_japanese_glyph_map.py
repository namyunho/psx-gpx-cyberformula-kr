#!/usr/bin/env python3
"""Build the complete, table-scoped Japanese glyph map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PRIMARY_GLYPH_COUNT = 0x04CD
ALTERNATE_GLYPH_COUNT = 0x05CC

HIRAGANA_OMISSIONS = frozenset("ぢゎゐゑ")
KATAKANA_OMISSIONS = frozenset("ヂヮヰヱヲヵ")

# Each bit selects one character from JIS X 0208 Level 1 in ku-ten order.
# The selected characters are assigned consecutively to the game's standard
# kanji range. These selections are the compact, reviewable invariant produced
# by OCR of the user-recolored atlases plus manual shape/JIS-order correction.
PRIMARY_JIS_LEVEL1_SELECTION = (
    "064C03004C7608BA2998036190008028130000802A08805AC2184BEB731020C9410EB84DC85000001568520440000001"
    "7506820EC4858011CFE937497EDA8244232A9B90FA1818D0A5A2883D80160DA104D80008A868A000E0B319F99B348473"
    "AE69464C02070E1C0ACC226092A02020400D084E80DF31401C80E08829B0006460334459080673F0E0E74921B3816B83"
    "71D0129CC02FD8CA0C43600431208E30048F8A2C484060A40270402502DB348840A317A6C15A040126CCA4083BCDCDD7"
    "0827AE5671D200060916C0040800019605003CEB4FD63AF0215B7030F405206B10A60C4C9FA1A08BA200500AA114C400"
    "B200003052A19025402F16090D87E801C11330395F021318A00024005AA14581CC17256896580C0490B80414901E1100"
    "04019580738400404520810068232200485C2502781C4D0C4A8D202697B00800DB440E0004F0C0050738867817511222"
    "30B2246C2838A8B83C5022280B2D170424D8681A480960204B08219094380218C8C208"
)

ALTERNATE_JIS_LEVEL1_SELECTION = (
    "946B421C68B0200884F9084E1AC641861B03C8AC013B90FA4BF09B47D5F044042598B025CBC00C6104605B281872E838"
    "51F0109882A53A1205380AC57AE00214D01970124C00F059A2C4B8239A610D80788621D7D81E2E38610039791A585538"
    "4F304849820FEE445B9C2F7E1E55C6E1C823D8DA305283511200B5903AA7EEC00A00225820121F77613386043DE9270E"
    "105668659223EE6286E75004E5A304BF0F8F68280C28F187E190E00004F3642A128306E6F91788CC322054AA9B57DDE6"
    "1C81874423D61F24631E40100C151982C13E812528C00D3000120850E3F3400CC8605C0799D81B29E400100C7426E40A"
    "999965C2EE1E80818C6F07707C474F9C6972A2515C73085097381DE963854D23C2C6494C83C0802D7CB1497442BE9022"
    "24440C94192D0A43462841B16BCA880E7B18A100192C4B04CA84C609D9F4E330858064B8247A58AD1D3DAABF5700D634"
    "5006E75302F930E98810107DC1659534F168C9E3C24A3A41185AE0B1B4309298102C00"
)

PRIMARY_SYMBOLS = {
    0x0000: "　",
    0x0001: "、",
    0x0002: "。",
    0x0003: "，",
    0x0004: "・",
    0x0005: "？",
    0x0006: "！",
    0x0007: "々",
    0x0008: "○",
    0x0009: "ー",
    0x000A: "〜",
    0x000B: "…",
    0x000C: "（",
    0x000D: "）",
    0x000E: "「",
    0x000F: "」",
    0x0010: "『",
    0x0011: "』",
    0x0012: "−",
    0x0013: "ⓧ",
    0x0014: "＝",
    0x0015: "％",
    0x0016: "💢",
    0x0017: "💦",
    0x0018: "◯",
    0x0019: "💧",
    0x001A: "●",
    0x001B: "△",
    0x001C: "※",
    0x001D: "♪",
}

ALTERNATE_SYMBOLS = {
    **{index: PRIMARY_SYMBOLS[index] for index in range(0x0013)},
    0x0013: "＝",
    0x0014: "％",
    0x0015: "💢",
    0x0016: "💦",
    0x0017: "💧",
    0x0018: "※",
    0x0019: "♪",
}

PRIMARY_CUSTOM_TAIL = "醤酒璧瞑綺萬貪贅"
ALTERNATE_CUSTOM_TAIL = (
    "弌丼弍儚凉凰刹卍凖雙吼哭國廣弑弩彌彗惠愼鴎戌"
    "昴朧栞條棍棕渕滉澁潦澤黎濱炬烝煌燎曝眞祠祓禮"
    "筐篁絽椅繚翔翻茉莢莉號邊酥雉霍瓢槇遙ゔぢヂヲ"
)

# Context and direct slot review of the user-recolored
# primary-glyphs-only_modify.png corrected four primary OCR readings.
# 0x00E4 repurposes the structural ヶ slot as Greek nu in νアスラーダ.
# The remaining three slots stay in strictly increasing JIS Level 1 order.
PRIMARY_CONTEXT_CORRECTIONS = {
    0x00E4: "ν",
    0x01AA: "驚",
    0x0310: "薦",
    0x03EE: "発",
}


def decode_sjis_trail_range(
    lead: int,
    trails: range | list[int],
) -> str:
    return "".join(bytes((lead, trail)).decode("cp932") for trail in trails)


def kana_sequences() -> tuple[str, str]:
    hiragana = "".join(
        character
        for character in decode_sjis_trail_range(0x82, range(0x9F, 0xF2))
        if character not in HIRAGANA_OMISSIONS
    )
    katakana_trails = list(range(0x40, 0x7F)) + list(range(0x80, 0x97))
    katakana = "".join(
        character
        for character in decode_sjis_trail_range(0x83, katakana_trails)
        if character not in KATAKANA_OMISSIONS
    )
    if len(hiragana) != 79 or len(katakana) != 80:
        raise ValueError("unexpected CP932 kana population")
    return hiragana, katakana


def jis_level1_characters() -> str:
    characters: list[str] = []
    for ku in range(16, 48):
        for ten in range(1, 95):
            try:
                character = bytes((ku + 0xA0, ten + 0xA0)).decode("euc_jp")
            except UnicodeDecodeError:
                continue
            characters.append(character)
    result = "".join(characters)
    if len(result) != 2965 or result[:2] != "亜唖" or result[-2:] != "碗腕":
        raise ValueError("unexpected JIS X 0208 Level 1 population")
    return result


def selected_jis_characters(selection_hex: str, expected_count: int) -> str:
    selection = bytes.fromhex(selection_hex)
    jis = jis_level1_characters()
    if len(selection) * 8 < len(jis):
        raise ValueError("JIS selection bitset is too short")
    result = "".join(
        character
        for index, character in enumerate(jis)
        if selection[index // 8] & (1 << (7 - index % 8))
    )
    if len(result) != expected_count:
        raise ValueError(
            f"JIS selection count differs: {len(result)} != {expected_count}"
        )
    return result


def structural_glyphs(table_id: str = "primary") -> dict[int, str]:
    hiragana, katakana = kana_sequences()
    if table_id == "primary":
        symbols = PRIMARY_SYMBOLS
        digit_start = 0x001E
        uppercase_start = 0x0028
        lowercase_start = 0x0042
        hiragana_start = 0x0046
        katakana_start = 0x0095
        heart_index = 0x00E5
    elif table_id == "alternate":
        symbols = ALTERNATE_SYMBOLS
        digit_start = 0x001A
        uppercase_start = 0x0024
        lowercase_start = 0x003E
        hiragana_start = 0x0042
        katakana_start = 0x0091
        heart_index = 0x00E1
    else:
        raise ValueError(f"unknown font table: {table_id}")

    glyphs = {
        **symbols,
        **{
            digit_start + index: character
            for index, character in enumerate("0123456789")
        },
        **{
            uppercase_start + index: character
            for index, character in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        },
        **{
            lowercase_start + index: character
            for index, character in enumerate("impz")
        },
        **{
            hiragana_start + index: character
            for index, character in enumerate(hiragana)
        },
        **{
            katakana_start + index: character
            for index, character in enumerate(katakana)
        },
        heart_index: "♥",
    }
    if table_id == "primary":
        glyphs.update(
            {
                index: character
                for index, character in PRIMARY_CONTEXT_CORRECTIONS.items()
                if index < 0x00E6
            }
        )
    return glyphs


def complete_table_glyphs(table_id: str) -> dict[int, str]:
    glyphs = structural_glyphs(table_id)
    if table_id == "primary":
        standard_start = 0x00E6
        standard = selected_jis_characters(
            PRIMARY_JIS_LEVEL1_SELECTION,
            0x04C5 - standard_start,
        )
        custom_start = 0x04C5
        custom = PRIMARY_CUSTOM_TAIL
        expected_count = PRIMARY_GLYPH_COUNT
    elif table_id == "alternate":
        standard_start = 0x00E2
        standard = selected_jis_characters(
            ALTERNATE_JIS_LEVEL1_SELECTION,
            0x058A - standard_start,
        )
        custom_start = 0x058A
        custom = ALTERNATE_CUSTOM_TAIL
        expected_count = ALTERNATE_GLYPH_COUNT
    else:
        raise ValueError(f"unknown font table: {table_id}")

    glyphs.update(
        {
            standard_start + index: character
            for index, character in enumerate(standard)
        }
    )
    glyphs.update(
        {
            custom_start + index: character
            for index, character in enumerate(custom)
        }
    )
    if table_id == "primary":
        glyphs.update(PRIMARY_CONTEXT_CORRECTIONS)
    if set(glyphs) != set(range(expected_count)):
        missing = sorted(set(range(expected_count)) - set(glyphs))
        raise ValueError(
            f"{table_id} map is not complete; missing "
            + ", ".join(f"{index:04X}" for index in missing)
        )
    return glyphs


def table_document(
    table_id: str,
    *,
    scope: str,
    standard_range: str,
    custom_range: str,
) -> dict[str, object]:
    glyphs = complete_table_glyphs(table_id)
    return {
        "scope": scope,
        "glyph_count": len(glyphs),
        "coverage": "complete",
        "ranges": {
            "structural_symbols_alnum_kana": (
                "0000..00E5" if table_id == "primary" else "0000..00E1"
            ),
            "jis_x_0208_level1_ordered_subset": standard_range,
            "game_custom_tail": custom_range,
        },
        "glyphs": {
            f"{index:04X}": character
            for index, character in sorted(glyphs.items())
        },
    }


def build_document() -> dict[str, object]:
    return {
        "schema_version": 3,
        "encoding": "custom-u16le-glyph-index",
        "status": "complete-user-recolored-atlas-ocr-cross-checked",
        "evidence": {
            "primary_modified_atlas": {
                "path": (
                    "work/analysis/font-ocr-atlas/"
                    "primary-glyphs-only_modify.png"
                ),
                "sha256": (
                    "632843c693046c8648d830b8038e1ff922dab26e456a21c6a9"
                    "ad2f42488eb526"
                ),
            },
            "alternate_modified_atlas": {
                "path": (
                    "work/analysis/font-ocr-atlas/"
                    "alternate-glyphs-only_modify.png"
                ),
                "sha256": (
                    "1eec8fcc1bc48911d7b3ba69b1d3b0aa357789b23278ceee9"
                    "235f438ec5170a2"
                ),
            },
            "method": [
                "User color-normalized each atlas against in-game rendering.",
                "Apple Vision Japanese OCR supplied the primary transcription.",
                (
                    "Standard kanji were constrained to strictly increasing "
                    "JIS X 0208 Level 1 order."
                ),
                (
                    "OCR outliers were corrected by neighboring JIS bounds, "
                    "glyph-shape inspection, and dialogue context."
                ),
                (
                    "Direct slot review of the user-recolored "
                    "primary-glyphs-only_modify.png corrected primary 00E4 "
                    "to semantic ν, 01AA to 驚, 0310 to 薦, and 03EE to 発; "
                    "dialogue context independently confirms the readings."
                ),
                (
                    "Primary and alternate tables remain separate because their "
                    "symbol and repertoire layouts differ."
                ),
            ],
            "nontext_symbol_policy": (
                "Controller and manga-style emotion glyphs use visible Unicode "
                "approximations; their original u16 token remains authoritative."
            ),
        },
        "tables": {
            "primary": table_document(
                "primary",
                scope="dialogue",
                standard_range="00E6..04C4",
                custom_range="04C5..04CC",
            ),
            "alternate": table_document(
                "alternate",
                scope="font-rendered-ui",
                standard_range="00E2..0589",
                custom_range="058A..05CB",
            ),
        },
        "controls": {
            "8000": "<PAGE_WAIT>",
            "903F": "<CTRL_903F>",
            "FFFB": "<LINE_END>",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/glyph-map.json"),
    )
    args = parser.parse_args()
    document = build_document()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    counts = {
        table_id: table["glyph_count"]
        for table_id, table in document["tables"].items()
    }
    print(f"output={args.output} tables={counts} status={document['status']}")


if __name__ == "__main__":
    main()
