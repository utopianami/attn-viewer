"""MAC/FAC 결정적 검색 — as-of 필터 → 메타(섹터) → 표면 키워드 스코어.
LLM 구조 리랭크는 Plan 2(설계 §5 5단계). 여기선 표면 스코어까지."""
from __future__ import annotations

import re

from casemem.contracts import CaseEpisode, CaseMatch, Phase, _parse_ts

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(texts: list[str]) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out.update(_WORD.findall(t.lower()))
    return out


def _phase_visible(phase: Phase, as_of_dt) -> bool:
    k = _parse_ts(phase.knowable_at)
    return k is not None and as_of_dt is not None and k <= as_of_dt


def _surface_score(signals: list[str], phase: Phase) -> float:
    """오늘 signal 토큰 vs 국면 identifying_signals 토큰 겹침 비율(0~1)."""
    sig = _tokens(signals)
    ph = _tokens(phase.identifying_signals)
    if not sig or not ph:
        return 0.0
    return len(sig & ph) / len(sig | ph)


def search_cases(episodes: list[CaseEpisode], signals: list[str], *,
                 as_of_dt, sector: str | None, k: int = 5) -> list[CaseMatch]:
    matches: list[CaseMatch] = []
    for ep in episodes:
        if sector is not None and ep.sector != sector:
            continue
        best: tuple[float, Phase] | None = None
        for ph in ep.phases:
            if not _phase_visible(ph, as_of_dt):
                continue
            sc = _surface_score(signals, ph)
            if best is None or sc > best[0]:
                best = (sc, ph)
        if best is None or best[0] <= 0.0:
            continue
        score, mph = best
        # 다음 국면(예측) = order가 매치보다 큰 전체 국면 라벨(라벨 노출은 룩어헤드 아님)
        next_labels = [p.label for p in ep.phases if p.order > mph.order]
        # evidence는 as-of 가시분만 (룩어헤드 차단)
        vis_ev = [e for e in mph.evidence
                  if (_parse_ts(e.knowable_at) is not None
                      and _parse_ts(e.knowable_at) <= as_of_dt)]
        matches.append(CaseMatch(episode_id=ep.id, matched_phase_order=mph.order,
                                 score=score, next_phase_labels=next_labels,
                                 evidence=vis_ev))
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:k]
