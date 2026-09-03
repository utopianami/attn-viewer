"""모니터 주기 실행 — sector.scheduler와 같은 asyncio 루프 관례 (기본 OFF).

run_checks는 파일 IO뿐이지만 지표 tail 읽기가 수십 ms를 넘을 수 있어
이벤트루프 점유를 피해 to_thread로 돌린다. never-raise — 다음 주기는 계속.
"""
from __future__ import annotations

import asyncio
import logging

from app.settings import settings

logger = logging.getLogger(__name__)


async def _loop() -> None:
    from monitor.runner import probe_engine_health, run_checks

    while True:
        try:
            health = await asyncio.to_thread(run_checks, engine_probe=probe_engine_health)
            logger.info("monitor: 점검 완료 worst=%s (%d checks)",
                        health.worst, len(health.results))
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
