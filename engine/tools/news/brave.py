"""Brave 검색 — 뉴스(유닛별 최신 기사) + 웹(배경지식 web_knowledge)."""

from __future__ import annotations

import httpx

from app.settings import settings

_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
_WEB_URL = "https://api.search.brave.com/res/v1/web/search"


async def news_search(query: str, *, count: int = 6, freshness: str = "pd",
                      country: str = "kr", search_lang: str = "ko",
                      client: httpx.AsyncClient | None = None) -> list[dict]:
    """뉴스 검색. freshness: pd(하루)|pw(주)|pm(월). 실패 시 빈 리스트 (never-raise는 호출자)."""
    if not settings.brave_api_key:
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(
            _NEWS_URL,
            params={"q": query, "country": country, "search_lang": search_lang,
                    "freshness": freshness, "count": count},
            headers={"X-Subscription-Token": settings.brave_api_key,
                     "Accept": "application/json"},
        )
        resp.raise_for_status()
        results = resp.json().get("results", []) or []
        return [{
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
            "age": r.get("age", ""),
            "source": (r.get("meta_url") or {}).get("hostname", ""),
        } for r in results]
    finally:
        if own:
            await client.aclose()


async def web_search(query: str, *, count: int = 5,
                     country: str = "kr", search_lang: str = "ko",
                     client: httpx.AsyncClient | None = None) -> list[dict]:
    """일반 웹 검색 — 배경지식·관행 수집(web_knowledge)용. 뉴스와 동일 shape 반환."""
    if not settings.brave_api_key:
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(
            _WEB_URL,
            params={"q": query, "country": country, "search_lang": search_lang, "count": count},
            headers={"X-Subscription-Token": settings.brave_api_key,
                     "Accept": "application/json"},
        )
        resp.raise_for_status()
        results = (resp.json().get("web") or {}).get("results", []) or []
        return [{
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
            "age": r.get("age", "") or "",
            "source": (r.get("meta_url") or {}).get("hostname", ""),
        } for r in results]
    finally:
        if own:
            await client.aclose()
