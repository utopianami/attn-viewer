"""메모리 섹터 P1 — 구조화 검색 (magnitude 우선, direction 균형 보장)."""
from __future__ import annotations

import datetime as _dt

from sector.contracts import SectorCard
from sector.queryplan import TOPIC_TERMS_BY_SECTOR
from sector.store import SectorStore


def _ranked(cards: list[SectorCard]) -> list[SectorCard]:
    """magnitude 내림차순 → ts 내림차순 안정 정렬."""
    # Python stable sort: secondary key 먼저, primary key 나중에
    result = sorted(cards, key=lambda c: c.ts, reverse=True)   # ts desc (secondary)
    result.sort(key=lambda c: c.magnitude, reverse=True)        # magnitude desc (primary)
    return result


def _balanced_top(ranked: list[SectorCard], k: int) -> list[SectorCard]:
    """정렬된 카드에서 상위 k개 — pos·neg 각 min(2, 보유수) 보장. 입력 순서 보존."""
    pos = [c for c in ranked if c.direction == "pos"]
    neg = [c for c in ranked if c.direction == "neg"]
    reserved_ids = {c.id for c in pos[:min(2, len(pos))] + neg[:min(2, len(neg))]}
    if len(reserved_ids) >= k:
        return [c for c in ranked if c.id in reserved_ids][:k]
    fill = [c for c in ranked if c.id not in reserved_ids][:k - len(reserved_ids)]
    keep = reserved_ids | {c.id for c in fill}
    return [c for c in ranked if c.id in keep][:k]


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
    return _balanced_top(cards, k)


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


_GRADE_W = {"S": 1.0, "A": 0.8, "B": 0.5, "C": 0.3, "D": 0.1}


def _age_days(ts: str, now: _dt.datetime) -> float:
    """ts → 경과일수. 파싱 실패는 오래된 것으로 취급(never-raise)."""
    try:
        d = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return max(0.0, (now - d).total_seconds() / 86400)
    except Exception:  # noqa: BLE001 — ts 파싱 실패 카드는 오래된 것으로 취급
        return 999.0


def _score(c: SectorCard, plan, now: _dt.datetime) -> float:
    """플랜 관련성 + 중요도 + 최신성 + 출처 등급 가중합. 가중치는 상수로 시작 —
    튜닝은 sector_rag 레이어의 plan/rule_plan 로그가 쌓인 뒤 (스펙 §4)."""
    s = 0.0
    if plan.segments:
        if c.memory_segment in plan.segments:
            s += 3.0
        elif c.memory_segment == "mixed":
            s += 0.9
    if plan.entities and set(plan.entities) & set(c.entities):
        s += 2.0
    if plan.keywords:
        text = f"{c.title} {c.interpreted_signal} {c.raw_quote}".lower()
        s += 2.0 * sum(1 for kw in plan.keywords if kw.lower() in text) / len(plan.keywords)
    if plan.event_types and c.event_type in plan.event_types:
        s += 1.0
    s += c.magnitude / 3.0
    s += max(0.0, 1.0 - _age_days(c.ts, now) / max(plan.days, 1))
    s += _GRADE_W.get(c.source_grade, 0.3)
    return s


def search_with_plan(store: SectorStore, plan, *, k: int = 12) -> list[SectorCard]:
    """SectorQueryPlan 기반 검색 — LLM/규칙 플랜 공용 실행부."""
    cards = store.read_cards(days=plan.days)
    if not cards or k <= 0:
        return []
    now = _dt.datetime.now(_dt.timezone.utc)
    ranked = sorted(cards, key=lambda c: (_score(c, plan, now), c.ts), reverse=True)
    return _balanced_top(ranked, k)
