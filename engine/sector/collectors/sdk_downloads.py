"""수집기 — sdk_downloads (지표: sdk_downloads)."""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "sdk_downloads"
KIND = "metric"
_PYPI_PKGS = ["openai", "anthropic"]
_NPM_PKGS = ["openai", "@anthropic-ai/sdk"]


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    obs: list[MetricObservation] = []
    notes: list[str] = []
    status = "ok"
    ts = _dt.date.today().isoformat()
    try:
        for pkg in _PYPI_PKGS:
            try:
                resp = await client.get(f"https://pypistats.org/api/packages/{pkg}/recent")
                resp.raise_for_status()
                data = resp.json().get("data") or {}
                downloads = data.get("last_week")
                if downloads is not None:
                    obs.append(MetricObservation(
                        metric="sdk_downloads", ts=ts,
                        value=float(downloads), unit="downloads",
                        meta={"pkg": pkg, "ecosystem": "pypi"}))
            except Exception as e:  # noqa: BLE001
                notes.append(f"pypi:{pkg}:error={e}")
                status = "degraded"

        for pkg in _NPM_PKGS:
            try:
                resp = await client.get(
                    f"https://api.npmjs.org/downloads/point/last-week/{pkg}")
                resp.raise_for_status()
                downloads = resp.json().get("downloads")
                if downloads is not None:
                    obs.append(MetricObservation(
                        metric="sdk_downloads", ts=ts,
                        value=float(downloads), unit="downloads",
                        meta={"pkg": pkg, "ecosystem": "npm"}))
            except Exception as e:  # noqa: BLE001
                notes.append(f"npm:{pkg}:error={e}")
                status = "degraded"

        return CollectorResult(name=NAME, kind=KIND, observations=obs,
                               status=status, detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
