# 디스크 1 초기 조사

대상은 `Future GPX Cyber Formula - Aratanaru Chousensha (Japan)` PS1판이다.
이 문서는 확인한 사실과 아직 검증되지 않은 가설을 구분한다.

## 확인한 사실

### 매체

- 디스크 1은 멀티 BIN/CUE 구성이다.
- 트랙 1은 `MODE2/2352` 데이터, 트랙 2~4는 CDDA 오디오다.
- 트랙 1은 602,020,272바이트, 255,961 raw sector다.
- 트랙 1 식별값:
  - CRC32: `725BA190`
  - MD5: `a33012953c1cc37ee472450377fb8ec8`
  - SHA-256: `35e43fba9c5ffc39ab805adbc42f13ec3198c888c1c1e9e651408409e041b2a9`
- 트랙 1의 PVD는 Mode 2 Form 1이며 ISO 9660 식별자 `CD001`가 유효하다.
- ISO 시스템 ID는 `PLAYSTATION`이다.
- ISO의 `DA_NA.DA`, `OP_BGM.DA`, `NONE.DA`는 각각 CDDA 트랙 2~4의 INDEX 01 LBA를 가리킨다.

### 부트 코드

- `SYSTEM.CNF`는 `SLPS_019.58;1`을 부트 대상으로 지정한다.
- `SLPS_019.58`은 유효한 `PS-X EXE`다.
- entry point: `0x80041C18`
- load address: `0x80030000`
- text size: `0x31000`
- 부트 EXE에는 ISO 주요 파일명이 연속된 테이블로 들어 있다. `ALLBIN.BIN` 검색/읽기
  래퍼는 `0x80048E3C`에서 시작하며 내부적으로 ISO 파일 검색 루틴
  `0x80048B38`을 호출한다.
- 부트 EXE는 Sony 라이브러리 문자열과 CD/GPU 디버그 문자열을 보존하고 있어 정적
  분석 앵커로 사용할 수 있다.

### BIOS

- 로컬 `scph1001.bin`은 524,288바이트다.
- MD5: `924E392ED05558FFDB115408C263DCCF`
- SHA-256: `71AF94D1E47A68C11E8FDB9F8368040601514A42A5A399CDA48C7D3BFF1E99D3`
- 이 BIOS는 디버깅 입력으로만 사용하고 저장소에 포함하지 않는다.

### ISO 주요 파일

| 파일 | 크기 | 현재 역할 판정 |
|---|---:|---|
| `SLPS_019.58` | 202,752 | 부트 로더/초기 실행 코드 |
| `ALLBIN.BIN` | 1,501,184 | MIPS 코드로 시작하는 주 실행/오버레이 후보 |
| `START.BIN` | 5,015,552 | 복합 게임 데이터 후보 |
| `OUTSIDE.BIN` | 1,857,536 | 복합 게임 데이터 후보 |
| `COURSE.BIN` | 9,576,448 | 코스/그래픽 데이터 후보 |
| `MACHINE.BIN` | 2,439,168 | 머신/그래픽 데이터 후보 |
| `CYBER_XA.STR` | 214,106,112 | XA 스트림 |
| `MOVIE.STR`, `MOVIE2.STR` | 87,367,680 / 70,297,600 | 영상 스트림 |

### 폰트 경로 1차 판정

- `SLPS_019.58`과 `ALLBIN.BIN`에서 직접 BIOS B-table 호출 스텁을 전수 검사했다.
- 확인된 B-table 함수 번호 집합에는 `0x51`과 `0x58`이 없다.
- 따라서 표준 `Krom2RawAdd` 직접 호출은 현재까지 발견되지 않았다.
- 이 결과는 **직접 호출 부재**만 증명한다. 함수 포인터 또는 별도 오버레이를 통한
  간접 호출 가능성은 아직 남아 있다.
- ISO 주요 파일을 구조 검증형 TIM 스캐너로 전수 검사했으나 표준 PS1 TIM은 0개다.
  그래픽은 원시 텍스처, 자체 컨테이너 또는 압축 블록이다.

### 자체 16비트 텍스트 스트림

- `ALLBIN.BIN`의 첫 84바이트(`0x0000..0x0053`)는 짧은 MIPS 함수 4개다.
- `0x0054`부터는 리틀엔디언 u16 토큰 스트림이 시작된다.
- 문자 후보는 주로 `0x0001..0x04xx`, 제어코드 후보는 `0x90xx`, 엔트리 종료자
  후보는 `0xFFFB`다.
- `0x0054..0x2A800`을 첫 대표 텍스트 구간으로 분리했다. `0x2A808`부터는 다시
  명확한 MIPS 함수 프롤로그가 등장한다.
- `ALLBIN.BIN` 전체에는 `0xFFFB`가 7,613회 존재한다. 코드·기타 데이터의 우연한
  일치를 제외해야 하므로 전량 엔트리 수로 아직 승격하지 않는다.
- 작품 고유명사의 Shift-JIS 검색이 실패한 이유는 이 자체 글리프 인덱스 방식으로
  설명된다.

첫 대표 구간은 `scripts/custom_text.py`로 종료자 포함 raw 바이트를 JSON에 보존하고,
JSON의 `raw_hex`를 이어 붙였을 때 원 구간과 완전히 같음을 검증한다. 문자표가 확정되기
전에는 토큰을 일본어로 추측 디코딩하지 않는다.

### 동적 부트 확인

- DuckStation 0.1-11580에서 디스크 1이 `SLPS-01958`로 식별되고 정상 부팅됐다.
- 에뮬레이터는 이미지를 NTSC-J로 판정했으며 부트 완료 시간은 약 1.46초였다.
- 로컬 SCPH-1001은 NTSC-U BIOS이므로 리전 불일치 경고가 발생했다. fast boot에서는
  실행되지만 일본 BIOS 의존 동작의 최종 검증 근거로 사용하지 않는다.
- GDB 서버가 `127.0.0.1:3333`에서 열리는 것까지 확인했다. RAM 대량 덤프 클라이언트는
  ACK 처리와 실행 중 읽기 안정화를 더 보강해야 한다.

## 현재 가설

- 대사 본문은 ISO 파일 안에 평문 Shift-JIS로 저장되지 않았다. 작품 고유명사의
  표준 Shift-JIS 바이트 검색이 실패했고, 일반 SJIS 스캐너 결과 대부분은 그래픽
  데이터의 오탐이었다.
- 가능한 설명은 자체 문자 인덱스, 압축된 스크립트, 프리렌더 그래픽, XA 음성 중심
  구성 중 하나 이상이다.
- `ALLBIN.BIN`은 MIPS 코드와 비코드 데이터가 섞인 복합 파일이다. 파일 전체를 하나의
  연속 실행 이미지로 간주하면 안 된다.
- 직접 BIOS 폰트 호출이 보이지 않으므로 자체 글리프/텍스처 경로의 가능성이 더 크다.

## 다음 판정 작업

1. `ALLBIN.BIN` 내부의 코드/데이터 세그먼트 경계를 판정한다.
2. 부트 EXE의 `ALLBIN.BIN` 읽기 래퍼 호출자와 GPU 업로드 경로를 연결한다.
3. 실제 게임 화면의 일본어 한 문장을 확보해 자체 인코딩/압축 검색의 기준 표본으로 쓴다.
4. 글리프 공급 경로가 자체 폰트인지 프리렌더 텍스처인지 확정한다.

## 재현 명령

```powershell
python scripts/psx_disc.py info --image <disc1-track1.bin> --hash
python scripts/psx_disc.py list --image <disc1-track1.bin>
python -m pip install --target work/pydeps -r requirements-analysis.txt
$env:PYTHONPATH = "work/pydeps"
python scripts/mips_survey.py work/disc1/SLPS_019.58
python scripts/mips_survey.py work/disc1/ALLBIN.BIN --base 0
```

## 2026-07-12 dialogue-state confirmation

- A user-driven playthrough reached the first visible dialogue and the state was
  preserved as `work/dialogue-screen.png` and `work/ram-dialogue.bin`.
- The visible text was
  `（ようやくここまできた…憧れの / チーム、「スゴウグランプリ」）`.
- Its first token is at `ALLBIN.BIN+0x54`, loaded at RAM `0x800A8054`.
- The live text-base pointer chain is
  `[0x80061158] -> 0x8001426C -> 0x800A8054`.
- The live u16 cursor chain is `[0x80060FA0] -> 0x8001425A`; its captured value
  was `0x22`, pointing at `0x800A8098`, immediately after the displayed page.
- `0xFFFB` is a line boundary in this sample. `0x8000` stops at the end of the
  displayed two-line page. Other control values remain intentionally unnamed.
- The token interpreter/update candidate begins at `0x80032D3C`. Token fetches
  occur at `0x800339A0` and `0x80033AC0`.
- Ordinary glyph tokens also call `0x80041018`, but this is **not yet the font
  renderer**. It indexes a six-byte-per-token table at `0x800512EC` and selects
  a CD audio range synchronized with the token.
- The downstream routine at `0x80043444` converts three BCD MSF bytes to an
  LBA. The table's three signed halfwords are used as an in-sector offset plus
  start/end multiples of 32 relative to the base MSF at `0x80057608`.
- The visual glyph renderer therefore remains a separate path to identify.
- The first 29 verified glyph mappings are recorded in `data/glyph-map.json`.
  They are evidence-backed only by the captured screen; unmapped tokens remain
  explicit placeholders.

## Fixed localization requirement: protagonist name

- The Korean patch will use the canonical protagonist name **시바 세이치로**.
- The original name-entry flow does not need arbitrary Korean character input.
- The patched name screen should expose only **시바 세이치로**, while later
  name-variable rendering must continue to work with that fixed value.
