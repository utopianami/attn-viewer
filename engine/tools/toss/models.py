"""토스 응답의 typed 모델.

토스 응답 필드가 매우 많고(investment는 80+) 토스가 언제든 추가할 수 있으므로,
모델은 `extra="allow"`로 관대하게 두고 엔진이 실제로 쓰는 핵심 필드만 명시한다.
전체 raw는 항상 보존되어 하류에서 필요 시 꺼내 쓸 수 있다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Lax(BaseModel):
    model_config = ConfigDict(extra="allow")


class FeedArticle(_Lax):
    """`/api/v1/dashboard/wts/news` 피드 항목."""

    news_id: str = Field(alias="newsId")
    title: str
    summary: str = ""
    created_at: str | None = Field(default=None, alias="createdAt")
    news_type: str | None = Field(default=None, alias="newsType")
    related_stocks: list[dict] = Field(default_factory=list, alias="relatedStocks")


class CompanyArticle(_Lax):
    """`/api/v2/news/companies/{code}` 회사 뉴스 항목."""

    id: str
    title: str
    summary: str = ""
    content_text: str = Field(default="", alias="contentText")
    created_at: str | None = Field(default=None, alias="createdAt")


class StockOverview(_Lax):
    """`/api/v2/stock-infos/A{code}/overview` — 시장·회사 식별 + 시총."""

    type: str | None = None
    market: dict | None = None
    company: dict | None = None
    market_value_krw: float | int | None = Field(default=None, alias="marketValueKrw")


class InvestmentInfo(_Lax):
    """`/api/v2/stock-infos/A{code}/investment` — 밸류에이션·수급 지표."""

    per: float | None = None
    pbr: float | None = None
    psr: float | None = None
    roe: float | None = None
    eps: float | None = None
    bps: float | None = None
    dividend_yield_ratio: float | None = Field(default=None, alias="dividendYieldRatio")
    foreigner_shareholding_ratio: float | None = Field(
        default=None, alias="foreignerShareholdingRatio"
    )
    market_value_krw: float | int | None = Field(default=None, alias="marketValueKrw")


class TradingTrendRow(_Lax):
    """`/api/v1/.../trading-trend` — 하루치 투자자별 수급."""

    base_date: str = Field(alias="baseDate")
    net_individuals_buy_volume: int | None = Field(
        default=None, alias="netIndividualsBuyVolume"
    )
    net_foreigner_buy_volume: int | None = Field(
        default=None, alias="netForeignerBuyVolume"
    )
    net_institution_buy_volume: int | None = Field(
        default=None, alias="netInstitutionBuyVolume"
    )
    foreigner_ratio: float | None = Field(default=None, alias="foreignerRatio")
    close: float | int | None = None


class BrokerRanking(_Lax):
    """`/api/v1/mds/broker/trading-ranking` — 거래 창구 상위 5 + 외국인."""

    code: str
    top5_activity_list: list[dict] = Field(
        default_factory=list, alias="top5ActivityList"
    )
    updated_at: str | None = Field(default=None, alias="updatedAt")


class Candle(_Lax):
    """`/api/v1/c-chart/...` 캔들 한 개."""

    dt: str
    open: float | int | None = None
    high: float | int | None = None
    low: float | int | None = None
    close: float | int | None = None
    volume: float | int | None = None
