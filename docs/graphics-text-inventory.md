# 그래픽에 새겨진 문자 자산 분모

이 문서는 실제 폰트로 그리는 대사와 분리해, 이미지 픽셀에 포함된 문자를 찾고
수정하기 위한 상태 단위 목록 기준을 정의한다.

## 작업 단위

번역 작업 단위는 raw rectangle 하나가 아니라 **scheduled state 하나**다.

```text
scheduled state
  ├─ palette/CLUT
  ├─ image rectangle
  ├─ render metadata
  └─ control/offset directory
```

이 중 하나만 따로 번역 자산으로 세면 팔레트와 그림의 관계, 같은 VRAM 위치를
공유하는 상태, zero padding을 잃는다. `scripts/psx_layout.py`의
`raw_vram_rectangle` 판정은 저장 포맷 후보일 뿐 화면 소비 증거가 아니다.

## 정확한 분모

`scripts/psx_graphics_scope.py`는 1,739개 state를 하나씩 분류하고 누락·중복이
없음을 검사한다.

| 파일 | 베이크드 문자 검토 | 폰트 | 초상 | 비그래픽 |
|---|---:|---:|---:|---:|
| `MINI_G1..4.BIN` | 10 | 0 | 0 | 0 |
| `AVM_MAP.BIN` | 1,334 | 0 | 0 | 0 |
| `START.BIN` | 39 | 2 | 24 | 0 |
| `OUTSIDE.BIN` | 11 | 0 | 0 | 0 |
| `MACHINE.BIN` | 42 | 0 | 0 | 0 |
| `COURSE.BIN` | 27 | 0 | 0 | 250 |
| 합계 | 1,463 | 2 | 24 | 250 |

여기서 “베이크드 문자 검토”는 글자가 있다는 확정이 아니라, 글자가 존재할 수
있는 시각 자산 분모다. 실제 수정 목록으로 승격하려면 화면 소비와 문자 존재를
둘 다 확인한다.

## 파일별 판정

### 글꼴 렌더 UI 60개와 일반 UI의 구분

`work/translations/disc1-ui.json`의 60개는 게임 전체 UI 목록이 아니다. 전부
`ALLBIN.BIN` unit 40의 이름 등록 화면에서 alternate/primary 글꼴로 그리는
스트림이다.

| 역할 | 수 | 현재 처리 |
|---|---:|---|
| 한자 입력 팔레트 | 47 | 원본 보존 |
| 이름 입력·확인 문구 | 2 | 한국어 주입 |
| 가나·영문·기호 입력 팔레트 | 6 | 원본 보존 |
| 이름·출신 라벨 | 1 | 한국어 주입 |
| 출신 선택지 | 1 | 한국어 주입 |
| 가상 플레이어명 스트림 | 2 | 런타임 코드 보존 |
| 출신 표시 가변 버퍼 | 1 | 런타임 버퍼 보존 |

따라서 현재 UI 빌드가 번역한 고정 문구는 4개이고, 56개는 입력 팔레트 또는
가변 버퍼라 의도적으로 보존했다. 미니게임 HUD, 머신 설정, 결과·랭킹,
장 카드 등의 일본어는 이 60개와 별개다. 접촉표에서 다음 베이크드 후보를
확인했으며, 프로젝트 방침대로 그래픽 현지화 단계에서 마지막에 처리한다.

- `MINI_G1..4.BIN`: HUD/menu texture state 10개
- `START.BIN`: title/menu, selection, race result/ranking, chapter card 후보 39개
- `OUTSIDE.BIN`: cockpit/external UI state 11개
- `COURSE.BIN`: course/environment/HUD visual state 27개
- `AVM_MAP.BIN`: 장면 속 UI·간판·포스터를 포함할 수 있는 state 1,334개

`MACHINE.BIN` 42개는 차량 텍스처 atlas라는 구조 판정만 끝났다. 머신 설정
화면의 UI 소비자가 이 파일이라고 단정하지 않으며, 화면→VRAM→RAM→저장
위치의 소비 경로를 먼저 연결한다.

### 특수 화면 폰트 대사와 그래픽 라벨의 구분

사용자 화면 관측과 `u38/u43` 소비자 교차 분석으로 다음 391개는 이미지가
아니라 primary 글꼴 스트림임을 확인했다.

| 화면 | 폰트 번역 범위 | 그래픽 범위 |
|---|---:|---|
| 미니게임 | 규칙·블랙잭·카메라·요리 대사와 런타임 단어 322개 | HUD·버튼·타이틀 |
| 코스 정보 | 코스 설명 57개 | `Course Information`, 지도·날씨 라벨 |
| 머신 설정 | 타이어·전략·윙·부스트 설명 12개 | `Machine Setting`, A/B/C Tire와 버튼 |

폰트 문자열은 `scripts/extract_special_screen_text.py`와
`data/translations/disc1-special-screen-ko.json`에서 다룬다. 그래픽
라벨은 이 문서의 1,463 state 분모에 그대로 남는다. 한 화면에 둘이 함께
보인다는 이유로 폰트 대사를 베이크드 그래픽으로 분류하거나, 반대로 버튼
이미지를 폰트 재삽입기로 수정하지 않는다. 상세 주소·수량·번역 병합 상태는
[`special-screen-font-text.md`](special-screen-font-text.md)를 따른다.

### START

- unit 2: primary dialogue font, 그래픽 수정 대상 아님
- unit 40: alternate UI font, 그래픽 수정 대상 아님
- unit 41..64: 48×56 4bpp 초상화 provider, 문자 없음
- 나머지 39개: UI·카드·상태 화면 시각 검토 대상

접촉표에서 확인한 대표 내용:

- 0..1: 타이틀·메뉴 UI
- 9..17: 이름/캐릭터 선택, 로마자 alphabet과 UI
- 20..23: 레이스 상태·결과·랭킹 UI
- 24..37: 장/종료 카드, credits, game over
- 38..39: branding imagery

### AVM_MAP

1,334개 state는 파일 전체를 정확히 분할한다.

- 462개: state 자체가 직접 VRAM rectangle
- 872개: offset directory를 가진 palette/image/metadata 상태
- 후자의 raw rectangle child는 1,744개
- `unknown` child 839개는 state 내부 control/metadata로 보존하며 초상화라고
  추정하지 않는다.

접촉표에서 일본어 UI, 포스터, 표지판이 보이는 장면이 확인됐다. 모든 장면에
글자가 있는 것은 아니므로 state별 화면 대응 후 편집한다.

### OUTSIDE

11개 전부 cockpit/외부 UI 상태다. unit 0, 1, 2, 9, 10에서 status/options와
베이크드 label을 접촉표로 확인했다.

### MINI_G1..4

10개 전부 HUD/menu texture 상태다. palette와 atlas가 한 state를 이루므로
rectangle 수가 아니라 state 단위로 유지한다.

### MACHINE

42개 전부 vehicle texture atlas다. 차체 logo, 번호, sponsor lettering은
프리렌더 텍스처의 일부이므로 번역 정책상 유지/수정 여부를 별도로 결정해야 한다.
원 상표와 일본어 안내 문구를 같은 종류로 취급하지 않는다.

### COURSE

- unit 0..25, 276: 27개 course/environment/HUD visual state
- unit 26..275: offset directory가 없는 250개 코스/모델 데이터, 그래픽 문자
  수정 대상에서 제외

unit 24에서 결과/HUD, unit 25에서 warning label을 접촉표로 확인했다.
0..23의 track signage는 실제 화면과 대응해 판정한다.

## 편집 승격 조건

각 state의 기본 `edit_status`는
`blocked_pending_per_target_consumer_trace`다. 다음을 만족하면 한 state만
편집 대상으로 승격한다.

| 경계 | 필요한 증거 |
|---|---|
| 저장 | 파일, state index, offset, size, SHA-256 |
| 탐색 | 스케줄/descriptor 또는 state 선택 값 |
| 적재·변환 | RAM 목적지, decompressor/atlas builder 여부 |
| 상주 | VRAM rectangle, depth, CLUT |
| 소비 | 실제 primitive의 Texpage/UV/Texture Window |
| 회귀 | 목표 픽셀 외 동일, 원본 CUE/CDDA 관계 유지 |

폰트처럼 보이는 접촉표, header가 우연히 맞는 rectangle, 화면에 닮은 RAM dump 중
하나만으로는 편집하지 않는다.

## 보고서 생성

```bash
.venv/bin/python scripts/psx_layout.py \
  --output work/analysis/disc1-layout.json
.venv/bin/python scripts/psx_graphics_scope.py \
  --output work/analysis/disc1-graphics-scope.json
.venv/bin/python scripts/psx_graphics_scope.py \
  --output work/analysis/disc1-graphics-scope-summary.json --summary
```

접촉표는 다음 위치에 생성돼 있으며 버전 관리 대상이 아니다.

```text
work/analysis/vram-review/
work/analysis/vram-course-machine/
work/analysis/portraits/
```
