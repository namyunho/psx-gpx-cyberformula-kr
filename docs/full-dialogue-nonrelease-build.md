# `u00..u34` 전체 대사 비배포 빌드

## 판정

2026-07-28 생성한 개발용 Disc 1 이미지는 다음 범위를 한 Track 1에 넣는다.

- 직접 포인터 대상 대사 5,783개
- `u00..u21` 무포인터 선택·대사 83개
- 고정 주인공명 `시바 세이치로`와 화자명 34개
- 이름 등록 화면의 고정 폰트 UI 4개
- 위 문자열에 필요한 primary/alternate Galmuri11 글리프

미니게임·코스·머신 설정 391개는 이 빌드 뒤에 추출·번역했으므로 포함하지
않는다. 번역문도 의미·용어·줄바꿈 검토 중이므로 상태는
`nonrelease-partial-translation`이며 배포 적격이 아니다.

## 입력과 정적 결과

| 항목 | 값 |
|---|---|
| story unit | `u00..u34`, 35개 |
| 직접+무포인터 엔트리 | 5,866개 |
| placement | `unit-shared-pool` |
| unit arena | unit별 원본 byte capacity 유지 |
| 공백 축소 | 8 unit, 공백 266개 |
| 비공백·제어 셸 손실 | 0 |
| primary 필요 문자 | 998자 |
| Galmuri11 생성 | 958자 |
| 원본 글리프 보존 | 40자 |
| 고정 보호 슬롯 | 72개 |
| 남는 primary 슬롯 | 199개 |

공백 축소는 `--allow-unit-capacity-space-compaction`을 명시한 비배포
예외다. `u27..u34`의 원문 후보가 unit 총량을 각각 12~150바이트 넘기므로
비공백 글리프와 모든 제어 셸을 보존한 채 필요한 수만큼의 공백만 제거했다.
이 결과는 게임 진행 가능성을 확인하기 위한 개발 입력이며 자연스러운
띄어쓰기 승인본이 아니다.

각 unit의 모든 직접 포인터, 이벤트 operand와 무포인터 앵커를 고정 참조
카탈로그로 검증한다. 대사와 기타 제어의 논리 순서는 유지하고 남는 용량은
참조되지 않는 arena 후미에만 `0x0000`으로 둔다. 한 unit의 공간을 다른
unit으로 넘기지 않으며 각 페이지의 17×3 제한도 유지한다.

## 파일·디스크 결과

| 파일 | SHA-256 |
|---|---|
| `START.BIN` | `be029199ba5c6781198ae4d2dd6ae0343729fb65f0d6123e2e07ce0269c46fc3` |
| `ALLBIN.BIN` | `ce42bd98ef9518ffefc819bdacbfc0ce19ef32bdca9e9159efdf4f54b7eb2a33` |
| `SLPS_019.58` | `95a684498691134646005075c3b46cc226f4f9321dc11896f3de5dc9e5fe54aa` |
| 출력 Track 1 | `d290859416e3573177c4e1e3df40bdad2013fa9ded31c8baae4ed6fb178f851f` |

출력 Track 1 크기는 원본과 같은 602,020,272바이트다. 파일별 실제 변경은
다음과 같다.

| 파일 | 변경 파일 바이트 | 변경 raw sector |
|---|---:|---:|
| `START.BIN` | 55,046 | 45 |
| `ALLBIN.BIN` | 302,894 | 404 |
| `SLPS_019.58` | 289 | 4 |
| **합계** |  | **453** |

전체 raw diff의 sector 집합은 사전 Expected Write와 일치한다. 변경 전·후
453개 sector의 Mode 2/Form 1 EDC와 이 디스크가 쓰는 zero-address P/Q ECC가
유효하다. 완성 Track에서 세 파일을 다시 추출한 SHA-256도 파일 빌드와
일치한다.

## 재현 명령

```bash
.venv/bin/python scripts/audit_dialogue_reinsertion.py

.venv/bin/python scripts/build_dialogue_chapter_patch.py \
  --start-bin work/extracted/disc1/iso/START.BIN \
  --allbin work/extracted/disc1/iso/ALLBIN.BIN \
  --all-story \
  --placement-policy unit-shared-pool \
  --allow-unit-capacity-space-compaction \
  --output-dir work/build/dialogue-u00-u34-current-incomplete

.venv/bin/python scripts/build_character_name_patch.py \
  --file-build-dir work/build/dialogue-u00-u34-current-incomplete \
  --output-dir work/build/dialogue-u00-u34-current-incomplete-names

.venv/bin/python scripts/build_ui_translation_patch.py \
  --file-build-dir work/build/dialogue-u00-u34-current-incomplete-names \
  --output-dir work/build/dialogue-u00-u34-current-incomplete-names-ui

.venv/bin/python scripts/build_dialogue_chapter_disc.py \
  --file-build-dir work/build/dialogue-u00-u34-current-incomplete-names-ui \
  --output-dir work/build/dialogue-u00-u34-current-incomplete-names-ui-disc
```

마지막 출력 파일명에 남아 있는 `chapter01`은 초기 도구의 역사적 기본
이름이다. manifest의 `selected_units`와 SHA-256이 실제 범위의 정본이며,
파일명만으로 챕터 범위를 판정하지 않는다.

## 사용자 실행 관측

사용자는 이 Track 1을 제2장 종료까지 직접 진행했고 해당 경로에서 프리즈,
대사 순서 뒤섞임, 앞부분 잘림, 초상화·화자명 소실과 분기 밀림이 다시
발생하지 않았다고 확인했다. Codex는 사용자 방침에 따라 GUI 자동 조작이나
Lua 실행을 하지 않았다.

이 관측이 증명하지 않는 범위는 다음과 같다.

- 제3장 이후와 선택하지 않은 모든 분기
- `u22..u34`의 아직 발견하지 못한 무포인터 연속 페이지
- 미니게임·코스·머신 설정 391개와 그래픽 라벨
- 이름 등록 화면의 모든 입력 팔레트·출신 선택 조합
- 번역의 의미·용어·띄어쓰기 품질

로컬에는 이 전체 빌드의 Track 1 하나만 유지하고 이전 개발용 전체 ROM은
삭제했다. 원본 BIN/CUE와 이 출력 이미지는 `roms/`, `work/`의 비커밋
자료이며 Git에는 코드·번역 정본·manifest를 재생성하는 절차와 해시만
남긴다.
