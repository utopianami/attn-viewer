"""메모리 섹터 P1 — 주기 수집 스케줄러 (기본 OFF, 원칙 10)."""
from __future__ import annotations

import asyncio
import logging

from app.settings import settings

logger = logging.getLogger(__name__)


async def _loop() -> None:
    from sector.api import _get_store
    from sector.runner import collect_all

    while True:
        try:
            store = _get_store()
            await collect_all(store)
            logger.info("sector scheduler: collect_all 완료")
        except Exception as exc:  # noqa: BLE001
            logger.error("sector scheduler: collect_all 실패 — %s", exc)
        await asyncio.sleep(settings.sector_collect_interval_s)


async def start(app) -> asyncio.Task | None:
    if not settings.sector_scheduler_enabled:
        logger.info("sector scheduler: 비활성화(기본 OFF) — POST /v1/sector/collect로 수동 실행")
        return None
    task = asyncio.create_task(_loop())
    app.state.sector_task = task
    logger.info(
        "sector scheduler: 시작 (interval=%ds)", settings.sector_collect_interval_s
    )
    return task
