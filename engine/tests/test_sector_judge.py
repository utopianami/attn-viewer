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


def test_judge_grade_matches_bare_source_names(monkeypatch):
    """라이브 발견 회귀 — SaveTicker source는 도메인이 아니라 'reuters' 표기명."""
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, *a, **k):
            return judge._JudgeBatch(rows=[judge._JudgeRow(idx=0, relevant=True)])
    monkeypatch.setattr(judge, "Role", FakeRole)
    it = _items(1)[0]
    it.source = "reuters"
    cards = asyncio.run(judge.judge_items([it]))
    assert cards[0].source_grade == "B"


def test_judge_cap_keeps_s_grade_first(monkeypatch):
    """라이브 발견 회귀 — 80건 상한이 뒤에 온 S급 공시를 버리면 안 됨."""
    seen_titles = []
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, prompt, **kw):
            seen_titles.append(prompt)
            return judge._JudgeBatch(rows=[])
    monkeypatch.setattr(judge, "Role", FakeRole)
    items = _items(81)                       # 상한 80 초과
    items[80].grade_hint = "S"               # 맨 마지막이 S급 공시
    items[80].title = "EDGAR-8K-MUST-SURVIVE"
    asyncio.run(judge.judge_items(items))
    assert any("EDGAR-8K-MUST-SURVIVE" in p for p in seen_titles)
