# Galmuri11 본문 출력 PoC

검증일: 2026-07-24

## 판정 범위

기존 Galmuri14 PoC로 증명한 본문 저장→적재→선택→14×14 렌더 경로에
Galmuri11 프로필을 대입한다. 이번 PoC가 판정할 질문은 다음과 같다.

> 12px로 래스터한 Galmuri11의 실제 11×11 잉크가 게임의 14×14 셀에서
> 중앙 여백을 유지하며 읽을 수 있게 표시되는가?

통과 기준:

1. 첫 대사의 한글 18자가 의도한 자형으로 표시된다.
2. 글자가 좌상단에 붙지 않고 14×14 셀 안에서 일관된 여백을 가진다.
3. 두 줄의 기준선과 글자 간격이 어색하지 않다.
4. 괄호·낫표·말줄임표와 대화창이 손상되지 않는다.

## 기준 입력

| 항목 | 값 |
|---|---|
| 원본 Track 1 SHA-256 | `35E43FBA9C5FFC39AB805ADBC42F13EC3198C888C1C1E9E651408409E041B2A9` |
| 폰트 프로필 | `galmuri11-primary-dialogue-v1` |
| TTF 크기 | 12px |
| 게임 셀 | 14×14, 3bpp, 74바이트 |
| 최종 잉크 합집합 | `(1,1)..(11,11)` |
| 대사 | `（드디어 여기까지 왔다…` / `꿈의 팀 「스고 그랑프리」）` |

## 빌드

```bash
.venv/bin/python scripts/original_media.py verify --cue

.venv/bin/python scripts/build_font_poc.py \
  --start-bin work/extracted/disc1/iso/START.BIN \
  --allbin work/extracted/disc1/iso/ALLBIN.BIN \
  --font-profile config/font-profile.json \
  --full-dialogue \
  --output-dir work/poc-galmuri11/files \
  --track1 "roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1) (Track 1).bin" \
  --track-output work/poc-galmuri11/disc1-galmuri11-track1.bin \
  --source-cue "roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1).cue" \
  --cue-output work/poc-galmuri11/disc1-galmuri11.cue \
  --allow-invalid-edc
```

## 정적 검증 결과

상태: **통과**

| 항목 | 결과 |
|---|---:|
| 삽입 한글 | 18자 |
| 변경된 `START.BIN` 바이트 | 733 |
| 변경된 `ALLBIN.BIN` 바이트 | 30 |
| Track 1 변경 바이트 | 763 |
| 변경 LBA | `277, 279..284, 311, 9919` |
| ISO directory | 원본과 동일 |
| raw Track diff | 선언한 두 파일 쓰기와 정확히 동일 |

산출물 해시:

| 산출물 | SHA-256 |
|---|---|
| `START.BIN` | `076165DD9F2E1588CED1110FE3E6A997EE7B25D5E55B8217086E3187D5251620` |
| `ALLBIN.BIN` | `A521A3EF428E30AE30494EFF0432C9C11544B4B38D4C3487A544B31E202856EF` |
| PoC Track 1 | `35FDA5FACD74A1881475428DB0D44D50022F1AC7A0773F3FAEEE8B8F710A8C98` |

검증 보고서:

```text
work/poc-galmuri11/verification.json
```

삽입된 `START.BIN` 글리프 레코드를 다시 읽어 만든 14×14 셀 미리보기:

```text
work/poc-galmuri11/inserted-dialogue-preview.png
```

이 미리보기는 저장 바이트와 배치를 검증하지만, 게임의 배경·팔레트·합성 결과를
대신하지 않는다.

## 실제 화면 검증

상태: **사용자 확인 대기**

Computer Use와 Lua는 사용자 요청에 따라 사용하지 않는다. DuckStation에서
다음 CUE를 깨끗한 부팅으로 실행하고 첫 대사 화면을 캡처한다.

```text
work/poc-galmuri11/disc1-galmuri11.cue
```

이전 빌드의 save state는 폰트 RAM과 VRAM을 보존할 수 있으므로 사용하지 않는다.
새 CUE로 콜드 부팅하거나 완전 리셋한 뒤 첫 대사에 진입한다.

이 PoC는 변경 sector의 EDC/ECC를 재계산하지 않은 **DuckStation 전용**이다.
실기·CD-R·ODE·배포 빌드로 사용하지 않는다.
