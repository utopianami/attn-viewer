"""수집기 — status_pages (지표: ai_status_incidents)."""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "status_pages"
KIND = "metric"
_PROVIDERS = [
    ("openai", "https://status.openai.com/api/v2/summary.json"),
    # status.anthropic.com → status.claude.com 302 이전 (2026-07-06 라이브 확인)
    ("anthropic", "https://status.claude.com/api/v2/summary.json"),
]


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    obs: list[MetricObservation] = []
    notes: list[str] = []
    status = "ok"
    ts = _dt.date.today().isoformat()
    try:
        for provider, url in _PROVIDERS:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                incidents = resp.json().get("incidents") or []
                names = [inc.get("name") or "" for inc in incidents]
                obs.append(MetricObservation(
                    metric="ai_status_incidents", ts=ts,
                    value=float(len(incidents)), unit="count",
                    meta={"provider": provider, "ongoing": names}))
            except Exception as e:  # noqa: BLE001
                notes.append(f"{provider}:error={e}")
                status = "degraded"
        return CollectorResult(name=NAME, kind=KIND, observations=obs,
                               status=status, detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
