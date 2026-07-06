# engine/sector/collectors/brave_matrix.py
"""축별 쿼리 매트릭스 — 기존 brave 도구 + geo 라우팅 + 커뮤니티/URL 필터 재사용."""
from __future__ import annotations

import hashlib
import re

import httpx

from sector.contracts import CollectorResult, RawNewsItem
from sector.store import SectorStore
from stages.ra_external import _BLOCKED_DOMAINS, _norm_url
from tools.news.brave import news_search

NAME = "brave_matrix"
KIND = "news"
_HANGUL = re.compile(r"[가-힣]")

_QUERIES: list[tuple[str, str]] = [  # (axis, query) — 계획 §2 쿼리 매트릭스
    ("A", "SK Hynix HBM supply contract"), ("A", "Samsung DRAM price"),
    ("A", "Micron guidance"), ("A", "삼성전자 감산"), ("A", "메모리 고정거래가격"),
    ("A_prime", "TSMC CoWoS capacity"), ("A_prime", "SemiAnalysis memory HBM"),
    ("B", "Microsoft capex guidance"), ("B", "Google datacenter spending"),
    ("B", "Meta AI infrastructure capex"), ("B", "hyperscaler memory procurement"),
    ("C", "OpenAI revenue"), ("C", "Anthropic usage"), ("C", "AI inference demand"),
    ("E", "smartphone shipment forecast"), ("E", "중국 스마트폰 보조금"),
    ("P", "HBM export control"), ("P", "CXMT DRAM capacity"),
]


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    items: list[RawNewsItem] = []
    seen: set[str] = set()
    fails = 0
    for axis, q in _QUERIES:
        kr = bool(_HANGUL.search(q))
        try:
            rows = await news_search(q, count=5, freshness="pd",
                                     country="kr" if kr else "us",
                                     search_lang="ko" if kr else "en", client=client)
        except Exception:  # noqa: BLE001
            fails += 1
            continue
        for r in rows:
            url = r.get("url") or ""
            host = (r.get("source") or "").lower()
            if any(host.endswith(d) for d in _BLOCKED_DOMAINS):
                continue
            nu = _norm_url(url)
            if nu in seen:
                continue
            seen.add(nu)
            items.append(RawNewsItem(
                id="bv-" + hashlib.sha1(nu.encode()).hexdigest()[:12],
                title=r.get("title") or "", preview=r.get("description") or "",
                content=r.get("description") or "", source=host, url=url,
                published_at=r.get("age") or "", extra={"axis_hint": axis, "query": q}))
    status = "ok" if fails == 0 else "degraded"
    return CollectorResult(name=NAME, kind=KIND, items=items, status=status,
                           detail="" if not fails else f"query_fail={fails}")
