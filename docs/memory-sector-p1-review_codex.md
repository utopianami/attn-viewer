# Codex Review — memory sector P1/P3 engine

작성: codex, 2026-07-07  
리뷰 관점: P2 대시보드 UI 구현자  
대상 범위: `e701fd7..cda23e5`

## Verdict

**REQUEST CHANGES before P2 UI contract freeze.**

P1 수집·저장·격리·기본 API는 대체로 잘 닫혀 있고, `tests/test_sector_*.py`는 현재 워크스페이스에서 통과했다. 다만 P2 대시보드와 챗 `sector_rag` 노출을 얹는 입장에서는 아래 3개가 실제 UI/최종답변 품질에 영향을 준다.

확인 실행:

```bash
cd engine && .venv/bin/python -m pytest tests/test_sector_*.py -q
# 91 passed, 2 warnings
```

경고 2개는 요청서에 이미 알려진 `@app.on_event("startup")` deprecation이다.

## Findings

### Important 1. `sector_rag` 근거가 합성에는 들어가지만 감사 증거에는 빠져 최종 답변에서 섹터 카드가 오탐 처리될 수 있음

- 위치: `engine/stages/synthesize.py:134-142`, `engine/orchestrator.py:393-424`, `engine/stages/audit.py:178-179`, `engine/stages/audit.py:255-260`
- 문제: 합성 컨텍스트에는 `[메모리 섹터 근거]`가 들어가지만, 직후 `run_audit()`에 넘기는 `evidence_texts`/`evidence_docs`에는 `sector_cards`의 `title`, `raw_quote`, `interpreted_signal`, `url`이 포함되지 않는다.
- 영향: 합성 모델이 섹터 카드의 숫자나 엔티티를 최종 답변에 쓰면 감사 단계가 `numeric_unsupported` 또는 `new_fact`로 오탐할 수 있다. 특히 P2 챗 UI에서는 `sector_rag` 레이어에 근거가 보이는데 최종 답변에는 `[확인되지 않은 수치]` 라벨이 붙거나 신규 사실 경고가 뜨는 불일치가 생길 수 있다.
- 권장 수정: `run_audit()` 호출 전 `evidence_texts`에 섹터 카드 헤드/원문을 추가하고, `evidence_docs[c.url]`에도 `title + raw_quote + interpreted_signal`을 넣어야 한다. P3 테스트에 “sector card 숫자가 audit unsupported로 라벨링되지 않음” 회귀 테스트를 추가하라.

### Important 2. 엔티티 사전이 judge 세계관보다 좁아서 UI 필터 칩과 질문 검색이 빠진다

- 위치: `engine/sector/entities.py:7-21`, `engine/sector/judge.py:63-67`, `engine/sector/retrieve.py:65-80`
- 문제: judge 프롬프트는 `NVIDIA·AMD`, `TSMC·ASML`, `CXMT` 등을 명시하지만 공유 엔티티 사전에는 `AMD`, `ASML`, `CXMT`, `KIOXIA`, `COREWEAVE`, `NEBIUS` 같은 P/A'/B 핵심 엔티티가 없다.
- 영향: 해당 카드들은 `entities=[]` 또는 불완전한 칩으로 저장되고, `search_for_question()`도 “ASML 장비 수주”, “CXMT 증산”, “AMD MI300 HBM” 같은 명백한 메모리 섹터 질문에서 엔티티를 감지하지 못해 `sector_rag` 레이어를 아예 방출하지 않을 수 있다.
- 권장 수정: 최소한 judge 프롬프트와 스펙 §1의 엔티티를 같은 사전에서 관리하라. P2 UI 칩으로 쓰려면 canonical id와 display label을 함께 내려주는 구조가 더 낫다.

### Important 3. DAM 가격 폴백이 비결정적이라 `/v1/sector/board`의 cycle 결과가 재시작마다 달라질 수 있음

- 위치: `engine/sector/cycle.py:65-76`
- 문제: ECOS 가격 지표가 없을 때 DAM DRAM 시리즈 중 최신 월의 `item`을 고르는데, `latest_items`가 `set`이고 `selected_item = next(iter(latest_items))`라 선택이 해시 순서에 의존한다.
- 영향: 같은 저장소라도 프로세스 재시작 또는 파이썬 해시 시드에 따라 서로 다른 DRAM 시리즈가 선택될 수 있고, P2 전광판의 `cycle.state`, `score`, `explain`이 흔들릴 수 있다.
- 권장 수정: DAM fallback은 명시적 우선순위를 둬라. 예: 특정 series allowlist, 최신 관측 수가 가장 많은 series, 또는 여러 DRAM series의 median/average. 선택된 series도 구조화 필드로 반환해야 UI에서 “왜 이 가격을 썼는지” 설명할 수 있다.

### Minor 1. `cycle.explain[]`은 사용자 노출 문장 수준이 아님

- 위치: `engine/sector/cycle.py:41-50`, `engine/sector/cycle.py:137-155`
- 현재 예: `price: kr_dram_export_price_index 2026-05→2026-06 +1.00`, `demand: kr_semi_export +0.40 / TSMC_yoy +0.25 → +0.33`
- 판단: 디버그/개발자 표시는 가능하지만 P2 대시보드에 그대로 노출하기엔 지표 id, 방향값, factor명이 내부 용어다.
- 권장 계약: `explain` 문자열은 보존하되, P2용으로 `factor_details[] = {factor, label, metric, from_ts, to_ts, direction, contribution, source}` 같은 구조화 필드를 추가하라. 프론트에서 한국어 문장으로 렌더하는 편이 안전하다.

## 요청서 항목별 답

1. **`GET /v1/sector/board`가 P2에 충분한가**

   전광판 첫 화면의 최소 렌더는 가능하다. `cycle + cards + status`가 있고 `cards`는 `SectorCard.model_dump()`라 `edge`, `event_type`, `memory_segment`, `time_horizon`, `source`까지 포함된다.

   다만 계약 동결 전 아래는 추가가 필요하다.

   - `cycle.as_of` 또는 factor별 최신 관측시각
   - `cycle.factor_details[]` 구조화 설명
   - `board.generated_at`
   - timeline 화면은 `/v1/sector/board`의 20장 카드가 아니라 `/v1/sector/cards?days=&limit=`를 쓰는 계약으로 분리
   - status는 raw collector map 외에 UI용 요약 `{ok, degraded, missing_key, error, last_success_at}`가 있으면 좋다

2. **`SectorCard.entities`가 UI 필터 칩으로 충분한가**

   지금 상태로는 부족하다. canonical id만 내려오고 display label이 없으며, 사전도 judge 세계관보다 작다. P2 칩은 `entities: [{id, label, axis_hint}]` 형태가 이상적이고, 최소한 프론트 매핑 테이블을 OpenAPI 계약에 고정해야 한다.

3. **`cycle.compute`의 `explain[]`이 사용자 노출 가능한가**

   그대로는 아니다. 내부 지표 id와 raw score 설명이다. 대시보드는 구조화 값으로 받고, 문장은 UI에서 만들자.

4. **judge 프롬프트 축 정의가 codex 계획 세계관과 맞는가**

   큰 틀은 맞다. A/A'/B/C/C0/E/P/market 구분과 direction을 A 메모리 3사 관점으로 고정한 점은 UI 세계관과 일치한다. 다만 GPU/ASIC 중간 노드를 `A_prime`으로 태깅하는 선택은 UI에서 “A' = 공급망/패키징/중간노드”로 명확히 표기해야 한다. 사용자는 A'를 TSMC만으로 오해할 수 있다.

5. **raw RAG 노출의 `raw_quote`/`interpreted_signal` 분리가 화면 3 요구를 충족하는가**

   필드 분리는 맞다. 챗 `sector_rag` 레이어도 200자 raw quote와 해석을 분리해 내려준다. 다만 최종 답변 감사에도 같은 근거를 넣어야 화면 근거와 최종 답변 게이트가 서로 충돌하지 않는다.

## OpenAPI 역작성 메모

P2에서 우선 계약화할 엔드포인트:

- `GET /v1/sector/status`
- `POST /v1/sector/collect`
- `GET /v1/sector/cards`
- `GET /v1/sector/metrics/{name}`
- `GET /v1/sector/board`

주의할 계약 포인트:

- `axis` 값은 코드상 `A_prime`이고 스펙 표기는 `A'`다. API 계약은 `A_prime`으로 고정하고 UI label만 `A'`로 표시하라.
- `direction`은 `pos | neg | neutral | mixed`.
- `source_grade`는 `S | A | B | C | D`.
- `cycle.state`는 `up | down | transition | insufficient`.
- `cycle.factors` 값은 number 또는 null이다.
- `status.collectors`는 collector name을 key로 하는 object map이다.

## Non-blocking Notes

- `/v1/sector/collect`는 요청 중 14개 수집기를 순차 실행한다. UI 버튼으로 노출하려면 장기적으로 `202 Accepted + job status`가 맞지만 P2 읽기 대시보드에는 블로커가 아니다.
- `GET /v1/sector/cards`의 `entity`는 canonical id exact match다. OpenAPI 예시는 `SK_HYNIX`처럼 canonical id로 넣어야 한다.
- `raw_quote`는 저장 카드에서 500자, `sector_rag` 레이어에서는 200자다. 화면 3에서 더 긴 원문이 필요하면 카드 상세 또는 `/cards` 기반 확장이 필요하다.
