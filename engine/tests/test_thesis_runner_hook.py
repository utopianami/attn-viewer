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
    """정상: update_all이 store 인자로 1회 호출, write_status는 훅 이전에 이미 끝남."""
    import sector.runner as runner
    from app.settings import settings

    monkeypatch.setattr(settings, "thesis_update_enabled", True)
    monkeypatch.setattr(runner, "_registry", lambda: [_empty_registry_module()])

    calls = []

    async def fake_update_all(store):
        calls.append(store)
        return {"seed-1": "unchanged"}

    monkeypatch.setattr("sector.thesis_update.update_all", fake_update_all)

    store = SectorStore(tmp_path / "s")
    results = asyncio.run(runner.collect_all(store))

    assert len(calls) == 1
    assert calls[0] is store
    # collect_all 결과에는 fake 수집기 결과만 있고 thesis 관련 항목은 없다
    assert [r.name for r in results] == ["fake"]
    # write_status는 훅 이전에 이미 기록됐고, 훅 성공 시 상태 파일은 재작성되지 않는다
    status = store.read_status()
    assert "thesis_update" not in status
    assert status["fake"]["status"] == "ok"


def test_update_all_raises_appends_error_but_does_not_rewrite_status(tmp_path, monkeypatch):
    """update_all 예외 → results에 error 항목 추가, write_status 페이로드엔 미반영, 예외 미전파."""
    import sector.runner as runner
    from app.settings import settings

    monkeypatch.setattr(settings, "thesis_update_enabled", True)
    monkeypatch.setattr(runner, "_registry", lambda: [_empty_registry_module()])

    async def boom(store):
        raise RuntimeError("x" * 500)

    monkeypatch.setattr("sector.thesis_update.update_all", boom)

    store = SectorStore(tmp_path / "s")
    results = asyncio.run(runner.collect_all(store))  # must not raise

    names = [r.name for r in results]
    assert names == ["fake", "thesis_update"]
    err = results[-1]
    assert err.status == "error"
    assert len(err.detail) <= 200

    # write_status was called before the hook — status.json must NOT contain thesis_update
    status = store.read_status()
    assert "thesis_update" not in status
    assert status["fake"]["status"] == "ok"


def test_flag_off_update_all_never_called(tmp_path, monkeypatch):
    """thesis_update_enabled=False → update_all 미호출."""
    import sector.runner as runner
    from app.settings import settings

    monkeypatch.setattr(settings, "thesis_update_enabled", False)
    monkeypatch.setattr(runner, "_registry", lambda: [_empty_registry_module()])

    calls = []

    async def fake_update_all(store):
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

    async def fake_update_all(store):
        calls.append(store)
        return {}

    monkeypatch.setattr("sector.thesis_update.update_all", fake_update_all)

    store = SectorStore(tmp_path / "s")
    results = asyncio.run(runner.collect_all(store))

    assert len(calls) == 1
    assert results == []
