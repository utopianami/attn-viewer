"""수집기 — kosis (지표: kr_semi_production_index, 반도체 생산·출하·재고지수)."""
from __future__ import annotations

import httpx

from app.settings import settings
from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "kosis"
KIND = "metric"
_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
_KEYWORDS = ("반도체", "재고", "출하", "생산")


def _yyyymm(raw: str) -> str:
    """"202606" → "2026-06"."""
    s = str(raw).strip()
    return f"{s[:4]}-{s[4:6]}"


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    key = settings.kosis_api_key
    if not key:
        return CollectorResult(name=NAME, kind=KIND, status="missing_key",
                               detail="kosis_api_key 미설정 — KOSIS 생산·출하·재고지수 생략")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        params = {"method": "getList", "apiKey": key, "orgId": "101",
                  "tblId": "DT_1JH20151", "format": "json", "jsonVD": "Y",
                  "prdSe": "M", "newEstPrdCnt": "12", "objL1": "ALL"}
        try:
            resp = await client.get(_URL, params=params)
            if resp.status_code != 200:
                return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                       detail=f"HTTP {resp.status_code}")
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return CollectorResult(name=NAME, kind=KIND, status="degraded", detail=str(e)[:300])

        if not isinstance(data, list):
            keys = list(data)[:8] if isinstance(data, dict) else type(data).__name__
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail=f"예상 밖 응답 형태 — top-level: {keys}"[:300])
        obs: list[MetricObservation] = []
        for row in data:
            if not isinstance(row, dict) or not row.get("PRD_DE") or row.get("DT") in (None, ""):
                continue
            c1, itm = str(row.get("C1_NM") or ""), str(row.get("ITM_NM") or "")
            if not any(k in c1 or k in itm for k in _KEYWORDS):
                continue
            try:
                obs.append(MetricObservation(
                    metric="kr_semi_production_index", ts=_yyyymm(row["PRD_DE"]),
                    value=float(row["DT"]), unit="index",
                    meta={"item": itm or c1}))
            except (TypeError, ValueError):
                continue
        if not obs:
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail="리스트 응답이나 매칭 행 없음 (반도체/재고/출하/생산)")
        return CollectorResult(name=NAME, kind=KIND, observations=obs)
    finally:
        if own:
            await client.aclose()
