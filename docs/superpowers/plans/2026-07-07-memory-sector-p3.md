# 메모리 섹터 P3 + DAM 보강 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. 태스크별 리뷰 생략(세션 관례), 최종은 컨트롤러 라이브 검증.

**Goal:** ① 무키 가격 시계열(Stanford DAM) 수집기 추가로 사이클 price 요소를 키 없이 활성화, ② 질문 파이프라인에 섹터 카드를 근거로 주입하고 `sector_rag` 레이어로 노출 (P3, 엔진 측만).

**Architecture:** P1과 동일 규약. P3는 news_summary 통합 패턴(orchestrator 비차단 + synthesize 주입)을 그대로 복제한다.

## Global Constraints (P1과 동일 + 추가)

- 신규 pip 의존성 0 / server.mjs·public 수정 금지 / 테스트 sync+asyncio.run, MockTransport
- 전체 스위트 그린: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/ -q --ignore=tests/test_stages_live.py --ignore=tests/test_price_live.py --ignore=tests/test_toss_live.py` (현재 150)
- **P3 비차단 절대 원칙**: 섹터 조회/레이어의 어떤 실패도 기존 QA 답변을 막으면 안 됨 — try/except → `degraded.append("sector_rag")` (news_summary와 동일, orchestrator.py:202-212 참조)
- 섹터 카드가 0장이거나 질문이 메모리 섹터와 무관하면 레이어를 아예 방출하지 않음 (무관 질문 무영향)
- 커밋 메시지 끝 Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

---

### Task 1: stanford_dam 수집기 + cycle price 폴백

**Files:**
- Create: `engine/sector/collectors/stanford_dam.py`
- Modify: `engine/sector/collectors/__init__.py` (registry에 추가), `engine/sector/cycle.py` (price 폴백)
- Test: `engine/tests/test_sector_collectors_metrics.py` (append), `engine/tests/test_sector_cycle_retrieve.py` (append)

**스펙 (2026-07-07 실측 확정):**
- `GET https://dam.stanford.edu/assets/memory-prices/memory-prices.csv` (무키, UA 명시, 140KB)
- CSV 헤더: `date,category,series,metric,value,unit,source,n_samples,representative,notes`
- 필터: date >= "2023-01-01" 행만. → `MetricObservation(metric="memory_price_usd_per_gb", ts=date[:7], value=float(value), unit=unit, meta={"item": f"{category}|{series}", "category": category})`
- float 변환 실패 행은 건너뜀. HTTP/파싱 실패 → status="degraded"+detail (never-raise)
- cycle.py price 요소: 기존 `kr_dram_export_price_index`(ECOS)가 없으면 폴백 —
  `memory_price_usd_per_gb`에서 meta.category=="DRAM" 행만 → 그중 **가장 최신 ts를 가진 series(meta.item) 하나로 한정** → 방향 헬퍼. explain에 "price(fallback DAM): ..." 표기
- 테스트: ① 픽스처 CSV(2행 유효+1행 값깨짐+1행 2022년) → 관측 2건·ts 변환·meta 검증, ② HTTP 500 → degraded, ③ cycle: ECOS 없음 + DAM 관측 2개 → price 요소 not None / ECOS 있으면 ECOS 우선

- [ ] 실패 테스트 → 구현 → 전체 그린 → 커밋 `feat(sector): Stanford DAM 무키 가격 수집기 + cycle price 폴백`

---

### Task 2: P3 — sector_rag 레이어 + synthesize 주입

**Files:**
- Create: `engine/sector/entities.py` (판별 사전을 judge에서 이동 — 공유 모듈화)
- Modify: `engine/sector/judge.py` (entities.py import로 교체, 동작 불변), `engine/contracts/packets.py` (LAYER_NAMES에 "sector_rag" — "news_summary" 뒤), `engine/orchestrator.py`, `engine/stages/synthesize.py`
- Test: `engine/tests/test_sector_p3.py` (신규)

**entities.py:** judge의 `_ENTITY_PATTERNS`·`_extract_entities`를 옮기고 공개 함수로:
`ENTITY_PATTERNS`, `extract_entities(text: str) -> list[str]` (RawNewsItem이 아니라 str을 받게 일반화 — judge는 `extract_entities(f"{item.title} {item.content[:500]} {item.source}")`로 호출, 기존 judge 테스트가 계속 통과해야 함).

**orchestrator 통합** (news_summary 블록 orchestrator.py:202-212 바로 아래에 동일 패턴):
```python
sector_cards = []
try:
    from sector.entities import extract_entities
    from sector.retrieve import search as sector_search
    from sector.api import _get_store
    ents = extract_entities(plan.standalone_question or "")
    if ents:
        sector_cards = sector_search(_get_store(), entities=ents, days=14, k=12)
    if sector_cards:
        yield _layer("sector_rag", {
            "entities": ents,
            "cards": [{"id": c.id, "axis": c.axis, "direction": c.direction,
                       "magnitude": c.magnitude, "source_grade": c.source_grade,
                       "title": c.title, "interpreted_signal": c.interpreted_signal,
                       "raw_quote": c.raw_quote[:200], "url": c.url,
                       "ts": c.ts, "entities": c.entities} for c in sector_cards],
        })
except Exception:
    degraded.append("sector_rag")
    sector_cards = []
```
run_synthesize 호출(orchestrator.py:378 근처)에 `sector_cards=sector_cards` 전달.

**synthesize.py:** `run_synthesize(..., sector_cards=None)` → `_render_context(..., sector_cards=sector_cards)`. 렌더: sector_cards 있으면 `[뉴스 요약]` 블록 뒤에:
```
[메모리 섹터 근거]  ← 축적된 섹터 카드(자동 수집·판정). 등급 S/A 우선 신뢰, D급은 루머
- (B/neg/m2/B급) Meta, 잉여 GPU… — 해석 한 줄 (url)
```
카드당 1줄 `f"- ({c.axis}/{c.direction}/m{c.magnitude}/{c.source_grade}급) {c.title} — {c.interpreted_signal} ({c.url})"`, 최대 12줄.

**테스트 (test_sector_p3.py):**
1. `extract_entities("하이닉스 HBM 어때")` → ["SK_HYNIX"] 포함; 무관 텍스트 → []
2. LAYER_NAMES에 "sector_rag" 존재
3. synthesize `_render_context` (기존 news_summary 테스트 패턴 복제 — stages/synthesize 임포트해 직접 호출): sector_cards 주면 "[메모리 섹터 근거]"와 카드 제목이 컨텍스트 문자열에 포함, None이면 미포함
4. judge 기존 테스트 전부 그대로 통과 (entities 이동 회귀)

- [ ] 실패 테스트 → 구현 → 전체 그린 → 커밋 `feat(sector): P3 — sector_rag 레이어 + 합성 주입 (비차단)`

---

### Task 3 (컨트롤러 직접): 라이브 검증

8899 인스턴스: 수집 1회 → `/v1/answer`에 하이닉스 질문 → sector_rag 레이어 방출 + 합성에 [메모리 섹터 근거] 반영 확인. 무관 질문(유럽 전력주)은 레이어 미방출 확인. 운영 8801 재시작.
