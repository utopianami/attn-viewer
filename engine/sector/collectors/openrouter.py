"""수집기 — openrouter (지표: token_price, openrouter_daily_tokens)."""
from __future__ import annotations

import datetime as _dt

import httpx

from app.settings import settings
from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "openrouter"
KIND = "metric"
_BASE = "https://openrouter.ai/api/v1"
_TRACK = ("openai/gpt-5", "anthropic/claude", "google/gemini", "x-ai/grok", "deepseek/", "moonshotai/")


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    obs: list[MetricObservation] = []
    notes: list[str] = []
    status = "ok"
    ts = _dt.date.today().isoformat()
    try:
        # 1. /models — no key required
        try:
            resp = await client.get(f"{_BASE}/models")
            resp.raise_for_status()
            data = resp.json().get("data") or []
            for m in data:
                mid = m.get("id") or ""
                if not any(mid.startswith(p) for p in _TRACK):
                    continue
                pricing = m.get("pricing") or {}
                try:
                    prompt_per_1m = float(pricing.get("prompt") or 0) * 1e6
                    completion_per_1m = float(pricing.get("completion") or 0) * 1e6
                except (TypeError, ValueError):
                    continue
                obs.append(MetricObservation(
                    metric="token_price", ts=ts, value=completion_per_1m,
                    unit="usd_per_1m",
                    meta={"model": mid, "prompt": prompt_per_1m, "completion": completion_per_1m}))
        except Exception as e:  # noqa: BLE001
            notes.append(f"models:error={e}")
            status = "degraded"

        # 2. /datasets/rankings-daily — key needed
        if settings.openrouter_api_key:
            try:
                r = await client.get(
                    f"{_BASE}/datasets/rankings-daily",
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})
                if r.status_code in (401, 403, 404):
                    notes.append(f"rankings:http_{r.status_code}")
                    status = "degraded"
                elif r.status_code == 200:
                    rows = r.json().get("data") or []
                    ok = False
                    for row in rows:
                        model_id = row.get("model") or row.get("model_permaslug") or ""
                        tokens = row.get("total_tokens") or row.get("tokens")
                        date = (row.get("date") or "")[:10]
                        if model_id and tokens is not None and date:
                            try:
                                obs.append(MetricObservation(
                                    metric="openrouter_daily_tokens", ts=date,
                                    value=float(tokens), unit="tokens",
                                    meta={"model": model_id}))
                                ok = True
                            except (TypeError, ValueError):
                                pass
                    if not ok:
                        notes.append("rankings:schema_unknown")
                        status = "degraded"
                else:
                    notes.append(f"rankings:http_{r.status_code}")
                    status = "degraded"
            except Exception as e:  # noqa: BLE001
                notes.append(f"rankings:error={e}")
                status = "degraded"
        else:
            notes.append("rankings: missing_key")

        return CollectorResult(name=NAME, kind=KIND, observations=obs,
                               status=status, detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
