"""SectorQueryPlan — 게이트·규칙 플랜·정제 (2026-07-13 LLM 쿼리 플래너 P1)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.queryplan import (  # noqa: E402
    SectorQueryPlan, build_rule_plan, is_sector_question, sanitize_plan)


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
