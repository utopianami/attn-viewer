"""Case-Memory API 라우터 — sector/api.py 패턴 복제. 결정적(리랭크 없음)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.settings import REPO_ROOT, settings
from casemem.query import query_case_memory
from casemem.seeds import load_seeds
from casemem.store import CaseStore

router = APIRouter(prefix="/v1/case-memory")

_STORE: CaseStore | None = None


def _store_root() -> Path:
    override = getattr(settings, "casemem_storage_dir", "") or ""
    return Path(override) if override else REPO_ROOT / "storage" / "rag" / "case_memory"


def _get_store() -> CaseStore:
    global _STORE
    if _STORE is None:
        _STORE = CaseStore(_store_root())
        if not _STORE.read_episodes():          # 빈 스토어면 시드 1회 적재
            load_seeds(_STORE)
    return _STORE


class QueryBody(BaseModel):
    signals: list[str] = []
    as_of: str
    sector: str = "memory"
    k: int = 5


@router.post("/query")
async def query(body: QueryBody) -> dict:
    res = query_case_memory(_get_store(), signals=body.signals, as_of=body.as_of,
                            sector=body.sector, k=body.k)
    return res.model_dump()


@router.get("/cases")
async def cases(sector: str = "") -> dict:
    eps = _get_store().read_episodes(sector=sector or None)
    return {"cases": [e.model_dump() for e in eps]}


@router.get("/cases/{episode_id}")
async def case_one(episode_id: str):
    for e in _get_store().read_episodes():
        if e.id == episode_id:
            return e.model_dump()
    return JSONResponse(status_code=404, content={"error": "not_found", "id": episode_id})
