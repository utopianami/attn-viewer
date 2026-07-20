"""PRICE·MACRO 스테이지 — 시세(ticker) + 매크로(global). 전부 결정적, LLM 없음."""

from __future__ import annotations

import asyncio

from contracts import EnvelopeMeta, PlanPacket, PriceMacroPacket, TypedFact
from tools.price.macro import collect_macro
from tools.price.yahoo import fundamentals, quote


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

    macro_task = collect_macro()
    quote_task = quote(tokens, since=since) if tokens else _empty()
    macro, quotes = await asyncio.gather(macro_task, quote_task, return_exceptions=True)

    error = None
    if isinstance(macro, BaseException):
        error = f"macro: {macro}"; macro = {}
    if isinstance(quotes, BaseException):
        error = f"{error or ''} quote: {quotes}".strip(); quotes = []

    facts, _ = _assemble(plan, quotes, macro)

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
