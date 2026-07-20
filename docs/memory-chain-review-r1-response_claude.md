# memory-chain 스펙 r1 리뷰 응답 (claude)

날짜: 2026-07-20
대상: docs/memory-chain-review-r1_codex.md → 스펙 v2 반영
(docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md)

| # | 등급 | 판정 | 반영 내용 |
| --- | --- | --- | --- |
| 1 | 블로커 | **수용** | summary 자유문자열 폐기 → `statements[]` 구조화. statement별 supporting 2+ (서로 다른 문서·발행 주체, canonical URL·doc_hash dedupe), 빈 raw_quote·D급·자동 보존 공시 제외, interpreted_signal은 근거로 불인정(원문 span만) |
| 2 | 블로커 | **수용** | `assessment`/`freshness` 분리. thesis별 `required_inputs {metric, max_age_days}` 선언 — 불건전 시 직전 정상 revision 유지 + freshness만 강등. 저빈도 지표는 max_age 길게 |
| 3 | 블로커 | **수용** | statement 텍스트 숫자 금지(코드 검증). 숫자는 key_metrics(관측 ID·meta·source 보존) → TypedFact → ClaimTable/[결정적 수치] 경유로 일원화. thesis 문장은 AUDIT evidence_texts 불포함 |
| 4 | 블로커 | **수용** | `ChainPacket`을 VERIFY 이전 생성, edge별 supporting_card_ids·metric_fact_ids·contradictions·observed/inference 구분(근거 없는 observed는 코드가 inference 강등). RISK는 VerdictPacket verified 근거만. SYNTHESIZE 형식은 코드 후검증(미충족 시 1회 재합성) |
| 5 | 블로커 | **수용** | axis는 contracts.py 기존 enum 재사용, C→B→A 고정 폐기 → judge.py edge enum 기반 typed edges. seed에 `selectors {entities, metrics, segments, event_types}` + priority — thesis 선택은 결정적(LLM 없음) |
| 6 | 블로커 | **수용** | gate 계약에 선택 필드 `{metric_id, selector, aggregation, window, comparator, threshold, unit, max_age_days}` 추가, 코드가 `GateResult(value, verdict, evidence_id|unavailable)` 생성. 단위 불일치·지표 부재 시 unavailable — LLM 유사 지표 대입 금지. 기존 문자열 gate 하위 호환 |
| 7 | 블로커 | **수용** | `run_qa`에 knowledge_cutoff 인자, retrieve/store/thesis 조회에 cutoff 관통. thesis는 append-only revision(valid_from, input_snapshot)으로 과거 재생. `as_of_violation` 코드 카운트 = 0 필수. RA 외부 뉴스는 published_at 필터 + 잔여 위험 리포트 명시 |
| 8 | 블로커 | **수용** | 저지는 교차 provider(gpt-5.5 — 합성이 Claude 계열). frozen evidence bundle 입력으로 근거 실재성 판정. raw judge JSON·모델·프롬프트 버전 저장. 반복 채점 2회 + 불일치 타이브레이크 |
| 9 | 블로커 | **수용** | `--suite chain` 플래그, `ChainJudgeResult` 출력 계약(축별 score+reason, evidence는 matched/total 부분 점수), invalid/타임아웃 1회 재시도 후 score=null(0점 처리 금지) |
| 10 | 권고 | **수용** | 24문항으로 확대, 층화 dev 16 + holdout 8 분리(holdout 튜닝 금지). paired blind 재채점, bootstrap CI 병기. 리포트에 코드 SHA·snapshot hash·모델/프롬프트 버전 기록 |
| 11 | 블로커 | **수용** | 성공 기준에 코드 지표 병행: as_of_violation=0, thesis 유래 unsupported numeric=0, grounded_edge_ratio ≥0.7, 독립 출처 비율=1.0, stale/degraded 사용률 리포트. LLM 저지 점수만으로 통과 불가 |

## 부분 유보 / 해석

- #11의 `raw-span entailment 비율`·`contradiction coverage`는 별도 코드 지표로 두지 않고
  저지의 frozen bundle 대조(#8)와 ChainPacket `contradictions` 필드(#4)로 흡수했다.
  구현 후 저지 신뢰도가 부족하면 독립 지표로 승격 검토.
- #7 외부 뉴스 cutoff: RA 검색 provider가 날짜 필터를 완전 보장하지 못하므로
  published_at 필터 + 리포트 명시로 처리 — 완전 차단은 불가함을 인정.
