"""라우팅 Stage 1 — 프로필 해석 순수 함수 (오케스트레이터 접합부 검증)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiles import PROFILES  # noqa: E402
from routing import resolve, risk_forced  # noqa: E402
from stages.triage import TriageResult  # noqa: E402


def _t(**kw):
    base = dict(route="deep", question_type="fact_lookup", type_confidence="high")
    base.update(kw)
    return TriageResult(**base)


def test_resolve_picks_type_profile():
    p, reason = resolve(_t())
    assert p.name == "fact_lookup" and reason


def test_resolve_low_confidence_full():
    p, _ = resolve(_t(type_confidence="low"))
    assert p.name == "full"


def test_risk_forced_by_tier():
    """tier 3은 프로필이 off여도 RISK 강제 — tier 안전 제어 우선."""
    assert risk_forced(PROFILES["fact_lookup"], _t(), tier=3) is True


def test_risk_forced_by_countercase_auto():
    t = _t(question_type="event_interpretation", requires_countercase=True)
    assert risk_forced(PROFILES["event_interpretation"], t, tier=2) is True
    t2 = _t(question_type="event_interpretation", requires_countercase=False)
    assert risk_forced(PROFILES["event_interpretation"], t2, tier=2) is False


def test_risk_off_profile_low_tier():
    assert risk_forced(PROFILES["fact_lookup"], _t(), tier=1) is False


def test_risk_force_on_profile():
    assert risk_forced(PROFILES["strategy_portfolio"], _t(question_type="strategy_portfolio"), tier=2) is True
