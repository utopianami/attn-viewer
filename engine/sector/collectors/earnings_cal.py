"""수집기 — earnings_cal (나스닥 실적 캘린더, 2026-07-07 실측 무인증).

GET https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
→ {"data":{"rows":[{"symbol","name","time",...}]}} — 해당일 발표 전 종목.
향후 21일(주말 제외) 순회하며 감시 종목만 저장. 실패일은 건너뜀 (never-block).
한계: 미국 상장분만 — 삼전·하이닉스 국내 실적일은 미포함 (하이닉스 ADR 상장 후 재검).
"""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "earnings_cal"
KIND = "metric"
_URL = "https://api.nasdaq.com/api/calendar/earnings"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json"}
# GOOG(클래스 C)은 GOOGL과 같은 회사·같은 실적 발표라 제외 (중복 이벤트 방지)
_WATCH = {"MU", "NVDA", "TSM", "MSFT", "GOOGL", "AMZN", "META", "AAPL",
          "ORCL", "AMD", "ASML", "AVGO", "SMCI", "DELL", "WDC", "STX", "QCOM"}
_DAYS_AHEAD = 21

# 삼전·하이닉스는 미국 상장이 없어 나스닥 캘린더에 안 잡힘 → 발표 관례로 '예상' 생성.
# DART 기업설명회(IR) 공시가 잡히면 confirmed로 승격 (dart_edgar 쪽).
_KR_RULES = [("삼성전자", "잠정실적", 7),        # 분기 종료 후 첫 주
             ("SK하이닉스", "실적발표·콜", 24),   # 분기 종료 월 하순
             ("삼성전자", "확정실적·콜", 29)]


def kr_earnings_estimates(today: _dt.date, days_ahead: int = _DAYS_AHEAD) -> list[MetricObservation]:
    """관례 기반 국내 실적일 '예상' — 오늘~창 안만, 주말은 다음 평일로 민다."""
    out: list[MetricObservation] = []
    end = today + _dt.timedelta(days=days_ahead)
    for year in (today.year, today.year + 1):
        for month in (1, 4, 7, 10):
            for corp, event, day in _KR_RULES:
                d = _dt.date(year, month, day)
                while d.weekday() >= 5:
                    d += _dt.timedelta(days=1)
                if today <= d <= end:
                    out.append(MetricObservation(
                        metric="earnings_calendar", ts=d.isoformat(), value=1.0,
                        unit="event",
                        meta={"item": corp, "name": corp, "event": event,
                              "kind": "est", "provider": "rule", "time": ""}))
    return out


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers=_HEADERS)
    obs: list[MetricObservation] = []
    fails = 0
    try:
        today = _dt.date.today()
        for d in range(_DAYS_AHEAD):
            day = today + _dt.timedelta(days=d)
            if day.weekday() >= 5:      # 주말 제외
                continue
            try:
                resp = await client.get(_URL, params={"date": day.isoformat()})
                resp.raise_for_status()
                rows = ((resp.json().get("data") or {}).get("rows")) or []
            except Exception:  # noqa: BLE001 — 일자별 격리
                fails += 1
                continue
            for row in rows:
                sym = (row.get("symbol") or "").strip().upper()
                if sym not in _WATCH:
                    continue
                obs.append(MetricObservation(
                    metric="earnings_calendar", ts=day.isoformat(), value=1.0,
                    unit="event",
                    meta={"item": sym, "name": (row.get("name") or "")[:60],
                          "time": row.get("time") or "", "provider": "nasdaq"}))
        obs.extend(kr_earnings_estimates(today))
        status = "ok" if fails == 0 else ("degraded" if obs or fails < _DAYS_AHEAD else "degraded")
        return CollectorResult(name=NAME, kind=KIND, observations=obs, status=status,
                               detail="" if fails == 0 else f"day_fail={fails}")
    finally:
        if own:
            await client.aclose()
