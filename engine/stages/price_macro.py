"""PRICE·MACRO 스테이지 — 시세(ticker) + 매크로(global). 전부 결정적, LLM 없음."""

from __future__ import annotations

import asyncio

from contracts import (
    AtomicClaim,
    ClaimNorm,
    EnvelopeMeta,
    PlanPacket,
    PriceMacroPacket,
    TypedFact,
)
from tools.price.macro import collect_macro
from tools.price.yahoo import fundamentals, quote
from tools.toss.sector_momentum import (
    SectorMomentumResult,
    collect_sector_momentum,
    is_sector_momentum_request,
    parse_lookback_sessions,
)


def _assemble(plan: PlanPacket, quotes: list, macro: dict,
              extra_series: list | None = None) -> tuple[list[TypedFact], str | None]:
    """quotes + macro 로부터 typed_facts 와 error 메시지를 조립한다.

    라이브 경로와 snapshot 경로가 동일한 변환 로직을 재사용하도록 추출한 헬퍼.
    외부에서 직접 호출해도 되는 순수 함수 (I/O 없음).
    """
    since = None
    # "올해" 수익률 요구 — fiscal 표현 또는 metrics("올해 수익률", "기간 수익률", YTD)가 신호
    wants_ytd = any("YTD" in (fp.calendar_period or "") or fp.expression in ("올해", "연초")
                    for fp in plan.fiscal_periods)
    wants_ret = any(k in m for m in plan.metrics for k in ("수익률", "상승률", "올랐", "YTD", "ytd"))
    if wants_ytd or wants_ret:
        since = f"{plan.knowledge_cutoff[:4]}-01-02"

    # typed_facts — 수익률/현재가를 계산 입력 자격으로
    facts: list[TypedFact] = []
    for q in quotes:
        if isinstance(q, dict) and "error" not in q:
            facts.append(TypedFact(
                # 통화는 yahoo meta 실측값 — KRW 하드코딩이 AAPL/MU를 원화로 라벨링했던
                # 버그 (2026-07-09 woojin 피드백). 미제공 시에만 KRW 폴백 (국내 위주 가정)
                id=f"price:{q['token']}", value=float(q["last"]),
                unit=q.get("cur") or "KRW",
                label=f"{q['token']} 현재가", source=f"yahoo:{q.get('symbol')}",
            ))
            if "ret_pct" in q:
                facts.append(TypedFact(
                    id=f"ret:{q['token']}", value=round(float(q["ret_pct"]), 2), unit="percent",
                    period=f"since {since}", label=f"{q['token']} 기간수익률", source=f"yahoo:{q.get('symbol')}",
                ))

    return facts, since


def _sector_evidence(
    result: SectorMomentumResult,
    plan: PlanPacket,
) -> tuple[list[TypedFact], list[AtomicClaim], list[dict]]:
    """업종 집계 결과를 PRICE 패킷의 결정적 수치·주장·원본 시계열로 변환한다."""
    raw = {"kind": "sector_momentum", **result.model_dump(mode="json")}
    if not result.sectors or not result.as_of:
        return [], [], [raw]
    period = (
        f"{result.base_session}..{result.as_of}"
        if result.base_session else f"{result.lookback_sessions} sessions"
    )
    facts: list[TypedFact] = []
    claims: list[AtomicClaim] = [
        AtomicClaim(
            id="price:sector_momentum:coverage",
            text=(
                f"KOSPI 표본 {result.universe_valid}/{result.universe_requested}개로 "
                f"{result.lookback_sessions}거래일 업종별 등락률을 집계했다"
            ),
            type="context",
            source="price",
            unit_id="q0",
            uncertainty="low",
            norm=ClaimNorm(
                entity="코스피 업종지수",
                metric="업종별 등락률",
                period=period,
                source_type="primary",
                as_of=result.as_of,
            ),
            ref="toss-wts:overview+c-chart",
        )
    ]
    # PLAN은 같은 요구를 “KOSPI/KOSDAQ sectors / 2~3거래일 수익률”처럼
    # 다른 언어·표현으로 만들 수 있다. 실제 가격 슬롯 표현을 그대로 별칭 claim으로
    # 남겨, 수집 성공 뒤에도 단순 토큰 차이로 uncovered가 되는 일을 막는다.
    for index, slot in enumerate(plan.needed_evidence):
        if slot.source_type != "price":
            continue
        alias_text = f"{slot.entity} {slot.metric}".lower()
        if not (
            any(token in alias_text for token in ("sector", "업종", "섹터", "산업"))
            and any(token in alias_text for token in ("수익", "등락", "상승", "return"))
        ):
            continue
        claims.append(AtomicClaim(
            id=f"price:sector_momentum:slot:{index}",
            text=(
                f"{slot.entity}의 {slot.metric}을 KOSPI WICS 표본 일봉으로 집계했다"
            ),
            type="context",
            source="price",
            unit_id="q0",
            uncertainty="low",
            norm=ClaimNorm(
                entity=slot.entity,
                metric=slot.metric,
                period=slot.period or period,
                source_type="primary",
                as_of=result.as_of,
            ),
            ref="toss-wts:overview+c-chart",
        ))
    for row in result.sectors[:12]:
        fact_id = f"sector_ret:{row.sector_code or row.rank}"
        facts.append(TypedFact(
            id=fact_id,
            value=row.median_return_pct,
            unit="percent",
            period=period,
            label=f"{row.sector_name} 업종 중앙수익률",
            source="toss-wts:wics+c-chart",
        ))
        claims.append(AtomicClaim(
            id=f"price:{fact_id}",
            text=(
                f"{row.sector_name} 업종의 {result.lookback_sessions}거래일 "
                f"중앙수익률은 {row.median_return_pct:+.2f}%"
            ),
            type="price",
            source="price",
            unit_id="q0",
            uncertainty="low",
            norm=ClaimNorm(
                entity=row.sector_name,
                metric="업종별 등락률",
                period=period,
                unit="percent",
                value=row.median_return_pct,
                source_type="primary",
                as_of=result.as_of,
            ),
            ref="toss-wts:overview+c-chart",
        ))
    return facts, claims, [raw]


async def run_price_macro(plan: PlanPacket,
                          snapshot: dict | None = None) -> PriceMacroPacket:
    """시세·매크로 브랜치.

    snapshot: eval bundle 모드. {"quotes": [...raw rows...], "macro": {...}} 형태.
              None이면 라이브 fetch (기존 경로 — 기본값 불변).
    """
    if snapshot is not None:
        # ── eval bundle 경로: 라이브 fetch 없이 _assemble 직행 (B2)
        quotes = snapshot.get("quotes", [])
        macro = snapshot.get("macro", {})
        facts, _ = _assemble(plan, quotes, macro)
        return PriceMacroPacket(
            meta=EnvelopeMeta(round=plan.meta.round, plan_ref=plan.plan_ref()),
            status="ok",
            quotes=[q for q in quotes if isinstance(q, dict)],
            macro=macro if isinstance(macro, dict) else {},
            typed_facts=facts,
        )

    # ── 라이브 경로 (기본값 — None이면 여기)
    since = None
    # "올해" 수익률 요구 — fiscal 표현 또는 metrics("올해 수익률", "기간 수익률", YTD)가 신호
    wants_ytd = any("YTD" in (fp.calendar_period or "") or fp.expression in ("올해", "연초")
                    for fp in plan.fiscal_periods)
    wants_ret = any(k in m for m in plan.metrics for k in ("수익률", "상승률", "올랐", "YTD", "ytd"))
    if wants_ytd or wants_ret:
        since = f"{plan.knowledge_cutoff[:4]}-01-02"

    tokens = [t.yahoo_symbol or t.code for t in plan.tickers if (t.yahoo_symbol or t.code)]
    sector_text = " ".join([
        plan.original_question,
        plan.standalone_question,
        *(
            f"{slot.entity} {slot.metric}"
            for slot in plan.needed_evidence
        ),
    ])
    wants_sector = is_sector_momentum_request(sector_text, plan.market_scope)

    macro_task = collect_macro()
    quote_task = quote(tokens, since=since) if tokens else _empty()
    sector_task = (
        collect_sector_momentum(
            lookback_sessions=parse_lookback_sessions(sector_text),
            cutoff=plan.knowledge_cutoff,
        )
        if wants_sector else _empty_sector()
    )
    macro, quotes, sector = await asyncio.gather(
        macro_task, quote_task, sector_task, return_exceptions=True
    )

    error = None
    if isinstance(macro, BaseException):
        error = f"macro: {macro}"; macro = {}
    if isinstance(quotes, BaseException):
        error = f"{error or ''} quote: {quotes}".strip(); quotes = []
    if isinstance(sector, BaseException):
        error = f"{error or ''} sector: {sector}".strip()
        sector = None

    facts, _ = _assemble(plan, quotes, macro)
    claims: list[AtomicClaim] = []
    extra_series: list[dict] = []
    if isinstance(sector, SectorMomentumResult):
        sector_facts, sector_claims, sector_series = _sector_evidence(sector, plan)
        facts.extend(sector_facts)
        claims.extend(sector_claims)
        extra_series.extend(sector_series)
        if sector.status != "ok":
            detail = sector.error or f"coverage {sector.coverage_pct}%"
            error = f"{error or ''} sector: {detail}".strip()

    # PER/EPS(TTM) 승격 — "A와 같은 PER이면 주가 얼마" 류 질문의 CALC 입력.
    # 해외 종목 PER 소스 부재로 계산 불가였던 갭 해소 (2026-07-09 woojin 피드백). never-raise.
    try:
        ok_quotes = [q for q in quotes if isinstance(q, dict) and "error" not in q and q.get("symbol")]
        funda = await fundamentals([q["symbol"] for q in ok_quotes]) if ok_quotes else {}
        for q in ok_quotes:
            f = funda.get(q["symbol"])
            if not f:
                continue
            if f.get("per") is not None:
                facts.append(TypedFact(
                    id=f"per:{q['token']}", value=round(float(f["per"]), 2), unit="배",
                    period="TTM", label=f"{q['token']} PER", source=f"yahoo:{q['symbol']}",
                ))
            if f.get("eps") is not None:
                facts.append(TypedFact(
                    id=f"eps:{q['token']}", value=float(f["eps"]),
                    unit=f.get("cur") or q.get("cur") or "",
                    period="TTM", label=f"{q['token']} EPS", source=f"yahoo:{q['symbol']}",
                ))
    except Exception:
        pass  # 밸류에이션 보강 실패가 시세 브랜치를 죽이면 안 됨

    status = "ok" if not error else (
        "degraded" if (macro or quotes or extra_series) else "error"
    )
    return PriceMacroPacket(
        meta=EnvelopeMeta(round=plan.meta.round, plan_ref=plan.plan_ref()),
        status=status,  # type: ignore[arg-type]
        error=error,
        quotes=[q for q in quotes if isinstance(q, dict)],
        macro=macro if isinstance(macro, dict) else {},
        extra_series=extra_series,
        typed_facts=facts,
        claims=claims,
    )


async def _empty():
    return []


async def _empty_sector():
    return None
