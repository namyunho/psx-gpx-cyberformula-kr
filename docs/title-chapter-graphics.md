# 타이틀·챕터 카드 그래픽

`START.BIN`의 리테일 타이틀과 챕터 카드는 폰트 문자열이 아니라 indexed 그래픽
에셋이다. Disc 1·2에서 대상 scheduled unit은 바이트가 같다.

## 확인된 위치

| 화면 | START unit | 형식 | 저장 구조 |
|---|---:|---:|---:|
| 실제 리테일 타이틀 | 21, child 2/4 | 4bpp + 16색 CLUT 16뱅크 | child 4의 마지막 256×256 페이지 |
| TGS '98 미사용 타이틀 잔재 | 8 | 8bpp + 256색 CLUT | 384×256 |
| 챕터 카드 | 24..34 | 8bpp + 개별 256색 CLUT | 각 512×256 |

초기에 unit 8을 타이틀로 판단했으나 PCSX-Redux VRAM과 현재 화면을 대조한 결과,
그 데이터는 `TOKYO GAME SHOW '98`용 미사용 화면이었다. 실제 리테일 타이틀은
unit 21 child 4가 VRAM `(768, 0)`에 올리는 512×256 halfword 이미지 가운데,
VRAM x=`960..1023`에 해당하는 마지막 4bpp 256×256 페이지다. CLUT는 child 2의
16×16 BGR555 뱅크이며 GPU primitive가 요소마다 뱅크를 골라 같은 4비트 index를
다른 색으로 표시한다.

따라서 통합 편집 PNG의 palette index를 그대로 ROM에 복사하면 안 된다. 편집
내보내기 과정에서 팔레트가 압축·재정렬될 수 있고, 하나의 256색 PNG 고위 nibble은
ROM에 저장되지 않는 저작용 CLUT 뱅크 정보이기 때문이다.

## 리테일 타이틀 편집본 삽입

현재 승인 편집본은 다음 파일이다.

```text
work/graphics/title-chapter/title/retail-title-screen/
  retail-title-unified-preview-purple-export_import.png
```

삽입기는 네 편집 영역(상단 좌·우 문구, 중앙 일본어 제목, 하단 저작권 표기)만
변경할 수 있게 제한한다. 각 영역의 RGB는 원래 GPU primitive가 쓰는 CLUT 뱅크
안에서 가장 가까운 PS1 BGR555 색으로 되돌린다. `#FF00FF`와 알파 255 미만은
투명 local index 0으로 복원한다. 메뉴, 엠블럼, 버튼 및 child 4 앞쪽 VRAM 열은
원본 바이트를 보존한다.

```bash
.venv/bin/python scripts/build_title_graphics_patch.py \
  --file-build-dir work/build/<입력-파일-빌드> \
  --image \
    work/graphics/title-chapter/title/retail-title-screen/retail-title-unified-preview-purple-export_import.png \
  --output-dir work/build/<출력-파일-빌드>
```

출력 파일 빌드에는 `retail-title-quantized-preview-purple.png`가 생긴다. 이것은
ROM에 들어간 4비트 index를 각 요소의 정규 CLUT로 다시 그린 검수본이다.
manifest는 입력 이미지 해시, 변경 픽셀·바이트 수, 뱅크별 양자화 오차와 허용된
Expected Write 범위를 기록한다.

타이틀은 공용 `START.BIN` 변경이므로 같은 승인 입력으로 Disc 1·2 전체 이미지를
각각 다시 만들고 독립 검증한다. 정적 검증 뒤 실제 타이틀 화면은 PCSX-Redux의
clean boot로 확인해야 하며 save state로 대체하지 않는다.

## 현재 검증 상태

2026-08-04 빌드는 편집본 10,492픽셀을 네 CLUT 뱅크로 재양자화했고 실제
`START.BIN` 변경은 unit 21 child 4의 5,591바이트로 제한됐다. unit 8은 원본
SHA-256 `8553b2804884b5a345eda677e3976c413e44bcfbaf651111e2387f8bab639f3e`을
유지한다. Disc 1·2 Track 1은 각각 596개 변경 sector의 Expected Write,
EDC/ECC와 독립 재추출 검증을 통과했다.

Disc 1 Track 1 SHA-256
`d060ff748a4faea5601ac765fa24701bd7161666ab2b5fc481fb38976f40d88c`을
PCSX-Redux에서 clean boot해 편집한 한국어 타이틀이 정상 출력되는 것을 사용자가
확인했다. 이는 Disc 1의 리테일 타이틀 소비 경로 실행 검증이며, Disc 2의 정적
unit 21 바이트 동등성과 이미지 무결성 검증을 대신하는 것으로 기록하지 않는다.

## 챕터 카드 추출

```bash
.venv/bin/python scripts/extract_title_chapter_graphics.py
```

기존 추출기는 unit 8의 역사적 잔재와 unit 24..34 챕터 카드를 원래 index·CLUT와
함께 내보낸다. unit 8 파일은 리테일 타이틀 삽입 입력으로 사용하지 않는다.
보라색은 투명 편집 경계를 보여 주는 미리보기일 뿐 팔레트에 삽입하는 색이 아니다.
그래픽에 구워진 문자와 배경은 별도 레이어로 분리되어 있지 않다.
