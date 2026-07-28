#!/usr/bin/env python3
"""Export a compact AI handoff for special-screen dialogue translation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


JP_PATTERN = re.compile(r"[ぁ-んァ-ン一-龯]")
PLACEHOLDER_DISPLAY = {
    "{name:surname}": "시바",
    "{name:given}": "세이치로",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def visible_length(text: str) -> int:
    for token, replacement in PLACEHOLDER_DISPLAY.items():
        text = text.replace(token, replacement)
    return len(text)


def draft_issues(entry: dict[str, Any], text: str) -> list[str]:
    lines = text.split("\n")
    fixed_control_words = sum(
        control["kind"] != "align"
        for control in entry["original"]["control_tokens"]
    )
    max_positions = (
        int(entry["source"]["byte_size"]) // 2 - fixed_control_words
    )
    issues: list[str] = []
    if len(lines) > int(entry["layout"]["rows"]):
        issues.append("row_limit")
    if any(visible_length(line) > 17 for line in lines):
        issues.append("column_limit")
    positions = (
        sum(visible_length(line) for line in lines) + len(lines) - 1
    )
    if positions > max_positions:
        issues.append("slot_limit")
    if JP_PATTERN.search(text):
        issues.append("japanese_residue")
    return issues


def build_brief(
    *,
    workset: dict[str, Any],
    translation: dict[str, Any],
    workset_path: Path,
    translation_path: Path,
) -> dict[str, Any]:
    if workset.get("baseline_id") != translation.get("baseline_id"):
        raise ValueError("workset and draft translation baselines differ")
    entries = workset.get("entries")
    translations = translation.get("translations")
    if not isinstance(entries, list) or not isinstance(translations, list):
        raise ValueError("workset and draft translation require entry arrays")
    draft_by_id: dict[str, str] = {}
    for item in translations:
        entry_id = item.get("id")
        ko = item.get("ko")
        if (
            not isinstance(entry_id, str)
            or not isinstance(ko, str)
            or entry_id in draft_by_id
        ):
            raise ValueError(f"invalid draft item: {entry_id!r}")
        draft_by_id[entry_id] = ko
    source_ids = [entry["entry_id"] for entry in entries]
    if set(source_ids) != set(draft_by_id):
        raise ValueError("workset and draft translation IDs differ")

    brief_entries: list[dict[str, Any]] = []
    issue_count = 0
    for entry in entries:
        entry_id = entry["entry_id"]
        ko = draft_by_id[entry_id]
        fixed_control_words = sum(
            control["kind"] != "align"
            for control in entry["original"]["control_tokens"]
        )
        max_positions = (
            int(entry["source"]["byte_size"]) // 2 - fixed_control_words
        )
        issues = draft_issues(entry, ko)
        issue_count += bool(issues)
        brief_entries.append(
            {
                "id": entry_id,
                "category": entry["classification"],
                "max_rows": int(entry["layout"]["rows"]),
                "max_columns": 17,
                "max_encoded_positions": max_positions,
                "jp": entry["original"]["display_text"],
                "ko": ko,
                "draft_issues": issues,
            }
        )
    return {
        "schema_version": 1,
        "status": "external-ai-translation-review-required",
        "baseline_id": workset["baseline_id"],
        "instructions": [
            "각 entries 항목의 id, category, max_* 필드는 절대 변경하지 않는다.",
            "jp를 기준으로 ko의 오역·누락·미완성 문장·일본어 잔존을 교정한다.",
            "ko의 줄 수는 max_rows 이하, 각 줄은 max_columns(17)자 이하로 쓴다.",
            "ko의 표시 글리프 수와 줄바꿈 수의 합은 max_encoded_positions 이하로 쓴다.",
            "줄바꿈은 단어를 쪼개지 말고 어절 경계에서 한다.",
            "{name:surname}, {name:given} 플레이스홀더는 원문에 있으면 그대로 보존한다.",
            "◯, ♥, 💢, 💦, 💧, ♪, ZERO 같은 의미 있는 기호·표기는 보존한다.",
            "draft_issues는 참고 진단이며 결과 파일에 그대로 남겨도 된다.",
            "전체 JSON 구조를 유지한 채 ko만 교정해 반환한다.",
        ],
        "fixed_terms": {
            "スゴウ": "스고",
            "アスラーダ": "아스라다",
            "ネメシス": "네메시스",
            "ブラックジャック": "블랙잭",
            "グリップ力": "접지력",
            "タイヤ": "타이어",
            "ウイング": "윙",
            "ブースト": "부스트",
            "コース": "코스",
            "マシン": "머신",
            "サーキット": "서킷",
            "ピット": "피트",
            "カード": "카드",
            "バースト": "버스트",
            "ドローゲーム": "무승부",
            "キャンギャル": "레이싱 모델",
        },
        "source": {
            "workset": str(workset_path.resolve()),
            "workset_sha256": sha256_bytes(workset_path.read_bytes()),
            "draft_translation": str(translation_path.resolve()),
            "draft_translation_sha256": sha256_bytes(
                translation_path.read_bytes()
            ),
        },
        "summary": {
            "entry_count": len(brief_entries),
            "draft_issue_entry_count": issue_count,
            "batch_recommendation": 200,
            "scope": [
                "u38 미니게임 폰트 대사",
                "u43 코스 설명 폰트 대사",
                "u43 머신 셋팅 폰트 대사",
            ],
            "excluded": [
                "그래픽 버튼",
                "그래픽 타이틀·라벨 에셋",
            ],
        },
        "entries": brief_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workset",
        type=Path,
        default=Path(
            "work/translations/disc1-special-screen-text.json"
        ),
    )
    parser.add_argument(
        "--draft",
        type=Path,
        default=Path(
            "data/translations/disc1-special-screen-ko.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "work/translations/"
            "disc1-special-screen-translation-brief.json"
        ),
    )
    parser.add_argument(
        "--batch-output-dir",
        type=Path,
        default=Path(
            "work/translations/"
            "disc1-special-screen-translation-batches"
        ),
    )
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    workset = load_object(args.workset)
    translation = load_object(args.draft)
    brief = build_brief(
        workset=workset,
        translation=translation,
        workset_path=args.workset,
        translation_path=args.draft,
    )
    write_json(args.output, brief)

    entries = brief["entries"]
    batch_paths: list[str] = []
    for batch_index, start in enumerate(
        range(0, len(entries), args.batch_size),
        start=1,
    ):
        batch = {
            **brief,
            "status": "external-ai-translation-review-batch",
            "batch": {
                "index": batch_index,
                "start_entry_index": start,
                "end_entry_index_exclusive": min(
                    start + args.batch_size,
                    len(entries),
                ),
                "entry_count": len(entries[start : start + args.batch_size]),
                "total_entry_count": len(entries),
            },
            "entries": entries[start : start + args.batch_size],
        }
        batch_path = (
            args.batch_output_dir
            / f"disc1-special-screen-batch-{batch_index:03d}.json"
        )
        write_json(batch_path, batch)
        batch_paths.append(str(batch_path))
    manifest = {
        "schema_version": 1,
        "status": "external-ai-translation-review-batches",
        "full_file": str(args.output),
        "full_file_sha256": sha256_bytes(args.output.read_bytes()),
        "batch_size": args.batch_size,
        "batch_count": len(batch_paths),
        "batch_files": batch_paths,
    }
    write_json(args.batch_output_dir / "manifest.json", manifest)
    print(
        f"entries={brief['summary']['entry_count']} "
        f"draft_issues={brief['summary']['draft_issue_entry_count']} "
        f"batches={len(batch_paths)} output={args.output}"
    )


if __name__ == "__main__":
    main()
