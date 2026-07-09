"""네이버 뉴스 검색 — 국내 뉴스 주력 (2026-07-09 brave 대체 구성: 국내=네이버, 해외=구글뉴스 RSS).

무료 25,000콜/일. 키는 datalab과 같은 네이버 앱 (앱에 "검색" API 권한 필요 —
미활성이면 401/024 → 빈 리스트 반환, 호출자 폴백 체인이 이어받음).
반환 형식은 brave news_search와 동일한 dict rows (title/url/description/age/source).
"""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

import httpx

from app.settings import settings

_URL = "https://openapi.naver.com/v1/search/news.json"
_TAG_RE = re.compile(r"</?b>|&quot;|&amp;|&lt;|&gt;")
_UNESCAPE = {"&quot;": '"', "&amp;": "&", "&lt;": "<", "&gt;": ">"}


def _clean(s: str) -> str:
    s = re.sub(r"</?b>", "", s or "")
    for k, v in _UNESCAPE.items():
        s = s.replace(k, v)
    return s.strip()


def _iso(pub: str) -> str:
    """RFC822 pubDate → YYYY-MM-DD (실패 시 빈칸 — 시점 불명은 G3가 중립 취급)."""
    try:
        return parsedate_to_datetime(pub).date().isoformat()
    except Exception:
        return ""


async def naver_news_search(query: str, *, count: int = 5, sort: str = "date",
                            client: httpx.AsyncClient | None = None) -> list[dict]:
    """뉴스 검색. sort: date(최신순)|sim(정확도순). 실패 시 빈 리스트 (never-raise는 호출자)."""
    cid = settings.naver_search_client_id or settings.naver_client_id
    secret = settings.naver_search_client_secret or settings.naver_client_secret
    if not (cid and secret):
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(
            _URL,
            params={"query": query, "display": min(count, 10), "sort": sort},
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret},
        )
        resp.raise_for_status()
        items = resp.json().get("items", []) or []
        out = []
        for it in items:
            url = it.get("originallink") or it.get("link") or ""
            out.append({
                "title": _clean(it.get("title", "")),
                "url": url,
                "description": _clean(it.get("description", "")),
                "age": _iso(it.get("pubDate", "")),
                "source": httpx.URL(url).host or "" if url else "",
            })
        return out
    finally:
        if own:
            await client.aclose()
