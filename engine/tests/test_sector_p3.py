"""sector P3 — sector_rag 레이어 + synthesize 주입 통합 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Test 1: extract_entities ──────────────────────────────────────────────────

from sector.entities import extract_entities  # noqa: E402


def test_extract_entities_hynix():
    result = extract_entities("하이닉스 HBM 어때")
    assert "SK_HYNIX" in result


def test_extract_entities_irrelevant():
    result = extract_entities("오늘 날씨가 맑고 화창합니다")
    assert result == []


# ── Test 2: LAYER_NAMES에 sector_rag 존재 ────────────────────────────────────

from contracts.packets import LAYER_NAMES  # noqa: E402


def test_sector_rag_in_layer_names():
    assert "sector_rag" in LAYER_NAMES


# ── Test 3: _render_context sector_cards 렌더링 ───────────────────────────────

from contracts.packets import DaPacket, PlanPacket  # noqa: E402
from stages.synthesize import _render_context  # noqa: E402
from sector.contracts import SectorCard  # noqa: E402


def _mini_plan():
    return PlanPacket(tier=2, original_question="하이닉스 전망", standalone_question="하이닉스 전망",
                      knowledge_cutoff="2026-07-06")


def _make_card(title="Meta, 잉여 GPU 처분 계획", url="https://reuters.com/test"):
    return SectorCard(
        id="test-001",
        ts="2026-07-06T09:00:00Z",
        axis="B",
        direction="neg",
        magnitude=2,
        source_grade="B",
        title=title,
        interpreted_signal="메모리 수요 둔화 신호",
        raw_quote="원문 인용",
        url=url,
        entities=["META"],
    )


def test_render_context_includes_sector_cards():
    cards = [_make_card()]
    ctx = _render_context(_mini_plan(), DaPacket(status="ok"), None, None, None, None, [], None,
                          sector_cards=cards)
    assert "[메모리 섹터 근거]" in ctx
    assert "Meta, 잉여 GPU 처분 계획" in ctx


def test_render_context_excludes_sector_cards_when_none():
    ctx = _render_context(_mini_plan(), DaPacket(status="ok"), None, None, None, None, [], None,
                          sector_cards=None)
    assert "[메모리 섹터 근거]" not in ctx


def test_render_context_excludes_sector_cards_when_empty():
    ctx = _render_context(_mini_plan(), DaPacket(status="ok"), None, None, None, None, [], None,
                          sector_cards=[])
    assert "[메모리 섹터 근거]" not in ctx


# ── Test 4: judge 기존 동작 회귀 (entities 이동 후에도 동일 결과) ──────────────

import asyncio  # noqa: E402
from sector import judge  # noqa: E402
from sector.contracts import RawNewsItem  # noqa: E402


def _items(n=2):
    return [RawNewsItem(id=f"i{k}", title=f"hynix HBM {k}", content="본문",
                        source="reuters.com", url=f"http://n/{k}",
                        published_at="2026-07-06T09:00:00Z") for k in range(n)]


def test_judge_entities_regression(monkeypatch):
    """entities.py 분리 후에도 _extract_entities가 동일하게 동작해야 한다."""
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, prompt, instructions="", *, response_format=None, **kw):
            return judge._JudgeBatch(rows=[
                judge._JudgeRow(idx=0, relevant=True, axis="B", direction="pos",
                                magnitude=2, interpreted_signal="HBM 수요 증가"),
            ])
    monkeypatch.setattr(judge, "Role", FakeRole)
    cards = asyncio.run(judge.judge_items(_items(1)))
    assert len(cards) == 1
    # hynix → SK_HYNIX 엔티티 추출 확인
    assert "SK_HYNIX" in cards[0].entities


def test_search_for_question_fallback_when_entity_filter_empty(tmp_path):
    """엔티티 감지 + 매칭 0건 → 무필터 폴백 (구세대 entities=[] 카드 자가 치유)."""
    from sector.retrieve import search_for_question
    from sector.store import SectorStore
    from sector.contracts import SectorCard
    import datetime as _dt
    store = SectorStore(tmp_path)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    store.append_cards([SectorCard(id="old1", ts=now, axis="B", entities=[],
                                   title="구세대 카드", raw_quote="", url="", source="")])
    ents, cards = search_for_question(store, "SK하이닉스 HBM 어때?")
    assert "SK_HYNIX" in ents and [c.id for c in cards] == ["old1"]
    ents2, cards2 = search_for_question(store, "유럽 전력주 어때?")
    assert ents2 == [] and cards2 == []
