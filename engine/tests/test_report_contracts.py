import sys
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
