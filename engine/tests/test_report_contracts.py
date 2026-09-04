import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from pydantic import ValidationError

from sector.report_contracts import (
    Anchor,
    ClaimVerdict,
    EvidenceRef,
    EventCluster,
    FinalOpinion,
    NumericFact,
    PipelineStage,
    Report,
    ReportClaim,
    ReportPipeline,
    StageIO,
    StageResult,
)


def _report_fixture(cards, **overrides):
    report = {
        "id": "2026-09-04-4",
        "seq": 4,
        "generatedAt": "2026-09-04T18:30:00+09:00",
        "title": "AI 전력망이 시장을 이끈다",
        "window": {"from": "2026-09-04T06:30:00+09:00",
                   "to": "2026-09-04T18:30:00+09:00"},
        "finalOpinion": {"text": "카드 참조", "confidence": "중"},
        "claims": [],
        "pipeline": {"stages": []},
        "format": "axes",
        "cards": cards,
    }
    report.update(overrides)
    return report


OLD_FIXED_AXIS_REPORT = _report_fixture([
    {"axis": "macro", "title": "거시"},
    {"axis": "memory", "title": "메모리"},
    {"axis": "other", "title": "기타"},
], title="메모리")


def _scenarios():
    return [
        {
            "polarity": "positive",
            "thesis": "수요가 확대된다",
            "beneficiaries": [
                {"name": "전력 인프라", "kind": "sector", "direction": "direct",
                 "polarity": "benefit", "causalChain": "수요 증가 → 수주 증가",
                 "evidence": "전력 수요 전망"},
                {"name": "산업재", "kind": "sector", "direction": "indirect",
                 "polarity": "benefit", "causalChain": "수주 증가 → 설비 투자 증가",
                 "evidence": "설비 투자 계획"},
            ],
        },
        {
            "polarity": "negative",
            "thesis": "투자가 지연된다",
            "beneficiaries": [
                {"name": "전력 인프라", "kind": "sector", "direction": "direct",
                 "polarity": "damage", "causalChain": "금리 상승 → 발주 지연",
                 "evidence": "금리 민감도"},
                {"name": "산업재", "kind": "sector", "direction": "indirect",
                 "polarity": "damage", "causalChain": "발주 지연 → 가동률 하락",
                 "evidence": "가동률 자료"},
            ],
        },
    ]


TOPICS_V1_REPORT = _report_fixture([
    {"axis": "macro", "label": "거시", "topicKey": "macro", "title": "금리 경로",
     "scenarios": _scenarios()},
    {"axis": "topic1", "label": "AI 전력망", "topicKey": "ai-power-grid",
     "title": "AI 전력망이 시장을 이끈다", "scenarios": _scenarios()},
    {"axis": "topic2", "label": "방산 수출", "topicKey": "defense-exports",
     "title": "방산 수출의 재평가", "scenarios": _scenarios()},
], axisModel="topics_v1", leadAxis="topic1")


def test_claim_defaults_safe_and_id_required():
    c = ReportClaim(claim_id="c0", title="t")
    assert c.confidence == "낮" and c.status == "unverified"
    assert c.evidence == [] and c.evidence_refs == [] and c.numeric_facts == []
    assert c.precedent_grounded is False and c.load_bearing is False
    with pytest.raises(ValidationError):
        ReportClaim(title="no-id")  # claim_id 필수


def test_stage_result_output_required():
    io = StageIO(key="f1", label="x")
    with pytest.raises(ValidationError):
        StageResult(io=io)  # output 명시 필수(빈 결과도 명시)
    ok = StageResult(output=[], io=io)
    assert ok.output == [] and ok.error is None


def test_pipeline_items_are_strings_enforced():
    with pytest.raises(ValidationError):
        PipelineStage(key="f1", label="x", items=[{"title": "obj"}])  # 문자열만(뷰어 안전)
    p = ReportPipeline(stages=[PipelineStage(key="f1", label="x", items=["ok"])])
    assert p.stages[0].items == ["ok"]


def test_report_roundtrip_with_typed_pipeline():
    r = Report(id="2026-07-21-2", seq=2, generatedAt="x", title="t",
               window={"from": "a", "to": "b"},
               finalOpinion=FinalOpinion(text="hold", confidence="낮"),
               pipeline=ReportPipeline(stages=[]), diagnostics={})
    d = r.model_dump()
    assert d["pipeline"]["stages"] == [] and d["finalOpinion"]["confidence"] == "낮"


def test_numeric_fact_and_anchor():
    nf = NumericFact(anchor_id="memory_price_usd_per_gb:DRAM", value=3.5)
    a = Anchor(anchor_id="memory_price_usd_per_gb:DRAM", metric="memory_price_usd_per_gb",
               value=3.5, as_of="2026-07")
    assert nf.anchor_id == a.anchor_id


def test_cluster_and_verdict_roundtrip():
    ev = EvidenceRef(kind="news", id="n1", title="MU", ts="2026-07-21T09:00:00+00:00")
    cl = EventCluster(cluster_id="c1", title="MU", members=[ev])
    assert cl.members[0].kind == "news" and cl.topics == []
    v = ClaimVerdict(claim_id="c0", status="rejected", reasons=["시점 위반"])
    assert v.adjusted_confidence == "낮"


def test_report_accepts_old_fixed_axis_contract_without_axis_model():
    report = Report.model_validate(OLD_FIXED_AXIS_REPORT)
    assert report.axisModel is None
    assert [card.axis for card in report.cards] == ["macro", "memory", "other"]


def test_report_accepts_topics_v1_contract():
    report = Report.model_validate(TOPICS_V1_REPORT)
    assert report.axisModel == "topics_v1" and report.leadAxis == "topic1"
    assert report.cards[1].label == "AI 전력망"
    assert report.cards[1].topicKey == "ai-power-grid"
    assert report.cards[1].scenarios[0].beneficiaries[0].causalChain


@pytest.mark.parametrize("mutate", [
    lambda report: report["cards"].__setitem__(2, {
        **report["cards"][2], "axis": "other",
    }),
    lambda report: report["cards"][2].__setitem__("topicKey", "ai-power-grid"),
    lambda report: report["cards"][1].__setitem__("label", ""),
    lambda report: report.__setitem__("leadAxis", "other"),
    lambda report: report.__setitem__("title", "리드 카드와 다른 제목"),
    lambda report: report["cards"][0].__setitem__(
        "scenarios", report["cards"][0]["scenarios"][:1]),
    lambda report: report["cards"][0]["scenarios"][0].__setitem__(
        "beneficiaries", report["cards"][0]["scenarios"][0]["beneficiaries"][:1]),
    lambda report: report["cards"][0]["scenarios"][0]["beneficiaries"][0].__setitem__(
        "causalChain", ""),
    lambda report: report["cards"][0]["scenarios"][0]["beneficiaries"][0].update(
        {"name": "전력기업 (PWR)", "kind": "stock", "evidence": ""}),
])
def test_topics_v1_rejects_mixed_or_incomplete_contract(mutate):
    report = deepcopy(TOPICS_V1_REPORT)
    mutate(report)
    with pytest.raises(ValidationError):
        Report.model_validate(report)


@pytest.mark.parametrize("missing_field", ["kind", "direction", "polarity",
                                            "causalChain", "evidence"])
def test_topics_v1_requires_beneficiary_semantic_fields(missing_field):
    report = deepcopy(TOPICS_V1_REPORT)
    del report["cards"][0]["scenarios"][0]["beneficiaries"][0][missing_field]
    with pytest.raises(ValidationError):
        Report.model_validate(report)


def test_topics_v1_requires_non_empty_card_title():
    report = deepcopy(TOPICS_V1_REPORT)
    del report["cards"][2]["title"]
    with pytest.raises(ValidationError):
        Report.model_validate(report)


def test_topics_v1_error_card_rejects_non_empty_scenarios():
    report = deepcopy(TOPICS_V1_REPORT)
    report["cards"][2]["error"] = "generation timeout"
    with pytest.raises(ValidationError):
        Report.model_validate(report)


@pytest.mark.parametrize(("mutation", "expected_error"), [
    (lambda report: report["cards"][2].__setitem__("topicKey", "ai-power-grid"),
     "topicKey values must be unique"),
    (lambda report: report.__setitem__("title", "리드 카드와 다른 제목"),
     "must equal the leadAxis card title"),
])
def test_executable_transport_validator_rejects_topics_semantic_mismatch(
        tmp_path, mutation, expected_error):
    report = deepcopy(TOPICS_V1_REPORT)
    mutation(report)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    validator = Path(__file__).resolve().parents[2] / "scripts" / "validate_market_report.py"
    result = subprocess.run([sys.executable, str(validator), str(path)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stdout + result.stderr
    assert expected_error in result.stderr
