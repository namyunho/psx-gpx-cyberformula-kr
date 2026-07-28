# 미니게임·코스·머신 설정 폰트 문자열

## 판정

2026-07-29 기준으로 그래픽 에셋에 새겨진 버튼·라벨과 별개인 폰트 렌더
문자열 391개를 `ALLBIN.BIN` unit `38`, `43`에서 추출했다. 안정 ID와 원문
바이트는 로컬 추출 workset에, 현재 한국어 초벌 번역은 Git 추적 정본에
분리한다.

| 범위 | 수 | 렌더 제약 | 현재 상태 |
|---|---:|---|---|
| 미니게임 규칙 페이지 | 24 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 블랙잭 대사 | 239 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 카메라 대사 | 9 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 요리 대사 | 27 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 요리 런타임 단어 | 23 | 17×1 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 코스 설명 | 57 | 17×3 | 외부 AI 교정본 병합, 안전 슬롯 4건 수정 필요 |
| 머신 설정 설명 | 12 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| **합계** | **391** |  | **ROM 미주입** |

이 391개에는 머신 설정 화면의 타이어·윙·부스트 설명과 코스 정보 대사가
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
| `data/translations/disc1-special-screen-ko.json` | 한국어 번역 정본 391개 | 추적 |
| `scripts/export_special_screen_translation_brief.py` | 외부 AI용 간결한 검토본과 배치 생성 | 추적 |
| `work/translations/disc1-special-screen-translation-batches/` | 200+191건 로컬 교환 배치 | 비커밋 |
| `scripts/import_special_screen_translation_batches.py` | 보호 필드 검증 후 `ko`만 정본에 병합 | 추적 |
| `work/analysis/disc1-special-screen-translation-batch-import.json` | 병합 검사 보고서 | 비커밋 |

`work/` 파일은 원본 바이트와 일본어 텍스트를 포함하는 재생성 가능 파생
자료라 커밋하지 않는다. 번역 정본은 안정 ID와 한국어 문자열만 보존한다.
병합 기록에는 사용한 workset과 두 원본/번역 배치의 SHA-256을 남겨 로컬
증거와 다시 대조할 수 있게 한다.

## 외부 AI 교정본 병합 결과

두 `-ko` 배치는 각각 200건과 191건이며 다음 검사를 통과했다.

- 391개 안정 ID의 집합·순서와 배치 범위가 workset과 정확히 일치
- `entries[].ko` 이외의 배치 필드 변경 0건
- 빈 한국어 0건, 일본어 문자 잔존 0건
- `{name:surname}`, `{name:given}` 불일치 0건
- `◯`, `♥`, `💢`, `💦`, `💧`, `♪`, `ZERO` 같은 의미 기호 누락 0건
- 행 수·17글리프 열 한도 초과 0건

현재 정본 상태는
`external-ai-revised-draft-static-and-runtime-review-required`다. 외부
AI의 교정은 번역 완성이나 빌드 적격 승인이 아니다. 원문 보호와 기계
레이아웃만 통과했으며, 사람의 의미·용어 검수와 실제 화면 검증이 남아 있다.

원본 슬롯에 그대로 쓰는 보수적 기준에서는 코스 설명 4건이 아직 길다.

| 안정 ID | 현재 위치 | 원본 한도 | 초과 |
|---|---:|---:|---:|
| `disc1/allbin/u43/course_page/ref0027` | 29 | 26 | 3 |
| `disc1/allbin/u43/course_page/ref0038` | 29 | 28 | 1 |
| `disc1/allbin/u43/course_page/ref0042` | 27 | 24 | 3 |
| `disc1/allbin/u43/course_page/ref0050` | 20 | 18 | 2 |

여기서 위치 수는 표시 글리프와 줄바꿈 토큰을 포함하고 고정 제어토큰은
별도로 보존해 계산한 값이다. `u43`의 공용 재배치가 검증되지 않았으므로
다른 문장의 남는 공간을 이 네 문장에 임의로 배분하지 않는다.

## 재현과 검증

```bash
.venv/bin/python scripts/extract_special_screen_text.py
.venv/bin/python scripts/export_special_screen_translation_brief.py

# -ko 배치를 받은 뒤 보호 필드와 현재 초과를 검사
.venv/bin/python scripts/import_special_screen_translation_batches.py --check

# 검사 통과 뒤 한국어 필드만 정본에 병합
.venv/bin/python scripts/import_special_screen_translation_batches.py

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
실행됐다는 증거가 아니다. 현재 비배포 ROM은 이 특수 화면 정본을 아직
주입하지 않는다. 다음 단계는 다음 순서로 진행한다.

1. 코스 설명 4건을 원본 슬롯 안으로 교정한다.
2. `u38/u43`의 모든 쓰기를 Expected Write로 계획하는 재삽입기를 만든다.
3. primary 글꼴 맵에 391개 번역의 한글 글리프를 함께 배정한다.
4. 원본 슬롯·제어 셸·포인터와 Mode 2/Form 1 EDC/ECC를 정적으로 검증한다.
5. 사용자가 미니게임 네 종류, 코스 정보, 타이어·윙·부스트 설정을 실제
   화면에서 검수한다.

이 단계 전에는 391개를 “번역 초안 병합 완료”로만 부르며 “ROM 번역
완료”로 부르지 않는다.
