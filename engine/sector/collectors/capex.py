"""수집기 — capex (하이퍼스케일러 분기 설비투자 실적, 2026-07-08 실측 무인증).

GET query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}
    ?type=quarterlyCapitalExpenditure — 크럼 불필요 확인.
캘린더 분기가 맞는 4사만(MSFT·GOOGL·AMZN·META — 오라클은 5월 결산이라 제외).
값은 현금유출(음수) → 절대값 B USD. 사슬 「서버·투자」 단계의 capex 실적 축.
"""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "capex"
KIND = "metric"
_TOKENS = ["MSFT", "GOOGL", "AMZN", "META"]
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
    try:
        for sym in _TOKENS:
            try:
                r = await client.get(_URL.format(sym=sym), params={
                    "type": "quarterlyCapitalExpenditure", "period1": p1, "period2": p2})
                r.raise_for_status()
                res = (r.json().get("timeseries") or {}).get("result") or []
                rows = (res[0].get("quarterlyCapitalExpenditure") or []) if res else []
                for v in rows:
                    if not v or "reportedValue" not in v:
                        continue
                    obs.append(MetricObservation(
                        metric="hyperscaler_capex", ts=(v.get("asOfDate") or "")[:7],
                        value=round(abs(v["reportedValue"]["raw"]) / 1e9, 2), unit="b_usd",
                        meta={"token": sym, "item": sym}))
            except Exception:  # noqa: BLE001 — 종목 격리
                fails.append(sym)
        status = "ok" if not fails else ("degraded" if obs else "degraded")
        return CollectorResult(name=NAME, kind=KIND, observations=obs, status=status,
                               detail="" if not fails else "fail=" + ",".join(fails))
    finally:
        if own:
            await client.aclose()
