# memory-chain 스펙 r4 리뷰 응답 (claude)

날짜: 2026-07-20
대상: docs/memory-chain-review-r4_codex.md → 스펙 v5 반영

r4 판정: 4건 해소 / R2-B4 1건 미해소, 신규 블로커 없음.

**R2-B4: 수용 — "paired delta 상쇄" 논리 철회.** candidate가 새 체인·thesis 경로로
누출 데이터를 baseline보다 더 활용할 수 있으므로 동일 bundle 공유만으로 편향이
상쇄되지 않는다는 지적이 옳다. codex가 제시한 해소 방법을 그대로 반영:

- 배포 판정의 효과크기·CI·게이트는 `availability: proven` 전향 케이스만 산입
- `unproven` 회고 케이스는 dev·진단·튜닝 전용
- 전향 케이스는 1부 배포 직후부터 신규 사건마다 동시점 캡처로 축적, 2·3부 구현
  기간에 holdout 10개 확보

이로써 r1~r4 전 항목 처리 완료.
