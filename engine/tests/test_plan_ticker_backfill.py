"""G0 티커 역보충 오프라인 테스트 — "우리 삼성이" 축약 표현 케이스 (2026-07-09).

질문 텍스트 사전매칭과 LLM 보완이 모두 놓쳐도, needed_evidence의 정식명이
universe에 정확히 있으면 결정적으로 복원한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stages.plan as plan_mod  # noqa: E402


def test_backfill_from_needed_evidence(monkeypatch):
    monkeypatch.setattr(plan_mod, "_load_universe",
                        lambda: [{"name": "삼성전자", "code": "005930"}])
    a = plan_mod._PlanA(
        standalone_question="삼성전자가 애플과 같은 PER이면 주가는?",
        tier=3, knowledge_cutoff="2026-07-09",
        needed_evidence=[plan_mod._NeedEv(entity="삼성전자", metric="EPS",
                                             source_type="company")],
    )
    b = plan_mod._PlanB()
    # 질문 원문엔 "삼성전자" 정확명이 없음 → 사전매칭 0건
    packet = plan_mod._g0_merge("우리 삼성이 애플이랑 같은 PER이면 주가가 얼마지?", [], a, b)
    names = {(t.name, t.code) for t in packet.tickers}
    assert ("삼성전자", "005930") in names
    assert any("역보충" in n for n in packet.g0_notes)


def test_no_backfill_for_unknown_entity(monkeypatch):
    """universe에도 글로벌 별칭에도 없는 엔티티는 보충하지 않는다 (오염 방지)."""
    monkeypatch.setattr(plan_mod, "_load_universe",
                        lambda: [{"name": "삼성전자", "code": "005930"}])
    a = plan_mod._PlanA(
        standalone_question="q", tier=1, knowledge_cutoff="2026-07-09",
        needed_evidence=[plan_mod._NeedEv(entity="듣보잡상사", metric="PER",
                                             source_type="price")],
    )
    packet = plan_mod._g0_merge("듣보잡상사 PER?", [], a, plan_mod._PlanB())
    assert all(t.name != "듣보잡상사" for t in packet.tickers)


def test_alias_backfill_from_needed_evidence(monkeypatch):
    """needed_evidence의 글로벌 별칭 엔티티(Apple)도 역보충된다."""
    monkeypatch.setattr(plan_mod, "_load_universe", lambda: [])
    a = plan_mod._PlanA(
        standalone_question="q", tier=1, knowledge_cutoff="2026-07-09",
        needed_evidence=[plan_mod._NeedEv(entity="Apple", metric="PER",
                                             source_type="price")],
    )
    packet = plan_mod._g0_merge("아까 그 회사 PER?", [], a, plan_mod._PlanB())
    assert any(t.yahoo_symbol == "AAPL" for t in packet.tickers)


def test_global_alias_prematch():
    """질문 텍스트의 글로벌 별칭은 LLM 없이 결정적으로 프리매칭된다."""
    out = plan_mod._prematch_tickers("우리 삼성이 애플이랑 같은 PER이면? 마이크론이랑은?")
    syms = {t.yahoo_symbol for t in out}
    assert "AAPL" in syms and "MU" in syms


def test_ticker_dedup_by_symbol(monkeypatch):
    """같은 심볼이 다른 이름으로 중복 유입되면 1개만 남긴다."""
    monkeypatch.setattr(plan_mod, "_load_universe",
                        lambda: [{"name": "삼성전자", "code": "005930"}])
    from contracts import TickerCandidate
    pre = [TickerCandidate(name="Samsung Electronics", yahoo_symbol="005930.KS",
                           confidence="low", source="llm")]
    a = plan_mod._PlanA(
        standalone_question="q", tier=2, knowledge_cutoff="2026-07-09",
        needed_evidence=[plan_mod._NeedEv(entity="삼성전자", metric="EPS",
                                          source_type="company")])
    packet = plan_mod._g0_merge("우리 삼성이?", pre, a, plan_mod._PlanB())
    syms = [t.yahoo_symbol for t in packet.tickers]
    assert syms.count("005930.KS") == 1


def test_llm_ticker_code_filled_from_symbol(monkeypatch):
    """LLM 보완 국내 티커(심볼만, code 없음)에 code를 보정 — 토스 수집 대상 자격."""
    monkeypatch.setattr(plan_mod, "_load_universe", lambda: [])
    from contracts import TickerCandidate
    pre = [TickerCandidate(name="삼성전자", yahoo_symbol="005930.KS",
                           confidence="low", source="llm")]
    a = plan_mod._PlanA(standalone_question="q", tier=2, knowledge_cutoff="2026-07-09")
    packet = plan_mod._g0_merge("우리 삼성이?", pre, a, plan_mod._PlanB())
    t = next(t for t in packet.tickers if t.name == "삼성전자")
    assert t.code == "005930"
