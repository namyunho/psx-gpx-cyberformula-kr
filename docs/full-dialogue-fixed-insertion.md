# 전체 대사 정위치 진단 빌드

## 목적과 범위

현재 번역 후보의 내용과 줄바꿈을 자동 수정하지 않고, 직접 포인터 대상으로
추출된 대사 5,783개를 각각의 원본 시작 주소에 인코딩한다. 대상은
`ALLBIN.BIN` scheduled unit `0..34` 전체이며 스토리, 일반 레이스,
진단/시험, 정적 로더 도달이 확인되지 않은 휴면 엔트리를 모두 포함한다.

이 빌드는 재배치 가능성을 주장하지 않는다. 포인터는 원본 값을 유지하고,
각 엔트리의 `entries[].ko`를 원본 제어 shell 사이에 넣는다. 후보의 공백,
문장부호, 줄바꿈을 자동 reflow하거나 축약하지 않는다. `{name:surname}`과
`{name:given}`만 고정 이름인 `시바`, `세이치로`의 실제 표시 글리프로
확장한다.

## 빌드 입력

| 입력 | 적용 |
|---|---|
| `work/translations/disc1-dialogue.json` | 안정 ID, 원본 바이트, 주소와 제어 shell |
| `work/translations/disc1-dialogue-ko-candidate.json` | `entries[].ko` 5,783개 |
| `work/analysis/disc1-layout.json` | ALLBIN unit `0..34` 저장 경계 |
| `work/analysis/disc1-translation-reinsertion-audit.json` | 보호 구조 충돌 기준선 |
| `data/glyph-map.json` | 원본 primary 글리프와 보호 기호 대응 |
| `config/font-profile.json` | Galmuri11 14×14 변환 프로필 |

이번 산출물이 읽은 번역 후보 SHA-256은
`ed74fd1aa67cc1fc5d589369df20ab18fe0a59f24f3d72eeb30050bd0e30772f`이다.
후보 파일을 편집해 다시 빌드하면 매니페스트의 입력 해시와 결과 해시도
달라져야 한다.

## 재생성

```bash
.venv/bin/python scripts/build_dialogue_chapter_patch.py \
  --start-bin work/extracted/disc1/iso/START.BIN \
  --allbin work/extracted/disc1/iso/ALLBIN.BIN \
  --all-dialogue \
  --placement-policy fixed-original-exact-diagnostic \
  --allow-pointerless-gap-glyph-loss \
  --output-dir work/build/dialogue-all-fixed-original-exact-diagnostic

.venv/bin/python scripts/build_dialogue_chapter_disc.py \
  --file-build-dir work/build/dialogue-all-fixed-original-exact-diagnostic \
  --output-dir work/build/dialogue-all-disc-fixed-original-exact-diagnostic
```

`--allow-pointerless-gap-glyph-loss`는 비배포 exact 진단 정책에서만 허용된다.
unit 전부의 엔트리 사이에 남은 일본어 글리프 563슬롯을 한글 988자와 함께
byte-exact로 보존하면 primary 1,229슬롯을 초과하기 때문이다. 따라서 직접
엔트리를 우선하고, 아직 추출·번역되지 않은 무포인터 연속 페이지는 잘못된
글리프로 표시될 수 있음을 매니페스트에 기록한다.

## 정적 결과

| 항목 | 결과 |
|---|---:|
| 선택 unit | 35 (`0..34`) |
| 계획한 직접 엔트리 | 5,783 |
| primary 매핑 문자 | 988 |
| 확장 후 17글리프 행 한도 위반 | 283 |
| 그중 51글리프 총량 초과 | 17 |
| 원본 안전 슬롯 초과 | 1,379 |
| 최종 바이트가 온전한 엔트리 | 4,450 |
| 앞 엔트리에 일부 덮인 엔트리 | 1,333 |
| 화자·음성 선두 제어 손상 | 1,236 |
| 보호 이름 토큰 불일치 | 1 |

보호 이름 토큰 불일치는
`disc1/allbin/u15/event_page/ref0010`이다. 이 진단은 사용자가 승인한 현재
후보를 그대로 관찰하기 위해 빌드를 차단하지 않고 매니페스트에 예외로 남긴다.

원본 주소가 겹치면 낮은 원본 주소의 앞 대사를 끝까지 보존한다. 따라서 모든
번역 스트림을 계획하고 각 원본 시작점에 썼더라도, 최종 `ALLBIN.BIN`에서
1,333개 후속 스트림은 일부가 앞 대사로 덮인다. 이 정책은 첫 실제 충돌을
관찰하기 위한 것이며 전체 진행 가능한 저장 정책이 아니다.

## u00·u21 검수 반영

사용자가 `u00`과 `u21`의 17×3 표시 한도 초과 문장을 교정한 뒤 현재 후보로
다시 빌드했다. 두 unit 모두 행 폭·행 수·51글리프 검사 위반은 0건이다.

표시 한도와 원본 저장 슬롯은 서로 다른 제약이다. 문장 레이아웃 교정 뒤에도
제어 shell을 포함한 인코딩 바이트가 다음 원본 시작점까지의 안전 범위를
넘는 항목은 `u00` 16개, `u21` 21개 남아 있다.

| unit | 첫 저장 슬롯 충돌 | 초과 |
|---|---|---:|
| `u00` | `disc1/allbin/u00/event_page/ref0003` → `ref0004` | 4바이트·2토큰 |
| `u21` | `disc1/allbin/u21/voice_event/ref0001` → `ref0002` | 6바이트·3토큰 |

따라서 이번 수정은 두 unit의 화면 레이아웃 위반을 해소했지만, 고정 원본 위치
정책의 제어 데이터 손상까지 해소한 것은 아니다.

## 매체 검증

| 항목 | 결과 |
|---|---|
| `START.BIN` 변경 | 54,590바이트, 14,088 범위 |
| `ALLBIN.BIN` 변경 | 221,833바이트, 48,466 범위 |
| 변경 raw sector | 235 |
| 실제 변경 sector와 Expected Write 계획 | 일치 |
| 변경 전 sector EDC/ECC | 전부 유효 |
| 변경 후 sector EDC/ECC | 전부 유효 |
| 출력 ISO에서 START/ALLBIN 재추출 | 파일 빌드와 byte-exact 일치 |
| Track 1 크기 | 602,020,272바이트, 원본과 동일 |

출력 Track 1 SHA-256은
`28379eb70d4c709b92bc84d01700356009f200d0b37482e14f7e48de7b6e4f41`,
CUE SHA-256은
`d58606fe9304f177be61af82555c77f9238fc915df23684473efad6c675cc7b6`이다.

```text
work/build/dialogue-all-disc-fixed-original-exact-diagnostic/
├── disc1-all-dialogue-nonrelease-track1.bin
├── disc1-all-dialogue-nonrelease.cue
└── manifest.json
```

## 판정과 다음 단계

이 산출물은 **비배포 전체 충돌 진단 이미지**다. 정적 쓰기와 매체 무결성은
통과했지만 다음 조건 때문에 통합 패치나 플레이 가능 빌드로 판정하지 않는다.

- 1,379개 원본 슬롯 충돌을 해소하지 않았다.
- 1,236개 후속 엔트리에서 화자·음성 제어 손상이 예상된다.
- 무포인터 연속 페이지 모집단과 번역이 완성되지 않았다.
- 17×3 위반 283개와 51글리프 초과 17개는 사람 검수·축약이 필요하다.
- 이름 토큰 불일치 1개를 사람이 판정해야 한다.
- 실제 GUI 진행 검증은 사용자가 생성된 CUE로 수행해야 한다.

후보 검수가 진행되면 동일 명령으로 다시 빌드해 입력 해시와 충돌 수가 줄었는지
대조한다. 전체 진행용 저장 정책은 번역 축약으로 모든 고정 슬롯을 만족시키거나,
런타임이 실제로 소비하는 모든 연속 페이지·참조를 포함한 재배치 구조를 별도로
확정한 뒤 선택한다.
