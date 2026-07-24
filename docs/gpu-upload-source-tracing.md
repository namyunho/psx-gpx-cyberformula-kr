# GPU 업로드에서 폰트·이미지 원본 역추적

이 문서는 PCSX-Redux의 GPU Logger와 Lua breakpoint를 이용해 화면의
폰트·이미지가 어느 RAM 버퍼에서 VRAM으로 올라왔는지 찾는 기법을 이 프로젝트에
적용하기 위한 기술 기록이다.

- 참고 글:
  [루아 스크립트를 이용한 폰트 및 이미지 찾기](https://sunlightface.github.io/psx1/%EB%A3%A8%EC%95%84-%EC%8A%A4%ED%81%AC%EB%A6%BD%ED%8A%B8%EB%A5%BC-%EC%9D%B4%EC%9A%A9%ED%95%9C-%ED%8F%B0%ED%8A%B8-%EB%B0%8F-%EC%9D%B4%EB%AF%B8%EC%A7%80-%EC%B0%BE%EA%B8%B0/)
- 공식 도구 문서:
  [PCSX-Redux GPU Logger](https://pcsx-redux.consoledev.net/Debugging/gpu-logger/),
  [Lua memory/register API](https://pcsx-redux.consoledev.net/Lua/memory-and-registers/),
  [Lua breakpoint API](https://pcsx-redux.consoledev.net/Lua/breakpoints/)
- 하드웨어 사양:
  [psx-spx GPU](https://psx-spx.consoledev.net/graphicsprocessingunitgpu/),
  [psx-spx DMA channels](https://psx-spx.consoledev.net/dmachannels/)
- 검토일: 2026-07-24
- 현재 판정: **적용 가능한 조사 기법, 아직 이 게임에서 실행하지 않음**

참고 글의 전체 Lua 코드를 저장소에 복제하지 않는다. 원문을 실행 기준으로
참조하고, 이 문서에는 프로젝트에 필요한 원리, 강화할 검증 조건과 증거 형식만
유지한다.

## 이 프로젝트의 현재 상태

이 기법은 대사 폰트를 처음부터 다시 찾기 위한 필수 단계는 아니다. 커밋 기록상
초기 실패와 후속 확정이 다음처럼 구분된다.

| 커밋 | 시각 | 당시 판정 |
|---|---|---|
| `c8e78e1` | 2026-07-12 10:57 KST | BIOS `Krom2RawAdd` 직접 호출과 표준 TIM을 찾지 못했고 시각 글리프 렌더러가 미확정 |
| `5a86034` | 2026-07-12 11:04 KST | 대사 폰트를 `START.BIN + 0x1A000`의 14×14, 3bpp, 글리프당 74바이트 테이블로 확정 |
| `3d83565` | 2026-07-12 11:12 KST | 한글 후보 글꼴의 게임 포맷 변환을 검증 |
| `0e8351d` | 2026-07-12 15:15 KST | 첫 한글 폰트 PoC를 준비 |

현재 확인된 대사 경로는 다음 문서가 정본이다.

- 저장 위치와 글리프 포맷: [`font-format.md`](font-format.md)
- 한글 글꼴 입력과 변환: [`korean-font.md`](korean-font.md)
- 화면 표시 PoC: [`poc.md`](poc.md)

따라서 이 GPU 역추적 기법의 우선 용도는 다음과 같다.

1. 아직 저장 형식을 모르는 메뉴, 이름 화면, 선택 상태와 베이크드 그래픽 조사
2. 알려진 대사 글리프가 작업 표면, VRAM과 화면까지 도달하는 연결의 독립 검증
3. 향후 한글 글리프 캐시가 실제 업로드·상주·소비되는지 확인
4. 같은 화면에서 서로 다른 폰트·텍스처 공급자를 쓰는 경로 분리

## 핵심 원리

PS1 VRAM은 CPU 주소 공간에 직접 매핑되지 않는다. CPU가 GPU의 `GP0`
포트(`0x1F801810`)로 명령·데이터를 쓰거나 DMA2를 사용해야 VRAM에 데이터가
도달한다.

화면에서 선택한 텍스처를 저장 원본까지 추적하는 기본 연결은 다음과 같다.

```text
화면 primitive
  -> Texpage + UV (+ Texture Window)
  -> 소비한 VRAM halfword 좌표
  -> 그 좌표를 포함한 GP0(A0h) CPU-to-VRAM 업로드
  -> DMA2 MADR의 RAM 소스
  -> RAM 버퍼를 만든 writer / 변환·해제 루틴
  -> 적재 파일·컨테이너·디스크 위치
```

`GP0(A0h)`와 DMA2에서 확인할 레지스터는 다음과 같다.

| 경계 | 값 | 의미 |
|---|---:|---|
| GPU 포트 | `0x1F801810` | GP0 명령과 데이터 |
| DMA2 MADR | `0x1F8010A0` | RAM 전송 시작 주소 |
| DMA2 BCR | `0x1F8010A4` | block 크기와 개수 |
| DMA2 CHCR | `0x1F8010A8` | 방향, sync mode, 시작 상태 |

`A0h` packet의 첫 세 word는 명령, VRAM 목적지 `YyyyXxxx`, 크기
`YsizXsizh`다. 여기의 X와 폭은 화면 픽셀이 아니라 VRAM **16비트
halfword** 단위다. 이후 픽셀 데이터는 16비트 VRAM 값의 열이다.

## 화면 UV를 VRAM 좌표로 바꾸기

GPU Logger에서 화면에 보이는 primitive를 골라 다음 값을 기록한다.

- 명령 종류와 화면 vertex/크기
- U/V
- Texpage X/Y와 texture depth
- indexed texture이면 CLUT 좌표
- Texture Window 설정
- logger가 표시하는 command origin과 DMA chain

Textured Rectangle은 보통 현재 `GP0(E1h)` draw mode의 Texpage를 사용한다.
Textured Polygon은 primitive 안의 Texpage 속성을 사용할 수 있다. 두 경우를
섞지 않는다.

Texture Window를 적용한 유효 좌표를 `U'`, `V'`라 할 때, texture source의
물리 VRAM X halfword 후보는 다음과 같다.

| texture depth | X halfword |
|---|---|
| 4bpp | `texpage_x + floor(U' / 4)` |
| 8bpp | `texpage_x + floor(U' / 2)` |
| 15bpp | `texpage_x + U'` |

Y 후보는 `texpage_y + V'`다. 이 좌표는 화면 좌표와 무관하다. 4bpp·8bpp의
실제 색을 재현하려면 texture data와 별도로 CLUT의 저장·업로드 경로도 추적한다.

참고 글의 예시는 4bpp texture에서 Texpage X `896`, U `0`이므로 물리 X가
`896 + 0 / 4 = 896`이 된다. `A0h` 폭 `4` halfword는 4bpp에서 가로
16 texel에 해당한다.

목적지 원점이 정확히 같은 `A0h`만 찾으면 더 큰 atlas나 부분 업데이트를 놓칠 수
있다. 구현 시에는 다음 포함 조건으로 후보를 모은다.

```text
upload_x <= target_x < upload_x + upload_w
upload_y <= target_y < upload_y + upload_h
```

같은 영역을 여러 번 썼다면 화면 primitive가 소비되기 전 마지막으로 유효한
쓰기와 상태 수명을 구분한다.

## PCSX-Redux 조사 절차

### 1. 재현 기준선 고정

원본 Disc 1 해시, BIOS, emulator revision, 시작 상태와 입력 순서를 기록한다.
표시된 뒤 만든 save state만으로 시작하면 앞서 일어난 texture upload를 놓칠 수
있다. 가능하면 목표 자산이 적재되기 전 상태나 새 실행에서 시작한다.

### 2. GPU Logger에서 소비 지점 선택

GPU logging과 필요하면 vsync breakpoint를 켠다. 목표 화면에서 primitive를
highlight/replay해 실제로 해당 글자·이미지를 그리는 명령인지 확인한다.
`Show origins`로 CPU write 또는 DMA chain 경로를 함께 기록한다.

한 프레임의 primitive를 제거했을 때 해당 요소가 사라지는 것은 소비 primitive의
증거이지 저장 원본의 증거는 아니다.

### 3. VRAM 좌표와 범위 계산

Texpage, UV, depth와 Texture Window를 적용해 위 식으로 물리 VRAM 좌표를
계산한다. atlas 전체가 아니라 목표 글자·라벨 내부의 대표 point와 예상 범위를
기록한다. indexed texture이면 CLUT 위치도 별도 target으로 둔다.

### 4. Lua watcher 실행

참고 글의 Lua는 다음 순서를 감시한다.

1. `0x1F801810` write에서 `A0h`, 목적지, 크기 세 word를 조립
2. target 목적지를 만나면 DMA2 MADR write 값을 보존
3. DMA2 CHCR write로 실제 전송 시작을 확인
4. MADR, 크기와 `A0h`/CHCR write PC를 기록하고 emulator를 정지

PCSX-Redux Lua console에서는 원문의 스크립트를 로컬 파일로 둔 뒤 다음처럼
불러온다.

```lua
dofile("/absolute/path/to/gpu_a0_source_finder.lua")
```

Lua breakpoint 객체는 전역이나 수명이 충분한 table에 보존해야 한다. 객체가
garbage collection되면 breakpoint도 제거된다. callback은 emulator의 안전한
Lua 환경 밖에서 실행되므로 `pcall`로 오류를 기록한다. 공식 문서상 이
breakpoint 기능은 debugger를 켜고 interpreter를 사용할 때 동작한다.

프로젝트용 구현을 만들 때는 원문의 exact X/Y match를 앞 절의 rectangle
containment로 바꾸고, BCR·CHCR 값과 일련번호도 함께 기록한다.

### 5. DMA 전송 검증

MADR를 잡았다는 사실만으로 목표 upload를 확정하지 않는다.

- CHCR bit 0이 RAM→device 방향인지 확인한다.
- CHCR bit 24의 start/busy write를 확인한다.
- sync mode가 block transfer인지 linked list인지 기록한다.
- block transfer이면 `BCR`의 word 수와 `ceil(width * height / 2)`를 대조한다.
  `A0h`의 `width * height`는 halfword 수이고 DMA word 하나는 halfword 둘이다.
- MADR의 유효 RAM 주소를 정규화하고 KSEG0/KSEG1 표기와 섞지 않는다.
- 같은 target에 대한 모든 후보를 기록하고 화면 소비 시점과 순서를 대조한다.

참고 글은 `A0h -> MADR -> CHCR` 순서를 유용한 최소 조건으로 제시한다. 위
검사는 그 방법을 이 프로젝트의 확정 증거로 승격할 때 추가할 조건이다.

### 6. RAM에서 저장 원본으로 역추적

MADR는 다음 셋 가운데 하나일 수 있다.

1. 파일에서 읽은 자산이 그대로 놓인 RAM
2. atlas나 글리프를 조립한 작업 버퍼
3. 압축 해제·색 깊이 변환 뒤의 임시 버퍼

먼저 MADR 범위를 덤프해 목표 픽셀을 재현한다. 포맷이 확정되지 않았다면 4bpp,
8bpp, 15bpp, 폭, stride와 CLUT를 후보로 명시하고 한 가지 시각적 일치만으로
확정하지 않는다.

작업 버퍼라면 해당 범위에 write breakpoint를 걸어 최초로 다른 값이 생기는
writer를 잡는다. 압축 또는 조립이 확인되면 입력 pointer를 거꾸로 따라
파일·overlay·archive 위치까지 연결한다. `scripts/ram_map.py`의 파일/RAM 일치와
원본 해시로 정적 위치를 검산한다.

### 7. IDA와 Ghidra로 코드 경로 교차검증

`A0_PC`와 `CHCR_PC`, RAM writer PC를 정적 분석의 앵커로 사용한다.

- IDA/idalib: 정확한 instruction bytes, 함수 경계, 직접 xref와 호출자를 확인
- Ghidra: 버퍼 pointer 전달, loop, 상태 분기와 긴 제어 흐름을 디컴파일로 대조
- DuckStation 또는 PCSX-Redux: 실제 module, register와 자산 수명을 재확인

PC가 `SLPS_019.58` 범위가 아니라 runtime overlay에 있으면 먼저 적재 범위와
파일 대응을 찾는다. PS-X EXE 환산식을 다른 module에 그대로 적용하지 않는다.
두 정적 도구가 다른 결론을 내면 base·overlay·코드/데이터 경계를 먼저 재검토한다.

## 이 방법이 바로 성립하지 않는 경우

- GPU command와 픽셀을 CPU가 모두 PIO로 쓰면 DMA2 MADR가 없다.
- `A0h` packet 자체가 linked-list DMA 안에 있으면 CPU의 `sw`만 해석하는
  watcher로 command 값을 얻지 못할 수 있다.
- `GP0(80h)` VRAM-to-VRAM copy를 거쳤다면 최종 목적지에서 이전 VRAM 영역으로
  한 단계를 더 역추적해야 한다.
- 목표가 framebuffer, MDEC 출력 또는 GPU fill 결과이면 texture upload라는
  가정이 틀릴 수 있다.
- 더 큰 atlas가 앞 장면에서 이미 상주했다면 목표 화면 직전에는 upload가 없을
  수 있다.
- partial update, double buffering과 같은 좌표 재사용은 X/Y 한 번의 일치로
  구분되지 않는다.
- Texture Window, CLUT, Texpage state를 빠뜨리면 화면 UV와 물리 VRAM 좌표가
  잘못된다.
- 참고 Lua의 write 값 복원은 현재 PC의 MIPS `sw`를 디코딩한다. 다른 store
  형태, DMA 내부 전송이나 debugger 동작 차이는 별도 처리가 필요하다.
- MADR의 데이터가 화면과 닮았다는 사실은 디스크 원본을 찾았다는 뜻이 아니다.
  저장→탐색→적재·변환→상주→소비 연결의 각 경계를 확인한다.

## 프로젝트용 증거 기록

한 번의 조사 결과는 최소한 다음 필드를 남긴다.

| 필드 | 내용 |
|---|---|
| `trace_id` | 화면·상태와 분리된 안정 ID |
| `baseline` | 원본 해시, BIOS, emulator/version, 시작 상태 |
| `target` | 화면 요소, primitive, 선택 근거 |
| `draw` | GP0 명령, frame/order, screen XY/WH |
| `texture` | depth, Texpage, raw/effective UV, Texture Window, CLUT |
| `vram_target` | 계산한 halfword X/Y와 대상 범위 |
| `upload` | A0 목적지/크기, command order, 포함 판정 |
| `dma2` | MADR/BCR/CHCR, 방향·mode·word 수 검증 |
| `pcs` | A0, MADR, BCR, CHCR write PC와 실제 module |
| `ram` | 정규화한 주소, 덤프 해시·범위, 포맷 판정 |
| `storage` | 파일/컨테이너/오프셋·크기와 원본 해시 |
| `result` | 관찰, 가설, 확정 결론과 남은 미지수 |

RAM/VRAM dump와 원본 자산은 `work/`에 두고 커밋하지 않는다. 저장소에는 주소,
크기, 해시, 재현 절차와 판정만 남긴다.

## 첫 적용 후보

가장 작은 첫 실험은 이미 재현 가능한 첫 대사 화면을 쓴다.

1. 글리프 또는 대사 작업 표면을 소비하는 primitive 하나를 GPU Logger에서 확정
2. Texpage/UV로 VRAM source point 계산
3. 그 point를 포함하는 `A0h` upload와 DMA2 MADR 기록
4. RAM 결과가 알려진 `0x80014A00` 글리프 테이블 자체인지, `0x80032434`에서
   해제한 4bpp 작업 표면인지 구분
5. 저장 `START.BIN + 0x1A000`에서 화면 primitive까지 연결

이 실험은 대사 폰트 위치를 다시 찾는 작업이 아니라, 이미 확인한 포맷의
`저장 → 적재·변환 → 상주 → 소비` 연결을 독립적으로 닫는 작업이다. 그 뒤 같은
절차를 이름 화면과 미확인 UI 그래픽에 확대한다.
