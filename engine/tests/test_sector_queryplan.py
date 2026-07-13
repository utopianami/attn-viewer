"""SectorQueryPlan — 게이트·규칙 플랜·정제 (2026-07-13 LLM 쿼리 플래너 P1)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.queryplan import (  # noqa: E402
    PlanOutcome, SectorQueryPlan, build_rule_plan, is_sector_question, plan_query, sanitize_plan)


def test_gate_entity_and_topic():
    assert is_sector_question("하이닉스 실적 어때?")            # 엔티티
    assert is_sector_question("메모리 업황 지금 어디쯤이야?")    # 토픽
    assert is_sector_question("반도체 수출 사이클 어때")         # 반도체+보조어
    assert not is_sector_question("현대차 주가 어때?")          # 무관


def test_rule_plan_segments_and_metrics():
    p = build_rule_plan("HBM 공급 타이트해? 한국 수출도 궁금해")
    assert "hbm" in p.segments
    assert "kr_semi_export" in p.metrics
    assert p.days == 14 and p.sector == "memory"


def test_rule_plan_period_widening():
    assert build_rule_plan("6월에 메모리 쪽 무슨 일 있었어?").days == 90
    assert build_rule_plan("지난달 D램 가격 흐름은?").days == 90


def test_rule_plan_entities():
    p = build_rule_plan("삼성전자가 마이크론 따라잡을 수 있어?")
    assert {"SAMSUNG", "MICRON"} <= set(p.entities)


def test_sanitize_clamps_and_filters():
    dirty = SectorQueryPlan(
        segments=["hbm", "ssd"],                 # ssd는 세그먼트 아님
        entities=["SAMSUNG", "TESLA"],           # TESLA는 미등록
        metrics=["kr_semi_export", "bogus"],     # bogus 미등록
        event_types=["earnings", "bogus_type"],
        days=400, keywords=[" 점유율 ", "", "a", "b", "c", "d", "e", "f", "g", "h"])
    p = sanitize_plan(dirty)
    assert p.segments == ["hbm"]
    assert p.entities == ["SAMSUNG"]
    assert p.metrics == ["kr_semi_export"]
    assert p.event_types == ["earnings"]
    assert p.days == 90                          # [7, 90] 클램프
    assert len(p.keywords) <= 8 and "점유율" in p.keywords


class _FakeRole:
    """Role 대역 — run()이 준비된 값을 반환하거나 예외를 던진다."""
    def __init__(self, result=None, exc=None, delay=0.0):
        self._result, self._exc, self._delay = result, exc, delay

    async def run(self, prompt, instructions="", *, response_format=None, **kw):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc:
            raise self._exc
        return self._result


def test_plan_query_gate_miss(monkeypatch):
    out = asyncio.run(plan_query("현대차 주가 어때?"))
    assert out is None


def test_plan_query_llm_success(monkeypatch):
    from sector import queryplan
    fake = SectorQueryPlan(segments=["hbm"], metrics=["kr_semi_export"],
                           keywords=["점유율"], days=30)
    monkeypatch.setattr(queryplan, "_make_role", lambda overrides: _FakeRole(result=fake))
    out = asyncio.run(plan_query("HBM 요즘 어때?"))
    assert isinstance(out, PlanOutcome) and not out.fallback
    assert out.plan.segments == ["hbm"] and out.plan.days == 30
    assert out.rule_plan.segments == ["hbm"]     # 대조 로그용 규칙 플랜 동봉
    assert out.planner_ms >= 0


def test_plan_query_llm_error_falls_back(monkeypatch):
    from sector import queryplan
    monkeypatch.setattr(queryplan, "_make_role",
                        lambda overrides: _FakeRole(exc=RuntimeError("api down")))
    out = asyncio.run(plan_query("HBM 요즘 어때?"))
    assert out.fallback and out.plan == out.rule_plan


def test_plan_query_timeout_falls_back(monkeypatch):
    from sector import queryplan
    fake = _FakeRole(result=SectorQueryPlan(), delay=1.0)
    monkeypatch.setattr(queryplan, "_make_role", lambda overrides: fake)
    out = asyncio.run(plan_query("HBM 요즘 어때?", timeout=0.05))
    assert out.fallback


def test_plan_query_empty_llm_plan_uses_rule(monkeypatch):
    """플래너가 아무것도 못 고르면 규칙 플랜이 더 안전하다."""
    from sector import queryplan
    monkeypatch.setattr(queryplan, "_make_role",
                        lambda overrides: _FakeRole(result=SectorQueryPlan()))
    out = asyncio.run(plan_query("D램 현물가 어때?"))
    assert not out.fallback
    assert out.plan.segments == ["dram"]         # rule_plan으로 대체됨
