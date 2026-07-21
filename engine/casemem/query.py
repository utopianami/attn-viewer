"""Case-Memory 단일 진입점 — 리포트/후속 API가 부르는 안정 계약.
결정적: as_of가 유일한 시계. 룩어헤드는 search가 국면 knowable_at으로 차단."""
from __future__ import annotations

from casemem.contracts import CaseQueryResult, _parse_ts
from casemem.search import _phase_visible, search_cases
from casemem.store import CaseStore


def query_case_memory(store: CaseStore, *, signals: list[str], as_of: str,
                      sector: str = "memory", k: int = 5) -> CaseQueryResult:
    as_of_dt = _parse_ts(as_of)
    if as_of_dt is None:
        return CaseQueryResult(as_of=as_of, sector=sector, matches=[],
                               scanned=0, dropped_after_as_of=0, dropped_sector=0)
    episodes = store.read_episodes(sector=sector)   # 섹터는 store가 이미 필터
    scanned = len(episodes)
    dropped_after_as_of = sum(
        0 if any(_phase_visible(p, as_of_dt) for p in ep.phases) else 1
        for ep in episodes)
    matches = search_cases(episodes, signals, as_of_dt=as_of_dt, sector=sector, k=k)
    return CaseQueryResult(as_of=as_of, sector=sector, matches=matches,
                           scanned=scanned, dropped_after_as_of=dropped_after_as_of,
                           dropped_sector=0)
