# 신세기 GPX 사이버 포뮬러 새로운 도전자 한국어화

PlayStation용 일본 게임 **《신세기 GPX 사이버 포뮬러 새로운 도전자》**
Disc 1의 한국어 패치를 제작하기 위한 분석·도구·문서를 관리하는 저장소입니다.

현재는 원본 디스크 구조, 텍스트 엔진, 폰트 공급자와 그래픽 상태 분모를 전수
목록화한 뒤 Galmuri11 본문 폰트 PoC를 검증하는 단계입니다. 베이크드 그래픽은
화면 소비 경로가 확인된 상태만 편집 대상으로 승격합니다. 게임 ROM, BIOS,
추출 파일, RAM 덤프는 저장소에 포함하지 않습니다.

## 로컬 준비

원본 Disc 1의 기본 위치는 다음과 같습니다.

```text
roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1).cue
roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1) (Track 1).bin
```

멀티 BIN/CUE의 나머지 오디오 트랙도 같은 디렉터리에 두고 CUE의 원래 참조 관계를
유지합니다. 다른 위치를 사용하려면 `PSX_DISC1_CUE`와
`PSX_DISC1_TRACK1` 환경 변수로 재정의합니다. 원본 파일은 저장소에 커밋하지
않습니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-analysis.txt
.venv/bin/python scripts/original_media.py prepare
.venv/bin/python scripts/original_media.py paths
.venv/bin/python scripts/original_media.py verify --cue
```

기본 경로와 지원 원본의 크기·CRC32·MD5·SHA-256은
[`config/original-media.json`](config/original-media.json)이 관리합니다.

## 현재 진행 상황

- [x] Disc 1 BIN/CUE 구조와 데이터·오디오 트랙 확인
- [x] 실행 파일 및 주요 데이터 파일 추출 절차 작성
- [x] 원본 이미지 해시와 PS-X EXE 메타데이터 기록
- [x] `ALLBIN.BIN`의 커스텀 16비트 텍스트 스트림 확인
- [x] 손실 없는 텍스트 추출·재조립 도구 작성
- [x] 실제 대사 화면과 디스크/RAM 텍스트 주소 대응
- [x] 최초 확인 글리프 29자 매핑
- [x] 텍스트 토큰 해석 경로와 토큰 동기 CD 오디오 경로 분리
- [x] 실제 시각 글리프 렌더러와 폰트 비트맵 위치 확정
- [x] 5,843개 font-rendered stream의 저장 구조와 도달 등급 분류
- [x] 1,739개 그래픽 관련 state의 역할 분모 확정
- [x] IDA Pro·Ghidra로 loader/overlay/초상 경로 교차검증
- [x] Disc 1의 컨테이너·텍스트·그래픽·오디오·영상 전량 추출 및 검증
- [x] Galmuri11 12px → 실제 11×11 잉크 → 14×14 게임 셀 프로필 확정
- [x] 첫 한글 PoC용 빈 슬롯·대상 토큰 확정 및 로컬 이미지 생성
- [x] 첫 한국어 대사 PoC 제작·에뮬레이터 검증
- [x] Galmuri11 첫 대사 PoC 정적 삽입·raw Track diff 검증
- [ ] Galmuri11 첫 대사 DuckStation 화면 검증
- [x] 한국어 글리프 저장 공간 결정
- [x] 고상위 한글 토큰 렌더러 훅 PoC 폐기 및 리맵 표 전략 전환
- [x] 리맵/표시 버퍼 생성 경로 추적 PoC
- [ ] 베이크드 문자 대상별 GPU 소비 지점과 저장 state 연결
- [ ] 소비 지점 런타임 계측 및 로컬 토큰 리맵 패치 PoC
- [ ] 전체 대사 추출·번역·재삽입
- [ ] 재현 가능한 패치 빌드 및 배포용 패치 생성

## 확인된 핵심 정보

- 대상: 일본판 Disc 1, 부트 실행 파일 `SLPS_019.58`
- Disc 1 Track 1: `MODE2/2352` 데이터 트랙
- Disc 1 Track 2~4: CDDA 오디오 트랙
- 텍스트 저장 형식: little-endian 16비트 커스텀 글리프 인덱스
- 대표 텍스트 시작 위치: `ALLBIN.BIN + 0x54`
- 해당 블록의 확인된 RAM 적재 주소: `0x800A8054`
- 확인된 줄 경계 토큰: `0xFFFB`
- 확인된 페이지 대기 토큰: `0x8000`
- 증명된 font-rendered stream: 5,843개
- 그래픽 관련 scheduled state: 1,739개
- 베이크드 문자 시각 검토 state: 1,463개

최초로 대응한 화면 문장은 다음과 같습니다.

```text
（ようやくここまできた…憧れの
チーム、「スゴウグランプリ」）
```

수정 전 구조 기준선과 원본 이미지 해시는
[`docs/reverse-engineering-baseline.md`](docs/reverse-engineering-baseline.md)에
기록합니다. 2026-07-12의 역사적 첫 판정은
[`docs/initial-survey.md`](docs/initial-survey.md)에 보존합니다.

## 번역판 고정 방침

- 주인공의 한국어 이름은 **시바 세이치로**로 고정합니다.
- 범용 한글 이름 입력기를 새로 만들지 않습니다.
- 이름 선택 화면에서는 **시바 세이치로**만 선택할 수 있도록 단순화합니다.
- 이후 대사의 이름 변수도 이 고정 이름을 정상적으로 표시해야 합니다.

## 도구

| 파일 | 용도 |
|---|---|
| `scripts/psx_disc.py` | MODE1/MODE2 PS1 이미지의 ISO9660 조사 및 읽기 전용 추출 |
| `scripts/psx_layout.py` | 파일 레코드·164개 loader descriptor·11개 파일 schedule의 정확한 분할 조사 |
| `scripts/psx_text_inventory.py` | 포인터/코드 참조로 증명되는 5,843개 글꼴 스트림 전수 목록 |
| `scripts/psx_font_inventory.py` | primary/alternate 14×14 3bpp 폰트 공급자 경계 조사 |
| `scripts/psx_portrait_inventory.py` | START 41..64의 CLUT+48×56 4bpp 초상 block 목록 |
| `scripts/psx_graphics_scope.py` | 1,739개 그래픽 관련 state의 상호 배타적 수정 역할 분류 |
| `scripts/psx_vram_render.py` | raw VRAM rectangle의 검토용 접촉표 렌더링 |
| `scripts/psx_loader_calls.py` | main EXE의 scheduled-file loader 직접 호출과 상수 인자 조사 |
| `scripts/extract_disc1_assets.py` | ISO/state/child/text/font/portrait/VRAM/VAB/SEQ/raw XA·STR 전량 추출 |
| `scripts/decode_disc1_streams.py` | XA·VAB ADPCM, CDDA, MDEC를 PCM/FFV1로 무손실 해제 |
| `scripts/verify_disc1_extraction.py` | state 재결합·원본 해시·PCM frame·MDEC frame 전량 검증 |
| `scripts/mips_survey.py` | PS1 MIPS 코드와 BIOS 호출 후보 조사 |
| `scripts/mips_disasm.py` | PS-X EXE·raw overlay 선형 디스어셈블과 delay slot 표시 |
| `scripts/build_ida_db.py` | PS-X EXE header를 반영한 MIPS little-endian IDA DB 생성 |
| `scripts/hex_dump.py` | 임의 파일/RAM 범위의 hex·Shift-JIS·little-endian u16 덤프 |
| `scripts/tim_scan.py` | 구조적으로 유효한 PS1 TIM 이미지 탐색·렌더링 |
| `scripts/custom_text.py` | 커스텀 u16 텍스트의 손실 없는 추출·재조립·부분 해독 |
| `scripts/gdb_dump.py` | DuckStation GDB 서버를 통한 PS1 RAM 덤프 |
| `scripts/gdb_write.py` | DuckStation GDB 서버를 통한 검증된 PS1 RAM 쓰기 |
| `scripts/ram_map.py` | 디스크 파일 조각과 RAM 적재 위치 대응 |
| `scripts/psx_font.py` | 14×14, 3bpp 압축 글리프 추출·렌더링·재인코딩 |
| `scripts/korean_font.py` | 한글 TTF·16×16 비트맵의 14×14 게임 포맷 변환·미리보기 |
| `scripts/build_font_poc.py` | 첫 대사의 빈 슬롯 한글 PoC 파일·에뮬레이터용 이미지 생성 |
| `scripts/render_font_poc_preview.py` | 수정 `START.BIN`의 실제 글리프 레코드로 2줄 셀 미리보기 생성 |
| `scripts/verify_font_poc.py` | 폰트 슬롯·대사 영역·raw Track 예상 쓰기 전량 검증 |
| `scripts/build_cache_hook_poc.py` | 폐기된 고상위 한글 토큰 렌더러 훅 PoC 재현 이미지 생성 |
| `scripts/trace_remap_path.py` | RAM 덤프와 실행 파일에서 리맵/표시 버퍼 포인터 체인 추적 |
| `scripts/original_media.py` | 비커밋 원본 경로 준비·해시·CUE track 구조 검증 |
| `scripts/toolchain.py` | Python·MCP·IDA/Ghidra·DuckStation·패치 도구 진단 |
| `scripts/mcp_probe.py` | 프로젝트 MCP 서버의 `initialize` handshake 점검 |

확인된 부분 글리프 맵은
[`data/glyph-map.json`](data/glyph-map.json)에 누적합니다. 근거가 확보되지 않은
글자는 임의로 추정하지 않고 미매핑 상태로 유지합니다.

대사 글꼴은 `START.BIN + 0x1A000`에 있는 글자당 74바이트의 14×14,
3bpp primary 표이며, UI용 alternate 표는 `START.BIN + 0x3D1800`입니다.
상세 포맷과 실행 코드 경로는
[`docs/font-format.md`](docs/font-format.md)에 정리합니다.

그래픽 픽셀에 새겨진 문자의 작업 단위, 파일별 state 분모와 편집 승격 조건은
[`docs/graphics-text-inventory.md`](docs/graphics-text-inventory.md)에
정리했습니다.

Disc 1의 전체 추출 경로, 24,000개 이상의 원본·파생 파일과 XA/MDEC/VAB
압축 해제 결과는 [`docs/disc1-extraction.md`](docs/disc1-extraction.md)에
정리했습니다. 실제 산출물은 `work/extracted/disc1/`에 있습니다.

PCSX-Redux의 GPU Logger와 Lua breakpoint로 화면 primitive의 VRAM 좌표에서
`GP0(A0) → DMA2 MADR/CHCR → RAM writer → 저장 자산`을 역추적하는 방법은
[`docs/gpu-upload-source-tracing.md`](docs/gpu-upload-source-tracing.md)에
정리했습니다. 대사 폰트 위치는 이미 확정됐으므로, 이 기법은 미확인 UI·이미지
탐색과 저장→RAM→VRAM→화면 연결 검증에 사용합니다.

사용 글꼴은 로컬 `fonts/galmuri11/`의 `Galmuri11 Regular`로 확정했습니다.
16×16은 참고 `.bin`의 컨테이너이며, 빌드는 TTF를 공식 네이티브 크기 12px로
래스터해 실제 최대 11×11 잉크를 14×14 셀 중앙에 배치합니다. 11px 파생
비트맵은 문자 충돌이 있어 사용하지 않습니다. 분석과 변환 결과는
[`docs/korean-font.md`](docs/korean-font.md)에 기록합니다.

첫 가시성 PoC는 빈 글리프 `0x4CD`에 `한`을 표시해 본문 경로를 확인한 뒤,
첫 대사 전체를 18개 임시 한글 글리프로 교체했습니다. DuckStation에서 흰색
한글 두 줄과 주변 대화창이 정상 표시되는 것을 확인해 최소 가시성 게이트를
통과했습니다. 상세 내용은 [`docs/poc.md`](docs/poc.md)에 기록합니다.
현재 Galmuri11 교체 PoC의 정적 검증과 화면 확인 상태는
[`docs/galmuri11-font-poc.md`](docs/galmuri11-font-poc.md)에 기록합니다.

전체 한글 2,350자를 기존 폰트 테이블에 전상주시킬 RAM 공간은 없으므로, 한글
글리프는 Disc 1 Track 1 말미의 `LBA 255811..255960` 150섹터에 전용 폰트
팩으로 저장하고 런타임에는 화면 또는 텍스트 블록 단위 캐시에 필요한 글리프만
적재합니다. 이 저장 공간 결정은 유지하되, 텍스트 스트림에 `0x5xxx`/`0x7xxx`
같은 고상위 토큰을 직접 넣는 방식은 에뮬레이터 검증에서 폐기했습니다. 세부
계산과 폐기 근거는
[`docs/hangul-storage-encoding.md`](docs/hangul-storage-encoding.md)에 기록합니다.

고상위 토큰 훅 PoC는 두 반례를 남기고 폐기했습니다. `0x5xxx` 토큰은 이름/변수
표시 경로와 충돌해 화면에 한자 `司馬`가 반복됐고, `0x7xxx` 토큰은 원본 대사
RAM에는 남아도 렌더러 직전의 리맵/표시 버퍼 변환 단계에서 공백처럼 사라졌습니다.
따라서 다음 전략은 렌더러 말단 훅이 아니라 `ALLBIN.BIN + 0x54`의 원본 토큰이
`0x8001425A` 주변 표시 구조와 `0x8001426C` 주변 리맵 표로 변환되는 생산자
경로를 추적해, 엔진이 받아들이는 작은 로컬 토큰과 리맵 표를 한글 캐시에 연결하는
방식입니다. 폐기된 PoC 기록은
[`docs/cache-hook-poc.md`](docs/cache-hook-poc.md)에 기록합니다.
새 전략의 작업 단위와 통과 기준은
[`docs/remap-table-strategy.md`](docs/remap-table-strategy.md)에 기록합니다.

리맵/표시 버퍼 생성 경로 추적 PoC는 첫 대사 RAM 덤프에서
`[0x80061158] -> 0x8001426C -> 0x800A8054`와
`[0x80060FA0] -> 0x8001425A`를 재확인했고, 표시 커서 `0x22`가 첫 페이지
34개 u16 토큰을 모두 소비한 상태임을 도구로 고정했습니다. 또한
`0x800327B0`, `0x800327B8`, `0x800327E0`, `0x800327E8`,
`0x800328B8`, `0x800328C0`이 두 전역 포인터를 직접 소비하는 지점임을
정적 스캔으로 확인했습니다. 자세한 내용은
[`docs/remap-path-poc.md`](docs/remap-path-poc.md)에 기록합니다.

## 테스트

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/toolchain.py
.venv/bin/python scripts/mcp_probe.py
```

`mips_survey.py`를 사용하려면 분석용 의존성을 별도로 설치합니다.

```bash
.venv/bin/python -m pip install -r requirements-analysis.txt
```

`work/`는 분석 중 생성되는 임시 추출물과 덤프를 위한 경로이며 버전 관리 대상이
아닙니다.

## 역공학 MCP와 외부 도구

`mini-yonku-wgp2-kr`의 상보적 IDA/idalib/Ghidra 운용 방식을 PS1용으로
이식했습니다. 프로젝트 `.mcp.json`에는 `ida-pro-mcp`, `idalib-mcp`,
`ghidra`가 등록돼 있습니다. PS-X EXE load address, overlay 경계, MIPS
delay/load hazard, DuckStation GDB와 디스크 도구의 적용 범위는
[`docs/reverse-engineering-mcp.md`](docs/reverse-engineering-mcp.md)를
따릅니다.

현재 Mac에는 IDA Professional 9.4, Ghidra 12.1.2, DuckStation,
armips, mkpsxiso/dumpsxiso, xdelta3, Flips, FFmpeg와 vgmstream을
준비했습니다. SNES 전용
HiROM/65816/Mesen Lua/asar 코드는 가져오지 않았습니다.

## 원본 자료 및 저작권

이 저장소는 원본 게임 이미지, BIOS, 저작권이 있는 게임 데이터의 추출본을
배포하지 않습니다. 사용자는 자신이 적법하게 보유한 원본 매체를 준비해야 합니다.
최종 배포물은 원본 전체 이미지가 아닌 차이 패치 형태를 목표로 합니다.

## 작업 원칙

- 원본 ROM과 BIOS는 읽기 전용으로 취급합니다.
- 분석과 빌드는 가능한 한 스크립트로 재현할 수 있게 유지합니다.
- 추출 후 재조립 결과가 원본과 바이트 단위로 일치하는지 먼저 검증합니다.
- 화면에서 검증된 정보와 추정 내용을 구분해 기록합니다.
- 각 단계가 완료될 때마다 이 README의 진행 상황을 갱신합니다.
