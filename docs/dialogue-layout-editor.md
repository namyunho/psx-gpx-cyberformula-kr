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

## 실행

Homebrew Python 3.14에서는 Tk 모듈이 별도 패키지다.

```bash
brew install python-tk@3.14
.venv/bin/python scripts/dialogue_layout_editor.py
```

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

GUI를 열지 않고 입력 구조와 현재 17×3 초과 수를 확인:

```bash
.venv/bin/python scripts/dialogue_layout_editor.py --check
```

## 기능

- 17열×3행 셀 미리보기
- 행별 사용량, 표시 글리프 합계와 초과 경고
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
