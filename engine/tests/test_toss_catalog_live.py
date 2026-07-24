"""WTS 계약의 공개 read-only operation 전수 라이브 스모크.

수동/야간 전용이며 로그인·계좌·주문·게스트 전용 작업은 호출하지 않는다.
"""

from __future__ import annotations

import asyncio

import pytest

from tools.toss.readonly import (
    collect_community_aggregate,
    execute_wts_operation,
    load_wts_catalog,
)

pytestmark = pytest.mark.live

KR_CODE = "A005930"
KR_BARE = "005930"
US_PRODUCT_CODE = "US20100629001"


PUBLIC_SAMPLES = {
    "searchAutocomplete": {"body": {"query": "삼성", "size": 5}},
    "resolveProduct": {"path_params": {"identifier": KR_CODE}},
    "getWtsStocks": {"query": {"codes": KR_CODE}},
    "getStockCommon": {"path_params": {"productCode": KR_CODE}},
    "getStockHeader": {"path_params": {"productCode": KR_CODE}},
    "getStockBadges": {"path_params": {"productCode": KR_CODE}},
    "getWtsPrices": {"query": {"productCodes": KR_CODE, "meta": "true"}},
    "getWtsPriceDetails": {"query": {"productCodes": KR_CODE}},
    "getWtsBatchPrices": {"query": {"productCodes": KR_CODE, "meta": "true"}},
    "getWtsTicks": {
        "path_params": {"productCode": KR_CODE},
        "query": {"viewType": "krx_all", "count": 5, "investMode": "krx"},
    },
    "getWtsPriceLimits": {"path_params": {"productCode": KR_CODE}},
    "getKrDailyCandles": {
        "path_params": {"productCode": KR_CODE},
        "query": {"count": 5, "useAdjustedRate": "true"},
    },
    "getKrMinuteCandles": {
        "path_params": {"productCode": KR_CODE},
        "query": {
            "count": 5,
            "from": "2026-07-23T15:31:00+09:00",
            "useAdjustedRate": "true",
        },
    },
    "getUsDailyCandles": {
        "path_params": {"productCode": US_PRODUCT_CODE},
        "query": {"count": 5, "session": "all", "useAdjustedRate": "true"},
    },
    "getWtsOverview": {"path_params": {"productCode": KR_CODE}},
    "getWtsInvestment": {"path_params": {"productCode": KR_CODE}},
    "getWtsInvestmentIndicators": {"path_params": {"productCode": KR_CODE}},
    "getWtsDividend": {"path_params": {"productCode": KR_CODE}},
    "getWtsRedFlags": {"path_params": {"productCode": KR_CODE}},
    "getTradingTrend": {"query": {"productCode": KR_CODE, "size": 5}},
    "getProgramTrading": {"query": {"productCode": KR_CODE, "size": 5}},
    "getBrokerRanking": {"query": {"code": KR_CODE}},
    "getWtsNewsFeed": {"body": {"type": "HOT", "indexCode": None}},
    "getCompanyNews": {
        "path_params": {"code": KR_BARE},
        "query": {"size": 5, "number": 1, "orderBy": "latest"},
    },
    "getAiSignalDetail": {
        "query": {"productCode": KR_CODE, "productType": "STOCKS"},
    },
    "getAiSignalBatch": {"body": {"productCodes": [KR_CODE]}},
    "getReasoningInterest": {"query": {"size": 5}},
    "getRealtimeRanking": {"query": {"size": 5}},
    "getIndexPrice": {"path_params": {"indexCode": "COMP.NAI"}},
    "getExchangeRates": {},
    "getMarketIndicators": {},
    "getUsIndexIndicators": {"query": {"market": "us"}},
    "getTradingInfo": {},
    "getEconomicEvents": {},
}


def test_every_public_wts_tool_operation():
    catalog = load_wts_catalog()
    expected = {
        op["operationId"]
        for op in catalog["operations"]
        if op.get("auth") == "public" and op.get("exposure") == "tool"
    }
    assert set(PUBLIC_SAMPLES) == expected - {"getNewsDetail"}

    async def run():
        responses = {}
        for operation_id, arguments in PUBLIC_SAMPLES.items():
            payload = await execute_wts_operation(operation_id, **arguments)
            assert isinstance(payload, dict), operation_id
            responses[operation_id] = payload
        return responses

    responses = asyncio.run(run())
    news = responses["getCompanyNews"]
    rows = ((news.get("result") or {}).get("body") or [])
    assert rows
    news_id = rows[0].get("id")
    assert news_id
    detail = asyncio.run(execute_wts_operation(
        "getNewsDetail", path_params={"newsId": news_id}
    ))
    assert isinstance(detail, dict)


def test_community_live_exposes_aggregate_only():
    aggregate = asyncio.run(collect_community_aggregate("KR7005930003"))
    assert aggregate["privacy"].startswith("aggregate_only")
    assert "comments" not in aggregate
    assert "content" not in aggregate
