"""Dedicated owner for sector, report, and monitoring schedules."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import types
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from app.settings import REPO_ROOT
from runtime_io import atomic_write_text, try_singleton_lock
from runtime_revision import RUNNING_REVISION

logger = logging.getLogger(__name__)
Starter = Callable[[object], Awaitable[asyncio.Task | None]]


def _scheduler_starters() -> tuple[Starter, ...]:
    from monitor.scheduler import start as start_monitor
    from sector.report_scheduler import start as start_reports
    from sector.scheduler import start as start_sector

    return start_sector, start_reports, start_monitor


async def start_all(app: object) -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = []
    for start in _scheduler_starters():
        task = await start(app)
        if task is not None:
            tasks.append(task)
    return tasks


async def run(
    *,
    stop_event: asyncio.Event | None = None,
    lock_path: Path | None = None,
) -> int:
    lock_path = lock_path or REPO_ROOT / "storage" / "run" / "scheduler-worker.lock"
    with try_singleton_lock(lock_path) as acquired:
        if not acquired:
            logger.warning("scheduler worker already running; exiting")
            return 0

        event = stop_event or asyncio.Event()
        loop = asyncio.get_running_loop()
        if stop_event is None:
            for signum in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(signum, event.set)
                except NotImplementedError:
                    pass

        app = types.SimpleNamespace(state=types.SimpleNamespace())
        atomic_write_text(lock_path.with_suffix(".json"), json.dumps({
            "pid": os.getpid(), "revision": RUNNING_REVISION,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }))
        tasks = await start_all(app)
        logger.info("scheduler worker started revision=%s with %d active schedules",
                    RUNNING_REVISION, len(tasks))
        try:
            await event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("scheduler worker stopped")
        return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
