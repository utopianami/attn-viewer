"""토스 피드 4탭 수집 (RA-외부 toss_trend 수집기의 결정적 부분).

이 모듈은 순수 수집만 한다 — 뉴스 요약·트렌드 합성(LLM)은 RA-외부 executor 몫.
캐싱 없음(사용자 지시). feed-count(같은 기사가 여러 탭에 등장 = 강조 신호)를 집계해
트렌드 합성 단계가 우선순위를 매길 수 있게 한다.
"""

from __future__ import annotations

import asyncio

from .client import TossClient
from .models import FeedArticle

FEED_PATH = "/api/v1/dashboard/wts/news"

# 피드 탭 → 토스 TYPE (docs/toss-api-inventory.md). 비로그인 가능한 4탭만.
FEED_TABS: dict[str, str] = {
    "popular": "PERSONALIZED",      # 인기 (비로그인: 많이 보는 뉴스)
    "highlight": "ALL_HIGHLIGHT",   # 주요
    "latest": "HOT",                # 최신
    "soaring": "SOARING_STOCK",     # 급상승
}

DEFAULT_TREND_CAP = 30  # dedup 후 상한 (settings로 이관 예정 — 콜 폭발 방지)


class TrendArticle(FeedArticle):
    """피드 기사 + 몇 개 탭에 등장했는지(feed_count) + 어느 탭들인지."""

    feed_count: int = 1
    tabs: list[str] = []


async def fetch_tab(client: TossClient, tab_type: str) -> list[FeedArticle]:
    data = await client.post_json(FEED_PATH, {"type": tab_type, "indexCode": None})
    news = (data or {}).get("result", {}).get("news", []) or []
    out: list[FeedArticle] = []
    for item in news:
        try:
            out.append(FeedArticle.model_validate(item))
        except Exception:
            continue  # 스키마 드리프트 항목은 건너뛴다 (never-raise)
    return out


async def collect_feed(
    client: TossClient | None = None, cap: int = DEFAULT_TREND_CAP
) -> list[TrendArticle]:
    """4탭 병렬 수집 → newsId dedup(feed_count 집계) → feed_count·최신순 상위 cap.

    반환은 요약/트렌드 합성의 입력. 어느 탭도 못 받으면 빈 리스트(never-raise).
    """
    own = client is None
    client = client or TossClient()
    try:
        results = await asyncio.gather(
            *(fetch_tab(client, t) for t in FEED_TABS.values()),
            return_exceptions=True,
        )
    finally:
        if own:
            await client.__aexit__()

    merged: dict[str, TrendArticle] = {}
    for tab_name, res in zip(FEED_TABS.keys(), results):
        if isinstance(res, BaseException):
            continue  # 탭 단위 degraded — 나머지 탭은 계속
        for art in res:
            if art.news_id in merged:
                cur = merged[art.news_id]
                cur.feed_count += 1
                cur.tabs.append(tab_name)
            else:
                merged[art.news_id] = TrendArticle(
                    **art.model_dump(by_alias=True), feed_count=1, tabs=[tab_name]
                )

    ranked = sorted(
        merged.values(),
        key=lambda a: (a.feed_count, a.created_at or ""),
        reverse=True,
    )
    return ranked[:cap]
