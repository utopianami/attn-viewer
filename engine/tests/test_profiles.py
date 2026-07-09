"""라우팅 Stage 1 — 프로필 선택·승급 규칙 (스펙 §6: 화이트리스트, 애매→풀코스, 승급 전용)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiles import PROFILES, select_profile, upgrade_if_needed  # noqa: E402


def test_registry_has_all_types_and_full():
    for k in ("fact_lookup", "event_interpretation", "stock_judgment",
              "industry_analysis", "strategy_portfolio", "full"):
        assert k in PROFILES


def test_stage1_whitelist_invariants():
    """Stage 1 금지 목록 — 어떤 프로필도 소스를 제거하지 못한다."""
    for p in PROFILES.values():
        assert p.da_mode in ("dual", "single")      # off 금지
        assert p.news_units_cap >= 1                # 뉴스 0콜 금지
        assert 1 <= p.reflect_max_rounds <= 2


def test_select_low_confidence_falls_back_to_full():
    p, reason = select_profile("fact_lookup", "low")
    assert p.name == "full" and "확신" in reason


def test_select_unknown_type_falls_back_to_full():
    p, _ = select_profile("unknown", "high")
    assert p.name == "full"


def test_select_known_type():
    p, _ = select_profile("fact_lookup", "high")
    assert p.name == "fact_lookup"
    assert p.da_mode == "single" and p.reflect_max_rounds == 1
    assert p.risk_mode == "off"


def test_upgrade_tier3_forces_full():
    """PLAN이 tier 3(판단)으로 판정하면 경량 프로필은 풀코스로 승급 (승급 전용)."""
    p, _ = select_profile("fact_lookup", "high")
    up, reason = upgrade_if_needed(p, tier=3)
    assert up.name == "full" and reason
    # 이미 무거운 프로필은 그대로 (강등 없음)
    same, r2 = upgrade_if_needed(PROFILES["full"], tier=3)
    assert same.name == "full" and r2 is None
