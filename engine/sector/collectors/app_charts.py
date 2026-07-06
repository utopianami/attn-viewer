"""수집기 — app_charts (지표: app_rank)."""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "app_charts"
KIND = "metric"
_COUNTRIES = ["us", "kr"]
_APPS = ["ChatGPT", "Gemini", "Claude", "Copilot"]


def _match_app(name: str) -> str | None:
    low = name.lower()
    for app in _APPS:
        if app.lower() in low:
            return app
    return None


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    obs: list[MetricObservation] = []
    notes: list[str] = []
    status = "ok"
    ts = _dt.date.today().isoformat()
    try:
        for country in _COUNTRIES:
            try:
                url = (f"https://rss.applemarketingtools.com/api/v2/{country}"
                       f"/apps/top-free/100/apps.json")
                resp = await client.get(url)
                resp.raise_for_status()
                results = (resp.json().get("feed") or {}).get("results") or []
                for idx, item in enumerate(results, start=1):
                    name = item.get("name") or ""
                    matched = _match_app(name)
                    if matched:
                        obs.append(MetricObservation(
                            metric="app_rank", ts=ts,
                            value=float(idx), unit="rank",
                            meta={"app": matched, "country": country}))
            except Exception as e:  # noqa: BLE001
                notes.append(f"{country}:error={e}")
                status = "degraded"
        return CollectorResult(name=NAME, kind=KIND, observations=obs,
                               status=status, detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
