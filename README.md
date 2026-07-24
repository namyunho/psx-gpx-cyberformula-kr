# 신세기 GPX 사이버 포뮬러 새로운 도전자 — 한국어 패치 프로젝트

PlayStation용 일본 게임 **《신세기 GPX 사이버 포뮬러 새로운 도전자》** Disc 1의
한국어 팬 번역 패치 프로젝트입니다. 원본 디스크 조사부터 역공학, 폰트,
텍스트·그래픽 추출, 번역, 재삽입, 패치 빌드와 실행 검증까지 재현 가능한
파이프라인으로 연결하는 것을 목표로 합니다.

> ⚠️ **법적 고지**: 이 저장소에는 원본 BIN/CUE, BIOS, 추출한 게임 자산,
> RAM/VRAM 덤프 또는 패치된 전체 이미지가 포함되지 않습니다. 사용자는 적법하게
> 보유한 원본을 직접 준비해야 하며, 최종 배포물은 원본 전체가 아닌 차분 패치만을
> 목표로 합니다.

## 대상 디스크

| 항목 | 값 |
|---|---|
| 플랫폼·범위 | PlayStation, 일본판 Disc 1 |
| 부트 실행 파일 | `SLPS_019.58` |
| Track 1 | `MODE2/2352` 데이터, 602,020,272바이트, 255,961 sector |
| Track 2~4 | CDDA 오디오 |
| Track 1 CRC32 | `725BA190` |
| Track 1 MD5 | `a33012953c1cc37ee472450377fb8ec8` |
| Track 1 SHA-256 | `35e43fba9c5ffc39ab805adbc42f13ec3198c888c1c1e9e651408409e041b2a9` |

기본 원본 위치:

```text
roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1).cue
roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1) (Track 1).bin
```

멀티 BIN/CUE의 오디오 트랙도 같은 디렉터리에 두고 CUE의 참조 관계를 유지합니다.
다른 위치는 `PSX_DISC1_CUE`, `PSX_DISC1_TRACK1` 환경 변수로 재정의할 수
있습니다. 지원 원본의 경로와 식별값은
[`config/original-media.json`](config/original-media.json)이 관리합니다.

## 배포 상태

현재 공개 패치는 없습니다. Disc 1 구조 분모와 추출·폰트 PoC는 확정됐지만,
전체 대사 번역·재삽입, 베이크드 그래픽 현지화, 통합 빌드와 전편 QA는 아직
진행 전입니다.

## 진행 상태

| 단계 | 상태 |
|---|---|
| 원본 매체 식별·무결성 | ✅ 완료 — 멀티트랙 CUE와 Track 1 크기·CRC32·MD5·SHA-256 고정 |
| PS-X EXE·파일 로더·schedule 역공학 | ✅ 완료 — 19개 파일 record, 164개 descriptor, 11개 scheduled 파일 분할 |
| Disc 1 전량 추출·압축해제 | ✅ 완료 — 1,935 state 재결합, XA·VAB·CDDA·MDEC 검증 |
| 글꼴 렌더 스트림 모집단 | ✅ 완료 — 증거가 있는 5,843개 스트림과 도달 등급 분류 |
| 일본어 글리프 대응표 | ✅ 완료 — primary 1,229자와 alternate 1,484자 전 슬롯, JIS 순서·수정 아틀라스 교차 검증 |
| 본문·UI 폰트 구조 | ✅ 완료 — primary/alternate 14×14, 3bpp, 74바이트 record |
| Galmuri11 사용 프로필 | ✅ 완료 — TTF 12px, 실제 최대 11×11 잉크, 14×14 셀 배치 |
| 최초 한글 가시성 PoC | ✅ 통과 — 역사적 Galmuri14 시험으로 DuckStation 본문 렌더 경로 확인 |
| Galmuri11 첫 대사 PoC | 🟡 정적 검증 통과 — 18자 삽입과 raw Track diff 확인, 실제 화면 최종 확인 대기 |
| 한글 저장·리맵 전략 | 🚧 조건부 확정 — Track 1 말미 폰트 팩과 화면 단위 캐시, 생산자 리맵 구현 필요 |
| 그래픽 현지화 분모 | ✅ 구조 완료 — 1,739개 그래픽 관련 state 역할 분류 |
| 베이크드 문자 소비 경로 | 🚧 진행 전 — 1,463개 검토 state를 화면→VRAM→RAM→저장 위치에 연결해야 함 |
| 전체 대사 추출 작업본 | ✅ 원문 판독 완료 — 대사 5,783개와 UI 60개 미매핑 0, 번역 필드는 전부 비움 |
| 전체 번역·재삽입 | ⏳ 예정 |
| 통합 빌드·실행 QA·차분 배포 | ⏳ 예정 |

> **현재 판정 요약**: 구조 분석, 원본 유래 데이터의 무손실 추출과 일본어
> 글리프 판독은 완료됐습니다. 번역 자산, 런타임 리맵과 재삽입 검증은 아직
> 남아 있으므로 한글 패치 완성으로 판정하지 않습니다.

## 확정된 작업 블록

| 시스템 | 규모 | 확정 내용 |
|---|---:|---|
| ISO·scheduled 컨테이너 | ISO 파일 16개, scheduled 파일 11개, state 1,935개 | 원본 경계·해시와 state 재결합 일치 |
| 글꼴 렌더 스트림 | 총 5,843개 | 스토리 4,022, 일반 레이스 68, 진단/시험 1,080, 휴면 613, UI 60 |
| 대사 협업 작업본 | 대사 5,783개, UI 60개 | 가역 원문·안정 ID·보호 필드와 빈 완역본/축약본을 JSON으로 분리 |
| 텍스트 저장 | little-endian u16 | 커스텀 글리프 index, `FFFB` 정렬/줄 경계, `8000` 페이지 대기 |
| 폰트 공급자 | primary 1,229 slot, alternate 1,484 slot | 두 표 모두 14×14, 3bpp, 글리프당 74바이트 |
| 초상 | 625 block | 32바이트 CLUT + 48×56 4bpp |
| 그래픽 | 관련 state 1,739개 | 베이크드 문자 검토 1,463, 폰트 2, 초상 24, 비그래픽 COURSE 250 |
| 오디오·영상 | XA 33, VAB 81 bank/1,663 sample, CDDA 3, MDEC 2 | PCM16 WAV·FFV1로 해제하고 frame·해시 검증 |
| Galmuri11 | 한글 문자표 2,350자 | TTF 12px 결과가 2,350개 고유 자형을 유지하고 14×14 셀 밖 픽셀 0개 |
| 첫 대사 PoC | 한글 18자, 변경 763바이트 | `START.BIN`·`ALLBIN.BIN` 변경과 9개 raw LBA 쓰기가 선언 범위와 일치 |

일반 플레이 경로는 4,150개 스트림이며, 진단/시험 경로까지 포함하면
5,230개입니다. Disc 1 정적 실행 코드에서 로더 도달이 확인되지 않은 613개는
삭제하거나 번역 대상으로 단정하지 않고 휴면 자산으로 보존합니다.

## 번역판 고정 방침

- 주인공의 한국어 이름은 **시바 세이치로**로 고정합니다.
- 범용 한글 이름 입력기를 새로 만들지 않습니다.
- 이름 선택 화면은 고정 이름만 선택할 수 있도록 단순화합니다.
- 이후 대사의 이름 변수도 같은 이름을 정상 표시해야 합니다.
- 원문, 의미를 보존한 완역본, 표시 한도 때문에 승인된 축약본을 서로 덮어쓰지
  않고 별도 필드로 보존합니다.
- 미확정 글리프·제어 토큰·도달 경로를 임의 추정하거나 조용히 건너뛰지 않습니다.

## 저장소 구조

```text
config/
  original-media.json   지원 원본 식별값과 기본 로컬 경로
  font-profile.json     Galmuri11 입력 해시와 14×14 변환 프로필
data/
  dialogue-extraction-schema.json
                        대사 협업 작업본 JSON Schema
  glyph-map.json        primary·alternate 전체 일본어 글리프 대응표
docs/
  *.md                  구조 기준선·추출·폰트·PoC·역공학 판정 기록
fonts/galmuri11/
  OFL.txt               SIL OFL 1.1 전문
  *.ttf, *.bin, *.json  허용된 Galmuri11 원본과 문자표
scripts/
  *.py                  조사·추출·대사 작업본·디코드·PoC·검증 도구
  ida/                  PS-X EXE용 IDA loader 보조 스크립트
tests/
  test_*.py             컨테이너·폰트·추출·재삽입 회귀 검사
roms/                   비커밋 원본 BIN/CUE
work/                   비커밋 추출물·DB·RAM·분석 보고서·PoC 이미지
tmp/                    비커밋 임시 캡처
```

## 문서 정본

| 문서 | 역할 |
|---|---|
| [수정 전 역공학 기준선](docs/reverse-engineering-baseline.md) | 대상 리비전, 로더·schedule·텍스트·폰트·초상·그래픽 분모의 현재 결론 |
| [Disc 1 전량 추출·압축해제](docs/disc1-extraction.md) | 추출 경계, 출력 구조, 압축해제 수량과 전량 검증 |
| [Disc 1 대사 추출 작업본](docs/dialogue-extraction.md) | 번역 없는 가역 JSON, 협업 필드 정책, 17×3 대사창과 저장 공간 판정 |
| [그래픽 문자 인벤토리](docs/graphics-text-inventory.md) | 베이크드 문자 검토 state와 편집 승격 조건 |
| [폰트 포맷](docs/font-format.md) | primary/alternate 14×14 3bpp 공급자와 렌더러 |
| [Galmuri11 사용 글꼴](docs/korean-font.md) | 12px 입력, 11×11 잉크, 14×14 셀 프로필과 라이선스 |
| [Galmuri11 본문 PoC](docs/galmuri11-font-poc.md) | 첫 대사 정적 삽입·raw Track 검증과 남은 화면 확인 |
| [한글 저장·인코딩](docs/hangul-storage-encoding.md) | 폰트 팩 저장 위치, 캐시와 리맵 전략의 제약 |
| [리맵 표 전략](docs/remap-table-strategy.md) | 고상위 토큰 폐기 뒤의 생산자 리맵 설계 |
| [리맵 경로 추적 PoC](docs/remap-path-poc.md) | 표시 구조·리맵 표 포인터와 다음 런타임 계측 지점 |
| [역공학 MCP 운용](docs/reverse-engineering-mcp.md) | IDA Pro·idalib·Ghidra의 상호보완적 사용과 PS1 import 규칙 |
| [GPU 업로드 원본 추적](docs/gpu-upload-source-tracing.md) | 화면→VRAM→DMA2/RAM→저장 자산을 연결하는 미실행 조사 절차 |

역사적 첫 조사와 폐기된 설계는 현재 정본과 구분해
[`docs/initial-survey.md`](docs/initial-survey.md),
[`docs/poc.md`](docs/poc.md),
[`docs/cache-hook-poc.md`](docs/cache-hook-poc.md)에 보존합니다.

## 로컬 준비

```bash
git clone https://github.com/namyunho/psx-gpx-cyberformula-kr.git
cd psx-gpx-cyberformula-kr

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-analysis.txt

.venv/bin/python scripts/original_media.py prepare
.venv/bin/python scripts/original_media.py paths
.venv/bin/python scripts/original_media.py verify --cue
```

`prepare`는 원본을 내려받지 않습니다. 기본 경로를 만들고 사용자가 보유한 원본의
배치 위치만 안내합니다.

## 추출·분석·검증

```bash
# Disc 1 전량 추출·압축해제·검증
.venv/bin/python scripts/extract_disc1_assets.py
.venv/bin/python scripts/decode_disc1_streams.py
.venv/bin/python scripts/verify_disc1_extraction.py

# 구조 보고서 재생성
.venv/bin/python scripts/psx_layout.py \
  --output work/analysis/disc1-layout.json
.venv/bin/python scripts/psx_text_inventory.py \
  --output work/analysis/disc1-text.json
.venv/bin/python scripts/build_japanese_glyph_map.py
.venv/bin/python scripts/extract_disc1_dialogue.py
.venv/bin/python scripts/psx_font_inventory.py \
  --output work/analysis/disc1-fonts.json
.venv/bin/python scripts/psx_portrait_inventory.py \
  --output work/analysis/disc1-portraits.json
.venv/bin/python scripts/psx_graphics_scope.py \
  --output work/analysis/disc1-graphics-scope.json

# 전체 회귀 테스트와 로컬 도구 진단
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/toolchain.py
.venv/bin/python scripts/mcp_probe.py
```

현재는 최종 한글판을 만드는 통합 빌드 진입점이 없습니다. PoC 빌드 명령과
DuckStation 전용 이미지의 제한은
[`docs/galmuri11-font-poc.md`](docs/galmuri11-font-poc.md)를 따릅니다.

## 도구체인

- **Python 3** — 원본 검증, ISO/raw sector 처리, schedule·텍스트·폰트·그래픽
  조사, 추출·디코드와 PoC 검증.
- **IDA Professional 9.4 / `ida-pro-mcp` / `idalib-mcp`** — 정확한 MIPS
  instruction, 함수 경계, xref와 반복 질의.
- **Ghidra 12.1.2 / GhidraMCP** — 긴 상태 분기와 포인터 전달 디컴파일
  교차검증.
- **DuckStation** — 실제 게임 진행, RAM·overlay·화면 소비 검증. GUI 조작과
  Lua 실행이 필요하면 자동화하지 않고 사용자에게 요청합니다.
- **armips** — 향후 MIPS R3000A 훅 조립. 생성 코드는 독립 디스어셈블로
  delay slot과 분기 대상을 검산합니다.
- **mkpsxiso / dumpsxiso** — CUE·ISO 구조의 독립 대조와 향후 재구성.
- **FFmpeg / vgmstream** — MDEC·XA·VAB·CDDA 해제와 frame/sample 검증.
- **xdelta3 / Flips** — 최종 차분 패치 생성 후보. 아직 배포 산출물은 없습니다.

`mini-yonku-wgp2-kr`에서 사용한 IDA/idalib/Ghidra 상호보완 방식을 PS1의
PS-X EXE, overlay, MIPS delay/load hazard, Mode 2 raw sector 조건에 맞게
수정했습니다. SNES용 HiROM·65816·Mesen Lua·asar 코드는 이식하지 않았습니다.

## 기여·에이전트 협업

작업 전 [`AGENTS.md`](AGENTS.md)를 먼저 읽어야 합니다.

핵심 불변식:

- 원본·추출물·패치된 전체 이미지 비커밋
- 지원 원본의 강한 해시 확인 후 작업
- ISO 파일, raw sector, PS-X EXE 파일 offset, runtime 주소의 좌표계 분리
- 추출·재조립 round-trip 우선
- IDA Pro와 Ghidra를 대체 관계가 아닌 상호보완 도구로 사용
- 화면·RAM에서 검증된 사실과 정적 가설을 구분
- 최종 변경은 불변 원본에 대한 예상 쓰기 범위로 전부 설명
- 인코딩 누락, 표시 범위 초과와 미확정 토큰을 빌드 오류로 처리

## 라이선스

- 프로젝트 도구·문서: 저장소 소유자에게 권리가 있습니다.
- Galmuri11: SIL Open Font License 1.1. 자세한 고지와 전문은
  [`fonts/galmuri11/OFL.txt`](fonts/galmuri11/OFL.txt)를 따릅니다.
- 원본 게임의 모든 권리는 원저작권자에게 있습니다. 이 프로젝트는 비영리 팬
  번역 작업이며 원본 게임 데이터를 배포하지 않습니다.
