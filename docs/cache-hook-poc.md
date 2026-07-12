# 0x5xxx 한글 캐시 훅 PoC

## 목표

첫 한글 대사 PoC는 원본 일본어 글리프 슬롯을 임시로 덮어썼습니다. 이번 PoC의
목표는 한글 토큰을 `0x5xxx` 대역으로 운반하고, 렌더러 훅이 해당 토큰만 한글
캐시 베이스에서 읽도록 만드는 것입니다.

이 단계는 정적 빌드와 바이트 검증까지 완료했습니다. DuckStation 화면 검증은
아직 수행하지 않았습니다.

## 훅 구조

`SLPS_019.58`의 대사 렌더러는 현재 토큰을 읽은 직후 `0x0180` 비트로 특수
분기를 판정합니다. 따라서 `token & 0x0FFF` 마스크 직전이 아니라
`0x8003271C`에서 먼저 `0x5xxx`를 가로채야 합니다.

| 항목 | 값 |
|---|---:|
| 훅 설치 위치 | `0x8003271C` |
| 훅 코드 위치 | `0x8005A000` |
| 한글 캐시 위치 | `0x80059800` |
| 캐시 글리프 수 | 18 |
| 한글 토큰 범위 | `0x5000..0x5011` |

훅의 동작은 다음과 같습니다.

1. 현재 토큰의 상위 니블이 `0x5`인지 확인한다.
2. 한글이면 `a0 = 0x80059800`으로 설정하고 원본의 12비트 인덱스 계산
   (`0x80032804`)으로 돌아간다.
3. 한글이 아니면 훅으로 덮어쓴 원본 `0x0180` 특수 분기 판정을 재현해
   `0x80032728` 또는 `0x80032788`로 돌아간다.

정적 디스어셈블 확인:

```text
0x8003271C: j       0x8005a000
0x80032720: nop

0x8005A000: andi    v0, v1, 0xf000
0x8005A004: addiu   at, zero, 0x5000
0x8005A008: bne     v0, at, 0x8005a020
0x8005A010: lui     a0, 0x8005
0x8005A014: ori     a0, a0, 0x9800
0x8005A018: j       0x80032804
0x8005A020: andi    v0, v1, 0x180
0x8005A024: bnez    v0, 0x8005a034
0x8005A028: andi    v0, v1, 0x80
0x8005A02C: j       0x80032788
0x8005A034: j       0x80032728
```

## 대사 토큰

첫 대사는 다음 한국어 문장을 사용합니다.

```text
（드디어 여기까지 왔다…
꿈의 팀 「스고 그랑프리」）
```

한글 18자는 첫 등장 순서대로 `0x5000..0x5011`에 배정했습니다. 공백은 기존
빈 글리프 `0x04CD`를 사용하고, 괄호·낫표·말줄임표는 원본 글리프를 유지합니다.

```text
드=0x5000, 디=0x5001, 어=0x5002, 여=0x5003, 기=0x5004, 까=0x5005,
지=0x5006, 왔=0x5007, 다=0x5008, 꿈=0x5009, 의=0x500A, 팀=0x500B,
스=0x500C, 고=0x500D, 그=0x500E, 랑=0x500F, 프=0x5010, 리=0x5011
```

## 재현 빌드

```powershell
$env:PYTHONPATH = "work/pydeps-current;work/pydeps"
python scripts/build_cache_hook_poc.py `
  --slps work/disc1/SLPS_019.58 `
  --allbin work/disc1/ALLBIN.BIN `
  --ttf font/font-12345a7f7565e4fe.ttf `
  --intensity 1 `
  --output-dir work/cache-hook-poc/files `
  --track1 "roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1) (Track 1).bin" `
  --track-output work/cache-hook-poc/disc1-cache-hook-track1.bin `
  --source-cue "roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 1).cue" `
  --cue-output work/cache-hook-poc/disc1-cache-hook.cue `
  --allow-invalid-edc
```

검증된 산출물:

| 산출물 | SHA-256 |
|---|---|
| PoC `SLPS_019.58` | `D89363BDBD05755C20CC75E44885E62481FBAE319C367831F50F7965D8CC64FF` |
| PoC `ALLBIN.BIN` | `39DFC8E0D04F2AB7DEDB73937F985774A1DE17D518B502A8AEB5DDFE91F8A7C7` |

변경된 raw 섹터는 LBA 29, 108, 109, 9919입니다. 이 PoC 이미지는 변경 섹터의
EDC/ECC를 아직 재계산하지 않으므로 **DuckStation 검증 전용**입니다. 실기,
CD-R, ODE 또는 배포 빌드에는 사용하지 않습니다.

## 통과한 정적 검증

- 훅 설치 위치의 원본 바이트를 검증한 뒤에만 패치합니다.
- 한글 캐시와 훅 코드 대상 영역이 0으로 비어 있는지 검증합니다.
- `0x5xxx` 토큰은 캐시 베이스 `0x80059800`으로 분기하고, 비한글 토큰은 원본
  특수 분기 판정으로 돌아가도록 디스어셈블했습니다.
- `scripts/psx_font.py`로 캐시 글리프 18자를 렌더링해 자형을 확인했습니다.
- `python -m unittest discover -s tests -v`가 20개 테스트를 모두 통과했습니다.

## 남은 검증

- DuckStation에서 첫 대사 화면까지 진행해 흰색 한글 두 줄과 주변 UI를 확인해야
  합니다.
- 화면 검증이 통과하면 이 훅 위치와 `0x5xxx` 운반 경로를 본 구현 후보로
  승격합니다.
- 화면 검증이 실패하면 `a0` 폰트 베이스 선택, code cave 생존 여부, I-cache stale
  여부를 GDB로 분리해 확인합니다.
