"""sector judge — 배치 판정·후검증·카드 변환 (P1 Task 7)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector import judge  # noqa: E402
from sector.contracts import RawNewsItem  # noqa: E402


def _items(n=2):
    return [RawNewsItem(id=f"i{k}", title=f"hynix HBM {k}", content="본문",
                        source="reuters.com", url=f"http://n/{k}",
                        published_at="2026-07-06T09:00:00Z") for k in range(n)]


def test_judge_drops_irrelevant_and_validates(monkeypatch):
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, prompt, instructions="", *, response_format=None, **kw):
            return judge._JudgeBatch(rows=[
                judge._JudgeRow(idx=0, relevant=True, axis="WRONG", direction="bogus",
                                magnitude=9, interpreted_signal="sig"),
                judge._JudgeRow(idx=1, relevant=False),
            ])
    monkeypatch.setattr(judge, "Role", FakeRole)
    cards = asyncio.run(judge.judge_items(_items()))
    assert len(cards) == 1
    c = cards[0]
    assert c.axis == "B" and c.direction == "neutral" and c.magnitude == 3  # clamp 9→3
    assert c.source_grade == "B"          # reuters → B
    assert c.interpreted_signal == "sig" and c.raw_quote == "본문"


def test_judge_respects_grade_hint(monkeypatch):
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, *a, **k):
            return judge._JudgeBatch(rows=[judge._JudgeRow(idx=0, relevant=True)])
    monkeypatch.setattr(judge, "Role", FakeRole)
    it = _items(1)[0]
    it.grade_hint = "D"
    cards = asyncio.run(judge.judge_items([it]))
    assert cards[0].source_grade == "D"


def test_judge_batches_over_40(monkeypatch):
    calls = []
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, prompt, **kw):
            calls.append(prompt)
            return judge._JudgeBatch(rows=[])
    monkeypatch.setattr(judge, "Role", FakeRole)
    asyncio.run(judge.judge_items(_items(41)))
    assert len(calls) == 2
