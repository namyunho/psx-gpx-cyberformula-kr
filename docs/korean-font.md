# 한국어 후보 글꼴 검증

## 결론

로컬 `font/`에 제공된 후보는 게임의 14×14 대사 글꼴에 사용하기 적합합니다.
TTF 내부 패밀리 이름은 `Galmuri14`, 스타일은 `Regular`입니다. 함께 제공된
비트맵은 글리프당 16×16, 1bpp이지만 실제 획은 가운데 14×14 영역 안에만
들어갑니다.

| 항목 | 결과 |
|---|---:|
| 글리프 수 | 2,350자 |
| 원본 비트맵 | 16×16, 1bpp, 32바이트/자 |
| 행 저장 순서 | 16비트 big-endian, MSB 우선 |
| 전체 실제 픽셀 범위 | `x=2..14`, `y=1..13` |
| 14×14 바깥 픽셀이 있는 글리프 | 0자 |
| 게임 변환 포맷 | 14×14, 3bpp, 74바이트/자 |

16×16 비트맵에서 상하좌우 1픽셀 테두리를 제거해 `x=1..14`, `y=1..14`를
취하면 획 손실이 없습니다. 1bpp의 꺼진 픽셀과 켜진 픽셀은 각각 게임의 3bpp
값 0과 7로 변환합니다. 이 방식은 보간이 없어 픽셀 글꼴의 획을 그대로
보존합니다.

## 고정 이름 검증

고정 이름 **시바 세이치로**에 필요한 여섯 글자는 모두 문자표에 있습니다.

| 글자 | 후보 인덱스 | 16×16 실제 경계 |
|---|---:|---|
| 시 | 1256 | `(2, 1)..(12, 13)` |
| 바 | 902 | `(2, 1)..(14, 13)` |
| 세 | 1155 | `(2, 1)..(13, 13)` |
| 이 | 1547 | `(2, 1)..(12, 13)` |
| 치 | 1880 | `(2, 1)..(12, 13)` |
| 로 | 703 | `(2, 1)..(13, 12)` |

변환된 여섯 글자는 `6 × 74 = 444`바이트이며 `pack_glyph()`로 다시 읽었을
때 원래 14×14 픽셀과 일치합니다. 최종 화면 가독성은 실제 게임의 글자색,
배경, 합성 효과가 적용된 PoC에서 한 번 더 확인합니다.

## 재현 방법

후보 원본은 배포 저장소에 포함하지 않고 로컬 `font/`에 둡니다.

```powershell
$env:PYTHONPATH = "work/pydeps"
python scripts/korean_font.py `
  font/font-12345a7f7565e4fe.bin `
  --glyph-map font/font-12345a7f7565e4fe_glyph_map.json `
  --text "시바세이치로" `
  --preview work/korean-name-source.png `
  --packed-output work/korean-name-14x14.bin

python scripts/psx_font.py work/korean-name-14x14.bin `
  --offset 0 --start 0 --count 6 --scale 8 --columns 6 `
  --output work/korean-name-game-format.png
```

검증한 로컬 입력 파일의 SHA-256은 다음과 같습니다.

```text
9B5C3DEDE010F95B58A479C0824A11A3BFA05D34BF87A1204B4E3A78AC3BE845  font-12345a7f7565e4fe.bin
D3818C0F2898A3B2D79CCD04EC1E4DE5E8940AA26ABEE261F73E315A44CE8DF9  font-12345a7f7565e4fe.ttf
697EE64E9999A3D58985DA31F0968419EA58211D3BD7AD20C5C9733F26C38406  font-12345a7f7565e4fe_glyph_map.json
946087E2A19AC81C7F837651E37A301D734B9AA5945E29307090FBBFA1FC9474  font-12345a7f7565e4fe_preview.png
```

## 글리프 수와 배포 조건

후보 2,350자를 게임의 기존 글리프 테이블에 통째로 넣을 공간은 없습니다.
따라서 번역문에 실제로 쓰는 한글만 선별해 넣고, 사용할 슬롯 또는 확장된 폰트
저장 위치를 다음 단계에서 결정해야 합니다. 글꼴 자체의 크기 적합성과 별개인
용량·인덱싱 문제입니다.

Galmuri 공식 저장소는 이 글꼴을 SIL Open Font License 1.1로 배포합니다.
폰트 또는 수정·변환된 폰트 자료를 배포물에 포함할 때는 해당 저작권 고지와
라이선스 전문을 함께 포함해야 합니다.

- 공식 저장소: <https://github.com/quiple/galmuri>
- 공식 한국어 라이선스: <https://github.com/quiple/galmuri/blob/main/ofl-ko.md>
