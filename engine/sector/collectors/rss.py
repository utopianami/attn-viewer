"""수집기 스텁 — rss (뉴스)."""
from __future__ import annotations

import httpx

from sector.contracts import CollectorResult
from sector.store import SectorStore

NAME = "rss"
KIND = "news"


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    return CollectorResult(name=NAME, kind=KIND, status="degraded", detail="not implemented")
