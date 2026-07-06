"""수집기 — stanford_dam (지표: memory_price_usd_per_gb, Stanford DAM 무키 메모리 가격)."""
from __future__ import annotations

import csv
import io

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore

NAME = "stanford_dam"
KIND = "metric"
_URL = "https://dam.stanford.edu/assets/memory-prices/memory-prices.csv"
_UA = "attn-viewer/sector-collector (+https://github.com/ryze_yn/attn-viewer)"
_CUTOFF = "2023-01-01"


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, headers={"User-Agent": _UA})
    try:
        try:
            resp = await client.get(_URL, headers={"User-Agent": _UA})
            resp.raise_for_status()
            text = resp.text
        except Exception as e:  # noqa: BLE001
            return CollectorResult(name=NAME, kind=KIND, status="degraded", detail=str(e)[:300])

        obs: list[MetricObservation] = []
        notes: list[str] = []
        try:
            for row in csv.DictReader(io.StringIO(text)):
                date = (row.get("date") or "").strip()
                if not date or date < _CUTOFF:
                    continue
                category = (row.get("category") or "").strip()
                series = (row.get("series") or "").strip()
                unit = (row.get("unit") or "").strip()
                try:
                    value = float(row.get("value") or "")
                except (ValueError, TypeError):
                    notes.append(f"skip:{date}:{category}:value parse error")
                    continue
                obs.append(MetricObservation(
                    metric="memory_price_usd_per_gb",
                    ts=date[:7],
                    value=value,
                    unit=unit,
                    meta={"item": f"{category}|{series}", "category": category},
                ))
        except Exception as e:  # noqa: BLE001
            return CollectorResult(name=NAME, kind=KIND, status="degraded",
                                   detail=f"parse error: {e!s}"[:300])

        status = "ok" if obs else "degraded"
        if not obs and not notes:
            notes.append("2023-01-01 이후 행 없음")
        return CollectorResult(name=NAME, kind=KIND, observations=obs,
                               status=status, detail="; ".join(notes)[:300])
    finally:
        if own:
            await client.aclose()
