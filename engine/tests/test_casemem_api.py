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
