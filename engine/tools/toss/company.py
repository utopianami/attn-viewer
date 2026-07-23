"""토스 회사별 데이터 수집 (RA-외부 toss_company 수집기).

번들: 뉴스(목록+본문 인리치) · 회사정보(overview/investment/indicators/dividend/red_flags)
· 거래동향(trading_trend/broker_ranking). 전부 결정적 — LLM 없음.

뉴스 수집은 하네스 internal/ingest/toss.go의 규칙을 이식:
- createdAt은 KST 무타임존 문자열 그대로 (필요 시 하류가 파싱)
- 목록의 contentText는 103자 프리뷰 → 본문 상세로 인리치
"""

from __future__ import annotations

import asyncio
from typing import Any

from .client import TossClient
from .models import (
    BrokerRanking,
    CompanyArticle,
    InvestmentInfo,
    NewsDetailResult,
    StockOverview,
    TradingTrendRow,
)


def _norm(code: str) -> tuple[str, str]:
    """'005930' 또는 'A005930' → (6자리, A접두)."""
    c = code.strip().upper()
    bare = c[1:] if c.startswith("A") else c
    return bare, f"A{bare}"


async def fetch_company_news(
    client: TossClient, code: str, size: int = 20, enrich: bool = True
) -> list[CompanyArticle]:
    bare, _ = _norm(code)
    data = await client.get_json(
        f"/api/v2/news/companies/{bare}", params={"size": size, "number": 1}
    )
    body = (data or {}).get("result", {}).get("body", []) or []
    articles: list[CompanyArticle] = []
    for item in body:
        try:
            articles.append(CompanyArticle.model_validate(item))
        except Exception:
            continue

    if enrich:
        async def _enrich(a: CompanyArticle) -> None:
            # 목록 contentText가 프리뷰(짧음)면 본문 상세로 교체
            if len(a.content_text) < 200:
                try:
                    d = await client.get_json(f"/api/v2/news/{a.id}")
                    detail = NewsDetailResult.model_validate((d or {}).get("result", {}))
                    full = detail.full_text()
                    if full and len(full) > len(a.content_text):
                        a.content_text = full
                except Exception:
                    pass  # 인리치 실패는 프리뷰 유지

        await asyncio.gather(*(_enrich(a) for a in articles))
    return articles


async def fetch_company_info(client: TossClient, code: str) -> dict[str, Any]:
    """overview·investment·indicators·dividend·red_flags를 병렬 번들."""
    bare, pref = _norm(code)

    async def _try(coro):
        try:
            return await coro
        except Exception:
            return None

    overview, investment, indicators, dividend, red_flags = await asyncio.gather(
        _try(client.get_json(f"/api/v2/stock-infos/{pref}/overview")),
        _try(client.get_json(f"/api/v2/stock-infos/{pref}/investment")),
        _try(client.get_json(f"/api/v1/stock-detail/ui/wts/{pref}/investment-indicators")),
        _try(client.get_json(f"/api/v1/stock-infos/dividend/{pref}/summary")),
        _try(client.get_json(f"/api/v1/stock-infos/{pref}/red-flags")),
    )

    out: dict[str, Any] = {}
    if overview:
        out["overview"] = StockOverview.model_validate(overview["result"])
    if investment:
        out["investment"] = InvestmentInfo.model_validate(investment["result"])
    if indicators:
        out["indicators"] = indicators.get("result")  # 표시용 raw (섹션 구조)
    if dividend:
        out["dividend"] = dividend.get("result")
    if red_flags is not None:
        out["red_flags"] = (red_flags or {}).get("result", [])
    return out


async def fetch_trading_trend(
    client: TossClient, code: str, size: int = 20
) -> list[TradingTrendRow]:
    """투자자별 수급(개인/외국인/기관 순매수) — 최근 size일."""
    _, pref = _norm(code)
    data = await client.get_json(
        "/api/v1/stock-infos/trade/trend/trading-trend",
        params={"productCode": pref, "size": size},
    )
    body = (data or {}).get("result", {}).get("body", []) or []
    rows: list[TradingTrendRow] = []
    for item in body:
        try:
            rows.append(TradingTrendRow.model_validate(item))
        except Exception:
            continue
    return rows


async def fetch_broker_ranking(client: TossClient, code: str) -> BrokerRanking | None:
    _, pref = _norm(code)
    try:
        data = await client.get_json(f"/api/v1/mds/broker/trading-ranking?code={pref}")
        return BrokerRanking.model_validate(data["result"])
    except Exception:
        return None


async def collect_company(
    code: str,
    client: TossClient | None = None,
    news_size: int = 20,
    trend_size: int = 20,
) -> dict[str, Any]:
    """한 종목의 뉴스+정보+거래동향 전체 번들 (RA-외부 toss_company 진입점)."""
    own = client is None
    client = client or TossClient()
    try:
        news, info, trend, broker = await asyncio.gather(
            fetch_company_news(client, code, size=news_size),
            fetch_company_info(client, code),
            fetch_trading_trend(client, code, size=trend_size),
            fetch_broker_ranking(client, code),
        )
    finally:
        if own:
            await client.__aexit__()
    return {
        "code": _norm(code)[0],
        "news": news,
        "info": info,
        "trading_trend": trend,
        "broker_ranking": broker,
    }
