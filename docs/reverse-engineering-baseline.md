# Disc 1 수정 전 역공학 기준선

최초 검토일: 2026-07-24

최근 구조 갱신: 2026-07-29
대상: `Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1)`

이 문서는 한국어 데이터를 쓰기 전에 고정한 구조 기준선이다. 여기서 “완전”은
Disc 1의 수정 범위에 들어오는 저장 단위가 빠짐없이 분모에 들어가고, 각 단위가
대사·폰트·베이크드 그래픽·비대상 데이터 중 하나로 분류됐다는 뜻이다. 게임의
모든 실행 코드를 의미하지 않는다.

현재 새 바이너리 수정은 시작하지 않았다. 베이크드 그래픽은 각 화면의 실제 소비
경로까지 확인한 상태만 개별 편집 대상으로 승격한다.

## 원본 기준

기본 원본 위치:

```text
roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1).cue
roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1) (Track 1).bin
```

Track 1은 `MODE2/2352` 데이터 트랙이며 Track 2~4는 CDDA다.

| 식별값 | 값 |
|---|---|
| 크기 | 602,020,272바이트 |
| raw sector | 255,961 |
| CRC32 | `725BA190` |
| MD5 | `a33012953c1cc37ee472450377fb8ec8` |
| SHA-256 | `35e43fba9c5ffc39ab805adbc42f13ec3198c888c1c1e9e651408409e041b2a9` |

원본은 읽기 전용으로 취급하며 `config/original-media.json`과
`scripts/original_media.py`가 위치와 식별값을 검증한다.

## 실행 파일과 로더 구조

부트 파일 `SLPS_019.58`의 PS-X EXE 경계:

| 항목 | 값 |
|---|---:|
| entry | `0x80041C18` |
| load address | `0x80030000` |
| text size | `0x31000` |
| file payload | `+0x800` |

확정한 테이블과 로더:

| 구조 | 주소 | 수량/역할 |
|---|---:|---|
| ISO 파일 레코드 | `0x80057444` | 19개 |
| 로드 descriptor | `0x80058FB8` | 164개 |
| scheduled-file loader | `0x80041294` | descriptor index를 인자로 받음 |

부트 코드의 loader 직접 호출은 61개이며, 국소 상수 전달이 증명되는 호출은
56개, 레지스터 유래라 정적 스캐너가 의도적으로 미확정으로 둔 호출은 5개다.
후자의 존재는 파일·상태 분모에 빈칸을 만들지 않는다. descriptor 테이블과 아래
스케줄이 파일 전체를 이미 분할하기 때문이다.

초기 조사에서 `0x80048E3C`를 `ALLBIN.BIN` 읽기 래퍼로 기록한 판정은
철회한다. IDA와 Ghidra에서 main 및 `ALLBIN` 30번 오버레이를 별도 base로
분석한 결과 이 함수는 사각형과 좌표를 받아 화면 영역을 옮기는 `MoveImage`
계열 호출이다.

## 스케줄과 파일 분모

모든 표는 `{u16 start_sector, u16 sector_count}`이며 첫 섹터 0에서 파일 끝까지
틈·중첩 없이 정확히 분할한다.

| 파일 | 상태 수 | 바이트 | 표 위치 |
|---|---:|---:|---|
| `MINI_G1.BIN` | 2 | 278,528 | boot EXE |
| `MINI_G2.BIN` | 2 | 155,648 | boot EXE |
| `MINI_G3.BIN` | 3 | 245,760 | boot EXE |
| `MINI_G4.BIN` | 3 | 245,760 | boot EXE |
| `AVM_MAP.BIN` | 1,334 | 115,515,392 | boot EXE |
| `START.BIN` | 65 | 5,015,552 | boot EXE |
| `SOUND.BIN` | 152 | 14,837,760 | boot EXE |
| `ALLBIN.BIN` | 44 | 1,501,184 | boot EXE |
| `OUTSIDE.BIN` | 11 | 1,857,536 | boot EXE |
| `MACHINE.BIN` | 42 | 2,439,168 | `ALLBIN` unit 37 + `0x12A9D4` |
| `COURSE.BIN` | 277 | 9,576,448 | `ALLBIN` unit 37 + `0x12AA7C` |

`MACHINE`과 `COURSE`의 표는 각각 runtime `0x800AA9D4`,
`0x800AAA7C`에 대응한다. `scripts/psx_layout.py`가 이 분할과 각 상태의
SHA-256을 `work/analysis/disc1-layout.json`에 재현한다.

## 실제 폰트로 그리는 문자열

기존 직접 포인터·이름 등록 UI 조사에서 증명한 글꼴 스트림은 5,843개다.

| 구분 | 스트림 | 도달 판정 |
|---|---:|---|
| `ALLBIN` 0..20 | 4,022 | 일반 스토리 경로 |
| `ALLBIN` 21 | 68 | 입단 직후 테스트 주행 |
| `ALLBIN` 22..29 | 914 | 실제 경기 경로 |
| `ALLBIN` 30..34 | 779 | 실제 경기 경로, 혼합 code/data overlay |
| `ALLBIN` 40 UI | 60 | main/overlay 직접 참조 또는 공유 mutable buffer |

따라서 직접 포인터 대상 대사 5,783개는 모두 정상 스토리·테스트 주행·실제
경기 경로에 포함된다. unit 42의 진단 메뉴에서도 일부 경기 unit을 고를 수
있지만, 그것은 정상 경로 도달성을 배제하는 증거가 아니다.

0..29번의 5,004개 엔트리는 각 scheduled unit 끝의 포인터 배열과 count로
증명된다. 30..34번은 짧은 MIPS 초기화 코드와 데이터가 섞인 overlay다.
정렬된 in-unit u32 참조가 같은 unit 안의 토큰 스트림을 가리키며 각 스트림은
`FFFF` 또는 `D003`에 도달한다. 우연히 종료자처럼 보이는 u32 값 표는
명시적으로 제외한다. 이 표에서 포인터가 없는 바이트열은 직접 포인터
모집단으로 승격하지 않는다. 물리 fall-through와 별도 코드 소비자가 증명된
문자열은 아래의 독립 추출기로 분리한다.

핵심 총계:

- 포인터 표 엔트리: 5,004개, 포인터 참조 5,134개
- 혼합 레이스 overlay 엔트리: 779개, 참조 783개
- UI 스트림: 60개
- 전체 서로 다른 encoded content: 4,901개
- 전체 glyph index: `0x000..0x5CB`, 서로 다른 index 1,478개

기계 판독 보고서는 `scripts/psx_text_inventory.py`로 생성한다.

### 후속 확인한 무포인터·특수 화면 문자열

직접 포인터 모집단만으로 게임의 모든 폰트 문자열을 대표할 수 없다는 사실을
재삽입 실행 실패와 별도 화면 소비자 조사로 확인했다.

| 범위 | 원본 엔트리 | 현재 분류 |
|---|---:|---|
| `u00..u21` 물리 gap의 연속 페이지 | 83 | 선택 29, 대사 54 |
| `u38` 미니게임 | 322 | 포인터 페이지 260, 직접 대사 39, 요리 런타임 단어 23 |
| `u43` 코스 설명 | 57 | 코스 상태 switch가 고르는 7개 포인터 표 |
| `u43` 머신 설정 설명 | 12 | 타이어·전략·윙·부스트 고정 시작점 |
| 기존 workset 밖 추가 글꼴 스트림 | 716 | 순차 291, 경기 색인 325, 미니게임 73, 저장 27 |

무포인터 83개는 `scripts/extract_pointerless_pages.py`가 직접 대사 사이의
보호 gap과 참조 카탈로그를 함께 검사해 추출한다. 특수 화면 391개는
`scripts/extract_special_screen_text.py`가 `u38/u43`의 고정 unit 해시,
포인터·직접 시작점과 모집단 수를 검증한다. 추가 716개는
`scripts/extract_unindexed_font_text.py`가 기존 범위를 마스킹한 물리 gap에서
찾은 후보 776개 중 검토한 이진 오탐 60개를 제외해 생성한다.

이 수치는 기존 5,843개에 단순히 더해 “Disc 1 최종 총계”라고 부르지 않는다.
기존 5,843개에는 번역하지 않는 이름 입력 팔레트·런타임 버퍼까지 포함되고,
새 716개도 모든 색인 진입 경로를 전수 증명한 최종 모집단은 아니다. 번역
편집기는 현재 확인된 범위 중 실제로 편집할 항목만 정규화해 7,014행으로
보여준다. 특수 화면 391개의 상태는
[`special-screen-font-text.md`](special-screen-font-text.md), 추가 716개의
근거와 번역 상태는
[`unindexed-font-text.md`](unindexed-font-text.md)를 따른다.

## 폰트 공급자와 렌더러

두 폰트 공급자는 모두 14×14, 3bpp, 글리프당 74바이트다.

| 공급자 | 저장 위치 | RAM | 정의 slot | 마지막 정의 index |
|---|---:|---:|---:|---:|
| primary dialogue | `START + 0x1A000` / unit 2 | `0x80014A00` | 1,229 | `0x4CC` |
| alternate UI | `START + 0x3D1800` / unit 40 | `0x80185000` | 1,484 | `0x5CB` |

`sub_80032704`가 `(token & 0x0FFF) * 74`를 선택하고
`sub_80032434`가 14×14 3bpp를 작업 표면으로 해제한다. alternate 분기는
`dword_80061140 & 0x2000`일 때 선택된다. 일반 대사 최대 index `0x4CB`는
primary 범위 안이고, UI 최대 index `0x5CB`는 alternate의 마지막 정의
글리프와 일치한다.

## 초상과 베이크드 그래픽

초상화 경로:

- `sub_8003C558`: `START`의 `41 + story_state`를 `0x800B8000`에 적재
- `sub_800329B8`: 토큰의 `(token & 0x0FC0) >> 6`으로
  `0x560 * portrait_index` 선택
- block: 32바이트 CLUT + 1,344바이트 48×56 4bpp
- `START` 41..64: 625 block, 서로 다른 내용 127개, 중복 498개

초상화에는 현재 접촉표에서 번역할 문자가 없으며 베이크드 문자 수정 분모에서
제외한다.

그래픽 관련 scheduled state 1,739개는 다음처럼 정확히 분할된다.

| 역할 | 상태 수 |
|---|---:|
| 베이크드 문자 시각 검토 | 1,463 |
| 폰트 공급자 | 2 |
| 초상화 공급자 | 24 |
| 비그래픽 COURSE 데이터 | 250 |

구조적으로 VRAM 사각형과 맞는 블록은 2,462개지만 이것은 번역 자산 수가 아니다.
팔레트·이미지·메타데이터·제어 record가 한 scheduled state를 이루며, 폰트도
우연히 사각형 header 검사에 맞을 수 있다. 그래픽 작업 단위와 상세 분모는
`docs/graphics-text-inventory.md`가 정본이다.

## IDA와 Ghidra 교차검증

두 도구는 같은 결론을 복제하는 용도가 아니라 서로 다른 실패 형태를 잡는 데
사용했다.

| 항목 | IDA/idalib | Ghidra | 결론 |
|---|---|---|---|
| main EXE | 정확한 주소·xref·descriptor write 전수 검색 | 긴 상태 분기와 pointer 전달 복원 | loader와 상태 선택 일치 |
| 정상 경기 진입 | `0x80058FF6` write xref와 `sub_8003C94C` 명령열 확인 | `0x8003CE34..0x8003CE78` delay slot 포함 교차 확인 | 현재 경기 상태 `0..13`에 21을 더해 `u21..u34` 선택 |
| `ALLBIN` 42 | 직접 write와 call address 확인 | 진단 switch 디컴파일 | 21..30 선택은 대사, 12..35 선택은 SOUND라는 구분 확정 |
| `ALLBIN` 30 | entry와 혼합 code/data 경계 확인 | 별도 PS-X EXE import 후 entry 디컴파일 | 같은 초기화 흐름, `0x80048E3C` 오판 철회 |
| `ALLBIN` 38·43 | 직접 문자열 시작·정렬 포인터와 수량 대조 | 미니게임·코스 상태 switch와 런타임 단어 전달 복원 | 그래픽이 아닌 폰트 문자열 391개 분리 |
| 초상화 | 토큰 bitfield와 block stride xref | 로드→선택 흐름 대조 | START 41..64 공급자 확정 |

이전의 `u22..u30=진단 전용`, `u31..u34=휴면` 판정은
`0x8003CE58`의 동적 계산을 고정 descriptor write 조사에서 놓친 결과이므로
폐기한다. `sub_8003C94C`는 현재 경기 상태 byte를 읽어 `addiu +0x15`한 값을
descriptor 5의 sub-id `0x80058FF6`에 저장하고 loader
`sub_80041294(5)`를 호출한다. MIPS delay slot 때문에 저장은 호출 직전에
실행된다. 상태 범위가 `0..13`이므로 정상 경기는 `u21..u34` 전체를 선택한다.
내용상 `u21`은 테스트 주행이고 `u22`가 제1장 진입 후 실제 첫 경기다.

## 수정 전 게이트

대사/폰트 구조 게이트는 통과했다. 그래픽 구조 분모도 닫혔다. 그러나 개별
그래픽 state의 편집 게이트는 다음 증거가 생기기 전까지 닫혀 있다.

1. 실제 화면 primitive와 Texpage/UV/CLUT 확인
2. 해당 VRAM 범위를 마지막으로 채운 `GP0(A0)` 또는 VRAM copy 확인
3. DMA2 MADR/BCR/CHCR 또는 PIO 원본 RAM 확인
4. RAM writer/변환 경로를 scheduled state의 offset·SHA-256까지 연결
5. 원본과 수정본에서 목표 문자 외 영역·팔레트가 동일함을 검증

이 게이트는 `docs/gpu-upload-source-tracing.md`의 절차를 따른다. 구조적 분모가
완성됐다는 이유만으로 1,463개 state를 일괄 수정하지 않는다.

## 재현 명령

```bash
.venv/bin/python scripts/original_media.py verify --cue
.venv/bin/python scripts/psx_layout.py \
  --output work/analysis/disc1-layout.json
.venv/bin/python scripts/psx_text_inventory.py \
  --output work/analysis/disc1-text.json
.venv/bin/python scripts/extract_pointerless_pages.py
.venv/bin/python scripts/extract_special_screen_text.py
.venv/bin/python scripts/psx_font_inventory.py \
  --output work/analysis/disc1-fonts.json
.venv/bin/python scripts/psx_portrait_inventory.py \
  --output work/analysis/disc1-portraits.json
.venv/bin/python scripts/psx_graphics_scope.py \
  --output work/analysis/disc1-graphics-scope.json
```

`work/`의 원본 추출·DB·이미지·RAM은 커밋하지 않는다. 저장소에는 생성기,
테스트, 주소·수량·해시와 판정만 남긴다.
