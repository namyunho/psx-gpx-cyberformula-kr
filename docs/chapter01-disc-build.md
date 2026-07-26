# 챕터 1 비배포 디스크 빌드

## 현재 판정

스토리 챕터 1은 ALLBIN scheduled unit `0`이다. 기존 작업셋의 포인터 대상
대사 88개는 모두 띄어쓰기 경계만 사용한 17×3 줄 배치에 들어간다. 이 범위에
보호 이름 토큰 충돌과 글리프 누락은 없다. 물리 스트림 재감사에서 별도로
확인한 무포인터 페이지는 5개다.

사용자 실행 검증에서 고정 원본 주소 빌드의 대사 내용과 순서는 정상으로
확인됐다. 이후 관측된 초상화·등장인물명 누락은 문장부호의 줄 이동이 아니라
앞 대사의 슬롯 초과가 다음 페이지의 선두 `speaker_style`·`audio` 제어를
덮은 결과다. 상세 근거와 반각 문장부호 검토, unit `21` 상태는
[`dialogue-runtime-findings.md`](dialogue-runtime-findings.md)에 정리했다.

현재 개발 빌드는 다음 변경을 함께 만든다.

- `START.BIN`: primary 1,229슬롯을 후보 코퍼스용 정적 글꼴로 교체
- `ALLBIN.BIN`: unit `0`의 88개와 unit `21`의 68개 포인터 대상 대사를
  한국어 글리프 코드로 재인코딩하되 각 원본 시작 주소를 유지
- Track 1: 위 두 파일의 실제 변경분만 원래 ISO extent에 제자리 삽입
- raw sector: 변경한 Mode 2/Form 1 섹터의 EDC와 P/Q ECC 재계산

폰트는 실제로 교체됐지만 슬롯 초과를 의도적으로 허용한 **비배포 진단
빌드**다. primary 글꼴은 전역으로 교체되는 반면 unit `0`, `21` 이외 대사는
아직 일본어 토큰이므로 다른 대사 unit에 진입하면 안 된다. 아래에서 확인한
무포인터 5페이지는 기존 추출·번역 작업셋에서 빠져 있으므로 현재 빌드에서는
원문 토큰과 해당 원본 글리프 슬롯을 함께 보존한다. 추출·번역 입력에
편입하기 전까지 챕터 1의 완전 한글화 빌드로 판정하지 않는다.

## 연속 대사 순서 결함과 수정

최초 재삽입기는 번역 스트림을 크기순으로 빈 원문 영역에 배치했다. 포인터로
도달하는 대사는 안정 ID별 포인터를 함께 갱신했지만, 게임의 첫 표시 경로는
`ALLBIN.BIN + 0x54`를 고정 시작점으로 사용한다. 그 결과 실패 빌드는 이 위치를
`ref0058`의 “좋아! 이렇게 된 이상…”으로 덮었고, 원래 `ref0000` 앞의
`0x903F` speaker-style 토큰도 함께 사라져 첫 화면의 이름·초상화 상태가
설정되지 않았다.

첫 수정본은 `ref0000`만 `0x54`에 고정했다. 사용자의 실행 검증에서 첫 대사
다음에 `ref0001`이 아니라 `ref0059`가 표시됐다. 실패 빌드의 `0x98`을
역검증하니 실제로 `ref0059`가 있었다. 이는 첫 페이지가 끝난 뒤 엔진이
두 번째 포인터 항목을 다시 조회하지 않고 현재 텍스트 포인터를 스트림 끝
다음 주소로 전진시킨다는 증거다.

IDA Pro와 Ghidra의 `SLPS_019.58` 교차 분석도 같은 소비 규칙을 확인했다.
`sub_8003907C`는 텍스트 기준 포인터 `0x80061158`만 설정하고,
`sub_8003229C`가 새 텍스트 초기화 때 커서 `0x80060FA0`을 0으로 만든다.
`sub_80032D34`는 계속 `base + cursor × 2`에서 토큰을 읽고 커서를 증가시킨
뒤 `0x8000`에서 대기하므로, 다음 페이지는 같은 기준 포인터의 바로 다음
토큰에서 재개된다.

두 번째 수정본은 원본에서 주소가 정확히 맞닿은 엔트리만 하나의 체인으로
묶었다. 그러나 대부분의 페이지 사이에는 `0x0000` 한 워드가 있고, 이는
할당기가 사용해도 되는 빈 공간이 아니라 런타임 커서가 그대로 통과하는
물리 스트림의 일부다. 이 빌드는 `ref0001` 뒤의 남은 공간에 `ref0013`을,
원래 `ref0002` 주소에는 `ref0011`을 배치했다. 사용자의 실행 검증에서
`ref0000 → ref0001 → ref0011`로 진행한 뒤 대사가 중단된 원인이 바로 이
크기 우선 재배치다.

unit `0`의 엔트리 사이 비영 간격을 다시 해석하니 포인터로 직접 가리키지
않는 페이지도 5개 확인됐다.

- `ref0039 → ref0040`: 시스템 성별 선택 1페이지
- `ref0048 → ref0087`: “예/아니오” 선택 1페이지
- `ref0070 → ref0071`: 익스트림 스피드 설명 3페이지

특히 `ref0048` 뒤의 선택 페이지와 실패 분기 `ref0087`, 이후 합류하는
`ref0049`는 `ref` 번호 정렬만으로는 복원할 수 없는 제어 흐름이다. `ref`
번호는 포인터 테이블의 참조 번호이고, 실제 다음 페이지는 원본 물리 배치의
fall-through와 분기 포인터를 함께 따라야 한다.

현재 수정본은 unit `0`의 `0x0054..0x17C6` 물리 스트림을 원본 주소순으로
한 번만 다시 싼다. 포인터가 있는 88개 페이지는 번역 스트림으로 바꾸고,
엔트리 사이의 378바이트는 위치만 함께 이동하며 바이트를 그대로 보존한다.
따라서 87개 엔트리 간 fall-through, 5개 무포인터 페이지와 92개 분기·진입
포인터가 모두 같은 제어 흐름을 유지한다. 크기순/first-fit 할당은 더 이상
사용하지 않는다.

수정 빌드는 다음 불변식을 검증한다.

- 번역 후보 5,783개 ID는 원본 작업셋과 중복·누락 없이 같은 순서다.
- 줄바꿈 파생본도 원본 작업셋 순서를 그대로 유지한다.
- unit `0`의 고정 시작 엔트리 `ref0000`은 `0x0054`에서 이동하지 않는다.
- `0x0054`의 첫 토큰은 원본과 같은 `0x903F`이며 첫 포인터도
  `0x800A8054`다.
- 첫 네 페이지는 `ref0000@0x0054 → ref0001@0x0098 →
  ref0002@0x00E0 → ref0003@0x010E` 순서다.
- unit `0`의 물리 엔트리 순서 88개와 엔트리 간 fall-through 87개를
  모두 보존한다.
- 엔트리 사이 원본 378바이트와 그 안의 무포인터 페이지 5개가 바이트
  단위로 보존된다.
- 88개 인코딩 스트림과 92개 갱신 포인터가 각각 같은 안정 ID의 스트림을
  가리키는지 재검증한다.

이 정적 검증은 사용자가 확인한 세 실패 원인에 대응한다. 실제 연속 진행과
이름·초상화 복구 여부는 새 CUE를 깨끗하게 부팅해 다시 확인해야 한다.

## 고정 원본 주소 진단 빌드

원본 물리 순서로 압축한 수정본도 실행 화면에서는 `ref0002`가
“씨처럼…”부터, `ref0003`이 “테스트생이.”만 표시됐다. 두 잘린 위치는 각각
이동 전 원본 주소 `0x00F0`, `0x0124`와 정확히 일치한다.

- `ref0002`: 재배치 주소 `0x00E0`, 런타임 관측 시작 `0x00F0` — 앞 8토큰 누락
- `ref0003`: 재배치 주소 `0x010E`, 런타임 관측 시작 `0x0124` — 앞 11토큰 누락

이는 갱신한 92개 포인터 외에 아직 목록화하지 못한 원본 주소 소비자가 있음을
뜻한다. 따라서 순서 보존 재배치 빌드도 실패본으로 판정하며, 재배치 성공의
근거로 사용하지 않는다.

`fixed-original-diagnostic` 정책은 이 가설을 분리하기 위한 의도적 파괴
진단이다. 포인터를 한 건도 바꾸지 않고 각 한국어 스트림을 원본 시작 주소에
쓴다. 원본 슬롯을 넘는 앞 대사를 끝까지 관찰할 수 있도록 높은 주소부터
낮은 주소 순으로 쓰므로, 충돌 시 앞 대사가 다음 대사의 머리를 덮는다.

unit `0`에서는 안전 경계 기준 15개가 초과한다. 첫 충돌은
`ref0003@0x0124`이며 번역 36바이트가 안전한 32바이트보다 4바이트 길다.
따라서 이 빌드에서 기대하는 관측은 다음과 같다.

1. `ref0000..ref0003`은 앞부분 손실 없이 원문 번역 전체가 표시된다.
2. `ref0003` 다음 `ref0004`는 첫 4바이트가 손상돼 정상 표시되지 않는다.
3. 문제가 정확히 여기서 처음 나타나면 고정 주소 가설과 슬롯 길이 초과를
   분리해서 확인한 것이다.

이 이미지는 진행용·배포용이 아니며 첫 충돌 위치 확인에만 사용한다.

## 보호 글리프

한글 배정은 원본 primary 글꼴의 영문·숫자·특수문자 영역을 사용하지 않는다.
`0x000..0x045` 70슬롯과 `0x0E4..0x0E5`의 `ν`·하트 2슬롯, 총 72슬롯을
항상 예약하고 원본 레코드를 같은 인덱스에 바이트 단위로 복사한다. 번역에서
사용하지 않는 문자도 보호 대상이며, 빌드 후 72개 레코드 전체를 원본과 다시
대조한다. unit `0`의 무포인터 페이지가 쓰는 원본 글리프 76슬롯도 동적으로
예약한다. 고정 보호 범위와 중복을 제거하면 원본 레코드를 바이트 단위로
보존하는 슬롯은 총 137개이며, 한글 배정과 충돌하지 않는다.

## 줄바꿈·축약 입력

`scripts/audit_dialogue_reinsertion.py`는 다음 순서로 후보 번역을 판정한다.

1. 17열×3행에 띄어쓰기 경계로 줄바꿈한다.
2. 네 줄이 되지만 단어 내부 분할로 3행에 들어가면 추적 가능한 예외를 적용한다.
3. 그래도 들어가지 않으면 재삽입 차단 상태로 남긴다.

현재 전체 5,783개 후보 중 22개가 단어 분할 예외로 구제됐다. 24개는 여전히
들어가지 않으며, 그중 18개는 최선의 두 줄 경계 공백 제거를 고려해도 51글리프를
초과한다. 이 18개는 다음 별도 작업본에 안정 ID, 원문, 현재 번역, 최소 필요
글리프, 초과량과 빈 축약문 필드로 기록한다.

```text
work/translations/disc1-dialogue-abbreviation-required.json
```

자동 축약은 수행하지 않는다. 나머지 6개는 51글리프 이하이지만 순차적인
17×3 배치가 불가능한 레이아웃 수정 대상이다. 모든 차단 항목은 unit `21..34`에
있으며 챕터 1 빌드에는 영향을 주지 않는다.

## 재현 명령

```bash
.venv/bin/python scripts/build_japanese_glyph_map.py
.venv/bin/python scripts/extract_disc1_dialogue.py
.venv/bin/python scripts/audit_dialogue_reinsertion.py

.venv/bin/python scripts/build_dialogue_chapter_patch.py \
  --start-bin work/extracted/disc1/iso/START.BIN \
  --allbin work/extracted/disc1/iso/ALLBIN.BIN \
  --unit 0 \
  --output-dir work/build/dialogue-u00-order-preserving-nonrelease

.venv/bin/python scripts/build_dialogue_chapter_disc.py \
  --file-build-dir work/build/dialogue-u00-order-preserving-nonrelease \
  --output-dir work/build/dialogue-chapter01-order-preserving-nonrelease

# 원본 시작 주소 고정·길이 초과 위치 확인용 의도적 파괴 진단
.venv/bin/python scripts/build_dialogue_chapter_patch.py \
  --start-bin work/extracted/disc1/iso/START.BIN \
  --allbin work/extracted/disc1/iso/ALLBIN.BIN \
  --unit 0,21 \
  --placement-policy fixed-original-diagnostic \
  --output-dir work/build/dialogue-u00-u21-fixed-original-diagnostic

.venv/bin/python scripts/build_dialogue_chapter_disc.py \
  --file-build-dir work/build/dialogue-u00-u21-fixed-original-diagnostic \
  --output-dir work/build/dialogue-chapter01-u21-fixed-original-diagnostic
```

두 빌더 모두 지원 원본의 강한 해시와 같은 크기를 요구한다. 디스크 빌더는
`config/original-media.json`과 로컬 경로 재정의를 사용해 원본 Track 1과
4트랙 CUE를 다시 검증한다.

## 순서 보존 재배치 실패본의 정적 검증 결과

| 경계 | 결과 |
|---|---:|
| 챕터 1 대사 | 88개, 차단 0 |
| 정적 primary 매핑 | 988자 |
| Galmuri11 생성 | 949자 |
| 원본 글리프 보존 | 39자 |
| 영문·숫자·특수문자 보호 | 72슬롯, 원본과 바이트 차이 0 |
| 무포인터 원문 통과용 보호 | 76슬롯(고정 보호와 중복 포함) |
| 전체 원본 바이트 보존 슬롯 | 137개 |
| 남은 primary 슬롯 | 143개 |
| 첫 엔트리 고정 | `ref0000`, unit `0x0054`, 첫 토큰 `0x903F` |
| 첫 연속 대사 | `ref0000@0x0054` → `ref0001@0x0098` → `ref0002@0x00E0` |
| 물리 fall-through | 엔트리 88개, 관계 87개 전부 보존 |
| 무포인터 페이지 | 5개, 원본 토큰·글리프 보존 |
| 안정 ID/포인터 결합 | 스트림 88개·포인터 92개 전부 일치 |
| `START.BIN` 변경 | 51,941바이트, font 영역 밖 0 |
| `ALLBIN.BIN` 변경 | 5,033바이트, unit 0 text·pointer 밖 0 |
| 변경 raw sector | 47개 |
| `START.BIN` LBA | `279..321` |
| `ALLBIN.BIN` LBA | `9919..9921`, `9924` |
| 계획 밖 sector 변경 | 0 |
| 변경 전·후 sector EDC/ECC | 전부 유효 |
| 출력 재추출 | `START.BIN`·`ALLBIN.BIN` 모두 빌드 결과와 동일 |

Mode 2/Form 1 무결성 계산은 주소를 0으로 두는 이 디스크의 기존 ECC 정책을
각 원본 변경 섹터에서 먼저 검출한 뒤 그대로 재생성한다. 구현은 원본 섹터의
저장된 EDC/P/Q ECC와 전수 대조하므로, 기존의 `--allow-invalid-edc` PoC와 달리
변경 섹터의 무결성 필드가 유효하다.

## 로컬 산출물

```text
work/build/dialogue-u00-order-preserving-nonrelease/
  START.BIN
  ALLBIN.BIN
  primary-korean-glyph-map.json
  manifest.json

work/build/dialogue-chapter01-order-preserving-nonrelease/
  disc1-chapter01-nonrelease-track1.bin
  disc1-chapter01-nonrelease.cue
  manifest.json

work/build/dialogue-u00-fixed-original-diagnostic/
  START.BIN
  ALLBIN.BIN
  primary-korean-glyph-map.json
  manifest.json

work/build/dialogue-chapter01-fixed-original-diagnostic/
  disc1-chapter01-nonrelease-track1.bin
  disc1-chapter01-nonrelease.cue
  manifest.json

work/build/dialogue-u00-u21-fixed-original-diagnostic/
  START.BIN
  ALLBIN.BIN
  primary-korean-glyph-map.json
  manifest.json

work/build/dialogue-chapter01-u21-fixed-original-diagnostic/
  disc1-chapter01-nonrelease-track1.bin
  disc1-chapter01-nonrelease.cue
  manifest.json
```

Track 1 SHA-256:

```text
125eeeb51b7d43f9e537cfcc771d3d6660b4b9f27bbbf207672c21b0aec6617a
```

고정 원본 주소 진단 Track 1 SHA-256:

```text
6abf48c9e092799202eda341940f46c13f64003ae8344e7a027732ece92a8cd5
```

unit `0` + `21` 고정 원본 주소 진단 Track 1 SHA-256:

```text
061c32a605a3d658fb5a6832d552e484be4a34767b7231ce251d91c524f8086c
```

전체 이미지와 추출 파일은 `work/` 아래 비커밋 산출물이다. CUE는 Track 1은
빌드 결과를, Track 2~4는 `roms/`의 검증된 원본 오디오 트랙을 상대 경로로
참조한다.

## 남은 실행 검증

GUI와 Lua 자동화는 사용하지 않는다. 사용자가 DuckStation에서
`dialogue-chapter01-u21-fixed-original-diagnostic`의 CUE를 직접 열고 다음을
확인해야 한다.

1. 깨끗한 부팅으로 챕터 1에 진입한다.
2. `ref0000`의 “드디어 여기까지…” 다음에 `ref0001`의
   “오늘 테스트에 붙으면…”, 이어서 `ref0002`의
   “그 카자미 씨처럼…”이 앞부분 손실 없이 나오는지 확인한다.
3. `ref0003`의 “자네인가? 오늘 테스트생이.”가 끝까지 나오는지 확인한다.
4. 다음 `ref0004`에서 대사가 깨지거나 중단되는지 기록하고 종료한다.
5. 진행 가능하다면 unit `21`의 첫 두 대사 뒤 `ref0002`에서 음성·화자
   상태가 손상되는지 기록한다.

이 검증이 끝날 때까지 상태는
`nonrelease-fixed-original-offset-overflow-runtime-diagnostic`이다.
