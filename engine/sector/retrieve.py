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


def _balanced_top(ranked: list[SectorCard], k: int, eligible=None) -> list[SectorCard]:
    """정렬된 카드에서 상위 k개 — pos·neg 각 min(2, 보유수) 보장. 입력 순서 보존.

    eligible: 균형 예약 자격 predicate. 플랜 검색에서 무관 카드가 반대근거랍시고
    끌려오지 않게 (codex 리뷰 M2). None이면 전 카드 자격 (기존 search 경로)."""
    pool = ranked if eligible is None else [c for c in ranked if eligible(c)]
    pos = [c for c in pool if c.direction == "pos"]
    neg = [c for c in pool if c.direction == "neg"]
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


def _parse_ts(ts: str) -> _dt.datetime | None:
    """ISO ts → aware datetime. 실패 시 None (never-raise)."""
    try:
        d = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d.replace(tzinfo=_dt.timezone.utc) if d.tzinfo is None else d
    except Exception:  # noqa: BLE001
        return None


def _age_days(ts: str, now: _dt.datetime) -> float:
    """ts → 경과일수. 파싱 실패는 오래된 것으로 취급(never-raise)."""
    d = _parse_ts(ts)
    if d is None:
        return 999.0
    return max(0.0, (now - d).total_seconds() / 86400)


def _score(c: SectorCard, plan, now: _dt.datetime) -> float:
    """플랜 관련성 + 중요도 + 최신성 + 출처 등급 가중합. 가중치는 상수로 시작 —
    튜닝은 sector_rag 레이어의 plan/rule_plan 로그가 쌓인 뒤 (스펙 §4)."""
    s = 0.0
    if plan.segments:
        # 스펙 §4 수식은 mixed를 일치와 동급으로 두지만, 세그먼트 특정 질문에서
        # 직접 일치가 mixed보다 앞서야 하므로 의도적으로 차등 (2026-07-13 리뷰 M2 응답)
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


def search_with_plan(store: SectorStore, plan, *, k: int = 12,
                     hard_entities: list[str] | None = None,
                     ref_now: str | None = None) -> list[SectorCard]:
    """SectorQueryPlan 기반 검색 — LLM/규칙 플랜 공용 실행부.

    hard_entities: 질문이 직접 언급한 회사(extract_entities 결과)만 하드 필터
    (codex H3 — 회사 질문엔 그 회사 카드만, 스코어 +2만으론 타사 고중요도가 앞섬).
    플래너가 추론한 plan.entities는 소프트 부스트만 — 과잉 선택이 구세대
    entities=[] 카드를 죽이면 기간 질문(완성 기준 3)이 깨진다.
    ref_now: eval bundle 모드용 랭킹 시계 고정 (ISO date 문자열, None이면 utcnow).
    """
    # 일 ~40장 적재라 90일 창은 기본 캡(500)을 넘는다 — 스코어링 전에 잘리면
    # 오래된 카드가 아예 안 보임 (codex 리뷰 H2). 창 전체를 읽고 점수로 거른다.
    now = (
        _dt.datetime.fromisoformat(ref_now).replace(tzinfo=_dt.timezone.utc)
        if ref_now
        else _dt.datetime.now(_dt.timezone.utc)
    )
    ref = _parse_ts(f"{plan.until}T23:59:59+00:00") if getattr(plan, "until", None) else None
    if ref:
        # 기간 지목 질문 — 창을 until에서 days만큼 과거로, 최신성도 until 기준.
        # days만 넓히면 최근 카드가 최신성 점수로 과거 카드를 밀어낸다 (완성 기준 3)
        pool = store.read_cards(days=None, limit=10_000)
        cards = []
        for c in pool:
            d = _parse_ts(c.ts)
            if d and 0.0 <= (ref - d).total_seconds() / 86400 <= plan.days:
                cards.append(c)
    else:
        ref = now
        cards = store.read_cards(days=plan.days, limit=10_000)
    if not cards or k <= 0:
        return []
    if hard_entities:
        ent = set(hard_entities)
        filtered = [c for c in cards if ent & set(c.entities)]
        if filtered:  # 0건이면 무필터 폴백 (스펙 에러표 원칙)
            cards = filtered
    # ts 포맷 혼재(날짜 전용 vs ISO 풀 포맷) → 문자열 비교 대신 파싱된 나이로 동점 처리
    ranked = sorted(cards, key=lambda c: (_score(c, plan, ref), -_age_days(c.ts, ref)), reverse=True)
    return _balanced_top(ranked, k, eligible=lambda c: _plan_relevant(c, plan))


def _plan_relevant(c: SectorCard, plan) -> bool:
    """플랜 필터 기준 관련성 — 균형 예약 자격. 필터 없는 플랜은 전 카드 관련."""
    if not (plan.segments or plan.entities or plan.keywords or plan.event_types):
        return True
    if plan.segments and (c.memory_segment in plan.segments or c.memory_segment == "mixed"):
        return True
    if plan.entities and set(plan.entities) & set(c.entities):
        return True
    if plan.keywords:
        text = f"{c.title} {c.interpreted_signal} {c.raw_quote}".lower()
        if any(kw.lower() in text for kw in plan.keywords):
            return True
    return bool(plan.event_types) and c.event_type in plan.event_types
