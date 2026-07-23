# engine/tests/test_chain_stage.py
import asyncio

import pytest

from contracts import AtomicClaim, ClaimTable, NewsItem, PlanPacket, RaPacket, TypedFact
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


def test_invalid_output_when_role_returns_non_chain_out():
    # r3-5 — LLM 호출은 성공(try#1 통과)하지만 반환 객체가 기대 형태(_ChainOut)가
    # 아니면(예: dict/None) 후처리(out.edges 접근)에서 AttributeError → invalid_output.
    class _WrongShape:
        model = "wrong-shape"
        async def run(self, *a, **k):
            return {"event": "x"}  # dict, not _ChainOut — .edges 접근 시 AttributeError

    cp, note = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [],
                                     role=_WrongShape()))
    assert cp is None and note == "invalid_output"


def test_invalid_output_when_role_returns_none():
    class _NoneShape:
        model = "none-shape"
        async def run(self, *a, **k):
            return None

    cp, note = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [],
                                     role=_NoneShape()))
    assert cp is None and note == "invalid_output"


def test_empty_string_citation_id_is_dropped():
    # r3-5 — NewsItem.id 기본값 ""이 실존 대조를 무의미하게 통과시키던 구멍.
    # 빈 id 뉴스 카드 + ""를 인용하는 제안 → 그 인용은 드롭되고(다른 근거 없으면 강등)
    ra = RaPacket(web_knowledge={"u1": [NewsItem(id="", title="무제목")]})
    proposal = {
        "event": "e", "mechanism": "m", "verdict": "",
        "edges": [{"edge": "B->A", "kind": "observed",
                   "supporting_card_ids": [""], "metric_fact_ids": [],
                   "contradicting_card_ids": []}],
        "thesis_relation": []}
    cp, note = asyncio.run(run_chain(_plan(), _table(), [], ra, [],
                                     role=_Role(proposal)))
    assert note == "" and cp is not None
    assert cp.edges[0].supporting_card_ids == []   # "" 인용 드롭
    assert cp.edges[0].kind == "inference"          # 근거 전무 → 강등


def test_duplicate_canonical_edge_merged_not_multiplied():
    # 3부 T11 블로커2 — 동일 canonical edge를 LLM이 N회 반복 제안해도 코드가 N개의
    # e0..e(N-1)을 부여하면 grounded_edge_ratio 등 eval 분모가 부풀려진다(codex
    # 최종 리뷰: grounded B->A 9회 + unsupported C->B 1회 → 10개 보존·ratio=0.9,
    # 실질 canonical 기준으로는 1/2=0.5). 첫 등장이 kind를 결정하고 인용은 순서
    # 보존 union — 후속 중복은 드롭(fail-hard 아님, 반복은 예상 가능 노이즈).
    edges = [{"edge": "B->A", "kind": "observed",
              "supporting_card_ids": [f"card-{i}"], "metric_fact_ids": [],
              "contradicting_card_ids": []} for i in range(9)]
    edges.append({"edge": "C->B", "kind": "observed", "supporting_card_ids": [],
                  "metric_fact_ids": [], "contradicting_card_ids": []})
    proposal = {"event": "e", "mechanism": "m", "verdict": "", "edges": edges,
                "thesis_relation": []}
    cards = [_card(f"card-{i}") for i in range(9)]
    cp, note = asyncio.run(run_chain(_plan(), _table(), cards, RaPacket(), [],
                                     role=_Role(proposal)))
    assert note == "" and cp is not None
    assert len(cp.edges) == 2                    # 9x B->A + 1x C->B → 2 merged edges
    e0 = next(e for e in cp.edges if e.edge == "B->A")
    e1 = next(e for e in cp.edges if e.edge == "C->B")
    assert e0.supporting_card_ids == [f"card-{i}" for i in range(9)]  # union, 순서보존
    assert e0.kind == "observed"
    assert e1.kind == "inference"                # 근거 전무(unsupported) → 강등


def test_card_fact_id_collision_ambiguous_citation_dropped():
    # 3부 T11 블로커1 — 카드 id와 fact id가 같은 문자열이면 각 집합(card_ids/fact_ids)
    # 에서 독립적으로 "유일"하게 보여 양쪽 다 인용 가능해지던 결함(codex 최종 리뷰).
    # 전 소스 통합 카운트(count==1만 인정)로 카드↔fact 충돌 id는 양쪽 다 드롭한다.
    table = ClaimTable(
        claims=[AtomicClaim(id="cl-1", text="x", type="fact", source="da_gpt")],
        typed_facts=[TypedFact(id="dup-id", value=1.0, unit="USD/GB")])
    proposal = {
        "event": "e", "mechanism": "m", "verdict": "",
        "edges": [{"edge": "B->A", "kind": "observed",
                   "supporting_card_ids": ["dup-id"], "metric_fact_ids": ["dup-id"],
                   "contradicting_card_ids": []}],
        "thesis_relation": []}
    cp, note = asyncio.run(run_chain(_plan(), table, [_card("dup-id")], RaPacket(), [],
                                     role=_Role(proposal)))
    assert note == "" and cp is not None
    e0 = cp.edges[0]
    assert e0.supporting_card_ids == []      # 카드↔fact 충돌 id → 드롭
    assert e0.metric_fact_ids == []          # 동일 id — 양쪽 다 드롭
    assert e0.kind == "inference"            # 근거 전무 → 강등


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
