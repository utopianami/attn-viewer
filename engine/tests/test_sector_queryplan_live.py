"""LLM 플래너 라이브 검증 — 실제 상류 출력 층 (test-with-real-upstream-outputs).

실행: cd engine && .venv/bin/python -m pytest tests/test_sector_queryplan_live.py -v -m live
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402
from sector.queryplan import plan_query  # noqa: E402

pytestmark = pytest.mark.live

_NO_KEY = not (settings.claude_api_key or settings.openai_api_key)


@pytest.mark.skipif(_NO_KEY, reason="API 키 없음")
def test_live_planner_hbm_question():
    out = asyncio.run(plan_query("HBM 공급 요즘 타이트해?", timeout=20.0))
    assert out is not None and not out.fallback, "라이브 플래너가 폴백됨"
    assert "hbm" in out.plan.segments


@pytest.mark.skipif(_NO_KEY, reason="API 키 없음")
def test_live_planner_metric_routing():
    out = asyncio.run(plan_query("한국 반도체 수출 요즘 어때?", timeout=20.0))
    assert out is not None and not out.fallback
    assert "kr_semi_export" in out.plan.metrics


@pytest.mark.skipif(_NO_KEY, reason="API 키 없음")
def test_live_planner_period_widening():
    out = asyncio.run(plan_query("6월에 메모리 쪽 무슨 일 있었어?", timeout=20.0))
    assert out is not None and not out.fallback
    assert out.plan.days > 14
