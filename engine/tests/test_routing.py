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


def test_role_overrides_light_profile(monkeypatch):
    """경량 프로필 → planner/verifier/synthesizer sonnet, 사용자 overrides 우선."""
    from routing import role_overrides
    light = PROFILES["fact_lookup"]
    ov = role_overrides(light, None)
    assert ov["planner"][0][1].startswith("claude-sonnet") or "sonnet" in ov["planner"][0][1]
    assert ov["planner"][0][0] == "claude_cli"
    assert ov["planner"][1][0] == "codex_cli"
    assert "synthesizer" in ov and "verifier" in ov
    assert "verifier_cross" not in ov  # 교차 심판(gpt)은 유지
    # 사용자 overrides가 이김
    user = {"planner": [("codex_cli", "gpt-x", "low")]}
    ov2 = role_overrides(light, user)
    assert ov2["planner"] == [("codex_cli", "gpt-x", "low")]


def test_role_overrides_full_profile_passthrough():
    from routing import role_overrides
    user = {"planner": [("codex_cli", "gpt-x", "low")]}
    assert role_overrides(PROFILES["full"], user) is user
    assert role_overrides(PROFILES["full"], None) is None
