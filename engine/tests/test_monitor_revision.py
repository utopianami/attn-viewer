"""Monitor code reload and scheduler revision provenance without service restarts."""
import asyncio
import json

import pytest

from monitor.runner import run_checks


def test_monitor_executes_updated_module_in_a_new_process_each_time(tmp_path, monkeypatch):
    import monitor.scheduler as scheduler
    module = tmp_path / "monitor"
    module.mkdir()
    (module / "__init__.py").write_text("")
    runner = module / "runner.py"
    marker = tmp_path / "executed.txt"
    runner.write_text("from pathlib import Path\nPath('executed.txt').write_text('first')\n")
    monkeypatch.setattr(scheduler, "_ENGINE_DIR", tmp_path, raising=False)
    assert asyncio.run(scheduler._run_once()) == 0
    assert marker.read_text() == "first"
    runner.write_text("from pathlib import Path\nPath('executed.txt').write_text('updated code')\n")
    assert asyncio.run(scheduler._run_once()) == 0
    assert marker.read_text() == "updated code"


def test_worker_records_revision_and_pid_before_starting_schedules(tmp_path, monkeypatch):
    from app import scheduler_worker as worker
    record_path = tmp_path / "scheduler-worker.json"
    observed = []

    async def starter(app):
        observed.append(json.loads(record_path.read_text()))
        return None

    monkeypatch.setattr(worker, "_scheduler_starters", lambda: (starter,))
    async def exercise():
        stop = asyncio.Event()
        stop.set()
        return await worker.run(stop_event=stop, lock_path=tmp_path / "scheduler-worker.lock")

    assert asyncio.run(exercise()) == 0
    import os
    assert observed[0]["pid"] == os.getpid()
    assert len(observed[0]["revision"]) == 40
    assert observed[0]["started_at"]


def test_monitor_reports_loaded_scheduler_revision_mismatch(tmp_path):
    import subprocess
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    state = tmp_path / "run" / "scheduler-worker.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"revision": "old-revision", "pid": 123}))
    report = run_checks(storage_root=tmp_path, times_kst=[(6, 30), (18, 30)], cooldown_s=21600)
    check = next((r for r in report.results if r.check == "scheduler_revision"), None)
    assert check is not None
    assert check.level == "warn"
    assert "old-revision" in check.detail and revision in check.detail
    state.write_text(json.dumps({"revision": revision, "pid": 123}))
    report = run_checks(storage_root=tmp_path, times_kst=[(6, 30), (18, 30)], cooldown_s=21600)
    check = next(r for r in report.results if r.check == "scheduler_revision")
    assert check.level == "ok"
    monitor = next(r for r in report.results if r.check == "monitor_revision")
    assert revision in monitor.detail


def test_monitor_reports_unknown_worker_revision_instead_of_claiming_current(tmp_path):
    report = run_checks(storage_root=tmp_path, times_kst=[(6, 30), (18, 30)], cooldown_s=21600)
    check = next((r for r in report.results if r.check == "scheduler_revision"), None)
    assert check is not None and check.level == "warn"
    assert "unknown" in check.detail


def test_malformed_worker_record_does_not_interrupt_health_checks(tmp_path):
    state = tmp_path / "run" / "scheduler-worker.json"
    state.parent.mkdir()
    state.write_text('["invalid record"]')
    report = run_checks(storage_root=tmp_path, times_kst=[(6, 30), (18, 30)], cooldown_s=21600)
    check = next(r for r in report.results if r.check == "scheduler_revision")
    assert check.level == "warn" and "unknown" in check.detail


@pytest.mark.parametrize("cancel", [False, True])
def test_monitor_child_is_reaped_on_timeout_or_cancellation(tmp_path, monkeypatch, cancel):
    import os
    import monitor.scheduler as scheduler
    module = tmp_path / "monitor"
    module.mkdir()
    (module / "__init__.py").write_text("")
    (module / "runner.py").write_text(
        "import os, time\nfrom pathlib import Path\n"
        "Path('child.pid').write_text(str(os.getpid()))\ntime.sleep(30)\n")
    monkeypatch.setattr(scheduler, "_ENGINE_DIR", tmp_path)
    monkeypatch.setattr(scheduler, "_CHECK_TIMEOUT_S", 0.2, raising=False)

    async def exercise():
        task = asyncio.create_task(scheduler._run_once())
        try:
            for _ in range(100):
                if (tmp_path / "child.pid").exists():
                    break
                await asyncio.sleep(0.01)
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                assert await asyncio.wait_for(task, 1) is None
            pid = int((tmp_path / "child.pid").read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            # Keep RED isolated too: baseline implementation leaves its child alive.
            if (tmp_path / "child.pid").exists():
                try:
                    os.kill(int((tmp_path / "child.pid").read_text()), 9)
                except ProcessLookupError:
                    pass

    asyncio.run(exercise())
