import asyncio

import pytest

from evals.chain_judge import judge_edge_entailment
from evals.metrics import chain_layer, grounded_edge_ratio


def _layers(verdicts):
    return [
        {"kind": "layer", "name": "chain", "round": 0, "data": {
            "event": "e", "mechanism": "m", "verdict": "",
            "edges": [{"edge_id": "e0", "edge": "B->A", "kind": "observed",
                       "supporting_card_ids": ["card-1"], "metric_fact_ids": [],
                       "contradicting_card_ids": []},
                      {"edge_id": "e1", "edge": "A_prime->A", "kind": "inference",
                       "supporting_card_ids": [], "metric_fact_ids": [],
                       "contradicting_card_ids": []}],
            "thesis_relation": [],
            "typed_fact_snapshot": {                    # r2-7 — T5 방출면과 동형
                # r3-4 — 실 ID shape: price_macro.py:47 `price:{q['token']}`,
                # token=yahoo_symbol(price_macro.py:187) → 국내 종목은 000660.KS
                "price:000660.KS": {"label": "000660.KS 현재가", "value": 250000.0,
                                    "unit": "KRW", "source": "yahoo:000660.KS",
                                    "metric": "", "period": ""},
                "toss:000660:per": {"label": "SK하이닉스 PER", "value": 12.3,
                                    "unit": "ratio", "source": "toss:000660",
                                    "metric": "", "period": ""}}}},
        {"kind": "layer", "name": "verify", "round": 0, "data": {
            "counts": {"verified": 1, "unverified": 0, "rejected": 0},
            "chain_verdicts": verdicts}},
    ]


def test_grounded_ratio_denominator_is_chain_edge_set():
    # e1 verdict 누락 → False 계수 (분모 = 실제 edge 집합, r1-B9)
    layers = _layers([{"edge_id": "e0", "grounded": True, "note": ""}])
    assert chain_layer(layers)["edges"][0]["edge_id"] == "e0"
    assert grounded_edge_ratio(layers) == 0.5
    assert chain_layer([]) is None and grounded_edge_ratio([]) is None


def test_grounded_ratio_extra_or_duplicate_verdict_is_error():
    with pytest.raises(ValueError):                     # 미지 edge verdict (r1-B9)
        grounded_edge_ratio(_layers([{"edge_id": "e9", "grounded": True, "note": ""}]))
    with pytest.raises(ValueError):                     # 중복 verdict
        grounded_edge_ratio(_layers([{"edge_id": "e0", "grounded": True, "note": ""},
                                     {"edge_id": "e0", "grounded": False, "note": ""}]))


class _Role:
    model = "fake"
    def __init__(self, rows): self.rows, self.calls = rows, 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        return response_format.model_validate({"rows": self.rows})


_EDGES = _layers([])[0]["data"]["edges"]
_EV = {"card-1": "card-1: HBM 증설 본문"}


def test_judge_edge_entailment_ratio_over_all_edges_with_context():
    role = _Role([{"edge_id": "e0", "entailed": True, "reason": ""},
                  {"edge_id": "e1", "entailed": False, "reason": "근거 없음"}])
    ratio = asyncio.run(judge_edge_entailment(
        "cj-t", _EDGES, _EV, role, thesis_claims=["HBM 공급은 구조적으로 타이트하다"]))
    assert ratio == 0.5                                   # 분모 = 전체 edge
    assert asyncio.run(judge_edge_entailment("cj-t", [], _EV, role)) is None


def test_judge_edge_entailment_row_mismatch_returns_none():
    # 누락·중복·미지 edge_id 전부 invalid — 1회 재시도 후 None (r1-B9)
    missing = _Role([{"edge_id": "e0", "entailed": True, "reason": ""}])
    assert asyncio.run(judge_edge_entailment("cj-t", _EDGES, _EV, missing)) is None
    assert missing.calls == 2                             # 정확 1회 재시도
    unknown = _Role([{"edge_id": "e0", "entailed": True, "reason": ""},
                     {"edge_id": "e9", "entailed": True, "reason": ""}])
    assert asyncio.run(judge_edge_entailment("cj-t", _EDGES, _EV, unknown)) is None


def test_resolver_uses_full_snapshot_and_fails_hard_on_unresolved():
    # r2-7 — price:*·toss:* 인용이 chain layer 스냅샷만으로 정확 역참조
    # (r3-4 — ID는 실 shape: price:{token}, 국내는 price:000660.KS)
    from evals.chain_judge import resolve_edge_evidence
    layers = _layers([])
    edges = [{"edge_id": "e0", "supporting_card_ids": [],
              "metric_fact_ids": ["price:000660.KS", "toss:000660:per"],
              "contradicting_card_ids": []}]
    ev = resolve_edge_evidence(edges, None, layers)   # metric id는 bundle 불요
    assert "250000" in ev["price:000660.KS"] and "KRW" in ev["price:000660.KS"]
    assert "PER" in ev["toss:000660:per"]
    with pytest.raises(ValueError):                   # 미해석 = 측정 오류 fail-hard
        resolve_edge_evidence([{"edge_id": "e0", "supporting_card_ids": [],
                                "metric_fact_ids": ["price:ghost"],
                                "contradicting_card_ids": []}], None, layers)
    with pytest.raises(ValueError):                   # 빈 인용 id — 비공백 강제 (r3-4)
        resolve_edge_evidence([{"edge_id": "e0", "supporting_card_ids": [""],
                                "metric_fact_ids": [],
                                "contradicting_card_ids": []}], None, layers)


class _StubStore:
    # EvalBundle.store()의 소비면(read_cards)만 모사 — bundle.py:125 시그니처와 동형
    def __init__(self, cards): self._cards = cards
    def read_cards(self, **kw): return self._cards


class _StubBundle:
    # EvalBundle 소비면(store()·ra_news_items())만 모사 — bundle.py:159·162
    def __init__(self, cards, news): self._cards, self._news = cards, news
    def store(self): return _StubStore(self._cards)
    def ra_news_items(self): return self._news


def test_resolver_multi_resolution_is_error():
    # r3-4 — 같은 id가 스냅샷과 카드 양쪽에 실존 → 유일 해소 실패 = 측정 오류
    from evals.chain_judge import resolve_edge_evidence
    from tests.test_chain_stage import _card
    layers = _layers([])
    bundle = _StubBundle([_card("price:000660.KS")], [])
    with pytest.raises(ValueError):
        resolve_edge_evidence([{"edge_id": "e0", "supporting_card_ids": [],
                                "metric_fact_ids": ["price:000660.KS"],
                                "contradicting_card_ids": []}], bundle, layers)


def test_resolver_same_source_duplicate_news_is_error():
    # 3부 T11 블로커1 — dict comprehension({d["id"]: d for d in ...})이 동일 소스
    # 중복(같은 id의 뉴스 2건)을 조용히 덮어써(마지막 항목 승) 다중 해소를 은폐하던
    # 결함(codex 최종 리뷰). 카운트 기반이면 같은 소스 내 중복도 ValueError로 잡는다.
    from evals.chain_judge import resolve_edge_evidence
    layers = _layers([])
    bundle = _StubBundle([], [{"id": "dup-news", "title": "a"},
                              {"id": "dup-news", "title": "b"}])
    with pytest.raises(ValueError):
        resolve_edge_evidence([{"edge_id": "e0", "supporting_card_ids": ["dup-news"],
                                "metric_fact_ids": [], "contradicting_card_ids": []}],
                              bundle, layers)


def test_entailed_gate_pure_fn():
    from evals.run_eval import check_entailed_gate
    with_chain = {"id": "c1", "layers_had_chain": True, "entailed_edge_ratio": None}
    ok = {"id": "c2", "layers_had_chain": True, "entailed_edge_ratio": 0.8}
    no_chain = {"id": "c3", "layers_had_chain": False, "entailed_edge_ratio": None}
    assert check_entailed_gate([with_chain, ok, no_chain]) == ["c1"]  # 1부 1420행 게이트
