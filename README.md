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
전체 대사 번역 검토·축약, 베이크드 그래픽 현지화와 전편 QA는 아직
진행 중입니다. `u00..u34`의 직접·무포인터 대사, 고정 이름, 이름 등록 UI,
미니게임·코스·머신 설정 폰트 대사 391개까지 현재 식별한 그래픽 제외
폰트 문자열을 담은 비배포 개발 이미지를 생성했습니다. 정적 검증은
통과했지만 새 특수 화면 범위의 사용자 실행 검증은 남아 있습니다.

## 진행 상태

| 단계 | 상태 |
|---|---|
| 원본 매체 식별·무결성 | ✅ 완료 — 멀티트랙 CUE와 Track 1 크기·CRC32·MD5·SHA-256 고정 |
| PS-X EXE·파일 로더·schedule 역공학 | ✅ 완료 — 19개 파일 record, 164개 descriptor, 11개 scheduled 파일 분할 |
| Disc 1 전량 추출·압축해제 | ✅ 완료 — 1,935 state 재결합, XA·VAB·CDDA·MDEC 검증 |
| 글꼴 렌더 스트림 모집단 | 🚧 확대 조사 — 직접 포인터/UI 5,843개, `u00..u21` 무포인터 83개, 특수 화면 391개 확인; `u22..u34` 무포인터 전수 재감사 필요 |
| 일본어 글리프 대응표 | ✅ 완료 — primary 1,229자와 alternate 1,484자 전 슬롯, JIS 순서·수정 아틀라스 교차 검증 |
| 본문·UI 폰트 구조 | ✅ 완료 — primary/alternate 14×14, 3bpp, 74바이트 record |
| Galmuri11 사용 프로필 | ✅ 완료 — TTF 12px, 실제 최대 11×11 잉크, 14×14 셀 배치 |
| 최초 한글 가시성 PoC | ✅ 통과 — 역사적 Galmuri14 시험으로 DuckStation 본문 렌더 경로 확인 |
| Galmuri11 본문 출력 | ✅ 실행 확인 — 첫 대사 PoC 이후 전체 대사 개발 빌드에서도 14×14 셀 렌더 경로 확인 |
| 한글 저장·인코딩 | ✅ 정적 경로 확정 — 현재 전체 대사 빌드의 998자를 primary 1,229슬롯에 배치하고 대사 토큰 직접 재인코딩, 훅 불필요 |
| 고정 주인공명·화자명 | ✅ 실행 확인 — `시바` 2칸+`세이치로` 4칸과 화자명·용어집 표기가 실제 화면에서 정상 표시 |
| 그래픽 현지화 분모 | ✅ 구조 완료 — 1,739개 그래픽 관련 state 역할 분류 |
| 베이크드 문자 소비 경로 | 🚧 진행 전 — 1,463개 검토 state를 화면→VRAM→RAM→저장 위치에 연결해야 함 |
| 대사 추출 작업본 | 🚧 직접 대사 5,783개, `u00..u21` 무포인터 83개, 이름 등록 UI 60개와 특수 화면 391개 원문 보호 기준선 확보 |
| 후보 번역 레이아웃 감사 | 🚧 직접 대사 5,783개 기계 배치 가능·차단 0 — 단어 분할 16건, 동일 원문 표기 후보 63건·용어집 후보 71건 사람 검토 필요 |
| 특수 화면 폰트 번역 | 🚧 391개 정적 주입 — 미매핑·빈값·고정 슬롯 초과·보호 필드 충돌 0, 사용자 실행 검토 필요 |
| 이름 등록 폰트 UI | 🚧 고정 리터럴 4개 정적 주입 완료 — 입력 팔레트·런타임 버퍼 56개 원본 보존, 실행 전수 검토 필요 |
| 전체 대사 재삽입 개발 이미지 | 🚧 `u00..u34` 직접+무포인터 5,866개와 특수 화면 391개 정적 주입 — 기존판은 제2장 종료까지 사용자 진행 확인, 새 특수 화면 통합판은 실행 검증 필요 |
| 전체 번역·재삽입 | 🚧 초벌 후보 상태 — 의미·용어·자연스러운 줄바꿈과 전편 실행 QA 필요 |
| 통합 빌드·실행 QA·차분 배포 | ⏳ 예정 |

> **현재 판정 요약**: 원본 유래 데이터의 무손실 추출, 일본어 글리프 판독과
> 정적 한글 글꼴·직접 인코딩 경로는 완료됐습니다. 다만 기존 대사 작업본이
> 직접 포인터 대상만 수집해 물리 스트림 안의 무포인터 연속 페이지를 누락한
> 사실이 확인돼 텍스트 모집단 판정을 다시 열었습니다. 현재는
> `u00..u21`에서 무포인터 83개를 추가했고, 별도 소비자를 쓰는 `u38/u43`의
> 미니게임·코스·머신 설정 391개도 분리해 정적 주입했습니다. unit 공용 arena 재배치
> 방식은 `u00`과 테스트 주행 `u21`에서 구조 실험을 통과했고, 같은 정적
> 불변식으로 만든 `u00..u34` 개발 이미지는 사용자가 제2장 종료까지 진행해
> 프리즈가 없음을 확인했습니다. 이는 이후 장·모든 분기·특수 화면의 전수
> 통과를 뜻하지 않습니다. 특수 화면 통합판은 아직 사용자 실행 검증 전이고,
> 번역은 기계 후보와 수작업 교정이 섞여 있으므로 한글 패치
> 완성으로 판정하지 않습니다.

## 확정된 작업 블록

| 시스템 | 규모 | 확정 내용 |
|---|---:|---|
| ISO·scheduled 컨테이너 | ISO 파일 16개, scheduled 파일 11개, state 1,935개 | 원본 경계·해시와 state 재결합 일치 |
| 직접 포인터 대상 글꼴 스트림 | 총 5,843개 | 스토리 4,022, 테스트 주행 68, 실제 경기 914, 경기 내장 메시지 779, 이름 등록 UI 60 |
| 무포인터 연속 페이지 | `u00..u21` 83개 | 선택 29, 대사 54; 원문 제어 셸과 안정 ID를 보존하고 한국어 정본 분리 |
| 특수 화면 폰트 문자열 | 391개 | `u38` 미니게임 322, `u43` 코스 57·머신 설정 12; 그래픽 버튼·라벨 제외 |
| 통합 폰트 편집기 | 6,298행 | 직접 대사, 무포인터, 특수 화면, UI 리터럴 4, 고정 이름·화자명 36을 원본별로 안전 저장 |
| 텍스트 저장 | little-endian u16 | 커스텀 글리프 index, `FFFB` 정렬/줄 경계, `8000` 페이지 대기 |
| 폰트 공급자 | primary 1,229 slot, alternate 1,484 slot | 두 표 모두 14×14, 3bpp, 글리프당 74바이트 |
| 초상 | 625 block | 32바이트 CLUT + 48×56 4bpp |
| 그래픽 | 관련 state 1,739개 | 베이크드 문자 검토 1,463, 폰트 2, 초상 24, 비그래픽 COURSE 250 |
| 오디오·영상 | XA 33, VAB 81 bank/1,663 sample, CDDA 3, MDEC 2 | PCM16 WAV·FFV1로 해제하고 frame·해시 검증 |
| Galmuri11 | 한글 문자표 2,350자 | TTF 12px 결과가 2,350개 고유 자형을 유지하고 14×14 셀 밖 픽셀 0개 |
| 첫 대사 PoC | 한글 18자, 변경 763바이트 | `START.BIN`·`ALLBIN.BIN` 변경과 9개 raw LBA 쓰기가 선언 범위와 일치 |
| 전체 대사 비배포 빌드 | unit `u00..u34`, 직접+무포인터 5,866개, 정적 맵 998자 | 453개 raw sector Expected Write·EDC/ECC 검증, 제2장 종료까지 사용자 진행 확인 |
| 그래픽 제외 전체 폰트 빌드 | 위 5,866개+특수 화면 391개, primary 미매핑 0 | 469개 raw sector Expected Write·EDC/ECC 검증, 특수 화면 실행 검토 필요 |

정상 경기 선택 코드는 현재 경기 상태 `0..13`에 21을 더해 `u21..u34`를
고르므로, 직접 포인터 대상 대사 5,783개는 모두 정상 실행 후보 경로다.
내용상 `u21`은 입단 직후 테스트 주행이며 제1장 진입 후 실제 첫 경기는
`u22`다. 이 수치는 포인터 없는 연속 페이지를 포함한 최종 페이지 수가 아니다.

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
  translations/         한국어 정본, 용어집, 고정 이름과 UI·특수 화면 번역
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
| [미니게임·코스·머신 설정 폰트 문자열](docs/special-screen-font-text.md) | `u38/u43` 391개 소비자·추출·외부 AI 병합과 고정 슬롯 정적 주입 |
| [그래픽 문자 인벤토리](docs/graphics-text-inventory.md) | 베이크드 문자 검토 state와 편집 승격 조건 |
| [폰트 포맷](docs/font-format.md) | primary/alternate 14×14 3bpp 공급자와 렌더러 |
| [Galmuri11 사용 글꼴](docs/korean-font.md) | 12px 입력, 11×11 잉크, 14×14 셀 프로필과 라이선스 |
| [Galmuri11 본문 PoC](docs/galmuri11-font-poc.md) | 첫 대사 정적 삽입·raw Track 검증과 남은 화면 확인 |
| [한글 저장·인코딩](docs/hangul-storage-encoding.md) | primary 1,229슬롯 정적 맵과 직접 대사 인코딩 |
| [캐릭터 이름과 고정 주인공명](docs/character-name-layout.md) | `시바/세이치로` 2+4 슬롯, 이름 화면·재표시·화자명 34개 안전 삽입 |
| [리맵 표 전략](docs/remap-table-strategy.md) | 후속 분석에서 폐기된 역사적 설계 |
| [리맵 경로 추적 PoC](docs/remap-path-poc.md) | 텍스트 상태 필드 판정을 남긴 역사적 PoC |
| [챕터 1 비배포 디스크 빌드](docs/chapter01-disc-build.md) | 정적 폰트·u00/u21 대사·이름·raw sector 삽입과 EDC/ECC 검증 |
| [대사 런타임 검증 기준선](docs/dialogue-runtime-findings.md) | 고정 주소 판정, 초상화·이름 제어 손상, 반각 검토, u21·선택지 후속 과제 |
| [대사별 검증 안전 슬롯](docs/dialogue-safe-slots.md) | 5,783개 고정 원위치 바이트 경계, 생성 JSON·CSV와 엄격 보호 정책 |
| [unit 공용 대사 arena](docs/unit-dialogue-pool-experiment.md) | u00/u21 전수 포인터 재연결, 공용 용량과 실행 검증 결과 |
| [`u00..u34` 전체 대사 비배포 빌드](docs/full-dialogue-nonrelease-build.md) | 직접+무포인터 5,866개, 이름·UI, 453 sector 검증과 제2장 종료 관측 |
| [그래픽 제외 전체 폰트 문자열 비배포 빌드](docs/all-font-text-nonrelease-build.md) | 전체 대사·이름·UI·특수 화면 391개, 글꼴 완전성과 469 sector 검증 |
| [프로젝트 진행 요약](docs/project-progress-summary.md) | 원본 조사부터 현재 통합 비배포 빌드와 남은 작업까지의 전체 작업 요약 |
| [통합 폰트 번역 편집기](docs/dialogue-layout-editor.md) | 본편·무포인터·미니게임·코스·머신 설정·UI·이름을 원본별로 안전 저장하는 검수 GUI |
| [Git 작업 흐름](docs/git-workflow.md) | `main`과 목적별 단기 브랜치, 검증·병합·태그 정책 |
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
.venv/bin/python scripts/extract_pointerless_pages.py
.venv/bin/python scripts/extract_special_screen_text.py
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

그래픽을 제외한 통합 폰트 번역 편집기와 특수 화면 번역 검사는 다음 명령으로
실행합니다.

```bash
.venv/bin/python scripts/dialogue_layout_editor.py --check
.venv/bin/python scripts/import_special_screen_translation_batches.py --check
.venv/bin/python scripts/dialogue_layout_editor.py
```

macOS에서는 저장소 최상위의 `대사-편집기.command`를 더블클릭해 같은
편집기를 열 수 있습니다. 특수 화면 `-ko` 배치가 없는 환경에서는 이미
병합된 `data/translations/disc1-special-screen-ko.json`을 정본으로
사용하며, 배치 재병합 명령은 실행할 필요가 없습니다.

실행 검증을 통과한 `u00/u21` 기준 빌드는 다음 순서로 재생성합니다.

```bash
.venv/bin/python scripts/audit_dialogue_reinsertion.py
.venv/bin/python scripts/build_dialogue_chapter_patch.py \
  --start-bin work/extracted/disc1/iso/START.BIN \
  --allbin work/extracted/disc1/iso/ALLBIN.BIN \
  --unit 0,21 \
  --placement-policy unit-shared-pool \
  --output-dir work/build/dialogue-u00-u21-unit-shared-pool
.venv/bin/python scripts/build_character_name_patch.py \
  --file-build-dir work/build/dialogue-u00-u21-unit-shared-pool \
  --output-dir work/build/dialogue-u00-u21-unit-shared-pool-names
.venv/bin/python scripts/build_ui_translation_patch.py \
  --file-build-dir work/build/dialogue-u00-u21-unit-shared-pool-names \
  --output-dir work/build/dialogue-u00-u21-unit-shared-pool-names-ui
.venv/bin/python scripts/build_dialogue_chapter_disc.py \
  --file-build-dir work/build/dialogue-u00-u21-unit-shared-pool-names-ui \
  --output-dir work/build/dialogue-u00-u21-unit-shared-pool-names-ui-disc
```

실행 범위와 출력 CUE/BIN은
[`docs/chapter01-disc-build.md`](docs/chapter01-disc-build.md)를 따릅니다.
빌더는 번역 후보의 안정 ID와 u00/u21의 고정 참조 카탈로그를 검증하고,
모든 대사·무포인터 페이지·이벤트 포인터를 unit 안에서 함께 재배치합니다.
개별 원본 슬롯은 초과할 수 있지만 unit의 원본 대사 스트림 총량은 넘을 수
없고, 줄당 17글리프·페이지당 3줄 제한은 별도로 유지합니다. 이 경로는 u00
시작부터 u21의 분기와 종료까지 사용자 실행 검증을 통과했습니다. 다른
unit은 자체 참조 카탈로그와 실행 검증을 완료하기 전까지 공용 재배치
대상으로 자동 승격하지 않습니다. primary 글꼴의 `0x000..0x045`,
`0x0E4..0x0E5`는 영문·숫자·특수문자 보호 슬롯으로 예약되어 한글 배정에
사용되지 않습니다.

현재의 `u00..u34` 그래픽 제외 전체 폰트 개발 이미지는 다음 단계를
추가해 생성합니다.

```bash
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

원본 Track 1과 같은 602,020,272바이트이며 SHA-256은
`66025f1527a85b459cc09ea4e3b6750de3db82536df2e7d05f140d37cfea1757`다.
469개 raw sector Expected Write와 EDC/ECC를 검증했다. 이 해시는 로컬
회귀 식별값이지 배포 파일이 아니며, 전체 BIN/CUE는 Git에 커밋하지
않습니다.

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
