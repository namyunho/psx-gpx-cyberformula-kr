# 미니게임·코스·머신 설정 폰트 문자열

## 판정

2026-08-08 기준으로 `ALLBIN.BIN` unit `38`, `43`에서 파싱 가능한 특수 화면
문자열 422개를 추출했다. 이 가운데 417개가 폰트 렌더 소비자에 연결되고,
규칙 제목 5개는 안정 ID를 보존하는 무참조 중복 문자열이다. 실제 화면의 같은
제목은 `MINI_G3.BIN` unit 0에 새겨진 4bpp 그래픽이다. 안정 ID와 원문 바이트는
로컬 추출 workset에, 현재 한국어 초벌 번역은 Git 추적 정본에 분리한다.

| 범위 | 수 | 렌더 제약 | 현재 상태 |
|---|---:|---|---|
| 미니게임 규칙 제목·헤더 중복 문자열 | 5 | 13×1 | 무참조 보존; 실제 MINI_G3 그래픽 별도 주입 |
| 미니게임 규칙 페이지 | 24 | 13×3~4 | 13열 재조판, 실행 검토 필요 |
| 블랙잭 대사 | 239 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 카메라 대사 | 9 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 요리 대사 | 27 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 요리 런타임 단어 | 23 | 17×1 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 요리 결과 합성 조각 | 4 | 17×1~2 | 런타임 캡처로 누락 확인, 한국어 주입 |
| 코스 설명 | 57 | 17×3 | 외부 AI 교정본 병합, 정적 주입 완료 |
| 머신 설정 설명 | 12 | 17×3 | 외부 AI 교정본 병합, 실행 검토 필요 |
| 모터홈 행동 메뉴 | 2 | 17×3 | 실행 위치 확인, 정적 주입 |
| 머신 설정 순차 대사·확인 선택 | 20 | 17×1~4 자동 줄바꿈 | 고정 제어코드 보존 주입, 실행 검토 필요 |
| **합계** | **422** |  | **ROM 정적 주입 완료, 실행 검토 필요** |

규칙 화면의 공통 제목과 게임명은 `MINI_G3.BIN` unit 0의 4bpp 완성형
그래픽이다. `u38:0x18214..0x1827E`의 동명 문자열에는 IDA·Ghidra 코드 참조가
없다. 채택 표기는 `규칙 설명`, `앙리를 붙잡아라`, `음료 도둑 찍기`,
`레나의 3분 요리`, `블랙잭`이며 `scripts/build_minigame_rule_graphics_patch.py`가
현재 primary 글꼴의 명암 인덱스를 사용해 그래픽에 삽입한다.
세 번째 캐시 행의 `앙리를 붙잡아라`와 `블랙잭`은 원본 일본어 잉크의
기준선이 47px 행까지 내려오지만 한글 잉크가 45px에서 끝나 화면에서 약 2px
위로 보였다. 두 제목만 2px 아래로 옮기고 `블랙잭`은 2px 오른쪽으로도
옮긴다. 원본과 삽입 미리보기를 대조한 결과 마지막 `y=47` 행의 잔여 69픽셀은
별도 항목이 아니라 두 일본어 제목의 마지막 명암 행이었다. 이 고정 원본
마스크의 불투명 픽셀만 제거한 뒤 이동한 한글을 그리며, `x<16`의 캐시 경계,
`x>=240`의 cyan guard와 캐시 밖 `y>=48` 그래픽은 그대로 보존한다.

이 422개에는 머신 설정 화면의 타이어·윙·부스트 설명, 그 전후의 설명·확인
분기와 코스 정보 대사가
들어간다. `Machine Setting`, 타이어 버튼, `Course Information` 타이틀처럼
이미지 픽셀에 새겨진 영문·일문은 들어가지 않는다. 그래픽 문자는 프로젝트
방침에 따라 마지막 단계에서 별도로 다룬다.

## u09 런타임 인라인 메뉴

PCSX-Redux의 주크박스 선택 화면에서 대사 추출 모집단 밖의
`ⓧ　キャンセル` 리터럴을 확인했다. `ALLBIN.BIN` 파일 오프셋 `0x305F0`,
u09 상대 오프셋 `0x5DF0`의 5글리프 고정 슬롯이다. `FFFD 0013 0000` 앞부분과
뒤의 `FFFC` 제어 및 메뉴 데이터 위치는 유지하고, 본문만 `취소`와 후행 공백
3글리프로 교체한다.

정본은 `data/translations/disc1-inline-menu-ko.json`, 빌더는
`scripts/build_inline_menu_patch.py`다. 동일한 제어 셸은 전체 `ALLBIN.BIN`에서
이 항목 한 건만 확인됐다. 정적 슬롯·Expected Writes와 Disc 1·2 이미지 검증은
통과했으며 새 이미지에서 화면 확인이 남아 있다.

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
- `u38` `0x18214..0x18280`의 무참조 규칙 헤더·미니게임 제목 중복 5개
- `u38` 요리 결과에서 런타임 선택하는 음식·상태 단어 23개
- `u38` 요리 결과 문장을 이어 붙이는 따옴표·서술어·유사 음식 조각 4개
- `u43` 코스 상태 switch가 선택하는 7개 포인터 표의 대사 57개
- `u43` 타이어·전략·윙·부스트 설명의 고정 시작점 12개
- `u43`의 두 인접 순차 스트림 `0x3EA8..0x4068`, `0x4444..0x4784`에서
  화자·음성 제어 사이에 놓인 머신 설정 대사·확인 선택 20개

마지막 20개는 직접 포인터 표가 아니라 실행 커서가 순서대로 소비하는 슬롯이다.
특히 확인 선택은 `FFFD`와 `D002`를 포함한다. 재삽입기는 모든 원본 제어
워드의 토큰 위치와 바이트 주소를 그대로 보존하고 글리프 워드만 교체한다.
원본 스트림에 줄바꿈 워드가 없으므로 편집기에서는 수동 개행을 금지하고
17열 런타임 자동 줄바꿈 결과를 1~4행으로 보여준다.

추출기는 원본 unit 크기·해시와 각 모집단 수를 고정한다. 지원하지 않는
글리프, 종료자를 찾지 못한 문자열, 예상 수량 변화가 있으면 실패한다.

## 산출물과 단일 기준

| 경로 | 역할 | Git |
|---|---|---|
| `scripts/extract_special_screen_text.py` | 원본 `u38/u43`에서 보호 workset 재생성 | 추적 |
| `work/translations/disc1-special-screen-text.json` | raw·토큰·소비자·레이아웃 보호 기준선 | 비커밋 |
| `data/translations/disc1-special-screen-ko.json` | 한국어 번역 정본 422개 | 추적 |
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
규칙 제목 5건, 이번 감사에서 확인한 머신 설정 순차·분기 20건은 정본
마지막에 안정 ID로 추가했다. 아래의 391건 수치는 외부 AI가 검토한 역사적
접두 범위이며, 현재 전체 422건의 분모와 구분한다.

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
저장 위치를 분리해 다시 계산한 결과 역사적 391건 모두 원본 고정 슬롯에 들어간다.
재삽입기는 이름 제어토큰을 한 단어로 보존하고, 앞뒤 제어 셸과 포인터를
이동하지 않는다. 2026-08-01 PCSX-Redux VRAM에서 규칙 창을 직접
확인한 결과, 본문의 채택 표시 범위는 17열이 아니라 13열이었다. 추격·카메라·
요리·블랙잭 규칙 본문 24개를 모두 같은 기준으로 재조판했다.

### 요리 결과 합성 조각 누락 수정

2026-08-04 런타임 캡처에서는 번역된 `와, 레나의 특기인`, 조리상태와
요리명 사이에 `쉬거운…`처럼 의미 없는 한글이 나타났다. 이는 번역문
오인식이 아니라 원본 일본어 글리프 index를 교체된 한글 글꼴로 읽은
결과였다. 해당 화면은 한 문자열이 아니라 다음 조각을 차례로 소비한다.

```text
접두문 + 여는 따옴표 + 조리상태 + 요리명
       + "に\n似た食べ物" + 닫는 따옴표 + "だぁ！"
```

`u38:0x1DA02`, `0x1DA08`, `0x1DA0C`, `0x1E200`의 네 조각은 매우
짧고 `FFFF`와 `8000` 종료자가 섞여 있어 기존 포인터·gap 스캔에서
제외됐다. 이제 `cooking_composite/*` 안정 ID로 보호 workset과 통합
편집기에 포함한다. 한국어 합성은 접두문 끝 줄바꿈을 복원하고
`" 「" + 상태 + 요리명 + " 같은\n음식" + "」" + "이야!"`가 되도록
각 물리 슬롯 안에서 인코딩한다. 일본어의 조사 `の`가 담당하던 경계는
일곱 상태 단어의 마지막 반각 공백으로 바꿔 모든 상태·요리명 조합에서
한글 어절이 붙지 않게 했고, 7×16 조합 모두 17열×3행 이내임을 검사한다.
`p1E018`의 후속 반응도
`(맛을 논하기 전에 / 이게 음식이긴 한 걸까…?)`로 교정했다.

### 요리 소감 페이지 경계와 종료자 수정

요리 시식 후 일반 소감과 재료별 소감이 두 번 나오는 것은 원본 이벤트 표의
의도된 동작이다. 문제는 번역 빌더가 직접 참조된 첫 페이지만 줄이고, 뒤의
일본어 페이지 또는 0 패딩을 같은 스트림에 남겼다는 점이었다. 또한 후속
페이지 재패킹 경로가 최종 `FFFF`를 기록하지 않아 다음 데이터까지 읽을 수
있었다.

원본 `u38`에는 시식 1종과 반응 18종의 독립 스트림이 있다. 각 스트림은
1~4개의 `8000` 페이지 뒤에 `FFFF` 하나로 끝난다. 빌더는 이제 19개 시작
주소를 고정한 채 원본과 같은 페이지 수를 요구하고, 번역 페이지 뒤에
`FFFF` 하나를 붙인 다음 남은 바이트만 0으로 채운다. 구두점만 있어 자동
일본어 판정에서 빠졌던 `u38:0x1DA50`의 `…。`도 `p1DA50` 안정 ID로 보호한다.
정적 검증 결과 19개 모두 원본 페이지 수와 종료자 수가 일치한다.

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

# 실제 화면에 쓰이는 MINI_G3 unit 0의 베이크드 제목 5개 주입
.venv/bin/python scripts/build_minigame_rule_graphics_patch.py \
  --file-build-dir <updated-file-build> \
  --output-dir <updated-file-build-with-rule-graphics>

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

2026-08-08 clean boot 캡처에서 VRAM `(828,446) 68×48 halfword`가
`MINI_G3.BIN` unit 0의 `(768,256) 128×256 halfword` 레코드 우하단과 행별로
완전히 일치했다. 일치한 6,528바이트의 SHA-256은
`72ae0fb2bc73e9943de8ab3c2dda593749c0ea93ba59f7bd377f2c5b25285558`이다.
동시에 RAM의 다섯 `u38` 문자열은 한글이었지만 VRAM은 일본어였고, IDA와
Ghidra 모두 그 주소들에 코드 참조가 없음을 확인했다. 이는 과거의
“폰트 렌더 확인” 판정을 반증하며, 저장→적재→표시 연결은 MINI_G3 그래픽으로
확정한다. Disc 1·2의 원본 MINI_G3 해시가 동일함도 빌더가 검사한다.

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
