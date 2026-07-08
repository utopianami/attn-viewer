"""수집기 — supply (공급 축: 메모리 3사 분기 capex + 장비 4사 분기 매출).

capex.py와 같은 yahoo fundamentals-timeseries 무인증 엔드포인트.
통화가 제각각(원·달러·유로)이라 절대값 합산은 금지 — supply_risk가 회사별 QoQ만 쓴다.
장비 수주(bookings)는 공개 API가 없어 분기 매출을 프록시로 사용.
"""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "supply"
KIND = "metric"
_MEMORY = ["005930.KS", "000660.KS", "MU"]        # 삼전·하이닉스·마이크론 — 증설 의지
_EQUIP = ["ASML", "AMAT", "LRCX", "KLAC"]         # 장비 4사 — 증설 실행(수주 프록시)
_URL = ("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance"
        "/timeseries/{sym}")
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=20, headers=_UA)
    obs: list[MetricObservation] = []
    fails: list[str] = []
    now = _dt.datetime.now()
    p1 = int((now - _dt.timedelta(days=800)).timestamp())
    p2 = int(now.timestamp())

    async def fetch(sym: str, typ: str, metric: str) -> None:
        r = await client.get(_URL.format(sym=sym), params={
            "type": typ, "period1": p1, "period2": p2})
        r.raise_for_status()
        res = (r.json().get("timeseries") or {}).get("result") or []
        rows = (res[0].get(typ) or []) if res else []
        for v in rows:
            if not v or "reportedValue" not in v:
                continue
            obs.append(MetricObservation(
                metric=metric, ts=(v.get("asOfDate") or "")[:7],
                value=round(abs(v["reportedValue"]["raw"]) / 1e9, 2), unit="b_local",
                meta={"token": sym, "item": sym}))

    try:
        for sym in _MEMORY:
            try:
                await fetch(sym, "quarterlyCapitalExpenditure", "memory_capex")
            except Exception:  # noqa: BLE001 — 종목 격리
                fails.append(sym)
        for sym in _EQUIP:
            try:
                await fetch(sym, "quarterlyTotalRevenue", "equip_revenue")
            except Exception:  # noqa: BLE001
                fails.append(sym)
        status = "ok" if not fails else "degraded"
        return CollectorResult(name=NAME, kind=KIND, observations=obs, status=status,
                               detail="" if not fails else "fail=" + ",".join(fails))
    finally:
        if own:
            await client.aclose()
