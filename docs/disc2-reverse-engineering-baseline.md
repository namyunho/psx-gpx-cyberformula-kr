# Disc 2 역공학·Disc 1 비교 기준선

검증일: 2026-08-01
대상: `Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 2)`

Disc 2는 별도 대사·폰트 콘텐츠를 가진 변형이 아니다. 원본 Disc 1·2의 ISO
콘텐츠와 raw sector payload를 분리해 비교한 결과, 부트 파일명과 디스크 식별
플래그를 제외한 게임 콘텐츠는 동일하다. 따라서 Disc 1의 번역 정본과 글리프 맵을
Disc 2에도 재사용하되 Disc 2 원본에 고정된 두 플래그와 물리 LBA는 반드시
보존해야 한다.

## 원본 매체

```text
roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 2).cue
roms/Future GPX Cyber Formula - Aratanaru Chousensha (Japan) (Disc 2) (Track 1).bin
```

| 항목 | 값 |
|---|---:|
| 부트 파일 | `SLPS_019.59` |
| Track 1 형식 | `MODE2/2352` |
| Track 1 크기 | 602,081,424바이트 |
| raw sector | 255,987 |
| CRC32 | `2FFDABE1` |
| MD5 | `0a66622840f575a1237d7b7f9b98176a` |
| SHA-256 | `a80c5efdff17d9363ee3990fba0e02a7e872a296f6882b2a7743de90cb52d691` |

Track 2~4의 크기·CRC32·MD5·SHA-256도
`config/original-media.json`에 고정했다. 세 CDDA 트랙은 Disc 1의 같은 번호
트랙과 바이트 단위로 동일하다.

## Disc 1과 동일한 구조

Disc 2에서 전량 추출·압축 해제·왕복 검증한 분모는 Disc 1과 같다.

| 항목 | 수량 |
|---|---:|
| ISO root entry | 19 |
| scheduled 파일 / state | 11 / 1,935 |
| offset-directory child | 4,876 |
| 글꼴 렌더 스트림 | 5,843 |
| 폰트 slot | 2,713 |
| 초상 block | 625 |
| XA / VAB / CDDA / MDEC | 33 / 81 / 3 / 2 |

다음 두 파일은 이름을 제외하거나 그대로 비교했을 때 Disc 1과 SHA-256까지
같다.

| 역할 | SHA-256 |
|---|---|
| 부트 EXE payload (`SLPS_019.58` / `.59`) | `0cbda75255e7f9edbb758ee8b815082c3dd167e7e0e709a5526c17653014fab9` |
| `ALLBIN.BIN` | `6f61295be0ce2d7d8f38b57badc3b1073e5c16ec3fba5ce898f3368051336a0e` |

`ALLBIN.BIN`의 44개 unit과 5,843개 직접 포인터 글꼴 스트림이 모두 같다.
primary 1,229슬롯과 alternate 1,484슬롯의 원본 폰트 SHA-256도 각각
`f798cfd2629e361d49e0f47292881cfb2a7e6f78d979cae7feb818a3943da2ac`,
`ba9a0022ac7bbf6b7304b5e9af1f838fbfcdecbead927e8d0211f3d162558370`로
일치한다.

XA/STR은 raw sector의 MSF와 EDC/ECC 때문에 파일 LBA가 달라지면 raw 해시가
달라진다. `scripts/compare_psx_discs.py`는 절대 MSF와 재생성 가능한 EDC/ECC를
제외하고 sector form, 복제 XA subheader와 전체 Form 1/2 payload를 해시한다.
이 기준에서 `CYBER_XA.STR`, `MOVIE.STR`, `MOVIE2.STR`도 모두 동일하다.

## 실제 차이

`SYSTEM.CNF`는 부트 파일명 `.58`과 `.59`만 다르다. `START.BIN`은 크기와
schedule이 같고 정확히 두 바이트만 다르다.

| 파일 오프셋 | unit / unit 오프셋 | Disc 1 | Disc 2 | 판정 |
|---:|---:|---:|---:|---|
| `0x8ACC` | unit 0 / `0x8ACC` | `00` | `01` | Disc 2 식별값의 두 번째 저장 위치; 직접 소비자 미확정, 보존 필수 |
| `0x3D1000` | unit 39 / `0x0000` | `00` | `01` | 실행 코드가 읽는 디스크 식별 플래그 |

Disc 2 Track 1은 Disc 1보다 정확히 26 sector 크다. `SYSTEM.CNF`, 부트 EXE와
`START.BIN`은 같은 LBA에 있고, `START.BIN` 끝과 `SOUND.BIN` 사이에 Disc 2만
26-sector 간격이 있다. 따라서 `SOUND.BIN`부터 외부 CDDA ISO record까지의 LBA는
Disc 2에서 모두 `+26`이다. 파일 payload는 이 차이와 무관하게 동일하다.

## 디스크 교체 상태 머신

Ghidra의 `SLPS_019.58` 분석은 RAM `0x801F7800` 읽기를
`0x8003FAC8`, `0x8003FB48`에서 찾았다. IDA/Hex-Rays로 같은
`sub_8003F37C`을 확인하면 다음 순서가 나온다.

1. 상태 `0x0D`에서 loader descriptor 156을 읽는다.
2. descriptor 156은 `START.BIN` unit 39를 RAM `0x801F7800`에 적재한다.
3. 상태 `0x0E`는 내부 디스크 상태 비트 `0x8`과 적재한 첫 바이트를 비교한다.
4. `0`이면 Disc 1, `1`이면 Disc 2로 내부 상태를 갱신하고 교체 절차를 계속한다.

이는 `START.BIN + 0x3D1000`이 단순 padding이 아니라 실행 중 소비되는 디스크
식별값임을 증명한다. `+0x8ACC`는 Disc 2에서 같은 값으로 복제돼 있지만 boot
EXE의 직접 xref는 두 정적 도구 모두 찾지 못했다. 포인터 기반 소비 또는 예비
복제일 수 있으므로 의미를 추정해 제거하지 않고 Disc 2 원본값을 유지한다.

## 글리프가 뒤섞여 보인 원인

Disc 2 교체 뒤 한글 글리프 모양은 남지만 문장이 뒤섞이는 현상은 별도 Disc 2
문자표 때문이 아니다. Disc 1 패치가 적재한 한글 primary 폰트는 RAM에 남아 있는
반면, 원본 Disc 2의 동일한 일본어 `ALLBIN.BIN` 글리프 index가 다시 사용되면서
그 index를 한글 슬롯으로 표시한 결과와 일치한다. Disc 2에도 Disc 1과 같은
한국어 `ALLBIN.BIN`·폰트·실행 파일 변경을 적용하면 같은 인코딩을 사용한다.

## Disc 2 빌드 불변식

1. Disc 2 원본 Track 1을 독립적으로 검증하고 그 Track을 기준으로 변경한다.
2. Disc 1의 패치된 `START.BIN`을 통째로 복사하지 않는다.
3. Disc 1 원본→패치 변경 범위만 Disc 2 원본에 적용하고
   `0x8ACC == 1`, `0x3D1000 == 1`을 전후 검증한다.
4. Disc 2의 `SLPS_019.59` 파일명, `SYSTEM.CNF`, 26-sector 간격과 실제 ISO LBA를
   유지한다.
5. 변경 sector만 Disc 2 원본 sector에 적용하고 Mode 2 Form 1 EDC/ECC를
   재계산한다.
6. 완성 Track에서 `START.BIN`, `ALLBIN.BIN`, `SLPS_019.59`을 재추출해 빌드
   입력과 일치시키고, 두 디스크 식별 바이트를 별도 게이트로 확인한다.

## 재현 명령

```bash
.venv/bin/python scripts/original_media.py verify --disc disc2 --cue

.venv/bin/python scripts/extract_disc1_assets.py --disc disc2
.venv/bin/python scripts/decode_disc1_streams.py --root work/extracted/disc2
.venv/bin/python scripts/verify_disc1_extraction.py --disc disc2

.venv/bin/python scripts/psx_layout.py --disc disc2 \
  --output work/analysis/disc2-layout.json
.venv/bin/python scripts/compare_psx_discs.py
```

비커밋 결과는 다음에 생성된다.

```text
work/extracted/disc2/
work/analysis/disc2-layout.json
work/analysis/disc1-disc2-comparison.json
```
