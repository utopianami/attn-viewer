"""GET /v1/monitor/health — 마지막 점검 결과 + 경과. openapi.yaml에 동시 등재."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

_REPO_ROOT = Path(__file__).resolve().parents[2]

router = APIRouter(prefix="/v1/monitor", tags=["monitor"])


@router.get("/health")
async def health() -> dict[str, Any]:
    path = _REPO_ROOT / "storage" / "monitor" / "health.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False, "detail": "아직 점검 기록 없음 — "
                "MONITOR_ENABLED 또는 python -m monitor.runner"}
    age_s = None
    try:
        at = dt.datetime.fromisoformat(data.get("at", ""))
        age_s = (dt.datetime.now(dt.timezone.utc) - at).total_seconds()
    except ValueError:
        pass
    return {"available": True, "age_s": age_s, **data}
