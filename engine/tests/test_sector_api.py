"""sector API — 라우터 배선·collect 트리거 (P1 Task 9)."""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402


def _client(tmp_path, monkeypatch):
    from app.settings import settings
    monkeypatch.setattr(settings, "sector_storage_dir", str(tmp_path))
    # 테스트 격리 — 운영 .env가 스케줄러를 켰어도 테스트 기대는 OFF 기준
    monkeypatch.setattr(settings, "sector_scheduler_enabled", False)
    from app.main import app
    import sector.api as api
    api._STORE = None   # 캐시 리셋
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://t")


def test_status_and_empty_board(tmp_path, monkeypatch):
    async def go():
        async with _client(tmp_path, monkeypatch) as c:
            s = await c.get("/v1/sector/status")
            assert s.status_code == 200
            sj = s.json()
            assert sj["scheduler"]["enabled"] is False
            # F4: summary 오브젝트 존재 확인
            assert "summary" in sj
            summary = sj["summary"]
            assert set(summary.keys()) >= {"ok", "degraded", "missing_key", "error"}

            b = await c.get("/v1/sector/board")
            assert b.status_code == 200
            bj = b.json()
            assert bj["cycle"]["state"] == "insufficient"
            # F4: generated_at 필드 + factor_details 존재 확인
            assert "generated_at" in bj
            assert "factor_details" in bj["cycle"]
    asyncio.run(go())


def test_collect_trigger_with_stub_registry(tmp_path, monkeypatch):
    import sector.runner as runner
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


# ── I2: scheduler 테스트 ──────────────────────────────────────────────────────

def test_scheduler_disabled_returns_none(tmp_path, monkeypatch):
    """sector_scheduler_enabled=False → start()가 None 반환, 태스크 없음."""
    from app.settings import settings
    monkeypatch.setattr(settings, "sector_scheduler_enabled", False)
    import sector.scheduler as scheduler
    app = types.SimpleNamespace(state=types.SimpleNamespace())

    async def go():
        result = await scheduler.start(app)
        assert result is None
        assert not hasattr(app.state, "sector_task") or app.state.sector_task is None

    asyncio.run(go())


def test_scheduler_enabled_creates_task_and_calls_collect(tmp_path, monkeypatch):
    """sector_scheduler_enabled=True → Task 생성, _loop가 collect_all을 1회 이상 호출."""
    from app.settings import settings
    monkeypatch.setattr(settings, "sector_scheduler_enabled", True)
    monkeypatch.setattr(settings, "sector_collect_interval_s", 0)
    monkeypatch.setattr(settings, "sector_storage_dir", str(tmp_path))

    import sector.scheduler as scheduler
    import sector.api as api
    api._STORE = None  # 캐시 리셋

    collect_calls = []

    async def fake_collect_all(store, **kwargs):
        collect_calls.append(1)
        return []

    # _loop 내부에서 import하므로 runner 모듈을 직접 패치
    import sector.runner as runner
    monkeypatch.setattr(runner, "collect_all", fake_collect_all)

    app = types.SimpleNamespace(state=types.SimpleNamespace())

    async def go():
        task = await scheduler.start(app)
        assert task is not None
        # collect_all이 최소 1회 호출될 때까지 짧게 양보
        for _ in range(20):
            await asyncio.sleep(0)
            if collect_calls:
                break
        assert collect_calls, "collect_all should have been called at least once"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(go())
