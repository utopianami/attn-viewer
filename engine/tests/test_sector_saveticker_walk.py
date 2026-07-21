"""SaveTicker id-walk 헬퍼·collect (2026-07-21 firehose)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import pytest  # noqa: E402

from sector.collectors import saveticker as st  # noqa: E402
from sector.store import SectorStore  # noqa: E402


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    """테스트 속도 — 요청 간 throttle 제거."""
    monkeypatch.setattr(st, "REQUEST_INTERVAL_S", 0)


def _detail(nid, deleted=False, title="삼성전자 HBM 공급", created="2026-07-20T10:00:00+09:00",
            content_blocks=True, drop_title=False):
    return {"id": str(nid), "title": "" if drop_title else title, "created_at": created,
            "is_deleted": deleted, "source": "연합",
            "content": ([{"type": "text", "content": "본문 일부"}] if content_blocks else "flat")}


def _transport(detail_map, top_ids=None):
    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/api/news/top-stories":
            ids = top_ids if top_ids is not None else []
            return httpx.Response(200, json={"news_list": [
                {"id": str(i), "title": "t", "content": "c",
                 "created_at": "2026-07-20T10:00:00+09:00"} for i in ids]})
        if p.startswith("/api/news/detail/"):
            rid = int(p.rsplit("/", 1)[1])
            kind = detail_map.get(rid, "not_found")
            if kind == "not_found":
                return httpx.Response(404, json={})
            if kind == "transient":
                return httpx.Response(503, json={})
            if kind == "invalid":
                return httpx.Response(200, json={"news": {}})
            if kind == "deleted":
                return httpx.Response(200, json={"news": _detail(rid, deleted=True)})
            return httpx.Response(200, json={"news": _detail(rid)})
        if p == "/api/calendar/events":
            return httpx.Response(200, json={"events": []})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def _client(transport):
    return httpx.AsyncClient(transport=transport, base_url="https://api.saveticker.com",
                             headers={"User-Agent": "test"})


# ── Task 5: 헬퍼 ──────────────────────────────────────────────────────────────
def test_classify_five_kinds():
    dm = {1: "valid", 2: "deleted", 3: "not_found", 4: "transient", 5: "invalid"}

    async def run():
        async with _client(_transport(dm)) as c:
            b = st._Budget(100, 100, 0)
            return {rid: (await st._classify_detail(c, rid, b))[0] for rid in (1, 2, 3, 4, 5)}
    assert asyncio.run(run()) == {1: "valid", 2: "deleted", 3: "not_found",
                                  4: "transient", 5: "invalid"}


def test_classify_missing_required_is_invalid():
    def handler(req):
        return httpx.Response(200, json={"news": _detail(1, drop_title=True)})

    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return (await st._classify_detail(c, 1, st._Budget(10, 10, 0)))[0]
    assert asyncio.run(run()) == "invalid"


def test_newest_returns_max_and_known():
    async def run():
        async with _client(_transport({}, top_ids=[100, 105, 103])) as c:
            return await st._newest(c, st._Budget(10, 10, 0))
    mx, known = asyncio.run(run())
    assert mx == 105 and set(known) == {100, 105, 103}


def test_newest_only_sunset_notice_is_none():
    def handler(req):
        return httpx.Response(200, json={"news_list": [
            {"id": "legacy-news-sunset-notice", "title": "x", "created_at": ""}]})

    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return await st._newest(c, st._Budget(10, 10, 0))
    assert asyncio.run(run()) == (None, [])


def test_to_text_blocks_and_flat():
    assert st._to_text({"content": [{"type": "text", "content": " a "}, {"content": "b"}]}) == "a\nb"
    assert st._to_text({"content": "flat"}) == "flat"
    assert st._to_text({"content": None}) == ""


# ── Task 6: 캘린더 ────────────────────────────────────────────────────────────
def test_calendar_stars_and_fed():
    def handler(req):
        if req.url.path == "/api/calendar/events":
            return httpx.Response(200, json={"events": [
                {"title": "6월 CPI ★★★", "event_date": "2026-07-22T21:00:00"},
                {"title": "연준 인사 투표권 발언", "event_date": "2026-07-23T00:00:00"},
                {"title": "무의미 ★", "event_date": "2026-07-24T00:00:00"}]})
        return httpx.Response(404, json={})

    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return await st._collect_calendar(c, st._Budget(10, 10, 0))
    obs, ok = asyncio.run(run())
    assert ok is True
    assert sorted(o.meta["kind"] for o in obs) == ["fed_speech", "macro"]


def test_calendar_non200_returns_false():
    def handler(req):
        if req.url.path == "/api/calendar/events":
            return httpx.Response(500, json={})
        return httpx.Response(404, json={})

    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return await st._collect_calendar(c, st._Budget(10, 10, 0))
    obs, ok = asyncio.run(run())
    assert obs == [] and ok is False


# ── Task 7: collect ───────────────────────────────────────────────────────────
def _run_collect(store, detail_map, top_ids):
    async def run():
        async with _client(_transport(detail_map, top_ids=top_ids)) as c:
            return await st.collect(store, client=c)
    return asyncio.run(run())


def _prime(s, cursor=100, anchor=100, floor=100, pending=None):
    s.set_states({"saveticker_scan_hwm": cursor, "saveticker_observed_anchor": anchor,
                  "saveticker_cutover_floor": floor, "saveticker_pending": pending or {},
                  "saveticker_retry_pos": 0})


def test_seeding_sets_cursor_no_raw(tmp_path):
    s = SectorStore(tmp_path)
    r = _run_collect(s, {105: "valid"}, top_ids=[105])
    assert r.status == "degraded" and "seeded" in r.detail
    assert s.get_state("saveticker_scan_hwm") == 105
    assert s.get_state("saveticker_cutover_floor") == 105
    assert r.stats.get("raw_added", 0) == 0


def test_forward_collects_all_and_advances(tmp_path):
    s = SectorStore(tmp_path)
    _prime(s)
    r = _run_collect(s, {101: "valid", 102: "valid", 103: "valid"}, top_ids=[103])
    assert s.get_state("saveticker_scan_hwm") == 103
    assert r.stats["raw_added"] == 3
    p = tmp_path / "news_raw" / "2026-07.jsonl"
    assert len(p.read_text().splitlines()) == 3


def test_trailing_404_does_not_advance_past_last_valid(tmp_path):
    s = SectorStore(tmp_path)
    _prime(s)
    # anchor=100(valid, canary용), 101 valid, 102.. 모두 404
    r = _run_collect(s, {100: "valid", 101: "valid"}, top_ids=[100])
    assert s.get_state("saveticker_scan_hwm") == 101


def test_transient_hole_freezes_cursor_and_pends(tmp_path):
    s = SectorStore(tmp_path)
    _prime(s, anchor=103)
    r = _run_collect(s, {101: "transient", 102: "valid", 103: "valid"}, top_ids=[103])
    assert "101" in (s.get_state("saveticker_pending") or {})
    assert r.stats["raw_added"] == 2
    assert r.status == "degraded"


def test_pending_retry_resolves_next_cycle(tmp_path):
    s = SectorStore(tmp_path)
    _prime(s, cursor=103, anchor=103,
           pending={"101": {"kind": "transient", "attempts": 1}})
    r = _run_collect(s, {101: "valid", 103: "valid"}, top_ids=[103])   # 103=canary valid
    assert "101" not in (s.get_state("saveticker_pending") or {})
    assert r.stats["raw_added"] == 1


def test_canary_all_gone_is_error(tmp_path):
    s = SectorStore(tmp_path)
    _prime(s)
    r = _run_collect(s, {}, top_ids=[200, 201, 202])     # top 존재하나 detail 전부 404
    assert r.status == "error" and "canary" in r.detail


def test_relevant_items_newest_first_capped(tmp_path):
    s = SectorStore(tmp_path)
    _prime(s)

    def handler(req):
        p = req.url.path
        if p == "/api/news/top-stories":
            return httpx.Response(200, json={"news_list": [{"id": "101", "title": "t",
                "content": "c", "created_at": "2026-07-20T10:00:00+09:00"}]})
        if p.startswith("/api/news/detail/"):
            rid = int(p.rsplit("/", 1)[1])
            title = "삼성전자 HBM" if rid == 101 else "날씨 맑음"
            return httpx.Response(200, json={"news": _detail(rid, title=title)})
        if p == "/api/calendar/events":
            return httpx.Response(200, json={"events": []})
        return httpx.Response(404, json={})

    async def run():
        async with _client(httpx.MockTransport(handler)) as c:
            return await st.collect(s, client=c)
    r = asyncio.run(run())
    assert [it.id for it in r.items] == ["st-101"]      # 무관 102 제외


def test_card_candidate_cap_newest_first(tmp_path):
    """80상한 잠식 방지: judge 후보는 CARD_CANDIDATE_CAP개·최신순으로 제한(raw는 전량)."""
    s = SectorStore(tmp_path)
    _prime(s)                                            # cursor=anchor=100
    dm = {i: "valid" for i in range(100, 161)}           # 100=canary, 101~160 relevant(61건)
    r = _run_collect(s, dm, top_ids=[100])
    assert r.stats["raw_added"] == 60                    # 101~160 전량 raw 저장
    assert len(r.items) == st.CARD_CANDIDATE_CAP         # 후보는 40개로 제한
    ids = [int(it.id.split("-")[1]) for it in r.items]
    assert ids[0] == 160 and min(ids) == 121             # 최신 40개(160..121)
