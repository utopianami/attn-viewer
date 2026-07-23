"""thesis 결정적 선택기 — rule_plan 스코어링으로 관련 테제를 뽑는다 (3부 T3).

LLM 없음, 전부 결정적. 스코어: entity∩×2 + metric∩×1 + event_type∩×1.
0점·stale 제외 후 (-score, priority, rev.id)로 정렬해 상위 최대 3개를 낸다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from contracts import TypedFact
from sector.queryplan import SectorQueryPlan, build_rule_plan
from sector.store import SectorStore
from sector.thesis_contracts import ThesisRevision
from sector.thesis_guard import quantity_literal
from sector.thesis_store import ThesisStore, freshness

_HEADER = "[배경 판 — 섹터 현재 가설 (자동 합성·경향 참고)]"
_BOUNDARY = (
    "아래는 축적 근거로 자동 유지되는 '배경 가설'이다. 사실 근거로 단정 인용하지 말고 "
    "해석의 배경으로만 써라. 이 절의 가설 관련 수치는 [결정적 수치] 절의 값만 인용하라."
)


@dataclass
class ThesisPick:
    rev: ThesisRevision
    freshness: str
    score: int


def score_thesis(rp: SectorQueryPlan, rev: ThesisRevision) -> int:
    entity_hits = len(set(rp.entities) & set(rev.selectors.entities))
    metric_hits = len(set(rp.metrics) & set(rev.selectors.metrics))
    event_hits = len(set(rp.event_types) & set(rev.selectors.event_types))
    return entity_hits * 2 + metric_hits * 1 + event_hits * 1


def select_from_revisions(rp: SectorQueryPlan, revs: list[ThesisRevision],
                          store: SectorStore, now: dt.datetime) -> list[ThesisPick]:
    picks: list[ThesisPick] = []
    for rev in revs:
        score = score_thesis(rp, rev)
        if score == 0:
            continue
        fresh = freshness(rev, store, now)
        if fresh == "stale":
            continue
        picks.append(ThesisPick(rev=rev, freshness=fresh, score=score))
    picks.sort(key=lambda p: (-p.score, p.rev.priority, p.rev.id))
    return picks[:3]


def select_theses(question: str, tstore: ThesisStore, store: SectorStore,
                  now: dt.datetime) -> list[ThesisPick]:
    rp = build_rule_plan(question, include_event_types=True)
    return select_from_revisions(rp, tstore.latest_all(), store, now)


def render_thesis_section(picks: list[ThesisPick]) -> str:
    """배경 판(thesis) 절 렌더 — 경계 문구로 감싸 해석 배경으로만 쓰이게 한다.

    revision_id·타임스탬프·key_metrics 값은 절에 넣지 않는다(숫자는 [결정적 수치]
    절 전용). 렌더 직전 코드 검증으로 quantity_literal에 잡히는 statement/claim은
    드롭한다 — LLM이 만든 claim이 아니라도 이중 안전망(fail-closed).
    """
    if not picks:
        return ""
    lines: list[str] = []
    for p in picks:
        rev = p.rev
        if quantity_literal(rev.claim):
            continue  # claim 자체에 수량 literal — 이 가설 라인 통째로 드롭
        stmt_texts = [s.text for s in rev.statements if not quantity_literal(s.text)]
        degraded = ", 입력 일부 노후" if p.freshness == "degraded" else ""
        lines.append(f"- ({rev.assessment}{degraded}) {rev.claim}: "
                     + "; ".join(stmt_texts))
    if not lines:
        return ""
    return "\n".join([_HEADER, _BOUNDARY] + lines)


def thesis_typed_facts(picks: list[ThesisPick]) -> list[TypedFact]:
    """key_metrics → TypedFact. id 중복은 상위 pick(먼저 온 pick) first-wins."""
    seen: set[str] = set()
    facts: list[TypedFact] = []
    for p in picks:
        rev = p.rev
        for km in rev.key_metrics:
            fid = f"thesis:{rev.id}:{km.metric}"
            if fid in seen:
                continue
            seen.add(fid)
            facts.append(TypedFact(
                id=fid, value=km.value, unit=km.unit, period=km.ts,
                label=f"{rev.id} 관련 지표 {km.metric}", source=km.source,
                metric=km.metric, observation_id=km.observation_id))
    return facts
