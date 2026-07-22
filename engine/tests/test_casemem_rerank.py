import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseMatch, CaseEpisode, Phase
from casemem.rerank import build_rerank_prompt, parse_rerank_response, rerank_matches


def _cand(eid, order, label, signals):
    return (CaseMatch(episode_id=eid, matched_phase_order=order, score=0.5,
                      surface_score=0.5), label, signals)


def test_prompt_exposes_signals_not_outcome():
    p = build_rerank_prompt(
        ["재고일수 상승"],
        [_cand("mem-2018", 1, "inventory_build", ["재고일수 상승", "고객 재고조정"])])
    assert "재고일수 상승" in p
    assert "inventory_build" in p
    assert "outcome" not in p.lower()          # 결과 누출 금지
    assert "0" in p and "1" in p               # 채점 범위 지시 존재


def test_parse_valid_json():
    got = parse_rerank_response('[{"i":0,"s":0.9},{"i":1,"s":0.2}]', n=2)
    assert got == {0: 0.9, 1: 0.2}


def test_parse_tolerates_prose_wrapping():
    got = parse_rerank_response('여기 결과: [{"i":0,"s":0.7}] 끝', n=1)
    assert got == {0: 0.7}


def test_parse_drops_out_of_range_and_bad_index():
    got = parse_rerank_response('[{"i":0,"s":1.5},{"i":9,"s":0.5},{"i":1,"s":0.3}]', n=2)
    assert got == {1: 0.3}                       # 1.5(범위밖)·index9(밖) 제외


def test_parse_total_garbage_returns_empty():
    assert parse_rerank_response("no json here", n=2) == {}
    assert parse_rerank_response("", n=2) == {}


def _ep(eid, order, label, signals):
    return CaseEpisode(id=eid, sector="memory", title=eid,
                       event_time="2018-01-01", knowable_at="2018-01-01",
                       phases=[Phase(order=order, label=label,
                                     period_start="2018-01-01", knowable_at="2018-01-01",
                                     identifying_signals=signals)])


def test_rerank_reorders_by_structural_score():
    # surface로는 A>B지만 구조 점수로 B>A 뒤집힘
    a = CaseMatch(episode_id="A", matched_phase_order=0, score=0.6, surface_score=0.6)
    b = CaseMatch(episode_id="B", matched_phase_order=0, score=0.5, surface_score=0.5)
    eps = {"A": _ep("A", 0, "capex_expansion", ["capex up"]),
           "B": _ep("B", 0, "inventory_build", ["inventory up"])}
    def fake(prompt): return '[{"i":0,"s":0.1},{"i":1,"s":0.9}]'
    out, failed = rerank_matches([a, b], ["x"], eps, fake, ws=0.4, wl=0.6)
    assert failed is False
    assert out[0].episode_id == "B"                # 구조로 역전
    assert out[0].reranked is True
    assert abs(out[0].score - (0.4*0.5 + 0.6*0.9)) < 1e-9
    assert out[0].structural_score == 0.9


def test_rerank_llm_raises_falls_back():
    a = CaseMatch(episode_id="A", matched_phase_order=0, score=0.6, surface_score=0.6)
    eps = {"A": _ep("A", 0, "capex_expansion", ["capex up"])}
    def boom(prompt): raise RuntimeError("timeout")
    out, failed = rerank_matches([a], ["x"], eps, boom)
    assert failed is True
    assert out == [a]                              # 원본 순서·값 보존
    assert out[0].reranked is False


def test_rerank_empty_parse_falls_back():
    a = CaseMatch(episode_id="A", matched_phase_order=0, score=0.6, surface_score=0.6)
    eps = {"A": _ep("A", 0, "capex_expansion", ["capex up"])}
    out, failed = rerank_matches([a], ["x"], eps, lambda p: "garbage")
    assert failed is True
    assert out[0].reranked is False


def test_rerank_empty_matches_noop():
    out, failed = rerank_matches([], ["x"], {}, lambda p: "[]")
    assert out == [] and failed is False


def test_rerank_nonstring_llm_return_falls_back():
    # llm_fn이 계약 위반(비문자열 반환)해도 폴백해야 — never-raise
    a = CaseMatch(episode_id="A", matched_phase_order=0, score=0.6, surface_score=0.6)
    eps = {"A": _ep("A", 0, "capex_expansion", ["capex up"])}
    out, failed = rerank_matches([a], ["x"], eps, lambda p: 12345)  # int 반환
    assert failed is True and out[0].reranked is False


def test_parse_nonstring_returns_empty():
    assert parse_rerank_response(None, n=2) == {}
    assert parse_rerank_response(99, n=2) == {}
