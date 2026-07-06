# engine/sector/collectors/rss.py
"""전문지 RSS — 표준 xml 파서 (신규 의존성 금지, 원칙 7). 피드별 실패 격리."""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

import httpx

from sector.contracts import CollectorResult, RawNewsItem
from sector.store import SectorStore
from sector.collectors.saveticker import _relevant

NAME = "rss"
KIND = "news"
_FEEDS = [
    ("etnews", "https://rss.etnews.com/Section901.xml"),
    ("trendforce", "https://www.trendforce.com/rss/press.xml"),
]


def _text(el, *tags) -> str:
    for t in tags:
        found = el.find(t)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True,
                                         headers={"User-Agent": "attn-viewer-sector/0.1"})
    items: list[RawNewsItem] = []
    failed: list[str] = []
    try:
        for name, url in _FEEDS:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                nodes = root.iter("item")
                for it in nodes:
                    title = _text(it, "title")
                    link = _text(it, "link")
                    if not title or not link or not _relevant(title):
                        continue
                    items.append(RawNewsItem(
                        id="rss-" + hashlib.sha1(link.encode()).hexdigest()[:12],
                        title=title, preview=_text(it, "description")[:300],
                        content=_text(it, "description"), source=name, url=link,
                        published_at=_text(it, "pubDate"), extra={"feed": name}))
            except Exception:  # noqa: BLE001 — 피드 격리
                failed.append(name)
        status = "ok" if not failed else "degraded"
        return CollectorResult(name=NAME, kind=KIND, items=items, status=status,
                               detail="" if not failed else "feed_fail=" + ",".join(failed))
    finally:
        if own:
            await client.aclose()
