# 수집 파이프라인 GIGO 감사 (2026-07-22)

리포트 중간과정 리뷰에서 발견된 단서들의 근본 원인 추적. 방법: codex 증거 수집(읽기 전용, 1,800s) + 직접 검증(상류 API 대조 포함). 결론: **수집 연속성은 건강, 그러나 "초록불=fetch 성공"일 뿐 데이터 의미 검증은 없음** — 의미 오염 3건, 운영 공백 3건.

## 판정 요약

| # | 항목 | 판정 | 근본 원인 | 조치 |
|---|---|---|---|---|
| 1 | SaveTicker firehose 연속성 | ✅ 건강 | scan_hwm 173576=anchor, backlog 0, pending 0, 무손실 (state.json) | — |
| 2 | 뉴스 본문 50% 빈 값 | ✅ 수집기 정상 — **상류 실체** | 원본 API가 content=null인 헤드라인 속보 다수 (id 173572 직접 대조 확인). `_to_text`는 블록/문자열 모두 처리 정상 | 리포트: title-only 근거는 load-bearing 단독 근거 금지(검증 스윕이 사실상 수행 중). 표기 강화는 선택 |
| 3 | 미래 ts 관측 (memory_price 2026-09 HBM 16.5$/GB) | 🔴 의미 오염 | 전망치(forecast)가 실측 관측으로 저장됨 — stanford_dam/supply 계열 수집기가 구분 플래그 없이 적재 | 리포트 측 cutoff가 방어 중(확인). 수집기에 `meta.kind=forecast` 표기 필요 → **수집기 담당 세션 과제** |
| 4 | 가격 metric에 원가 구성비 혼입 (HBM cost share % / spend $B가 memory_price 아래) | 🔴 의미 오염 | 수집기가 이종 관측을 같은 metric명으로 적재 | anchor 쪽은 top-8+단위 표기로 완화 완료. metric 분리(`hbm_cost_share`)는 수집기 과제 |
| 5 | 낡은 시리즈 잔존 (McCallum historical 2024-07) | 🟡 정상 데이터·소비 주의 | historical 시리즈는 갱신 안 되는 게 정상 | 리포트 anchor 365d 신선도 지평선 적용 완료 |
| 6 | capex 단위 혼재 (`b_local`: 하이닉스 7865.37 vs MU 7.83) | 🟡 표기 문제 | 로컬 통화 billions — 통화 라벨 없음. 시리즈별(회사별) delta는 유효 | anchor 표시에 unit 포함 중. 통화 명시는 수집기 과제 |
| 7 | ECOS D램 수출물가지수 | 🔴 미수집 | `ecos_api_key` 미설정 (status="missing_key"로 정직 표기 중) | **키만 넣으면 됨** — 사용자 액션 |
| 8 | sunset 공백 (07-07~07-21 뉴스) | 🟡 확정 공백 | 구 API sunset~firehose 재구현 사이 — 복구 불가(상류 소멸) | 기록만. 카드(구글뉴스)는 해당 기간 정상 |
| 9 | RSS trendforce | 🟡 지속 실패 | feed_fail (status 정직 표기 중) | 수집기 과제 (대체 피드 탐색) |
| 10 | sdk_downloads 429 | 🟡 rate limit | pypistats 429 (degraded 표기 중) | 백오프/캐시 — 수집기 과제 |
| 11 | 카드/캘린더/지표 freshness | ✅ 정상 | 19개 metric 최신 ts가 주기 대비 정상 범위 (월/분기 지표 지연은 미발표) | — |

## 시스템 관찰

- **"초록불" 의미의 한계**: status.json의 ok는 "fetch가 돌았다"이지 "저장된 데이터가 의미상 옳다"가 아님. 미래 ts·이종 혼입·빈 본문은 전부 초록불 아래에서 발생. → 수집기 쪽에 의미 검증(스키마+범위+시제) 게이트가 필요하다는 것이 이번 감사의 핵심 교훈.
- **리포트 파이프라인의 방어층이 실제로 일함**: cutoff(미래 ts 차단)·신선도 지평선(낡은 시리즈)·수치 스윕(비귀속 수치)·수집 건강 패널이 이번 감사 항목 대부분을 소비 시점에 가시화/차단.

## 남은 액션 (수집기 담당)

1. forecast 관측에 `meta.kind="forecast"` 플래그 (항목 3)
2. `hbm_cost_share`/`hbm_spend` metric 분리 (항목 4)
3. capex `meta.currency` 표기 (항목 6)
4. ECOS API 키 설정 (항목 7 — 사용자)
5. trendforce 대체 피드, pypistats 백오프 (항목 9·10)
