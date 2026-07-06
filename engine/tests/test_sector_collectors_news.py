"""섹터 뉴스 수집기 + runner 격리 (P1 Task 2~4)."""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sector.contracts import CollectorResult, RawNewsItem  # noqa: E402
from sector.store import SectorStore  # noqa: E402
from sector import runner  # noqa: E402


def _mod(name, kind="metric", fail=False):
    m = types.ModuleType(name)
    m.NAME, m.KIND = name, kind
    async def collect(store, client=None):
        if fail:
            raise RuntimeError("boom")
        return CollectorResult(name=name, kind=kind, status="ok")
    m.collect = collect
    return m


def test_collect_all_isolates_failures(tmp_path, monkeypatch):
    mods = [_mod("good"), _mod("bad", fail=True), _mod("good2")]
    monkeypatch.setattr(runner, "_registry", lambda: mods)
    store = SectorStore(tmp_path)
    results = asyncio.run(runner.collect_all(store))
    by = {r.name: r.status for r in results}
    assert by == {"good": "ok", "bad": "error", "good2": "ok"}
    assert store.read_status()["bad"]["status"] == "error"


def test_collect_all_only_filter(tmp_path, monkeypatch):
    mods = [_mod("a"), _mod("b")]
    monkeypatch.setattr(runner, "_registry", lambda: mods)
    results = asyncio.run(runner.collect_all(SectorStore(tmp_path), only=["b"]))
    assert [r.name for r in results] == ["b"]
