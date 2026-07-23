import asyncio

import pytest

from sector.thesis_contracts import Evidence, Statement
from sector.thesis_verify import VerificationFailed, verify_statements


def _st(sid, quotes):
    sup = [Evidence(card_id=f"c{sid}{i}", canonical_url=f"https://p{i}.com/1",
                    publisher_id=f"p{i}.com", quote=q) for i, q in enumerate(quotes)]
    return Statement(statement_id=sid, text="수요가 강하다", supporting=sup)


class _Role:
    model = "fake-gpt"
    def __init__(self, rows, relations): self.rows, self.relations = rows, relations
    async def run(self, prompt, instructions="", response_format=None, **kw):
        return response_format.model_validate({"rows": self.rows, "relations": self.relations})


def test_reject_and_relevance_and_direction():
    st = _st("s1", ["인용A", "인용B", "인용C"])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "c s10".replace(" ", ""), "supported": True, "why": ""},
                       {"statement_id": "s1", "card_id": "cs11", "supported": True, "why": ""},
                       {"statement_id": "s1", "card_id": "cs12", "supported": False, "why": "무관"}],
                 relations=[{"statement_id": "s1", "relevant": True, "direction": "supports"}])
    kept, directions, reasons = asyncio.run(verify_statements([st], "HBM 타이트", role))
    assert len(kept) == 1 and len(kept[0].supporting) == 2
    assert directions == {"s1": "supports"} and reasons     # 방향 Literal 그대로 (r2-B2)


def test_missing_or_duplicate_verdict_fails_closed():       # B1
    st = _st("s1", ["인용A", "인용B"])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "cs10", "supported": True, "why": ""}],
                 relations=[{"statement_id": "s1", "relevant": True, "direction": "supports"}])
    with pytest.raises(VerificationFailed):
        asyncio.run(verify_statements([st], "claim", role))  # cs11 판정 누락


def test_irrelevant_statement_dropped():                    # B2
    st = _st("s1", ["인용A", "인용B"])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "cs10", "supported": True, "why": ""},
                       {"statement_id": "s1", "card_id": "cs11", "supported": True, "why": ""}],
                 relations=[{"statement_id": "s1", "relevant": False, "direction": "neutral"}])
    kept, directions, _ = asyncio.run(verify_statements([st], "claim", role))
    assert kept == [] and directions == {}


def test_neutral_direction_dropped():                       # r2-B2
    st = _st("s1", ["인용A", "인용B"])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "cs10", "supported": True, "why": ""},
                       {"statement_id": "s1", "card_id": "cs11", "supported": True, "why": ""}],
                 relations=[{"statement_id": "s1", "relevant": True, "direction": "neutral"}])
    kept, directions, _ = asyncio.run(verify_statements([st], "claim", role))
    assert kept == [] and directions == {}                   # neutral은 저장 불가


def test_duplicate_input_pair_fails_closed():                # 2부 T9 블로커 6b
    """입력 statement 자체가 같은 (statement_id, card_id)를 두 번 가지면 fail-closed.

    expected_pairs가 set이면 이 중복이 조용히 하나로 뭉개져, LLM이 같은 카드를
    두 번 제안해도 한 verdict로 두 근거가 다 통과할 수 있었다 — 방어적 이중화.
    """
    ev = Evidence(card_id="cdup", canonical_url="https://p.com/1",
                 publisher_id="p.com", quote="같은 인용")
    st = Statement(statement_id="s1", text="수요가 강하다", supporting=[ev, ev.model_copy()])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "cdup", "supported": True, "why": ""}],
                 relations=[{"statement_id": "s1", "relevant": True, "direction": "supports"}])
    with pytest.raises(VerificationFailed):
        asyncio.run(verify_statements([st], "claim", role))
