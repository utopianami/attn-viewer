"""PRICE·MACRO 스테이지 — 시세(ticker) + 매크로(global). 전부 결정적, LLM 없음."""

from __future__ import annotations

import asyncio

from contracts import EnvelopeMeta, PlanPacket, PriceMacroPacket, TypedFact
from tools.price.macro import collect_macro
from tools.price.yahoo import fundamentals, quote


async def run_price_macro(plan: PlanPacket) -> PriceMacroPacket:
    since = None
    # "올해" 수익률 요구 — fiscal 표현 또는 metrics("올해 수익률", "기간 수익률", YTD)가 신호
    wants_ytd = any("YTD" in (fp.calendar_period or "") or fp.expression in ("올해", "연초")
                    for fp in plan.fiscal_periods)
    wants_ret = any(k in m for m in plan.metrics for k in ("수익률", "상승률", "올랐", "YTD", "ytd"))
    if wants_ytd or wants_ret:
        since = f"{plan.knowledge_cutoff[:4]}-01-02"

    tokens = [t.yahoo_symbol or t.code for t in plan.tickers if (t.yahoo_symbol or t.code)]

    macro_task = collect_macro()
    quote_task = quote(tokens, since=since) if tokens else _empty()
    macro, quotes = await asyncio.gather(macro_task, quote_task, return_exceptions=True)

    error = None
    if isinstance(macro, BaseException):
        error = f"macro: {macro}"; macro = {}
    if isinstance(quotes, BaseException):
        error = f"{error or ''} quote: {quotes}".strip(); quotes = []

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

    status = "ok" if not error else ("degraded" if (macro or quotes) else "error")
    return PriceMacroPacket(
        meta=EnvelopeMeta(round=plan.meta.round, plan_ref=plan.plan_ref()),
        status=status,  # type: ignore[arg-type]
        error=error,
        quotes=[q for q in quotes if isinstance(q, dict)],
        macro=macro if isinstance(macro, dict) else {},
        typed_facts=facts,
    )


async def _empty():
    return []
