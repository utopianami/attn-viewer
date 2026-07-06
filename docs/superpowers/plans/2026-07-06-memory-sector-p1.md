# 메모리 섹터 P1 수집 엔진 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 메모리 섹터 이벤트 카드·지표 시계열을 무인 수집→판정→저장하고 `/v1/sector/*` API로 노출하는 engine 패키지 P1.

**Architecture:** `engine/sector/` 독립 패키지. 소스당 수집기 1파일(공통 `collect(store, client=None) -> CollectorResult`), never-block 격리 실행, sonnet 배치 판정으로 뉴스→카드 변환, jsonl 저장, 규칙 기반 사이클 스코어, FastAPI 라우터. 스케줄러는 asyncio 루프이며 기본 OFF.

**Tech Stack:** Python 3.12, FastAPI, httpx, pydantic v2. **신규 pip 의존성 금지.**

## Global Constraints

- 원칙 문서 전문 준수: `docs/memory-sector-implementation-principles_claude.md` (14조)
- **신규 의존성 0**: httpx/pydantic/표준lib만. feedparser·apscheduler 설치 금지
- **기존 코드 수정 범위**: `app/settings.py`(필드 추가), `app/main.py`(라우터 include + 스케줄러 시작), `providers.py`(ROLE_MAP에 `sector_judge` 1줄) — 그 외 stages/orchestrator/tools **수정 금지** (import 재사용은 허용)
- `server.mjs`, `public/**` 절대 수정 금지 (codex 영역). `public/index.html` 절대 git add 금지
- 스케줄러 기본 OFF: `settings.sector_scheduler_enabled=False` 기본값
- 키 없는 수집기는 `status="missing_key"`로 skip — 예외 발생 금지
- 테스트: 파일 첫머리 `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))`, **pytest-asyncio 금지** — sync 함수 안에서 `asyncio.run(...)`. 외부 HTTP는 `httpx.MockTransport`로 목킹
- 전체 스위트 명령: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/ -q --ignore=tests/test_stages_live.py --ignore=tests/test_price_live.py --ignore=tests/test_toss_live.py` — 매 태스크 종료 시 그린 확인
- 커밋 메시지 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 외부 API의 정확한 응답 스키마가 불확실한 수집기는 **실패 시 status="degraded" + detail에 HTTP코드/원인**을 남기는 방어 파싱 필수 (탐사 실패가 엔진을 못 죽임)

## File Structure

```
engine/sector/__init__.py            # 빈 파일
engine/sector/contracts.py           # SectorCard·MetricObservation·RawNewsItem·CollectorResult
engine/sector/store.py               # SectorStore (jsonl append/read, state.json, dedup)
engine/sector/collectors/__init__.py # REGISTRY (모듈 목록)
engine/sector/collectors/saveticker.py
engine/sector/collectors/brave_matrix.py
engine/sector/collectors/rss.py
engine/sector/collectors/dart_edgar.py
engine/sector/collectors/openrouter.py
engine/sector/collectors/status_pages.py
engine/sector/collectors/sdk_downloads.py
engine/sector/collectors/app_charts.py
engine/sector/collectors/mops_tw.py
engine/sector/collectors/customs_kr.py
engine/sector/collectors/kosis.py
engine/sector/collectors/ecos.py
engine/sector/collectors/datalab.py
engine/sector/collectors/yahoo_metrics.py
engine/sector/runner.py              # run_all 격리 실행 + judge 연결 + 상태 집계
engine/sector/judge.py               # sonnet 배치 판정 → SectorCard
engine/sector/retrieve.py            # 구조화 검색
engine/sector/cycle.py               # 규칙 기반 사이클 스코어
engine/sector/api.py                 # APIRouter /v1/sector/*
engine/sector/scheduler.py           # asyncio 루프 (기본 OFF)
engine/tests/test_sector_store.py
engine/tests/test_sector_collectors_news.py
engine/tests/test_sector_collectors_metrics.py
engine/tests/test_sector_judge.py
engine/tests/test_sector_cycle_retrieve.py
engine/tests/test_sector_api.py
```

---

### Task 1: contracts + store

**Files:**
- Create: `engine/sector/__init__.py` (빈 파일), `engine/sector/contracts.py`, `engine/sector/store.py`
- Test: `engine/tests/test_sector_store.py`

**Interfaces (Produces):**
- `SectorCard(id, ts, axis, entities, speaker, edge, event_type, memory_segment, direction, magnitude, time_horizon, source_grade, title, raw_quote, interpreted_signal, numeric, url, source)`
- `MetricObservation(metric, ts, value, unit, meta)`
- `RawNewsItem(id, title, preview, content, source, url, published_at, grade_hint, extra)`
- `CollectorResult(name, kind, items, observations, status, detail, took_ms)`
- `SectorStore(root).append_cards/append_observations/read_cards/read_metric/get_state/set_state/write_status/read_status`

- [ ] **Step 1: 실패 테스트 작성**

```python
# engine/tests/test_sector_store.py
"""메모리 섹터 저장소 — 카드/지표 jsonl append·dedup·조회 (P1 Task 1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import CollectorResult, MetricObservation, RawNewsItem, SectorCard  # noqa: E402
from sector.store import SectorStore  # noqa: E402


def _card(cid="c1", ts="2026-07-06T09:00:00Z", axis="B"):
    return SectorCard(
        id=cid, ts=ts, axis=axis, entities=["META"], edge="B->A",
        event_type="demand_signal", memory_segment="hbm", direction="neg",
        magnitude=2, time_horizon="immediate", source_grade="B",
        title="t", raw_quote="rq", interpreted_signal="is", url="http://x", source="reuters.com",
    )


def test_card_defaults():
    c = _card()
    assert c.speaker is None and c.numeric is None


def test_append_and_read_cards_dedup(tmp_path):
    s = SectorStore(tmp_path)
    n1 = s.append_cards([_card("a"), _card("b")])
    n2 = s.append_cards([_card("b"), _card("c")])   # b는 중복
    assert (n1, n2) == (2, 1)
    got = s.read_cards(days=None)
    assert sorted(c.id for c in got) == ["a", "b", "c"]


def test_read_cards_filters(tmp_path):
    s = SectorStore(tmp_path)
    s.append_cards([_card("a", ts="2026-07-06T09:00:00Z", axis="B"),
                    _card("b", ts="2020-01-01T00:00:00Z", axis="C")])
    assert [c.id for c in s.read_cards(days=30)] == ["a"]
    assert [c.id for c in s.read_cards(days=None, axis="C")] == ["b"]
    assert [c.id for c in s.read_cards(days=None, entity="META")] and \
           s.read_cards(days=None, entity="NVDA") == []


def test_observations_dedup_and_read(tmp_path):
    s = SectorStore(tmp_path)
    o = MetricObservation(metric="token_price", ts="2026-07-06", value=15.0,
                          unit="usd_per_1m", meta={"model": "sonnet"})
    n1 = s.append_observations([o]); n2 = s.append_observations([o])
    assert (n1, n2) == (1, 0)
    rows = s.read_metric("token_price", last_n=10)
    assert rows[0].value == 15.0


def test_state_roundtrip(tmp_path):
    s = SectorStore(tmp_path)
    assert s.get_state("cursor") is None
    s.set_state("cursor", 161424)
    assert SectorStore(tmp_path).get_state("cursor") == 161424


def test_status_roundtrip(tmp_path):
    s = SectorStore(tmp_path)
    r = CollectorResult(name="saveticker", kind="news", status="ok", took_ms=12)
    s.write_status([r])
    st = s.read_status()
    assert st["saveticker"]["status"] == "ok"


def test_raw_news_item_defaults():
    it = RawNewsItem(id="1", title="t")
    assert it.grade_hint is None and it.extra == {}
```

- [ ] **Step 2: 실패 확인** — `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_sector_store.py -q` → `ModuleNotFoundError: sector`

- [ ] **Step 3: 구현**

```python
# engine/sector/contracts.py
"""메모리 섹터 P1 계약 — 카드·지표·수집 결과 (스펙: docs/memory-sector-rag-plan_claude.md §2-1)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Axis = Literal["A", "A_prime", "B", "C", "C0", "E", "P", "market"]
EventType = Literal["demand_signal", "supply_signal", "price_signal", "earnings",
                    "filing", "policy", "speaker", "product_policy", "market_reaction"]


class SectorCard(BaseModel):
    id: str
    ts: str                                   # ISO8601
    axis: Axis
    entities: list[str] = Field(default_factory=list)
    speaker: str | None = None
    edge: str = ""                            # 예: "B->A"
    event_type: EventType = "demand_signal"
    memory_segment: Literal["hbm", "dram", "nand", "mixed"] = "mixed"
    direction: Literal["pos", "neg", "neutral", "mixed"] = "neutral"
    magnitude: int = 1                        # 1~3
    time_horizon: Literal["immediate", "next_quarter", "next_2_4_quarters"] = "immediate"
    source_grade: Literal["S", "A", "B", "C", "D"] = "B"
    title: str
    raw_quote: str = ""                       # 원문 인용 (사실)
    interpreted_signal: str = ""              # LLM 해석 — 원문과 분리
    numeric: dict[str, Any] | None = None     # {"value":..., "unit":...}
    url: str = ""
    source: str = ""


class MetricObservation(BaseModel):
    metric: str                               # jsonl 파일명이 됨 (영숫자·_)
    ts: str                                   # "YYYY-MM-DD" 또는 "YYYY-MM"
    value: float
    unit: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)

    def key(self) -> str:
        """metric 내 dedup 키 — 같은 날짜·같은 대상(meta 주요 필드) 1회."""
        mk = self.meta.get("model") or self.meta.get("code") or self.meta.get("pkg") \
            or self.meta.get("token") or self.meta.get("provider") or self.meta.get("app") or ""
        return f"{self.ts}|{mk}"


class RawNewsItem(BaseModel):
    """수집기 출력 — 판정(judge) 전 뉴스 원료."""
    id: str
    title: str
    preview: str = ""
    content: str = ""
    source: str = ""
    url: str = ""
    published_at: str = ""
    grade_hint: Literal["S", "A", "B", "C", "D"] | None = None   # 예: 공시=S, (카더라)=D
    extra: dict[str, Any] = Field(default_factory=dict)


class CollectorResult(BaseModel):
    name: str
    kind: Literal["news", "metric"]
    items: list[RawNewsItem] = Field(default_factory=list)
    observations: list[MetricObservation] = Field(default_factory=list)
    status: Literal["ok", "degraded", "missing_key", "error"] = "ok"
    detail: str = ""
    took_ms: int = 0
```

```python
# engine/sector/store.py
"""섹터 저장소 — storage/rag/memory_sector/ 아래 jsonl 단일 창구 (원칙 6·계획 §8-2)."""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from sector.contracts import CollectorResult, MetricObservation, SectorCard

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


class SectorStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        (self.root / "cards").mkdir(parents=True, exist_ok=True)
        (self.root / "metrics").mkdir(parents=True, exist_ok=True)
        (self.root / "documents").mkdir(parents=True, exist_ok=True)
        self._index = self.root / "index.jsonl"
        self._state = self.root / "state.json"
        self._status = self.root / "status.json"

    # ---- 카드 ----
    def _known_ids(self) -> set[str]:
        if not self._index.exists():
            return set()
        out = set()
        for line in self._index.read_text(encoding="utf-8").splitlines():
            try:
                out.add(json.loads(line)["id"])
            except Exception:  # noqa: BLE001 — 손상 줄은 건너뜀
                continue
        return out

    def append_cards(self, cards: list[SectorCard]) -> int:
        known = self._known_ids()
        added = 0
        with self._index.open("a", encoding="utf-8") as f:
            for c in cards:
                if c.id in known:
                    continue
                known.add(c.id)
                f.write(c.model_dump_json() + "\n")
                month = (c.ts[:7] or "unknown")
                mdir = self.root / "cards" / month
                mdir.mkdir(parents=True, exist_ok=True)
                (mdir / f"{_SAFE.sub('_', c.id)}.json").write_text(
                    c.model_dump_json(indent=1), encoding="utf-8")
                added += 1
        return added

    def read_cards(self, *, days: int | None = 14, axis: str | None = None,
                   entity: str | None = None, limit: int = 500) -> list[SectorCard]:
        if not self._index.exists():
            return []
        cutoff = None
        if days is not None:
            cutoff = (_dt.datetime.now(_dt.timezone.utc)
                      - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        out: list[SectorCard] = []
        for line in self._index.read_text(encoding="utf-8").splitlines():
            try:
                c = SectorCard.model_validate_json(line)
            except Exception:  # noqa: BLE001
                continue
            if cutoff and c.ts.replace("Z", "") < cutoff:
                continue
            if axis and c.axis != axis:
                continue
            if entity and entity not in c.entities:
                continue
            out.append(c)
        out.sort(key=lambda c: c.ts, reverse=True)
        return out[:limit]

    # ---- 지표 ----
    def _metric_path(self, metric: str) -> Path:
        return self.root / "metrics" / f"{_SAFE.sub('_', metric)}.jsonl"

    def append_observations(self, obs: list[MetricObservation]) -> int:
        added = 0
        by_metric: dict[str, list[MetricObservation]] = {}
        for o in obs:
            by_metric.setdefault(o.metric, []).append(o)
        for metric, rows in by_metric.items():
            p = self._metric_path(metric)
            seen = set()
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    try:
                        seen.add(MetricObservation.model_validate_json(line).key())
                    except Exception:  # noqa: BLE001
                        continue
            with p.open("a", encoding="utf-8") as f:
                for o in rows:
                    if o.key() in seen:
                        continue
                    seen.add(o.key())
                    f.write(o.model_dump_json() + "\n")
                    added += 1
        return added

    def read_metric(self, metric: str, *, last_n: int = 90) -> list[MetricObservation]:
        p = self._metric_path(metric)
        if not p.exists():
            return []
        rows: list[MetricObservation] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(MetricObservation.model_validate_json(line))
            except Exception:  # noqa: BLE001
                continue
        rows.sort(key=lambda o: o.ts)
        return rows[-last_n:]

    # ---- 상태 ----
    def get_state(self, key: str):
        if not self._state.exists():
            return None
        try:
            return json.loads(self._state.read_text(encoding="utf-8")).get(key)
        except Exception:  # noqa: BLE001
            return None

    def set_state(self, key: str, value) -> None:
        data = {}
        if self._state.exists():
            try:
                data = json.loads(self._state.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}
        data[key] = value
        self._state.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def write_status(self, results: list[CollectorResult]) -> None:
        data = {}
        if self._status.exists():
            try:
                data = json.loads(self._status.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        for r in results:
            data[r.name] = {"status": r.status, "detail": r.detail,
                            "took_ms": r.took_ms, "at": now,
                            "items": len(r.items), "observations": len(r.observations)}
        self._status.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                encoding="utf-8")

    def read_status(self) -> dict:
        if not self._status.exists():
            return {}
        try:
            return json.loads(self._status.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
```

`engine/sector/__init__.py`는 빈 파일로 생성.

- [ ] **Step 4: 통과 확인** — `pytest tests/test_sector_store.py -q` → 전부 PASS. 전체 스위트도 그린 확인.
- [ ] **Step 5: 커밋** — `git add engine/sector engine/tests/test_sector_store.py && git commit -m "feat(sector): P1 계약·저장소 — 카드/지표 jsonl, dedup, state/status"`

---

### Task 2: settings 키 + 수집기 공통 규약 + runner

**Files:**
- Modify: `engine/app/settings.py` (키·플래그 필드 추가 — 기존 필드 뒤에)
- Create: `engine/sector/collectors/__init__.py`, `engine/sector/runner.py`
- Test: `engine/tests/test_sector_collectors_news.py` 중 runner 격리 테스트 부분

**Interfaces:**
- Consumes: Task 1 전부
- Produces: 수집기 모듈 규약 — 각 모듈은 `NAME: str`, `KIND: "news"|"metric"`, `async def collect(store, client: httpx.AsyncClient | None = None) -> CollectorResult`. `collectors.REGISTRY: list[module]`. `runner.collect_all(store, only: list[str] | None = None) -> list[CollectorResult]` (news 아이템은 judge로 카드화까지 수행 — judge는 Task 7에서 구현되므로 여기서는 `judge_fn` 주입 가능하게 설계, 기본은 pass-through 저장 안 함)

- [ ] **Step 1: settings 필드 추가** (`engine/app/settings.py`의 `trend_news_cap` 위쪽 아무 데나, 주석 포함)

```python
    # ---- 메모리 섹터 P1 (2026-07-06) — 키는 루트 .env, 없으면 해당 수집기 missing_key로 skip ----
    openrouter_api_key: str = ""      # openrouter.ai 무료 키 (datasets 랭킹용; /models는 키 불필요)
    data_go_kr_api_key: str = ""      # data.go.kr 공공데이터포털 (관세청 수출)
    kosis_api_key: str = ""           # kosis.kr (생산·출하·재고지수)
    ecos_api_key: str = ""            # ecos.bok.or.kr (D램 수출물가지수)
    dart_api_key: str = ""            # opendart.fss.or.kr (한국 공시)
    naver_client_id: str = ""         # developers.naver.com 데이터랩
    naver_client_secret: str = ""
    sector_scheduler_enabled: bool = False        # 원칙 10 — 기본 OFF
    sector_collect_interval_s: int = 43200        # 하루 2회
    sector_storage_dir: str = ""                  # 비면 REPO_ROOT/storage/rag/memory_sector
```

- [ ] **Step 2: runner 실패 테스트** (`engine/tests/test_sector_collectors_news.py` 신규 — 파일 헤더/컨벤션은 Task 1 테스트와 동일)

```python
"""섹터 뉴스 수집기 + runner 격리 (P1 Task 2~4)."""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sector.contracts import CollectorResult, RawNewsItem  # noqa: E402
from sector.store import SectorStore  # noqa: E402
from sector import runner  # noqa: E402


def _mod(name, kind="metric", fail=False):
    m = types.ModuleType(name)
    m.NAME, m.KIND = name, kind
    async def collect(store, client=None):
        if fail:
            raise RuntimeError("boom")
        return CollectorResult(name=name, kind=kind, status="ok")
    m.collect = collect
    return m


def test_collect_all_isolates_failures(tmp_path, monkeypatch):
    mods = [_mod("good"), _mod("bad", fail=True), _mod("good2")]
    monkeypatch.setattr(runner, "_registry", lambda: mods)
    store = SectorStore(tmp_path)
    results = asyncio.run(runner.collect_all(store))
    by = {r.name: r.status for r in results}
    assert by == {"good": "ok", "bad": "error", "good2": "ok"}
    assert store.read_status()["bad"]["status"] == "error"


def test_collect_all_only_filter(tmp_path, monkeypatch):
    mods = [_mod("a"), _mod("b")]
    monkeypatch.setattr(runner, "_registry", lambda: mods)
    results = asyncio.run(runner.collect_all(SectorStore(tmp_path), only=["b"]))
    assert [r.name for r in results] == ["b"]
```

- [ ] **Step 3: 실패 확인** — `pytest tests/test_sector_collectors_news.py -q` → `ModuleNotFoundError` 또는 AttributeError
- [ ] **Step 4: 구현**

```python
# engine/sector/collectors/__init__.py
"""수집기 레지스트리 — 1소스 1파일 (원칙 6). 모듈 규약: NAME, KIND, async collect(store, client=None)."""
from __future__ import annotations


def registry() -> list:
    from sector.collectors import (app_charts, brave_matrix, customs_kr, dart_edgar,
                                   datalab, ecos, kosis, mops_tw, openrouter, rss,
                                   saveticker, sdk_downloads, status_pages, yahoo_metrics)
    return [saveticker, brave_matrix, rss, dart_edgar,
            openrouter, status_pages, sdk_downloads, app_charts,
            mops_tw, customs_kr, kosis, ecos, datalab, yahoo_metrics]
```

```python
# engine/sector/runner.py
"""격리 실행기 — 수집기 하나의 실패가 나머지를 못 막는다 (원칙 2 never-block)."""
from __future__ import annotations

import time

from sector.contracts import CollectorResult, SectorCard
from sector.store import SectorStore


def _registry() -> list:
    from sector.collectors import registry
    return registry()


async def collect_all(store: SectorStore, *, only: list[str] | None = None,
                      judge_fn=None) -> list[CollectorResult]:
    """모든(또는 only 지정) 수집기 실행 → 지표 저장 → 뉴스는 judge_fn으로 카드화.

    judge_fn: async (list[RawNewsItem]) -> list[SectorCard]. None이면 뉴스는 카드화 생략
    (Task 7에서 기본 judge 연결).
    """
    results: list[CollectorResult] = []
    news_items = []
    for mod in _registry():
        if only and mod.NAME not in only:
            continue
        t0 = time.monotonic()
        try:
            r = await mod.collect(store)
        except Exception as exc:  # noqa: BLE001 — 격리가 목적
            r = CollectorResult(name=mod.NAME, kind=getattr(mod, "KIND", "metric"),
                                status="error", detail=f"{type(exc).__name__}: {exc}"[:300])
        r.took_ms = int((time.monotonic() - t0) * 1000)
        if r.observations:
            store.append_observations(r.observations)
        if r.items:
            news_items.extend(r.items)
        results.append(r)
    if judge_fn is None:
        try:
            from sector.judge import judge_items as judge_fn  # noqa: PLC0415
        except Exception:  # noqa: BLE001 — Task 7 이전엔 judge 부재 허용
            judge_fn = None
    if judge_fn is not None and news_items:
        try:
            cards: list[SectorCard] = await judge_fn(news_items)
            store.append_cards(cards)
        except Exception as exc:  # noqa: BLE001 — 판정 실패도 수집을 못 막음
            results.append(CollectorResult(name="judge", kind="news", status="error",
                                           detail=f"{type(exc).__name__}: {exc}"[:300]))
    store.write_status(results)
    return results
```

주의: 이 시점엔 `sector/collectors/` 하위 개별 모듈이 아직 없어 `registry()` import가 실패한다 — Task 2에서는 **모듈 파일 14개를 전부 빈 스텁으로 생성**한다. 스텁 내용(각 파일 동일 패턴, NAME만 파일명):

```python
# engine/sector/collectors/saveticker.py (등 14개 파일 공통 스텁 — 이후 태스크가 본문 교체)
from __future__ import annotations

import httpx

from sector.contracts import CollectorResult
from sector.store import SectorStore

NAME = "saveticker"   # 파일명과 동일하게
KIND = "news"         # 뉴스형: saveticker, brave_matrix, rss, dart_edgar / 나머지는 "metric"


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    return CollectorResult(name=NAME, kind=KIND, status="degraded", detail="not implemented")
```

- [ ] **Step 5: 통과 확인** — 두 테스트 PASS + 전체 스위트 그린
- [ ] **Step 6: 커밋** — `git add engine/app/settings.py engine/sector && git commit -m "feat(sector): 수집기 규약·격리 runner·settings 키 (기본 OFF)"`

---

### Task 3: SaveTicker 수집기 (실측 픽스처)

**Files:**
- Modify: `engine/sector/collectors/saveticker.py` (스텁 교체)
- Test: `engine/tests/test_sector_collectors_news.py`에 추가

**Interfaces:**
- Consumes: store.get_state/set_state (`saveticker_last_id`), RawNewsItem
- Produces: 뉴스 RawNewsItem(grade_hint: "(카더라)"→"D") + `macro_calendar` 지표 관측

**스펙 (2026-07-06 실측 확정 — 계획 §2-7):**
- 목록: `GET https://api.saveticker.com/api/news/list?page_size=50` → `{"news_list":[{id,title,content(83자 미리보기),source,created_at,...}]}`
- 상세: `GET https://api.saveticker.com/api/news/detail/{id}` → `{"news":{id,title,content:[{type,content}...],source,tickers,tags,created_at}}`
- 캘린더: `GET https://api.saveticker.com/api/calendar/events?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` → `{"events":[{id,title,event_date,...}]}` (제목에 ★~★★★)
- 검색 인덱스 비실시간 → search= 사용 금지, last_seen_id 증분
- 키워드 1차 필터 후 매칭 항목만 detail 호출 (전량 detail 금지)

- [ ] **Step 1: 실패 테스트** (실측 응답을 축약한 픽스처 — test_sector_collectors_news.py에 추가)

```python
_ST_LIST = {"news_list": [
    {"id": "161424", "title": "JP모건, 금값 전망 낮춰…4분기 온스당 4,500달러 예상",
     "content": "JP모건은 주요 부문의 금 수요가...", "source": "로이터",
     "created_at": "2026-07-06T17:04:05+09:00"},
    {"id": "161415", "title": "SK하이닉스 10일 나스닥 데뷔… 외국 기업 IPO 최대 기록 예고",
     "content": "SK하이닉스가 글로벌 AI 메모리...", "source": "연합",
     "created_at": "2026-07-06T16:45:00+09:00"},
    {"id": "161167", "title": "(카더라) SK하이닉스 미국 상장 추진…주관사 수수료 0.5% 지급 논의",
     "content": "...", "source": "", "created_at": "2026-07-06T15:00:00+09:00"},
]}
_ST_DETAIL = {"news": {"id": "161415", "title": "SK하이닉스 10일 나스닥 데뷔…",
    "content": [{"type": "text", "content": "SK하이닉스가 290억 달러 규모 ADR 상장을 추진하며"},
                {"type": "text", "content": "- 미국 투자자 접근성 개선"}],
    "source": "연합", "tickers": [{"code": "000660"}], "created_at": "2026-07-06T16:45:00+09:00"}}
_ST_CAL = {"events": [{"id": 1, "title": "6월 ISM 서비스업 PMI ★★★",
                       "event_date": "2026-07-06T23:00:00"}]}


def _st_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/news/list":
            return httpx.Response(200, json=_ST_LIST)
        if p.startswith("/api/news/detail/"):
            return httpx.Response(200, json=_ST_DETAIL)
        if p == "/api/calendar/events":
            return httpx.Response(200, json=_ST_CAL)
        return httpx.Response(404, json={"detail": "Not Found"})
    return httpx.MockTransport(handler)


def test_saveticker_filters_and_fetches_detail(tmp_path):
    from sector.collectors import saveticker
    store = SectorStore(tmp_path)
    client = httpx.AsyncClient(transport=_st_transport())
    r = asyncio.run(saveticker.collect(store, client=client))
    assert r.status == "ok"
    ids = [i.id for i in r.items]
    assert "st-161415" in ids                    # 하이닉스 → 관련, detail 전문 획득
    assert "st-161424" not in ids                # 금값 → 무관 필터
    full = next(i for i in r.items if i.id == "st-161415")
    assert "290억 달러" in full.content           # detail 본문 병합 확인
    rumor = next(i for i in r.items if i.id == "st-161167")
    assert rumor.grade_hint == "D"               # (카더라) → D급
    assert store.get_state("saveticker_last_id") == 161424   # 커서 전진 (최대 id)
    cal = store.read_metric("macro_calendar", last_n=10)
    assert cal and cal[0].value == 3.0           # ★★★ = 3


def test_saveticker_incremental_skips_seen(tmp_path):
    from sector.collectors import saveticker
    store = SectorStore(tmp_path)
    store.set_state("saveticker_last_id", 161424)  # 전부 이미 봄
    client = httpx.AsyncClient(transport=_st_transport())
    r = asyncio.run(saveticker.collect(store, client=client))
    assert r.items == [] and r.status == "ok"
```

- [ ] **Step 2: 실패 확인** — 스텁이라 items 비어 assert 실패
- [ ] **Step 3: 구현** (스텁 본문 교체)

```python
# engine/sector/collectors/saveticker.py
"""SaveTicker — P1 1차 뉴스 소스 (계획 §2-7, 2026-07-06 실측).

목록(미리보기 83자)으로 감지 → 키워드 필터 → 관련 항목만 detail(무인증 전문).
search= 파라미터는 인덱스가 비실시간이라 사용 금지. 비공식 API — 저강도, UA 명시.
"""
from __future__ import annotations

import re

import httpx

from sector.contracts import CollectorResult, MetricObservation, RawNewsItem
from sector.store import SectorStore

NAME = "saveticker"
KIND = "news"
_BASE = "https://api.saveticker.com/api"
_UA = {"User-Agent": "attn-viewer-sector/0.1 (personal research)"}

# 엔티티/주제 키워드 — 제목+미리보기에 하나라도 걸리면 후보 (계획 §1 축 엔티티)
_KEYWORDS = (
    "하이닉스", "삼성전자", "마이크론", "micron", "삼전", "메모리", "hbm", "d램", "dram",
    "낸드", "nand", "반도체", "tsmc", "엔비디아", "nvidia", "openai", "오픈ai", "오픈에이아이",
    "앤트로픽", "anthropic", "구글", "마이크로소프트", "ms", "아마존", "메타", "애플",
    "오라클", "데이터센터", "capex", "설비투자", "gpu", "수출통제", "관세",
)
_STAR = re.compile(r"★")


def _relevant(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in _KEYWORDS)


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers=_UA)
    items: list[RawNewsItem] = []
    obs: list[MetricObservation] = []
    detail_fail = 0
    try:
        resp = await client.get(f"{_BASE}/news/list", params={"page_size": 50})
        resp.raise_for_status()
        rows = resp.json().get("news_list", []) or []
        last_id = int(store.get_state("saveticker_last_id") or 0)
        max_id = last_id
        for row in rows:
            try:
                rid = int(row.get("id", 0))
            except (TypeError, ValueError):
                continue
            max_id = max(max_id, rid)
            if rid <= last_id:
                continue
            title = row.get("title") or ""
            preview = row.get("content") or ""
            if not _relevant(f"{title} {preview}"):
                continue
            content = preview
            source = row.get("source") or ""
            try:
                d = await client.get(f"{_BASE}/news/detail/{rid}")
                d.raise_for_status()
                news = d.json().get("news", {}) or {}
                blocks = news.get("content")
                if isinstance(blocks, list):
                    content = "\n".join(
                        (b.get("content") or "").strip() for b in blocks
                        if isinstance(b, dict) and (b.get("content") or "").strip())
                source = news.get("source") or source
            except Exception:  # noqa: BLE001 — detail 실패는 미리보기로 진행
                detail_fail += 1
            items.append(RawNewsItem(
                id=f"st-{rid}", title=title, preview=preview, content=content,
                source=source, url=f"https://www.saveticker.com/news?id={rid}",
                published_at=row.get("created_at") or "",
                grade_hint="D" if "(카더라)" in title else None,
                extra={"provider": "saveticker"}))
        if max_id > last_id:
            store.set_state("saveticker_last_id", max_id)

        # 매크로 캘린더 (향후 14일) — ★ 개수 = 중요도
        import datetime as _dt
        today = _dt.date.today()
        cal = await client.get(f"{_BASE}/calendar/events", params={
            "start_date": today.isoformat(),
            "end_date": (today + _dt.timedelta(days=14)).isoformat()})
        if cal.status_code == 200:
            for ev in cal.json().get("events", []) or []:
                stars = len(_STAR.findall(ev.get("title") or ""))
                if stars >= 2:
                    obs.append(MetricObservation(
                        metric="macro_calendar", ts=(ev.get("event_date") or "")[:10],
                        value=float(stars), unit="stars",
                        meta={"title": ev.get("title") or "", "provider": "saveticker"}))
        status = "ok" if detail_fail == 0 else "degraded"
        detail = "" if detail_fail == 0 else f"detail_fail={detail_fail}"
        return CollectorResult(name=NAME, kind=KIND, items=items,
                               observations=obs, status=status, detail=detail)
    finally:
        if own:
            await client.aclose()
```

- [ ] **Step 4: 통과 확인** + 전체 스위트 그린
- [ ] **Step 5: 커밋** — `git commit -m "feat(sector): SaveTicker 수집기 — 증분 감지→키워드 필터→detail 전문, 캘린더"`

---

### Task 4: brave_matrix + rss + dart_edgar

**Files:**
- Modify: `engine/sector/collectors/brave_matrix.py`, `rss.py`, `dart_edgar.py`
- Test: `engine/tests/test_sector_collectors_news.py`에 추가

**Interfaces:**
- Consumes: `tools.news.brave.news_search(query, count, freshness, country, search_lang, client)`, `stages.ra_external._norm_url`, `_BLOCKED_DOMAINS` (import만 — 수정 금지)
- Produces: RawNewsItem (brave: grade_hint None / dart_edgar: grade_hint "S")

**brave_matrix 스펙**: 쿼리 매트릭스(계획 §2 쿼리 매트릭스 A/A'/B/C/E/P 그대로, 총 ~20쿼리). 한글 포함 쿼리→country=kr/search_lang=ko, 아니면 us/en. freshness="pd", count=5. `_BLOCKED_DOMAINS` 도메인 제거 + `_norm_url` dedup. id는 `bv-` + norm_url의 sha1 12자.

**rss 스펙**: 표준 `xml.etree.ElementTree`로 RSS 2.0/Atom 파싱. 피드 목록은 모듈 상수 `_FEEDS` — `("전자신문 반도체", "https://rss.etnews.com/Section901.xml")`, `("TrendForce press", "https://www.trendforce.com/rss/press.xml")` 2개로 시작. 피드별 개별 try/except — 하나 죽으면 detail에 기록하고 status=degraded. item→RawNewsItem(제목·링크·pubDate·description), `_relevant` 키워드 필터는 saveticker의 `_KEYWORDS`를 import해 재사용. id는 `rss-` + url sha1 12자.

**dart_edgar 스펙**:
- DART (키 필요 — 없으면 부분 skip): `GET https://opendart.fss.or.kr/api/list.json?crtfc_key={key}&corp_code={code}&bgn_de={YYYYMMDD 7일 전}&end_de={오늘}&page_count=20` — corp_code 삼성전자 `00126380`, SK하이닉스 `00164779`. 응답 `{"status":"000","list":[{report_nm, rcept_no, rcept_dt, corp_name}]}`. status!="000"이면 degraded. 카드 제목=report_nm, url=`https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}`, grade_hint="S".
- EDGAR (키 불필요, UA 필수): `GET https://data.sec.gov/submissions/CIK{cik:0>10}.json`, 헤더 `{"User-Agent": "attn-viewer research dev@vault.haus"}`. CIK: MU `723125`, NVDA `1045810`, MSFT `789019`, META `1326801`. `filings.recent`에서 form이 8-K/10-Q/10-K인 최근 7일(filingDate) 항목 → RawNewsItem(title=f"{ticker} {form}", grade_hint="S", url=`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}`).
- 키 없으면 DART만 건너뛰고 EDGAR는 수행, status="ok", detail="dart: missing_key".

- [ ] **Step 1: 실패 테스트** (추가)

```python
def test_brave_matrix_geo_and_dedup(tmp_path, monkeypatch):
    from sector.collectors import brave_matrix
    calls = []
    async def fake_news_search(query, *, count=5, freshness="pd",
                               country="kr", search_lang="ko", client=None):
        calls.append((query, country, search_lang))
        return [{"title": f"t-{query}", "url": "https://ex.com/a?utm_source=x",
                 "description": "d", "age": "", "source": "ex.com"},
                {"title": "dup", "url": "https://ex.com/a", "description": "", "age": "", "source": "ex.com"}]
    monkeypatch.setattr(brave_matrix, "news_search", fake_news_search)
    r = asyncio.run(brave_matrix.collect(SectorStore(tmp_path)))
    korean = [c for c in calls if c[1] == "kr"]
    english = [c for c in calls if c[1] == "us"]
    assert korean and english                      # 언어별 지오 라우팅
    assert len(r.items) == 1                       # norm_url dedup (utm 제거 후 동일)


def test_rss_parses_and_isolates_feed_failure(tmp_path, monkeypatch):
    from sector.collectors import rss as rssmod
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item><title>SK hynix HBM4 supply</title><link>https://n.com/1</link>
      <pubDate>Mon, 06 Jul 2026 09:00:00 +0900</pubDate><description>d</description></item>
      <item><title>irrelevant kitten news</title><link>https://n.com/2</link></item>
    </channel></rss>"""
    def handler(request):
        if "etnews" in str(request.url):
            return httpx.Response(200, content=xml)
        return httpx.Response(500)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(rssmod.collect(SectorStore(tmp_path), client=client))
    assert [i.title for i in r.items] == ["SK hynix HBM4 supply"]   # 키워드 필터
    assert r.status == "degraded" and "trendforce" in r.detail.lower()


def test_dart_edgar_without_key_runs_edgar_only(tmp_path, monkeypatch):
    from sector.collectors import dart_edgar
    from app.settings import settings
    monkeypatch.setattr(settings, "dart_api_key", "")
    import datetime as _dt
    today = _dt.date.today().isoformat()
    sub = {"filings": {"recent": {"form": ["8-K", "4"], "filingDate": [today, today],
                                  "accessionNumber": ["a1", "a2"],
                                  "primaryDocDescription": ["earnings", ""]}}}
    def handler(request):
        if "data.sec.gov" in str(request.url):
            return httpx.Response(200, json=sub)
        raise AssertionError("DART must not be called without key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(dart_edgar.collect(SectorStore(tmp_path), client=client))
    assert r.status == "ok" and "missing_key" in r.detail
    assert all(i.grade_hint == "S" for i in r.items)
    assert any("8-K" in i.title for i in r.items)
    assert not any("| 4" in i.title for i in r.items)   # form 4(내부자거래)는 제외
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — brave_matrix.py:

```python
# engine/sector/collectors/brave_matrix.py
"""축별 쿼리 매트릭스 — 기존 brave 도구 + geo 라우팅 + 커뮤니티/URL 필터 재사용."""
from __future__ import annotations

import hashlib
import re

import httpx

from sector.contracts import CollectorResult, RawNewsItem
from sector.store import SectorStore
from stages.ra_external import _BLOCKED_DOMAINS, _norm_url
from tools.news.brave import news_search

NAME = "brave_matrix"
KIND = "news"
_HANGUL = re.compile(r"[가-힣]")

_QUERIES: list[tuple[str, str]] = [  # (axis, query) — 계획 §2 쿼리 매트릭스
    ("A", "SK Hynix HBM supply contract"), ("A", "Samsung DRAM price"),
    ("A", "Micron guidance"), ("A", "삼성전자 감산"), ("A", "메모리 고정거래가격"),
    ("A_prime", "TSMC CoWoS capacity"), ("A_prime", "SemiAnalysis memory HBM"),
    ("B", "Microsoft capex guidance"), ("B", "Google datacenter spending"),
    ("B", "Meta AI infrastructure capex"), ("B", "hyperscaler memory procurement"),
    ("C", "OpenAI revenue"), ("C", "Anthropic usage"), ("C", "AI inference demand"),
    ("E", "smartphone shipment forecast"), ("E", "중국 스마트폰 보조금"),
    ("P", "HBM export control"), ("P", "CXMT DRAM capacity"),
]


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    items: list[RawNewsItem] = []
    seen: set[str] = set()
    fails = 0
    for axis, q in _QUERIES:
        kr = bool(_HANGUL.search(q))
        try:
            rows = await news_search(q, count=5, freshness="pd",
                                     country="kr" if kr else "us",
                                     search_lang="ko" if kr else "en", client=client)
        except Exception:  # noqa: BLE001
            fails += 1
            continue
        for r in rows:
            url = r.get("url") or ""
            host = (r.get("source") or "").lower()
            if any(host.endswith(d) for d in _BLOCKED_DOMAINS):
                continue
            nu = _norm_url(url)
            if nu in seen:
                continue
            seen.add(nu)
            items.append(RawNewsItem(
                id="bv-" + hashlib.sha1(nu.encode()).hexdigest()[:12],
                title=r.get("title") or "", preview=r.get("description") or "",
                content=r.get("description") or "", source=host, url=url,
                published_at=r.get("age") or "", extra={"axis_hint": axis, "query": q}))
    status = "ok" if fails == 0 else "degraded"
    return CollectorResult(name=NAME, kind=KIND, items=items, status=status,
                           detail="" if not fails else f"query_fail={fails}")
```

rss.py:

```python
# engine/sector/collectors/rss.py
"""전문지 RSS — 표준 xml 파서 (신규 의존성 금지, 원칙 7). 피드별 실패 격리."""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

import httpx

from sector.contracts import CollectorResult, RawNewsItem
from sector.store import SectorStore
from sector.collectors.saveticker import _relevant

NAME = "rss"
KIND = "news"
_FEEDS = [
    ("etnews", "https://rss.etnews.com/Section901.xml"),
    ("trendforce", "https://www.trendforce.com/rss/press.xml"),
]


def _text(el, *tags) -> str:
    for t in tags:
        found = el.find(t)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True,
                                         headers={"User-Agent": "attn-viewer-sector/0.1"})
    items: list[RawNewsItem] = []
    failed: list[str] = []
    try:
        for name, url in _FEEDS:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                nodes = root.iter("item")
                for it in nodes:
                    title = _text(it, "title")
                    link = _text(it, "link")
                    if not title or not link or not _relevant(title):
                        continue
                    items.append(RawNewsItem(
                        id="rss-" + hashlib.sha1(link.encode()).hexdigest()[:12],
                        title=title, preview=_text(it, "description")[:300],
                        content=_text(it, "description"), source=name, url=link,
                        published_at=_text(it, "pubDate"), extra={"feed": name}))
            except Exception:  # noqa: BLE001 — 피드 격리
                failed.append(name)
        status = "ok" if not failed else "degraded"
        return CollectorResult(name=NAME, kind=KIND, items=items, status=status,
                               detail="" if not failed else "feed_fail=" + ",".join(failed))
    finally:
        if own:
            await client.aclose()
```

dart_edgar.py:

```python
# engine/sector/collectors/dart_edgar.py
"""공시 — DART(키 필요) + SEC EDGAR(키 불필요, UA 필수). 공시=S급, 100% 관련."""
from __future__ import annotations

import datetime as _dt

import httpx

from app.settings import settings
from sector.contracts import CollectorResult, RawNewsItem
from sector.store import SectorStore

NAME = "dart_edgar"
KIND = "news"
_DART_CORPS = [("삼성전자", "00126380"), ("SK하이닉스", "00164779")]
_EDGAR_CIKS = [("MU", 723125), ("NVDA", 1045810), ("MSFT", 789019), ("META", 1326801)]
_EDGAR_FORMS = {"8-K", "10-Q", "10-K", "20-F"}
_EDGAR_UA = {"User-Agent": "attn-viewer research dev@vault.haus"}


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    items: list[RawNewsItem] = []
    notes: list[str] = []
    today = _dt.date.today()
    week_ago = today - _dt.timedelta(days=7)
    try:
        if settings.dart_api_key:
            for corp, code in _DART_CORPS:
                try:
                    resp = await client.get("https://opendart.fss.or.kr/api/list.json", params={
                        "crtfc_key": settings.dart_api_key, "corp_code": code,
                        "bgn_de": week_ago.strftime("%Y%m%d"), "end_de": today.strftime("%Y%m%d"),
                        "page_count": 20})
                    data = resp.json()
                    if data.get("status") != "000":
                        notes.append(f"dart:{corp}={data.get('status')}")
                        continue
                    for row in data.get("list", []) or []:
                        rno = row.get("rcept_no", "")
                        items.append(RawNewsItem(
                            id=f"dart-{rno}", title=f"[공시] {corp} {row.get('report_nm', '')}",
                            source="dart.fss.or.kr", grade_hint="S",
                            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rno}",
                            published_at=row.get("rcept_dt", ""), extra={"corp": corp}))
                except Exception:  # noqa: BLE001
                    notes.append(f"dart:{corp}=error")
        else:
            notes.append("dart: missing_key")
        for ticker, cik in _EDGAR_CIKS:
            try:
                resp = await client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                                        headers=_EDGAR_UA)
                resp.raise_for_status()
                recent = (resp.json().get("filings") or {}).get("recent") or {}
                forms = recent.get("form", [])
                dates = recent.get("filingDate", [])
                accs = recent.get("accessionNumber", [])
                descs = recent.get("primaryDocDescription", [""] * len(forms))
                for form, fdate, acc, desc in zip(forms, dates, accs, descs):
                    if form not in _EDGAR_FORMS or fdate < week_ago.isoformat():
                        continue
                    items.append(RawNewsItem(
                        id=f"edgar-{acc}", title=f"[filing] {ticker} {form} {desc}".strip(),
                        source="sec.gov", grade_hint="S", published_at=fdate,
                        url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}",
                        extra={"ticker": ticker, "form": form}))
            except Exception:  # noqa: BLE001
                notes.append(f"edgar:{ticker}=error")
        return CollectorResult(name=NAME, kind=KIND, items=items, status="ok",
                               detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
```

- [ ] **Step 4: 통과 + 전체 스위트 그린**
- [ ] **Step 5: 커밋** — `git commit -m "feat(sector): brave 매트릭스·RSS·DART/EDGAR 수집기"`

---

### Task 5: C0·토큰 지표 수집기 (openrouter, status_pages, sdk_downloads, app_charts)

**Files:**
- Modify: 해당 4개 스텁
- Test: `engine/tests/test_sector_collectors_metrics.py` (신규)

**Interfaces:** Consumes MetricObservation/Store. Produces 지표: `token_price`(meta.model), `openrouter_daily_tokens`(meta.model), `ai_status_incidents`(meta.provider), `sdk_downloads`(meta.pkg,ecosystem), `app_rank`(meta.app,country).

**스펙:**
- openrouter: `GET https://openrouter.ai/api/v1/models` (키 불필요) → data[]에서 id가 `_TRACK`(`openai/gpt-5.5`, `anthropic/claude-sonnet-4.6`, `anthropic/claude-opus-4.8`, `google/gemini` 접두 등 — id 접두 매칭)인 모델의 `pricing.prompt/completion`(문자열, USD/token) ×1e6 → `token_price` (value=completion, meta={model, prompt, completion}). 랭킹: `settings.openrouter_api_key` 있으면 `GET https://openrouter.ai/api/v1/datasets/rankings-daily` Authorization Bearer — **404/401이면 detail에 기록하고 degraded** (엔드포인트 경로는 키 발급 후 실측 확정 — 응답이 `{"data":[{model/model_permaslug, total_tokens/tokens, date}...]}` 형태면 `openrouter_daily_tokens` 저장, 아니면 detail="rankings schema unknown"). 키 없으면 models만 하고 status="ok", detail="rankings: missing_key".
- status_pages: `GET https://status.openai.com/api/v2/summary.json`, `GET https://status.anthropic.com/api/v2/summary.json` → `ai_status_incidents` value=len(incidents), meta={provider, ongoing: [name...]}. ts=오늘.
- sdk_downloads: PyPI `GET https://pypistats.org/api/packages/{pkg}/recent` (pkg: openai, anthropic) → data.last_week; npm `GET https://api.npmjs.org/downloads/point/last-week/{pkg}` (pkg: openai, @anthropic-ai/sdk) → downloads. metric=`sdk_downloads`, meta={pkg, ecosystem}.
- app_charts: `GET https://rss.applemarketingtools.com/api/v2/{country}/apps/top-free/100/apps.json` (country: us, kr) → results[]에서 name에 ChatGPT/Gemini/Claude/Copilot 포함 항목의 순위(1-base index) → `app_rank` value=rank, meta={app,country}. 미포함 앱은 관측 없음(정상).

- [ ] **Step 1: 실패 테스트** (`test_sector_collectors_metrics.py` 신규 — 헤더 컨벤션 동일. MockTransport 핸들러로 각 API 최소 응답, 키 없는 경로/있는 경로 각각. 코드는 Task 3~4 테스트와 같은 패턴으로 4수집기 × (정상 1 + 결측/열화 1). openrouter 예:)

```python
def test_openrouter_models_snapshot_without_key(tmp_path, monkeypatch):
    from sector.collectors import openrouter as orc
    from app.settings import settings
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    models = {"data": [
        {"id": "anthropic/claude-sonnet-4.6", "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
        {"id": "meta-llama/tiny", "pricing": {"prompt": "0", "completion": "0"}},
    ]}
    def handler(request):
        assert request.url.path == "/api/v1/models"
        return httpx.Response(200, json=models)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(orc.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok" and "missing_key" in r.detail
    rows = store.read_metric("token_price")
    assert rows and abs(rows[0].value - 15.0) < 1e-6 and rows[0].meta["model"].startswith("anthropic/")
```

(status_pages/sdk_downloads/app_charts도 동형 — 응답 최소 JSON, 값·meta 검증, 한 소스 500이면 degraded 검증)

- [ ] **Step 2: 실패 확인 → Step 3: 구현** — 4파일 각각 위 스펙대로. 공통 뼈대: own-client 패턴, 소스별 try/except, ts는 `datetime.date.today().isoformat()`. openrouter `_TRACK` 접두: `("openai/gpt-5", "anthropic/claude", "google/gemini", "x-ai/grok", "deepseek/", "moonshotai/")`.
- [ ] **Step 4: 통과 + 전체 그린 → Step 5: 커밋** `feat(sector): C0·토큰 지표 수집기 4종`

---

### Task 6: 정형 통계 수집기 (mops_tw, customs_kr, kosis, ecos, datalab, yahoo_metrics)

**Files:**
- Modify: 해당 6개 스텁
- Test: `engine/tests/test_sector_collectors_metrics.py`에 추가

**스펙:**
- mops_tw (키 불필요, 실측 확정): `GET https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv` — utf-8-sig CSV, 컬럼 `出表日期,資料年月,公司代號,公司名稱,...,營業收入-當月營收,...,營業收入-去年同月增減(%)`(인덱스로 접근하지 말고 헤더명으로). `_TRACK_CODES = {"2330":"TSMC","2382":"Quanta","3231":"Wistron","2356":"Inventec","6669":"Wiwynn","2317":"HonHai"}`만 필터 → metric=`tw_monthly_revenue`, ts=`資料年月`(민국력 "115/06" → "2026-06" 변환: 년+1911), value=당월매출(천TWD), meta={code, name, yoy}.
- customs_kr (data_go_kr_api_key 없으면 missing_key): `GET https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList` params={serviceKey, strtYymm, endYymm, hsSgn: "8542"(반도체 HS), type:"json"} — **응답 스키마가 불확실하므로**: 200 + json 파싱 성공 + items 존재 시 metric=`kr_semi_export`(value=수출금액), 그 외 어떤 형태든 status="degraded" + detail에 응답 최상위 키/코드 기록. (키 발급 후 아침 트리거에서 실측 확정하는 구조)
- kosis (kosis_api_key 게이트): `GET https://kosis.kr/openapi/Param/statisticsParameterData.do` params={method:"getList", apiKey, orgId:"101", tblId:"DT_1JH20151", format:"json", jsonVD:"Y", prdSe:"M", newEstPrdCnt:"12", objL1:"ALL"} — 동일한 방어 파싱: 리스트[{PRD_DE, DT, C1_NM...}] 형태면 C1_NM에 "반도체" 포함 행만 metric=`kr_semi_production_index`(ts=PRD_DE "202606"→"2026-06", value=float(DT), meta={item: C1_NM}), 아니면 degraded+detail.
- ecos (ecos_api_key 게이트): `GET https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100/402Y014/M/{시작 YYYYMM}/{끝 YYYYMM}` — `StatisticSearch.row[]`에서 ITEM_NAME1에 "D램" 또는 "반도체" 포함 행 → metric=`kr_dram_export_price_index`(ts=TIME "202606"→"2026-06", value=float(DATA_VALUE), meta={item: ITEM_NAME1}). row 없거나 RESULT 에러 구조면 degraded+detail (통계코드 402Y014는 후보 — 아침 실측 확정 대상).
- datalab (naver_client_id/secret 게이트): `POST https://openapi.naver.com/v1/datalab/search` json={startDate: 90일 전, endDate: 오늘, timeUnit: "week", keywordGroups: [{groupName:"chatgpt", keywords:["챗지피티","ChatGPT"]},{groupName:"claude",keywords:["클로드 AI","Claude"]},{groupName:"gemini",keywords:["제미나이","Gemini"]}]} 헤더 X-Naver-Client-Id/Secret → results[].data[] → metric=`search_interest_kr`, ts=period, value=ratio, meta={app: groupName}.
- yahoo_metrics (키 불필요): `tools.price.yahoo.quote(_TICKERS)` — `_TICKERS = ["005930.KS","000660.KS","MU","TSM","NVDA","^SOX","MSFT","GOOGL","AMZN","META","AAPL","ORCL"]` → error 없는 항목만 metric=`stock_price`, ts=오늘, value=cur, meta={token, day_pct}. quote가 내부 에러 항목을 주므로 오류 티커는 detail에 집계.

- [ ] **Step 1: 실패 테스트** — mops(실측 헤더의 축약 CSV 픽스처: 컬럼명 실제와 동일 2행), yahoo(monkeypatch로 quote 대체), kosis/ecos/customs/datalab(키 없음→missing_key 1개 + 키 있음 mock 응답 정상 파싱 1개씩). 예:

```python
_MOPS_CSV = ("﻿出表日期,資料年月,公司代號,公司名稱,產業別,營業收入-當月營收,營業收入-上月營收,"
             "營業收入-去年當月營收,營業收入-上月比較增減(%),營業收入-去年同月增減(%),"
             "累計營業收入-當月累計營收,累計營業收入-去年累計營收,累計營業收入-前期比較增減(%),備註\n"
             "1150707,11506,2330,台積電,半導體業,263710000,250000000,207870000,5.4,26.8,"
             "1500000000,1200000000,25.0,-\n"
             "1150707,11506,9999,無關公司,其他,100,90,80,1,1,10,8,2,-\n")

def test_mops_filters_and_converts_roc_date(tmp_path):
    from sector.collectors import mops_tw
    def handler(request):
        return httpx.Response(200, content=_MOPS_CSV.encode("utf-8"))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(mops_tw.collect(SectorStore(tmp_path), client=client))
    assert len(r.observations) == 1
    o = r.observations[0]
    assert o.ts == "2026-06" and o.meta["name"] == "TSMC" and o.meta["yoy"] == 26.8
```

- [ ] **Step 2~4: 실패 확인 → 구현 → 통과+전체 그린**
- [ ] **Step 5: 커밋** — `feat(sector): 정형 통계 수집기 6종 (MOPS·관세청·KOSIS·ECOS·데이터랩·yahoo)`

---

### Task 7: judge — sonnet 배치 판정

**Files:**
- Modify: `engine/providers.py` (ROLE_MAP에 1줄)
- Create: `engine/sector/judge.py`
- Test: `engine/tests/test_sector_judge.py`

**Interfaces:**
- Consumes: `providers.Role` (news_summary와 동일 사용법: `await Role("sector_judge").run(prompt, response_format=Model)` → `.value`가 아닌 반환값 자체가 파싱 객체)
- Produces: `async def judge_items(items: list[RawNewsItem]) -> list[SectorCard]`

**스펙:**
- ROLE_MAP 추가: `"sector_judge": [("anthropic", settings.model_claude_sonnet, "low"), ("openai", settings.model_gpt_mini, "low")],`
- 배치 최대 40건/콜, 초과분은 2번째 콜 (최대 2콜 — 원칙 14 비용 상한)
- 구조화 출력 모델(주의 — MAF structured output은 중첩 Literal에 관대하지 않을 수 있으므로 news_summary 패턴처럼 **plain BaseModel + str 필드 + 후검증**):

```python
class _JudgeRow(BaseModel):
    idx: int
    relevant: bool
    axis: str = "B"
    edge: str = "B->A"
    event_type: str = "demand_signal"
    memory_segment: str = "mixed"
    direction: str = "neutral"
    magnitude: int = 1
    time_horizon: str = "immediate"
    speaker: str = ""
    interpreted_signal: str = ""

class _JudgeBatch(BaseModel):
    rows: list[_JudgeRow]
```

- 프롬프트: 인과 엣지 요약(§1-3) + 판정 기준(축/방향은 A 메모리 주가 관점, 엣지 매핑 불가→relevant=false) + 아이템 목록(idx, 제목, 본문 400자, 출처)
- 후검증: axis∉허용집합→"B", direction∉→"neutral", magnitude를 1~3로 clamp, event_type∉→"demand_signal" 등. relevant=false는 드롭
- 카드 변환: id=item.id, ts=item.published_at 또는 지금, source_grade=item.grade_hint 우선, 없으면 공시 S / 등급 규칙(로이터·블룸버그·연합 등 `_GRADE_B` 셋 → "B", 그 외 "C"), raw_quote=content 앞 500자, title/url/source 복사, numeric=None
- LLM 예외는 **그대로 raise** (runner가 격리 — news_summary와 동일 계약)

- [ ] **Step 1: 실패 테스트**

```python
"""sector judge — 배치 판정·후검증·카드 변환 (P1 Task 7)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector import judge  # noqa: E402
from sector.contracts import RawNewsItem  # noqa: E402


def _items(n=2):
    return [RawNewsItem(id=f"i{k}", title=f"hynix HBM {k}", content="본문",
                        source="reuters.com", url=f"http://n/{k}",
                        published_at="2026-07-06T09:00:00Z") for k in range(n)]


def test_judge_drops_irrelevant_and_validates(monkeypatch):
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, prompt, instructions="", *, response_format=None, **kw):
            return judge._JudgeBatch(rows=[
                judge._JudgeRow(idx=0, relevant=True, axis="WRONG", direction="bogus",
                                magnitude=9, interpreted_signal="sig"),
                judge._JudgeRow(idx=1, relevant=False),
            ])
    monkeypatch.setattr(judge, "Role", FakeRole)
    cards = asyncio.run(judge.judge_items(_items()))
    assert len(cards) == 1
    c = cards[0]
    assert c.axis == "B" and c.direction == "neutral" and c.magnitude == 3  # clamp 9→3
    assert c.source_grade == "B"          # reuters → B
    assert c.interpreted_signal == "sig" and c.raw_quote == "본문"


def test_judge_respects_grade_hint(monkeypatch):
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, *a, **k):
            return judge._JudgeBatch(rows=[judge._JudgeRow(idx=0, relevant=True)])
    monkeypatch.setattr(judge, "Role", FakeRole)
    it = _items(1)[0]
    it.grade_hint = "D"
    cards = asyncio.run(judge.judge_items([it]))
    assert cards[0].source_grade == "D"


def test_judge_batches_over_40(monkeypatch):
    calls = []
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, prompt, **kw):
            calls.append(prompt)
            return judge._JudgeBatch(rows=[])
    monkeypatch.setattr(judge, "Role", FakeRole)
    asyncio.run(judge.judge_items(_items(41)))
    assert len(calls) == 2
```

- [ ] **Step 2: 실패 확인 → Step 3: 구현** (스펙 그대로. `_GRADE_B = {"reuters.com","bloomberg.com","연합","로이터","yna.co.kr","wsj.com","ft.com"}` — source 부분 문자열 매칭)
- [ ] **Step 4: 통과 + 전체 그린 → Step 5: 커밋** `feat(sector): sonnet 배치 판정 judge — 후검증·등급·카드 변환`

---

### Task 8: retrieve + cycle

**Files:**
- Create: `engine/sector/retrieve.py`, `engine/sector/cycle.py`
- Test: `engine/tests/test_sector_cycle_retrieve.py`

**Interfaces:**
- `retrieve.search(store, *, entities: list[str] | None = None, days=14, k=12) -> list[SectorCard]` — magnitude desc→최신순 정렬, direction 균형(pos·neg 각각 최소 min(2, 존재수) 보장), entities 필터
- `cycle.compute(store) -> dict` — `{"state": "up"|"down"|"transition"|"insufficient", "score": float, "factors": {"price": f|None, "inventory": ..., "demand": ..., "supply": ...}, "explain": [str,...]}`

**cycle 규칙 (규칙 기반 — 원칙 14):**
- 각 요소는 해당 지표 시계열의 **최근값 vs 이전값 방향**을 -1.0~+1.0로: price=`kr_dram_export_price_index`(없으면 None), inventory=`kr_semi_production_index` 중 meta.item에 "재고" 포함 시계열 방향 **반전**(재고↑=악재), demand=`kr_semi_export`와 `tw_monthly_revenue`(TSMC) YoY 평균, supply=`tw_monthly_revenue` 장비 프록시 없으므로 P1은 None 허용
- 방향 계산 공통 헬퍼: 마지막 2개 관측 (b-a): a==0→0, 아니면 clamp((b-a)/abs(a)*10, -1, 1)
- score = 가용 요소 가중평균 (price .35, inventory .25, demand .30, supply .10 — 가용 요소만으로 가중치 재정규화). 가용 요소 <2 → state="insufficient"
- state: score>+0.15→"up", <-0.15→"down", 사이→"transition". explain에 요소별 근거 문자열

- [ ] **Step 1: 실패 테스트** (합성 관측 주입 → 요소·상태 검증; direction 균형 테스트 — pos 9 neg 1 카드에서 k=5 뽑아도 neg 최소 1 포함; insufficient 케이스)
- [ ] **Step 2~4: 실패 → 구현 → 통과+전체 그린**
- [ ] **Step 5: 커밋** — `feat(sector): 구조화 검색 + 규칙 기반 사이클 스코어`

---

### Task 9: API 라우터 + 스케줄러 + 배선 + .env 플레이스홀더

**Files:**
- Create: `engine/sector/api.py`, `engine/sector/scheduler.py`
- Modify: `engine/app/main.py` (include_router + startup에서 scheduler 시작), 루트 `.env` (주석 플레이스홀더 **append만** — 기존 줄 절대 수정 금지)
- Test: `engine/tests/test_sector_api.py`

**Interfaces:**
- `GET /v1/sector/status` → `{"collectors": store.read_status(), "scheduler": {"enabled": bool, "interval_s": int}}`
- `POST /v1/sector/collect` body `{"only": ["saveticker"] | null}` → runner.collect_all 실행, `{"results": [{name,status,items,observations,detail}...]}`
- `GET /v1/sector/cards?days=14&axis=&entity=&limit=100` → `{"cards":[...]}`
- `GET /v1/sector/metrics/{name}?n=90` → `{"metric": name, "rows":[...]}`
- `GET /v1/sector/board` → `{"cycle": cycle.compute(...), "cards": retrieve.search(...k=20), "status": ...}`
- store 인스턴스: `api._get_store()` — `settings.sector_storage_dir or REPO_ROOT/"storage/rag/memory_sector"`, 모듈 레벨 캐시
- scheduler: `async def start(app)` — enabled 아니면 no-op 로그만; enabled면 `asyncio.create_task(_loop())`, `_loop`은 `while True: collect_all → sleep(interval)`, 예외 삼킴+로그

- [ ] **Step 1: 실패 테스트** (httpx.ASGITransport로 앱 직접 — 기존 라이브 테스트와 달리 프로세스 불필요)

```python
"""sector API — 라우터 배선·collect 트리거 (P1 Task 9)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402


def _client(tmp_path, monkeypatch):
    from app.settings import settings
    monkeypatch.setattr(settings, "sector_storage_dir", str(tmp_path))
    from app.main import app
    import sector.api as api
    api._STORE = None   # 캐시 리셋
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://t")


def test_status_and_empty_board(tmp_path, monkeypatch):
    async def go():
        async with _client(tmp_path, monkeypatch) as c:
            s = await c.get("/v1/sector/status")
            assert s.status_code == 200 and s.json()["scheduler"]["enabled"] is False
            b = await c.get("/v1/sector/board")
            assert b.status_code == 200 and b.json()["cycle"]["state"] == "insufficient"
    asyncio.run(go())


def test_collect_trigger_with_stub_registry(tmp_path, monkeypatch):
    import sector.runner as runner
    import types
    m = types.ModuleType("fake"); m.NAME, m.KIND = "fake", "metric"
    async def collect(store, client=None):
        from sector.contracts import CollectorResult, MetricObservation
        return CollectorResult(name="fake", kind="metric", observations=[
            MetricObservation(metric="stock_price", ts="2026-07-06", value=1.0,
                              meta={"token": "MU"})])
    m.collect = collect
    monkeypatch.setattr(runner, "_registry", lambda: [m])
    async def go():
        async with _client(tmp_path, monkeypatch) as c:
            r = await c.post("/v1/sector/collect", json={"only": None})
            assert r.status_code == 200
            assert r.json()["results"][0]["status"] == "ok"
            mrows = await c.get("/v1/sector/metrics/stock_price")
            assert mrows.json()["rows"][0]["value"] == 1.0
    asyncio.run(go())
```

- [ ] **Step 2: 실패 확인 → Step 3: 구현** — api.py는 위 계약 그대로 APIRouter(prefix="/v1/sector"). main.py에 `from sector.api import router as sector_router; app.include_router(sector_router)` + 기존 startup 훅(없으면 `@app.on_event("startup")`)에서 `from sector.scheduler import start; await start(app)`.
- [ ] **Step 4: .env 플레이스홀더 append** (루트 /home/ryze_yn/attn-viewer/.env 끝에 — 기존 내용 확인 후 append만):

```bash
# ---- 메모리 섹터 P1 (2026-07-07 claude) — yvon: 아래 키 발급해서 채우면 코드 수정 없이 활성화 ----
# OPENROUTER_API_KEY=        # https://openrouter.ai/keys (무료) — 일별 토큰 랭킹
# DATA_GO_KR_API_KEY=        # https://data.go.kr (무료) — 관세청 반도체 수출 10일
# KOSIS_API_KEY=             # https://kosis.kr/openapi (무료) — 생산·출하·재고지수
# ECOS_API_KEY=              # https://ecos.bok.or.kr/api (무료) — D램 수출물가지수
# DART_API_KEY=              # https://opendart.fss.or.kr (무료) — 한국 공시
# NAVER_CLIENT_ID=           # https://developers.naver.com (무료) — 데이터랩 검색 관심도
# NAVER_CLIENT_SECRET=
# SECTOR_SCHEDULER_ENABLED=true   # 주기 수집 켜기 (기본 꺼짐; 수동은 POST /v1/sector/collect)
```

- [ ] **Step 5: 통과 + 전체 그린 → Step 6: 커밋** — `feat(sector): /v1/sector API·스케줄러(기본 OFF)·.env 플레이스홀더` (`.env`는 gitignore 확인 — 커밋 대상 아님, 코드만)

---

## Self-Review 결과

- 스펙 커버: §2-7 SaveTicker(T3), 쿼리매트릭스+geo(T4), 공시(T4), C0 4종(T5), 정형통계 6종(T6), 판정·등급·분리저장(T7), 구조화 검색·direction 균형(T8), 사이클 4요소·insufficient(T8), API·스케줄러 OFF·키 플레이스홀더(T9). **비범위**: P2 UI, P3 QA 연결, 임베딩 — 원칙 문서 범위와 일치
- 외부 API 불확실 항목(openrouter rankings 경로, customs/kosis/ecos 스키마)은 전부 "방어 파싱 + degraded + detail" 계약으로 명시 — 플레이스홀더 아님, 탐사 설계
- 타입 일관성: RawNewsItem/CollectorResult/SectorCard 필드명 태스크 간 대조 완료 (grade_hint, observations, interpreted_signal)
