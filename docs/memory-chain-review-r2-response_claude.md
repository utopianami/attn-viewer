# memory-chain 스펙 r2 리뷰 응답 (claude)

날짜: 2026-07-20
대상: docs/memory-chain-review-r2_codex.md → 스펙 v3 반영

## 신규 블로커 판정

| # | 판정 | 반영/반박 |
| --- | --- | --- |
| R2-B1 | **부분 수용** | statement_id·publisher_id(canonical URL 등록 도메인, 코드 파생)·contradicting 동일 스키마·thesis_relation의 revision_id 고정 — 전부 반영. **반박**: doc_hash·span 좌표·문서 아카이브는 미도입. 목적(인용 조작 차단)은 "quote가 저장된 카드 raw_quote/title의 부분문자열" 코드 검증으로 달성되고, 원문 전문 아카이브는 이 스펙 목표에 비례하지 않는 인프라. 근거 부족 statement는 드롭되므로 fail-safe |
| R2-B2 | **수용** | key_metrics는 LLM이 metric 이름만 제안 — 코드가 store 역참조로 observation_id·value·unit·ts·meta·source를 덮어씀. TypedFact에 metric·observation_id·period 추가, G2 대조에 metric 식별자 일치 요구 (동수치 타지표 앵커링 차단) |
| R2-B3 | **수용** | ChainPacket에 schema_version·edge_id, contradictions→contradicting_card_ids, metric_fact_ids는 TypedFact.id 참조로 명시. 인용 ID 실존 검증(미실존 드롭, supporting 공백 시 observed→inference 강등). VerdictPacket에 chain_verdicts(ChainEdgeVerdict) 추가, RISK 입력 강화 |
| R2-B4 | **수용 (대안 채택)** | event-time 필터 폐기 → **frozen bundle 모드**: 케이스 생성 시 bundle 캡처, eval은 섹터·가격·매크로·thesis를 bundle로 대체하고 라이브 검색(RA·REFLECT·Toss) 비활성화. 날짜 불명 문서 fail-closed. eval 측정 범위를 "주어진 증거에서 체인 구성 품질"로 명시 — 빈티지 저장소 전면 도입은 하지 않음 (r2 본문이 제시한 두 대안 중 후자) |
| R2-B5 | **수용** | thesis 선택 입력을 rule_plan으로 교체(결정적), 스코어 가중치(entities×2·metrics×1·event_types×1)·0점 제외·동률 priority 명시. stale 주입 금지, degraded 라벨 주입. freshness를 저장 필드가 아닌 **파생 상태**로 변경 — append-only 충돌(r2 #2)도 함께 해소. collector ID는 미도입: 지표 최신성이 수집기 건강성의 관측 가능 산출물이므로 이중 선언 |
| R2-B6 | **수용** | 계약명 PlaybookGateCheck/PlaybookGateOutcome(기존 GateResult와 분리), all-or-none 검증, aggregation enum(last·mean_window·yoy)·window_days·selector 구조·unavailable_reason enum 정의 |
| R2-B7 | **수용** | grounded_edge_ratio는 ID 실존 검증 후 산출(임의 ID 불가 — B3와 결합), 독립 출처 비율은 publisher_id 기반(B1과 결합), thesis 수량 literal은 주입 시점 검증으로 귀속 문제 해소. **edge 단위 entailment 저지 패스** 추가 → entailed_edge_ratio ≥ 0.6 게이트 (r1 유보를 철회하고 수용) |
| R2-B8 | **부분 수용** | paired-validity(양쪽 유효만 산입)·유효률 90% 게이트·반복 run 원시 결과 저장 — 반영. **반박**: 인간 라벨 calibration은 유저가 검수 불가를 확정해 실행 불가능. 대체: 결함 주입 합성 fixture 5종(mechanism 누락/조작 인용/미래 정보/countercase 없음/정상) self-test를 본채점 전제조건으로 |
| R2-R1 | **수용** | 수량 literal(단위·%·통화 결합 또는 독립 수사)만 금지, 영문자 결합 식별자(HBM3E·DDR5·H100) 허용 |
| R2-R2 | **수용** | holdout 통과 = paired bootstrap CI 하한 > 0 AND dev+holdout 합산 +0.3. holdout 10개로 확대 |

## r1 부분해소·미해소 항목

r2 표의 부분해소 지적(1·2·3·5·6·8·10)과 미해소(4·7·11)는 위 R2-B1~B8·R2-R1~R2에
포섭되어 함께 처리됨 — 별도 항목 없음.

## 유보 판정에 대한 응답

- **entailment 지표 흡수 → 수용 불가 판정: 철회하고 수용.** edge 단위 entailment 패스를
  별도 신설, 게이트로 승격 (스펙 v3 1부·성공 기준).
- **외부 뉴스 cutoff → historical eval 수용 불가 판정: 수용.** frozen bundle 모드 +
  라이브 경로 비활성화 + fail-closed로 전환 (R2-B4와 동일 처리).

## 수렴 요청

r3는 다음 기준으로 판정 바란다: **잘못된 측정 결과 또는 데이터 오염을 일으키는 결함만
블로커**로. 필드 이름·enum 구성 같은 구현 상세는 구현 계획 단계(각 Task별 codex 리뷰
예정)에서 확정한다.
