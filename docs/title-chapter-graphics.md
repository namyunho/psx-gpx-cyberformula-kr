# 타이틀·챕터 카드 그래픽 추출

`START.BIN`에서 타이틀 화면 1장과 챕터 카드 11장을 원래 저장 캔버스 크기로
추출한다. 대상은 Disc 1·2에서 바이트가 같은 공용 scheduled unit이다.

## 확인된 위치

| 화면 | START unit | 형식 | 저장 캔버스 |
|---|---:|---:|---:|
| 타이틀 | 8 | 8bpp indexed + 256색 CLUT | 384×256 |
| 챕터 카드 | 24..34 | 8bpp indexed + 개별 256색 CLUT | 각 512×256 |

타이틀의 로고·메뉴 문자와 챕터 카드의 일본어 제목은 배경과 동일한 index
평면에 구워져 있다. 따라서 손상 없이 꺼낼 수 있는 별도 문자 레이어나 깨끗한
배경 레이어는 없다. 대신 index 평면과 BGR555 CLUT는 별도 파일로 보존한다.

## 실행

```bash
.venv/bin/python scripts/extract_title_chapter_graphics.py
```

스크립트는 읽기 전에 Disc 1·2 Track 1의 크기, CRC32, MD5, SHA-256을 검증한다.
그 다음 대상 unit의 고정 SHA-256과 두 디스크 사이의 바이트 동일성을 검사한다.
기본 출력은 커밋하지 않는 `work/graphics/title-chapter/`이다.

각 화면 폴더에는 다음 파일이 생긴다.

- `original-texture.png`: 저장 캔버스 전체를 유지한 알파 PNG
- `edit-template-purple.png`: 투명 texel을 `#FF00FF`로 표시한 작업 확인본
- `original-screen-320x240.png`: 게임 화면 범위 확인용 crop
- `screen-320x240-purple.png`: 위 crop의 보라색 투명영역 확인본
- `transparent-mask.png`: 투명 texel만 흰색인 마스크
- `index-map.png`: 8비트 index 값을 그대로 담은 회색조 PNG
- `palette.png`: 256색 CLUT 확인표
- `indices.bin`, `palette-bgr555.bin`: 재삽입용 무가공 payload

루트의 `overview-original.png`와 `overview-purple.png`는 12장을 한 번에 확인하는
접촉표다.

보라색은 편집 경계를 눈으로 확인하기 위한 미리보기일 뿐 팔레트에 삽입하는
색이 아니다. 재삽입 시에는 저장 캔버스 크기, index 개수와 256색 CLUT 총량을
그대로 유지해야 한다. `320×240` 파일은 확인용 crop이므로 원자료를 대체하지
않는다. 상세 source unit, child, VRAM 좌표와 파일 경로는 출력의
`manifest.json`이 정본이다.

## 편집한 타이틀 재삽입

384×256 전체 캔버스를 편집한 뒤 다음처럼 기존 파일 빌드 위에 적용한다.

```bash
.venv/bin/python scripts/build_title_graphics_patch.py \
  --file-build-dir work/build/<입력-파일-빌드> \
  --image work/graphics/title-chapter/title/title-screen/edit-template-purple-import.png \
  --output-dir work/build/<출력-파일-빌드>
```

편집 프로그램이 PNG 팔레트 순서를 다시 매기므로 PNG의 index 바이트를 그대로
복사하면 안 된다. 삽입기는 각 픽셀의 RGB를 원본 PS1 BGR555 CLUT 색과 정확히
대조해 원래 index로 되돌린다. 시각적으로 바뀌지 않은 좌표는 중복색이 있어도
원래 index 바이트를 보존하고, `#FF00FF` 또는 알파 0인 픽셀만 투명 index 0으로
복원한다. 256색 CLUT와 컨테이너 크기·헤더·패딩은 변경하지 않는다.

현재 타이틀은 Disc 1·2 공용 `START.BIN` unit 8이므로, 이 변경을 포함한 전체
이미지는 두 디스크를 같은 파일 빌드에서 각각 다시 만들어 검증해야 한다.
