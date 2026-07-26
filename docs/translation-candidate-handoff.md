# Disc 1 번역 후보 인계

## 현재 상태

`disc1-dialogue-ko-candidate.json`과
`disc1-glossary-candidates.json`은 Notion AI의 GPT-5.5로 한 번에
약 200~300건씩 처리한 기계 번역 후보이다. 컨텍스트 압축을 거친 대량
작업이므로 **아직 승인된 번역으로 취급하지 않는다.**

원문 전문이 들어 있는 입력 파일은 저작물·추출물 보존 정책에 따라
`work/translations/`에만 둔다. Git에는 다음 검토용 자료만 기록한다.

- `data/translations/disc1-dialogue-ko-candidate.json`: 안정 ID와 한국어
  후보만 담은 오버레이
- `data/translations/disc1-glossary-candidates.json`: 고유명사·팀·머신·용어
  후보와 근거 ID
- `data/translations/disc1-translation-candidate-audit.json`: 재현 가능한
  기계 검증 결과와 검토 대기열
- `scripts/import_translation_candidates.py`: 위 자료를 다시 검증하고
  생성하는 임포터

## 기계 검증 결과

- 대사 ID 5,783건 일치: 누락·추가·중복 0건
- 보호 필드(`id`, `jp`, `max_glyphs`) 변경 0건
- 빈 한국어 후보 및 일본어 문자 잔존 0건
- 확인된 51글리프 제한 4,022건 중 초과 0건
- 제한 미확인 대사 1,761건
- 용어 97건: high 52, medium 43, low 2
- 용어 ID 중복·잘못된 근거 ID·동일 원어의 복수 표기 충돌 0건

이는 형식과 길이만 통과했다는 뜻이다. 오역, 누락, 인물 말투, 이름
동일성, 표기 일관성은 기계 검증 범위가 아니다.

## u00/u21 수작업 교정 기준선

2026-07-27에 `work/` 편집본의 unit `0`과 `21` 156개만 추적 오버레이에
선택 동기화했다. 기존 추적본과 실제 한국어 문구가 달라진 항목은 66개이며,
두 unit 밖의 미검증 편집 61개는 포함하지 않았다.

선택 동기화한 오버레이로 재감사·재빌드한 결과는 사용자가 실행 검증한
파일과 바이트 단위로 같다.

- `START.BIN` SHA-256:
  `641384a1f8c8a66204438fbf62fbeedf420cac7319e9040ddaaba85faff4e31a`
- `ALLBIN.BIN` SHA-256:
  `a0318e0a0122d540f132cf51085a87f4cfc63be9efc1615a48c5637b3cbd7ee9`
- unit `0`: 88개, 안전 슬롯 초과·겹침 0개
- unit `21`: 68개, 안전 슬롯 초과·겹침 0개

따라서 Git의 `data/translations/disc1-dialogue-ko-candidate.json`은
`u00/u21`에 대해서는 현재 수작업 레이아웃 입력을 재현한다. 나머지 unit은
여전히 기계 번역 후보이며 같은 승인 상태로 간주하지 않는다.

## 다음 작업

1. 용어집을 먼저 승인한다. 특히 medium/low 45건과 low인
   `term-0020`, `term-0021`을 실제 등장인물·공식 표기와 대조한다.
2. 승인 용어집과 대사 후보 사이의 표기 편차를 찾아 일괄 수정 후보로
   만들되 자동 확정하지 않는다.
3. 안정 ID를 변경하지 말고 대사를 구간별로 의미·누락·말투 관점에서
   검수한다.
4. `max_glyphs: 51`에 해당하는 대사는 최종 문구를 다시 길이 검증한다.
   제한 미확인 1,761건은 렌더러 구조 확인 전까지 별도 대기열로 둔다.
5. 검수 승인 상태를 명시적으로 기록하기 전까지 전 항목을
   `needs_review`로 취급한다.

재생성 명령:

```sh
python3 scripts/import_translation_candidates.py
```
