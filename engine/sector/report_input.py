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
    # ingested_at look-ahead 게이트 (Phase 2 T3): 빈/불파싱 레거시는 통과·카운트만
    cards_ingested_unknown: int = 0
    raw_ingested_unknown: int = 0
    read_errors: list[str] = Field(default_factory=list)   # store 읽기 실패(never-raise)
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


# 리포트 입력 메트릭 allowlist — 상수 leaf로 추출(report_anchors와 공유), 호환 re-export
from sector.report_metrics_allowlist import REPORT_METRICS as _REPORT_METRICS  # noqa: E402


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


def build_metric_summaries(store, metrics: list[str] | None = None,
                           *, cutoff=None) -> tuple[list[MetricSummary], list[str]]:
    """cutoff(datetime) 주입 시 ts>cutoff 관측 제외 — look-ahead 차단(code review SF1)."""
    names = _REPORT_METRICS if metrics is None else metrics
    out: list[MetricSummary] = []
    missing: list[str] = []
    for m in names:
        info = METRIC_REGISTRY.get(m, {})
        try:
            summ = metric_summary(store, m, cutoff=cutoff)     # "" if 부재/실패
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


def _ingested_gate(items, now: datetime):
    """수집시각 look-ahead 차단. 파싱 가능 ∧ >now → 제외(future). 빈/불파싱 → 통과+카운트.

    레거시 데이터(빈 ingested_at 대량)를 배제하지 않기 위한 정책 — event-ts 창 필터가
    1차 방어이고, 신규 수집분은 ingested_at이 채워지므로 게이트가 점진 실효(스펙 v3)."""
    kept, future, unknown = [], 0, 0
    for it in items:
        dt = _parse_ts(getattr(it, "ingested_at", "") or "")
        if dt is None:
            unknown += 1
            kept.append(it)
        elif dt <= now:
            kept.append(it)
        else:
            future += 1
    return kept, future, unknown


def assemble_report_input(store, *, window_hours: int = 12,
                          now: datetime,
                          metrics: list[str] | None = None,
                          case_store=None, signals: list[str] | None = None,
                          as_of: str | None = None) -> ReportInput:
    now = _to_utc(now)      # 필수 — effective_now를 호출자가 1회 계산해 주입(결정성)
    win_from = now - timedelta(hours=window_hours)

    # 전량 읽어(limit=None) 주입 now로 정밀 컷 — 캡 절단 없음, 실시계 미사용(결정성)
    # store 읽기 실패도 never-raise(빈 목록 + 실패 표기 — code review B5)
    read_errors: list[str] = []
    try:
        all_cards = store.read_cards(days=None, limit=None)
    except Exception as exc:  # noqa: BLE001
        all_cards = []
        read_errors.append(f"read_cards: {exc}")
    try:
        all_raw = store.read_raw_news(months=None, limit=None)
    except Exception as exc:  # noqa: BLE001
        all_raw = []
        read_errors.append(f"read_raw_news: {exc}")
    cards, cstat = _in_window(all_cards, lambda c: c.ts, win_from, now)
    raw_news, rstat = _in_window(all_raw, lambda d: d.created_at, win_from, now)
    cards, c_ing_future, c_ing_unknown = _ingested_gate(cards, now)
    raw_news, r_ing_future, r_ing_unknown = _ingested_gate(raw_news, now)

    metric_summaries, missing = build_metric_summaries(store, metrics, cutoff=now)

    # 과거사례 지식층 seam — case_store 주면 결정적 질의(리랭크 없음), 없으면 빈 리스트(하위호환)
    external_knowledge: list[dict] = []
    if case_store is not None:
        try:
            from casemem.query import query_case_memory
            res = query_case_memory(case_store, signals=signals or [],
                                    as_of=as_of or now.isoformat(), sector="memory")
            external_knowledge = [res.model_dump()]
        except Exception:  # noqa: BLE001 — never-raise, seam 실패는 빈 리스트
            external_knowledge = []

    diag = ReportInputDiagnostics(
        cards_in_window=len(cards), raw_news_in_window=len(raw_news),
        cards_scanned=cstat["scanned"], raw_scanned=rstat["scanned"],
        cards_dropped_unparsed=cstat["unparsed"],
        cards_dropped_future=cstat["future"] + c_ing_future,
        cards_dropped_out=cstat["out"],
        raw_dropped_unparsed=rstat["unparsed"],
        raw_dropped_future=rstat["future"] + r_ing_future,
        raw_dropped_out=rstat["out"],
        cards_ingested_unknown=c_ing_unknown, raw_ingested_unknown=r_ing_unknown,
        read_errors=read_errors,
        metrics_missing=missing,
    )
    return ReportInput(
        window_from=win_from.isoformat(), window_to=now.isoformat(),
        cards=cards, raw_news=raw_news, metrics=metric_summaries, diagnostics=diag,
        external_knowledge=external_knowledge,
    )
