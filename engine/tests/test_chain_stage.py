# engine/tests/test_chain_stage.py
import asyncio

import pytest

from contracts import AtomicClaim, ClaimTable, PlanPacket, RaPacket, TypedFact
from sector.contracts import SectorCard
from stages.chain import run_chain, typed_fact_snapshot
from stages.thesis_context import ThesisPick
from tests.test_thesis_contracts import make_rev


def _plan():
    return PlanPacket(tier=3, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")


def _card(cid):
    return SectorCard(id=cid, ts="2026-07-20T00:00:00", axis="A", direction="pos",
                      magnitude=2, source_grade="A", title=f"t-{cid}",
                      interpreted_signal="sig", raw_quote="본문", url="https://a.com/1",
                      entities=["SK_HYNIX"])


def _table():
    return ClaimTable(
        claims=[AtomicClaim(id="cl-1", text="HBM 수요 강세", type="fact", source="da_gpt")],
        typed_facts=[TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB")])


class _Role:
    model = "fake-sonnet"
    def __init__(self, out): self.out, self.calls = out, 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        return response_format.model_validate(self.out)


_PROPOSAL = {
    "event": "HBM 증설 보도", "mechanism": "공급 확대 기대", "verdict": "혼조",
    "edges": [
        {"edge": "B->A", "kind": "observed",
         "supporting_card_ids": ["card-1", "ghost"],
         "metric_fact_ids": ["sector:dram_price", "no-such-fact"],
         "contradicting_card_ids": ["ghost2"]},
        {"edge": "C->B", "kind": "observed", "supporting_card_ids": ["ghost"],
         "metric_fact_ids": [], "contradicting_card_ids": []},
        {"edge": "A->A", "kind": "observed", "supporting_card_ids": ["card-1"],
         "metric_fact_ids": [], "contradicting_card_ids": []}],
    "thesis_relation": [
        {"thesis_revision_id": "hbm-tightness@2026-07-21T00:00:00",
         "relation": "supports"},
        {"thesis_revision_id": "ghost@2026-01-01T00:00:00", "relation": "contradicts"}]}


def test_code_validation_drops_demotes_assigns_ids_and_meta():
    picks = [ThesisPick(rev=make_rev(), freshness="fresh", score=3)]
    cp, note = asyncio.run(run_chain(_plan(), _table(), [_card("card-1")], RaPacket(),
                                     picks, round_=1, role=_Role(_PROPOSAL)))
    assert note == "" and cp is not None
    assert cp.meta.round == 1 and cp.meta.plan_ref.tier == 3   # 실제 생성 라운드 (판정 3)
    assert [e.edge_id for e in cp.edges] == ["e0", "e1"]
    e0, e1 = cp.edges
    assert e0.supporting_card_ids == ["card-1"]          # ghost 드롭
    assert e0.metric_fact_ids == ["sector:dram_price"]   # no-such-fact 드롭
    assert e0.contradicting_card_ids == []               # ghost2 드롭
    assert e0.kind == "observed"
    assert e1.kind == "inference"                        # 빈 supporting → 강등
    assert len(cp.edges) == 2                            # A->A 레지스트리 밖 → 드롭
    assert [t.thesis_revision_id for t in cp.thesis_relation] == \
        ["hbm-tightness@2026-07-21T00:00:00"]            # 미주입 revision 드롭


def test_never_raise_returns_reason_marker():
    class _Boom:
        model = "boom"
        async def run(self, *a, **k): raise RuntimeError("down")
    cp, note = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [],
                                     role=_Boom()))
    assert cp is None and note == "llm_error"            # B5 — 무음 None 금지


def test_all_edges_dropped_is_visible():
    bad = dict(_PROPOSAL, edges=[{"edge": "A->A", "kind": "observed",
                                  "supporting_card_ids": [], "metric_fact_ids": [],
                                  "contradicting_card_ids": []}])
    cp, note = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [],
                                     role=_Role(bad)))
    assert cp is None and note == "all_edges_dropped"


def test_snapshot_duplicate_fact_id_fails_hard():
    # r3-4 — dict 조립의 조용한 덮어쓰기 금지: 중복 ID는 방출 시점 오류
    snap = typed_fact_snapshot(_table())
    assert set(snap) == {"sector:dram_price"}
    assert snap["sector:dram_price"]["unit"] == "USD/GB"
    dup = ClaimTable(typed_facts=[
        TypedFact(id="price:000660.KS", value=250000.0, unit="KRW"),
        TypedFact(id="price:000660.KS", value=1.0, unit="KRW")])
    with pytest.raises(ValueError):
        typed_fact_snapshot(dup)
