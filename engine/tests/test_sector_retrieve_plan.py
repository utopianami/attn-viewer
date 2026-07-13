"""플랜 기반 카드 스코어링 (2026-07-13 LLM 쿼리 플래너 P1)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import SectorCard  # noqa: E402
from sector.queryplan import SectorQueryPlan  # noqa: E402
from sector.retrieve import search, search_with_plan  # noqa: E402


def _card(id, *, seg="mixed", ents=(), et="demand_signal", direction="neutral",
          mag=1, grade="B", title="t", signal="s", days_ago=1) -> SectorCard:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return SectorCard(id=id, ts=ts, axis="A", entities=list(ents), event_type=et,
                      memory_segment=seg, direction=direction, magnitude=mag,
                      source_grade=grade, title=title, interpreted_signal=signal)


class _FakeStore:
    def __init__(self, cards):
        self._cards = cards

    def read_cards(self, *, days=14, **kw):
        return list(self._cards)


def test_segment_match_outranks_magnitude():
    """HBM 질문이면 저중요도 HBM 카드가 고중요도 낸드 카드보다 위."""
    cards = [_card("nand-big", seg="nand", mag=3),
             _card("hbm-small", seg="hbm", mag=1)]
    plan = SectorQueryPlan(segments=["hbm"])
    got = search_with_plan(_FakeStore(cards), plan, k=2)
    assert got[0].id == "hbm-small"


def test_keyword_overlap_boosts():
    cards = [_card("noise", title="무관한 카드", mag=2),
             _card("hit", title="SK하이닉스 HBM4 인증 통과", signal="점유율 방어", mag=1)]
    plan = SectorQueryPlan(keywords=["인증", "점유율"])
    got = search_with_plan(_FakeStore(cards), plan, k=2)
    assert got[0].id == "hit"


def test_direction_balance_kept():
    """스코어가 낮아도 pos·neg 각 2건은 보장 (기존 균형 원칙 유지)."""
    cards = ([_card(f"pos{i}", seg="hbm", direction="pos", mag=3) for i in range(10)]
             + [_card("neg1", direction="neg", mag=1),
                _card("neg2", direction="neg", mag=1)])
    plan = SectorQueryPlan(segments=["hbm"])
    got = search_with_plan(_FakeStore(cards), plan, k=6)
    assert sum(1 for c in got if c.direction == "neg") >= 2


def test_empty_plan_falls_back_to_magnitude_order():
    cards = [_card("small", mag=1), _card("big", mag=3)]
    got = search_with_plan(_FakeStore(cards), SectorQueryPlan(), k=2)
    assert got[0].id == "big"


def test_legacy_search_unchanged_with_real_index():
    """리팩터(_balanced_top 추출) 후에도 기존 search가 실제 index.jsonl에서 동작 (real upstream)."""
    root = Path(__file__).resolve().parents[2] / "storage/rag/memory_sector"
    if not (root / "index.jsonl").exists():
        return
    from sector.store import SectorStore
    store = SectorStore(root)
    got = search(store, days=14, k=12)
    if got:  # 최근 14일 카드가 있을 때만 의미 있는 검증
        assert len(got) <= 12
        assert all(hasattr(c, "magnitude") for c in got)


def test_search_with_plan_real_index_hbm():
    """실제 카드에서 HBM 플랜이 HBM/mixed 위주로 상위를 채우는지 (real upstream)."""
    root = Path(__file__).resolve().parents[2] / "storage/rag/memory_sector"
    if not (root / "index.jsonl").exists():
        return
    from sector.store import SectorStore
    store = SectorStore(root)
    plan = SectorQueryPlan(segments=["hbm"], days=30, keywords=["HBM"])
    got = search_with_plan(store, plan, k=8)
    if len(got) >= 4:
        top4 = got[:4]
        assert sum(1 for c in top4 if c.memory_segment in ("hbm", "mixed")) >= 2
