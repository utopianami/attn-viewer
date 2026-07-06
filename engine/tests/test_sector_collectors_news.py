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


_ST_LIST = {"news_list": [
    {"id": "161424", "title": "JP모건, 금값 전망 낮춰…4분기 온스당 4,500달러 예상",
     "content": "JP모건은 주요 부문의 금 수요가...", "source": "로이터",
     "created_at": "2026-07-06T17:04:05+09:00"},
    {"id": "161415", "title": "SK하이닉스 10일 나스닥 데뷔… 외국 기업 IPO 최대 기록 예고",
     "content": "SK하이닉스가 글로벌 AI 메모리...", "source": "연합",
     "created_at": "2026-07-06T16:45:00+09:00"},
    {"id": "161167", "title": "(카더라) SK하이닉스 미국 상장 추진…주관사 수수료 0.5% 지급 논의",
     "content": "...", "source": "", "created_at": "2026-07-06T15:00:00+09:00"},
]}
_ST_DETAIL = {"news": {"id": "161415", "title": "SK하이닉스 10일 나스닥 데뷔…",
    "content": [{"type": "text", "content": "SK하이닉스가 290억 달러 규모 ADR 상장을 추진하며"},
                {"type": "text", "content": "- 미국 투자자 접근성 개선"}],
    "source": "연합", "tickers": [{"code": "000660"}], "created_at": "2026-07-06T16:45:00+09:00"}}
_ST_CAL = {"events": [{"id": 1, "title": "6월 ISM 서비스업 PMI ★★★",
                       "event_date": "2026-07-06T23:00:00"}]}


def _st_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/news/list":
            return httpx.Response(200, json=_ST_LIST)
        if p.startswith("/api/news/detail/"):
            return httpx.Response(200, json=_ST_DETAIL)
        if p == "/api/calendar/events":
            return httpx.Response(200, json=_ST_CAL)
        return httpx.Response(404, json={"detail": "Not Found"})
    return httpx.MockTransport(handler)


def test_saveticker_filters_and_fetches_detail(tmp_path):
    from sector.collectors import saveticker
    store = SectorStore(tmp_path)
    client = httpx.AsyncClient(transport=_st_transport())
    r = asyncio.run(saveticker.collect(store, client=client))
    assert r.status == "ok"
    ids = [i.id for i in r.items]
    assert "st-161415" in ids                    # 하이닉스 → 관련, detail 전문 획득
    assert "st-161424" not in ids                # 금값 → 무관 필터
    full = next(i for i in r.items if i.id == "st-161415")
    assert "290억 달러" in full.content           # detail 본문 병합 확인
    rumor = next(i for i in r.items if i.id == "st-161167")
    assert rumor.grade_hint == "D"               # (카더라) → D급
    assert store.get_state("saveticker_last_id") == 161424   # 커서 전진 (최대 id)
    if r.observations:
        store.append_observations(r.observations)
    cal = store.read_metric("macro_calendar", last_n=10)
    assert cal and cal[0].value == 3.0           # ★★★ = 3


def test_saveticker_incremental_skips_seen(tmp_path):
    from sector.collectors import saveticker
    store = SectorStore(tmp_path)
    store.set_state("saveticker_last_id", 161424)  # 전부 이미 봄
    client = httpx.AsyncClient(transport=_st_transport())
    r = asyncio.run(saveticker.collect(store, client=client))
    assert r.items == [] and r.status == "ok"
