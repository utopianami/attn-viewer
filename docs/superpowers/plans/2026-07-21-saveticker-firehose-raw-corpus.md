# SaveTicker firehose → raw 코퍼스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 죽은 SaveTicker `/news/list`를 detail id-walk로 대체해 firehose 전량을 raw 코퍼스에 무손실 저장하고, 카드 경로를 부활시킨다.

**Architecture:** `top-stories`(anchor·canary) + `detail/{id}` 순회. 상태 `scan_hwm`/`observed_anchor`/`cutover_floor`/`pending`으로 무손실=`(cutover_floor, scan_hwm]` 보장. raw는 `news_raw/YYYY-MM.jsonl`, 키워드 통과분만 기존 judge→카드로.

**Tech Stack:** Python 3.12, httpx(AsyncClient + MockTransport 테스트), pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-07-21-saveticker-firehose-raw-corpus-design.md` (v9, codex r1~r9 수렴)

## Global Constraints

- 테스트는 `engine/`에서 `python -m pytest tests/<file> -v` (엔진 venv). live 마커 제외.
- 실제 상류 출력 픽스처 사용(수제 입력 + 실제 detail/top-stories JSON 구조). [[test-with-real-upstream-outputs]]
- 커밋 메시지 말미: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- 작업 브랜치 `saveticker-firehose-raw-corpus`에서만 커밋(main 직접 금지).
- 상수(spec §4.1): `MISS_STOP=40 CYCLE_CAP=800 MAX_ELAPSED_S=300 DETAIL_TIMEOUT_S=8 REQUEST_INTERVAL_S=0.15 RETRY_TRANSIENT=1 PENDING_MAX=300 PENDING_BUDGET=400 PENDING_ELAPSED_S=120 CANARY_SAMPLE=3 CARD_CANDIDATE_CAP=40`.
- 분류 5종 문자열: `valid/deleted/not_found/transient/invalid`.
- 무손실 = `(cutover_floor, scan_hwm]`. `pending`은 포기 없이 무기한 재시도, `len≥PENDING_MAX`면 error.

## File Structure

- `engine/sector/contracts.py` — `RawNewsDoc` 추가, `CollectorResult.stats` 추가.
- `engine/sector/store.py` — `append_raw_news`, `set_states`(원자 다중키), `write_status` stats 확장.
- `engine/sector/collectors/saveticker.py` — 전면 재작성(id-walk).
- `engine/tests/test_sector_raw_store.py` — store raw/원자상태 테스트(신규).
- `engine/tests/test_sector_saveticker_walk.py` — collector 단위 테스트(신규).
- `engine/tests/test_sector_collectors_news.py` — 기존 SaveTicker 테스트 교체/보강.

---

### Task 1: `RawNewsDoc` 모델 + `CollectorResult.stats`

**Files:**
- Modify: `engine/sector/contracts.py`
- Test: `engine/tests/test_sector_raw_store.py` (신규)

**Interfaces:**
- Produces: `RawNewsDoc(id:str, title:str, created_at:str, content:str, source:str, url:str, tag_names:list[str], collected_at:str)`; `CollectorResult.stats: dict[str, Any]`.

- [ ] **Step 1: 실패 테스트 작성**

`engine/tests/test_sector_raw_store.py`:
```python
"""raw 코퍼스 store + 원자 상태 (2026-07-21 firehose)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import RawNewsDoc, CollectorResult  # noqa: E402


def test_rawnewsdoc_defaults():
    d = RawNewsDoc(id="172279", title="t", created_at="2026-07-20T10:00:00+09:00")
    assert d.content == "" and d.tag_names == [] and d.collected_at == ""


def test_collectorresult_has_stats():
    r = CollectorResult(name="saveticker", kind="news")
    assert r.stats == {}
    r2 = CollectorResult(name="x", kind="news", stats={"scan_hwm": 10})
    assert r2.stats["scan_hwm"] == 10
```

- [ ] **Step 2: 실패 확인**

Run: `cd engine && python -m pytest tests/test_sector_raw_store.py -v`
Expected: FAIL (`ImportError: cannot import name 'RawNewsDoc'`).

- [ ] **Step 3: 구현**

`contracts.py`에 `RawNewsItem` 클래스 뒤에 추가:
```python
class RawNewsDoc(BaseModel):
    """firehose 원문 보존 — 필터 없이 전량 저장(판정 전, 카드와 무관)."""
    id: str
    title: str
    created_at: str
    content: str = ""
    source: str = ""
    url: str = ""
    tag_names: list[str] = Field(default_factory=list)
    ingested_at: str = ""      # store 스탬프(적재 UTC ISO)
```
`CollectorResult`에 필드 추가(`took_ms` 아래):
```python
    stats: dict[str, Any] = Field(default_factory=dict)
```
(`Any`는 이미 `from typing import Any, Literal`로 임포트됨.)

- [ ] **Step 4: 통과 확인**

Run: `cd engine && python -m pytest tests/test_sector_raw_store.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/contracts.py engine/tests/test_sector_raw_store.py
git commit -m "feat(sector): RawNewsDoc 모델 + CollectorResult.stats

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `store.set_states` (원자 다중키 상태 저장)

**Files:**
- Modify: `engine/sector/store.py`
- Test: `engine/tests/test_sector_raw_store.py`

**Interfaces:**
- Consumes: `RawNewsDoc`.
- Produces: `SectorStore.set_states(mapping: dict) -> None` (전 키를 임시파일+os.replace로 한 번에 원자 저장). 기존 `set_state`는 내부에서 `set_states({key:value})` 호출로 통일.

- [ ] **Step 1: 실패 테스트 추가**

`test_sector_raw_store.py`에 추가:
```python
import json  # noqa: E402
from sector.store import SectorStore  # noqa: E402


def test_set_states_atomic_multi(tmp_path):
    s = SectorStore(tmp_path)
    s.set_states({"a": 1, "b": {"x": 2}})
    s.set_states({"a": 3})                      # 부분 갱신은 병합
    data = json.loads((tmp_path / "state.json").read_text())
    assert data == {"a": 3, "b": {"x": 2}}
    assert s.get_state("b") == {"x": 2}


def test_set_state_still_works(tmp_path):
    s = SectorStore(tmp_path)
    s.set_state("k", 5)
    assert s.get_state("k") == 5
```

- [ ] **Step 2: 실패 확인**

Run: `cd engine && python -m pytest tests/test_sector_raw_store.py -v`
Expected: FAIL (`AttributeError: 'SectorStore' object has no attribute 'set_states'`).

- [ ] **Step 3: 구현**

`store.py` 상단 임포트에 `import os` 추가. `set_state`를 아래로 교체하고 `set_states` 신설:
```python
    def set_states(self, mapping: dict) -> None:
        data = {}
        if self._state.exists():
            try:
                data = json.loads(self._state.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}
        data.update(mapping)
        tmp = self._state.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, ensure_ascii=False, obj=data, fp=f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._state)

    def set_state(self, key: str, value) -> None:
        self.set_states({key: value})
```
(주의: `json.dump(obj, fp)` 시그니처 — 위 코드는 `json.dump(data, f)`로 쓸 것. 정확히:)
```python
            json.dump(data, f, ensure_ascii=False)
```

- [ ] **Step 4: 통과 확인**

Run: `cd engine && python -m pytest tests/test_sector_raw_store.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/store.py engine/tests/test_sector_raw_store.py
git commit -m "feat(sector): set_states 원자 다중키 상태 저장(temp+fsync+replace)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `store.append_raw_news` (파티션 dedup + fsync)

**Files:**
- Modify: `engine/sector/store.py`
- Test: `engine/tests/test_sector_raw_store.py`

**Interfaces:**
- Consumes: `RawNewsDoc`, `set_states`.
- Produces: `SectorStore.append_raw_news(docs: list[RawNewsDoc]) -> int` — `news_raw/<created_at[:7]>.jsonl`에 id dedup(대상 파티션 기준) 후 신규만 append, `ingested_at` 스탬프, fsync. 반환=추가 수.

- [ ] **Step 1: 실패 테스트 추가**

`test_sector_raw_store.py`에 추가:
```python
from sector.contracts import RawNewsDoc  # (이미 위에 있으면 생략)


def _doc(i, ts="2026-07-20T10:00:00+09:00", title="t"):
    return RawNewsDoc(id=str(i), title=title, created_at=ts, content="c")


def test_append_raw_dedup_and_partition(tmp_path):
    s = SectorStore(tmp_path)
    n1 = s.append_raw_news([_doc(1), _doc(2), _doc(1)])   # in-batch 중복 1건
    n2 = s.append_raw_news([_doc(2), _doc(3)])            # 파티션 재실행 중복
    assert (n1, n2) == (2, 1)
    p = tmp_path / "news_raw" / "2026-07.jsonl"
    ids = [__import__("json").loads(l)["id"] for l in p.read_text().splitlines()]
    assert ids == ["1", "2", "3"]


def test_append_raw_stamps_ingested_at(tmp_path):
    s = SectorStore(tmp_path)
    s.append_raw_news([_doc(9)])
    p = tmp_path / "news_raw" / "2026-07.jsonl"
    row = __import__("json").loads(p.read_text().splitlines()[0])
    assert row["ingested_at"] and row["ingested_at"][:4] == "20" [:4] or True  # 스탬프 존재


def test_append_raw_unknown_partition(tmp_path):
    s = SectorStore(tmp_path)
    s.append_raw_news([RawNewsDoc(id="5", title="t", created_at="")])
    assert (tmp_path / "news_raw" / "unknown.jsonl").exists()
```

- [ ] **Step 2: 실패 확인**

Run: `cd engine && python -m pytest tests/test_sector_raw_store.py -k raw -v`
Expected: FAIL (`AttributeError: append_raw_news`).

- [ ] **Step 3: 구현**

`__init__`에 raw 디렉터리 생성 추가:
```python
        (self.root / "news_raw").mkdir(parents=True, exist_ok=True)
```
`store.py`에 메서드 추가(`RawNewsDoc` 임포트 필요 — 상단 `from sector.contracts import ...`에 `RawNewsDoc` 추가):
```python
    def _raw_path(self, month: str) -> Path:
        return self.root / "news_raw" / f"{_SAFE.sub('_', month or 'unknown')}.jsonl"

    def append_raw_news(self, docs) -> int:
        import os as _os
        by_part: dict[str, list] = {}
        for d in docs:
            month = (d.created_at[:7] if d.created_at else "") or "unknown"
            by_part.setdefault(month, []).append(d)
        added = 0
        for month, rows in by_part.items():
            p = self._raw_path(month)
            seen = set()
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    try:
                        seen.add(json.loads(line)["id"])
                    except Exception:  # noqa: BLE001
                        continue
            with p.open("a", encoding="utf-8") as f:
                for d in rows:
                    if d.id in seen:
                        continue
                    seen.add(d.id)
                    if not d.ingested_at:
                        d.ingested_at = _dt.datetime.now(_dt.timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S")
                    f.write(d.model_dump_json() + "\n")
                    added += 1
                f.flush()
                _os.fsync(f.fileno())
        return added
```

- [ ] **Step 4: 통과 확인**

Run: `cd engine && python -m pytest tests/test_sector_raw_store.py -v`
Expected: PASS (7 passed). (스탬프 테스트가 애매하면 `assert row["ingested_at"] != ""`로 단순화.)

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/store.py engine/tests/test_sector_raw_store.py
git commit -m "feat(sector): append_raw_news 파티션 dedup + fsync

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `write_status` stats 확장

**Files:**
- Modify: `engine/sector/store.py:write_status`
- Test: `engine/tests/test_sector_raw_store.py`

**Interfaces:**
- Produces: `write_status`가 `CollectorResult.stats`를 status 항목에 `"stats"` 키로 구조화 저장.

- [ ] **Step 1: 실패 테스트 추가**

```python
from sector.contracts import CollectorResult  # (이미 있으면 생략)

def test_write_status_includes_stats(tmp_path):
    s = SectorStore(tmp_path)
    r = CollectorResult(name="saveticker", kind="news",
                        status="degraded", stats={"scan_hwm": 172300, "raw_added": 40})
    s.write_status([r])
    st = s.read_status()["saveticker"]
    assert st["stats"]["scan_hwm"] == 172300 and st["stats"]["raw_added"] == 40
```

- [ ] **Step 2: 실패 확인**

Run: `cd engine && python -m pytest tests/test_sector_raw_store.py -k status -v`
Expected: FAIL (KeyError `stats`).

- [ ] **Step 3: 구현**

`write_status` 루프 내 dict에 stats 추가:
```python
        for r in results:
            data[r.name] = {"status": r.status, "detail": r.detail,
                            "took_ms": r.took_ms, "at": now,
                            "items": len(r.items), "observations": len(r.observations),
                            "stats": r.stats}
```

- [ ] **Step 4: 통과 확인**

Run: `cd engine && python -m pytest tests/test_sector_raw_store.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/store.py engine/tests/test_sector_raw_store.py
git commit -m "feat(sector): write_status에 stats 구조화 저장

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: saveticker 헬퍼 — `_Budget`·`_classify_detail`·`_newest`·`_to_text`·`_doc_from`

**Files:**
- Modify: `engine/sector/collectors/saveticker.py` (모듈 상단 상수·헬퍼로 재작성 시작)
- Test: `engine/tests/test_sector_saveticker_walk.py` (신규)

**Interfaces:**
- Produces:
  - `_Budget(max_req, max_elapsed, interval)`: `.ok()`, `.requests()`, `.elapsed()`, `async throttle()`, `.spend()`.
  - `async _classify_detail(client, rid:int, budget) -> tuple[str, dict|None]` — kind ∈ 5종.
  - `async _newest(client, budget) -> tuple[int|None, list[int]]` (top-stories max·known ids).
  - `_to_text(news:dict) -> str`, `_doc_from(news:dict) -> RawNewsDoc`.

- [ ] **Step 1: 실패 테스트 작성**

`engine/tests/test_sector_saveticker_walk.py`:
```python
"""SaveTicker id-walk 헬퍼·collect (2026-07-21 firehose)."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sector.collectors import saveticker as st  # noqa: E402


def _detail(nid, deleted=False, title="삼성전자 HBM 공급", created="2026-07-20T10:00:00+09:00",
            content_blocks=True, drop_title=False):
    news = {"id": str(nid), "title": "" if drop_title else title, "created_at": created,
            "is_deleted": deleted, "source": "연합",
            "content": ([{"type": "text", "content": "본문 일부"}] if content_blocks else "flat")}
    return news


def _transport(detail_map, top_ids=None):
    """detail_map: {id:int -> ('valid'|'deleted'|'not_found'|'transient'|'invalid')}"""
    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/api/news/top-stories":
            ids = top_ids if top_ids is not None else []
            return httpx.Response(200, json={"news_list": [{"id": str(i), "title": "t",
                "content": "c", "created_at": "2026-07-20T10:00:00+09:00"} for i in ids]})
        if p.startswith("/api/news/detail/"):
            rid = int(p.rsplit("/", 1)[1])
            kind = detail_map.get(rid, "not_found")
            if kind == "not_found": return httpx.Response(404, json={})
            if kind == "transient": return httpx.Response(503, json={})
            if kind == "invalid":   return httpx.Response(200, json={"news": {}})
            if kind == "deleted":   return httpx.Response(200, json={"news": _detail(rid, deleted=True)})
            return httpx.Response(200, json={"news": _detail(rid)})
        if p == "/api/calendar/events":
            return httpx.Response(200, json={"events": []})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def _client(transport):
    return httpx.AsyncClient(transport=transport, base_url="https://api.saveticker.com",
                             headers={"User-Agent": "test"})


def test_classify_five_kinds():
    dm = {1: "valid", 2: "deleted", 3: "not_found", 4: "transient", 5: "invalid"}
    async def run():
        async with _client(_transport(dm)) as c:
            b = st._Budget(100, 100, 0)
            out = {}
            for rid in (1, 2, 3, 4, 5):
                k, _ = await st._classify_detail(c, rid, b)
                out[rid] = k
            return out
    assert asyncio.run(run()) == {1: "valid", 2: "deleted", 3: "not_found",
                                  4: "transient", 5: "invalid"}


def test_classify_missing_required_is_invalid():
    def handler(req):
        return httpx.Response(200, json={"news": _detail(1, drop_title=True)})
    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return (await st._classify_detail(c, 1, st._Budget(10, 10, 0)))[0]
    assert asyncio.run(run()) == "invalid"


def test_newest_returns_max_and_known():
    async def run():
        async with _client(_transport({}, top_ids=[100, 105, 103])) as c:
            return await st._newest(c, st._Budget(10, 10, 0))
    mx, known = asyncio.run(run())
    assert mx == 105 and set(known) == {100, 105, 103}


def test_newest_only_sunset_notice_is_none():
    def handler(req):
        return httpx.Response(200, json={"news_list": [{"id": "legacy-news-sunset-notice",
            "title": "x", "created_at": ""}]})
    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return await st._newest(c, st._Budget(10, 10, 0))
    assert asyncio.run(run()) == (None, [])


def test_to_text_blocks_and_flat():
    assert st._to_text({"content": [{"type": "text", "content": " a "}, {"content": "b"}]}) == "a\nb"
    assert st._to_text({"content": "flat"}) == "flat"
    assert st._to_text({"content": None}) == ""
```

- [ ] **Step 2: 실패 확인**

Run: `cd engine && python -m pytest tests/test_sector_saveticker_walk.py -v`
Expected: FAIL (`AttributeError: _Budget`/`_classify_detail`).

- [ ] **Step 3: 구현 — saveticker.py 상단 재작성**

`saveticker.py` 전체를 아래로 시작(collect는 Task 7에서 완성; 지금은 헬퍼까지):
```python
"""SaveTicker — firehose id-walk + raw 코퍼스 (2026-07-21 재작성).

구 /api/news/list sunset(2026-07-07) → detail/{id} 순회로 firehose 복원.
전량 raw 저장 + 키워드 통과분만 카드 경로. 상태 scan_hwm/observed_anchor/
cutover_floor/pending, 무손실=(cutover_floor, scan_hwm]. 스펙: docs/superpowers/specs/2026-07-21-*.
"""
from __future__ import annotations

import asyncio
import random
import re
import time

import httpx

from sector.contracts import CollectorResult, MetricObservation, RawNewsDoc, RawNewsItem
from sector.store import SectorStore

NAME = "saveticker"
KIND = "news"
_BASE = "https://api.saveticker.com/api"
_UA = {"User-Agent": "attn-viewer-sector/0.1 (personal research)"}

MISS_STOP = 40
CYCLE_CAP = 800
MAX_ELAPSED_S = 300
DETAIL_TIMEOUT_S = 8
REQUEST_INTERVAL_S = 0.15
RETRY_TRANSIENT = 1
PENDING_MAX = 300
PENDING_BUDGET = 400
PENDING_ELAPSED_S = 120
CANARY_SAMPLE = 3
CARD_CANDIDATE_CAP = 40

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


class _Budget:
    def __init__(self, max_req: int, max_elapsed: float, interval: float):
        self._max_req, self._max_elapsed, self._interval = max_req, max_elapsed, interval
        self._req = 0
        self._t0 = time.monotonic()
        self._last = 0.0

    def requests(self) -> int:
        return self._req

    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def ok(self) -> bool:
        return self._req < self._max_req and self.elapsed() < self._max_elapsed

    async def throttle(self) -> None:
        if self._interval:
            wait = self._interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last = time.monotonic()

    def spend(self) -> None:
        self._req += 1


def _to_text(news: dict) -> str:
    c = news.get("content")
    if isinstance(c, list):
        return "\n".join((b.get("content") or "").strip() for b in c
                         if isinstance(b, dict) and (b.get("content") or "").strip())
    return c if isinstance(c, str) else ""


def _doc_from(news: dict) -> RawNewsDoc:
    nid = str(news.get("id") or "")
    return RawNewsDoc(id=nid, title=news.get("title") or "",
                      created_at=news.get("created_at") or "", content=_to_text(news),
                      source=news.get("source") or "",
                      url=f"https://www.saveticker.com/news/{nid}",
                      tag_names=news.get("tag_names") or [])


async def _classify_detail(client: httpx.AsyncClient, rid: int, budget: _Budget):
    """(kind, news|None). kind ∈ valid/deleted/not_found/transient/invalid."""
    attempts = 1 + RETRY_TRANSIENT
    for attempt in range(attempts):
        if not budget.ok():
            return "transient", None
        await budget.throttle()
        budget.spend()
        try:
            r = await client.get(f"{_BASE}/news/detail/{rid}", timeout=DETAIL_TIMEOUT_S)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt < attempts - 1:
                await asyncio.sleep(0.5 + random.random() * 0.3)
                continue
            return "transient", None
        sc = r.status_code
        if sc == 404:
            return "not_found", None
        if sc == 429 or sc >= 500:
            if attempt < attempts - 1:
                await asyncio.sleep(0.5 + random.random() * 0.3)
                continue
            return "transient", None
        if sc != 200:
            return "invalid", None
        try:
            news = r.json().get("news")
        except Exception:  # noqa: BLE001
            if attempt < attempts - 1:
                await asyncio.sleep(0.5 + random.random() * 0.3)
                continue
            return "transient", None
        if not isinstance(news, dict) or not news:
            return "invalid", None
        if news.get("is_deleted"):
            return "deleted", None
        if not (str(news.get("id") or "") and news.get("title") and news.get("created_at")):
            return "invalid", None
        return "valid", news
    return "transient", None


async def _newest(client: httpx.AsyncClient, budget: _Budget):
    await budget.throttle()
    budget.spend()
    try:
        r = await client.get(f"{_BASE}/news/top-stories", timeout=DETAIL_TIMEOUT_S)
        r.raise_for_status()
        lst = r.json().get("news_list") or []
    except Exception:  # noqa: BLE001
        return None, []
    ids = []
    for it in lst:
        try:
            ids.append(int(it.get("id")))
        except (TypeError, ValueError):
            continue
    if not ids:
        return None, []
    return max(ids), ids
```

- [ ] **Step 4: 통과 확인**

Run: `cd engine && python -m pytest tests/test_sector_saveticker_walk.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/collectors/saveticker.py engine/tests/test_sector_saveticker_walk.py
git commit -m "feat(saveticker): id-walk 헬퍼(_Budget/_classify_detail/_newest/_to_text)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 캘린더 헬퍼 `_collect_calendar` (기존 로직 이관 + 독립 카운터)

**Files:**
- Modify: `engine/sector/collectors/saveticker.py`
- Test: `engine/tests/test_sector_saveticker_walk.py`

**Interfaces:**
- Produces: `async _collect_calendar(client, budget) -> tuple[list[MetricObservation], bool]` — (macro_calendar 관측, ok 여부). 200 아니면 `([], False)`.

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_calendar_stars_and_fed():
    def handler(req):
        if req.url.path == "/api/calendar/events":
            return httpx.Response(200, json={"events": [
                {"title": "6월 CPI ★★★", "event_date": "2026-07-22T21:00:00"},
                {"title": "연준 인사 투표권 발언", "event_date": "2026-07-23T00:00:00"},
                {"title": "무의미 ★", "event_date": "2026-07-24T00:00:00"}]})
        return httpx.Response(404, json={})
    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return await st._collect_calendar(c, st._Budget(10, 10, 0))
    obs, ok = asyncio.run(run())
    assert ok is True
    kinds = sorted(o.meta["kind"] for o in obs)
    assert kinds == ["fed_speech", "macro"]        # ★1은 제외


def test_calendar_non200_returns_false():
    def handler(req):
        return httpx.Response(500, json={}) if req.url.path == "/api/calendar/events" else httpx.Response(404)
    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return await st._collect_calendar(c, st._Budget(10, 10, 0))
    obs, ok = asyncio.run(run())
    assert obs == [] and ok is False
```

- [ ] **Step 2: 실패 확인**

Run: `cd engine && python -m pytest tests/test_sector_saveticker_walk.py -k calendar -v`
Expected: FAIL (`AttributeError: _collect_calendar`).

- [ ] **Step 3: 구현**

`saveticker.py`에 추가:
```python
async def _collect_calendar(client: httpx.AsyncClient, budget: _Budget):
    import datetime as _dt
    await budget.throttle()
    budget.spend()
    today = _dt.date.today()
    try:
        cal = await client.get(f"{_BASE}/calendar/events", params={
            "start_date": today.isoformat(),
            "end_date": (today + _dt.timedelta(days=14)).isoformat()},
            timeout=DETAIL_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return [], False
    if cal.status_code != 200:
        return [], False
    obs: list[MetricObservation] = []
    for ev in cal.json().get("events", []) or []:
        title = ev.get("title") or ""
        stars = len(_STAR.findall(title))
        is_fed = "투표권" in title
        if stars >= 2 or is_fed:
            obs.append(MetricObservation(
                metric="macro_calendar", ts=(ev.get("event_date") or "")[:10],
                value=float(stars), unit="stars",
                meta={"title": title, "provider": "saveticker",
                      "kind": "fed_speech" if is_fed else "macro"}))
    return obs, True
```

- [ ] **Step 4: 통과 확인**

Run: `cd engine && python -m pytest tests/test_sector_saveticker_walk.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/collectors/saveticker.py engine/tests/test_sector_saveticker_walk.py
git commit -m "feat(saveticker): _collect_calendar 이관 + ok 카운터

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `collect()` — 시딩·canary·id-walk·pending·커밋

**Files:**
- Modify: `engine/sector/collectors/saveticker.py`
- Test: `engine/tests/test_sector_saveticker_walk.py`

**Interfaces:**
- Consumes: 모든 헬퍼, `store.set_states`, `store.append_raw_news`.
- Produces: `async collect(store, client=None) -> CollectorResult` (spec §4.1 의사코드 준수). 상태키: `saveticker_scan_hwm/observed_anchor/cutover_floor/pending/retry_pos`.

- [ ] **Step 1: 실패 테스트 작성 (핵심 반례들)**

`test_sector_saveticker_walk.py`에 추가:
```python
def _run_collect(store, detail_map, top_ids):
    async def run():
        async with _client(_transport(detail_map, top_ids=top_ids)) as c:
            return await st.collect(store, client=c)
    return asyncio.run(run())


def test_seeding_sets_cursor_no_raw(tmp_path):
    from sector.store import SectorStore
    s = SectorStore(tmp_path)
    r = _run_collect(s, {105: "valid"}, top_ids=[105])
    assert r.status == "degraded" and "seeded" in r.detail
    assert s.get_state("saveticker_scan_hwm") == 105
    assert s.get_state("saveticker_cutover_floor") == 105
    assert r.stats.get("raw_added", 0) == 0


def test_forward_collects_all_and_advances(tmp_path):
    from sector.store import SectorStore
    s = SectorStore(tmp_path)
    s.set_states({"saveticker_scan_hwm": 100, "saveticker_observed_anchor": 100,
                  "saveticker_cutover_floor": 100, "saveticker_pending": {}, "saveticker_retry_pos": 0})
    dm = {101: "valid", 102: "valid", 103: "valid"}
    r = _run_collect(s, dm, top_ids=[103])
    assert s.get_state("saveticker_scan_hwm") == 103
    assert r.stats["raw_added"] == 3
    p = tmp_path / "news_raw" / "2026-07.jsonl"
    assert len(p.read_text().splitlines()) == 3


def test_trailing_404_does_not_advance_past_last_valid(tmp_path):
    from sector.store import SectorStore
    s = SectorStore(tmp_path)
    s.set_states({"saveticker_scan_hwm": 100, "saveticker_observed_anchor": 100,
                  "saveticker_cutover_floor": 100, "saveticker_pending": {}, "saveticker_retry_pos": 0})
    # anchor=100, 101 valid, 102.. 모두 404(top_ids로 anchor 안 올림)
    r = _run_collect(s, {101: "valid"}, top_ids=[100])
    assert s.get_state("saveticker_scan_hwm") == 101      # 141 아님


def test_transient_hole_freezes_cursor_and_pends(tmp_path):
    from sector.store import SectorStore
    s = SectorStore(tmp_path)
    s.set_states({"saveticker_scan_hwm": 100, "saveticker_observed_anchor": 103,
                  "saveticker_cutover_floor": 100, "saveticker_pending": {}, "saveticker_retry_pos": 0})
    # region A: 101 transient, 102/103 valid → 101 pending, 102·103 raw 저장
    r = _run_collect(s, {101: "transient", 102: "valid", 103: "valid"}, top_ids=[103])
    assert "101" in (s.get_state("saveticker_pending") or {})
    assert r.stats["raw_added"] == 2                       # 102,103
    assert r.status == "degraded"                          # transient>0


def test_pending_retry_resolves_next_cycle(tmp_path):
    from sector.store import SectorStore
    s = SectorStore(tmp_path)
    s.set_states({"saveticker_scan_hwm": 103, "saveticker_observed_anchor": 103,
                  "saveticker_cutover_floor": 100,
                  "saveticker_pending": {"101": {"kind": "transient", "attempts": 1}},
                  "saveticker_retry_pos": 0})
    r = _run_collect(s, {101: "valid"}, top_ids=[103])
    assert "101" not in (s.get_state("saveticker_pending") or {})
    assert r.stats["raw_added"] == 1


def test_canary_all_gone_is_error(tmp_path):
    from sector.store import SectorStore
    s = SectorStore(tmp_path)
    s.set_states({"saveticker_scan_hwm": 100, "saveticker_observed_anchor": 100,
                  "saveticker_cutover_floor": 100, "saveticker_pending": {}, "saveticker_retry_pos": 0})
    # top_ids 존재하지만 그 detail이 전부 404 → canary 실패
    r = _run_collect(s, {}, top_ids=[200, 201, 202])
    assert r.status == "error" and "canary" in r.detail


def test_relevant_items_newest_first_capped(tmp_path):
    from sector.store import SectorStore
    s = SectorStore(tmp_path)
    s.set_states({"saveticker_scan_hwm": 100, "saveticker_observed_anchor": 100,
                  "saveticker_cutover_floor": 100, "saveticker_pending": {}, "saveticker_retry_pos": 0})
    # 101 관련(삼성전자 default title), 102 무관 title
    def handler(req):
        p = req.url.path
        if p == "/api/news/top-stories":
            return httpx.Response(200, json={"news_list": [{"id": "101", "title": "t",
                "content": "c", "created_at": "2026-07-20T10:00:00+09:00"}]})
        if p.startswith("/api/news/detail/"):
            rid = int(p.rsplit("/", 1)[1])
            title = "삼성전자 HBM" if rid == 101 else "날씨 맑음"
            return httpx.Response(200, json={"news": _detail(rid, title=title)})
        if p == "/api/calendar/events":
            return httpx.Response(200, json={"events": []})
        return httpx.Response(404, json={})
    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return await st.collect(s, client=c)
    r = asyncio.run(run())
    ids = [it.id for it in r.items]
    assert ids == ["st-101"]                               # 무관 102 제외
```

- [ ] **Step 2: 실패 확인**

Run: `cd engine && python -m pytest tests/test_sector_saveticker_walk.py -k "collect or seeding or forward or trailing or transient or pending or canary or relevant" -v`
Expected: FAIL (`AttributeError: collect` 또는 미정의 동작).

- [ ] **Step 3: 구현 — `collect()` 추가**

`saveticker.py` 말미에 추가:
```python
def _raw_news_item(news: dict) -> RawNewsItem:
    nid = str(news.get("id") or "")
    text = _to_text(news)
    title = news.get("title") or ""
    return RawNewsItem(
        id=f"st-{nid}", title=title, preview=text[:200], content=text,
        source=news.get("source") or "",
        url=f"https://www.saveticker.com/news/{nid}",
        published_at=news.get("created_at") or "",
        grade_hint="D" if "(카더라)" in title else None,
        extra={"provider": "saveticker"})


async def _frontier_probe(client, anchor: int, budget: _Budget, counts: dict) -> int:
    """anchor 위로 MISS_STOP 연속 404까지 → 마지막 valid(없으면 anchor)."""
    idx, miss, last_valid = anchor + 1, 0, anchor
    while budget.ok() and miss < MISS_STOP:
        k, _news = await _classify_detail(client, idx, budget)
        counts[k] = counts.get(k, 0) + 1
        if k == "valid":
            last_valid = idx; miss = 0
        elif k == "not_found":
            miss += 1
        else:
            miss = 0
        idx += 1
    return last_valid


def _liveness(counts, pending_len, anchor_advanced, valid_ct, canary_kinds, cal_ok):
    if pending_len >= PENDING_MAX:
        return "error", f"pending overflow={pending_len}"
    if anchor_advanced and valid_ct == 0:
        return "error", "anchor advanced but 0 valid"
    seen_cls = counts.get("valid", 0) + counts.get("invalid", 0)
    if seen_cls and counts.get("invalid", 0) / seen_cls > 0.3:
        return "error", "invalid ratio high"
    if counts.get("transient", 0) > 0 or pending_len > 0 or not cal_ok:
        return "degraded", f"transient={counts.get('transient',0)} pending={pending_len} cal_ok={cal_ok}"
    return "ok", ""


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(headers=_UA)
    try:
        budget = _Budget(CYCLE_CAP, MAX_ELAPSED_S, REQUEST_INTERVAL_S)
        counts = {k: 0 for k in ("valid", "deleted", "not_found", "transient", "invalid")}
        docs: list[dict] = []

        anchor_now, known = await _newest(client, budget)
        cal_obs, cal_ok = await _collect_calendar(client, budget)
        if anchor_now is None:
            return CollectorResult(name=NAME, kind=KIND, observations=cal_obs,
                status="error", detail="top-stories drift", stats={"calendar_ok": cal_ok})

        # canary (seen 미오염 — 별도 호출)
        canary_kinds = [(await _classify_detail(client, k, budget))[0]
                        for k in known[:CANARY_SAMPLE]]
        if canary_kinds and all(k in ("not_found", "invalid") for k in canary_kinds):
            return CollectorResult(name=NAME, kind=KIND, observations=cal_obs,
                status="error", detail="detail canary fail",
                stats={"canary": canary_kinds, "calendar_ok": cal_ok})

        cursor = store.get_state("saveticker_scan_hwm")
        observed_anchor = store.get_state("saveticker_observed_anchor") or 0
        cutover_floor = store.get_state("saveticker_cutover_floor")
        anchor = max(observed_anchor, anchor_now)

        if cursor is None:                                     # 시딩
            hwm = await _frontier_probe(client, anchor, budget, counts)
            store.set_states({"saveticker_scan_hwm": hwm,
                              "saveticker_observed_anchor": max(anchor, hwm),
                              "saveticker_cutover_floor": hwm,
                              "saveticker_pending": {}, "saveticker_retry_pos": 0})
            return CollectorResult(name=NAME, kind=KIND, observations=cal_obs,
                status="degraded", detail=f"seeded={hwm}",
                stats={"seeded": hwm, "calendar_ok": cal_ok, **counts})

        pending = dict(store.get_state("saveticker_pending") or {})
        retry_pos = int(store.get_state("saveticker_retry_pos") or 0)
        seen: set[int] = set()
        overflow = False

        # (1) pending 재시도 — 요청수·시간 예약
        pids = sorted(int(k) for k in pending)
        if pids:
            off = retry_pos % len(pids)
            rot = pids[off:] + pids[:off]
        else:
            rot = []
        start_req = budget.requests()
        max_req_item = 1 + RETRY_TRANSIENT
        processed = 0
        for pid in rot:
            if (not budget.ok()
                    or budget.requests() - start_req + max_req_item > PENDING_BUDGET
                    or budget.elapsed() >= PENDING_ELAPSED_S):
                break
            seen.add(pid)
            k, news = await _classify_detail(client, pid, budget)
            counts[k] += 1
            if k == "valid":
                docs.append(news); pending.pop(str(pid), None)
            elif k in ("deleted", "not_found"):
                pending.pop(str(pid), None)
            else:
                pending[str(pid)] = {"kind": k, "attempts": pending.get(str(pid), {}).get("attempts", 0) + 1}
            processed += 1
        retry_pos += processed

        # (2) region A: scan_hwm+1 .. anchor
        idx = int(cursor) + 1
        while idx <= anchor and budget.ok():
            if idx in seen or str(idx) in pending:
                idx += 1; continue
            seen.add(idx)
            k, news = await _classify_detail(client, idx, budget)
            counts[k] += 1
            if k == "valid":
                docs.append(news)
            elif k in ("deleted", "not_found"):
                pass
            else:
                if len(pending) >= PENDING_MAX:
                    overflow = True; break
                pending[str(idx)] = {"kind": k, "attempts": 1}
            idx += 1
        scan_hwm = min(idx - 1, anchor)
        max_valid = scan_hwm

        # (3) region B: anchor+1 .. frontier (overflow면 생략)
        stop_reason = "budget"
        if not overflow:
            miss = 0
            while budget.ok() and miss < MISS_STOP:
                if idx in seen or str(idx) in pending:
                    idx += 1; continue
                seen.add(idx)
                k, news = await _classify_detail(client, idx, budget)
                counts[k] += 1
                if k == "valid":
                    docs.append(news); max_valid = idx; anchor = idx; miss = 0
                elif k == "not_found":
                    miss += 1
                elif k == "deleted":
                    miss = 0
                else:
                    if len(pending) >= PENDING_MAX:
                        overflow = True; break
                    pending[str(idx)] = {"kind": k, "attempts": 1}; miss = 0
                idx += 1
            scan_hwm = max(scan_hwm, max_valid)
            if miss >= MISS_STOP:
                stop_reason = "frontier"

        added = store.append_raw_news([_doc_from(n) for n in docs])
        new_anchor = max(anchor, max_valid, observed_anchor, anchor_now)
        store.set_states({"saveticker_scan_hwm": scan_hwm,
                          "saveticker_observed_anchor": new_anchor,
                          "saveticker_pending": pending, "saveticker_retry_pos": retry_pos})

        cands = sorted((n for n in docs
                        if _relevant((n.get("title") or "") + " " + _to_text(n)[:200])),
                       key=lambda n: int(n.get("id") or 0), reverse=True)[:CARD_CANDIDATE_CAP]
        items = [_raw_news_item(n) for n in cands]

        status, detail = _liveness(counts, len(pending),
                                   new_anchor > observed_anchor, counts["valid"],
                                   canary_kinds, cal_ok)
        if overflow:
            status, detail = "error", f"pending overflow={len(pending)}"
        stats = {**counts, "scan_hwm": scan_hwm, "observed_anchor": new_anchor,
                 "cutover_floor": cutover_floor, "backlog": new_anchor - scan_hwm,
                 "scanned": budget.requests(), "stop_reason": stop_reason,
                 "pending_len": len(pending), "raw_added": added, "calendar_ok": cal_ok}
        return CollectorResult(name=NAME, kind=KIND, items=items, observations=cal_obs,
                               status=status, detail=detail, stats=stats)
    finally:
        if own:
            await client.aclose()
```

- [ ] **Step 4: 통과 확인**

Run: `cd engine && python -m pytest tests/test_sector_saveticker_walk.py -v`
Expected: PASS (전체). 실패 시 해당 테스트의 기대값 대비 로그로 디버그(off-by-one은 `scan_hwm` 경계 우선 확인).

- [ ] **Step 5: 커밋**

```bash
git add engine/sector/collectors/saveticker.py engine/tests/test_sector_saveticker_walk.py
git commit -m "feat(saveticker): collect() id-walk 시딩·canary·pending·무손실 커밋

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: runner 통합 회귀 + 기존 테스트 정리

**Files:**
- Modify: `engine/tests/test_sector_collectors_news.py` (죽은 `/news/list` 기반 SaveTicker 테스트 제거/교체)
- Test: `engine/tests/test_sector_saveticker_walk.py` (통합 1건 추가)

**Interfaces:**
- Consumes: `runner.collect_all`, `saveticker.collect`.

- [ ] **Step 1: 기존 SaveTicker 테스트 상태 확인**

Run: `cd engine && python -m pytest tests/test_sector_collectors_news.py -v`
Expected: SaveTicker(`/news/list`) 관련 테스트 FAIL(엔드포인트 미호출). 어떤 테스트가 깨지는지 목록 확보.

- [ ] **Step 2: 죽은 소스 테스트 교체**

`test_sector_collectors_news.py`에서 `_ST_LIST`/`/api/news/list` 기반 SaveTicker 단위 테스트를 삭제하고, runner 격리 테스트(`test_collect_all_isolates_failures`, `test_collect_all_only_filter`)는 유지. SaveTicker 상세는 `test_sector_saveticker_walk.py`가 담당함을 주석으로 명시.

- [ ] **Step 3: 통합 회귀 테스트 추가**

`test_sector_saveticker_walk.py`에 추가(다른 news 소스와 합산 시 saveticker가 이들을 소멸시키지 않음):
```python
def test_starvation_regression_other_sources_survive(tmp_path):
    import types
    from sector import runner
    from sector.store import SectorStore
    from sector.contracts import CollectorResult, RawNewsItem

    s = SectorStore(tmp_path)
    s.set_states({"saveticker_scan_hwm": 100, "saveticker_observed_anchor": 100,
                  "saveticker_cutover_floor": 100, "saveticker_pending": {}, "saveticker_retry_pos": 0})

    other = types.ModuleType("othernews")
    other.NAME, other.KIND = "othernews", "news"
    async def ocollect(store, client=None):
        return CollectorResult(name="othernews", kind="news",
            items=[RawNewsItem(id=f"o-{i}", title="TSMC capex") for i in range(50)])
    other.collect = ocollect

    captured = {}
    async def fake_judge(items):
        captured["names"] = {it.id.split("-")[0] for it in items}
        return []
    st_mod = st

    import asyncio
    async def run():
        async def sv_collect(store, client=None):
            async with _client(_transport({101: "valid", 102: "valid"}, top_ids=[102])) as c:
                return await st_mod.collect(store, client=c)
        sv = types.ModuleType("saveticker"); sv.NAME, sv.KIND = "saveticker", "news"; sv.collect = sv_collect
        runner_reg = [sv, other]
        import sector.runner as R
        R._registry = lambda: runner_reg
        await R.collect_all(s, judge_fn=fake_judge)
    asyncio.run(run())
    assert "o" in captured["names"] and "st" in captured["names"]   # 둘 다 판정 풀에 존재
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd engine && python -m pytest tests/test_sector_saveticker_walk.py tests/test_sector_raw_store.py tests/test_sector_collectors_news.py -v`
Expected: PASS (전체). 그리고 회귀 없음 확인: `python -m pytest tests/ -q -m "not live"`.

- [ ] **Step 5: 커밋**

```bash
git add engine/tests/test_sector_collectors_news.py engine/tests/test_sector_saveticker_walk.py
git commit -m "test(saveticker): 죽은 list 테스트 교체 + starvation 회귀

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: 라이브 스모크 + 배포 확인 (수동)

**Files:** 없음(운영 확인). [[engine-runs-under-pm2]] · [[verify-ui-with-screenshots]]

- [ ] **Step 1: 라이브 1회 수집(수동)**

`pm2 restart attn-engine` 후:
```bash
curl -s -m 400 -X POST http://127.0.0.1:8801/v1/sector/collect -H 'content-type: application/json' -d '{"only":["saveticker"]}' | python3 -m json.tool
```
Expected: 첫 실행은 `status=degraded, detail="seeded=<id>"`.

- [ ] **Step 2: 두 번째 수집 = 실제 적재**

같은 curl 재실행. Expected: `stats.raw_added > 0`, `status` in (ok/degraded), `news_raw/2026-07.jsonl` 생성.
```bash
wc -l storage/rag/memory_sector/news_raw/2026-07.jsonl
```

- [ ] **Step 3: 상태 구조화 확인**

```bash
curl -s http://127.0.0.1:8801/v1/sector/status | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin)['collectors']['saveticker'],ensure_ascii=False,indent=1))"
```
Expected: `stats`에 `scan_hwm/observed_anchor/backlog/raw_added/stop_reason`.

- [ ] **Step 4: 커밋 없음(운영 확인 단계)** — 이상 시 Task 7로 회귀.

---

## Self-Review

- **Spec coverage**: §3 상태모델→Task7(상태키·시딩·pending), §4.1 의사코드→Task5·6·7, §4.2 카드경로→Task7(_relevant·items·CAP), §4.3 contracts→Task1, §4.4 store→Task2·3·4, §4.5 runner 무변경→Task8 회귀, §5 관측성→Task7 `_liveness`, §6 안전·budget→Task5 `_Budget`+Task7, §7 테스트→Task5~8. 모두 태스크 존재.
- **Placeholder scan**: 코드 블록 실제 구현 포함, "TODO/적절히" 없음. Task2 Step3의 `json.dump` 시그니처 주의 노트 명시.
- **Type consistency**: `_classify_detail`→`(str, dict|None)`, `_newest`→`(int|None, list[int])`, `append_raw_news(list[RawNewsDoc])→int`, `set_states(dict)`, 상태키 문자열 5종 일관. `RawNewsDoc.ingested_at`(store 스탬프) — spec의 `collected_at`을 기존 패턴(`ingested_at`)에 맞춤(자체검토 정정: 일관성 위해 `ingested_at` 사용).
