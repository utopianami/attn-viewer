"""thesis 결정적 선택기 — rule_plan 스코어링으로 관련 테제를 뽑는다 (3부 T3).

LLM 없음, 전부 결정적. 스코어: entity∩×2 + metric∩×1 + event_type∩×1.
0점·stale 제외 후 (-score, priority, rev.id)로 정렬해 상위 최대 3개를 낸다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sector.queryplan import SectorQueryPlan, build_rule_plan
from sector.store import SectorStore
from sector.thesis_contracts import ThesisRevision
from sector.thesis_store import ThesisStore, freshness


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
