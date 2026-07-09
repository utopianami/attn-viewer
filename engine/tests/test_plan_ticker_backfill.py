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
    monkeypatch.setattr(plan_mod, "_load_universe",
                        lambda: [{"name": "삼성전자", "code": "005930"}])
    a = plan_mod._PlanA(
        standalone_question="q", tier=1, knowledge_cutoff="2026-07-09",
        needed_evidence=[plan_mod._NeedEv(entity="Apple", metric="PER",
                                             source_type="price")],
    )
    packet = plan_mod._g0_merge("애플 PER?", [], a, plan_mod._PlanB())
    assert all(t.name != "Apple" for t in packet.tickers)  # universe 밖 — 보충 안 함
