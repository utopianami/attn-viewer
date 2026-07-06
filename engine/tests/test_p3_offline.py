"""P3 CALC 확장 오프라인 테스트 — 공식 매칭 · 토스 재무 승격 · missing 합류.

① match_formula 동의어 매핑 (구체 표현 우선: "올해 수익률" → ytd, "수익률" → period)
② 공식 템플릿 프로그램이 finance_math에서 실제로 도는지 (결정적 실행)
③ 토스 per → TypedFact 승격 (assemble)
④ calc_missing → answerability 프리패스 보완질문 합류
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    ClaimTable,
    DaPacket,
    PlanPacket,
    PriceMacroPacket,
    RaPacket,
    TickerCandidate,
    TypedFact,
)
from stages.assemble import run_assemble  # noqa: E402
from tools.calc.finance_math import evaluate  # noqa: E402
from tools.calc.formulas_kr import FORMULAS, match_formula  # noqa: E402


def _plan(**kw):
    base = dict(tier=2, original_question="q", standalone_question="q",
                knowledge_cutoff="2026-07-03")
    base.update(kw)
    return PlanPacket(**base)


def test_match_formula():
    assert match_formula("올해 수익률(%)") == "ytd_return"
    assert match_formula("연초 대비 상승률") == "ytd_return"
    assert match_formula("기간 수익률") == "period_return"
    assert match_formula("등락률") == "period_return"
    assert match_formula("PER 밸류에이션") == "per"
    assert match_formula("전년 동기 대비 성장") == "yoy"
    assert match_formula("목표가 괴리율") == "gap_pct"
    assert match_formula("배당수익률") == "div_yield"
    assert match_formula("수주잔고") is None


def test_formula_programs_execute():
    """모든 템플릿이 finance_math에서 결정적으로 실행되는지 (자리표시자 → fact id 치환)."""
    fact_vals = {"price_now": 110.0, "price_yearstart": 100.0, "price_base": 100.0,
                 "eps_ttm": 10.0, "bps": 55.0, "dps": 3.0,
                 "value_now": 120.0, "value_prev_year": 100.0, "value_prev_q": 110.0,
                 "value_a": 110.0, "value_b": 100.0}
    units = {"price_now": "KRW", "price_yearstart": "KRW", "price_base": "KRW",
             "eps_ttm": "KRW", "bps": "KRW", "dps": "KRW",
             "value_now": "KRW", "value_prev_year": "KRW", "value_prev_q": "KRW",
             "value_a": "KRW", "value_b": "KRW"}
    from stages.calc import _coerce_args
    for key, f in FORMULAS.items():
        facts = [{"id": i, "value": fact_vals[i], "unit": units[i], "label": i}
                 for i in f["inputs"]]
        # 실경로 동일: 프로그램 args는 calc.py _coerce_args를 거쳐 evaluate에 들어간다
        program = [{"op": s["op"], "args": _coerce_args(list(s["args"])), "out": s["out"]}
                   for s in f["program"]]
        out = evaluate({"typed_facts": facts, "program": program})
        assert not out.get("errors"), f"{key}: {out.get('errors')}"
        assert out["checks"]["units_consistent"], f"{key}: 단위 불일치"
        v = out["result"]["value"]
        if key == "ytd_return":
            assert abs(float(v) - 10.0) < 1e-6, (key, v)
        if key == "per":
            assert abs(float(v) - 11.0) < 1e-6, (key, v)


def test_toss_per_promoted():
    plan = _plan(tickers=[TickerCandidate(name="카카오", code="035720")])
    ra = RaPacket(toss_company={"035720": {"info_per": 42.5, "news": []}})
    pm = PriceMacroPacket(typed_facts=[
        TypedFact(id="price:카카오", value=35500, unit="KRW", label="카카오 현재가")])
    table = run_assemble(plan, DaPacket(unit_answers=[]), ra, pm)
    ids = {f.id: f for f in table.typed_facts}
    assert "toss:035720:per" in ids, table.typed_facts
    assert ids["toss:035720:per"].unit == "ratio" and "카카오" in ids["toss:035720:per"].label
    # per=None/0이면 승격 안 됨
    ra2 = RaPacket(toss_company={"035720": {"info_per": None}})
    t2 = run_assemble(plan, DaPacket(unit_answers=[]), ra2, pm)
    assert "toss:035720:per" not in {f.id for f in t2.typed_facts}


def test_calc_missing_joins_answerability():
    from stages.answerability import run_answerability

    async def _no_llm(self, *a, **k):
        raise RuntimeError("offline")
    import stages.answerability as ans_mod
    orig = ans_mod.Role.run
    ans_mod.Role.run = _no_llm
    try:
        plan = _plan(tickers=[TickerCandidate(name="카카오", code="035720")])
        res = asyncio.run(run_answerability(
            plan, ClaimTable(), RaPacket(),
            calc_missing=[{"metric": "배당수익률", "needed": "2025년 연간 주당배당금"}]))
        qs = res.queries()
        assert any("주당배당금" in q and "카카오" in q for q in qs), qs
    finally:
        ans_mod.Role.run = orig


if __name__ == "__main__":
    test_match_formula()
    test_formula_programs_execute()
    test_toss_per_promoted()
    test_calc_missing_joins_answerability()
    print("p3 offline: all passed")
