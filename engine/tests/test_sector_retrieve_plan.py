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


def test_direction_balance_skips_irrelevant_cards():
    """플랜과 무관한 반대 방향 카드는 균형 예약으로 끌려오지 않음
    (codex 리뷰 M2: HBM 질문에 무관 낸드 neg 2장이 강제 포함되던 문제).
    mixed 카드는 관련 취급이라 기존 균형 테스트(neg=mixed)는 그대로 유지."""
    cards = ([_card(f"pos{i}", seg="hbm", direction="pos", mag=2) for i in range(6)]
             + [_card("nand-neg1", seg="nand", direction="neg", mag=3, grade="S"),
                _card("nand-neg2", seg="nand", direction="neg", mag=3, grade="S")])
    plan = SectorQueryPlan(segments=["hbm"])
    got = search_with_plan(_FakeStore(cards), plan, k=6)
    assert all(c.memory_segment != "nand" for c in got)


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


def test_plan_window_not_capped_at_500(tmp_path):
    """90일 플랜이 저장소 500장 캡에 잘려 오래된 카드를 못 보면 안 됨
    (codex 리뷰 H2: 실저장소 541장에서 6월 카드 전멸 재현)."""
    from sector.store import SectorStore
    store = SectorStore(tmp_path)
    recent = [_card(f"r{i}", days_ago=2) for i in range(520)]
    old_hbm = _card("june-hbm", seg="hbm", mag=3, days_ago=60)
    store.append_cards(recent + [old_hbm])
    plan = SectorQueryPlan(segments=["hbm"], days=90)
    got = search_with_plan(store, plan, k=12)
    assert any(c.id == "june-hbm" for c in got), "90일 창의 오래된 카드가 캡에 잘림"


def test_question_entities_hard_filter():
    """질문이 직접 언급한 회사(hard_entities)는 하드 필터 — 스코어 가산(+2)만으론
    타사 고중요도가 앞섬 (codex 리뷰 H3: 기존 search_for_question 의미 회귀)."""
    cards = [_card("other-high", ents=("SAMSUNG",), mag=3, grade="S"),
             _card("target-low", ents=("SK_HYNIX",), mag=1, days_ago=5)]
    plan = SectorQueryPlan(entities=["SK_HYNIX"])
    got = search_with_plan(_FakeStore(cards), plan, k=2, hard_entities=["SK_HYNIX"])
    assert [c.id for c in got] == ["target-low"]


def test_planner_inferred_entities_do_not_hard_filter():
    """플래너가 추론한 entities는 소프트 부스트만 — 회사명 없는 질문("6월에 무슨 일")
    에서 과잉 선택된 엔티티가 구세대 entities=[] 카드를 죽이면 완성 기준 3 실패
    (2026-07-13 라이브 재확인에서 발견)."""
    cards = [_card("old-noent", ents=(), seg="hbm", mag=3, grade="S", days_ago=40),
             _card("recent-ent", ents=("SAMSUNG",), mag=1, days_ago=2)]
    plan = SectorQueryPlan(entities=["SAMSUNG"], days=90)
    got = search_with_plan(_FakeStore(cards), plan, k=2)   # hard_entities 없음
    assert {c.id for c in got} == {"old-noent", "recent-ent"}


def test_hard_entities_zero_match_falls_back_unfiltered():
    """엔티티 매칭 0건이면 기존 원칙대로 무필터 폴백 (스펙 에러표)."""
    cards = [_card("a", ents=("SAMSUNG",)), _card("b", ents=())]
    plan = SectorQueryPlan(entities=["MICRON"])
    got = search_with_plan(_FakeStore(cards), plan, k=2, hard_entities=["MICRON"])
    assert len(got) == 2


def test_until_targets_past_window():
    """until이 있으면 그 시점 기준의 창 — 이후 카드는 제외, 최신성도 until 기준."""
    plan = SectorQueryPlan(until="2026-06-30", days=35)
    now = datetime.now(timezone.utc)
    june = _card("june", seg="hbm", mag=1)
    june.ts = "2026-06-25T00:00:00+00:00"
    july = _card("july", seg="hbm", mag=3, grade="S", days_ago=1)
    got = search_with_plan(_FakeStore([june, july]), plan, k=5)
    assert [c.id for c in got] == ["june"], "until 이후(7월) 카드가 섞임"


def test_timestamp_format_mixed_tiebreaker():
    """ts 포맷 혼재 — 파싱된 나이로 동점 처리되는지 검증.

    문자열 비교가 틀리는 실제 케이스는 타임존 혼재: KST(+09:00) 스탬프는
    같은 순간의 UTC 스탬프보다 날짜 문자열이 앞서 보인다.
    older(13일 01시 KST = 12일 16시 UTC)가 문자열로는 newer(12일 20시 UTC)보다
    크므로, 문자열 정렬이면 older가 먼저 나와 이 테스트가 깨진다
    (codex 리뷰 L2: 종전 테스트는 전제가 거짓이라 수정 전 코드도 통과했음).
    """
    from unittest.mock import patch

    now = datetime.now(timezone.utc)

    base = now - timedelta(hours=12)
    card_newer = _card("newer", seg="mixed")
    card_newer.ts = base.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    older_utc = base - timedelta(hours=4)          # 4시간 더 오래됨
    older_kst = older_utc + timedelta(hours=9)      # 같은 순간의 KST 표기 — 문자열은 더 큼
    card_older = _card("older", seg="mixed")
    card_older.ts = older_kst.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    assert card_older.ts > card_newer.ts            # 전제: 문자열 비교는 반대로 판단

    # 두 카드가 동점 스코어를 갖도록 _score 모킹
    with patch('sector.retrieve._score', return_value=5.0):
        cards = [card_older, card_newer]
        plan = SectorQueryPlan()
        got = search_with_plan(_FakeStore(cards), plan, k=2)
        # 나이 기반 정렬: 1일 전(age_days=1) 이 3일 전(age_days=3) 보다 먼저
        assert got[0].id == "newer", f"expected 'newer' first, got {got[0].id}"
        assert got[1].id == "older"
