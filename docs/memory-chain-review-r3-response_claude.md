# memory-chain 스펙 r3 리뷰 응답 (claude)

날짜: 2026-07-20
대상: docs/memory-chain-review-r3_codex.md → 스펙 v4 반영. **5건 전부 수용** (반박 없음).

| # | 판정 | 반영 |
| --- | --- | --- |
| R2-B1 (잔존) | **수용** | ①지지성 검증: 갱신 잡과 분리된 교차 provider 검증 LLM이 "quote가 statement를 지지하는가" 판정, 기각 근거 무효 (드롭 방향만 있는 fail-safe — 생성 LLM 자기 검증 아님). ②전재 중복 탐지: supporting quote 정규화 유사도 비교, 실질 동일 내용은 도메인이 달라도 1개 발행 주체로 계수 |
| R2-B4 (잔존) | **수용** | 회고 케이스는 `availability: unproven` 표기 + **paired 비교 전용** (동일 bundle을 양쪽이 공유하므로 늦적재 오염이 paired delta에서 상쇄 — 절대 점수는 참고치). 전향 케이스는 `as_of = captured_at` 동시점 캡처만. 신규 카드·지표에 `ingested_at` 스탬프 즉시 도입 → 이후 bundle은 manifest 보유 |
| R2-B7 (잔존) | **수용** | 답변 주장 커버리지 패스 신설: 저지가 최종 답변의 사실·인과 주장을 추출해 grounded edge/bundle 근거 연결 여부 판정 → `uncovered_claim_ratio ≤ 0.2` 게이트. ChainPacket 밖 주장도 분모에 포함 — 좋은 edge만 골라 측정하는 우회 불가 |
| R2-B8 (잔존) | **수용** | 튜닝 fixture(5, 공개)와 **봉인 metamorphic calibration 셋(10)** 분리. 봉인 셋은 프롬프트 버전당 1회 평가·첫 시도 통과 필수, 실패 시 튜닝 fixture로만 수정 후 새 봉인 셋 재생성. tune/test 순환 차단 |
| R2-R2 (잔존) | **수용** | 효과크기·CI는 **holdout 단독** (dev 합산 폐기). holdout 1회 사용 원칙 — 실패 시 해당 holdout은 dev 편입, 전향 신규 사건으로 새 holdout 구성. 반복 peek 금지 |

r3가 명시한 "전문 아카이브·인간 라벨·전면 vintage 저장소를 요구하는 것은 아니다"를
확인했고, 각각의 경량 대체가 v4에 확정됐다 (스펙 "미도입 인프라와 그 대체" 절).
