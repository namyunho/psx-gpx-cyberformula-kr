# 한국어 사용 글꼴: Galmuri11

## 확정 결론

본문 한글의 사용 글꼴은 로컬 `fonts/galmuri11/`의 **Galmuri11 Regular**로
확정한다. 빌드의 단일 입력은 `config/font-profile.json`이며, 정확한 파일
해시와 래스터 설정을 검증한 뒤에만 게임 글리프를 만든다.

Galmuri11의 이름, 포인트와 픽셀, 컨테이너 크기는 서로 다른 값이다.

| 구분 | 값 |
|---|---:|
| 로컬 TTF 내부 이름 | `Galmuri11 Regular` |
| 로컬 TTF 버전 | `2.403` |
| 공식 네이티브 표기 | 9pt / 12px |
| TTF 래스터 입력 | 12px |
| 래스터 작업 컨테이너 | 16×16px |
| 실제 본문 잉크 합집합 | 최대 11×11px |
| 게임 저장 셀 | 14×14px |
| 본문+그림자 합집합 | `(1,1)..(12,12)` |
| 게임 표현 | 3bpp, 74바이트/자 |
| 본문 / 그림자 픽셀 | 값 `1` / 값 `6` |

16×16은 `.bin`과 래스터 작업 공간의 저장 컨테이너일 뿐, 게임에 16×16
글리프를 넣는다는 뜻이 아니다. 12px TTF를 16×16 작업 공간의 `(2,1)`에서
그린 뒤 바깥 1px를 잘라내면, 14×14 게임 셀의 본문은
`(1,1)..(11,11)` 안에 들어간다. 여기에 값 `6`의 우하단 1px 그림자를 먼저
그리고 값 `1`의 본문을 덮어쓴다. 최종 합집합도 `(1,1)..(12,12)`라서 셀을
벗어나지 않는다. 이 값의 밝기 역할은 원본처럼 실제 소비자의 CLUT가 정한다.
현재 대사·이름·UI의 CLUT에서는 값 `1`이 흰 본문, 값 `6`이 회색 그림자다.

## 11px 비트맵을 사용하지 않는 이유

같은 폴더의 `font-58c1637749eb0742.bin`은 다음 형식의 참고 자산이다.

- 16×16 컨테이너
- 1bpp
- 글리프당 32바이트
- 2,350자

이 파일의 실제 획은 대체로 9~10×10이며, 2,350자가 2,250개의 고유
비트맵으로 축소된다. 예를 들어 `산/선/신`, `안/언/인`이 같은 비트맵이 된다.
로컬 TTF도 11px로 래스터하면 같은 종류의 충돌이 생긴다.

반면 Galmuri11 TTF를 공식 네이티브 크기인 12px로 래스터하면:

- 2,350자 전부 서로 다른 비트맵
- 14×14 셀 밖 픽셀 0개
- 본문 잉크 합집합 `(1,1)..(11,11)`
- 1px 우하단 그림자를 포함한 합집합 `(1,1)..(12,12)`

가 된다. 따라서 사용 글꼴은 Galmuri11이지만, 빌드 원천은 11px 파생 `.bin`이
아니라 동일 폴더의 TTF 12px 렌더다.

## 고정 프로필

`config/font-profile.json`이 다음 표현값의 단일 기준이다.

```text
profile: galmuri11-primary-dialogue-v1
source: fonts/galmuri11/font-58c1637749eb0742.ttf
source SHA-256: 2C709890595668F7BDB6DF408420FDA957DDE0288E95B31A1CC17A2AB98B4B4F
glyph map SHA-256: 697EE64E9999A3D58985DA31F0968419EA58211D3BD7AD20C5C9733F26C38406
TTF size: 12px
x offset: 1
y offset: 0
target: 14×14, 3bpp, 74 bytes
intensity: 1
shadow intensity: 6
shadow offset: (1, 1)
```

구조 상수인 `START.BIN` 폰트 주소와 자주 조정할 수 있는 표현값은 분리한다.
빌더는 프로필의 원천 해시, 내부 family/style, 2,350개 문자표와 연속 인덱스를
검증한다. 미일치 시 결과를 만들지 않는다.

## 재현

대표 18자를 프로필에서 게임 포맷으로 만들고 원천 배치를 확인한다.

```bash
.venv/bin/python scripts/korean_font.py \
  --font-profile config/font-profile.json \
  --text "드디어여기까지왔다꿈의팀스고그랑프리" \
  --preview work/poc-galmuri11/galmuri11-source-preview.png \
  --packed-output work/poc-galmuri11/galmuri11-dialogue-glyphs.3bpp
```

`--intensity`를 명시하면 비교용 단색 출력이 되며 프로필 그림자를 사용하지
않는다. 실제 패치 빌드는 옵션을 생략해 프로필 전체 표현을 적용한다.

전수 프로필 검증은 기본 테스트에 포함된다.

```bash
.venv/bin/python -m unittest tests.test_korean_font -v
```

## 배포 조건

Galmuri는 SIL Open Font License 1.1로 배포된다. 폰트 소프트웨어나 변환된
폰트 자료를 배포물에 포함할 때는 저작권 고지와 OFL 1.1 전문을 함께 포함한다.

- 공식 저장소: <https://github.com/quiple/galmuri>
- 공식 영문 라이선스: <https://github.com/quiple/galmuri/blob/main/ofl.md>
- 한국어 비공식 번역: <https://github.com/quiple/galmuri/blob/main/ofl-ko.md>

현재 PoC의 정적 삽입과 실제 화면 판정은
[`galmuri11-font-poc.md`](galmuri11-font-poc.md)에 기록한다.
