"""메모리 섹터 P1 — 구조화 검색 (magnitude 우선, direction 균형 보장)."""
from __future__ import annotations

from sector.contracts import SectorCard
from sector.queryplan import TOPIC_TERMS_BY_SECTOR
from sector.store import SectorStore


def _ranked(cards: list[SectorCard]) -> list[SectorCard]:
    """magnitude 내림차순 → ts 내림차순 안정 정렬."""
    # Python stable sort: secondary key 먼저, primary key 나중에
    result = sorted(cards, key=lambda c: c.ts, reverse=True)   # ts desc (secondary)
    result.sort(key=lambda c: c.magnitude, reverse=True)        # magnitude desc (primary)
    return result


def search(
    store: SectorStore,
    *,
    entities: list[str] | None = None,
    days: int = 14,
    k: int = 12,
) -> list[SectorCard]:
    """카드를 검색해 최대 k개 반환.

    정렬: magnitude 내림차순 → ts 내림차순.
    direction 균형: pos·neg 각각 min(2, 전체 보유 수) 개 이상 보장.
    entities가 주어지면 card.entities와 교집합이 있는 카드만 포함.
    """
    cards = store.read_cards(days=days)

    if entities:
        entity_set = set(entities)
        cards = [c for c in cards if entity_set.intersection(c.entities)]

    if not cards or k <= 0:
        return []

    cards = _ranked(cards)

    all_pos = [c for c in cards if c.direction == "pos"]
    all_neg = [c for c in cards if c.direction == "neg"]

    need_pos = min(2, len(all_pos))
    need_neg = min(2, len(all_neg))

    # 보장 슬롯: 최우선 pos·neg 카드를 reserved에 먼저 확보
    reserved_pos = all_pos[:need_pos]
    reserved_neg = all_neg[:need_neg]
    reserved_ids = {c.id for c in reserved_pos + reserved_neg}

    remaining_slots = k - len(reserved_pos) - len(reserved_neg)

    if remaining_slots < 0:
        # k가 매우 작은 경우 — reserved 내에서 magnitude 순으로 잘라냄
        return _ranked(reserved_pos + reserved_neg)[:k]

    # 나머지 슬롯은 magnitude 순위 상위 카드로 채움 (reserved 제외)
    free = [c for c in cards if c.id not in reserved_ids]
    fill = free[:remaining_slots]

    result = _ranked(reserved_pos + reserved_neg + fill)
    return result[:k]


_TOPIC_TERMS = TOPIC_TERMS_BY_SECTOR["memory"]  # 단일 소스 — queryplan (2026-07-13)


def search_for_question(store: SectorStore, question: str, *,
                        days: int = 14, k: int = 12) -> tuple[list[str], list[SectorCard]]:
    """질문 텍스트 → (감지 엔티티, 카드). 오케스트레이터 진입점.

    엔티티 미감지 = 메모리 섹터 무관 질문 → ([], []) (레이어 미방출).
    엔티티는 감지됐는데 매칭 카드 0건이면 **무필터 최신 카드로 폴백** —
    저장소 전체가 섹터 전용이므로 안전 (구세대 카드 entities=[] 자가 치유,
    2026-07-07 라이브 검증 발견).
    """
    from sector.entities import extract_entities
    ents = extract_entities(question)
    if not ents:
        # 회사명 없는 섹터 일반 질문 ("메모리 업황 어디쯤?", "D램 가격 어때") —
        # 토픽 키워드로 발동, 무필터 최신 카드 (2026-07-13: 가장 섹터스러운 질문이
        # 정작 0건이던 갭. 저장소 전체가 메모리 섹터 전용이라 무필터 안전)
        low = question.lower()
        topical = any(t in low for t in _TOPIC_TERMS) or             ("반도체" in low and any(w in low for w in ("업황", "사이클", "가격", "수급")))
        if not topical:
            return [], []
        return ["MEMORY_SECTOR"], search(store, days=days, k=k)
    cards = search(store, entities=ents, days=days, k=k)
    if not cards:
        cards = search(store, days=days, k=k)
    return ents, cards
