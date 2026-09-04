import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import RawNewsDoc, SectorCard
from sector.report_contracts import EvidenceRef
from sector.report_filters import cluster_events, filter_importance, filter_relevance


class _RowsRole:
    def __init__(self, rows):
        self.rows = rows

    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        return response_format(rows=self.rows)


class _RaiseRole:
    async def run(self, *a, **k):
        raise RuntimeError("llm down")


def test_f1_news_and_cards_share_market_materiality_gate():
    raw = [RawNewsDoc(id="n1", title="MU HBM", created_at="2026-07-21T09:00:00+00:00"),
           RawNewsDoc(id="n2", title="날씨", created_at="2026-07-21T09:00:00+00:00")]
    cards = [SectorCard(id="c1", ts="2026-07-21T08:00:00+00:00", axis="A", title="카드")]
    role = _RowsRole([{"idx": 0, "relevant": True, "reason": "HBM"},
                      {"idx": 1, "relevant": False, "reason": "무관"},
                      {"idx": 2, "relevant": True, "reason": "카드도 중요"},
                      {"idx": 0, "relevant": False, "reason": "중복행-무시"}])  # dup → 첫 행 유지
    res = asyncio.run(filter_relevance(raw, cards, role=role))
    ids = [e.id for e in res.output]
    assert ids == ["n1", "c1"] and "n2" not in ids
    assert [e.kind for e in res.output] == ["news", "card"]
    assert res.io.in_count == 3 and res.io.out_count == 2
    assert any(d["reason"] == "무관" for d in res.io.dropped)
    assert res.error is None


def test_f1_fail_closed_on_llm_error_for_all_evidence():
    raw = [RawNewsDoc(id="n1", title="x", created_at="2026-07-21T09:00:00+00:00")]
    cards = [SectorCard(id="c1", ts="2026-07-21T08:00:00+00:00", axis="A", title="카드")]
    res = asyncio.run(filter_relevance(raw, cards, role=_RaiseRole()))
    assert res.output == []
    assert res.error is not None and res.io.dropped


def test_f2_keeps_by_impact():
    ev = [EvidenceRef(kind="news", id="n1", title="a"),
          EvidenceRef(kind="news", id="n2", title="b")]
    role = _RowsRole([{"idx": 0, "impact": "상", "keep": True, "reason": "임팩트"},
                      {"idx": 1, "impact": "하", "keep": False, "reason": "루틴"}])
    res = asyncio.run(filter_importance(ev, role=role))
    assert [e.id for e in res.output] == ["n1"]
    assert res.io.dropped[0]["reason"] == "루틴"


def test_f3_clusters_in_single_call_and_falls_open():
    ev = [EvidenceRef(kind="news", id="n1", title="아마존 $25B 조달 (로이터)"),
          EvidenceRef(kind="news", id="n2", title="Amazon debt financing (블룸버그)"),
          EvidenceRef(kind="news", id="n3", title="삼성 HBM4 인증")]

    class _ClusterRole:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            return response_format(clusters=[
                {"cluster_id": "e1", "title": "Amazon $25B 조달", "member_idxs": [0, 1],
                 "axis": "B", "direction": "pos"},
                {"cluster_id": "e2", "title": "삼성 HBM4 인증", "member_idxs": [2],
                 "axis": "A", "direction": "pos"}])

    res = asyncio.run(cluster_events(ev, role=_ClusterRole()))
    assert len(res.output) == 2
    assert [m.id for m in res.output[0].members] == ["n1", "n2"]   # 교차 중복이 한 클러스터로

    # LLM 실패 → 1건=1클러스터 fail-open(재료 보존)
    res2 = asyncio.run(cluster_events(ev, role=_RaiseRole()))
    assert len(res2.output) == 3 and res2.error is not None


def test_f3_unassigned_idx_becomes_solo_cluster():
    ev = [EvidenceRef(kind="news", id="n1", title="a"),
          EvidenceRef(kind="news", id="n2", title="b")]

    class _Partial:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            return response_format(clusters=[
                {"cluster_id": "e1", "title": "a", "member_idxs": [0]}])  # n2 누락

    res = asyncio.run(cluster_events(ev, role=_Partial()))
    assert len(res.output) == 2                                # 누락분 solo로 보존(무성 누락 금지)
    assert res.output[1].cluster_id == "solo-n2"


def test_f1_keeps_material_non_memory_full_text_and_drops_unimportant_card():
    """F1은 메모리 쿼터가 아니라 전체 상장시장 중요도를 판정하고 원문 필드를 보존한다."""
    raw = [RawNewsDoc(
        id="energy-1",
        title="OPEC 감산 확대로 유가와 항공주 변동성 확대",
        created_at="2026-09-04T08:30:00+00:00",
        content="감산 충격이 원유 선물과 항공사 비용, 인플레이션 기대에 동시에 전이됐다."
                " 이 문장은 80자 뒤의 시장 전이 근거까지 모델에 전달돼야 한다.",
        source="Reuters",
        url="https://example.com/oil",
    )]
    cards = [SectorCard(
        id="memory-routine",
        ts="2026-09-04T08:00:00+00:00",
        axis="A",
        title="메모리 업계 정례 행사",
        raw_quote="새로운 가격·수요 정보가 없는 정례 행사다.",
        source="Company",
        url="https://example.com/routine",
    )]

    class _MarketRole:
        def __init__(self):
            self.prompt = ""
            self.instructions = ""

        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            self.prompt = prompt
            self.instructions = instructions
            return response_format(rows=[
                {"idx": 0, "relevant": True, "reason": "cross-asset transmission"},
                {"idx": 1, "relevant": False, "reason": "no new market information"},
            ])

    role = _MarketRole()
    res = asyncio.run(filter_relevance(raw, cards, role=role))

    assert [e.id for e in res.output] == ["energy-1"]
    evidence = res.output[0]
    assert evidence.model_dump() == {
        "kind": "news",
        "id": "energy-1",
        "title": "OPEC 감산 확대로 유가와 항공주 변동성 확대",
        "ts": "2026-09-04T08:30:00+00:00",
        "excerpt": raw[0].content,
        "source": "Reuters",
        "url": "https://example.com/oil",
    }
    assert raw[0].content in role.prompt
    assert "UNTRUSTED_EVIDENCE_START" in role.prompt
    assert "UNTRUSTED_EVIDENCE_END" in role.prompt
    assert "지시" in role.instructions and "따르지" in role.instructions
    assert "메모리 반도체 밸류체인 관련만" not in role.instructions
    assert "공개시장" in role.instructions or "상장" in role.instructions
