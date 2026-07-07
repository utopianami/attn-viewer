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


def test_brave_matrix_geo_and_dedup(tmp_path, monkeypatch):
    from sector.collectors import brave_matrix
    calls = []
    async def fake_news_search(query, *, count=5, freshness="pd",
                               country="kr", search_lang="ko", client=None):
        calls.append((query, country, search_lang))
        return [{"title": f"t-{query}", "url": "https://ex.com/a?utm_source=x",
                 "description": "d", "age": "", "source": "ex.com"},
                {"title": "dup", "url": "https://ex.com/a", "description": "", "age": "", "source": "ex.com"}]
    monkeypatch.setattr(brave_matrix, "news_search", fake_news_search)
    r = asyncio.run(brave_matrix.collect(SectorStore(tmp_path)))
    korean = [c for c in calls if c[1] == "kr"]
    english = [c for c in calls if c[1] == "us"]
    assert korean and english                      # 언어별 지오 라우팅
    assert len(r.items) == 1                       # norm_url dedup (utm 제거 후 동일)


def test_rss_parses_and_isolates_feed_failure(tmp_path, monkeypatch):
    from sector.collectors import rss as rssmod
    xml = b"""<?xml version="1.0"?><rss><channel>
      <item><title>SK hynix HBM4 supply</title><link>https://n.com/1</link>
      <pubDate>Mon, 06 Jul 2026 09:00:00 +0900</pubDate><description>d</description></item>
      <item><title>irrelevant kitten news</title><link>https://n.com/2</link></item>
    </channel></rss>"""
    def handler(request):
        if "etnews" in str(request.url):
            return httpx.Response(200, content=xml)
        return httpx.Response(500)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(rssmod.collect(SectorStore(tmp_path), client=client))
    assert [i.title for i in r.items] == ["SK hynix HBM4 supply"]   # 키워드 필터
    assert r.status == "degraded" and "trendforce" in r.detail.lower()


def test_collect_all_judge_failure_is_isolated(tmp_path, monkeypatch):
    """runner judge-failure 격리 — judge_fn이 raise해도 수집기 결과는 ok, judge=error 추가."""
    news_mod = types.ModuleType("news_only")
    news_mod.NAME, news_mod.KIND = "news_only", "news"
    async def collect_news(store, client=None):
        return CollectorResult(
            name="news_only", kind="news", status="ok",
            items=[RawNewsItem(id="j1", title="SK하이닉스 HBM4", content="c",
                               source="reuters", url="http://x",
                               published_at="2026-07-06T09:00:00Z")])
    news_mod.collect = collect_news
    monkeypatch.setattr(runner, "_registry", lambda: [news_mod])

    async def failing_judge(items):
        raise RuntimeError("judge exploded")

    store = SectorStore(tmp_path)
    results = asyncio.run(runner.collect_all(store, judge_fn=failing_judge))

    by_name = {r.name: r for r in results}
    assert by_name["news_only"].status == "ok"      # 수집기는 성공
    assert "judge" in by_name                        # judge 오류 결과 추가됨
    assert by_name["judge"].status == "error"
    assert "RuntimeError" in by_name["judge"].detail
    assert store.read_cards(days=None) == []         # 카드는 저장되지 않음
    assert store.read_status()["judge"]["status"] == "error"


def test_dart_edgar_without_key_runs_edgar_only(tmp_path, monkeypatch):
    from sector.collectors import dart_edgar
    from app.settings import settings
    monkeypatch.setattr(settings, "dart_api_key", "")
    import datetime as _dt
    today = _dt.date.today().isoformat()
    sub = {"filings": {"recent": {"form": ["8-K", "4"], "filingDate": [today, today],
                                  "accessionNumber": ["a1", "a2"],
                                  "primaryDocDescription": ["earnings", ""]}}}
    def handler(request):
        if "data.sec.gov" in str(request.url):
            return httpx.Response(200, json=sub)
        raise AssertionError("DART must not be called without key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(dart_edgar.collect(SectorStore(tmp_path), client=client))
    assert r.status == "ok" and "missing_key" in r.detail
    assert all(i.grade_hint == "S" for i in r.items)
    assert any("8-K" in i.title for i in r.items)
    assert not any("| 4" in i.title for i in r.items)   # form 4(내부자거래)는 제외


def test_saveticker_paginates_until_cursor(tmp_path):
    """12시간 사이 50건 초과 시 커서까지 페이지를 거슬러 올라감 (2026-07-07 유실 버그 회귀)."""
    from sector.collectors import saveticker
    pages = {
        1: [{"id": str(200 - i), "title": f"하이닉스 뉴스 {200 - i}", "content": "p",
             "source": "로이터", "created_at": "2026-07-07T10:00:00+09:00"} for i in range(50)],
        2: [{"id": str(150 - i), "title": f"하이닉스 뉴스 {150 - i}", "content": "p",
             "source": "로이터", "created_at": "2026-07-07T04:00:00+09:00"} for i in range(50)],
    }
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/api/news/list":
            page = int(request.url.params.get("page", "1"))
            calls.append(page)
            return httpx.Response(200, json={"news_list": pages.get(page, [])})
        if p.startswith("/api/news/detail/"):
            return httpx.Response(200, json={"news": {"id": "x", "title": "t",
                "content": [{"type": "text", "content": "본문"}], "source": "로이터"}})
        if p == "/api/calendar/events":
            return httpx.Response(200, json={"events": []})
        return httpx.Response(404)
    store = SectorStore(tmp_path)
    store.set_state("saveticker_last_id", 140)          # 커서: 2쪽 중간
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(saveticker.collect(store, client=client))
    assert calls[:2] == [1, 2]                          # 2쪽까지 내려감
    got_ids = {int(i.id.split("-")[1]) for i in r.items}
    assert 141 in got_ids and 151 in got_ids            # 커서~50건 사이 유실 없음
    assert 140 not in got_ids                           # 커서 이하 제외
    assert store.get_state("saveticker_last_id") == 200
