"""주가 시계열 — 대시보드 스파크라인용 (P2 지원, 2026-07-07).

기존 tools.price.yahoo._fetch 재사용. 저장하지 않고 온디맨드 + api.py에서 1시간 캐시
(일봉이라 충분). 종목별 실패 격리 — 죽은 종목은 error 필드로.
"""
from __future__ import annotations

import datetime as _dt

import httpx

from tools.price.yahoo import _UA, _fetch

TICKERS: list[tuple[str, str]] = [
    ("005930.KS", "삼성전자"), ("000660.KS", "SK하이닉스"), ("MU", "마이크론"),
    ("TSM", "TSMC"), ("NVDA", "엔비디아"), ("^SOX", "SOX"),
    ("SKHY", "하이닉스 ADR"),   # 2026-07-10 나스닥 상장 (ADR 10 = 원주 1) — 미국장 시세
]


async def price_series(days: int = 90, client: httpx.AsyncClient | None = None) -> dict:
    now = _dt.datetime.now()
    p1 = int((now - _dt.timedelta(days=days)).timestamp())
    p2 = int(now.timestamp()) + 86400
    own = client is None
    client = client or httpx.AsyncClient(headers=_UA, timeout=25, verify=False)
    series = []
    try:
        for sym, name in TICKERS:
            try:
                pairs, _meta = await _fetch(client, sym, p1, p2)
            except Exception as exc:  # noqa: BLE001 — 종목 격리
                series.append({"token": sym, "name": name, "error": str(exc)[:120]})
                continue
            points = [[_dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d"), round(c, 2)]
                      for t, c in pairs]
            last = points[-1][1] if points else None
            prev = points[-2][1] if len(points) > 1 else None
            day_pct = round((last / prev - 1) * 100, 2) if last and prev else None
            series.append({"token": sym, "name": name, "points": points,
                           "last": last, "day_pct": day_pct})
        return {"series": series, "as_of": now.isoformat(timespec="minutes")}
    finally:
        if own:
            await client.aclose()
