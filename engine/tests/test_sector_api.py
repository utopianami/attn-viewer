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
