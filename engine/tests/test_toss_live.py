"""토스 모듈 라이브 스모크 — 실제 API를 친다 (네트워크 필요).

CI 상시 실행 금지 (docs 계획: 실 API는 야간/수동 스모크).
    engine/.venv/bin/python -m pytest engine/tests/test_toss_live.py -v -s
"""

import asyncio
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.toss import (  # noqa: E402
    TossClient,
    collect_company,
    collect_feed,
    daily_candles,
)

CODE = "005930"  # 삼성전자


def test_feed_four_tabs():
    arts = asyncio.run(collect_feed())
    assert arts, "feed returned nothing"
    assert len(arts) <= 30
    top = arts[0]
    assert top.news_id and top.title
    # feed_count 집계가 작동하는가 (최소 1)
    assert top.feed_count >= 1
    print(f"\nfeed: {len(arts)} articles, top feed_count={top.feed_count} tabs={top.tabs}")
    print(f"  top: {top.title[:50]}")


def test_company_bundle():
    async def run():
        async with TossClient() as c:
            return await collect_company(CODE, client=c, news_size=5, trend_size=5)

    bundle = asyncio.run(run())
    assert bundle["code"] == CODE
    assert bundle["news"], "no company news"
    assert any(len(article.content_text) > 200 for article in bundle["news"]), (
        "company news detail enrichment stayed at the 103-char preview"
    )
    assert bundle["info"].get("overview") is not None
    inv = bundle["info"].get("investment")
    assert inv is not None and inv.per is not None
    assert bundle["trading_trend"], "no trading trend"
    row = bundle["trading_trend"][0]
    assert row.base_date and row.net_foreigner_buy_volume is not None
    print(f"\ncompany {CODE}: news={len(bundle['news'])} PER={inv.per} PBR={inv.pbr}")
    print(f"  latest trend {row.base_date}: 외국인순매수={row.net_foreigner_buy_volume:,}")
    if bundle["broker_ranking"]:
        print(f"  broker top5={len(bundle['broker_ranking'].top5_activity_list)}")


def test_daily_candles():
    candles = asyncio.run(daily_candles(CODE, count=10))
    assert len(candles) >= 5
    assert candles[0].close is not None
    print(f"\ndaily: {len(candles)} candles, latest close={candles[0].close}")
