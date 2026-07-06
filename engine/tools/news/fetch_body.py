"""뉴스 본문 수집 — curation 통과 상위 N개만 (P1-1, F6: 제목/요약만으론 G1 근거 판정이 얕음).

httpx GET → trafilatura.extract() → NewsItem.content 채움 (≤4000자).
실패는 조용히 스킵 — 제목/요약만으로도 파이프라인은 계속 동작한다.
토스 뉴스는 수집 시점에 이미 본문 API(api/v2/news/{id})로 채워지므로 여기 대상이 아니다.
"""

from __future__ import annotations

import asyncio

from contracts import NewsItem

_MAX_CONTENT = 4000
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


async def _fetch_one(item: NewsItem, client) -> None:
    try:
        resp = await client.get(item.url, headers={"User-Agent": _UA},
                                follow_redirects=True)
        if resp.status_code != 200 or not resp.text:
            return
        import trafilatura
        text = trafilatura.extract(resp.text, include_comments=False,
                                   include_tables=False)
        if text and len(text) > len(item.content):
            item.content = text[:_MAX_CONTENT]
    except Exception:
        return  # 본문 실패 = 제목/요약으로 동작 유지


async def fetch_bodies(items: list[NewsItem], *, top_n: int = 5,
                       timeout_s: float = 8.0) -> int:
    """URL 있는 앞쪽 top_n개 본문 채움 (in-place). 반환: 성공 건수."""
    try:
        import trafilatura  # noqa: F401 — 미설치 환경이면 통째로 스킵
    except ImportError:
        return 0
    import httpx

    targets, seen = [], set()
    for n in items:
        if len(targets) >= top_n:
            break
        if n.url and n.url not in seen and len(n.content) < 300:
            seen.add(n.url)
            targets.append(n)
    if not targets:
        return 0
    async with httpx.AsyncClient(timeout=timeout_s) as hc:
        await asyncio.gather(*(_fetch_one(n, hc) for n in targets),
                             return_exceptions=True)
    return sum(1 for n in targets if len(n.content) >= 300)
