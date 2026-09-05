"""수집기 — mops_tw (지표: tw_monthly_revenue, 대만 상장사 월별 매출 공시)."""
from __future__ import annotations

import csv
import io
from types import MappingProxyType

import httpx

from sector.collectors._util import num as _num
from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "mops_tw"
KIND = "metric"
_URL = "https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv"
# 추적 대상 — MOPS가 실제 제공하는 bare code를 리포트 종목 검증과 공유한다.
# 거래소 suffix는 원문에 없으므로 여기서 추론하거나 덧붙이지 않는다.
TRACKED_COMPANIES = MappingProxyType({
    "2330": "TSMC",
    "2382": "Quanta",
    "3231": "Wistron",
    "2356": "Inventec",
    "6669": "Wiwynn",
    "2317": "HonHai",
})


def _roc_to_iso_month(raw: str) -> str:
    """민국력 "11506" 또는 "115/06" → "2026-06" (년+1911)."""
    s = raw.strip().replace("/", "")
    return f"{int(s[:-2]) + 1911:04d}-{int(s[-2:]):02d}"


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        try:
            resp = await client.get(_URL)
            resp.raise_for_status()
            text = resp.content.decode("utf-8-sig")
        except Exception as e:  # noqa: BLE001
            return CollectorResult(name=NAME, kind=KIND, status="error", detail=str(e)[:300])
        obs: list[MetricObservation] = []
        notes: list[str] = []
        for row in csv.DictReader(io.StringIO(text)):
            code = (row.get("公司代號") or "").strip()
            if code not in TRACKED_COMPANIES:
                continue
            try:
                value = _num(row.get("營業收入-當月營收"))
                if value is None:
                    raise ValueError("당월매출 파싱 불가")
                obs.append(MetricObservation(
                    metric="tw_monthly_revenue",
                    ts=_roc_to_iso_month(row.get("資料年月") or ""),
                    value=value, unit="kTWD",
                    meta={"code": code, "name": TRACKED_COMPANIES[code],
                          "yoy": _num(row.get("營業收入-去年同月增減(%)")) or 0.0,
                          "mom": _num(row.get("營業收入-上月比較增減(%)")) or 0.0}))
            except Exception as e:  # noqa: BLE001
                notes.append(f"{code}:{e}")
        status = "ok" if obs else "degraded"
        if not obs and not notes:
            notes.append("추적 종목 행 없음")
        return CollectorResult(name=NAME, kind=KIND, observations=obs,
                               status=status, detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
