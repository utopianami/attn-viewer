"""수집기 — datalab (지표: search_interest_kr, 네이버 데이터랩 AI 앱 검색량)."""
from __future__ import annotations

import datetime as _dt

import httpx

from app.settings import settings
from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "datalab"
KIND = "metric"
_URL = "https://openapi.naver.com/v1/datalab/search"
_GROUPS = [
    {"groupName": "chatgpt", "keywords": ["챗지피티", "ChatGPT"]},
    {"groupName": "claude", "keywords": ["클로드 AI", "Claude"]},
    {"groupName": "gemini", "keywords": ["제미나이", "Gemini"]},
]


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    cid, secret = settings.naver_client_id, settings.naver_client_secret
    if not cid or not secret:
        missing = [n for n, v in (("naver_client_id", cid), ("naver_client_secret", secret)) if not v]
        return CollectorResult(name=NAME, kind=KIND, status="missing_key",
                               detail=f"{'/'.join(missing)} 미설정 — 네이버 데이터랩 생략")
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        today = _dt.date.today()
        body = {"startDate": (today - _dt.timedelta(days=90)).isoformat(),
                "endDate": today.isoformat(), "timeUnit": "week",
                "keywordGroups": _GROUPS}
        headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret}
        try:
            resp = await client.post(_URL, json=body, headers=headers)
            if resp.status_code != 200:
                return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                       detail=f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return CollectorResult(name=NAME, kind=KIND, status="degraded", detail=str(e)[:300])

        obs: list[MetricObservation] = []
        results = data.get("results") if isinstance(data, dict) else None
        for g in results or []:
            if not isinstance(g, dict):
                continue
            app = str(g.get("title") or g.get("groupName") or "")
            for point in g.get("data") or []:
                try:
                    obs.append(MetricObservation(
                        metric="search_interest_kr", ts=str(point["period"]),
                        value=float(point["ratio"]), meta={"app": app}))
                except (KeyError, TypeError, ValueError):
                    continue
        if not obs:
            keys = list(data)[:8] if isinstance(data, dict) else type(data).__name__
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail=f"results 데이터 없음 — top-level: {keys}"[:300])
        return CollectorResult(name=NAME, kind=KIND, observations=obs)
    finally:
        if own:
            await client.aclose()
