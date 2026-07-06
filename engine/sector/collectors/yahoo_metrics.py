"""수집기 스텁 — yahoo_metrics (지표)."""
from __future__ import annotations

import httpx

from sector.contracts import CollectorResult
from sector.store import SectorStore

NAME = "yahoo_metrics"
KIND = "metric"


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    return CollectorResult(name=NAME, kind=KIND, status="degraded", detail="not implemented")
