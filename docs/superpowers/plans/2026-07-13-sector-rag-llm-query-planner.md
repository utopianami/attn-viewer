# 섹터 RAG — LLM 쿼리 플래너 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 채팅 질문을 LLM 플래너가 해석해 섹터 DB(카드 508건+, 지표 18종)에서 관련 카드·지표를 골라 답변 재료로 주입한다.

**Architecture:** 게이트(키워드)는 유지하고, 섹터 질문이면 경량 sonnet이 구조화 출력으로 `SectorQueryPlan`(세그먼트·회사·지표·기간·키워드)을 생성 → 플랜 기반 카드 스코어링 + 지표 요약 주입. 규칙 플랜은 폴백 겸 대조 로그. 스펙: `docs/superpowers/specs/2026-07-13-sector-rag-llm-query-planner-design.md`

**Tech Stack:** Python 3.12 (engine/), pydantic, providers.py `Role` (structured output = `response_format` 옵션), pytest

## Global Constraints

- **never-raise**: 섹터 레이어의 어떤 실패도 답변 파이프라인을 죽이면 안 됨 (기존 원칙, orchestrator.py:240 주석)
- 기존 `search_for_question`의 동작·시그니처는 건드리지 않음 (폴백 안전망 + 기존 테스트 보존)
- 테스트 실행: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/<파일> -v`
- 커밋 메시지: 한국어, `feat(sector): ...` 형식, 마지막 줄 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 엔진 재시작은 `pm2 restart attn-engine`만 사용 (pkill 금지 — 즉시 부활·포트 충돌)
- 주석 스타일: 기존 코드처럼 한국어 + 제약·이유 중심

---

### Task 1: METRIC_REGISTRY + 지표 요약

**Files:**
- Create: `engine/sector/metrics_registry.py`
- Test: `engine/tests/test_sector_metrics_registry.py`

**Interfaces:**
- Produces: `METRIC_REGISTRY: dict[str, dict]` — 키 = 지표명(jsonl 파일명), 값 = `{"label": str, "desc": str, "keywords": tuple[str, ...]}`
- Produces: `metric_summary(store: SectorStore, metric: str) -> str` — 최신 관측 요약 텍스트, 데이터 없으면 `""`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_sector_metrics_registry.py
"""METRIC_REGISTRY 단일 소스 + metric_summary (2026-07-13 LLM 쿼리 플래너 P1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.metrics_registry import METRIC_REGISTRY, metric_summary  # noqa: E402
from sector.store import SectorStore  # noqa: E402


def _store(tmp_path, metric: str, rows: list[dict]) -> SectorStore:
    store = SectorStore(tmp_path)
    mdir = tmp_path / "metrics"
    mdir.mkdir(exist_ok=True)
    (mdir / f"{metric}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    return store


def test_registry_covers_existing_metric_files():
    """저장소의 실제 지표 파일이 전부 레지스트리에 등록돼 있다 (real upstream)."""
    mdir = Path(__file__).resolve().parents[2] / "storage/rag/memory_sector/metrics"
    if not mdir.exists():
        return  # CI 등 저장소 없는 환경 — 등록 검증은 라이브 환경에서만
    on_disk = {p.stem for p in mdir.glob("*.jsonl")}
    assert on_disk <= set(METRIC_REGISTRY), f"미등록 지표: {on_disk - set(METRIC_REGISTRY)}"


def test_registry_entries_complete():
    for name, info in METRIC_REGISTRY.items():
        assert info["label"] and info["desc"], name
        assert isinstance(info["keywords"], tuple), name


def test_metric_summary_single_series(tmp_path):
    store = _store(tmp_path, "kr_semi_export", [
        {"metric": "kr_semi_export", "ts": "2026-06", "value": 100.0,
         "unit": "k_usd", "meta": {"item": "01~10", "provider": "customs"}},
        {"metric": "kr_semi_export", "ts": "2026-07", "value": 110.0,
         "unit": "k_usd", "meta": {"item": "01~10", "provider": "customs"}},
    ])
    txt = metric_summary(store, "kr_semi_export")
    assert "반도체 수출" in txt        # label
    assert "110" in txt and "2026-07" in txt
    assert "+10.0%" in txt             # 직전 대비


def test_metric_summary_grouped_series(tmp_path):
    """meta 그룹(회사·모델별)이 섞인 시계열은 그룹별 최신값으로 요약한다."""
    store = _store(tmp_path, "hyperscaler_capex", [
        {"metric": "hyperscaler_capex", "ts": "2026-03", "value": 19.0,
         "unit": "b_usd", "meta": {"token": "META", "item": "META"}},
        {"metric": "hyperscaler_capex", "ts": "2026-03", "value": 30.0,
         "unit": "b_usd", "meta": {"token": "MSFT", "item": "MSFT"}},
    ])
    txt = metric_summary(store, "hyperscaler_capex")
    assert "META" in txt and "MSFT" in txt


def test_metric_summary_missing_data(tmp_path):
    assert metric_summary(SectorStore(tmp_path), "kr_semi_export") == ""
    assert metric_summary(SectorStore(tmp_path), "no_such_metric") == ""
```

- [ ] **Step 2: 실패 확인**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_metrics_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sector.metrics_registry'`

- [ ] **Step 3: 구현**

```python
# engine/sector/metrics_registry.py
"""지표 레지스트리 — 단일 소스 (2026-07-13 LLM 쿼리 플래너 P1).

플래너 메뉴 / 규칙 폴백 keywords / 요약 라벨이 전부 이 dict 하나를 쓴다.
새 지표는 수집기 추가 시점에 여기 한 줄 등록.
"""
from __future__ import annotations

METRIC_REGISTRY: dict[str, dict] = {
    "kr_semi_export": {
        "label": "한국 반도체 수출액",
        "desc": "관세청 10일 단위 수출액 — 삼성·하이닉스 매출 선행 proxy",
        "keywords": ("수출",)},
    "kr_semi_export_share": {
        "label": "반도체 수출 비중",
        "desc": "전체 수출 중 반도체 비중(%)",
        "keywords": ("수출 비중",)},
    "kr_semi_production_index": {
        "label": "한국 반도체 생산·재고지수",
        "desc": "통계청 생산·출하·재고지수 — 재고 사이클 판단",
        "keywords": ("재고", "생산지수")},
    "hyperscaler_capex": {
        "label": "하이퍼스케일러 CAPEX",
        "desc": "MS·구글·메타·아마존 등 분기 설비투자(10억달러) — AI 인프라 수요",
        "keywords": ("capex", "캐펙스", "설비투자", "인프라 투자")},
    "memory_capex": {
        "label": "메모리 3사 CAPEX",
        "desc": "삼성·하이닉스·마이크론 분기 설비투자 — 공급 증설 리스크",
        "keywords": ("증설", "공급 과잉")},
    "ai_chip_revenue": {
        "label": "AI 칩 기업 매출",
        "desc": "NVDA·AMD·AVGO 분기 매출(10억달러) — HBM 수요 선행",
        "keywords": ("엔비디아 매출", "ai 칩")},
    "equip_revenue": {
        "label": "반도체 장비사 매출",
        "desc": "ASML 등 장비사 분기 매출 — 6~12개월 뒤 공급 증가 신호",
        "keywords": ("장비", "asml")},
    "tw_monthly_revenue": {
        "label": "대만 ODM·TSMC 월매출",
        "desc": "TSMC·콴타·위윈 등 월매출(kTWD, YoY/MoM) — AI 서버 수요 proxy",
        "keywords": ("tsmc", "월매출", "대만", "odm")},
    "memory_price_usd_per_gb": {
        "label": "메모리 현물가",
        "desc": "D램·낸드 USD/GB 현물가 — 사이클 방향의 핵심",
        "keywords": ("현물가", "가격", "고정가")},
    "token_price": {
        "label": "LLM 토큰 단가",
        "desc": "모델별 1M 토큰 가격 — 토큰 경제/inference 수요 방향",
        "keywords": ("토큰 가격", "api 가격")},
    "openrouter_daily_tokens": {
        "label": "OpenRouter 일별 토큰 사용량",
        "desc": "모델별 일일 처리 토큰 — AI 사용량 proxy",
        "keywords": ("토큰 사용량", "사용량", "오픈라우터")},
    "sdk_downloads": {
        "label": "AI SDK 다운로드",
        "desc": "주요 AI SDK 다운로드 수 — 개발자 수요 proxy",
        "keywords": ("sdk", "다운로드")},
    "app_rank": {
        "label": "AI 앱 순위",
        "desc": "앱스토어 AI 앱 순위 — 소비자 수요 proxy",
        "keywords": ("앱 순위",)},
    "search_interest_kr": {
        "label": "한국 검색 관심도",
        "desc": "네이버 데이터랩 검색 트렌드 — 국내 관심도",
        "keywords": ("검색량", "관심도")},
    "stock_price": {
        "label": "종목 주가",
        "desc": "메모리·AI 관련 종목 일별 주가",
        "keywords": ("주가",)},
    "earnings_calendar": {
        "label": "실적 발표 일정",
        "desc": "관련 기업 실적 발표 예정일",
        "keywords": ("실적 발표", "실적 일정", "컨콜")},
    "macro_calendar": {
        "label": "매크로 일정",
        "desc": "FOMC·CPI 등 거시 이벤트 일정",
        "keywords": ("fomc", "cpi", "금리 결정")},
    "ai_status_incidents": {
        "label": "AI 서비스 장애",
        "desc": "주요 AI 서비스 장애 횟수 — capacity 압박 신호",
        "keywords": ("장애", "다운")},
}

_GROUP_KEYS = ("name", "item", "token", "model", "category")


def _group_key(meta: dict) -> str:
    for k in _GROUP_KEYS:
        v = meta.get(k)
        if v:
            return str(v)
    return ""


def metric_summary(store, metric: str) -> str:
    """지표 최신 관측 요약 한 줄 — 합성 컨텍스트 주입용. 실패·부재 시 ""."""
    info = METRIC_REGISTRY.get(metric)
    if not info:
        return ""
    try:
        rows = store.read_metric(metric, last_n=400)
    except Exception:  # noqa: BLE001 — never-raise
        return ""
    if not rows:
        return ""
    groups: dict[str, list] = {}
    for o in rows:  # read_metric이 ts 오름차순 보장
        groups.setdefault(_group_key(o.meta), []).append(o)
    top = sorted(groups.values(), key=lambda rs: rs[-1].ts, reverse=True)[:5]
    parts = []
    for rs in top:
        last = rs[-1]
        chg = ""
        if len(rs) >= 2 and rs[-2].value:
            chg = f", 직전 대비 {(float(last.value) / float(rs[-2].value) - 1) * 100:+.1f}%"
        gk = _group_key(last.meta)
        head = f"{gk} " if gk else ""
        parts.append(f"{head}{float(last.value):,.4g} {last.unit} ({last.ts}{chg})")
    return f"[섹터 지표] {info['label']}: " + " · ".join(parts)
```

- [ ] **Step 4: 통과 확인**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_metrics_registry.py -v`
Expected: PASS (5건)

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/metrics_registry.py engine/tests/test_sector_metrics_registry.py
git commit -m "feat(sector): METRIC_REGISTRY 단일 소스 + 지표 요약 — 쿼리 플래너 P1 (1/7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: SectorQueryPlan 스키마 + 게이트 + 규칙 플랜

**Files:**
- Create: `engine/sector/queryplan.py` (이 태스크에서는 스키마·게이트·규칙 플랜·정제까지 — LLM 호출은 Task 3)
- Modify: `engine/sector/retrieve.py:65` (`_TOPIC_TERMS`를 queryplan에서 import — 중복 제거)
- Test: `engine/tests/test_sector_queryplan.py`

**Interfaces:**
- Consumes: `METRIC_REGISTRY` (Task 1), `sector.entities.extract_entities`, `sector.entities.ENTITY_PATTERNS`
- Produces: `SectorQueryPlan(BaseModel)` — 필드 `sector: str = "memory"`, `segments: list[str]`, `entities: list[str]`, `metrics: list[str]`, `event_types: list[str]`, `days: int = 14`, `keywords: list[str]`
- Produces: `is_sector_question(q: str) -> bool`, `build_rule_plan(q: str) -> SectorQueryPlan`, `sanitize_plan(p: SectorQueryPlan) -> SectorQueryPlan`
- Produces: `TOPIC_TERMS_BY_SECTOR: dict[str, tuple[str, ...]]` (retrieve가 import)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_sector_queryplan.py
"""SectorQueryPlan — 게이트·규칙 플랜·정제 (2026-07-13 LLM 쿼리 플래너 P1)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.queryplan import (  # noqa: E402
    SectorQueryPlan, build_rule_plan, is_sector_question, sanitize_plan)


def test_gate_entity_and_topic():
    assert is_sector_question("하이닉스 실적 어때?")            # 엔티티
    assert is_sector_question("메모리 업황 지금 어디쯤이야?")    # 토픽
    assert is_sector_question("반도체 수출 사이클 어때")         # 반도체+보조어
    assert not is_sector_question("현대차 주가 어때?")          # 무관


def test_rule_plan_segments_and_metrics():
    p = build_rule_plan("HBM 공급 타이트해? 한국 수출도 궁금해")
    assert "hbm" in p.segments
    assert "kr_semi_export" in p.metrics
    assert p.days == 14 and p.sector == "memory"


def test_rule_plan_period_widening():
    assert build_rule_plan("6월에 메모리 쪽 무슨 일 있었어?").days == 90
    assert build_rule_plan("지난달 D램 가격 흐름은?").days == 90


def test_rule_plan_entities():
    p = build_rule_plan("삼성전자가 마이크론 따라잡을 수 있어?")
    assert {"SAMSUNG", "MICRON"} <= set(p.entities)


def test_sanitize_clamps_and_filters():
    dirty = SectorQueryPlan(
        segments=["hbm", "ssd"],                 # ssd는 세그먼트 아님
        entities=["SAMSUNG", "TESLA"],           # TESLA는 미등록
        metrics=["kr_semi_export", "bogus"],     # bogus 미등록
        event_types=["earnings", "bogus_type"],
        days=400, keywords=[" 점유율 ", "", "a", "b", "c", "d", "e", "f", "g", "h"])
    p = sanitize_plan(dirty)
    assert p.segments == ["hbm"]
    assert p.entities == ["SAMSUNG"]
    assert p.metrics == ["kr_semi_export"]
    assert p.event_types == ["earnings"]
    assert p.days == 90                          # [7, 90] 클램프
    assert len(p.keywords) <= 8 and "점유율" in p.keywords
```

- [ ] **Step 2: 실패 확인**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_queryplan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sector.queryplan'`

- [ ] **Step 3: 구현**

```python
# engine/sector/queryplan.py
"""섹터 검색 플랜 — 게이트·스키마·규칙 플랜 (2026-07-13 LLM 쿼리 플래너 P1).

게이트는 키워드(비섹터 질문 비용 0), 플랜 생성은 LLM(plan_query, Task 3)이 기본이고
규칙(build_rule_plan)이 폴백 겸 대조군. 두 경로가 같은 SectorQueryPlan을 내므로
검색 실행부(search_with_plan)는 하나만 존재한다.
"""
from __future__ import annotations

import re
from typing import get_args

from pydantic import BaseModel, Field

from sector.contracts import SectorCard
from sector.entities import ENTITY_PATTERNS, extract_entities
from sector.metrics_registry import METRIC_REGISTRY

_SEGMENTS = ("hbm", "dram", "nand")
_EVENT_TYPES: set[str] = set(get_args(SectorCard.model_fields["event_type"].annotation))
_VALID_ENTITIES = {canon for canon, _ in ENTITY_PATTERNS}

# 섹터별 토픽 키워드 — 타 섹터 추가 시 여기만 등록 (확장 대비 필터 차원)
TOPIC_TERMS_BY_SECTOR: dict[str, tuple[str, ...]] = {
    "memory": ("메모리", "d램", "디램", "dram", "hbm", "낸드", "nand", "웨이퍼"),
}


class SectorQueryPlan(BaseModel):
    """LLM/규칙 공용 검색 계획. 필드 의미는 스펙(2026-07-13 design) §2."""
    sector: str = "memory"
    segments: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    days: int = 14
    keywords: list[str] = Field(default_factory=list)


def is_sector_question(question: str) -> bool:
    low = (question or "").lower()
    if not low:
        return False
    if extract_entities(question):
        return True
    if any(t in low for t in TOPIC_TERMS_BY_SECTOR["memory"]):
        return True
    return "반도체" in low and any(
        w in low for w in ("업황", "사이클", "가격", "수급", "수출"))


_SEGMENT_TERMS = {
    "hbm": ("hbm", "고대역폭"),
    "dram": ("d램", "디램", "dram"),
    "nand": ("낸드", "nand", "ssd"),
}
_MONTH_RE = re.compile(r"\d{1,2}\s*월")
_LONG_TERMS = ("지난달", "저번달", "분기", "올해", "작년", "상반기", "하반기", "한 달", "한달")


def build_rule_plan(question: str) -> SectorQueryPlan:
    """키워드 규칙 플랜 — LLM 폴백 겸 대조군. 미매칭이면 빈 필드(무필터 광역 검색)."""
    low = (question or "").lower()
    segs = [s for s, terms in _SEGMENT_TERMS.items() if any(t in low for t in terms)]
    mets = [m for m, info in METRIC_REGISTRY.items()
            if any(k in low for k in info["keywords"])][:4]
    days = 90 if (_MONTH_RE.search(question or "") or any(t in low for t in _LONG_TERMS)) else 14
    return SectorQueryPlan(segments=segs, entities=extract_entities(question or ""),
                           metrics=mets, days=days)


def sanitize_plan(p: SectorQueryPlan) -> SectorQueryPlan:
    """LLM 출력 정제 — 미등록 값 제거·클램프. 검증 실패값이 검색을 오염시키지 않게."""
    return SectorQueryPlan(
        sector="memory",
        segments=[s for s in p.segments if s in _SEGMENTS][:3],
        entities=[e for e in p.entities if e in _VALID_ENTITIES][:6],
        metrics=[m for m in p.metrics if m in METRIC_REGISTRY][:4],
        event_types=[t for t in p.event_types if t in _EVENT_TYPES][:4],
        days=max(7, min(90, int(p.days or 14))),
        keywords=[k.strip() for k in p.keywords if k and k.strip()][:8],
    )
```

- [ ] **Step 4: retrieve.py 토픽 키워드 중복 제거**

`engine/sector/retrieve.py:65`의

```python
_TOPIC_TERMS = ("메모리", "d램", "디램", "dram", "hbm", "낸드", "nand", "웨이퍼")
```

를 다음으로 교체:

```python
from sector.queryplan import TOPIC_TERMS_BY_SECTOR

_TOPIC_TERMS = TOPIC_TERMS_BY_SECTOR["memory"]  # 단일 소스 — queryplan (2026-07-13)
```

(import는 파일 상단 `from sector.store import SectorStore` 아래에 추가)

- [ ] **Step 5: 전체 통과 확인**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_queryplan.py tests/test_sector_chat_injection.py -v`
Expected: PASS (신규 5건 + 기존 5건 — 기존 토픽 트리거 테스트가 회귀 검증)

- [ ] **Step 6: 커밋**

```bash
git add engine/sector/queryplan.py engine/sector/retrieve.py engine/tests/test_sector_queryplan.py
git commit -m "feat(sector): SectorQueryPlan 스키마·게이트·규칙 플랜 — 쿼리 플래너 P1 (2/7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: LLM 플래너 (plan_query)

**Files:**
- Modify: `engine/providers.py:26-46` (ROLE_MAP에 `sector_query` 추가)
- Modify: `engine/sector/queryplan.py` (플래너 프롬프트 + `plan_query` + `PlanOutcome` 추가)
- Test: `engine/tests/test_sector_queryplan.py` (추가)

**Interfaces:**
- Consumes: `providers.Role(role, overrides)` — `await role.run(prompt, instructions, response_format=Model)` → structured면 `resp.value`(모델 인스턴스) 반환
- Produces: `PlanOutcome` dataclass — 필드 `plan: SectorQueryPlan`, `rule_plan: SectorQueryPlan`, `fallback: bool`, `planner_ms: int`
- Produces: `async plan_query(question: str, overrides: dict | None = None, timeout: float = 5.0) -> PlanOutcome | None` — 게이트 미통과면 `None`

- [ ] **Step 1: ROLE_MAP에 역할 추가**

`engine/providers.py`의 ROLE_MAP dict 안 `"sector_judge"` 항목 아래에 추가:

```python
    # 섹터 검색 플래너 (2026-07-13): 질문 → SectorQueryPlan 구조화 출력. 경량이면 충분
    "sector_query": [("anthropic", settings.model_claude_sonnet, "low"),
                     ("openai", settings.model_gpt_mini, "low")],
```

- [ ] **Step 2: 실패하는 테스트 추가**

`engine/tests/test_sector_queryplan.py`에 추가:

```python
import asyncio

from sector.queryplan import PlanOutcome, plan_query  # noqa: E402  (기존 import 줄에 병합)


class _FakeRole:
    """Role 대역 — run()이 준비된 값을 반환하거나 예외를 던진다."""
    def __init__(self, result=None, exc=None, delay=0.0):
        self._result, self._exc, self._delay = result, exc, delay

    async def run(self, prompt, instructions="", *, response_format=None, **kw):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc:
            raise self._exc
        return self._result


def test_plan_query_gate_miss(monkeypatch):
    out = asyncio.run(plan_query("현대차 주가 어때?"))
    assert out is None


def test_plan_query_llm_success(monkeypatch):
    from sector import queryplan
    fake = SectorQueryPlan(segments=["hbm"], metrics=["kr_semi_export"],
                           keywords=["점유율"], days=30)
    monkeypatch.setattr(queryplan, "_make_role", lambda overrides: _FakeRole(result=fake))
    out = asyncio.run(plan_query("HBM 요즘 어때?"))
    assert isinstance(out, PlanOutcome) and not out.fallback
    assert out.plan.segments == ["hbm"] and out.plan.days == 30
    assert out.rule_plan.segments == ["hbm"]     # 대조 로그용 규칙 플랜 동봉
    assert out.planner_ms >= 0


def test_plan_query_llm_error_falls_back(monkeypatch):
    from sector import queryplan
    monkeypatch.setattr(queryplan, "_make_role",
                        lambda overrides: _FakeRole(exc=RuntimeError("api down")))
    out = asyncio.run(plan_query("HBM 요즘 어때?"))
    assert out.fallback and out.plan == out.rule_plan


def test_plan_query_timeout_falls_back(monkeypatch):
    from sector import queryplan
    fake = _FakeRole(result=SectorQueryPlan(), delay=1.0)
    monkeypatch.setattr(queryplan, "_make_role", lambda overrides: fake)
    out = asyncio.run(plan_query("HBM 요즘 어때?", timeout=0.05))
    assert out.fallback


def test_plan_query_empty_llm_plan_uses_rule(monkeypatch):
    """플래너가 아무것도 못 고르면 규칙 플랜이 더 안전하다."""
    from sector import queryplan
    monkeypatch.setattr(queryplan, "_make_role",
                        lambda overrides: _FakeRole(result=SectorQueryPlan()))
    out = asyncio.run(plan_query("D램 현물가 어때?"))
    assert not out.fallback
    assert out.plan.segments == ["dram"]         # rule_plan으로 대체됨
```

- [ ] **Step 3: 실패 확인**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_queryplan.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlanOutcome'`

- [ ] **Step 4: 구현**

`engine/sector/queryplan.py`에 추가 (파일 끝):

```python
import asyncio
import time
from dataclasses import dataclass
from datetime import date


@dataclass
class PlanOutcome:
    plan: SectorQueryPlan        # 검색에 실제 쓸 플랜
    rule_plan: SectorQueryPlan   # 대조 로그용 규칙 플랜 (LLM 기여 사후 측정)
    fallback: bool               # True = LLM 실패로 규칙 플랜 사용
    planner_ms: int


_PLANNER_INSTRUCTIONS = (
    "너는 메모리 반도체 섹터 데이터베이스의 검색 플래너다. 사용자 질문을 보고 "
    "어떤 데이터를 꺼내올지 SectorQueryPlan JSON으로만 답한다. "
    "질문과 무관한 필드는 빈 목록으로 둔다. 과잉 선택 금지 — 답변에 꼭 필요한 것만.")


def _planner_prompt(question: str) -> str:
    metrics_menu = "\n".join(f"- {name}: {info['label']} — {info['desc']}"
                             for name, info in METRIC_REGISTRY.items())
    return f"""오늘: {date.today().isoformat()}
질문: {question}

아래 메뉴에서 이 질문에 답하는 데 필요한 것만 고른다.

[metrics 메뉴 — 이 이름만 사용]
{metrics_menu}

[segments] {", ".join(_SEGMENTS)} — 질문이 특정 메모리 종류를 다룰 때만
[entities] {", ".join(sorted(_VALID_ENTITIES))}
[event_types] {", ".join(sorted(_EVENT_TYPES))}
[days] 검색 기간(일). 기본 14. 질문이 과거 기간·특정 월을 언급하면 넓힌다 (최대 90)
[keywords] 뉴스 카드 제목·해석 텍스트와 대조할 한국어 키워드 최대 8개 —
질문의 핵심 개념과 동의어·연관어 (예: "따라잡아?" → 점유율, 인증, 수율)"""


def _make_role(overrides: dict | None):
    """테스트 대역 주입 지점 — monkeypatch 대상."""
    from providers import Role
    return Role("sector_query", overrides)


async def plan_query(question: str, overrides: dict | None = None,
                     timeout: float = 5.0) -> PlanOutcome | None:
    """게이트 → LLM 플랜 (실패 시 규칙 플랜). never-raise."""
    if not is_sector_question(question or ""):
        return None
    rule = build_rule_plan(question)
    t0 = time.monotonic()
    try:
        role = _make_role(overrides)
        raw = await asyncio.wait_for(
            role.run(_planner_prompt(question), _PLANNER_INSTRUCTIONS,
                     response_format=SectorQueryPlan),
            timeout)
        ms = int((time.monotonic() - t0) * 1000)
        got = raw if isinstance(raw, SectorQueryPlan) \
            else SectorQueryPlan.model_validate_json(str(raw))
        plan = sanitize_plan(got)
        if not (plan.segments or plan.entities or plan.metrics or plan.keywords):
            plan = rule  # 플래너가 전부 비웠으면 규칙이 더 안전
        return PlanOutcome(plan=plan, rule_plan=rule, fallback=False, planner_ms=ms)
    except Exception:  # noqa: BLE001 — 타임아웃·API 오류·검증 실패 전부 규칙 강등
        return PlanOutcome(plan=rule, rule_plan=rule, fallback=True,
                           planner_ms=int((time.monotonic() - t0) * 1000))
```

(참고: `import asyncio/time/dataclass/date`는 파일 상단 import 블록으로 이동해 정리)

- [ ] **Step 5: 통과 확인**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_queryplan.py -v`
Expected: PASS (10건)

- [ ] **Step 6: 커밋**

```bash
git add engine/providers.py engine/sector/queryplan.py engine/tests/test_sector_queryplan.py
git commit -m "feat(sector): LLM 쿼리 플래너 plan_query — sonnet 구조화 출력, 5초 타임아웃 규칙 강등 (3/7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 플랜 기반 카드 검색 (search_with_plan)

**Files:**
- Modify: `engine/sector/retrieve.py` (`_balanced_top` 추출 + `search_with_plan` 추가, `search`는 리팩터만 — 동작 불변)
- Test: `engine/tests/test_sector_retrieve_plan.py`

**Interfaces:**
- Consumes: `SectorQueryPlan` (Task 2), `SectorStore.read_cards(days=...)`
- Produces: `search_with_plan(store, plan: SectorQueryPlan, *, k: int = 12) -> list[SectorCard]`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_sector_retrieve_plan.py
"""플랜 기반 카드 스코어링 (2026-07-13 LLM 쿼리 플래너 P1)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import SectorCard  # noqa: E402
from sector.queryplan import SectorQueryPlan  # noqa: E402
from sector.retrieve import search, search_with_plan  # noqa: E402


def _card(id, *, seg="mixed", ents=(), et="demand_signal", direction="neutral",
          mag=1, grade="B", title="t", signal="s", days_ago=1) -> SectorCard:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return SectorCard(id=id, ts=ts, axis="A", entities=list(ents), event_type=et,
                      memory_segment=seg, direction=direction, magnitude=mag,
                      source_grade=grade, title=title, interpreted_signal=signal)


class _FakeStore:
    def __init__(self, cards):
        self._cards = cards

    def read_cards(self, *, days=14, **kw):
        return list(self._cards)


def test_segment_match_outranks_magnitude():
    """HBM 질문이면 저중요도 HBM 카드가 고중요도 낸드 카드보다 위."""
    cards = [_card("nand-big", seg="nand", mag=3),
             _card("hbm-small", seg="hbm", mag=1)]
    plan = SectorQueryPlan(segments=["hbm"])
    got = search_with_plan(_FakeStore(cards), plan, k=2)
    assert got[0].id == "hbm-small"


def test_keyword_overlap_boosts():
    cards = [_card("noise", title="무관한 카드", mag=2),
             _card("hit", title="SK하이닉스 HBM4 인증 통과", signal="점유율 방어", mag=1)]
    plan = SectorQueryPlan(keywords=["인증", "점유율"])
    got = search_with_plan(_FakeStore(cards), plan, k=2)
    assert got[0].id == "hit"


def test_direction_balance_kept():
    """스코어가 낮아도 pos·neg 각 2건은 보장 (기존 균형 원칙 유지)."""
    cards = ([_card(f"pos{i}", seg="hbm", direction="pos", mag=3) for i in range(10)]
             + [_card("neg1", direction="neg", mag=1),
                _card("neg2", direction="neg", mag=1)])
    plan = SectorQueryPlan(segments=["hbm"])
    got = search_with_plan(_FakeStore(cards), plan, k=6)
    assert sum(1 for c in got if c.direction == "neg") >= 2


def test_empty_plan_falls_back_to_magnitude_order():
    cards = [_card("small", mag=1), _card("big", mag=3)]
    got = search_with_plan(_FakeStore(cards), SectorQueryPlan(), k=2)
    assert got[0].id == "big"


def test_legacy_search_unchanged_with_real_index():
    """리팩터(_balanced_top 추출) 후에도 기존 search가 실제 index.jsonl에서 동작 (real upstream)."""
    root = Path(__file__).resolve().parents[2] / "storage/rag/memory_sector"
    if not (root / "index.jsonl").exists():
        return
    from sector.store import SectorStore
    store = SectorStore(root)
    got = search(store, days=14, k=12)
    if got:  # 최근 14일 카드가 있을 때만 의미 있는 검증
        assert len(got) <= 12
        assert all(hasattr(c, "magnitude") for c in got)


def test_search_with_plan_real_index_hbm():
    """실제 카드에서 HBM 플랜이 HBM/mixed 위주로 상위를 채우는지 (real upstream)."""
    root = Path(__file__).resolve().parents[2] / "storage/rag/memory_sector"
    if not (root / "index.jsonl").exists():
        return
    from sector.store import SectorStore
    store = SectorStore(root)
    plan = SectorQueryPlan(segments=["hbm"], days=30, keywords=["HBM"])
    got = search_with_plan(store, plan, k=8)
    if len(got) >= 4:
        top4 = got[:4]
        assert sum(1 for c in top4 if c.memory_segment in ("hbm", "mixed")) >= 2
```

- [ ] **Step 2: 실패 확인**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_retrieve_plan.py -v`
Expected: FAIL — `ImportError: cannot import name 'search_with_plan'`

- [ ] **Step 3: 구현**

`engine/sector/retrieve.py`에서 `search()`의 균형 로직(41-62행)을 `_balanced_top`으로 추출하고 `search_with_plan`을 추가:

```python
def _balanced_top(ranked: list[SectorCard], k: int) -> list[SectorCard]:
    """정렬된 카드에서 상위 k개 — pos·neg 각 min(2, 보유수) 보장. 입력 순서 보존."""
    pos = [c for c in ranked if c.direction == "pos"]
    neg = [c for c in ranked if c.direction == "neg"]
    reserved_ids = {c.id for c in pos[:min(2, len(pos))] + neg[:min(2, len(neg))]}
    if len(reserved_ids) >= k:
        return [c for c in ranked if c.id in reserved_ids][:k]
    fill = [c for c in ranked if c.id not in reserved_ids][:k - len(reserved_ids)]
    keep = reserved_ids | {c.id for c in fill}
    return [c for c in ranked if c.id in keep][:k]
```

`search()` 본문의 41-62행(균형 로직)을 다음으로 교체:

```python
    cards = _ranked(cards)
    return _balanced_top(cards, k)
```

`search_with_plan` 추가:

```python
import datetime as _dt

_GRADE_W = {"S": 1.0, "A": 0.8, "B": 0.5, "C": 0.3, "D": 0.1}


def _age_days(ts: str, now: _dt.datetime) -> float:
    try:
        d = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return max(0.0, (now - d).total_seconds() / 86400)
    except Exception:  # noqa: BLE001 — ts 파싱 실패 카드는 오래된 것으로 취급
        return 999.0


def _score(c: SectorCard, plan, now: _dt.datetime) -> float:
    """플랜 관련성 + 중요도 + 최신성 + 출처 등급 가중합. 가중치는 상수로 시작 —
    튜닝은 sector_rag 레이어의 plan/rule_plan 로그가 쌓인 뒤 (스펙 §4)."""
    s = 0.0
    if plan.segments:
        if c.memory_segment in plan.segments:
            s += 3.0
        elif c.memory_segment == "mixed":
            s += 0.9
    if plan.entities and set(plan.entities) & set(c.entities):
        s += 2.0
    if plan.keywords:
        text = f"{c.title} {c.interpreted_signal} {c.raw_quote}".lower()
        s += 2.0 * sum(1 for kw in plan.keywords if kw.lower() in text) / len(plan.keywords)
    if plan.event_types and c.event_type in plan.event_types:
        s += 1.0
    s += c.magnitude / 3.0
    s += max(0.0, 1.0 - _age_days(c.ts, now) / max(plan.days, 1))
    s += _GRADE_W.get(c.source_grade, 0.3)
    return s


def search_with_plan(store: SectorStore, plan, *, k: int = 12) -> list[SectorCard]:
    """SectorQueryPlan 기반 검색 — LLM/규칙 플랜 공용 실행부."""
    cards = store.read_cards(days=plan.days)
    if not cards or k <= 0:
        return []
    now = _dt.datetime.now(_dt.timezone.utc)
    ranked = sorted(cards, key=lambda c: (_score(c, plan, now), c.ts), reverse=True)
    return _balanced_top(ranked, k)
```

- [ ] **Step 4: 통과 확인 (신규 + 기존 회귀)**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_retrieve_plan.py tests/test_sector_chat_injection.py tests/test_sector_queryplan.py -v`
Expected: PASS 전체 — 특히 `search` 리팩터 후 기존 테스트 무회귀

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/retrieve.py engine/tests/test_sector_retrieve_plan.py
git commit -m "feat(sector): 플랜 기반 카드 스코어링 search_with_plan — 균형 보장 유지 (4/7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: 오케스트레이터 배선 + 대조 로그

**Files:**
- Modify: `engine/orchestrator.py:240-276` (sector_rag 블록 교체)
- Test: `engine/tests/test_sector_chat_injection.py` (배선 테스트 추가)

**Interfaces:**
- Consumes: `plan_query`(Task 3), `search_with_plan`(Task 4), `metric_summary`(Task 1), 기존 `sector_typed_facts`/`cycle_context`
- Produces: `sector_rag` 레이어에 `plan`, `rule_plan`, `planner_fallback`, `planner_ms`, `metric_notes` 필드 추가. `sector_cycle_text`에 지표 요약 병합(합성·감사로 흐르는 기존 채널 재사용 — synthesize 시그니처 불변)

- [ ] **Step 1: 오케스트레이터 블록 교체**

`engine/orchestrator.py` 240-276행(`# SECTOR_RAG` 블록)을 다음으로 교체:

```python
    # SECTOR_RAG — LLM 쿼리 플래너 (2026-07-13, 스펙: specs/2026-07-13-sector-rag-llm-query-planner-design.md)
    # 게이트(키워드) → plan_query(경량 sonnet, 실패 시 규칙 강등) → search_with_plan.
    # rule_plan을 같이 기록해 LLM 기여를 사후 측정. 실패해도 비차단 (degrade).
    sector_cards = []
    sector_facts: list = []
    sector_cycle_text = ""
    if profile.sector_rag_enabled:
        try:
            from sector.api import _get_store
            from sector.metrics_registry import metric_summary
            from sector.queryplan import plan_query
            from sector.retrieve import search_with_plan
            metric_notes: list[str] = []
            outcome = await plan_query(plan.standalone_question or "", overrides)
            if outcome:
                qp = outcome.plan
                _store = _get_store()
                sector_cards = search_with_plan(_store, qp, k=12)
                metric_notes = [t for t in (metric_summary(_store, m)
                                            for m in qp.metrics) if t]
                if not outcome.fallback:
                    models_used.add("sonnet-4.6")
            if outcome and (sector_cards or metric_notes):
                from sector.cycle import compute as _cycle_compute
                from sector.evidence import cycle_context, sector_typed_facts
                try:
                    sector_facts = sector_typed_facts(_store)
                    sector_cycle_text = cycle_context(_cycle_compute(_store))
                except Exception:  # noqa: BLE001 — 부가 주입 실패가 카드 경로를 못 죽임
                    sector_facts, sector_cycle_text = [], ""
                if metric_notes:
                    # 지표 요약은 사이클 텍스트 채널에 병합 — 합성·감사로 함께 흐름
                    sector_cycle_text = "\n".join(
                        [t for t in [sector_cycle_text, *metric_notes] if t])
                yield _layer("sector_rag", {
                    "entities": qp.entities or ["MEMORY_SECTOR"],
                    "plan": qp.model_dump(),
                    "rule_plan": outcome.rule_plan.model_dump(),
                    "planner_fallback": outcome.fallback,
                    "planner_ms": outcome.planner_ms,
                    "metric_notes": metric_notes,
                    "cycle": sector_cycle_text or None,
                    "sector_typed_facts": [{"id": f.id, "value": f.value, "unit": f.unit,
                                            "period": f.period, "label": f.label}
                                           for f in sector_facts],
                    "cards": [{"id": c.id, "axis": c.axis, "direction": c.direction,
                               "magnitude": c.magnitude, "source_grade": c.source_grade,
                               "title": c.title, "interpreted_signal": c.interpreted_signal,
                               "raw_quote": c.raw_quote[:200], "url": c.url,
                               "ts": c.ts, "entities": c.entities} for c in sector_cards],
                })
        except Exception:  # noqa: BLE001
            degraded.append("sector_rag")
            sector_cards = []
    else:
        yield _layer("sector_rag", {"skipped": True,
                                    "reason": f"프로필 {profile.name} — 섹터 메모리 생략"})
```

- [ ] **Step 2: 배선 테스트 추가**

`engine/tests/test_sector_chat_injection.py`에 추가:

```python
def test_metric_notes_merge_into_cycle_channel(tmp_path):
    """지표 요약이 사이클 텍스트 채널에 병합돼 합성·감사로 흐른다 (Task 5 배선 규칙)."""
    # 오케스트레이터 전체 실행 없이 병합 규칙만 검증 (전체 경로는 라이브 확인)
    sector_cycle_text = "[메모리 섹터 사이클 판정] UP"
    metric_notes = ["[섹터 지표] 한국 반도체 수출액: 110 k_usd (2026-07, +10.0%)"]
    merged = "\n".join([t for t in [sector_cycle_text, *metric_notes] if t])
    assert "사이클 판정" in merged and "수출액" in merged

    # 사이클 텍스트가 비어도 지표만으로 성립
    merged2 = "\n".join([t for t in ["", *metric_notes] if t])
    assert merged2 == metric_notes[0]
```

- [ ] **Step 3: 임포트 스모크 + 전체 섹터 테스트**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -c "import orchestrator" && .venv/bin/python -m pytest tests/ -k "sector" -v`
Expected: import 무오류, 섹터 테스트 전체 PASS

- [ ] **Step 4: 커밋**

```bash
git add engine/orchestrator.py engine/tests/test_sector_chat_injection.py
git commit -m "feat(sector): 채팅 파이프라인에 쿼리 플래너 배선 — plan/rule_plan 대조 로그, 지표 요약 주입 (5/7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: 라이브 검증 + 배포

**Files:**
- Create: `engine/tests/test_sector_queryplan_live.py`
- 배포: `pm2 restart attn-engine`

**Interfaces:**
- Consumes: 전체 (Task 1~5)

- [ ] **Step 1: 라이브 플래너 테스트 작성** (기존 `test_price_live.py`류 패턴 — API 키 없으면 skip)

```python
# engine/tests/test_sector_queryplan_live.py
"""LLM 플래너 라이브 검증 — 실제 상류 출력 층 (test-with-real-upstream-outputs).

실행: cd engine && .venv/bin/python -m pytest tests/test_sector_queryplan_live.py -v -m live
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402
from sector.queryplan import plan_query  # noqa: E402

pytestmark = pytest.mark.live

_NO_KEY = not (settings.claude_api_key or settings.openai_api_key)


@pytest.mark.skipif(_NO_KEY, reason="API 키 없음")
def test_live_planner_hbm_question():
    out = asyncio.run(plan_query("HBM 공급 요즘 타이트해?", timeout=20.0))
    assert out is not None and not out.fallback, "라이브 플래너가 폴백됨"
    assert "hbm" in out.plan.segments


@pytest.mark.skipif(_NO_KEY, reason="API 키 없음")
def test_live_planner_metric_routing():
    out = asyncio.run(plan_query("한국 반도체 수출 요즘 어때?", timeout=20.0))
    assert out is not None and not out.fallback
    assert "kr_semi_export" in out.plan.metrics


@pytest.mark.skipif(_NO_KEY, reason="API 키 없음")
def test_live_planner_period_widening():
    out = asyncio.run(plan_query("6월에 메모리 쪽 무슨 일 있었어?", timeout=20.0))
    assert out is not None and not out.fallback
    assert out.plan.days > 14
```

주의: `engine/pytest.ini`에 `live` 마커가 이미 등록돼 있는지 확인 (`grep -n "live" engine/pytest.ini`). 없으면 `markers = live: 실제 외부 API 호출` 추가.

- [ ] **Step 2: 라이브 테스트 실행**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_queryplan_live.py -v`
Expected: PASS 3건 (키 있는 환경). 플래너 출력이 스키마 통과하고 세그먼트·지표·기간이 기대대로 나오는지 — 실패하면 프롬프트를 조정하고 재실행 (대량 실패 = 프롬프트 버그 신호, 정책 탓 아님)

- [ ] **Step 3: 전체 테스트 + 배포**

```bash
cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/ -v --ignore=tests/test_price_live.py --ignore=tests/test_toss_live.py
pm2 restart attn-engine
```

Expected: 전체 PASS 후 재시작. `pm2 logs attn-engine --lines 20 --nostream`으로 기동 확인

- [ ] **Step 4: 완성 기준 3종 질문 라이브 확인 (UI 스크린샷)**

스펙 완성 기준 — playwright로 로그인 → 채팅에 아래 3개 질문 → 답변·근거 캡처 후 눈으로 확인 (curl 보고 금지 — verify-ui-with-screenshots):

1. "HBM 공급 어때?" → 근거 카드가 HBM 세그먼트 위주인지
2. "한국 반도체 수출 어때?" → 답변에 실제 수출 수치가 인용되는지
3. "6월에 메모리 쪽 무슨 일 있었어?" → 6월 카드가 검색되는지

부가 확인: 엔진 로그 또는 sector_rag 레이어에서 `plan`/`rule_plan`/`planner_ms` 기록 확인, 비섹터 질문("현대차 주가 어때?")에서 플래너 미호출 확인.

- [ ] **Step 5: 커밋**

```bash
git add engine/tests/test_sector_queryplan_live.py engine/pytest.ini
git commit -m "test(sector): 쿼리 플래너 라이브 검증 3종 — 실제 LLM 출력 층 (6/7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: codex 리뷰 + 반영

**Files:**
- Create: `docs/sector-rag-queryplanner-review_codex.md` (리뷰 결과)
- Modify: 리뷰 지적 사항에 따라

- [ ] **Step 1: codex 리뷰 실행**

```bash
cd /home/ryze_yn/attn-viewer && codex exec --sandbox read-only \
  "git log --oneline로 '쿼리 플래너' 관련 최근 커밋들을 찾고 그 diff를 리뷰해줘. \
   스펙은 docs/superpowers/specs/2026-07-13-sector-rag-llm-query-planner-design.md. \
   관점: 정확성 버그, never-raise 위반, 스코어링 논리 오류, 프롬프트 인젝션(질문이 플래너 프롬프트에 들어감), \
   기존 search_for_question 경로 회귀. 심각도별로 정리." \
  > docs/sector-rag-queryplanner-review_codex.md
```

- [ ] **Step 2: 리뷰 지적 사항 검토·반영**

superpowers:receiving-code-review 스킬 사용 — 지적을 맹목 수용하지 말고 기술 검증 후 반영. 반영 커밋:

```bash
git add -A docs/sector-rag-queryplanner-review_codex.md <수정 파일들>
git commit -m "fix(sector): codex 리뷰 반영 — <요지> (7/7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 3: 리뷰 반영으로 코드가 바뀌었으면** 전체 테스트 재실행 + `pm2 restart attn-engine` + 완성 기준 3종 재확인
