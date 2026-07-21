# 시황 리포트 Phase 1 — 데이터 입력 조립 (Report Input Assembly) 구현 계획 · v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 수집 데이터(SectorCards + **SaveTicker firehose 전량 raw** + MetricObservations)를 파이프라인이 소비할 **결정적** "리포트 입력 번들(ReportInput)"로 조립한다. 메트릭은 기존 `metric_summary()`(시리즈 그룹핑 내장)를 재사용하고, 토스 종목·증권사 리포트·과거사례 지식층은 빈 seam으로 남긴다.

**Architecture:** 순수 결정적(LLM 없음). `engine/sector/report_input.py`에 `ReportInput` 계약 + `assemble_report_input()`. 카드/raw는 **주입 now 기준 창(window)으로 코드가 정밀 필터**(store의 실시계 필터 미사용). 메트릭은 `metrics_registry.metric_summary()` 재사용(다중 시리즈 그룹핑·delta_pct 처리 이미 됨). SaveTicker firehose는 전 세계 경제뉴스 전량이며 **메모리 선별은 Phase 2의 1차 LLM 필터**가 한다.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest. 기존 `engine/sector/` 관례.

## Global Constraints

- 순수 결정적: 이 Phase엔 LLM 콜 없음. — 설계 §1 "숫자는 코드가"
- **결정성**: 주입한 `now`가 유일한 시계 기준. 실시계(`datetime.now`) 의존 금지(테스트 flaky 방지). — codex BLOCKER3
- **창 필터**: `win_from ≤ ts ≤ now`, `win_from = now - window_hours`. 파싱 불가·창 밖·미래(>now) 레코드는 **제외**(now로 대체 금지). — codex BLOCKER3
- **다중 시리즈 금지**: 메트릭은 시리즈별 그룹핑 없이 trend 계산 금지 → `metric_summary()` 재사용. — codex BLOCKER1
- **firehose 파티션은 KST**: month 유도로 놓치지 말 것 → `months=None`으로 전 파티션 읽고 창 필터. — codex BLOCKER2
- never-raise + **진단 표기**: 누락/손상/절단은 예외 없이 `diagnostics`에 사유·카운트로 남긴다. — 설계 §1, codex SHOULD-FIX
- seam은 빈 리스트: `stock_signals`, `analyst_reports`, `external_knowledge`. — 사용자 지시 2026-07-21
- 시간 비교는 **aware UTC로 정규화** 후. KST(+09:00) 소스도 UTC로 변환해 비교.

**트리거 스케줄(Phase 3):** SaveTicker 수집 주기 정렬 — 하루 2회 **KST 04:39 / 16:39**. Phase 3에서 구현.

---

## File Structure

- Create: `engine/sector/report_input.py` — `MetricSummary`·`ReportInputDiagnostics`·`ReportInput` 계약 + `_parse_ts`/`_to_utc`/`_in_window` 헬퍼 + `build_metric_summaries()` + `assemble_report_input()`.
- Modify: `engine/sector/store.py` — `read_raw_news()` 추가(Task 2).
- Create: `engine/tests/test_report_input.py` — 조립/창/메트릭 테스트.
- Modify: `engine/tests/test_sector_store.py` — `read_raw_news` 라운드트립 테스트(store 단독).
- (참조·재사용) `engine/sector/metrics_registry.py` — `METRIC_REGISTRY`, `metric_summary(store, metric) -> str`.
- (참조) `engine/sector/store.py` — `read_cards(*, days, limit)`, `append_raw_news`, `_raw_path`; `engine/sector/contracts.py` — `SectorCard`, `RawNewsDoc`.

---

### Task 1: 계약 + 시간 헬퍼

**Files:**
- Create: `engine/sector/report_input.py`
- Test: `engine/tests/test_report_input.py`

**Interfaces:**
- Produces:
  - `class MetricSummary(BaseModel)`: `metric: str`, `label: str`, `summary: str`, `available: bool`.
  - `class ReportInputDiagnostics(BaseModel)`: `cards_in_window: int`, `raw_news_in_window: int`, `cards_scanned: int`, `raw_scanned: int`, `metrics_missing: list[str] = []`.
  - `class ReportInput(BaseModel)`: `window_from: str`, `window_to: str`, `cards: list[SectorCard]=[]`, `raw_news: list[RawNewsDoc]=[]`, `metrics: list[MetricSummary]=[]`, `diagnostics: ReportInputDiagnostics`, `stock_signals: list[dict]=[]`, `analyst_reports: list[dict]=[]`, `external_knowledge: list[dict]=[]`.
  - `def _to_utc(dt: datetime) -> datetime`, `def _parse_ts(ts: str) -> datetime | None` (둘 다 aware UTC 반환).

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_input.py
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_input import (
    MetricSummary, ReportInput, ReportInputDiagnostics, _parse_ts, _to_utc,
)


def test_seams_empty_and_diagnostics_required():
    ri = ReportInput(window_from="a", window_to="b",
                     diagnostics=ReportInputDiagnostics(
                         cards_in_window=0, raw_news_in_window=0,
                         cards_scanned=0, raw_scanned=0))
    assert ri.stock_signals == [] and ri.analyst_reports == [] and ri.external_knowledge == []
    assert ri.metrics == [] and ri.diagnostics.metrics_missing == []


def test_parse_ts_normalizes_kst_to_utc():
    # 2026-07-21T16:23:13+09:00 == 07:23:13Z
    dt = _parse_ts("2026-07-21T16:23:13+09:00")
    assert dt == datetime(2026, 7, 21, 7, 23, 13, tzinfo=timezone.utc)
    assert _parse_ts("garbage") is None
    assert _parse_ts("") is None


def test_to_utc_adds_tz_when_naive():
    naive = datetime(2026, 7, 21, 12, 0)
    assert _to_utc(naive) == datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && pytest tests/test_report_input.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sector.report_input'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/sector/report_input.py
"""리포트 입력 번들 조립 — 결정적(LLM 없음). Phase 2 파이프라인의 입력.

기존 수집 데이터만 사용: SectorCards + SaveTicker firehose raw + 메트릭 요약.
토스 종목·증권사 리포트·과거사례 지식층은 seam(빈 리스트)으로 남긴다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from sector.contracts import RawNewsDoc, SectorCard


class MetricSummary(BaseModel):
    metric: str
    label: str
    summary: str = ""       # metric_summary() 한 줄 요약; 부재/실패 시 ""
    available: bool = False


class ReportInputDiagnostics(BaseModel):
    cards_in_window: int
    raw_news_in_window: int
    cards_scanned: int
    raw_scanned: int
    # drop 사유별 카운트 (codex R2 SHOULD-FIX — 투명성)
    cards_dropped_unparsed: int = 0
    cards_dropped_future: int = 0
    cards_dropped_out: int = 0
    raw_dropped_unparsed: int = 0
    raw_dropped_future: int = 0
    raw_dropped_out: int = 0
    metrics_missing: list[str] = Field(default_factory=list)


class ReportInput(BaseModel):
    window_from: str
    window_to: str
    cards: list[SectorCard] = Field(default_factory=list)         # 구글뉴스 판정 메모리 카드
    raw_news: list[RawNewsDoc] = Field(default_factory=list)      # SaveTicker firehose 전량(창) — Phase2 1차 필터 대상
    metrics: list[MetricSummary] = Field(default_factory=list)
    diagnostics: ReportInputDiagnostics
    # seams — 나중에 채움(사용자 지시): 지금은 항상 빈 리스트
    stock_signals: list[dict] = Field(default_factory=list)       # 토스 종목(차트·수급·다이버전스)
    analyst_reports: list[dict] = Field(default_factory=list)     # 증권사 리포트(목표가·투자의견)
    external_knowledge: list[dict] = Field(default_factory=list)  # 과거사례/규칙(다른 세션)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    """ISO8601(Z/offset/naive) → aware UTC. 파싱 불가 시 None."""
    if not ts:
        return None
    raw = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _to_utc(dt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && pytest tests/test_report_input.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_input.py engine/tests/test_report_input.py
git commit -m "feat(report): ReportInput 계약 + 시간 헬퍼(aware UTC)"
```

---

### Task 2: SectorStore.read_raw_news — firehose 읽기

기존 store엔 `append_raw_news`만 있고 읽기 메서드가 없다.

**Files:**
- Modify: `engine/sector/store.py` (append_raw_news 아래 + read_cards 슬라이스 가드)
- Test: `engine/tests/test_sector_store.py` (store 단독 — NIT 반영)

**Interfaces:**
- Produces: `def read_raw_news(self, *, months: list[str] | None = None, limit: int | None = None) -> list[RawNewsDoc]` — created_at **파싱 datetime** 내림차순, **id 교차파티션 dedup(최신 우선)**, `limit is None`이면 무제한(codex R2). `months is None`이면 news_raw/*.jsonl 전체.
- Also modify: `read_cards(*, ..., limit: int | None = 500)` — `limit is None`이면 무제한(창 필터가 호출자에서 정밀히 되도록). 기존 호출자(기본 500)엔 영향 없음.

- [ ] **Step 1: Write the failing test**

```python
# append to engine/tests/test_sector_store.py  (기존 import 관례 그대로 사용)
from sector.contracts import RawNewsDoc


def test_read_raw_news_sorted_by_parsed_time(tmp_path):
    s = SectorStore(tmp_path)
    s.append_raw_news([
        RawNewsDoc(id="1", title="BOJ", created_at="2026-07-21T16:23:13+09:00"),  # 07:23Z
        RawNewsDoc(id="2", title="MU",  created_at="2026-07-21T09:00:00+00:00"),  # 09:00Z (더 최신)
    ])
    got = s.read_raw_news()               # months=None → 전체, limit=None → 무제한
    assert [d.id for d in got] == ["2", "1"]  # 파싱 datetime 내림차순 (문자열 정렬이면 틀림)
    assert s.read_raw_news(months=[]) == []    # 빈 리스트는 "선택 없음"(전체 아님)


def test_read_raw_news_dedups_by_id_across_partitions(tmp_path):
    s = SectorStore(tmp_path)
    # 같은 id가 서로 다른 월 파티션에 존재하는 상황을 직접 만든다
    (s.root / "news_raw").mkdir(parents=True, exist_ok=True)
    (s.root / "news_raw" / "2026-06.jsonl").write_text(
        RawNewsDoc(id="dup", title="jun", created_at="2026-06-30T23:00:00+00:00").model_dump_json() + "\n",
        encoding="utf-8")
    (s.root / "news_raw" / "2026-07.jsonl").write_text(
        RawNewsDoc(id="dup", title="jul", created_at="2026-07-01T01:00:00+00:00").model_dump_json() + "\n",
        encoding="utf-8")
    got = s.read_raw_news()
    assert [d.id for d in got] == ["dup"]      # 교차파티션 중복 1건으로
    assert got[0].title == "jul"               # 최신(파싱시각 큰) 것이 남음
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && pytest tests/test_sector_store.py -k read_raw_news -v`
Expected: FAIL — `AttributeError: 'SectorStore' object has no attribute 'read_raw_news'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to engine/sector/store.py, right after append_raw_news().
# 파일 상단에 이미 존재: import datetime as _dt, RawNewsDoc import.
    def read_raw_news(self, *, months: list[str] | None = None,
                      limit: int | None = None) -> list[RawNewsDoc]:
        """firehose raw 뉴스 읽기 — created_at 파싱 내림차순, id 교차파티션 dedup(최신 우선).

        months is None → news_raw/*.jsonl 전체. months=[] → 선택 없음(빈).
        limit is None → 무제한. 손상 라인·파싱 불가 created_at은 건너뜀(never-raise)."""
        if months is None:
            files = sorted((self.root / "news_raw").glob("*.jsonl"))
        else:
            files = []
            for m in dict.fromkeys(months):          # 중복 파티션 제거
                p = self._raw_path(m)
                if p not in files:
                    files.append(p)
        docs: list[RawNewsDoc] = []
        for p in files:
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    docs.append(RawNewsDoc.model_validate_json(line))
                except Exception:  # noqa: BLE001 — 손상 라인 무시
                    continue

        def _k(d: RawNewsDoc):
            raw = (d.created_at or "").replace("Z", "+00:00")
            try:
                dt = _dt.datetime.fromisoformat(raw)
            except ValueError:
                return _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            return dt.astimezone(_dt.timezone.utc)

        docs.sort(key=_k, reverse=True)
        seen: set[str] = set()
        deduped: list[RawNewsDoc] = []
        for d in docs:                                # 내림차순이므로 첫 등장=최신
            if d.id in seen:
                continue
            seen.add(d.id)
            deduped.append(d)
        return deduped if limit is None else deduped[:limit]
```

그리고 `read_cards`의 슬라이스 가드(`limit=None` 무제한) — 기존 시그니처에서 타입만 넓히고 마지막 슬라이스만 가드:

```python
# engine/sector/store.py read_cards() 내부, 마지막 줄 수정
    def read_cards(self, *, days: int | None = 14, axis: str | None = None,
                   entity: str | None = None, limit: int | None = 500) -> list[SectorCard]:
        ...  # (본문 동일)
        out.sort(key=lambda c: c.ts, reverse=True)
        return out if limit is None else out[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && pytest tests/test_sector_store.py -k read_raw_news -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/sector/store.py engine/tests/test_sector_store.py
git commit -m "feat(sector): SectorStore.read_raw_news — 파싱시각 정렬 firehose 읽기"
```

---

### Task 3: build_metric_summaries — 기존 metric_summary 재사용

**Files:**
- Modify: `engine/sector/report_input.py`
- Test: `engine/tests/test_report_input.py`

**Interfaces:**
- Consumes: `sector.metrics_registry.METRIC_REGISTRY`, `metric_summary(store, metric) -> str` (다중 시리즈 그룹핑·delta_pct 내장; 부재/실패 시 "").
- Produces: `def build_metric_summaries(store, metrics: list[str] | None = None) -> tuple[list[MetricSummary], list[str]]` — (요약 리스트, 누락 metric명 리스트). `metrics is None`이면 `_REPORT_METRICS` allowlist 사용.

- [ ] **Step 1: Write the failing test**

```python
# append to engine/tests/test_report_input.py
from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.report_input import build_metric_summaries, _REPORT_METRICS


def test_build_metric_summaries_marks_missing(tmp_path):
    s = SectorStore(tmp_path)
    # memory_price_usd_per_gb 한 시리즈만 적재 (meta.item으로 시리즈 식별)
    s.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=3.0,
                          unit="$/GB", meta={"item": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=3.5,
                          unit="$/GB", meta={"item": "DRAM"}),
    ])
    out, missing = build_metric_summaries(s, metrics=["memory_price_usd_per_gb", "token_price"])
    by = {m.metric: m for m in out}
    assert by["memory_price_usd_per_gb"].available is True
    assert by["memory_price_usd_per_gb"].summary != ""
    assert by["token_price"].available is False        # 미적재
    assert missing == ["token_price"]


def test_build_metric_summaries_empty_list_is_empty(tmp_path):
    s = SectorStore(tmp_path)
    out, missing = build_metric_summaries(s, metrics=[])   # [] ≠ None
    assert out == [] and missing == []


def test_report_allowlist_covers_core_series():
    for m in ("memory_price_usd_per_gb", "memory_capex", "equip_revenue",
              "tw_monthly_revenue", "openrouter_daily_tokens", "hyperscaler_capex"):
        assert m in _REPORT_METRICS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && pytest tests/test_report_input.py -k metric_summaries -v`
Expected: FAIL — `ImportError: cannot import name 'build_metric_summaries'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to engine/sector/report_input.py
from sector.metrics_registry import METRIC_REGISTRY, metric_summary  # noqa: E402

# 리포트 입력 메트릭 allowlist — 사이클/수요/공급/AI 수요 대표 시리즈 (codex SHOULD-FIX)
_REPORT_METRICS = [
    "memory_price_usd_per_gb",   # 현물가 — 사이클 핵심
    "kr_semi_production_index",  # 생산·재고
    "kr_semi_export",            # 수출액 — 수요 선행
    "memory_capex",              # 3사 CAPEX — 공급 증설
    "equip_revenue",             # 장비사 매출 — 공급 선행
    "hyperscaler_capex",         # 전방 capex
    "ai_chip_revenue",           # AI칩 매출
    "tw_monthly_revenue",        # 대만 ODM/TSMC
    "token_price",               # 토큰 단가 — AI 수요
    "openrouter_daily_tokens",   # 토큰 사용량 — AI 수요
]


def build_metric_summaries(store, metrics: list[str] | None = None
                           ) -> tuple[list[MetricSummary], list[str]]:
    names = _REPORT_METRICS if metrics is None else metrics
    out: list[MetricSummary] = []
    missing: list[str] = []
    for m in names:
        info = METRIC_REGISTRY.get(m, {})
        try:
            summ = metric_summary(store, m)     # "" if 부재/실패
        except Exception:  # noqa: BLE001 — never-raise, 진단으로만
            summ = ""
        available = bool(summ)
        if not available:
            missing.append(m)
        out.append(MetricSummary(metric=m, label=info.get("label", m),
                                 summary=summ, available=available))
    return out, missing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && pytest tests/test_report_input.py -k metric_summaries -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_input.py engine/tests/test_report_input.py
git commit -m "feat(report): build_metric_summaries — metric_summary 재사용 + allowlist"
```

---

### Task 4: assemble_report_input — 결정적 창 조립

**Files:**
- Modify: `engine/sector/report_input.py`
- Test: `engine/tests/test_report_input.py`

**Interfaces:**
- Consumes: `SectorStore.read_cards(*, days=None, limit)`, `SectorStore.read_raw_news(*, months=None, limit)` (Task 2), `build_metric_summaries` (Task 3), `_parse_ts`/`_to_utc` (Task 1).
- Produces: `def assemble_report_input(store, *, window_hours: int = 12, now: datetime | None = None, metrics: list[str] | None = None) -> ReportInput`.

- [ ] **Step 1: Write the failing test**

```python
# append to engine/tests/test_report_input.py
from sector.contracts import RawNewsDoc, SectorCard
from sector.report_input import assemble_report_input


def _card(cid, ts):
    return SectorCard(id=cid, ts=ts, axis="A", title=f"card {cid}")


def test_assemble_window_is_deterministic_and_bounded(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([
        _card("in",     "2026-07-21T15:00:00+00:00"),  # 창 안(6h 전)
        _card("old",    "2026-07-21T03:00:00+00:00"),  # 창 밖(18h 전)
        _card("future", "2026-07-21T23:00:00+00:00"),  # now 이후 → 제외
        _card("bad",    "not-a-date"),                 # 파싱 불가 → 제외
    ])
    s.append_raw_news([
        RawNewsDoc(id="rn_in",  title="in",  created_at="2026-07-22T00:30:00+09:00"),  # 15:30Z 창 안
        RawNewsDoc(id="rn_old", title="old", created_at="2026-07-21T03:00:00+00:00"),  # 창 밖
    ])
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[])
    assert {c.id for c in ri.cards} == {"in"}                 # old/future/bad 전부 제외
    assert {d.id for d in ri.raw_news} == {"rn_in"}
    assert ri.window_to == now.isoformat()
    assert ri.diagnostics.cards_in_window == 1
    assert ri.diagnostics.raw_news_in_window == 1
    assert ri.diagnostics.cards_scanned == 4
    assert ri.diagnostics.cards_dropped_future == 1     # future 카드
    assert ri.diagnostics.cards_dropped_out == 1        # old 카드
    assert ri.diagnostics.cards_dropped_unparsed == 1   # bad 카드
    assert ri.stock_signals == [] and ri.external_knowledge == []


def test_assemble_uses_injected_now_not_wall_clock(tmp_path):
    # 과거 시점 now를 주입해도 결정적으로 동작(실시계 의존 없음)
    s = SectorStore(tmp_path)
    past = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)
    s.append_cards([_card("x", "2020-01-01T09:00:00+00:00")])  # past-3h → 창 안
    ri = assemble_report_input(s, window_hours=12, now=past, metrics=[])
    assert {c.id for c in ri.cards} == {"x"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && pytest tests/test_report_input.py -k assemble -v`
Expected: FAIL — `ImportError: cannot import name 'assemble_report_input'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to engine/sector/report_input.py
from datetime import timedelta  # noqa: E402  (add to datetime import at top)


def _in_window(items, ts_getter, win_from: datetime, now: datetime):
    """창 필터 + drop 사유 카운트. 반환: (kept, stats). 경계 포함, 미래(>now) 제외."""
    kept = []
    unparsed = future = out = 0
    for it in items:
        dt = _parse_ts(ts_getter(it))
        if dt is None:
            unparsed += 1
            continue
        if dt > now:
            future += 1
            continue
        if dt < win_from:
            out += 1
            continue
        kept.append(it)
    return kept, {"scanned": len(items), "unparsed": unparsed, "future": future, "out": out}


def assemble_report_input(store, *, window_hours: int = 12,
                          now: datetime | None = None,
                          metrics: list[str] | None = None) -> ReportInput:
    now = _to_utc(now or datetime.now(timezone.utc))
    win_from = now - timedelta(hours=window_hours)

    # 전량 읽어(limit=None) 주입 now로 정밀 컷 — 캡 절단 없음(codex R2), 실시계 미사용(결정성)
    cards, cstat = _in_window(store.read_cards(days=None, limit=None),
                              lambda c: c.ts, win_from, now)
    raw_news, rstat = _in_window(store.read_raw_news(months=None, limit=None),
                                 lambda d: d.created_at, win_from, now)

    metric_summaries, missing = build_metric_summaries(store, metrics)
    diag = ReportInputDiagnostics(
        cards_in_window=len(cards), raw_news_in_window=len(raw_news),
        cards_scanned=cstat["scanned"], raw_scanned=rstat["scanned"],
        cards_dropped_unparsed=cstat["unparsed"], cards_dropped_future=cstat["future"],
        cards_dropped_out=cstat["out"],
        raw_dropped_unparsed=rstat["unparsed"], raw_dropped_future=rstat["future"],
        raw_dropped_out=rstat["out"],
        metrics_missing=missing,
    )
    return ReportInput(
        window_from=win_from.isoformat(), window_to=now.isoformat(),
        cards=cards, raw_news=raw_news, metrics=metric_summaries, diagnostics=diag,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && pytest tests/test_report_input.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_input.py engine/tests/test_report_input.py
git commit -m "feat(report): assemble_report_input — 결정적 창 조립 + 진단"
```

---

## Self-Review

- **Spec coverage**: 설계 §3의 정형 지표(metric_summary) + SectorCard + SaveTicker firehose raw를 ReportInput이 담는다. 토스(§3-C)·증권사(§3-D)·과거사례(§5)는 seam. 부합.
- **codex 리뷰 반영**: BLOCKER1(다중 시리즈→metric_summary 재사용), BLOCKER2(월경계→months=None 전량+창필터), BLOCKER3(결정성→days=None+주입 now+경계/미래/파싱실패 처리). SHOULD-FIX(months is None, 파싱정렬, 진단 diagnostics, allowlist 확장, metrics=[] 구분). NIT(store 테스트는 test_sector_store.py). `_trend` 폐기 → 음수/경계 버그 소멸.
- **Placeholder scan**: 모든 스텝 실제 코드·명령·기대출력. TBD 없음.
- **Type consistency**: `build_metric_summaries`(Task3)·`read_raw_news`(Task2)·`_parse_ts`/`_to_utc`(Task1)를 `assemble_report_input`(Task4)이 사용 — 시그니처 일치. `ReportInput.diagnostics`는 필수 필드(테스트에서 항상 생성).
- **잔여 리스크(수용)**: `read_cards(days=None)`는 index.jsonl 전량 스캔 — 현재 ~1MB, 월 단위 성장. 12h 리포트엔 무해하나 장기적으로 store에 시각-범위 인덱스가 필요할 수 있음(Phase 3 이후 과제). scanned 카운트가 scan_limit에 도달하면 절단 신호 → 후속 계획에서 truncated 플래그 추가.

## 다음 Phase (이 계획 밖)
- Phase 2: 파이프라인 — 1차 relevance 필터(raw_news→메모리 선별)·중요도 필터·합성(주장+overview+finalOpinion), `pipeline.stages` 기록.
- Phase 3: 뷰어 연결(골격 존재) + 스케줄러(KST 04:39/16:39) + run-log.
- seam 채우기: 토스 종목·증권사(사용자 소스 정리 후), 과거사례(다른 세션).
