"""섹터 뉴스 수집기 + runner 격리 (P1 Task 2~4)."""
import asyncio
import datetime as dt
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


def test_saveticker_calendar_includes_fed_speeches(tmp_path):
    """연준 인사 발언(별 없음, '투표권' 포함)도 캘린더에 저장 (2026-07-07)."""
    from sector.collectors import saveticker
    cal = {"events": [
        {"id": 1, "title": "6월 ISM ★★★", "event_date": "2026-07-08T23:00:00"},
        {"id": 2, "title": "월러 이사 (비둘기/투표권 O)", "event_date": "2026-07-07T00:00:00"},
        {"id": 3, "title": "덜 중요한 것 ★", "event_date": "2026-07-09T00:00:00"},
    ]}
    def handler(request):
        p = request.url.path
        if p == "/api/news/list":
            return httpx.Response(200, json={"news_list": []})
        if p == "/api/calendar/events":
            return httpx.Response(200, json=cal)
        return httpx.Response(404)
    store = SectorStore(tmp_path)
    r = asyncio.run(saveticker.collect(store, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    titles = [o.meta["title"] for o in r.observations]
    assert any("투표권" in t for t in titles)          # 연준 발언 포함
    assert not any(t == "덜 중요한 것 ★" for t in titles)   # ★1 제외 유지
    fed = next(o for o in r.observations if "투표권" in o.meta["title"])
    assert fed.meta["kind"] == "fed_speech"


# ─── dart — IR 개최 공시 → 실적 캘린더 확정 승격 ─────────────────────────────

def test_parse_ir_date_formats():
    from sector.collectors.dart_edgar import parse_ir_date
    base = dt.date(2026, 7, 8)
    assert parse_ir_date("1. 일시 : 2026년 7월 23일 (목) 16:00", base) == dt.date(2026, 7, 23)
    assert parse_ir_date("개최일시: 2026.07.24 09:00", base) == dt.date(2026, 7, 24)
    assert parse_ir_date("일시 2026-07-27 오후", base) == dt.date(2026, 7, 27)
    assert parse_ir_date("일시: 2026년 1월 5일", base) is None      # 과거 날짜 = 오탐 방지
    assert parse_ir_date("장소: 여의도. 문의: 02-1234-5678", base) is None  # 날짜 없음


def test_dart_ir_disclosure_emits_confirmed_calendar(tmp_path, monkeypatch):
    from app.settings import settings
    """기업설명회 공시 → earnings_calendar(kind=confirmed) 방출. 본문 파싱 실패 시 스킵."""
    import io, zipfile
    from sector.collectors import dart_edgar
    monkeypatch.setattr(settings, "dart_api_key", "k")
    def make_zip(text):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("doc.xml", f"<BODY><P>1. 일시 : {text}</P></BODY>")
        return buf.getvalue()
    def handler(request):
        host = request.url.host
        if host == "opendart.fss.or.kr" and "list.json" in str(request.url):
            corp = "삼성전자" if request.url.params["corp_code"] == "00126380" else "SK하이닉스"
            rcpt = "20260710000001" if corp == "삼성전자" else "20260710000002"
            return httpx.Response(200, json={"status": "000", "list": [
                {"rcept_no": rcpt, "report_nm": "기업설명회(IR)개최(안내공시)", "rcept_dt": "20260710"}]})
        if host == "opendart.fss.or.kr" and "document.xml" in str(request.url):
            if request.url.params["rcept_no"] == "20260710000001":
                return httpx.Response(200, content=make_zip("2026년 7월 30일 (목) 10:00"))
            return httpx.Response(200, content=make_zip("장소만 있고 날짜 없음"))   # 파싱 실패 케이스
        return httpx.Response(500)                                   # edgar 등은 실패 격리
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(dart_edgar._dt, "date",
                        type("D", (dt.date,), {"today": staticmethod(lambda: dt.date(2026, 7, 10))}))
    store = SectorStore(tmp_path)
    r = asyncio.run(dart_edgar.collect(store, client=client))
    store.append_observations(r.observations)
    rows = store.read_metric("earnings_calendar", last_n=10)
    assert len(rows) == 1                                            # 파싱 실패분은 방출 안 됨
    o = rows[0]
    assert o.ts == "2026-07-30" and o.meta["item"] == "삼성전자"
    assert o.meta["kind"] == "confirmed" and o.meta["provider"] == "dart"
    assert any("기업설명회" in i.title for i in r.items)             # 뉴스 카드 원료는 그대로


def test_collect_all_emits_scheduled_calendar(tmp_path, monkeypatch):
    """judge가 카드에 미래 일정을 실으면 runner가 캘린더 지표로 자동 방출."""
    from sector.contracts import SectorCard
    news_mod = types.ModuleType("news_only")
    news_mod.NAME, news_mod.KIND = "news_only", "news"
    async def collect_news(store, client=None):
        return CollectorResult(name="news_only", kind="news", status="ok",
            items=[RawNewsItem(id="n1", title="t", content="c", source="reuters",
                               url="http://x", published_at="2026-07-08T09:00:00Z")])
    news_mod.collect = collect_news
    monkeypatch.setattr(runner, "_registry", lambda: [news_mod])
    async def judge_fn(items):
        return [SectorCard(id="n1", ts="2026-07-08T09:00:00Z", axis="A", title="t",
                           entities=["SK_HYNIX"], scheduled_date="2026-07-10",
                           scheduled_label="나스닥 ADR 상장")]
    store = SectorStore(tmp_path)
    asyncio.run(runner.collect_all(store, judge_fn=judge_fn))
    rows = store.read_metric("earnings_calendar", last_n=10)
    assert rows and rows[0].meta["kind"] == "event" and rows[0].ts == "2026-07-10"


def test_brave_matrix_query_budget():
    """월 무료 크레딧($5=1,000쿼리) 안: 8쿼리×2회/일×31일 ≈ 496 (2026-07-09 다이어트)."""
    from sector.collectors.brave_matrix import _QUERIES
    assert len(_QUERIES) <= 8


def test_brave_matrix_quota_402_early_abort(tmp_path, monkeypatch):
    """크레딧 소진(402)이면 나머지 쿼리 헛호출 없이 조기 중단 + 사유 명시."""
    from sector.collectors import brave_matrix
    calls = []
    async def fake_news_search(query, **kw):
        calls.append(query)
        req = httpx.Request("GET", "https://api.search.brave.com")
        raise httpx.HTTPStatusError("402", request=req,
                                    response=httpx.Response(402, request=req))
    monkeypatch.setattr(brave_matrix, "news_search", fake_news_search)
    r = asyncio.run(brave_matrix.collect(SectorStore(tmp_path)))
    assert len(calls) == 1
    assert r.status == "degraded" and "quota" in r.detail
