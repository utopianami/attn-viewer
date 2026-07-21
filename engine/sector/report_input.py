"""리포트 입력 번들 조립 — 결정적(LLM 없음). Phase 2 파이프라인의 입력.

기존 수집 데이터만 사용: SectorCards + SaveTicker firehose raw + 메트릭 요약.
- 카드/raw는 store 전량을 읽어(limit=None) 주입 now 기준 창(window)으로 코드가 정밀 컷.
  store의 실시계 필터(read_cards days=)는 쓰지 않는다(결정성).
- 메트릭은 metrics_registry.metric_summary()를 재사용(다중 시리즈 그룹핑·delta_pct 내장).
- 토스 종목·증권사 리포트·과거사례 지식층은 seam(빈 리스트)으로 남긴다.
설계: /html/market-report-design.html · 계획: docs/superpowers/plans/2026-07-21-market-report-phase1-data-input.md
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from sector.contracts import RawNewsDoc, SectorCard
from sector.metrics_registry import METRIC_REGISTRY, metric_summary


class MetricSummary(BaseModel):
    metric: str
    label: str
    summary: str = ""       # metric_summary() 한 줄 요약; 부재/실패 시 ""
    available: bool = False


class ReportInputDiagnostics(BaseModel):
    cards_in_window: int
    raw_news_in_window: int
    cards_scanned: int
    raw_scanned: int
    # drop 사유별 카운트 (투명성)
    cards_dropped_unparsed: int = 0
    cards_dropped_future: int = 0
    cards_dropped_out: int = 0
    raw_dropped_unparsed: int = 0
    raw_dropped_future: int = 0
    raw_dropped_out: int = 0
    metrics_missing: list[str] = Field(default_factory=list)


class ReportInput(BaseModel):
    window_from: str
    window_to: str
    cards: list[SectorCard] = Field(default_factory=list)         # 구글뉴스 판정 메모리 카드
    raw_news: list[RawNewsDoc] = Field(default_factory=list)      # SaveTicker firehose 전량(창) — Phase2 1차 필터 대상
    metrics: list[MetricSummary] = Field(default_factory=list)
    diagnostics: ReportInputDiagnostics
    # seams — 나중에 채움(사용자 지시): 지금은 항상 빈 리스트
    stock_signals: list[dict] = Field(default_factory=list)       # 토스 종목(차트·수급·다이버전스)
    analyst_reports: list[dict] = Field(default_factory=list)     # 증권사 리포트(목표가·투자의견)
    external_knowledge: list[dict] = Field(default_factory=list)  # 과거사례/규칙(다른 세션)


# 리포트 입력 메트릭 allowlist — 사이클/수요/공급/AI 수요 대표 시리즈
_REPORT_METRICS = [
    "memory_price_usd_per_gb",   # 현물가 — 사이클 핵심
    "kr_semi_production_index",  # 생산·재고
    "kr_semi_export",            # 수출액 — 수요 선행
    "memory_capex",              # 3사 CAPEX — 공급 증설
    "equip_revenue",             # 장비사 매출 — 공급 선행
    "hyperscaler_capex",         # 전방 capex
    "ai_chip_revenue",           # AI칩 매출
    "tw_monthly_revenue",        # 대만 ODM/TSMC
    "token_price",               # 토큰 단가 — AI 수요
    "openrouter_daily_tokens",   # 토큰 사용량 — AI 수요
]


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    """ISO8601(Z/offset/naive) → aware UTC. 파싱·변환 불가 시 None(never-raise)."""
    if not ts:
        return None
    raw = ts.replace("Z", "+00:00")
    try:
        return _to_utc(datetime.fromisoformat(raw))
    except (ValueError, TypeError, OverflowError):
        return None


def build_metric_summaries(store, metrics: list[str] | None = None
                           ) -> tuple[list[MetricSummary], list[str]]:
    names = _REPORT_METRICS if metrics is None else metrics
    out: list[MetricSummary] = []
    missing: list[str] = []
    for m in names:
        info = METRIC_REGISTRY.get(m, {})
        try:
            summ = metric_summary(store, m)     # "" if 부재/실패
        except Exception:  # noqa: BLE001 — never-raise, 진단으로만
            summ = ""
        available = bool(summ)
        if not available:
            missing.append(m)
        out.append(MetricSummary(metric=m, label=info.get("label", m),
                                 summary=summ, available=available))
    return out, missing


def _in_window(items, ts_getter, win_from: datetime, now: datetime):
    """창 필터 + drop 사유 카운트. 반환: (kept, stats). 경계 포함, 미래(>now) 제외."""
    kept = []
    unparsed = future = out = 0
    for it in items:
        dt = _parse_ts(ts_getter(it))
        if dt is None:
            unparsed += 1
            continue
        if dt > now:
            future += 1
            continue
        if dt < win_from:
            out += 1
            continue
        kept.append(it)
    return kept, {"scanned": len(items), "unparsed": unparsed, "future": future, "out": out}


def assemble_report_input(store, *, window_hours: int = 12,
                          now: datetime | None = None,
                          metrics: list[str] | None = None) -> ReportInput:
    now = _to_utc(now or datetime.now(timezone.utc))
    win_from = now - timedelta(hours=window_hours)

    # 전량 읽어(limit=None) 주입 now로 정밀 컷 — 캡 절단 없음, 실시계 미사용(결정성)
    cards, cstat = _in_window(store.read_cards(days=None, limit=None),
                              lambda c: c.ts, win_from, now)
    raw_news, rstat = _in_window(store.read_raw_news(months=None, limit=None),
                                 lambda d: d.created_at, win_from, now)

    metric_summaries, missing = build_metric_summaries(store, metrics)
    diag = ReportInputDiagnostics(
        cards_in_window=len(cards), raw_news_in_window=len(raw_news),
        cards_scanned=cstat["scanned"], raw_scanned=rstat["scanned"],
        cards_dropped_unparsed=cstat["unparsed"], cards_dropped_future=cstat["future"],
        cards_dropped_out=cstat["out"],
        raw_dropped_unparsed=rstat["unparsed"], raw_dropped_future=rstat["future"],
        raw_dropped_out=rstat["out"],
        metrics_missing=missing,
    )
    return ReportInput(
        window_from=win_from.isoformat(), window_to=now.isoformat(),
        cards=cards, raw_news=raw_news, metrics=metric_summaries, diagnostics=diag,
    )
