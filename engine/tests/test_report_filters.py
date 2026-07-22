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


def test_f1_cards_pass_without_llm_and_news_filtered():
    raw = [RawNewsDoc(id="n1", title="MU HBM", created_at="2026-07-21T09:00:00+00:00"),
           RawNewsDoc(id="n2", title="날씨", created_at="2026-07-21T09:00:00+00:00")]
    cards = [SectorCard(id="c1", ts="2026-07-21T08:00:00+00:00", axis="A", title="카드")]
    role = _RowsRole([{"idx": 0, "relevant": True, "reason": "HBM"},
                      {"idx": 1, "relevant": False, "reason": "무관"},
                      {"idx": 0, "relevant": False, "reason": "중복행-무시"}])  # dup → 첫 행 유지
    res = asyncio.run(filter_relevance(raw, cards, role=role))
    ids = [e.id for e in res.output]
    assert "c1" in ids and "n1" in ids and "n2" not in ids     # 카드 무조건 통과
    assert res.output[0].kind == "card"                         # 카드 먼저, 안정 정렬
    assert res.io.in_count == 3 and res.io.out_count == 2
    assert any(d["reason"] == "무관" for d in res.io.dropped)
    assert res.error is None


def test_f1_fail_closed_on_llm_error_but_cards_survive():
    raw = [RawNewsDoc(id="n1", title="x", created_at="2026-07-21T09:00:00+00:00")]
    cards = [SectorCard(id="c1", ts="2026-07-21T08:00:00+00:00", axis="A", title="카드")]
    res = asyncio.run(filter_relevance(raw, cards, role=_RaiseRole()))
    assert [e.id for e in res.output] == ["c1"]                # 뉴스만 fail-closed drop
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
