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
