"""Tavily 검색 — 뉴스/웹 폴백 체인의 마지막 단 (dev 키, 무료 1K 크레딧/월).

폴백 순서상 Brave 우선 (Brave 유료 계정) — 여기는 Brave 실패/부족 시만.
"""

from __future__ import annotations

import httpx

from app.settings import settings

_URL = "https://api.tavily.com/search"


async def tavily_search(query: str, *, count: int = 5, topic: str = "general",
                        days: int | None = None,
                        client: httpx.AsyncClient | None = None) -> list[dict]:
    """Tavily 검색. 반환: [{title, url, description, age, source}] (brave와 동일 shape)."""
    if not settings.tavily_api_key:
        return []
    body: dict = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": count,
        "search_depth": "basic",
        "topic": topic,          # "news" | "general"
        "include_answer": False,
    }
    if days and topic == "news":
        body["days"] = days

    async def _post(hc: httpx.AsyncClient) -> list[dict]:
        r = await hc.post(_URL, json=body)
        r.raise_for_status()
        out = []
        for it in r.json().get("results", []):
            out.append({
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "description": (it.get("content") or "")[:400],
                "age": it.get("published_date", "") or "",
                "source": "tavily",
            })
        return out

    if client is not None:
        return await _post(client)
    async with httpx.AsyncClient(timeout=15) as hc:
        return await _post(hc)
