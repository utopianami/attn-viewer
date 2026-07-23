"""격리 실행기 — 수집기 하나의 실패가 나머지를 못 막는다 (원칙 2 never-block)."""
from __future__ import annotations

import time

from app.settings import settings
from sector.contracts import CollectorResult, SectorCard
from sector.store import SectorStore


def _registry() -> list:
    from sector.collectors import registry
    return registry()


async def collect_all(store: SectorStore, *, only: list[str] | None = None,
                      judge_fn=None) -> list[CollectorResult]:
    """모든(또는 only 지정) 수집기 실행 → 지표 저장 → 뉴스는 judge_fn으로 카드화.

    judge_fn: async (list[RawNewsItem]) -> list[SectorCard]. None이면 뉴스는 카드화 생략
    (Task 7에서 기본 judge 연결).
    """
    results: list[CollectorResult] = []
    news_items = []
    for mod in _registry():
        if only and mod.NAME not in only:
            continue
        t0 = time.monotonic()
        try:
            r = await mod.collect(store)
        except Exception as exc:  # noqa: BLE001 — 격리가 목적
            r = CollectorResult(name=mod.NAME, kind=getattr(mod, "KIND", "metric"),
                                status="error", detail=f"{type(exc).__name__}: {exc}"[:300])
        r.took_ms = int((time.monotonic() - t0) * 1000)
        if r.observations:
            store.append_observations(r.observations)
        if r.items:
            news_items.extend(r.items)
        results.append(r)
    if judge_fn is None:
        try:
            from sector.judge import judge_items as judge_fn  # noqa: PLC0415
        except Exception:  # noqa: BLE001 — Task 7 이전엔 judge 부재 허용
            judge_fn = None
    if judge_fn is not None and news_items:
        try:
            cards: list[SectorCard] = await judge_fn(news_items)
            store.append_cards(cards)
            # 뉴스가 공표한 미래 일정(상장·실적·출시 등) → 캘린더 자동 방출
            import datetime as _dt
            from sector.judge import scheduled_event_observations
            sched = scheduled_event_observations(cards, _dt.date.today())
            if sched:
                store.append_observations(sched)
        except Exception as exc:  # noqa: BLE001 — 판정 실패도 수집을 못 막음
            results.append(CollectorResult(name="judge", kind="news", status="error",
                                           detail=f"{type(exc).__name__}: {exc}"[:300]))
    store.write_status(results)
    if getattr(settings, "thesis_update_enabled", True):
        try:
            from sector.thesis_update import update_all
            await update_all(store)
        except Exception as exc:  # noqa: BLE001 — thesis 실패가 수집 결과를 못 건드림
            results.append(CollectorResult(name="thesis_update", kind="metric",
                                           status="error", detail=str(exc)[:200]))
    return results
