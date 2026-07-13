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
    async def fake_build(store, overrides=None, skip_llm=False):
        return {"text": "메모리 사이클은 현재 판정 데이터 축적 중.", "facts": {"cycle": {"state": "insufficient"}}}
    monkeypatch.setattr(brief, "build_briefing", fake_build)
    import sector.api as api
    api._BRIEF_CACHE.update(at=0.0, data=None, refreshing=False)
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


def test_facts_capex_qoq_needs_all_four(tmp_path):
    """4사 모두 보고한 분기만 합산 — 결산 시차 분기 혼입 방지."""
    from sector.briefing import gather_facts
    from sector.contracts import MetricObservation
    from sector.store import SectorStore
    store = SectorStore(tmp_path)
    obs = []
    for q, vals in [("2025-12", {"MSFT": 29.9, "GOOGL": 25.0, "AMZN": 30.0, "META": 18.0}),
                    ("2026-03", {"MSFT": 30.9, "GOOGL": 28.0, "AMZN": 33.0, "META": 20.0}),
                    ("2026-06", {"MSFT": 32.0})]:            # 미완 분기 — 제외돼야
        for tk, v in vals.items():
            obs.append(MetricObservation(metric="hyperscaler_capex", ts=q, value=v,
                                         meta={"token": tk, "item": tk}))
    store.append_observations(obs)
    f = gather_facts(store)
    assert f["capex_total_b"] == 111.9                      # 2026-03 4사 합
    assert abs(f["capex_qoq_pct"] - 8.8) < 0.15             # 102.9 → 111.9


def test_assessment_cycle_quality_and_divergence(tmp_path):
    """파생 인사이트 — Cycle Quality(업사이클의 질) + Market Divergence(주가 vs 실물)."""
    from sector.briefing import build_assessment
    from sector.store import SectorStore
    base = {"cycle": {"state": "up", "score": 0.5}, "token_growth_pct": 2.0,
            "dram_price_change_pct": 5.0, "dram_series": "DDR5",
            "semi_export_change_pct": 10.0, "inventory_change_pct": -2.0,
            "tsmc_yoy": 30.0, "tsmc_mom": 2.0, "quanta_mom": 3.0}
    a = build_assessment(base, SectorStore(tmp_path), {"avg30": 8.0})
    assert a["cycle_quality"]["grade"] == "strong"        # 수요↑가격↑재고↓ 공급 반대 아님
    assert a["market_divergence"]["state"] == "aligned"   # 실물↑ 주가↑

    a2 = build_assessment(base, SectorStore(tmp_path), {"avg30": -8.0})
    assert a2["market_divergence"]["state"] == "stock_lagging"   # 실물↑ 주가↓

    frag = dict(base, inventory_change_pct=3.0)           # 재고 급증 = 나쁨
    a3 = build_assessment(frag, SectorStore(tmp_path), {"avg30": 8.0})
    assert a3["cycle_quality"]["grade"] == "fragile"


def test_hbm_tightness_from_cards(tmp_path):
    """HBM Tightness — 카드 키워드 합성: sold-out·계약·병목=타이트 / 증설·과잉=완화."""
    import datetime as dt
    from sector.briefing import hbm_tightness
    from sector.contracts import SectorCard
    from sector.store import SectorStore
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    def card(i, title, seg="hbm", direction="pos", mag=3):
        return SectorCard(id=f"h{i}", ts=now, axis="A", title=title,
                          memory_segment=seg, direction=direction, magnitude=mag)
    store = SectorStore(tmp_path)
    store.append_cards([
        card(1, "SK하이닉스 HBM4 내년 물량 sold out — 완판 발언"),
        card(2, "마이크론, HBM 장기 공급계약 체결"),
        card(3, "TSMC CoWoS 병목 지속 — 패키징 캐파 부족"),
        card(4, "삼성전자 D램 일반 뉴스", seg="dram"),          # HBM 아님 — 제외
    ])
    r = hbm_tightness(store)
    assert r["level"] == "tight" and r["tight_score"] > 0 and r["loose_score"] == 0

    store2 = SectorStore(tmp_path / "b")
    store2.append_cards([
        card(1, "삼성전자 HBM 캐파 증설 발표 — 공급 확대", direction="neg"),
        card(2, "CXMT HBM 시장 진입 — 공급 과잉 우려", direction="neg"),
    ])
    r2 = hbm_tightness(store2, quanta_mom=-8.4)               # 서버 프록시 둔화도 완화 신호
    assert r2["level"] == "easing" and r2["loose_score"] > r2["tight_score"]

    r3 = hbm_tightness(SectorStore(tmp_path / "c"))
    assert r3["level"] == "nodata"


def test_build_briefing_skip_llm_is_rule_only(tmp_path, monkeypatch):
    """skip_llm=True — LLM 없이 규칙 문장+판단 즉시 반환 (판단·사슬이 LLM을 기다리지 않게)."""
    import sys
    import types as _types
    bomb = _types.ModuleType("providers")
    class _Boom:
        def __init__(self, *a, **k):
            raise AssertionError("skip_llm인데 LLM 경로 진입")
    bomb.Role = _Boom
    monkeypatch.setitem(sys.modules, "providers", bomb)
    from sector.briefing import build_briefing
    from sector.store import SectorStore
    r = asyncio.run(build_briefing(SectorStore(tmp_path), skip_llm=True))
    assert r["llm_pending"] is True
    assert r["text"] and isinstance(r["text"], str)      # 규칙 폴백 문장
    assert "assessment" in r and r["assessment"]["quadrants"]


def test_adr_premium_math():
    """ADR×10×환율 vs 원주 괴리율 — FX 없으면 None."""
    from sector.prices import adr_premium
    series = [{"token": "SKHY", "last": 168.01, "points": [["2026-07-10", 168.01]]},
              {"token": "000660.KS", "last": 2008000, "points": [["2026-07-13", 2008000]]}]
    r = adr_premium(series, 1380.0)
    assert abs(r["premium_pct"] - 15.5) < 0.2       # 168.01×10×1380 / 2,008,000 - 1
    assert r["adr_asof"] == "2026-07-10" and r["local_asof"] == "2026-07-13"
    assert adr_premium(series, None) is None
    assert adr_premium([series[0]], 1380.0) is None  # 원주 없으면 None


def test_assessment_stock_move_explains_drop(tmp_path):
    """주가 급변(±3%↑) 감지 시 최근 악재 카드에서 '왜' 후보를 뽑아 노출."""
    import datetime as dt
    from sector.briefing import build_assessment
    from sector.contracts import SectorCard
    from sector.store import SectorStore
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    store = SectorStore(tmp_path)
    store.append_cards([
        SectorCard(id="m1", ts=now, axis="market", title="ADR 신주 물량 부담에 반도체주 급락",
                   direction="neg", magnitude=3),
        SectorCard(id="m2", ts=now, axis="A", title="AI 고점론 확산 — 메모리 차익실현",
                   direction="neg", magnitude=2),
        SectorCard(id="m3", ts=now, axis="C0", title="무관한 소소한 뉴스",
                   direction="neg", magnitude=1),
    ])
    facts = {"cycle": {"state": "up", "score": 0.7}, "token_growth_pct": 2.0,
             "dram_price_change_pct": 5.0, "dram_series": "DDR5",
             "semi_export_change_pct": 10.0, "inventory_change_pct": -2.0,
             "tsmc_yoy": 30.0, "tsmc_mom": 2.0, "quanta_mom": 3.0}
    a = build_assessment(facts, store, {"avg30": -8.0,
                                        "day": {"005930.KS": -3.9, "000660.KS": -7.9}})
    mv = a["stock_move"]
    assert mv["direction"] == "down"
    assert any("ADR" in r for r in mv["reasons"])          # 임팩트 큰 악재가 이유 후보
    assert all("무관한" not in r for r in mv["reasons"])    # 저임팩트 잡음 제외
    assert mv["note"]                                       # 지표 강세 → 수급성 하락 해석

    a2 = build_assessment(facts, store, {"avg30": 5.0,
                                         "day": {"005930.KS": 0.5, "000660.KS": -0.8}})
    assert a2.get("stock_move") is None                     # 평온한 날은 미표시


def test_price_series_includes_macro_backdrop(tmp_path, monkeypatch):
    """거시 배경 4종(원달러·브렌트·미10y·VIX) — 주가와 분리된 macro 시리즈로."""
    import sector.prices as prices_mod
    async def fake_fetch(client, symbol, p1, p2):
        return ([(1751000000, 100.0), (1751086400, 103.0)], {})
    monkeypatch.setattr(prices_mod, "_fetch", fake_fetch)
    r = asyncio.run(prices_mod.price_series(days=30))
    macro = {s["token"] for s in r["macro"]}
    assert macro == {"KRW=X", "BZ=F", "^TNX", "^VIX"}
    assert all(s["day_pct"] is not None for s in r["macro"])
    assert r["adr_premium"] is not None                     # 환율은 macro에서 재사용


def test_assessment_stock_move_macro_context(tmp_path):
    """급변일에 거시(유가·환율)도 급변이면 macro_note로 배경 명시."""
    from sector.briefing import build_assessment
    from sector.store import SectorStore
    facts = {"cycle": {"state": "up", "score": 0.7}, "token_growth_pct": 2.0,
             "dram_price_change_pct": 5.0, "dram_series": "DDR5",
             "semi_export_change_pct": 10.0, "inventory_change_pct": -2.0,
             "tsmc_yoy": 30.0, "tsmc_mom": 2.0, "quanta_mom": 3.0}
    stock30 = {"avg30": -8.0, "day": {"005930.KS": -6.1, "000660.KS": -10.3},
               "macro": {"oil_day": 5.2, "fx_day": 1.1, "fx_level": 1505.4}}
    a = build_assessment(facts, SectorStore(tmp_path), stock30)
    note = a["stock_move"]["macro_note"]
    assert "유가" in note and "원달러" in note and "1,505" in note

    calm = dict(stock30, macro={"oil_day": 0.2, "fx_day": 0.1, "fx_level": 1400.0})
    a2 = build_assessment(facts, SectorStore(tmp_path), calm)
    assert a2["stock_move"]["macro_note"] == ""             # 거시 평온하면 침묵
