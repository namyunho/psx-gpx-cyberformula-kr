# Disc 1 대사 추출 작업본

## 목적

Disc 1에서 구조적으로 증명된 글꼴 렌더 스트림을 번역 도구, 다른 AI, 사람
번역자가 함께 사용할 수 있는 가역 JSON 작업본으로 만든다. 이 단계에서는
번역하지 않는다. 원본 바이트와 포인터 관계를 기준선으로 고정하고 완역본과
축약본 입력란만 비워 둔다.

추출기는 새 문자열을 휴리스틱으로 검색하지 않고
`work/analysis/disc1-text.json`의 직접 포인터 대상 모집단만 소비한다. 따라서
기존 JSON은 포인터가 가리키는 페이지의 가역 기준선으로는 유효하지만, 물리
스트림의 모든 페이지를 포함하는 최종 모집단은 아니다.

2026-07-26 unit `0` 재삽입 실패를 역추적하면서 엔트리 사이 간격에 포인터가
직접 가리키지 않는 연속 페이지 5개가 있음을 확인했다. 렌더러는 `0x8000`
뒤에서 기준 포인터를 다시 읽지 않고 다음 u16을 계속 소비할 수 있으므로,
포인터 대상만 첫 `0x8000`까지 추출하는 기존 방식은 다중 페이지와 분기 선택
텍스트를 누락한다. 후속 전수 검사로 `u00..u21`에서 무포인터 페이지 83개를
확인했지만 `u22..u34`에는 같은 검사를 아직 완료하지 않았다. 따라서
5,783개를 Disc 1 전체 대사 수로 부르지 않는다.

## 생성 명령과 산출물

원본 검증과 Disc 1 추출을 먼저 완료한 뒤 다음 명령을 실행한다.

```bash
.venv/bin/python scripts/build_japanese_glyph_map.py
.venv/bin/python scripts/extract_disc1_dialogue.py
.venv/bin/python scripts/extract_pointerless_pages.py
.venv/bin/python scripts/extract_special_screen_text.py
```

| 산출물 | 내용 |
|---|---|
| `work/translations/disc1-dialogue.json` | 직접 포인터 대상 대사 5,783개 |
| `work/translations/disc1-dialogue-batches/` | unit 경계를 지킨 최대 100개 단위 협업 배치와 manifest |
| `work/translations/disc1-ui.json` | 이름 등록 화면의 글꼴 렌더 UI 60개 |
| `work/translations/disc1-pointerless-pages-u00-u21.json` | `u00..u21` 무포인터 선택·대사 83개 |
| `data/translations/disc1-pointerless-pages-u00-u21-ko.json` | 무포인터 페이지 한국어 정본 83개 |
| `work/translations/disc1-special-screen-text.json` | `u38/u43` 미니게임·코스·머신 설정 보호 workset 391개 |
| `data/translations/disc1-special-screen-ko.json` | 특수 화면 한국어 초벌 번역 정본 391개 |
| `work/analysis/disc1-dialogue-layout.json` | 대사창 수용량과 저장 공간 진단 |
| `data/dialogue-extraction-schema.json` | 협업용 JSON Schema |

`work/` 아래 파일은 원본 게임 데이터에서 유래하므로 Git에 넣지 않는다. 저장소에는
재생성 가능한 추출기, 스키마, 테스트와 이 문서만 보존한다.

입력 `ALLBIN.BIN`은 다음 SHA-256과 정확히 일치해야 한다.

```text
6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e
```

## 직접 포인터 대상 추출 결과

| 구분 | 항목 수 | 포인터 참조 수 | 원문 바이트 |
|---|---:|---:|---:|
| 스토리 | 4,022 | 대사 합계에 포함 | 대사 합계에 포함 |
| 스고 입단 직후 테스트 주행 (`u21`) | 68 | 대사 합계에 포함 | 대사 합계에 포함 |
| 실제 경기 (`u22..u29`) | 914 | 대사 합계에 포함 | 대사 합계에 포함 |
| 경기 내장 메시지 (`u30..u34`) | 779 | 대사 합계에 포함 | 대사 합계에 포함 |
| **직접 포인터 대상 대사 합계** | **5,783** | **5,917** | **309,654** |
| 이름 등록 화면 글꼴 렌더 UI | 60 | 60 | 3,728 |

`SLPS_019.58`의 정상 경기 선택 코드는 현재 경기 상태 `0..13`에 21을 더해
`u21..u34`를 고른다. 따라서 과거의 `u22..u30=진단 전용`,
`u31..u34=휴면` 분류는 폐기했다. 내용상 `u21`은 입단 직후 테스트 주행이고,
제1장 진입 후 첫 실제 경기는 `u22`에서 시작한다.

직접 포인터 대상 대사 5,783개 중 서로 다른 인코딩 내용은 4,841개다. 한
원문을 여러 포인터가 공유할 수 있으므로 엔트리를 포인터별로 중복 복사하지
않고 모든 참조 위치를 `source.pointer_references`에 보존한다.

`scripts/extract_pointerless_pages.py`는 직접 대사 사이의 보호 gap과 전수
참조 카탈로그를 결합해 `u00..u21`에서 83개를 분리했다.

| 역할 | 엔트리 |
|---|---:|
| 무포인터 선택지 | 29 |
| 무포인터 대사 | 54 |
| **합계** | **83** |

unit `0`의 최초 5개에는 시스템 성별 선택, 예/아니오 선택과 익스트림
스피드 설명 3페이지가 들어간다. 현재 83개 모두 안정 ID와 별도 한국어
정본을 가지며 `unit-shared-pool` 빌드에 직접 대사와 함께 들어간다. 두
원본 스트림은 표시 구간이 둘이라 편집기에서 각각 두 행으로 보이고, 표시
글리프가 없는 제어 전용 센티널 하나는 편집 목록에서 제외한다.

`u38/u43`의 미니게임·코스·머신 설정 391개는 일반 story unit의 직접/무포인터
검사와 다른 소비자를 사용한다. 자세한 모집단, 외부 AI 교정본 병합과 아직
남은 슬롯 초과는
[`special-screen-font-text.md`](special-screen-font-text.md)를 따른다.

`data/glyph-map.json`은 글꼴 표를 렌더러 용도에 맞춰 분리한다. 대사에는
primary 1,229자, 글꼴 렌더 UI에는 alternate 1,484자를 적용하며 두 표의 모든
슬롯을 기록한다. 두 표는 앞쪽 기호 수와 수록 한자가 다르므로 한 대응표로
합치지 않는다.

사용자가 실제 게임 화면 색상에 맞게 정규화한
`primary-glyphs-only_modify.png`와 `alternate-glyphs-only_modify.png`를
Apple Vision 일본어 OCR로 판독했다. 표준 한자부는 JIS X 0208 제1수준
50음도 순서의 엄격한 증가 부분집합이라는 제약을 적용하고, OCR 이탈값은 인접
JIS 범위·글리프 자형·실제 대사 문맥으로 교정했다. primary 표준 한자 991자와
alternate 표준 한자 1,192자는 순서 위반과 누락이 없다. 각 표의 게임 전용
꼬리 영역도 수정 아틀라스를 직접 대조해 기록했다.

비문자 아이콘은 화면 형태에 가까운 유니코드 기호로 표기하지만 원래 u16
`tokens`가 항상 정본이다. 따라서 OCR 판독문을 수정하더라도 원시 코드를 잃거나
재해석하지 않는다.

## 한자 원문 복원 조사

primary의 `0x0046..0x00E4`와 alternate의 `0x0042..0x00E0`은 일부 희귀
가나를 뺀 같은 CP932/JIS 행 순서다. 뒤따르는 한자는 JIS 코드값을 그대로
사용하지 않고, 게임에 필요한 문자만 골라 JIS X 0208 제1수준 순서를 유지한
부분집합이다. 그러므로 표준 Shift-JIS 값을 토큰에 직접 대입해서는 안 된다.

로컬 SCPH-5500 BIOS의 16×15 일본어 글꼴, Tesseract 일본어 모델과 Manga
OCR은 초기 후보를 좁히는 데 사용했다. 최종 승격 근거는 사용자가 색상을
정규화한 아틀라스, Vision OCR, JIS 순서 제약과 자형·문맥 검토의 합치다.

로컬 조사 도구는 다음처럼 준비돼 있다.

```text
tesseract 5.5.2 + tesseract-lang 4.1.0
work/tools/manga-ocr-venv/ (Python 3.12, manga-ocr 0.1.16)
```

대응표 생성기는 수정 아틀라스의 SHA-256을 증거로 고정하고 두 표의 전체 슬롯
수와 JIS 증가 순서를 테스트한다. 이후 판독 수정은 원시 토큰이 아니라
`data/glyph-map.json` 생성 근거와 테스트를 함께 갱신해야 한다.

2026-07-26 재검토에서는 대사 문맥에서 반복적으로 어색했던 primary 네 슬롯을
사용자가 실제 게임의 표시색에 맞춰 정규화한
`work/analysis/font-ocr-atlas/primary-glyphs-only_modify.png`에서 직접 잘라
대조했다. `START.BIN` 원본 렌더는 이 판독의 확정 근거로 사용하지 않는다.

| 슬롯 | 이전 OCR | 교정 | 근거 |
|---:|---|---|---|
| `0x00E4` | `ヶ` | `ν` | modify 슬롯 자형과 모든 대사 문맥이 `νアスラーダ` |
| `0x01AA` | `暁` | `驚` | 하단 `馬` 자형과 `皆驚いてた` 문맥 |
| `0x0310` | `繊` | `薦` | `推薦枠` 문맥과 인접 JIS 범위 |
| `0x03EE` | `溌` | `発` | modify 슬롯 자형과 `発言` 문맥 |

세 한자 교정 뒤에도 primary 표준 한자부의 JIS X 0208 제1수준 순서는 엄격한
증가를 유지한다. `0x00E4`는 표준 한자부가 아니라 구조 문자부이며, 실제 게임이
그리스 문자 `ν`를 가나와 비슷한 대용 자형으로 수록한 사례로 기록한다. 원시
u16 토큰은 바꾸지 않고 표시용 원문 판독만 교정한다.

## JSON 협업 규칙

각 엔트리는 다음 세 영역을 분리한다.

- `source`, `original`, `layout`, `flags`: 추출기가 증명한 보호 필드
- `translation.full`: 의미를 보존한 완역본
- `translation.abbreviated`: 표시 한도 때문에 별도 승인을 받은 축약본

기준선의 두 번역 필드는 모두 아래와 같이 비어 있다.

```json
{
  "translation": {
    "full": {
      "text": "",
      "status": "untranslated",
      "notes": null
    },
    "abbreviated": {
      "text": "",
      "status": "untranslated",
      "notes": null,
      "use_only_when": "approved full translation cannot satisfy layout"
    }
  }
}
```

글리프 코드는 원시 바이트 바로 아래에 그대로 보존하고, 새 일본어 판독 영역은
그 다음에 둔다.

```json
{
  "original": {
    "raw_hex": "0C00...",
    "tokens": ["000C", "..."],
    "japanese": {
      "text": "（ようやくここまできた…",
      "display_text": "（ようやくここまできた…",
      "mapping_complete": true,
      "mapped_glyph_count": 15,
      "unmapped_glyphs": []
    },
    "token_kind_counts": {},
    "control_tokens": []
  }
}
```

외부 도구나 AI에는 필요한 엔트리 묶음과 스키마를 함께 전달한다. 반환 결과에서는
`translation.full`과 `translation.abbreviated`만 병합한다. 다음 필드는 바뀌면
안 된다.

전체 파일은 약 25MB이므로 보통
`work/translations/disc1-dialogue-batches/manifest.json`에서 필요한 배치를
고른다. 배치는 unit 경계를 넘지 않고 최대 100개 엔트리를 담으며, manifest가
각 파일의 SHA-256과 첫·마지막 `entry_id`를 고정한다. 외부 결과를 합칠 때도
파일 순서나 배열 위치가 아니라 `entry_id`를 사용한다.

- `baseline_id`와 `scope`의 원본·글리프 표 해시
- `entry_id`, 분류와 도달 등급
- 파일·unit offset, runtime pointer와 모든 포인터 참조
- `original.raw_hex`, u16 `tokens`, `original.japanese` 판독문과 제어 토큰
- 원문 레이아웃 계측과 플래그

`entry_id`는 원본 내 위치와 참조 순서를 기반으로 결정적으로 생성한다. 예를 들어
`disc1/allbin/u15/event_page/ref0010`은 같은 기준선에서 다시 추출해도 같은
대사를 가리킨다. 번역 배치를 나누거나 여러 도구의 결과를 합칠 때 이 ID를
조인 키로 사용한다.

제어 토큰은 `{speaker_style:03F}`, `{align}`, `{page_end}`처럼 명시적으로
보존한다. 의미가 아직 확정되지 않은 토큰은
`forbidden-until-semantics-confirmed`로 표시하며 번역 도구가 임의로 삭제하거나
재해석하면 안 된다.

## 대사창 레이아웃

IDA Pro의 정확한 xref·주소와 Ghidra의 제어 흐름을 상호 대조하고 첫 대사 RAM
덤프를 확인한 결과, 스토리 대사 한 페이지의 논리 한도는 다음과 같다.

| 항목 | 값 |
|---|---:|
| 한 줄 | 17 position |
| 줄 수 | 3 |
| 한 페이지 | 51 position |
| 글리프 셀 | 14×14px |
| 가로 stride | 14px |
| 세로 stride | 16px |
| VRAM 업로드 | 126×48px, 6,048바이트 |

직접 포인터 대상 스토리 4,022페이지의 최대 사용량은 정확히 51 position이고
84페이지가 한도를 가득 채운다. 이 기준선에서 51 position을 넘는 페이지는
없다.

렌더러에는 51 position을 넘는 입력을 막는 명시적 검사가 없다. 52번째부터는
3줄 VRAM 업로드에 포함되지 않는 행에 쓰고, 계속 넘치면 실행 코드가 시작되는
`0x80030000`에 도달할 수 있다. 재삽입 빌드는 번역문이 51 position을 넘으면
반드시 실패해야 한다.

후보 번역 감사에서는 띄어쓰기 경계 줄바꿈을 기본으로 사용한다. 이 방식으로
네 줄이 되더라도 단어 내부를 나누면 17×3에 들어가는 문장은 사용자의 승인에
따라 예외를 적용하고 `wrap_mode: word-split-fallback`으로 기록한다. 현재
후보에는 이 예외가 16개 있다. 이 중 일부는 비공백 글리프를 모두 보존한 채
공백을 제거했으므로 자연스러운 띄어쓰기의 사람 검토가 필요하다.

2026-07-29 재감사에서 5,783개 모두 기계적으로 17×3에 배치됐고 51글리프
초과와 재삽입 차단은 0개다. 축약 전용 작업본도 현재 0개다.

```text
work/translations/disc1-dialogue-abbreviation-required.json
```

향후 다시 51글리프를 넘는 번역이 생기면 이 파일에 안정 ID, 일본어 원문,
현재 한국어 후보, 최소 필요 글리프 수, 초과량과 빈 `ko_abbreviated`를
기록한다. 자동 축약은 하지 않는다.

기계 배치 통과는 번역 승인과 다르다. 같은 일본어 원문에 서로 다른 한국어가
있는 후보 63묶음과 용어집 표기 불일치 후보 71건이 남아 있다. 문맥·어미
차이로 정당한 항목도 있으므로 자동 치환하지 않고 통합 편집기에서 사람이
검토한다.

## 작업 버퍼와 저장 여유 판정

스토리 렌더 작업 버퍼는 `0x8002D000..0x80030000`, 총 `0x3000`바이트다. 현재
페이지 업로드에 직접 쓰이지 않는 6,240바이트가 있어도 페이지 초기화 때 버퍼
전체가 지워진다. 따라서 이 영역은 수명과 용도가 있는 렌더러 작업 공간으로
보존하며 상주 글꼴이나 대사 확장 공간으로 사용하지 않는다.

포인터 기반 unit 0..29의 저장 구조는 다음과 같다.

| 항목 | 바이트 | 판정 |
|---|---:|---|
| scheduled 총량 | 714,752 | unit 경계 유지 |
| 고유 원문 | 269,906 | 재패킹 대상 |
| 첫 원문 전 prefix | 9,728 | 미분류, 보존 |
| 엔트리 사이 gap | 23,416 | 무포인터 페이지 포함 확인, 전 unit 재분류 필요 |
| 마지막 원문과 포인터 표 사이 | 361,170 | 미분류, 보존 |
| 포인터 표·개수 | 20,656 | 참조 완전 갱신 필요 |
| 말단 zero padding | 29,876 | 후보일 뿐, 현재 사용 금지 |

gap은 빈 공간이 아니라 원본 물리 fall-through와 무포인터 페이지의 일부다.
현재 `unit-shared-pool` 빌더는 모든 알려진 직접·이벤트 참조를 unit별
고정 카탈로그로 검증하고, 대사·무포인터 페이지·제어 셸의 논리 순서를
유지한 채 같은 물리 arena 안에서 재배치한다. 남는 바이트는 참조되지 않는
arena 후미의 `0x0000` 패딩으로만 둔다.

이 구조는 `u00/u21`에서 사용자 실행 검증을 통과했다. `u00..u34` 전체
빌드도 카탈로그·arena 총량·Expected Write를 정적으로 통과했고 사용자가
제2장 종료까지 진행했다. 그러나 나머지 장과 모든 분기의 실행 검증은 아직
끝나지 않았으므로, 한 unit의 잔여량을 다른 unit으로 넘기거나 schedule
경계를 확장하지 않는다. 8개 unit은 비배포 빌드에서 비공백 글리프와 제어
셸을 보존한 채 공백 266개를 제거해 arena 총량을 맞췄다.

## 검증

추출기는 작성 직후 다음 사항을 다시 검사한다.

- 모든 `raw_hex`와 u16 토큰이 원본 바이트로 정확히 되돌아가는지
- 파일 offset의 원본 조각과 엔트리 SHA-256이 일치하는지
- 모든 번역 필드가 비어 있고 상태가 `untranslated`인지
- 생성된 번역 수가 0인지
- 직접 포인터 대상 기준선이 대사 5,783개와 UI 60개인지
- `u00..u21` 무포인터 83개와 `u38/u43` 특수 화면 391개의 모집단 수가
  고정값과 일치하는지

회귀 검사는 다음 명령으로 실행한다.

```bash
.venv/bin/python -m unittest \
  tests.test_extract_disc1_dialogue \
  tests.test_pointerless_pages \
  tests.test_extract_special_screen_text -v
.venv/bin/python -m unittest discover -s tests -v
jq empty data/dialogue-extraction-schema.json
```

후보 번역 재삽입 감사와 챕터 분리는 다음 명령으로 재생성한다.

```bash
.venv/bin/python scripts/audit_dialogue_reinsertion.py
```

이 검사는 보호 필드, 17×3 배치, 단어 분할 예외, 51글리프 초과, 글리프 인코딩
입력과 챕터별 차단 수를 함께 기록한다. 자세한 챕터 1 개발 이미지 결과는
[`chapter01-disc-build.md`](chapter01-disc-build.md)를 따른다.
