"""수집기 — customs_kr (지표: kr_semi_export, 관세청 반도체 HS8542 수출).

응답 스키마 미확정(키 발급 후 아침 트리거에서 실측 확정) → 방어 파싱:
정상 형태가 아니면 무엇이 왔는지 detail에 남기고 degraded.
"""
from __future__ import annotations

import datetime as _dt

import httpx

from app.settings import settings
from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "customs_kr"
KIND = "metric"
_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
_EXPORT_KEYS = ("expDlr", "expUsdAmt", "expAmt")  # 수출금액 후보 필드


def _months_ago(d: _dt.date, n: int) -> str:
    y, m = d.year, d.month - n
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y}{m:02d}"


def _parse_ts(raw: str) -> str | None:
    """"2026.05" 또는 "202605" → "2026-05". 총계 등 비월(非月) 행은 None."""
    s = str(raw).strip().replace(".", "")
    if len(s) == 6 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}"
    return None


def _extract_items(data) -> list[dict]:
    if not isinstance(data, dict):
        return []
    body = (data.get("response") or {}).get("body") or {}
    items = body.get("items")
    if isinstance(items, dict):
        items = items.get("item")
    if isinstance(items, dict):
        items = [items]
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    key = settings.data_go_kr_api_key
    if not key:
        return CollectorResult(name=NAME, kind=KIND, status="missing_key",
                               detail="data_go_kr_api_key 미설정 — 관세청 수출입 통계 생략")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        today = _dt.date.today()
        params = {"serviceKey": key, "strtYymm": _months_ago(today, 3),
                  "endYymm": today.strftime("%Y%m"), "hsSgn": "8542", "type": "json"}
        try:
            resp = await client.get(_URL, params=params)
            if resp.status_code != 200:
                return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                       detail=f"HTTP {resp.status_code}")
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return CollectorResult(name=NAME, kind=KIND, status="degraded", detail=str(e)[:300])

        obs: list[MetricObservation] = []
        for it in _extract_items(data):
            ts = _parse_ts(it.get("year") or it.get("prdYymm") or "")
            if not ts:
                continue
            for k in _EXPORT_KEYS:
                if it.get(k) not in (None, ""):
                    try:
                        obs.append(MetricObservation(
                            metric="kr_semi_export", ts=ts, value=float(it[k]), unit="USD",
                            meta={"item": "semiconductor_hs8542"}))
                    except (TypeError, ValueError):
                        pass
                    break
        if not obs:
            keys = list(data)[:8] if isinstance(data, dict) else type(data).__name__
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail=f"예상 밖 응답 형태 — top-level: {keys}"[:300])
        return CollectorResult(name=NAME, kind=KIND, observations=obs)
    finally:
        if own:
            await client.aclose()
