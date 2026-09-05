"""collect_all thesis 훅 — never-block 양방향·플래그 (2부 T6)."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.store import SectorStore  # noqa: E402


def _empty_registry_module(status: str = "ok"):
    """빈/성공 수집기 하나짜리 stub 모듈 (등록기 stub용)."""
    m = types.ModuleType("fake")
    m.NAME, m.KIND = "fake", "metric"

    async def collect(store):
        from sector.contracts import CollectorResult
        return CollectorResult(name="fake", kind="metric", status=status)

    m.collect = collect
    return m


def test_normal_update_all_called_and_results_unaffected(tmp_path, monkeypatch):
    """정상: thesis 훅이 끝날 때까지 실행 상태는 running이어야 한다."""
    import sector.runner as runner
    from app.settings import settings

    monkeypatch.setattr(settings, "thesis_update_enabled", True)
    monkeypatch.setattr(runner, "_registry", lambda: [_empty_registry_module()])

    calls = []
    during_update = []

    async def fake_update_all(store, tstore=None):
        calls.append((store, tstore))
        during_update.append(store.read_status().get("_run"))
        return {"seed-1": "unchanged"}

    monkeypatch.setattr("sector.thesis_update.update_all", fake_update_all)

    store = SectorStore(tmp_path / "s")
    results = asyncio.run(runner.collect_all(store))

    assert len(calls) == 1
    called_store, called_tstore = calls[0]
    assert called_store is store
    # 격리 회귀 방지: 훅이 넘기는 tstore는 수집 스토어의 tmp root에 결속돼야 한다
    # (production _ROOT의 storage/rag/memory_sector로 새지 않아야 함).
    assert called_tstore is not None
    assert called_tstore.root == store.root
    assert called_tstore._path == store.root / "theses.jsonl"
    assert "memory_sector" not in str(called_tstore._path)
    # collect_all 결과에는 fake 수집기 결과만 있고 thesis 관련 항목은 없다
    assert [r.name for r in results] == ["fake"]
    assert during_update[0]["state"] == "running"
    assert "finished_at" not in during_update[0]
    status = store.read_status()
    assert "thesis_update" not in status
    assert status["fake"]["status"] == "ok"
    assert status["_run"]["state"] == "completed"
    assert status["_run"]["started_at"] <= status["_run"]["finished_at"]


def test_update_all_raises_appends_error_and_records_final_status(tmp_path, monkeypatch):
    """update_all 예외 → 결과와 최종 상태에 오류를 기록하되 예외는 전파하지 않는다."""
    import sector.runner as runner
    from app.settings import settings

    monkeypatch.setattr(settings, "thesis_update_enabled", True)
    monkeypatch.setattr(runner, "_registry", lambda: [_empty_registry_module()])

    async def boom(store, tstore=None):
        raise RuntimeError("x" * 500)

    monkeypatch.setattr("sector.thesis_update.update_all", boom)

    store = SectorStore(tmp_path / "s")
    results = asyncio.run(runner.collect_all(store))  # must not raise

    names = [r.name for r in results]
    assert names == ["fake", "thesis_update"]
    err = results[-1]
    assert err.status == "error"
    assert len(err.detail) <= 200

    status = store.read_status()
    assert status["thesis_update"]["status"] == "error"
    assert status["fake"]["status"] == "ok"
    assert status["_run"]["state"] == "completed"
    assert status["_run"]["collector_count"] == 2
    assert status["_run"]["status_counts"] == {"ok": 1, "error": 1}


def test_flag_off_update_all_never_called(tmp_path, monkeypatch):
    """thesis_update_enabled=False → update_all 미호출."""
    import sector.runner as runner
    from app.settings import settings

    monkeypatch.setattr(settings, "thesis_update_enabled", False)
    monkeypatch.setattr(runner, "_registry", lambda: [_empty_registry_module()])

    calls = []

    async def fake_update_all(store, tstore=None):
        calls.append(store)
        return {}

    monkeypatch.setattr("sector.thesis_update.update_all", fake_update_all)

    store = SectorStore(tmp_path / "s")
    results = asyncio.run(runner.collect_all(store))

    assert calls == []
    assert [r.name for r in results] == ["fake"]


def test_empty_failing_registry_still_calls_update_all(tmp_path, monkeypatch):
    """수집기 전멸(빈 registry)에도 update_all은 호출된다 (수집 실패 ↛ thesis)."""
    import sector.runner as runner
    from app.settings import settings

    monkeypatch.setattr(settings, "thesis_update_enabled", True)
    monkeypatch.setattr(runner, "_registry", lambda: [])  # empty registry

    calls = []

    async def fake_update_all(store, tstore=None):
        calls.append(store)
        return {}

    monkeypatch.setattr("sector.thesis_update.update_all", fake_update_all)

    store = SectorStore(tmp_path / "s")
    results = asyncio.run(runner.collect_all(store))

    assert len(calls) == 1
    assert results == []


def test_returned_thesis_errors_do_not_count_as_recovery(tmp_path, monkeypatch):
    """update_all isolates per-seed errors into its return value instead of raising."""
    import sector.runner as runner
    from sector.contracts import CollectorResult

    monkeypatch.setattr(runner.settings, "thesis_update_enabled", True)
    monkeypatch.setattr(runner, "_registry", lambda: [_empty_registry_module()])

    async def still_failing(store, tstore=None):
        return {"seed-1": "error: RuntimeError: still unavailable"}

    monkeypatch.setattr("sector.thesis_update.update_all", still_failing)
    store = SectorStore(tmp_path)
    store.write_status([CollectorResult(name="thesis_update", kind="metric",
                                       status="error", detail="previous failure")])
    asyncio.run(runner.collect_all(store))
    status = store.read_status()
    assert status.get("thesis_update", {}).get("status") == "error"
    assert "still unavailable" in status["thesis_update"]["detail"]
    assert status["_run"]["status_counts"] == {"ok": 1, "error": 1}
