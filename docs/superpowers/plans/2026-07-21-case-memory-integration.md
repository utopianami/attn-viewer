# 과거사례 지식층 (Case-Memory) — Plan 3: 통합(API + 리포트 seam) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan 1/2 로 만든 case-memory 코어를 (a) 엔진 FastAPI 라우터 `/v1/case-memory/*`로 노출하고 (b) `ReportInput.external_knowledge` seam에 결정적으로 배선해, 리포트 입력이 과거사례 질의 결과를 담게 한다.

**Architecture:** 전부 결정적(llm_fn=None). `engine/casemem/api.py` = `sector/api.py` 패턴 복제(APIRouter + `_get_store` + 빈 스토어면 시드 자동 적재). `report_input.assemble_report_input`에 optional `case_store`/`signals`/`as_of` 추가 — 주면 `query_case_memory`로 external_knowledge 채움, 없으면 기존과 바이트 동일. **라이브 오케스트레이터 주입·async LLM 리랭크·HTML 대시보드는 Plan 4**(async 어댑터·PM2·스크린샷 필요).

**Tech Stack:** Python 3.11+, FastAPI 0.139(`engine/.venv`), Pydantic v2, pytest + fastapi.testclient.

## Global Constraints

- **결정적**: 이 Plan은 LLM 콜 없음. API·seam 모두 llm_fn 미주입(Plan1 동작).
- **하위호환**: `assemble_report_input`의 새 인자는 전부 optional·기본 None → 기존 호출자 영향 0.
- **never-raise**: API·seam은 스토어 부재/파싱 실패에도 빈 결과+진단. 500 대신 빈 매치.
- **인터프리터**: 테스트·실행은 `engine/.venv/bin/python`(fastapi 있음). 루트 `.venv`엔 fastapi 없음.
- **스토어 실경로**: `settings` 있으면 그걸로, 없으면 `REPO_ROOT/storage/rag/case_memory` (sector/api.py `_get_store` 패턴).
- as-of 안전·룩어헤드 차단은 Plan1 검색이 이미 보장 — 이 Plan은 경계만 노출.

---

## File Structure

- Create: `engine/casemem/api.py` — `APIRouter(prefix="/v1/case-memory")` + `_get_store()`(빈 스토어 시드 자동 적재) + `POST /query`·`GET /cases`·`GET /cases/{id}`.
- Modify: `engine/app/main.py` — `casemem.api.router` include.
- Modify: `engine/casemem/query.py` — 변경 없음(재사용). 
- Modify: `engine/sector/report_input.py` — `assemble_report_input(..., case_store=None, signals=None, as_of=None)` + external_knowledge 채움.
- Create: `engine/tests/test_casemem_api.py` — TestClient 라우트 테스트.
- Modify: `engine/tests/test_report_input.py` — seam 배선 테스트.

---

### Task 1: FastAPI 라우터 `/v1/case-memory`

**Files:**
- Create: `engine/casemem/api.py`
- Modify: `engine/app/main.py`
- Test: `engine/tests/test_casemem_api.py`

**Interfaces:**
- Produces:
  - `router = APIRouter(prefix="/v1/case-memory")`.
  - `def _get_store() -> CaseStore` — settings/REPO_ROOT 기준 루트, 빈 스토어(첫 read_episodes 빈 리스트)면 `load_seeds()` 1회 적재.
  - `POST /query` body `QueryBody(signals: list[str], as_of: str, sector: str = "memory", k: int = 5)` → `query_case_memory(...).model_dump()`.
  - `GET /cases?sector=` → `{"cases": [ep.model_dump() ...]}`.
  - `GET /cases/{episode_id}` → 단일 ep.model_dump() 또는 404 `{"error": "not_found"}`.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_casemem_api.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import casemem.api as capi
from casemem.store import CaseStore
from casemem.seeds import load_seeds
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(tmp_path):
    store = CaseStore(tmp_path)
    load_seeds(store)
    capi._STORE = store                       # 테스트용 스토어 주입
    app = FastAPI()
    app.include_router(capi.router)
    return TestClient(app)


def test_query_endpoint_returns_matches(tmp_path):
    c = _client(tmp_path)
    r = c.post("/v1/case-memory/query",
               json={"signals": ["재고일수 상승"], "as_of": "2018-07-01", "sector": "memory"})
    assert r.status_code == 200
    body = r.json()
    assert body["sector"] == "memory"
    assert any(m["episode_id"] == "mem-2018-downcycle" for m in body["matches"])
    assert body["rerank_used"] is False       # 결정적


def test_cases_list_and_get(tmp_path):
    c = _client(tmp_path)
    lst = c.get("/v1/case-memory/cases", params={"sector": "memory"}).json()
    assert len(lst["cases"]) >= 2
    one = c.get("/v1/case-memory/cases/mem-2018-downcycle")
    assert one.status_code == 200 and one.json()["id"] == "mem-2018-downcycle"
    missing = c.get("/v1/case-memory/cases/nope")
    assert missing.status_code == 404


def test_query_bad_as_of_is_empty_not_500(tmp_path):
    c = _client(tmp_path)
    r = c.post("/v1/case-memory/query",
               json={"signals": ["x"], "as_of": "garbage"})
    assert r.status_code == 200 and r.json()["matches"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'casemem.api'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/casemem/api.py
"""Case-Memory API 라우터 — sector/api.py 패턴 복제. 결정적(리랭크 없음)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.settings import REPO_ROOT, settings
from casemem.query import query_case_memory
from casemem.seeds import load_seeds
from casemem.store import CaseStore

router = APIRouter(prefix="/v1/case-memory")

_STORE: CaseStore | None = None


def _store_root() -> Path:
    override = getattr(settings, "casemem_storage_dir", "") or ""
    return Path(override) if override else REPO_ROOT / "storage" / "rag" / "case_memory"


def _get_store() -> CaseStore:
    global _STORE
    if _STORE is None:
        _STORE = CaseStore(_store_root())
        if not _STORE.read_episodes():          # 빈 스토어면 시드 1회 적재
            load_seeds(_STORE)
    return _STORE


class QueryBody(BaseModel):
    signals: list[str] = []
    as_of: str
    sector: str = "memory"
    k: int = 5


@router.post("/query")
async def query(body: QueryBody) -> dict:
    res = query_case_memory(_get_store(), signals=body.signals, as_of=body.as_of,
                            sector=body.sector, k=body.k)
    return res.model_dump()


@router.get("/cases")
async def cases(sector: str = "") -> dict:
    eps = _get_store().read_episodes(sector=sector or None)
    return {"cases": [e.model_dump() for e in eps]}


@router.get("/cases/{episode_id}")
async def case_one(episode_id: str):
    for e in _get_store().read_episodes():
        if e.id == episode_id:
            return e.model_dump()
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={"error": "not_found", "id": episode_id})
```

`engine/app/main.py`에 라우터 등록:

```python
# engine/app/main.py — sector_router include 아래에 추가
from casemem.api import router as casemem_router  # noqa: E402
app.include_router(casemem_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_api.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/api.py engine/app/main.py engine/tests/test_casemem_api.py
git commit -m "feat(casemem): FastAPI 라우터 /v1/case-memory (query·cases) + 앱 등록"
```

---

### Task 2: ReportInput.external_knowledge seam 배선

**Files:**
- Modify: `engine/sector/report_input.py`
- Test: `engine/tests/test_report_input.py`

**Interfaces:**
- Consumes: `casemem.query.query_case_memory`, `casemem.store.CaseStore`.
- Produces (수정): `def assemble_report_input(store, *, window_hours=12, now=None, metrics=None, case_store=None, signals=None, as_of=None) -> ReportInput`. `case_store`가 주어지면 `query_case_memory(case_store, signals=signals or [], as_of=as_of or now.isoformat(), sector="memory")` 결과를 `external_knowledge=[result.model_dump()]`로 채움. 없으면 `external_knowledge=[]`(기존). 쿼리 실패(예외)는 never-raise로 삼켜 빈 리스트.

- [ ] **Step 1: Write the failing test**

```python
# append to engine/tests/test_report_input.py
def test_external_knowledge_filled_when_case_store_given(tmp_path):
    from casemem.store import CaseStore
    from casemem.seeds import load_seeds
    from datetime import datetime, timezone
    cs = CaseStore(tmp_path / "cm")
    load_seeds(cs)
    s = SectorStore(tmp_path / "sec")
    now = datetime(2018, 7, 1, 12, 0, tzinfo=timezone.utc)
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[],
                               case_store=cs, signals=["재고일수 상승"],
                               as_of="2018-07-01")
    assert len(ri.external_knowledge) == 1
    ek = ri.external_knowledge[0]
    assert ek["sector"] == "memory"
    assert any(m["episode_id"] == "mem-2018-downcycle" for m in ek["matches"])


def test_external_knowledge_empty_without_case_store(tmp_path):
    s = SectorStore(tmp_path)
    from datetime import datetime, timezone
    ri = assemble_report_input(s, window_hours=12,
                               now=datetime(2018, 7, 1, tzinfo=timezone.utc), metrics=[])
    assert ri.external_knowledge == []          # 하위호환
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_report_input.py -k external_knowledge -v`
Expected: FAIL — `TypeError: assemble_report_input() got an unexpected keyword argument 'case_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/sector/report_input.py — assemble_report_input 시그니처·본문 수정
def assemble_report_input(store, *, window_hours: int = 12,
                          now: datetime | None = None,
                          metrics: list[str] | None = None,
                          case_store=None, signals: list[str] | None = None,
                          as_of: str | None = None) -> ReportInput:
    now = _to_utc(now or datetime.now(timezone.utc))
    win_from = now - timedelta(hours=window_hours)

    cards, cstat = _in_window(store.read_cards(days=None, limit=None),
                              lambda c: c.ts, win_from, now)
    raw_news, rstat = _in_window(store.read_raw_news(months=None, limit=None),
                                 lambda d: d.created_at, win_from, now)

    metric_summaries, missing = build_metric_summaries(store, metrics)

    external_knowledge: list[dict] = []
    if case_store is not None:
        try:
            from casemem.query import query_case_memory
            res = query_case_memory(case_store, signals=signals or [],
                                    as_of=as_of or now.isoformat(), sector="memory")
            external_knowledge = [res.model_dump()]
        except Exception:  # noqa: BLE001 — never-raise, seam 실패는 빈 리스트
            external_knowledge = []

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
        external_knowledge=external_knowledge,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_report_input.py -v`
Expected: PASS (전체 — 기존 + 신규)

- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_input.py engine/tests/test_report_input.py
git commit -m "feat(report): external_knowledge seam — case_store 주면 과거사례 질의 배선(하위호환)"
```

---

## Self-Review

- **Spec coverage**: 설계 §8(API 경계 — POST query·GET cases)=Task1, §3-L3(리포트가 API/seam으로만 소비)=Task2 external_knowledge. **의도적 제외**: 라이브 오케스트레이터 SYNTHESIZE/AUDITOR 주입·async LLM 리랭크·워크플로우/데이터수집 HTML·PM2 재기동=Plan 4(스크린샷·async 어댑터 필요).
- **하위호환/결정성**: `assemble_report_input` 새 인자 전부 optional 기본 None → 기존 테스트 회귀 0. API는 llm_fn 미주입 → rerank_used=False.
- **never-raise**: seam 쿼리 예외 삼킴, API bad as_of는 빈 매치 200(500 아님).
- **인터프리터 함정**: 테스트는 `engine/.venv`(fastapi 有). 계획 명령 전부 그 경로. 루트 `.venv` 금지 명시.
- **Placeholder scan**: 전 스텝 실제 코드·명령. `settings.casemem_storage_dir`는 `getattr(..., "")`로 부재 안전(설정 미정의여도 폴백). TBD 없음.
- **Type consistency**: `query_case_memory`(Plan1/2 시그니처: signals·as_of·sector·k)→API·seam 동일 호출. `CaseQueryResult.model_dump()`→dict. `CaseStore.read_episodes(sector=)`→API cases. 일치.
- **잔여 리스크(수용)**: `_get_store` 모듈 전역 캐시 — 테스트가 `capi._STORE` 주입으로 우회(테스트에 명시). 실서비스 첫 호출 시 시드 자동 적재는 idempotent(dedup). report_input은 아직 라이브 소비처 없음(Phase2 파이프라인 미구현) — seam은 선반영.

## 다음 Plan
- **Plan 4 (라이브 활성화 — 게이트)**: async LLM 리랭크 어댑터(`Role('casemem_rerank')` 재사용, temperature/effort 저) + 오케스트레이터 sector_rag 패턴 주입(profile 플래그 기본 OFF) + AUDITOR 근거 편입 + workflow-review.html·data-collection.html 현행화 + PM2 재기동 + Playwright 스크린샷 검증.
- **Plan 5 (증류·검증 — 리서치성)**: 코퍼스→국면/규칙 증류(§6) + 검증 게이트(§7).
