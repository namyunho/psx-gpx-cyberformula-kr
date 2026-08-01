# PS1 역공학 도구와 MCP 환경

이 문서는 `mini-yonku-wgp2-kr`에서 검증한 IDA/idalib/Ghidra 상보 운용을 이
프로젝트의 PlayStation·MIPS R3000A·PCSX-Redux 흐름에 맞게 옮긴 기록이다.
SNES 65816, HiROM 주소 변환, Mesen2 Lua, asar 설정은 가져오지 않는다.

## 설치 기준선

2026-07-24 현재 이 Mac에서 다음 구성을 확인했다.

| 도구 | 설치 상태 | 역할 |
|---|---|---|
| IDA Professional 9.4 | 설치됨 | GUI 분석, 함수·xref·타입·바이트 확인 |
| ida-pro-mcp 2.0.0 | 설치됨 | IDA GUI 브리지와 headless idalib MCP |
| Ghidra 12.1.2 / OpenJDK 21 | 설치됨 | MIPS 디컴파일 교차검증 |
| PCSX-Redux | 설치됨 | 실행 검증, GDB 서버, Lua API, VRAM 뷰어·워치포인트 |
| Kaitai Struct Compiler 0.11 | 설치됨 | 바이너리 형식 선언과 parse/build 왕복 검증 |
| armips 0.11.0 (`2d7f351`) | 소스 빌드 | MIPS R3000 코드 조립과 심볼 출력 |
| mkpsxiso/dumpsxiso 2.30 | 공식 macOS 배포본 | 디스크 구조 덤프·재구성 교차검증 |
| xdelta3 3.2.0 / Flips | 설치됨 | 배포용 차분 패치 생성·역적용 |

일본판 실행용 `SCPH5500.BIN`은 로컬에만 두고 PCSX-Redux에서 선택한다. BIOS
파일과 에뮬레이터 설정은 저장소로 복사하지 않는다.

armips는 2026-07-07의 공식 `master` 커밋
`2d7f351e640ec260b43943f07a00c57211940378`을
`~/tools/armips`에 빌드하고 `~/.local/bin/armips`로 연결했다.
mkpsxiso는 공식 v2.30 Darwin 아카이브를
`~/tools/mkpsxiso/2.30`에 설치했다.

전체 상태는 프로젝트 가상환경에서 확인한다.

```bash
.venv/bin/python scripts/toolchain.py
```

원본까지 준비됐는지를 배포 전제 수준으로 확인하려면 다음을 쓴다.

```bash
.venv/bin/python scripts/toolchain.py --require-media
```

## MCP 서버

프로젝트 범위 서버는 루트 `.mcp.json`에 등록했다.

| 서버 | 동작 조건 | 우선 용도 |
|---|---|---|
| `ida-pro-mcp` | IDA GUI에서 대상 DB를 열고 플러그인 HTTP 서버 실행 | 사람과 같은 DB를 보며 조사 |
| `idalib-mcp` | GUI 불필요, 동일 IDB 동시 개방 금지 | 반복 disasm·xref·바이트 질의 |
| `ghidra` | Ghidra CodeBrowser와 GhidraMCP 확장 실행 | 디컴파일과 긴 제어 흐름 대조 |

MCP 클라이언트가 프로젝트 설정을 새로 읽도록 재시작한 뒤 최초 연결 승인을
완료한다. `idalib-mcp`에는 `--unsafe`를 넣지 않았다. 현재 서버 수준 연결은
확인했으며, 열린 IDA 데이터베이스와 Ghidra 프로그램이 없는 상태에서는 세션·
인스턴스 목록이 빈 것이 정상이다.

세 서버의 stdio `initialize` handshake는 다음 명령으로 독립 확인한다. 이 검사는
GUI에 프로그램이 열려 있는지까지 증명하지 않는다.

```bash
.venv/bin/python scripts/mcp_probe.py
```

Codex는 사용자 범위 MCP/플러그인 설정으로 같은 서버를 사용할 수 있다.
Claude Code는 이 저장소의 `.mcp.json`을 사용한다. 두 클라이언트가 같은 IDB를
headless로 동시에 열지 않는다. 병렬 분석이 필요하면 원본에서 만든 서로 다른
IDB 사본을 `work/` 아래에 둔다.

## PS-X EXE와 overlay import

### PS-X EXE

`SLPS_019.58`의 확인된 값은 다음과 같다.

| 항목 | 값 |
|---|---:|
| entry | `0x80041C18` |
| load address | `0x80030000` |
| text size | `0x31000` |
| 파일 payload 시작 | `0x800` |

파일 오프셋과 runtime 주소 관계는 이 실행 파일의 text 범위에서만
`runtime = 0x80030000 + (file_offset - 0x800)`이다. `ALLBIN.BIN`이나 다른
overlay에 이 공식을 그대로 쓰지 않는다.

IDA가 PS-X EXE를 인식하면 little-endian MIPS로 로드하고 header의 load
address를 확인한다. raw import라면 `0x800` header를 제외한 payload를
`0x80030000`에 둔다. Ghidra raw import는 `MIPS:LE:32:default`를 사용하되,
같은 payload/base 조건을 직접 확인한다.

현재 idalib의 자동 open은 `SLPS_019.58`을 raw imagebase `0`으로 여는 것이
확인됐다. 따라서 새 PS-X EXE를 곧바로 `idb_open`하지 않는다. 먼저 IDA headless
loader fixup으로 payload를 header의 load address에 매핑한 DB를 만든다.

```bash
.venv/bin/python scripts/build_ida_db.py work/disc1/SLPS_019.58
```

출력은 `work/ida/SLPS_019.58.psx.i64`이며 원본 header의 entry/load/text size를
사용한다. 이 `.i64`를 `idalib-mcp`의 `idb_open` 입력으로 연다. health의
segment 목록에서 `TEXT` 실행 payload가 `0x80030000..0x80061000`에 있고 entry가
`0x80041C18`인지 확인하기 전에는 xref나 디컴파일 결과를 사용하지 않는다.

실제 생성 DB를 idalib로 다시 연 결과, `RAM/TEXT/RAM` 세 segment와 entry,
428개 함수가 인식됐고 PsyQ C runtime signature도 적용됐다. `0x800327A8`의
`0x80060FA0`·`0x80061158` 참조는 Capstone 기반
`scripts/mips_disasm.py` 결과와 일치했다.

### `ALLBIN.BIN`과 runtime module

`ALLBIN.BIN`은 코드와 u16 텍스트·기타 데이터가 섞여 있다. 파일 전체를 하나의
연속 MIPS segment로 가져오지 않는다. 먼저 PCSX-Redux GDB의 RAM 덤프와
`scripts/ram_map.py`로 적재 delta·범위를 확인하고, 현재 module의 실제 runtime
주소와 파일 범위를 분리한 뒤 해당 조각만 분석한다.

현재 unit 30, 35, 40, 42는 `scripts/wrap_psx_overlay.py`로 각각의 실제 load
address를 가진 조사용 PS-X EXE로 감싸 별도 IDA DB를 만들었다. Ghidra에도
unit 30, 35, 42를 별도 program으로 import했다. unit 30의 entry를 두 도구에서
독립 디컴파일한 결과 초기화와 `MoveImage` 계열 호출이 일치했다. 이처럼 동일
파일이라도 scheduled unit마다 base와 수명이 다르므로 DB를 합치지 않는다.

## 도구 선택 원칙

IDA/idalib과 Ghidra는 대체 관계가 아니다.

- 짧은 루틴, 직접 xref, 바이트와 반복 질의는 IDA/idalib을 먼저 쓴다.
- 포인터 전달, 상태 구조와 긴 분기 흐름이 읽기 어려우면 Ghidra 디컴파일로
  해당 함수만 대조한다.
- 정적 도구의 결과는 PCSX-Redux에서 실제 적재 module·레지스터·RAM 소비
  시점과 연결돼야 runtime 사실로 승격한다.
- 두 정적 도구가 같은 결과를 내더라도 잘못된 base, overlay 또는 코드/데이터
  경계를 공유했다면 독립 증거가 아니다.

MIPS R3000A에서는 특히 다음을 검산한다.

- branch/jump delay slot
- load delay와 hazard
- `$gp` 기준 데이터와 함수별 live register
- KSEG0/KSEG1 alias와 cache 상태
- self-modifying code나 RAM patch 뒤 instruction cache 갱신
- overlay가 다시 적재될 때 훅·데이터의 수명

`scripts/mips_disasm.py`는 선형 판독과 delay slot 표시를 제공한다. armips로
만든 패치의 독립 대조에 사용하되, 코드/데이터 경계와 제어 흐름은 IDA/Ghidra 및
runtime 관측으로 확정한다.

```bash
.venv/bin/python scripts/mips_disasm.py work/disc1/SLPS_019.58 \
  --address 0x800327A8 --count 0x120
```

## PCSX-Redux 동적 분석

기본 GDB endpoint는 `127.0.0.1:3333`이다. PCSX-Redux에서 디스크를 부팅하고
GDB 서버를 켠 뒤 다음 도구를 사용한다.

```bash
.venv/bin/python scripts/gdb_dump.py \
  --address 0x80000000 --size 0x200000 --output work/ram.bin

.venv/bin/python scripts/gdb_write.py work/probe.bin \
  --address 0x8001426C --leave-paused
```

RAM 쓰기는 원본 이미지 변경이 아니지만, 확인된 구조와 주소에만 수행한다.
쓰기 전후 바이트를 검증하고 조사용 상태 개입을 패치 빌드와 분리한다. 현재 다음
계측 지점은 `docs/remap-path-poc.md`의 `0x800327A8..0x800327D8`이다.

GUI 이동과 Lua 실행은 사용자가 필요한 화면·재현 지점에 게임을 놓고 신호를 준
뒤에만 수행한다. 정적 분석, 읽기 전용 GDB 메모리 확인과 워치포인트 설계는 대상에
따라 먼저 준비할 수 있다. DuckStation은 현재 작업과 검증에 사용하지 않는다.

## PCSX-Redux GPU/Lua 추적

화면에 보이는 폰트·이미지의 저장 위치를 모를 때는 PCSX-Redux GPU Logger에서
primitive의 Texpage·UV를 고른 뒤, Lua breakpoint로
`GP0(A0) → DMA2 MADR/BCR/CHCR → RAM writer`를 역추적할 수 있다. 현재 기본
PCSX-Redux를 기본 실행·동적 분석기로 사용한다.

대사 폰트 자체는 이미 `START.BIN + 0x1A000`과 RAM `0x80014A00`의
14×14·3bpp 테이블로 확정됐다. 이 방법을 기존 결론의 재탐색에 쓰지 않고,
미확인 UI·베이크드 그래픽과 정적 한글 primary 테이블의 실제 화면 색상·클리핑
연결을 검증하는 데 사용한다. 좌표 계산, DMA 검증 조건, 예외와 증거 형식은
[`gpu-upload-source-tracing.md`](gpu-upload-source-tracing.md)를 따른다.

## 디스크 도구 경계

`scripts/psx_disc.py`는 원본을 쓰지 않는 프로젝트 전용 조사 도구다.
`dumpsxiso`/`mkpsxiso`는 CUE/CDDA/XA/STR와 ISO 구조를 독립적으로 기록하고
재구성 가능성을 대조하는 데 사용한다.

mkpsxiso가 거의 동일한 재구성을 지원하더라도, 생성 이미지가 원본과 다르다는
사실을 자동으로 허용하지 않는다. 이 게임은 Mode 2 데이터 Track 1과 CDDA
Track 2~4를 사용하므로 다음을 별도로 확인한다.

- 원본 CUE track 순서와 INDEX
- raw sector form, 복제 subheader와 EDC/ECC
- ISO 파일 LBA, `DA_NA.DA`/`OP_BGM.DA`/`NONE.DA`의 CDDA 참조
- XA/STR 파일의 raw sector 표현
- 변경하지 않은 sector와 audio track의 바이트 동일성

원본 식별과 기본 위치는 `config/original-media.json` 및
`scripts/original_media.py`가 관리한다.
