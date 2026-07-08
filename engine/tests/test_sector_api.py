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


def test_prices_endpoint_caches_and_isolates(tmp_path, monkeypatch):
    """/v1/sector/prices — 시계열 반환 + 1시간 캐시 + 종목 실패 격리."""
    import sector.api as api
    import sector.prices as prices_mod
    calls = []
    async def fake_fetch(client, symbol, p1, p2):
        calls.append(symbol)
        if symbol == "MU":
            raise RuntimeError("down")
        return ([(1751000000, 100.0), (1751086400, 103.0)], {})
    monkeypatch.setattr(prices_mod, "_fetch", fake_fetch)
    api._PRICES_CACHE.update(at=0.0, days=0, data=None)
    async def go():
        async with _client(tmp_path, monkeypatch) as c:
            r = await c.get("/v1/sector/prices?days=30")
            assert r.status_code == 200
            data = r.json()
            by = {s["token"]: s for s in data["series"]}
            assert by["005930.KS"]["last"] == 103.0
            assert abs(by["005930.KS"]["day_pct"] - 3.0) < 0.01
            assert "error" in by["MU"]                    # 격리
            n1 = len(calls)
            await c.get("/v1/sector/prices?days=30")      # 캐시 적중
            assert len(calls) == n1
    asyncio.run(go())


def test_briefing_endpoint(tmp_path, monkeypatch):
    """/v1/sector/briefing — 지표 없어도 규칙 폴백 문장 반환, LLM 미호출 시에도 200."""
    import sector.briefing as brief
    async def fake_build(store, overrides=None):
        return {"text": "메모리 사이클은 현재 판정 데이터 축적 중.", "facts": {"cycle": {"state": "insufficient"}}}
    monkeypatch.setattr(brief, "build_briefing", fake_build)
    import sector.api as api
    api._BRIEF_CACHE.update(at=0.0, data=None)
    async def go():
        async with _client(tmp_path, monkeypatch) as c:
            r = await c.get("/v1/sector/briefing")
            assert r.status_code == 200
            assert "text" in r.json() and r.json()["text"]
    asyncio.run(go())


def test_briefing_rule_fallback_offline(tmp_path):
    """LLM 없이 gather_facts + 규칙 문장 생성 (실데이터 경로)."""
    from sector.briefing import gather_facts, _rule_text
    from sector.contracts import MetricObservation
    from sector.store import SectorStore
    store = SectorStore(tmp_path)
    store.append_observations([
        MetricObservation(metric="kr_semi_export", ts="2026-05", value=8.5e6, meta={"item": "01~10"}),
        MetricObservation(metric="kr_semi_export", ts="2026-06", value=11.1e6, meta={"item": "01~10"}),
    ])
    facts = gather_facts(store)
    assert facts["semi_export_change_pct"] is not None
    txt = _rule_text(facts)
    assert "사이클" in txt


def test_briefing_dram_series_not_mixed(tmp_path):
    """시리즈 혼합 회귀 — DDR3/DDR4가 섞여 -70% 같은 쓰레기 변화율이 나오면 안 됨."""
    from sector.briefing import gather_facts
    from sector.contracts import MetricObservation
    from sector.store import SectorStore
    store = SectorStore(tmp_path)
    store.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=8.0,
                          meta={"category": "DRAM", "item": "DRAM|DDR4"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=3.0,
                          meta={"category": "DRAM", "item": "DRAM|DDR3"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=8.4,
                          meta={"category": "DRAM", "item": "DRAM|DDR4"}),
    ])
    f = gather_facts(store)
    assert f["dram_price_change_pct"] == 5.0   # 8.0→8.4 (+5%), DDR3 혼입 시 +180%


def test_briefing_tsmc_uses_yoy_not_absolute(tmp_path):
    """스크린샷 검증 발견 회귀 — TSMC 칩에 +4억% 같은 절대값 혼입 방지."""
    from sector.briefing import gather_facts
    from sector.contracts import MetricObservation
    from sector.store import SectorStore
    store = SectorStore(tmp_path)
    store.append_observations([MetricObservation(
        metric="tw_monthly_revenue", ts="2026-05", value=30094980202.7,
        meta={"name": "TSMC", "code": "2330", "yoy": 30.1})])
    assert gather_facts(store)["tsmc_yoy"] == 30.1


def test_assessment_rules(tmp_path):
    """브리프(2026-07-08) 규칙 검증 — 4분면 상태, 끊긴 곳, 모르는 것."""
    from sector.briefing import build_assessment
    facts = {"cycle": {"state": "up", "score": 0.71},
             "token_growth_pct": -0.2,        # 밴드 안 → 정체(0)
             "dram_price_change_pct": 21.7, "dram_series": "DDR5 (Keepa)",
             "semi_export_change_pct": 29.6, "inventory_change_pct": 0.5,
             "tsmc_yoy": 30.1, "tsmc_mom": 1.5, "quanta_mom": -8.4}
    from sector.store import SectorStore
    a = build_assessment(facts, SectorStore(tmp_path), {"avg30": 7.7})
    q = {x["key"]: x for x in a["quadrants"]}
    assert q["demand"]["status"] == "good" and q["price"]["status"] == "good"
    assert q["inventory"]["status"] == "mixed"           # +0.5%는 ±1% 밴드 안
    assert q["supply"]["status"] == "nodata"
    assert "서버·투자 단계 약함" in a["break_point"]      # 서버 -3.5 vs 실물 +29.6
    assert any("공급" in u for u in a["unknown"])
    assert "업사이클" in a["headline"]
    bands = {c["key"]: c["band"] for c in a["chain"]}
    assert bands == {"ai": 0, "server": -1, "physical": 1, "stock": 1}


def test_assessment_stock_divergence(tmp_path):
    """실물 강세 + 주가 조정 → 괴리 문구."""
    from sector.briefing import build_assessment
    from sector.store import SectorStore
    facts = {"cycle": {"state": "up", "score": 0.5}, "token_growth_pct": 2.0,
             "dram_price_change_pct": 5.0, "dram_series": "DDR5",
             "semi_export_change_pct": 10.0, "inventory_change_pct": -2.0,
             "tsmc_yoy": 30.0, "tsmc_mom": 2.0, "quanta_mom": 3.0}
    a = build_assessment(facts, SectorStore(tmp_path), {"avg30": -8.0})
    assert "과민반응" in a["break_point"]
