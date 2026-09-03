"""메모리 섹터 P1 — API 라우터 (원칙 6·계획 §9)."""
from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.settings import REPO_ROOT, settings
from sector.cycle import compute
from sector.retrieve import search
from sector.store import SectorStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/sector")

_STORE: SectorStore | None = None


def _get_store() -> SectorStore:
    global _STORE
    if _STORE is None:
        root = (Path(settings.sector_storage_dir)
                if settings.sector_storage_dir
                else REPO_ROOT / "storage" / "rag" / "memory_sector")
        _STORE = SectorStore(root)
    return _STORE


# ── GET /v1/sector/status ────────────────────────────────────────────────────

@router.get("/status")
async def status() -> dict[str, Any]:
    store = _get_store()
    collectors = {
        name: value
        for name, value in store.read_status().items()
        if not name.startswith("_")
    }
    _summary: dict[str, int] = {"ok": 0, "degraded": 0, "missing_key": 0, "error": 0}
    for name, v in collectors.items():
        if name.startswith("_"):
            continue
        key = v.get("status", "error")
        if key in _summary:
            _summary[key] += 1
        else:
            _summary["error"] += 1
    return {
        "collectors": collectors,
        "summary": _summary,
        "scheduler": {
            "enabled": settings.sector_scheduler_enabled,
            "interval_s": settings.sector_collect_interval_s,
        },
    }


# ── POST /v1/sector/collect ──────────────────────────────────────────────────

class CollectRequest(BaseModel):
    only: list[str] | None = None


@router.post("/collect")
async def collect(body: CollectRequest) -> dict[str, Any]:
    from sector.runner import collect_all
    store = _get_store()
    results = await collect_all(store, only=body.only)
    return {
        "results": [
            {
                "name": r.name,
                "status": r.status,
                "detail": r.detail,
                "took_ms": r.took_ms,
                "items": len(r.items),
                "observations": len(r.observations),
            }
            for r in results
        ]
    }


# ── GET /v1/sector/cards ─────────────────────────────────────────────────────

@router.get("/cards")
async def cards(
    days: int = Query(14),
    axis: str = Query(""),
    entity: str = Query(""),
    limit: int = Query(100),
) -> dict[str, Any]:
    store = _get_store()
    result = store.read_cards(
        days=days,
        axis=axis or None,
        entity=entity or None,
        limit=limit,
    )
    return {"cards": [c.model_dump() for c in result]}


# ── GET /v1/sector/metrics/{name} ────────────────────────────────────────────

@router.get("/metrics/{name}")
async def metrics(name: str, n: int = Query(90)) -> dict[str, Any]:
    store = _get_store()
    rows = store.read_metric(name, last_n=n)
    return {"metric": name, "rows": [o.model_dump() for o in rows]}


# ── GET /v1/sector/board ─────────────────────────────────────────────────────

def _last_collected(store: SectorStore) -> str | None:
    """수집기 status의 마지막 성공 기록 시각 — 화면의 '데이터 기준' 시각."""
    ats = [v.get("at") for name, v in store.read_status().items()
           if not name.startswith("_") and isinstance(v, dict) and v.get("at")]
    return max(ats) if ats else None


@router.get("/board")
async def board() -> dict[str, Any]:
    from sector.cycle import supply_risk
    store = _get_store()
    cycle = compute(store)
    cards_list = search(store, k=20)
    return {
        "cycle": cycle,
        "supply_risk": supply_risk(store),
        "cards": [c.model_dump() for c in cards_list],
        "status": {
            name: value
            for name, value in store.read_status().items()
            if not name.startswith("_")
        },
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "last_collected_at": _last_collected(store),
        "collect_interval_s": settings.sector_collect_interval_s,
        "scheduler_enabled": settings.sector_scheduler_enabled,
    }

_PRICES_CACHE: dict = {"at": 0.0, "days": 0, "data": None}


@router.get("/prices")
async def get_prices(days: int = 90):
    """주가 시계열 (대시보드 스파크라인) — 1시간 캐시, 저장 안 함."""
    import time as _time
    now = _time.monotonic()
    if (_PRICES_CACHE["data"] is not None and _PRICES_CACHE["days"] == days
            and now - _PRICES_CACHE["at"] < 3600):
        return _PRICES_CACHE["data"]
    from sector.prices import price_series
    data = await price_series(days=days)
    _PRICES_CACHE.update(at=now, days=days, data=data)
    return data

_BRIEF_CACHE: dict = {"key": None, "at": 0.0, "data": None, "refreshing": False}


async def _rebuild_briefing(key: str | None) -> None:
    """백그라운드 완성본 생성 — LLM 해설 포함. 끝나면 캐시 통째 교체."""
    import time as _time
    try:
        from sector.briefing import build_briefing
        data = await build_briefing(_get_store())
        data["based_on"] = key
        _BRIEF_CACHE.update(key=key, at=_time.monotonic(), data=data)
    except Exception:  # noqa: BLE001 — 실패해도 기존 캐시 유지
        logger.exception("briefing 백그라운드 재생성 실패")
    finally:
        _BRIEF_CACHE["refreshing"] = False


@router.get("/theses")
async def theses() -> dict[str, Any]:
    """테제 최신 revision 목록 + freshness (2부 T7 — T1 계약 구현)."""
    from sector.thesis_store import ThesisStore, freshness
    store = _get_store()
    tstore = ThesisStore(store.root)
    now = _dt.datetime.now(_dt.timezone.utc)
    return {
        "theses": [
            {**rev.model_dump(mode="json"), "freshness": freshness(rev, store, now)}
            for rev in tstore.latest_all()
        ]
    }


@router.get("/briefing")
async def get_briefing():
    """종합 브리핑 — 판단·사슬(규칙)이 LLM을 기다리지 않게 (2026-07-09):

    ① 캐시 유효(같은 수집분·LLM 완성) → 즉시 반환
    ② 낡은 캐시 → 그것부터 즉시 반환, 백그라운드에서 새 완성본으로 교체
    ③ 프로세스 첫 조회 → 규칙 파트만 즉시(llm_pending), 해설은 백그라운드
    """
    import asyncio
    import time as _time
    store = _get_store()
    key = _last_collected(store)
    now = _time.monotonic()
    c = _BRIEF_CACHE
    fresh = c["data"] is not None and (
        (key is not None and c["key"] == key)
        or (key is None and now - c["at"] < 1800))
    if fresh and not c["data"].get("llm_pending"):
        return c["data"]
    if not c["refreshing"]:
        c["refreshing"] = True
        asyncio.get_running_loop().create_task(_rebuild_briefing(key))
    if c["data"] is not None:
        return c["data"]
    from sector.briefing import build_briefing
    data = await build_briefing(store, skip_llm=True)
    data["based_on"] = key
    c.update(key=key, at=now, data=data)
    return data
