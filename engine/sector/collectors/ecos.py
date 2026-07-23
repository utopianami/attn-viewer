"""수집기 — ecos (지표: kr_dram_export_price_index, 한국은행 D램 수출물가지수).

통계코드 402Y014는 후보 — 키 발급 후 아침 트리거에서 실측 확정 대상.
"""
from __future__ import annotations

import datetime as _dt

import httpx

from app.settings import settings
from sector.collectors._util import months_ago as _months_ago
from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "ecos"
KIND = "metric"
_BASE = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100/402Y014/M/{start}/{end}"


def _yyyymm(raw: str) -> str:
    """"202606" → "2026-06"."""
    s = str(raw).strip()
    return f"{s[:4]}-{s[4:6]}"


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    key = settings.ecos_api_key
    if not key:
        return CollectorResult(name=NAME, kind=KIND, status="missing_key",
                               detail="ecos_api_key 미설정 — 한국은행 ECOS D램 수출물가지수 생략")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        today = _dt.date.today()
        url = _BASE.format(key=key, start=_months_ago(today, 12), end=today.strftime("%Y%m"))
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                       detail=f"HTTP {resp.status_code}")
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return CollectorResult(name=NAME, kind=KIND, status="degraded", detail=str(e)[:300])

        rows = (data.get("StatisticSearch") or {}).get("row") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            res = data.get("RESULT") if isinstance(data, dict) else None
            if isinstance(res, dict):
                detail = f"RESULT {res.get('CODE')}: {res.get('MESSAGE')}"
            else:
                detail = ("예상 밖 응답 형태 — top-level: "
                          f"{list(data)[:8] if isinstance(data, dict) else type(data).__name__}")
            return CollectorResult(name=NAME, kind=KIND, status="degraded", detail=detail[:300])

        obs: list[MetricObservation] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = str(row.get("ITEM_NAME1") or "")
            if "D램" not in item and "반도체" not in item:
                continue
            try:
                obs.append(MetricObservation(
                    metric="kr_dram_export_price_index", ts=_yyyymm(row["TIME"]),
                    value=float(row["DATA_VALUE"]), unit="index",
                    meta={"item": item}))
            except (KeyError, TypeError, ValueError):
                continue
        if not obs:
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail="row 응답이나 D램/반도체 매칭 행 없음")
        return CollectorResult(name=NAME, kind=KIND, observations=obs)
    finally:
        if own:
            await client.aclose()
