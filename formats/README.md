# Kaitai Struct 형식 선언

이 디렉터리에는 정적 분석과 PCSX-Redux 동적 증거로 필드 경계가 확인된 바이너리
형식의 `.ksy` 원본만 둔다. 추측 단계의 구조를 정본처럼 선언하지 않는다.

- `.ksy`: 커밋
- 생성 Python: `work/generated/kaitai/`에 두고 비커밋
- parse dump·RAM/VRAM dump·재조립 바이너리: `work/`에 두고 비커밋
- 검증 wrapper: 재현 가능하고 범용이면 `scripts/`에 커밋

새 형식은 무수정 byte-exact round-trip, 단일 필드 변경 범위, 재파싱 검증을
모두 통과해야 한다. raw CD sector 재계산은 Kaitai serializer에 맡기지 않고
프로젝트의 Mode 2 EDC/ECC 도구를 사용한다. 자세한 절차는
[`docs/reverse-engineering-mcp.md`](../docs/reverse-engineering-mcp.md)의
Kaitai Struct 절을 따른다.
