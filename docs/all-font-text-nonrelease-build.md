# Disc 1 그래픽 제외 전체 폰트 문자열 비배포 빌드

## 범위와 판정

2026-07-29 기준으로 현재 식별한 그래픽 에셋 제외 폰트 문자열을 하나의
Disc 1 개발 이미지에 정적 주입했다.

- `u00..u34` 직접 대사 5,783개와 무포인터 연속 페이지 83개
- 고정 주인공명 `시바 / 세이치로`, 화자명 34개
- 이름 등록 폰트 UI 리터럴 4개
- `u38` 미니게임 322개
- `u43` 코스 설명 57개와 머신 설정 설명 12개

일반 대사 빌더가 보고하는 5,866개는 직접 대사와 무포인터 페이지의 합이다.
특수 화면 391개는 별도 고정 슬롯 단계에서 더한다. 현재 조사 분모에서
남아 있는 현지화 대상은 베이크드 그래픽 문자와 번역·실행 QA다. 새 폰트
소비자가 발견되면 이 판정을 다시 연다.

## 글꼴 완전성

특수 화면 번역에 필요한 고유 문자 606개 중 576개는 기존 전체 대사 맵에
있었다. 30개를 추가 배정했으며 미매핑은 0개다. 영문 `E/J/Q/R`과 괄호
`「/」`는 보호된 원본 글리프를 그대로 재사용하고 한글 24자는 Galmuri11로
생성했다. primary 1,229슬롯 중 174슬롯이 남는다.

## 재현 명령

`--all-story`는 `u00..u34`의 지원 대화 unit을 모두 선택한다.

```bash
.venv/bin/python scripts/original_media.py verify --cue
.venv/bin/python scripts/audit_dialogue_reinsertion.py
.venv/bin/python scripts/import_special_screen_translation_batches.py --check

.venv/bin/python scripts/build_dialogue_chapter_patch.py \
  --start-bin work/extracted/disc1/iso/START.BIN \
  --allbin work/extracted/disc1/iso/ALLBIN.BIN \
  --all-story \
  --placement-policy unit-shared-pool \
  --output-dir work/build/dialogue-u00-u34-all-font-current

.venv/bin/python scripts/build_character_name_patch.py \
  --file-build-dir work/build/dialogue-u00-u34-all-font-current \
  --output-dir work/build/dialogue-u00-u34-all-font-current-names

.venv/bin/python scripts/build_ui_translation_patch.py \
  --file-build-dir work/build/dialogue-u00-u34-all-font-current-names \
  --output-dir work/build/dialogue-u00-u34-all-font-current-names-ui

.venv/bin/python scripts/build_special_screen_patch.py \
  --file-build-dir work/build/dialogue-u00-u34-all-font-current-names-ui \
  --output-dir work/build/dialogue-u00-u34-all-font-current-names-ui-special

.venv/bin/python scripts/build_dialogue_chapter_disc.py \
  --file-build-dir work/build/dialogue-u00-u34-all-font-current-names-ui-special \
  --output-dir work/build/disc1-all-known-font-text-2026-07-29
```

`--all-story`가 과거 `u00..u20`만 선택하던 결함은 2026-07-29 수정했으며,
35개 unit 전부를 반환하는 회귀 검사를 둔다.

## 산출물과 정적 검증

| 항목 | 값 |
|---|---|
| Track 1 크기 | 602,020,272바이트 |
| Track 1 SHA-256 | `66025f1527a85b459cc09ea4e3b6750de3db82536df2e7d05f140d37cfea1757` |
| CUE SHA-256 | `2eea7f55b847932450ba063d0982d6eeba92d90a25bce11ca9b068e39ee319ca` |
| 변경 raw sector | 469 |
| START.BIN 변경 sector | 45 |
| ALLBIN.BIN 변경 sector | 420 |
| SLPS_019.58 변경 sector | 4 |

실제 변경 sector 집합은 사전 Expected Write와 일치한다. 변경 전후 모든
해당 Mode 2/Form 1 sector의 EDC와 이 디스크의 zero-address P/Q ECC가
유효하다. 완성 Track에서 `START.BIN`, `ALLBIN.BIN`, `SLPS_019.58`을
재추출한 SHA-256도 파일 빌드와 일치한다.

전체 BIN/CUE는 원본 게임 데이터를 포함하므로 Git에 커밋하지 않는다.

## 남은 실행 검증

GUI와 Lua는 자동 조작하지 않는다는 사용자 방침에 따라 실행 검증은 아직
수행하지 않았다. 생성 CUE를 DuckStation에서 열고 다음을 확인해야 한다.

1. 네 종류 미니게임의 규칙·대사·결과
2. Course Information의 모든 코스 상태와 동적 주인공명
3. 타이어·전략·윙·부스트 설정 대사
4. 기존 `u00..u34` 대사, 분기, 초상, 화자명과 음성 회귀

따라서 이 이미지는 배포판이 아니라 `정적 주입 완료·사용자 실행 검증 필요`
상태다.
