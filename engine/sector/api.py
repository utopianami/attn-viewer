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
    collectors = store.read_status()
    _summary: dict[str, int] = {"ok": 0, "degraded": 0, "missing_key": 0, "error": 0}
    for v in collectors.values():
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
    ats = [v.get("at") for v in store.read_status().values()
           if isinstance(v, dict) and v.get("at")]
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
        "status": store.read_status(),
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

_BRIEF_CACHE: dict = {"key": None, "at": 0.0, "data": None}


@router.get("/briefing")
async def get_briefing():
    """종합 브리핑 (사슬 서사) — 새 수집이 있을 때만 재생성 (수집 시각을 캐시 키로).
    수집 기록이 없으면 30분 TTL 폴백. LLM 실패해도 규칙 문장 반환."""
    import time as _time
    store = _get_store()
    key = _last_collected(store)
    now = _time.monotonic()
    if _BRIEF_CACHE["data"] is not None and (
            (key is not None and _BRIEF_CACHE["key"] == key)
            or (key is None and now - _BRIEF_CACHE["at"] < 1800)):
        return _BRIEF_CACHE["data"]
    from sector.briefing import build_briefing
    data = await build_briefing(store)
    data["based_on"] = key
    _BRIEF_CACHE.update(key=key, at=now, data=data)
    return data
