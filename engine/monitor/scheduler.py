"""모니터 주기 실행 — sector.scheduler와 같은 asyncio 루프 관례 (기본 OFF).

Each check runs in a fresh interpreter so a long-lived worker cannot retain old checks.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from app.settings import settings

logger = logging.getLogger(__name__)
_ENGINE_DIR = Path(__file__).resolve().parents[1]
_CHECK_TIMEOUT_S = 300


async def _run_once() -> int | None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "monitor.runner", cwd=str(_ENGINE_DIR))
    try:
        return await asyncio.wait_for(proc.wait(), timeout=_CHECK_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.error("monitor: check subprocess timed out")
        return None
    finally:
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()


async def _loop() -> None:
    while True:
        try:
            rc = await _run_once()
            logger.log(logging.INFO if rc == 0 else logging.ERROR,
                       "monitor: check subprocess exited rc=%s", rc)
        except Exception as exc:  # noqa: BLE001
            logger.error("monitor: 점검 실패 — %s", exc)
        await asyncio.sleep(settings.monitor_interval_s)


async def start(app) -> asyncio.Task | None:
    if not settings.monitor_enabled:
        logger.info("monitor: 비활성화(기본 OFF) — "
                    "cd engine && .venv/bin/python -m monitor.runner")
        return None
    task = asyncio.create_task(_loop())
    app.state.monitor_task = task
    logger.info("monitor: 시작 (interval=%ds, telegram=%s)",
                settings.monitor_interval_s,
                "설정됨" if settings.telegram_bot_token else "미설정—파일 기록만")
    return task
