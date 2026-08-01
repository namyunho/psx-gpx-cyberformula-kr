# 미니게임·코스·머신 설정 폰트 문자열

## 판정

2026-08-01 기준으로 그래픽 에셋에 새겨진 버튼·라벨과 별개인 폰트 렌더
문자열 398개를 `ALLBIN.BIN` unit `38`, `43`에서 추출했다. 안정 ID와 원문
바이트는 로컬 추출 workset에, 현재 한국어 초벌 번역은 Git 추적 정본에
분리한다.

| 범위 | 수 | 렌더 제약 | 현재 상태 |
|---|---:|---|---|
| 미니게임 규칙 제목·헤더 | 5 | 13×1 | VRAM 폰트 렌더 확인, 한국어 주입 |
| 미니게임 규칙 페이지 | 24 | 13×3~4 | 13열 재조판, 실행 검토 필요 |
| 블랙잭 대사 | 239 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 카메라 대사 | 9 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 요리 대사 | 27 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 요리 런타임 단어 | 23 | 17×1 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 코스 설명 | 57 | 17×3 | 외부 AI 교정본 병합, 정적 주입 완료 |
| 머신 설정 설명 | 12 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 모터홈 행동 메뉴 | 2 | 17×3 | 실행 위치 확인, 정적 주입 |
| **합계** | **398** |  | **ROM 정적 주입 완료, 실행 검토 필요** |

이 398개에는 머신 설정 화면의 타이어·윙·부스트 설명과 코스 정보 대사가
들어간다. `Machine Setting`, 타이어 버튼, `Course Information` 타이틀처럼
이미지 픽셀에 새겨진 영문·일문은 들어가지 않는다. 그래픽 문자는 프로젝트
방침에 따라 마지막 단계에서 별도로 다룬다.

## 원본과 소비자

지원 원본 `ALLBIN.BIN` SHA-256은 다음과 같다.

```text
6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e
```

| unit | ALLBIN 파일 범위 | 런타임 기준 주소 | unit SHA-256 | 역할 |
|---|---|---:|---|---|
| `u38` | `0x12B000..0x14B000` | `0x80098000` | `533f5e8585504a70d704ee64e2c41a48fb29e17f1e5ed4803ade1072c0ee5a6f` | 미니게임 |
| `u43` | `0x169000..0x16E800` | `0x800A8000` | `6bb12d3f6bb4b44e0ecbfe9c9944eb156b94f2d48ceef9cee10e5fd9373a0cd2` | 코스·머신 설정 |

`scripts/ghidra/AnalyzeSpecialScreenText.java`와
`scripts/ghidra/AnalyzeRaceTextRouting.java`는 Ghidra의 긴 분기·포인터
전달을 확인한다. IDA/idalib에서는 같은 주소의 명령 경계, 직접 참조와
delay slot을 대조했다. 이 교차 조사로 다음 소비자를 구분했다.

- `u38` 정렬된 포인터가 가리키는 미니게임 페이지 260개
- `u38` 코드가 직접 참조하는 대사 39개
- `u38` `0x18214..0x18280`의 규칙 헤더·미니게임 제목 5개
- `u38` 요리 결과에서 런타임 선택하는 음식·상태 단어 23개
- `u43` 코스 상태 switch가 선택하는 7개 포인터 표의 대사 57개
- `u43` 타이어·전략·윙·부스트 설명의 고정 시작점 12개

추출기는 원본 unit 크기·해시와 각 모집단 수를 고정한다. 지원하지 않는
글리프, 종료자를 찾지 못한 문자열, 예상 수량 변화가 있으면 실패한다.

## 산출물과 단일 기준

| 경로 | 역할 | Git |
|---|---|---|
| `scripts/extract_special_screen_text.py` | 원본 `u38/u43`에서 보호 workset 재생성 | 추적 |
| `work/translations/disc1-special-screen-text.json` | raw·토큰·소비자·레이아웃 보호 기준선 | 비커밋 |
| `data/translations/disc1-special-screen-ko.json` | 한국어 번역 정본 398개 | 추적 |
| `scripts/export_special_screen_translation_brief.py` | 외부 AI용 간결한 검토본과 배치 생성 | 추적 |
| `work/translations/disc1-special-screen-translation-batches/` | 200+191건 로컬 교환 배치 | 비커밋 |
| `scripts/import_special_screen_translation_batches.py` | 보호 필드 검증 후 `ko`만 정본에 병합 | 추적 |
| `work/analysis/disc1-special-screen-translation-batch-import.json` | 병합 검사 보고서 | 비커밋 |

`work/` 파일은 원본 바이트와 일본어 텍스트를 포함하는 재생성 가능 파생
자료라 커밋하지 않는다. 번역 정본은 안정 ID와 한국어 문자열만 보존한다.
병합 기록에는 사용한 workset과 두 원본/번역 배치의 SHA-256을 남겨 로컬
증거와 다시 대조할 수 있게 한다.

## 외부 AI 교정본 병합 결과

두 `-ko` 배치는 각각 200건과 191건이며, 이후 추가한 메뉴 2건과
규칙 제목 5건은 정본 마지막에 안정 ID로 추가했다.

- 391개 안정 ID의 집합·순서와 배치 범위가 workset과 정확히 일치
- `entries[].ko` 이외의 배치 필드 변경 0건
- 빈 한국어 0건, 일본어 문자 잔존 0건
- `{name:surname}`, `{name:given}` 불일치 0건
- `◯`, `♥`, `💢`, `💦`, `💧`, `♪`, `ZERO` 같은 의미 기호 누락 0건
- 규칙 페이지·제목은 13글리프, 나머지는 17글리프 열 한도 초과 0건
- 원본 고정 저장 슬롯 초과 0건

현재 정본 상태는
`external-ai-revised-draft-static-and-runtime-review-required`다. 외부
AI의 교정은 번역 완성이나 빌드 적격 승인이 아니다. 원문 보호와 기계
레이아웃만 통과했으며, 사람의 의미·용어 검수와 실제 화면 검증이 남아 있다.

과거 검사에서 코스 설명 4건이 초과로 보고됐지만 계산 오류였다.
`{name:surname}`, `{name:given}`은 화면에 여러 글리프로 펼쳐져도
`ALLBIN.BIN`에는 이름 삽입 제어토큰 하나의 u16으로 저장된다. 표시 폭을
저장 위치 수로 다시 더한 것이 거짓 양성의 원인이었다. 표시 레이아웃과
저장 위치를 분리해 다시 계산한 결과 391건 모두 원본 고정 슬롯에 들어간다.
재삽입기는 이름 제어토큰을 한 단어로 보존하고, 앞뒤 제어 셸과 포인터를
이동하지 않는다. 2026-08-01 PCSX-Redux VRAM에서 규칙 창을 직접
확인한 결과, 본문의 채택 표시 범위는 17열이 아니라 13열이었다. 추격·카메라·
요리·블랙잭 규칙 본문 24개를 모두 같은 기준으로 재조판했다.

## 글꼴 맵과 정적 주입 결과

전체 대사·이름·UI 빌드의 primary 글꼴 맵을 유지한 채 특수 화면에 필요한
문자를 추가했다.

| 항목 | 결과 |
|---|---:|
| 특수 화면 고유 필요 문자 | 606 |
| 기존 맵에서 재사용 | 576 |
| 추가 배정 | 30 |
| 원본 글리프 그대로 보존 | `E`, `J`, `Q`, `R`, `「`, `」` 6자 |
| Galmuri11로 생성 | 한글 24자 |
| 미매핑 문자 | 0 |
| 남은 primary 슬롯 | 174 |
| 고정 슬롯 초과 | 0 |

`scripts/build_special_screen_patch.py`는 지원 원본과 workset 해시, 안정 ID,
원본 바이트, 제어 셸, 저장 슬롯을 검증한 뒤 `u38/u43`을 주입한다. 기존
대사 글리프 index를 재배정하지 않으며 변경은 Expected Write로 기록한다.

## 재현과 검증

```bash
.venv/bin/python scripts/extract_special_screen_text.py
.venv/bin/python scripts/export_special_screen_translation_brief.py

# -ko 배치를 받은 뒤 보호 필드와 현재 초과를 검사
.venv/bin/python scripts/import_special_screen_translation_batches.py --check

# 검사 통과 뒤 한국어 필드만 정본에 병합
.venv/bin/python scripts/import_special_screen_translation_batches.py

# 기존 전체 대사·이름·UI 파일 빌드에 특수 화면과 필요한 글꼴을 추가
.venv/bin/python scripts/build_special_screen_patch.py \
  --file-build-dir work/build/dialogue-u00-u34-all-font-current-names-ui \
  --output-dir work/build/dialogue-u00-u34-all-font-current-names-ui-special

# 이미 통합 주입된 현재 파일 빌드의 미니게임 규칙 범위만 검증 갱신
.venv/bin/python scripts/build_minigame_rule_patch.py \
  --file-build-dir <current-file-build> \
  --output-dir <updated-file-build>

# 그래픽을 제외한 모든 폰트 문자열을 함께 검사
.venv/bin/python scripts/dialogue_layout_editor.py --check
```

관련 회귀 검사는 다음과 같다.

```bash
.venv/bin/python -m unittest \
  tests.test_extract_special_screen_text \
  tests.test_export_special_screen_translation_brief \
  tests.test_import_special_screen_translation_batches \
  tests.test_dialogue_layout_editor -v
```

## 실행 관측과 남은 작업

2026-07-28 사용자가 비배포 전체 대사 빌드를 제2장 종료까지 진행하면서
미니게임, 코스 설명과 머신 설정 화면에서 번역되지 않거나 깨진 폰트 대사를
확인했다. 다음 로컬 캡처는 조사 입력으로 사용했지만 Git에는 넣지 않는다.

```text
tmp/Shin Seiki GPX Cyber Formula - Aratanaru Chousensha (Disc 1) 2026-07-28-14-40-23.png
tmp/Shin Seiki GPX Cyber Formula - Aratanaru Chousensha (Disc 1) 2026-07-28-14-50-53.png
```

캡처는 화면 범위와 글꼴 렌더 여부를 찾는 증거이지, 현재 391개 번역이
실행됐다는 증거가 아니다. 2026-07-29 통합 비배포 ROM에는 391건을 모두
정적 주입했고 원본 슬롯·제어 셸·글꼴 맵·Expected Write와 Mode 2/Form 1
EDC/ECC를 검증했다. 남은 단계는 사용자가 미니게임 네 종류, 코스 정보,
타이어·전략·윙·부스트 설정과 동적 주인공명 출력을 실제 화면에서 확인하는
것이다. 그 전에는 “정적 주입 완료, 실행 검토 필요”로 판정한다.
