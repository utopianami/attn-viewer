"""수집기 — yahoo_metrics (지표: stock_price, 밸류체인 주가 스냅샷).

tools.price.yahoo.quote 재사용 (원칙: 시세는 야후 종가만, 검색 요약 금지).
"""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore
from tools.price.yahoo import quote

NAME = "yahoo_metrics"
KIND = "metric"
_TICKERS = ["005930.KS", "000660.KS", "MU", "TSM", "NVDA", "^SOX",
            "MSFT", "GOOGL", "AMZN", "META", "AAPL", "ORCL"]


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    rows = await quote(_TICKERS, client=client)
    ts = _dt.date.today().isoformat()
    obs: list[MetricObservation] = []
    errors: list[str] = []
    for row in rows:
        if row.get("error"):
            errors.append(f"{row.get('token')}: {row['error']}")
            continue
        try:
            # quote()의 cur는 통화 코드, 가격은 last — cur가 숫자(현재가)인 변형 구현도 수용
            try:
                value = float(row["cur"])
            except (KeyError, TypeError, ValueError):
                value = float(row["last"])
            obs.append(MetricObservation(
                metric="stock_price", ts=ts, value=value, unit=str(row.get("cur") or ""),
                meta={"token": row.get("token"), "day_pct": row.get("day_pct")}))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{row.get('token')}: {e}")
    status = "degraded" if not obs else "ok"
    detail = f"errors: {'; '.join(errors)}"[:300] if errors else ""
    return CollectorResult(name=NAME, kind=KIND, observations=obs, status=status, detail=detail)
