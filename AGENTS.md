# AGENTS.md — 신세기 GPX 사이버 포뮬러 PS1 한국어화

이 저장소는 PlayStation용 《신세기 GPX 사이버 포뮬러 새로운 도전자》 Disc 1의
한국어 패치를 만든다. 현재 상태는 `README.md`, 매체·실행 파일 식별값은
`docs/reverse-engineering-baseline.md`, 대사 협업 형식과 레이아웃 한계는
`docs/dialogue-extraction.md`, 통합 편집기는
`docs/dialogue-layout-editor.md`, 미니게임·코스·머신 설정 폰트 문자열은
`docs/special-screen-font-text.md`를 정본으로 삼는다. 리맵 관련 문서는
현재 직접 인코딩 방식으로 대체된 역사적 PoC다.

## 하드 불변식

1. 원본 BIN/CUE, BIOS, 추출 파일, RAM/VRAM 덤프와 패치된 전체 이미지는 커밋하지
   않는다. 기본 원본 위치는 `roms/`이며 `.gitignore`를 유지한다.
2. Track 1은 크기와 CRC32/MD5/SHA-256을 모두 검증한 뒤 읽는다. 알려진 원본과
   다르면 분석·빌드를 중단한다.
3. ISO 파일 좌표, raw 2352바이트 sector 좌표, PS-X EXE 파일 오프셋, runtime
   virtual address를 섞지 않는다.
4. Mode 2 sector는 Form 1/2와 복제 subheader를 판정한다. 변경 sector만 올바른
   EDC/ECC 규칙으로 다시 만들며, 변경하지 않은 sector를 정규화하지 않는다.
5. PS-X EXE는 파일 `+0x800`의 payload가 header의 load address에 적재된다.
   이 환산은 다른 overlay나 `ALLBIN.BIN` 전체에 적용하지 않는다.
6. MIPS R3000A 훅은 branch/load delay, live register, `$gp`, cache 갱신과 overlay
   수명을 검산한다. 생성한 모든 명령은 armips와 독립 디스어셈블 결과로 대조한다.
7. 추출·재조립은 무수정 round-trip을 먼저 통과한다. 최종 이미지 변경은 불변
   원본에 대한 예상 쓰기 범위로 모두 설명돼야 한다.
8. 대사 작업본을 외부 도구나 AI와 교환할 때 `entry_id`와 보호 필드는 변경하지
   않는다. 번역 단계 전 기준선의 완역본·축약본 필드는 모두 비어 있어야 한다.
9. 동적 분석은 PCSX-Redux의 clean boot와 재현 절차를 기준으로 한다. save state
   하나만 근거로 삼지 않으며 BIOS·emulator 식별값, breakpoint/watchpoint,
   register와 RAM/VRAM 증거를 함께 기록한다.

## 원본 매체

- 기본 CUE: `roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1).cue`
- 기본 데이터 Track 1: `roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1) (Track 1).bin`
- 경로 재정의: `PSX_DISC1_CUE`, `PSX_DISC1_TRACK1`
- 준비/검증:

```bash
.venv/bin/python scripts/original_media.py prepare
.venv/bin/python scripts/original_media.py paths
.venv/bin/python scripts/original_media.py verify --cue
```

## 역공학 도구 선택

- IDA Pro/`idalib-mcp`: 짧은 루틴, 바이트, xref, 함수 경계와 반복 질의의 주력.
- Ghidra MCP: 긴 제어 흐름이나 포인터 전달을 MIPS 디컴파일로 교차검증할 때 사용.
- PCSX-Redux GDB `127.0.0.1:3333`: runtime RAM, 실제 overlay 적재, 레지스터와
  소비 시점을 확인한다. CPU breakpoint/watchpoint 조사 때 debugger를 켜고
  Dynarec을 끈다.
- PCSX-Redux Lua API·VRAM Viewer·GPU Logger: 읽기/쓰기/실행 watchpoint와
  화면→VRAM→DMA/RAM 공급자 연결을 조사한다. 사용자가 목표 장면을 재현하고
  준비 신호를 보내기 전에는 GUI나 Lua를 실행하지 않는다. 신호 뒤에는 합의한
  관측 범위에 한해 에이전트가 GUI 조작·Lua 실행과 결과 해석을 담당할 수 있다.
- Kaitai Struct 0.11: 확인된 바이너리 구조를 `.ksy`로 선언하고 Python
  read/write 생성물로 무수정 byte-exact round-trip을 검증한다.
- 저장 파일과 runtime 표현이 다르면 정적 결과를 실행 증거로 승격하지 않는다.
- PS-X EXE는 직접 `idb_open`하지 말고 `scripts/build_ida_db.py`로 올바른
  `TEXT`/entry가 있는 `.i64`를 만든 뒤 연다.

DuckStation은 현재 작업과 이후 검증에 사용하지 않는다. 기존 문서의 DuckStation
표기는 과거 실험의 증거 출처일 때만 보존하며 새 조사 절차로 인용하지 않는다.

MCP 설정과 PS1별 import 규칙은 `docs/reverse-engineering-mcp.md`를 따른다.
GUI MCP는 해당 앱과 프로젝트/프로그램을 먼저 열어야 한다. headless idalib은
동일 IDB를 다른 프로세스와 동시에 열지 않는다.

## 기본 검증

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/toolchain.py
```
