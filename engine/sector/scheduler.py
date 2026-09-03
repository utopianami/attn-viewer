"""메모리 섹터 P1 — 주기 수집 스케줄러 (기본 OFF, 원칙 10)."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from app.settings import settings

logger = logging.getLogger(__name__)
_ENGINE_DIR = Path(__file__).resolve().parents[1]
_COLLECT_TIMEOUT_S = 30 * 60
_TERMINATE_GRACE_S = 30


async def run_collection_subprocess(*, timeout_s: float = _COLLECT_TIMEOUT_S) -> int | None:
    """Run one collection out of process and bound even a wedged CLI child."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "sector.collect_pipeline",
        cwd=str(_ENGINE_DIR),
    )
    try:
        return await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_S)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        logger.error("sector scheduler: hard timeout (%ss); process terminated", timeout_s)
        return None
    except asyncio.CancelledError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=_TERMINATE_GRACE_S)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        raise


async def _loop() -> None:
    while True:
        try:
            rc = await run_collection_subprocess()
            if rc == 0:
                logger.info("sector scheduler: collect pipeline completed")
            else:
                logger.error("sector scheduler: collect pipeline failed rc=%s", rc)
        except Exception as exc:  # noqa: BLE001
            logger.error("sector scheduler: collect pipeline failed — %s", exc)
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
