# unit 공용 대사 arena 재연결

## 목적과 기준선

이 구조 검증은 사용자 실행 검증을 통과한 커밋 `3f3aa74`의
`u00/u21` 고정 원본 주소 빌드를 보존한 채
`experiment/unit-dialogue-pool` 브랜치에서 수행한다.

검증한 가설은 다음과 같다.

- 개별 `ref****`는 원래 슬롯보다 길거나 짧아질 수 있다.
- 대사와 대사 사이의 화자·초상·음성·종료·선택지·무포인터 페이지 등
  기타요소는 바이트와 논리 순서를 보존한 채 함께 이동할 수 있다.
- 대사와 기타요소를 합친 물리 arena는 원래 byte capacity를 넘지 않으며,
  최종 출력도 같은 byte capacity를 유지한다.
- 모든 직접·간접 소비자가 새 구조 앵커를 가리키면 대사 순서, 분기,
  초상·화자명과 음성이 유지된다.
- 남는 용량은 다른 unit으로 넘기지 않고 같은 unit의 물리 arena 후미에만
  둔다.

현재 번역본은 사용자가 `u00/u21`을 개별 안전 슬롯 안으로 이미 교정했기
때문에 원래 슬롯을 넘는 항목이 0개다. 따라서 이번 빌드는 먼저 **모든
대사 주소를 실제로 이동시켜도 소비자와 기타요소가 함께 따라오는지**를
검증한다. 이 실행 검증이 통과해야 이후 긴 완역문이 같은 unit의 여유를
사용하도록 확대할 수 있다.

## 이전 재배치 실패 원인

기존 `source-order-repack`은 물리 대사 순서와 378바이트의 inter-entry
gap을 보존하고 추출기에 기록된 u00 포인터 92개를 갱신했다. 하지만
사용자 실행에서 다음 두 대사는 재배치 주소가 아니라 원래 주소부터
읽혔다.

| 항목 | 재배치 주소 | 실제로 읽힌 주소 |
|---|---:|---:|
| `u00/ref0002` | `0x00E0` | `0x00F0` |
| `u00/ref0003` | `0x010E` | `0x0124` |

원본 u00을 다시 전수 조사하면 `ref0002`의 절대 주소
`0x800A80F0`은 추출기가 기록한 `0x28BC`뿐 아니라 이벤트 명령의 operand
`0x192C`에도 있다. 이전 빌드는 `0x28BC`만 고쳐 `0x192C`의 실제 소비자가
원래 주소로 진입했다. 같은 방식의 누락은 u00에 97개, u21에 67개였다.

`SLPS_019.58`의 fresh IDA headless 검사는 기존 결론과도 일치한다.
`sub_8003907C`가 기준 포인터를 설정하고 `sub_8003229C`가 커서를 0으로
초기화하며, `sub_80032D34`는 `base + cursor × 2`를 순차 소비한다.
기존 Ghidra 장기 제어 흐름 분석도 같은 결과를 기록했다. 이번에 새로
확인한 것은 renderer가 아니라 **ALLBIN unit 내부 이벤트 operand의 누락된
포인터 분모**다.

## 전수 참조 카탈로그

지원 원본 `ALLBIN.BIN` SHA-256
`6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e`
에서 각 독립 적재 unit의 모든 byte 위치를 검사했다. 대사 물리 run을
가리키는 32비트 absolute pointer는 모두 4바이트 정렬되어 있었으며,
문자열 내부 진입 포인터는 0개였다.

| unit | unit bytes | 전체 참조 | 기존 추출 참조 | 추가 이벤트 소비자 | direct entry | 보존 gap |
|---|---:|---:|---:|---:|---:|---:|
| `u00` | 12,288 | 189 | 92 | 97 | 183 | 6 |
| `u21` | 20,480 | 135 | 68 | 67 | 135 | 0 |

카탈로그는 반복 빌드에서 새 후보를 자동 채택하지 않는다. storage와 원본
target의 정렬 목록을 다음 SHA-256으로 고정하고 개수·분류·digest가 하나라도
다르면 빌드를 실패시킨다.

| unit | frozen catalog SHA-256 |
|---|---|
| `u00` | `5829e12496562e919811f93cfb7fdd1d68fc5d2e69272deddcac7770f9b67d1e` |
| `u21` | `6421b4f9059af3efdbeaee89fe6981469e3232c8f1a1c66139ab69df15f2f7e5` |

u00의 보존 gap 참조 6개는 다음 무포인터 페이지의 구조 앵커다.

- 성별 선택 페이지: `0x0B8C`
- 예/아니오 선택 페이지: `0x0E18` 두 참조
- 익스트림 스피드 설명: `0x132C`, `0x1388`, `0x13F0`

이 주소들은 번역문 안의 원본 byte 거리로 추정하지 않는다. 해당 raw gap
전체를 byte-exact로 옮기고 gap 시작에 대한 delta로 다시 계산한다.

## 재삽입 불변식

`unit-shared-pool` 정책은 다음을 자동 검증한다.

1. 각 번역 entry의 원본 leading/trailing 제어 셸이 byte-exact다.
2. 포인터 없는 페이지를 포함한 모든 inter-entry gap이 byte-exact다.
3. 물리 entry와 gap의 순서가 원본과 같다.
4. frozen catalog의 모든 참조를 새 entry 또는 보존 gap 앵커로 계산한다.
5. 문자열 내부를 가리키거나 앵커가 없는 참조가 하나라도 있으면 실패한다.
6. 알려진 extractor 포인터는 전수 카탈로그의 부분집합이어야 한다.
7. 재배치 뒤 모든 참조와 모든 인코딩 stream을 다시 읽어 대조한다.
8. packed stream이 원래 물리 arena를 넘으면 실패한다.
9. 출력 arena는 후미 `0x0000` padding을 포함해 원래와 정확히 같은 byte
   capacity다. padding은 대사·기타요소 사이에 넣지 않는다.
10. Expected Writes 밖의 `START.BIN`·`ALLBIN.BIN` 변경은 실패한다.

후미 padding에는 카탈로그 포인터가 없다. 2026-07-27 사용자 실행 검증에서
u00 시작부터 u21의 분기와 종료까지 진행해 마지막 페이지 이후의 암묵적
fall-through, 초상·화자·음성·분기 흐름에 이상이 없음을 확인했다.

## 현재 정적 결과

| 항목 | `u00` | `u21` |
|---|---:|---:|
| entries | 88 | 68 |
| 원본 direct text bytes | 5,624 | 4,226 |
| 현재 한국어 text bytes | 4,848 | 3,974 |
| 보존 inter-entry gap bytes | 378 | 82 |
| 물리 arena capacity | 6,002 | 4,308 |
| packed 대사+기타요소 | 5,226 | 4,056 |
| 후미 padding | 776 | 252 |
| 최종 arena bytes | 6,002 | 4,308 |
| 원래 개별 안전 슬롯 초과 | 0 | 0 |
| 보호 제어 셸 tokens | 193 | 154 |
| 무포인터 pages | 5 | 0 |
| 재연결·재검증 참조 | 189 | 135 |

첫 연속 대사의 원본→출력 위치는 다음과 같다.

```text
u00/ref0000 0x0054 → 0x0054
u00/ref0001 0x0098 → 0x0096
u00/ref0002 0x00F0 → 0x00E0
u00/ref0003 0x0124 → 0x0110
u00/ref0004 0x0144 → 0x0130
```

과거 실패를 만든 이벤트 operand `0x192C`와 pointer-table entry
`0x28BC`는 이제 둘 다 `ref0002`의 새 runtime 주소 `0x800A80E0`을
가리킨다.

## 재현 명령

```bash
.venv/bin/python scripts/build_dialogue_chapter_patch.py \
  --start-bin work/extracted/disc1/iso/START.BIN \
  --allbin work/extracted/disc1/iso/ALLBIN.BIN \
  --workset work/translations/disc1-dialogue.json \
  --reflow-overlay work/translations/disc1-dialogue-ko-reflowed-nonrelease.json \
  --reinsertion-audit work/analysis/disc1-dialogue-reinsertion-audit.json \
  --unit 0,21 \
  --placement-policy unit-shared-pool \
  --output-dir work/build/dialogue-u00-u21-unit-shared-pool

.venv/bin/python scripts/build_character_name_patch.py \
  --file-build-dir work/build/dialogue-u00-u21-unit-shared-pool \
  --output-dir work/build/dialogue-u00-u21-unit-shared-pool-names

.venv/bin/python scripts/build_dialogue_chapter_disc.py \
  --file-build-dir work/build/dialogue-u00-u21-unit-shared-pool-names \
  --output-dir work/build/dialogue-u00-u21-unit-shared-pool-names-disc
```

## 실행 검증 결과

GUI와 Lua는 자동으로 실행하지 않았다. 사용자는 다음 Track 1을 포함한 CUE를
직접 부팅해 아래 범위를 모두 통과했다고 보고했다.

```text
Track 1 SHA-256
39da4bc7eb8d49944be5ad95f4acd73364d1ca1172f186772ca884c15a024b3f
```

1. u00 `ref0000..ref0004`가 앞부분 잘림 없이 순서대로 표시되는가.
2. 각 화면의 초상, 화자명과 음성이 원래 시점에 나타나는가.
3. 성별 선택, 예/아니오, 익스트림 스피드 설명의 무포인터 페이지와 분기가
   정상인가.
4. u00의 마지막까지 진행한 뒤 다음 장면으로 전환되는가.
5. u21의 기존 세 번째 분기 부근과 마지막까지 프리즈 없이 진행되는가.
6. u21에서도 초상, 화자명, 음성과 분기 결과가 유지되는가.

판정은 `unit-shared-pool-u00-u21-runtime-pass`다. `u00`, `u21`에서는
개별 원본 슬롯을 빌드 차단 한도로 사용하지 않고 unit 원본 대사 스트림
총량을 공용 한도로 사용할 수 있다. 단, 다음 조건은 유지한다.

- 줄당 최대 17글리프, 페이지당 최대 3줄이다.
- 대사 사이의 무포인터 페이지와 이벤트 gap은 공용 용량이 아니라 byte-exact
  보호 대상이다.
- 다른 unit의 잔여량을 가져오지 않는다.
- `u00`, `u21` 이외의 unit은 참조 카탈로그와 실행 검증을 별도로 완료하기
  전까지 같은 판정을 자동 승계하지 않는다.

이 결과와 편집기의 unit 공용 용량 검사는 `main`의 주 작업 방식으로
승격한다. 프로젝트 전체 번역은 미완료이므로 빌드 상태는 계속
`nonrelease-partial-translation`이다.
