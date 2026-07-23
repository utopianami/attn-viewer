"""수집기 — customs_kr (관세청 수출 주요품목별 10일 단위 잠정치, data.go.kr 15157908).

2026-07-07 실측 확정 스펙 (당초 추정 nitemtrade는 다른 API였음 — 403):
- GET https://apis.data.go.kr/1220000/prlstMmUtPrviExpAcrs/getPrlstMmUtPrviExpAcrs
- params: serviceKey, strtYymm, endYymm — XML 응답
- item 행: priodMon("202605"), priodDt("01~10"|"01~20"|"01~31"...),
  itemUsdAmt00=전체, itemUsdAmt01=반도체 (천 USD, 콤마·공백 포함 문자열)

지표:
- kr_semi_export        : 반도체 수출액 (meta.item = 집계구간 "01~10" 등)
- kr_semi_export_share  : 반도체/전체 비중 % (계획 §2-3 파생 — 사이클 위치)
사이클 demand 요소는 월간 비교가 가능하도록 meta.item=="01~10" 행을 우선 사용 (cycle.py).
"""
from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET

import httpx

from app.settings import settings
from sector.collectors._util import months_ago as _months_ago, num as _num
from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "customs_kr"
KIND = "metric"
_URL = ("https://apis.data.go.kr/1220000/prlstMmUtPrviExpAcrs"
        "/getPrlstMmUtPrviExpAcrs")


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    if not settings.data_go_kr_api_key:
        return CollectorResult(name=NAME, kind=KIND, status="missing_key",
                               detail="data_go_kr_api_key 미설정 — 관세청 수출입 통계 생략")
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    obs: list[MetricObservation] = []
    try:
        today = _dt.date.today()
        resp = await client.get(_URL, params={
            "serviceKey": settings.data_go_kr_api_key,
            "strtYymm": _months_ago(today, 3), "endYymm": _months_ago(today, 0)})
        if resp.status_code != 200:
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail=f"HTTP {resp.status_code}")
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail=f"XML parse: {exc}"[:200])
        code = (root.findtext(".//resultCode") or "").strip()
        if code not in ("00", "0", ""):
            msg = (root.findtext(".//resultMsg") or "").strip()
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail=f"resultCode={code} {msg}"[:200])
        for item in root.iter("item"):
            mon = (item.findtext("priodMon") or "").strip()      # "202605"
            period = (item.findtext("priodDt") or "").strip()    # "01~10"
            total = _num(item.findtext("itemUsdAmt00"))
            semi = _num(item.findtext("itemUsdAmt01"))
            if len(mon) != 6 or not mon.isdigit() or semi is None:
                continue
            ts = f"{mon[:4]}-{mon[4:]}"
            obs.append(MetricObservation(
                metric="kr_semi_export", ts=ts, value=semi, unit="k_usd",
                meta={"item": period, "provider": "customs"},
                source="관세청 수출입무역통계"))
            if total:
                obs.append(MetricObservation(
                    metric="kr_semi_export_share", ts=ts,
                    value=round(semi / total * 100, 2), unit="pct",
                    meta={"item": period, "provider": "customs"},
                    source="관세청 수출입무역통계"))
        status = "ok" if obs else "degraded"
        return CollectorResult(name=NAME, kind=KIND, observations=obs, status=status,
                               detail="" if obs else "item 행 없음")
    finally:
        if own:
            await client.aclose()
