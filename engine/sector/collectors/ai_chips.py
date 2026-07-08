"""수집기 — ai_chips (수요 상류: GPU/ASIC 3사 분기 매출, yahoo 무인증).

NVDA(GPU)·AMD(Instinct)·AVGO(custom ASIC/TPU) 분기 총매출 — 데이터센터 세그먼트
매출의 무료 프록시 (세그먼트 분해는 공시에만 있음. NVDA는 총매출의 ~9할이 DC라
방향 신호로 충분). "HBM 수요가 특정 체인에 쏠렸는지" 판별용 (브리프 §수요).
Oracle RPO·CoreWeave backlog는 무료 API가 없어 뉴스 카드·공시 경로가 커버.
"""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "ai_chips"
KIND = "metric"
_TOKENS = ["NVDA", "AMD", "AVGO"]
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
                    "type": "quarterlyTotalRevenue", "period1": p1, "period2": p2})
                r.raise_for_status()
                res = (r.json().get("timeseries") or {}).get("result") or []
                rows = (res[0].get("quarterlyTotalRevenue") or []) if res else []
                for v in rows:
                    if not v or "reportedValue" not in v:
                        continue
                    obs.append(MetricObservation(
                        metric="ai_chip_revenue", ts=(v.get("asOfDate") or "")[:7],
                        value=round(abs(v["reportedValue"]["raw"]) / 1e9, 2), unit="b_usd",
                        meta={"token": sym, "item": sym}))
            except Exception:  # noqa: BLE001 — 종목 격리
                fails.append(sym)
        status = "ok" if not fails else "degraded"
        return CollectorResult(name=NAME, kind=KIND, observations=obs, status=status,
                               detail="" if not fails else "fail=" + ",".join(fails))
    finally:
        if own:
            await client.aclose()
