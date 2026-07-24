# Disc 1 대사 추출 작업본

## 목적

Disc 1에서 구조적으로 증명된 글꼴 렌더 스트림을 번역 도구, 다른 AI, 사람
번역자가 함께 사용할 수 있는 가역 JSON 작업본으로 만든다. 이 단계에서는
번역하지 않는다. 원본 바이트와 포인터 관계를 기준선으로 고정하고 완역본과
축약본 입력란만 비워 둔다.

추출기는 새 문자열을 휴리스틱으로 검색하지 않고
`work/analysis/disc1-text.json`의 확정 모집단만 소비한다. 따라서 결과의 범위는
기존 구조 분석과 일치하며, 미확정 데이터가 조용히 번역 대상으로 섞이지 않는다.

## 생성 명령과 산출물

원본 검증과 Disc 1 추출을 먼저 완료한 뒤 다음 명령을 실행한다.

```bash
.venv/bin/python scripts/build_japanese_glyph_map.py
.venv/bin/python scripts/extract_disc1_dialogue.py
```

| 산출물 | 내용 |
|---|---|
| `work/translations/disc1-dialogue.json` | 대사 5,783개 |
| `work/translations/disc1-dialogue-batches/` | unit 경계를 지킨 최대 100개 단위 협업 배치와 manifest |
| `work/translations/disc1-ui.json` | 글꼴 렌더 UI 60개 |
| `work/analysis/disc1-dialogue-layout.json` | 대사창 수용량과 저장 공간 진단 |
| `data/dialogue-extraction-schema.json` | 협업용 JSON Schema |

`work/` 아래 파일은 원본 게임 데이터에서 유래하므로 Git에 넣지 않는다. 저장소에는
재생성 가능한 추출기, 스키마, 테스트와 이 문서만 보존한다.

입력 `ALLBIN.BIN`은 다음 SHA-256과 정확히 일치해야 한다.

```text
6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e
```

## 추출 결과

| 구분 | 항목 수 | 포인터 참조 수 | 원문 바이트 |
|---|---:|---:|---:|
| 스토리 | 4,022 | 대사 합계에 포함 | 대사 합계에 포함 |
| 일반 레이스 | 68 | 대사 합계에 포함 | 대사 합계에 포함 |
| 진단·시험 경로 | 1,080 | 대사 합계에 포함 | 대사 합계에 포함 |
| 휴면·정적 미도달 | 613 | 대사 합계에 포함 | 대사 합계에 포함 |
| **대사 합계** | **5,783** | **5,917** | **309,654** |
| 글꼴 렌더 UI | 60 | 60 | 3,728 |

대사 5,783개 중 서로 다른 인코딩 내용은 4,841개다. 한 원문을 여러 포인터가
공유할 수 있으므로 엔트리를 포인터별로 중복 복사하지 않고 모든 참조 위치를
`source.pointer_references`에 보존한다.

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

원본 스토리 4,022페이지의 최대 사용량은 정확히 51 position이고 84페이지가
한도를 가득 채운다. 원본에서 51 position을 넘는 페이지는 없다.

렌더러에는 51 position을 넘는 입력을 막는 명시적 검사가 없다. 52번째부터는
3줄 VRAM 업로드에 포함되지 않는 행에 쓰고, 계속 넘치면 실행 코드가 시작되는
`0x80030000`에 도달할 수 있다. 재삽입 빌드는 번역문이 51 position을 넘으면
반드시 실패해야 한다.

고정 이름 `시바 세이치로`의 길이만 원문 정렬에 기계적으로 적용해 본 결과,
`disc1/allbin/u15/event_page/ref0010` 한 페이지가 58 position이 된다. 이는
번역 결과가 아니라 사전 레이아웃 경고다. 해당 페이지는 번역 후 `{align}` 위치와
문장을 다시 배치해야 한다.

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
| 엔트리 사이 gap | 23,416 | 미분류, 보존 |
| 마지막 원문과 포인터 표 사이 | 361,170 | 미분류, 보존 |
| 포인터 표·개수 | 20,656 | 참조 완전 갱신 필요 |
| 말단 zero padding | 29,876 | 후보일 뿐, 현재 사용 금지 |

겉보기 여유 바이트는 로더와 런타임 소비가 끝까지 증명되지 않았다. 현재 방침은
모든 prefix·gap·마지막 원문 뒤 영역을 보존하고, 말단 zero padding도
`candidate-unproven-do-not-use`로 취급하는 것이다. unit을 가로지르는 증가는
schedule과 로더 경계까지 증명하기 전에는 금지한다.

번역이 승인된 뒤 각 문자열의 실제 인코딩 크기를 측정하고, 모든 참조를 갱신하는
unit 내부 재패커를 proven bound 안에서 구현한다. 공간이 모자랄 때만 별도 저장
영역이나 로더 변경을 설계한다.

## 검증

추출기는 작성 직후 다음 사항을 다시 검사한다.

- 모든 `raw_hex`와 u16 토큰이 원본 바이트로 정확히 되돌아가는지
- 파일 offset의 원본 조각과 엔트리 SHA-256이 일치하는지
- 모든 번역 필드가 비어 있고 상태가 `untranslated`인지
- 생성된 번역 수가 0인지
- 확정 모집단이 대사 5,783개와 UI 60개인지

회귀 검사는 다음 명령으로 실행한다.

```bash
.venv/bin/python -m unittest tests.test_extract_disc1_dialogue -v
.venv/bin/python -m unittest discover -s tests -v
jq empty data/dialogue-extraction-schema.json
```

실제 번역을 병합하는 단계에는 같은 보호 필드 검사를 별도 명령으로 재사용하고,
완역본·축약본의 51 position 검사와 인코딩 가능 여부를 추가해야 한다.
