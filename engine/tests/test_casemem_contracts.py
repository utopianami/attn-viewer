import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import (
    CaseEpisode, Phase, Evidence, QuantRef, DistilledRule,
    CaseMatch, CaseQueryResult, _parse_ts, _to_utc,
)


def test_episode_roundtrip_with_phases():
    ep = CaseEpisode(
        id="mem-x", sector="memory", title="t",
        event_time="2018-01-01", knowable_at="2018-01-15",
        phases=[Phase(order=0, label="capex_expansion",
                      period_start="2018-01-01", knowable_at="2018-02-01",
                      identifying_signals=["capex guidance up"],
                      quant_backbone=[QuantRef(metric_name="memory_capex",
                                               expected_direction="up")],
                      evidence=[Evidence(source="IR", grade="A",
                                         quote="capex +30%", knowable_at="2018-02-01")])])
    dumped = ep.model_dump_json()
    back = CaseEpisode.model_validate_json(dumped)
    assert back.phases[0].label == "capex_expansion"
    assert back.phases[0].quant_backbone[0].expected_direction == "up"
    assert back.phases[0].evidence[0].grade == "A"


def test_distilled_rule_defaults_candidate():
    r = DistilledRule(id="r1", situation="s", event_time="1990", knowable_at="1990")
    assert r.status == "candidate"          # 검증 전엔 리포트 주입 자격 없음(설계 §4.3)


def test_parse_ts_normalizes_kst_to_utc():
    assert _parse_ts("2026-07-21T16:23:13+09:00") == datetime(2026, 7, 21, 7, 23, 13, tzinfo=timezone.utc)
    assert _parse_ts("2018-01-15") == datetime(2018, 1, 15, tzinfo=timezone.utc)
    assert _parse_ts("garbage") is None
    assert _parse_ts("") is None


def test_to_utc_adds_tz_when_naive():
    assert _to_utc(datetime(2026, 7, 21, 12, 0)) == datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def test_casematch_observability_defaults():
    from casemem.contracts import CaseMatch, CaseQueryResult
    m = CaseMatch(episode_id="e", matched_phase_order=0, score=0.5)
    assert m.surface_score == 0.0 and m.structural_score is None and m.reranked is False
    r = CaseQueryResult(as_of="2018-01-01", sector="memory", scanned=0,
                        dropped_after_as_of=0, dropped_sector=0)
    assert r.rerank_used is False and r.rerank_failed is False
