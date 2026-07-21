"""C1 평가 하네스 — metrics 오프라인 테스트 (LLM 불필요)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.metrics import question_metrics, keyword_check  # noqa: E402


def _layers():
    return [
        {"kind": "layer", "name": "triage", "round": 0,
         "data": {"route": "deep", "profile": "fact_lookup", "question_type": "fact_lookup",
                  "type_confidence": "high"}},
        {"kind": "layer", "name": "verify", "round": 0,
         "data": {"counts": {"verified": 8, "unverified": 2, "rejected": 0},
                  "retry_directives": [], "coverage_holes": 1}},
        {"kind": "layer", "name": "verify", "round": 1,
         "data": {"counts": {"verified": 9, "unverified": 1, "rejected": 0},
                  "retry_directives": [], "coverage_holes": 0}},
    ]


def _final_meta():
    return {"rounds": 1, "elapsed_s": 42.5,
            "cost": {"total_usd": 0.31},
            "audit": {"numeric_total": 10, "numeric_supported": 9,
                      "provenance_soundness": 0.8, "severe": False},
            "degraded": []}


def test_question_metrics_basic():
    m = question_metrics(_layers(), _final_meta())
    assert m["verified_ratio"] == 0.9          # 마지막 verify 라운드 기준 9/10
    assert m["numeric_supported_ratio"] == 0.9
    assert m["rounds"] == 1
    assert m["elapsed_s"] == 42.5
    assert m["cost_usd"] == 0.31
    assert m["profile"] == "fact_lookup"
    assert m["severe"] is False


def test_question_metrics_empty_layers():
    m = question_metrics([], {"rounds": 0, "elapsed_s": 1.0, "cost": {},
                              "audit": {}, "degraded": ["da"]})
    assert m["verified_ratio"] is None
    assert m["degraded"] == ["da"]


def test_keyword_check():
    ok, missing, hit = keyword_check("삼성전자 PER는 12배 수준입니다",
                                     must_include=["PER", "삼성전자"],
                                     must_not=["매수하세요"])
    assert ok and missing == [] and hit == []
    ok2, missing2, hit2 = keyword_check("지금 매수하세요",
                                        must_include=["PER"], must_not=["매수하세요"])
    assert not ok2 and missing2 == ["PER"] and hit2 == ["매수하세요"]


def test_keyword_check_alternatives_with_first():
    """리스트 항목 중 첫 번째 대체어 포함 시 충족."""
    ok, missing, hit = keyword_check("이건 큰 리스크가 있어요",
                                     must_include=[["리스크", "위험"], "삼성전자"],
                                     must_not=[])
    assert not ok and missing == ["삼성전자"] and hit == []


def test_keyword_check_alternatives_with_second():
    """리스트 항목 중 두 번째 대체어만 포함 시 충족."""
    ok, missing, hit = keyword_check("이건 위험이 높아요",
                                     must_include=[["리스크", "위험"], "삼성전자"],
                                     must_not=[])
    assert not ok and missing == ["삼성전자"] and hit == []


def test_keyword_check_alternatives_both_missing():
    """리스트 항목의 모든 대체어가 없으면 missing에 '|'.join으로 기록."""
    ok, missing, hit = keyword_check("삼성전자는 좋은 회사야요",
                                     must_include=[["리스크", "위험"], "삼성전자"],
                                     must_not=[])
    # 리스크|위험 중 둘 다 없어서 missing에 포함됨
    assert not ok and missing == ["리스크|위험"] and hit == []

    ok2, missing2, hit2 = keyword_check("삼성전자는 리스크가 높아요",
                                        must_include=[["리스크", "위험"], "삼성전자"],
                                        must_not=[])
    # 리스크|위험 중 첫 번째 있고, 삼성전자도 있으면 통과
    assert ok2 and missing2 == [] and hit2 == []


def test_question_metrics_playbook_matched():
    layers_with_pb = _layers() + [
        {"kind": "layer", "name": "playbook", "round": 0,
         "data": {"matched": "memory-cycle-direction"}}
    ]
    m = question_metrics(layers_with_pb, _final_meta())
    assert m["playbook_matched"] == "memory-cycle-direction"

def test_question_metrics_playbook_absent():
    m = question_metrics(_layers(), _final_meta())  # no playbook layer
    assert m["playbook_matched"] is None

def test_question_metrics_playbook_none_matched():
    layers_with_none = _layers() + [
        {"kind": "layer", "name": "playbook", "round": 0,
         "data": {"matched": None}}
    ]
    m = question_metrics(layers_with_none, _final_meta())
    assert m["playbook_matched"] is None


def test_must_not_negation_prefix_exception():
    from evals.metrics import keyword_check
    ok, _, hit = keyword_check("전망은 불확실합니다.", [], ["확실"])
    assert ok and not hit                      # 불확실 → 위반 아님
    ok, _, hit = keyword_check("상승이 확실합니다.", [], ["확실"])
    assert not ok and hit == ["확실"]           # 무접두 확실 → 위반
    _, _, hit = keyword_check("불확실하지만 결국 확실합니다.", [], ["확실"])
    assert hit == ["확실"]                      # 혼재 시 무접두 등장이 걸림
