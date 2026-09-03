"""Scheduler process isolation and singleton lifecycle regressions."""

from __future__ import annotations

import asyncio
import logging
import types
from pathlib import Path


def test_fastapi_lifespan_does_not_start_schedulers(monkeypatch):
    from app import main
    import monitor.scheduler as monitor_scheduler
    import sector.report_scheduler as report_scheduler
    import sector.scheduler as sector_scheduler

    async def unexpected_start(_app):
        raise AssertionError("FastAPI must not own background schedulers")

    monkeypatch.setattr(sector_scheduler, "start", unexpected_start)
    monkeypatch.setattr(report_scheduler, "start", unexpected_start)
    monkeypatch.setattr(monitor_scheduler, "start", unexpected_start)

    async def exercise():
        async with main._lifespan(main.app):
            assert (await main.healthz())["ok"] is True

    asyncio.run(exercise())


def test_second_scheduler_worker_cannot_acquire_singleton(tmp_path: Path):
    from runtime_io import try_singleton_lock

    lock_path = tmp_path / "scheduler-worker.lock"
    with try_singleton_lock(lock_path) as first:
        assert first is True
        with try_singleton_lock(lock_path) as second:
            assert second is False


def test_collection_subprocess_timeout_terminates_and_reaps(monkeypatch):
    import sector.scheduler as scheduler

    class NeverEndingProcess:
        def __init__(self):
            self.waits = 0
            self.terminated = False
            self.killed = False

        async def wait(self):
            self.waits += 1
            if self.killed:
                return -9
            await asyncio.Future()

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    proc = NeverEndingProcess()

    async def fake_spawn(*_args, **_kwargs):
        return proc

    real_wait_for = asyncio.wait_for

    async def short_wait_for(awaitable, timeout):
        return await real_wait_for(awaitable, min(timeout, 0.01))

    monkeypatch.setattr(scheduler.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(scheduler.asyncio, "wait_for", short_wait_for)

    result = asyncio.run(scheduler.run_collection_subprocess(timeout_s=0.01))

    assert result is None
    assert proc.terminated is True
    assert proc.killed is True
    assert proc.waits == 3


def test_worker_starts_each_scheduler_once_and_cancels(monkeypatch, tmp_path: Path):
    from app import scheduler_worker

    starts: list[str] = []

    async def make_task(name: str):
        starts.append(name)
        return asyncio.create_task(asyncio.Event().wait())

    monkeypatch.setattr(
        scheduler_worker,
        "_scheduler_starters",
        lambda: (
            lambda app: make_task("sector"),
            lambda app: make_task("report"),
            lambda app: make_task("monitor"),
        ),
    )

    async def exercise():
        app = types.SimpleNamespace(state=types.SimpleNamespace())
        tasks = await scheduler_worker.start_all(app)
        assert starts == ["sector", "report", "monitor"]
        assert len(tasks) == 3
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(exercise())


def test_worker_main_configures_info_logging(monkeypatch):
    from app import scheduler_worker

    calls = []

    def fake_basic_config(**kwargs):
        calls.append(kwargs)

    def fake_run(coroutine):
        coroutine.close()
        return 0

    monkeypatch.setattr(scheduler_worker.logging, "basicConfig", fake_basic_config)
    monkeypatch.setattr(scheduler_worker.asyncio, "run", fake_run)

    assert scheduler_worker.main() == 0
    assert calls and calls[0]["level"] == logging.INFO


def test_collection_main_configures_info_logging(monkeypatch):
    from sector import collect_pipeline

    calls = []

    def fake_basic_config(**kwargs):
        calls.append(kwargs)

    def fake_run(coroutine):
        coroutine.close()
        return 0

    monkeypatch.setattr(collect_pipeline.logging, "basicConfig", fake_basic_config)
    monkeypatch.setattr(collect_pipeline.asyncio, "run", fake_run)

    assert collect_pipeline.main() == 0
    assert calls and calls[0]["level"] == logging.INFO
