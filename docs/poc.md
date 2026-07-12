# 첫 한글 가시성 PoC

## 목표와 현재 상태

목표는 한글 한 글자가 원본 Disc 1의 본문 데이터, 내장 폰트 공급 경로, 원본
14×14 렌더러를 거쳐 실제 화면에 표시되는지 확인하는 것입니다.

현재는 다음 준비와 정적·RAM 검증까지 완료했습니다.

- [x] TTF `Galmuri14 Regular`에서 `한`을 14×14, 3bpp 74바이트로 생성
- [x] 대사 시점에 안전한 완전한 빈 글리프 슬롯 `0x4CD` 확정
- [x] 첫 대사 토큰을 `0x03B7`에서 `0x04CD`로 바꾸는 동일 크기 빌드
- [x] 수정 Track 1에서 `START.BIN`과 `ALLBIN.BIN`을 재추출해 해시 검증
- [ ] 수정 이미지로 첫 대사를 다시 열어 화면의 `한`과 주변 표시를 확인

화면 검증 전이므로 최소 가시성 게이트는 아직 통과 처리하지 않습니다.

## 표적

처음 확인한 대사의 `憧`을 `한`으로 바꿉니다.

```text
（ようやくここまできた…憧れの
```

| 항목 | 값 |
|---|---:|
| 원본 텍스트 토큰 | `ALLBIN.BIN + 0x6E = 0x03B7` |
| PoC 텍스트 토큰 | `0x04CD` |
| PoC 글리프 | `START.BIN + 0x30342` |
| PoC 글리프 RAM | `0x8002AD42` |
| 글리프 크기 | 74바이트 |

대사 시점의 파일/RAM 연속 일치는 `START.BIN + 0x1A000`부터
`0x16393`바이트입니다. `0x4CD` 슬롯의 끝은 이 범위 끝보다 7바이트 앞이므로
한 슬롯 전체가 안전하지만, 다음 슬롯은 실행 코드와 겹칩니다.

## RAM 사전 실험

실행 중 RAM의 원본 `0x03B7` 글리프가 디스크의 해당 74바이트와 완전히
일치함을 확인했습니다. 이후 `gdb_write.py`로 같은 주소와 `0x0072` 슬롯에
`한` 글리프를 써서 재읽기 검증까지 통과했습니다. 당시 화면은 이미 VRAM에
그려진 대사를 유지하고 있어 기존 픽셀은 갱신되지 않았습니다.

이 결과는 다음 두 가지를 구분합니다.

- 증명됨: 폰트 RAM 주소 계산과 74바이트 주입 경로
- 미증명: 새로 렌더링된 본문 화면에서의 실제 한글 표시

## 재현 빌드

다음 명령은 원본에서 같은 크기의 중간 파일을 만들고, 로컬 Track 1 복사본의
변경 섹터 두 곳만 수정합니다. 원본 오디오 트랙은 PoC CUE와 같은 로컬 작업
폴더로 복사하며 원본에는 쓰지 않습니다.

```powershell
$env:PYTHONPATH = "work/pydeps"
python scripts/build_font_poc.py `
  --start-bin work/disc1/START.BIN `
  --allbin work/disc1/ALLBIN.BIN `
  --ttf font/font-12345a7f7565e4fe.ttf `
  --character "한" `
  --output-dir work/poc/files `
  --track1 "roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1) (Track 1).bin" `
  --track-output work/poc/disc1-poc-track1.bin `
  --source-cue "roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1).cue" `
  --cue-output work/poc/disc1-poc.cue `
  --allow-invalid-edc
```

검증된 결과:

| 산출물 | SHA-256 |
|---|---|
| PoC `START.BIN` | `6783B864CBD790B497E3F4558D84AE09E5EF89F8D150DA5087AAD7C032D2C6FE` |
| PoC `ALLBIN.BIN` | `3D822DC5578CC02FFA6ECBC3E2E518E8384240758CC70C494C5B122DE6899016` |

변경된 raw 섹터는 LBA 321과 9919입니다. 이 PoC 이미지는 변경 섹터의
EDC/ECC를 아직 재계산하지 않으므로 **DuckStation 검증 전용**입니다. 실기,
CD-R, ODE 또는 배포 빌드에는 사용하지 않습니다.

## 통과 기준과 남은 범위

첫 대사에서 `憧` 위치에 `한`이 올바른 모양과 색으로 표시되고, 주변 일본어,
대화창, 장면 진입·이탈이 깨지지 않아야 최소 가시성 게이트를 통과합니다.

이 PoC가 통과해도 다음 항목은 별도로 남습니다.

- 전체 한글 코드·슬롯 공급 방식
- 수백 자 폰트의 저장 위치와 적재 경로
- 전체 번역문 수용량과 포인터 재배치
- 이름 선택 화면의 고정 이름 표시·저장·재표시
- 실기용 Mode 2 Form 1 EDC/ECC 재계산
