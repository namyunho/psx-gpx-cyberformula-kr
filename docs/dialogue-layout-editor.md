# 17×3 대사 편집기

## 목적

`scripts/dialogue_layout_editor.py`는 번역 후보 JSON의 한국어 대사를 한
페이지씩 검토하고 17열×3행 고정 셀에서 직접 줄바꿈을 조정하는 로컬 GUI다.
ROM이나 빌드 이미지는 수정하지 않는다.

기본 입력은 다음 파일이다.

```text
work/translations/disc1-dialogue-ko-candidate.json
```

이 파일의 `entries[].ko`만 수정한다. 안정 ID, 일본어 원문, `max_glyphs`,
원본 해시와 다른 보호 필드는 입력 문서에서 그대로 복사한다.

기본 보호 workset은 다음 파일이다.

```text
work/translations/disc1-dialogue.json
```

편집기는 안정 ID로 두 파일을 결합해 `speaker_style`, `audio`,
`page_end`·`stream_end` 같은 실제 이벤트 스트림 제어를 읽기 전용으로
표시한다. 제어코드는 `ko` 문자열에 복사하지 않는다.

기본 검증 안전 슬롯 자료는 다음 파일이다.

```text
work/analysis/disc1-dialogue-safe-slots.json
```

이 자료는 원본 ALLBIN과 보호 workset을 전수 대조한 엔트리별 고정 원위치
바이트 한도다. 자세한 경계 정책은
[대사별 검증 안전 슬롯](dialogue-safe-slots.md)을 참고한다.

## 실행

Homebrew Python 3.14에서는 Tk 모듈이 별도 패키지다.

```bash
brew install python-tk@3.14
python3 scripts/build_dialogue_safe_slots.py
.venv/bin/python scripts/dialogue_layout_editor.py
```

macOS Finder에서는 저장소 최상위의 다음 파일을 더블클릭하면 된다.

```text
대사-편집기.command
```

실행기는 `.venv`와 번역 후보·보호 workset·원본 ALLBIN을 확인하고 안전 슬롯
JSON/CSV를 최신 원본에서 다시 만든 뒤 편집기를 연다. 첫 실행에서 macOS가
차단하면 Finder에서 파일을 Control-클릭한 뒤 `열기`를 선택한다.

특정 대사에서 시작:

```bash
.venv/bin/python scripts/dialogue_layout_editor.py \
  --entry-id disc1/allbin/u00/event_page/ref0000
```

다른 JSON이나 편집 필드를 선택:

```bash
.venv/bin/python scripts/dialogue_layout_editor.py \
  --input work/translations/disc1-dialogue-chapters/disc1-dialogue-u00.json \
  --editable-field ko_reflowed
```

다른 보호 workset을 선택:

```bash
.venv/bin/python scripts/dialogue_layout_editor.py \
  --workset work/translations/disc1-dialogue.json
```

다른 안전 슬롯 자료를 선택:

```bash
.venv/bin/python scripts/dialogue_layout_editor.py \
  --safe-slots work/analysis/disc1-dialogue-safe-slots.json
```

GUI를 열지 않고 입력 구조와 현재 17×3 초과 수를 확인:

```bash
.venv/bin/python scripts/dialogue_layout_editor.py --check
```

## 기능

- 17열×3행 셀 미리보기
- 행별 사용량, 표시 글리프 합계와 초과 경고
- `한도 초과만` 필터와 초과 목록 안의 검색·이전·다음 이동
- `안전 슬롯 초과만` 필터와 현재/안전/초과 바이트 막대
- `6자 미만 행만` 필터로 불필요한 줄바꿈 검수 후보 분리
- ALLBIN·유닛 안전 시작/종료 주소와 보호 경계 종류 표시
- 원본 raw 값·마크업·보존 정책과 편집 결과의 인라인 스트림 표시
- 일본어 원문·안정 ID·상태·제한값 읽기 전용 표시
- 이전/다음 이동과 ID·원문·번역 검색
- 현재 대사의 수동 편집과 Undo
- 띄어쓰기 경계만 사용하는 보수적 자동 배치
- 마지막 저장 상태로 엔트리 복원
- 저장과 다른 이름으로 저장

보수적 자동 배치는 기존 줄바꿈을 soft whitespace로 보고 단어 내용과 순서를
바꾸지 않는다. 17×3에 들어가는 배치 중 행 수를 먼저 최소화하고, 행 절반인
9글리프 미만을 줄인 뒤 길이 편차가 작은 후보를 제시한다. 단어를 쪼개야만
들어가는 문장은 자동 변경하지 않고 경고한다. 버튼을 누른 현재 엔트리에만
적용되며 저장 전 확인 창을 거친다.

`한도 초과만`은 고정 이름 토큰을 실제 표시명으로 확장한 뒤 다음 조건 중
하나라도 만족하는 엔트리만 모아 보여준다.

- 표시 글리프 합계가 51개보다 많음
- 어느 한 행이라도 17글리프보다 많음
- 명시적인 줄 수가 3행보다 많음

`안전 슬롯 초과만`은 현재 재인코딩 예상 크기가 엔트리별 엄격 안전 슬롯
바이트보다 큰 대사만 모은다. 표시 글리프뿐 아니라 선두·후미 제어와 줄바꿈
제어도 각각 2바이트로 센다. 따라서 17×3에는 들어가지만 슬롯은 초과하는
대사와, 슬롯에는 들어가지만 화면 배치가 잘못된 대사는 서로 다를 수 있다.

편집 중인 엔트리가 한도 안에 들어온 즉시 목록에서 사라지지는 않는다.
`목록 갱신`을 누르면 현재 편집값으로 초과 목록을 다시 계산한다. 목록의 `!`
표시는 화면 한도 초과, `B`는 안전 슬롯 바이트 초과, `~`는 짧은 행 후보,
`*`는 저장하지 않은 변경을 뜻한다.

`6자 미만 행만`은 2행 이상의 대사에서 표시 글리프가 1~5개인 행을 하나라도
가진 엔트리를 모은다. 빈 행과 원래 한 줄뿐인 짧은 대사는 제외한다. 고정 이름
토큰은 실제 표시명으로 확장해 센다. `한도 초과만`과 함께 선택하면 두 조건을
모두 만족하는 엔트리만 표시한다.

짧은 행은 불필요한 줄바꿈을 찾기 위한 검수 후보일 뿐 오류 판정이 아니다.
편집기가 행을 자동으로 합치지는 않으므로 앞뒤 문장, 읽기 호흡과 17×3
미리보기를 확인한 뒤 사람이 줄바꿈을 수정한다.

## 이벤트 스트림 제어

`실제 이벤트 스트림 제어 — 읽기 전용` 영역은 현재 대사가 재인코딩될 때
결합되는 제어 셸을 색상 칩과 함께 다음처럼 보여준다.

```text
바이트: 원본 스트림 68B · 검증 안전 슬롯 68B · 현재 예상 64B · 4B 미사용
슬롯 경계: ALLBIN 0x000054–0x000098 / unit 0x0054–0x0098 · 바로 다음 추출 대사 시작
선두 보호: 0x903F {speaker_style:03F} [preserve]
조판: 줄바꿈 2개 → 0xFFFB {align} [movable-layout-in-story-only]
후미 보호: 0x8000 {page_end} [preserve]
인라인 스트림: {speaker_style:03F}한국어{align}대사{page_end}
```

색상은 소비 역할을 나타낸다.

| 색상 | 역할 | 표시 글리프 |
|---|---|---:|
| 보라 | 화자·초상 상태 | 0 |
| 파랑 | 음성·음성 전환 | 0 |
| 주황 | `FFFB` 줄바꿈 | 0, 다음 행으로 이동 |
| 빨강 | 페이지·스트림 종료 | 0 |
| 회색 | 진행 속도·대기 같은 기타 제어 | 0 |
| 밝은 바탕 | 실제 표시 글리프 | 표시 문자 수만큼 |

17×3 셀 미리보기에서는 `FFFB`로 건너뛰는 현재 행의 남은 셀을 주황색으로
채우고 오른쪽에 `↵ FFFB`를 표시한다. 따라서 제어토큰이 글리프 칸을 직접
차지하지 않으면서도 다음 행으로 이동해 사용하지 못하게 만든 위치를
글리프 수와 분리해서 확인할 수 있다.

선두와 후미 제어는 원본 workset의 raw 토큰에서 가져오며 편집할 수 없다.
줄바꿈은 확인된 조판 토큰이므로 현재 한국어 줄바꿈에서 `0xFFFB`로 다시
계산한다. 화면에 인라인으로 보이더라도 후보 JSON에는 번역문만 저장한다.
빌드가 같은 안정 ID의 보호 workset을 결합하므로 제어코드를 `ko`에 다시
기입하면 중복 인코딩 위험이 생긴다.

현재 예상 바이트는 보호 셸, 표시 글리프와 줄바꿈을 합친 재인코딩 크기다.
검증 안전 슬롯은 원본 ALLBIN의 같은 시작 주소에서 인터엔트리 간격을 전혀
소비하지 않는 엄격한 최대치다. 녹색 막대는 슬롯 안의 현재 사용량, 회색은
쓰지 않은 원본 범위, 빨강은 초과 용량을 나타낸다. 현재 크기가 슬롯과 같으면
`정확히 일치`, 작으면 `미사용`, 크면 `초과`로 구분한다. `미사용` 영역은
새 번역이 덮지 않고 원본 바이트가 남는다는 뜻이며, 전역적으로 재배치 가능한
패딩이라는 뜻은 아니다.

편집기는 화면의 17×3 배치와 원본 이벤트 슬롯 바이트를 독립적으로 검사한다.
다만 초상화·인물명·분기 소비의 실행 시점까지 인증하지는 않으므로 ROM 삽입
감사와 실행 검증을 대신하지 않는다.

## 저장 안전성

기존 경로에 저장하면 먼저 같은 디렉터리에 다음 백업을 만든다.

```text
disc1-dialogue-ko-candidate.json.bak
```

새 JSON은 임시 파일에 쓴 뒤 다시 파싱하고 원자적으로 교체한다. 프로그램은
로드한 문서의 복사본에 감지된 한국어 필드 하나만 대입하므로 엔트리 순서나
보호 필드를 편집할 수 없다.

편집 결과는 번역 후보일 뿐 자동으로 빌드 적격이 되지 않는다. 저장 후 기존
감사와 빌드를 다시 실행해야 한다.

```bash
.venv/bin/python scripts/audit_dialogue_reinsertion.py
```
