# Disc 1 전량 추출·압축 해제

검증일: 2026-07-24
출력 루트: `work/extracted/disc1/`

원본 Disc 1을 수정하지 않고, 현재 구조 분석으로 경계를 증명할 수 있는 데이터를
전량 추출했다. 원본 유래 산출물은 모두 `work/` 아래에 있으며 커밋하지 않는다.

## 실행

```bash
.venv/bin/python scripts/extract_disc1_assets.py
.venv/bin/python scripts/decode_disc1_streams.py
.venv/bin/python scripts/verify_disc1_extraction.py
```

첫 단계는 byte-exact 원본·컨테이너 분리와 이미지 포맷 해독, 두 번째 단계는
MDEC/XA/VAB의 실제 코덱 해제, 세 번째 단계는 원본·출력 수량과 해시를 검증한다.

## 출력 구조

```text
work/extracted/disc1/
├── iso/                 ISO 9660의 2,048바이트 논리 파일
├── scheduled/           11개 scheduled 파일의 1,935개 state
├── children/            offset-directory child 4,876개
├── streams/
│   ├── raw/             XA/STR extent의 원본 2,352바이트 sector
│   ├── xa/              file/channel/coding별 XA stream
│   └── cdda/            CUE Track 2~4 raw CDDA
├── decoded/
│   ├── text/            u16le font-rendered stream
│   ├── fonts/           3bpp raw glyph와 PNG
│   ├── portraits/       CLUT+4bpp raw block과 PNG
│   ├── vram/            증명된 palette 조합별 PNG
│   └── sound/
│       ├── vab/          .vh/.vb/.vab
│       └── seq/          Sony SEQ event stream
├── decompressed/
│   ├── xa/              PCM16 WAV
│   ├── vab/             VAG subsong별 PCM16 WAV
│   ├── cdda/            PCM16 WAV
│   └── video/           FFV1 lossless video + PCM audio
└── manifests/           경계·해시·디코드·검증 보고서
```

## 전량 수량

### 컨테이너와 현지화 자산

| 항목 | 수량 |
|---|---:|
| ISO root entry | 19 |
| Track 1에서 추출한 ISO 파일 | 16 |
| Track 2~4를 가리키는 외부 CDDA record | 3 |
| scheduled 파일 | 11 |
| scheduled state | 1,935 |
| offset-directory child | 4,876 |
| font-rendered text stream | 5,843 |
| 정의된 폰트 slot | 2,713 |
| 초상 block | 625 |
| 구조적으로 증명된 VRAM record | 2,462 |
| palette별 디코드 PNG | 2,879 |
| Sony SEQ | 1,738 |

### 오디오·영상 해제

| 입력 | 해제 결과 |
|---|---:|
| XA ADPCM | 33 PCM16 WAV |
| Sony VAB | 81 bank / 1,663 PCM16 WAV |
| CDDA | 3 PCM16 WAV |
| `MOVIE.STR` | 320×224, 4,266 frame FFV1 |
| `MOVIE2.STR` | 320×192, 3,428 frame FFV1 + PCM audio |

설치해 고정한 디코더는 FFmpeg 8.1.2와 vgmstream r2117이다.

## CD-XA 추출 경계

ISO directory size는 2,048바이트 logical block 단위지만 XA Form 2는 한
sector에 2,324바이트 user data와 file/channel/submode/coding subheader를
가진다. 따라서 `.STR`을 일반 ISO 파일처럼 이어 붙이면 sector 경계와 audio
tail이 손실된다.

다음 세 파일은 두 표현을 모두 보존한다.

- `iso/*.STR`: ISO 2,048바이트 logical 표현
- `streams/raw/*.raw2352`: sync, duplicated XA subheader, EDC/ECC를 포함한
  원본 sector extent

실제 FFmpeg/vgmstream 입력은 후자다. `CYBER_XA.STR`은 32개 mono 18.9kHz
XA channel, `MOVIE2.STR`은 한 개의 stereo 37.8kHz XA channel을 가진다.

## SOUND.BIN

1,900개 child의 분류:

| 종류 | 수량 | 출력 |
|---|---:|---|
| `pBAV` VAB header | 81 | `.vh` |
| 다음 state의 VAB body | 81 | 유효 구간 `.vb` |
| `pQES` SEQ | 1,738 | `.seq` |

VAB header의 total-size 필드에서 body 유효 길이를 계산한다. 81개 body 모두
그 뒤가 0 padding이고, header+body가 total-size와 정확히 일치한다. 각 bank의
VAG 수만큼 vgmstream으로 해제한 결과는 총 1,663개 PCM16 WAV다.

SEQ는 압축 데이터가 아니라 Sony 이벤트 스트림이다. 의미를 바꿀 수 있는 MIDI
변환을 “압축 해제”로 가장하지 않고 원본 `.seq`를 보존한다.

## 그래픽과 폰트

- 폰트: 14×14, 3bpp, 74바이트 고정 record를 grayscale PNG로 해독
- 초상: 32바이트 CLUT + 48×56 4bpp를 RGBA PNG로 해독
- VRAM state: state 안에서 구조적으로 증명된 4bpp/8bpp CLUT와 이미지
  rectangle만 조합
- direct rectangle: PS1 BGR555 16bpp로 해독

팔레트가 없거나 소비 형식이 증명되지 않은 record에는 임의 팔레트나 압축기를
적용하지 않는다. 구조 분류상 `unknown`이던 SOUND child 1,900개는 위 VAB/SEQ로
모두 해결됐다. 남은 886개(`AVM_MAP` 839, `MACHINE` 46, `START` 1)는
control/metadata 또는 비시각 데이터로 byte-exact raw 보존한다.

## 검증 결과

`manifests/verification.json`의 최종 상태는 `passed`다.

- Form 1 ISO 파일 13개가 기존 추출 원본과 일치
- XA/STR raw extent 3개가 Track 1 원본 sector와 일치
- 1,935개 state를 다시 이어 붙인 11개 파일이 원본 SHA-256과 일치
- XA PCM frame 수가 sector count와 coding mode의 기대값과 일치
- 81개 VAB의 출력 sample 수가 header의 VAG 수와 일치
- CDDA PCM frame 수가 raw byte 수와 일치
- 두 MDEC 입력·FFV1 출력의 해상도와 frame 수가 일치

주 매니페스트:

```text
work/extracted/disc1/manifest.json
work/extracted/disc1/manifests/decompressed-streams.json
work/extracted/disc1/manifests/verification.json
```
