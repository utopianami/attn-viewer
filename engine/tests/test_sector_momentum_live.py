"""KOSPI 업종 모멘텀 실데이터 스모크 (수동/야간 전용)."""

from __future__ import annotations

import asyncio

import pytest

from tools.toss.sector_momentum import collect_sector_momentum

pytestmark = pytest.mark.live


def test_sector_momentum_live_same_trading_window():
    result = asyncio.run(collect_sector_momentum(
        lookback_sessions=3,
        universe_size=80,
        min_members=2,
    ))
    assert result.status in {"ok", "partial"}
    assert result.as_of and result.base_session
    assert result.universe_valid >= 50
    assert result.coverage_pct >= 60
    assert result.sector_count >= 5
    assert result.sectors
    assert all(row.member_count >= 2 for row in result.sectors)
