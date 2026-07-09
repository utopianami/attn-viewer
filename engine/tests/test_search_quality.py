"""검색 품질 보강 (2026-07-06 스펙) — 지오 파라미터·노이즈 필터·쿼리 선택."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.settings import settings  # noqa: E402
from contracts.packets import NewsItem  # noqa: E402
from stages.ra_external import _clean_pool  # noqa: E402
from stages.plan import _g0_merge, _PlanA, _PlanB, _SubQ  # noqa: E402


YVON_RA_X_FIXTURE = [
    ("미국 동부 폭염·폭풍에 전력난 심화…전기요금 급등·100만 가구 정전", "https://theguru.co.kr/news/article.html?no=103980"),
    ("삼전 실적발표·하닉 나스닥 데뷔 [7/6~7/10 투자캘린더]│Global Money Club", "https://joongang.co.kr/gmc/article/25442473"),
    ("한은, 삼전·하이닉스 레버리지 ETF 경고⋯쏠림 심화 우려 - 이투데이", "https://etoday.co.kr/news/view/2600308"),
    ("독자 최애 코너는 투자 고수에게 듣는다 | 한국경제", "https://hankyung.com/article/2026070565251"),
    ("OPEC+, 5개월 연속 증산 전망…내년엔 공급과잉 가능성", "https://view.asiae.co.kr/article/2026070515221002820"),
    ("Heat wave: European countries report 3,700 excess deaths", "https://dw.com/en/heat-wave-european-countries-report-3700-excess-deaths/a-77823303"),
    ("보지냐 골키퍼 세계 랭킹 1위 등극", "https://bbs.ruliweb.com/community/board/300143/read/75832692"),
    ("삼전·닉스 더갈까?…반도체 쏠림 장세 속 숨은 소부장株는", "https://ebn.co.kr/news/articleView.html?idxno=1715170"),
    ("유럽 퍼킹 코리안들아 너희 열돔 다시 가져가라고", "https://bbs.ruliweb.com/community/board/300143/read/75821172"),
    ("유럽 실적 시즌 프리뷰: 애널리스트가 주목하는 3가지 포인트", "https://kr.investing.com/news/stock-market-news/article-2005049"),
    ("유럽 폭염 근황 ㄷㄷ - 포텐 터짐 최신순 - 에펨코리아", "https://www.fmkorea.com/best/10044003905"),
    ("유럽 폭염 근황 ㄷㄷ - 포텐 터짐 최신순 - 에펨코리아", "https://www.fmkorea.com/best/10044003905"),
]


def test_clean_pool_blocks_community_and_dedupes():
    items = [NewsItem(title=t, url=u) for t, u in YVON_RA_X_FIXTURE]
    cleaned = _clean_pool(items)
    urls = [n.url for n in cleaned]
    assert len(cleaned) == 8  # 루리웹 2건 + 펨코 2건(중복 포함) 제거
    assert not any("ruliweb.com" in u for u in urls)
    assert not any("fmkorea.com" in u for u in urls)
    assert "https://dw.com/en/heat-wave-european-countries-report-3700-excess-deaths/a-77823303" in urls


def test_clean_pool_dedupes_by_normalized_url():
    items = [
        NewsItem(title="a", url="https://Example.com/news/1?utm=x"),
        NewsItem(title="b", url="https://example.com/news/1"),
    ]
    assert len(_clean_pool(items)) == 1


def test_clean_pool_blocks_subdomains():
    items = [NewsItem(title="글", url="https://gall.dcinside.com/board/view/?id=stock&no=1")]
    assert _clean_pool(items) == []


def test_g0_merge_carries_market_scope_and_sub_queries():
    a = _PlanA(
        standalone_question="유럽 전력주 전망", tier=3, knowledge_cutoff="2026-07-06",
        market_scope="global",
        sub_questions=[_SubQ(id="q1", text="유럽 유틸리티 주가",
                             search_queries=["European utility stocks 2026"])],
        search_queries=["Europe power crisis utilities"],
    )
    plan = _g0_merge("유럽 전력주 전망", [], a, _PlanB())
    assert plan.market_scope == "global"
    assert plan.sub_questions[0].search_queries == ["European utility stocks 2026"]


def test_g0_merge_invalid_scope_falls_back_to_kr():
    a = _PlanA(standalone_question="q", tier=1, knowledge_cutoff="2026-07-06",
               market_scope="europe")  # 어휘 밖 값
    plan = _g0_merge("q", [], a, _PlanB())
    assert plan.market_scope == "kr"


# ── Task 4: _geo_params + _unit_search_query (2026-07-06) ──────────────────

from stages.ra_external import _geo_params, _unit_search_query  # noqa: E402
from contracts.packets import PlanPacket, SubQuestion  # noqa: E402


def _mini_plan(**kw):
    base = dict(tier=2, original_question="지금 유럽에 전력난이잖아. 유럽 전력주식들 조사해줘",
                standalone_question="유럽 전력주 조사", knowledge_cutoff="2026-07-06")
    base.update(kw)
    return PlanPacket(**base)


def test_geo_params_by_scope():
    assert _geo_params("European utilities", "global") == {"country": "us", "search_lang": "en"}
    assert _geo_params("유럽 전력주", "kr") == {"country": "kr", "search_lang": "ko"}
    # mixed는 쿼리 언어로 판정
    assert _geo_params("유럽 전력주 전망", "mixed") == {"country": "kr", "search_lang": "ko"}
    assert _geo_params("European utility stocks", "mixed") == {"country": "us", "search_lang": "en"}


def test_unit_search_query_prefers_planner_queries():
    plan = _mini_plan(search_queries=["European utility stocks heatwave"])
    assert _unit_search_query(plan, "q0") == "European utility stocks heatwave"


def test_unit_search_query_falls_back_to_question():
    plan = _mini_plan()
    assert _unit_search_query(plan, "q0") == "유럽 전력주 조사"


def test_unit_search_query_subquestion():
    plan = _mini_plan(sub_questions=[SubQuestion(
        id="q1", text="유럽 유틸리티 주가", search_queries=["Iberdrola RWE stock 2026"])])
    assert _unit_search_query(plan, "q1") == "Iberdrola RWE stock 2026"


# ── Task 5: Sonnet 역할 등록 ──────────────────────────────────────────

from providers import ROLE_MAP, CostMeter, _PRICE_PER_M  # noqa: E402


def test_news_summary_role_uses_sonnet():
    chain = ROLE_MAP["news_summary"]
    assert chain[0] == ("anthropic", "claude-sonnet-4-6", "low")
    assert chain[1][0] == "openai"  # gpt-mini 폴백


def test_sonnet_price_bucket():
    assert _PRICE_PER_M["anthropic_sonnet"] == (3.0, 15.0)
    meter = CostMeter()
    meter.add("anthropic", "claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert meter.usd["claude"] == pytest.approx(18.0)  # 3 + 15


def test_opus_bucket_unchanged():
    meter = CostMeter()
    meter.add("anthropic", "claude-opus-4-8", 1_000_000, 0)
    assert meter.usd["claude"] == pytest.approx(5.0)


# ── Task 6: news_summary 스테이지 ──────────────────────────────────────────

from contracts.packets import NewsSummaryPacket, NewsSummaryLine, LAYER_NAMES, RaPacket  # noqa: E402
from stages import news_summary as ns_stage  # noqa: E402


def test_news_summary_layer_registered():
    assert "news_summary" in LAYER_NAMES


def test_news_summary_returns_none_without_news():
    async def _run():
        plan = _mini_plan()
        ra = RaPacket(status="ok")
        return await ns_stage.run_news_summary(plan, ra)

    assert asyncio.run(_run()) is None


def test_news_summary_builds_packet(monkeypatch):
    async def _run():
        plan = _mini_plan()
        ra = RaPacket(status="ok", x_search={"q0": [NewsItem(
            id="q0:n0", title="Heat wave hits Europe", summary="3,700 deaths",
            url="https://dw.com/a")]})

        class _FakeRole:
            def __init__(self, *a, **k):
                pass

            async def run(self, *a, **k):
                return ns_stage._Summary(lines=[
                    ns_stage._Line(text="유럽 폭염으로 전력 수요 급증", url="https://dw.com/a")])

        monkeypatch.setattr(ns_stage, "Role", _FakeRole)
        packet = await ns_stage.run_news_summary(plan, ra)
        return packet

    packet = asyncio.run(_run())
    assert isinstance(packet, NewsSummaryPacket)
    assert packet.lines[0].url == "https://dw.com/a"
    assert packet.as_of == "2026-07-06"


# ── Task 7: ra_x 큐레이션 방출 + news_summary 합성 연결 ──────────────────

from contracts.packets import DaPacket  # noqa: E402
from stages.synthesize import _render_context  # noqa: E402
from orchestrator import _ra_x_layer_data  # noqa: E402


def test_ra_x_layer_emits_curated_only():
    raw = [NewsItem(id=f"q0:n{i}", title=f"t{i}", url=f"https://ex.com/{i}") for i in range(4)]
    ra = RaPacket(status="ok", x_search={"q0": raw}, curated={"q0": ["q0:n1", "q0:n3"]})
    data = _ra_x_layer_data(ra)
    urls = [it["url"] for it in data["items"]]
    assert urls == ["https://ex.com/1", "https://ex.com/3"]


def test_ra_x_layer_falls_back_to_all_when_no_curation():
    raw = [NewsItem(id="q0:n0", title="t", url="https://ex.com/0")]
    ra = RaPacket(status="ok", x_search={"q0": raw})
    assert len(_ra_x_layer_data(ra)["items"]) == 1


def test_render_context_includes_news_summary():
    summary = NewsSummaryPacket(lines=[NewsSummaryLine(
        text="유럽 폭염으로 전력 수요 급증", url="https://dw.com/a")], as_of="2026-07-06")
    ctx = _render_context(_mini_plan(), DaPacket(status="ok"), None, None, None, None, [], None,
                          news_summary=summary)
    assert "[뉴스 요약]" in ctx
    assert "https://dw.com/a" in ctx


# ── 최종 리뷰 반영 (2026-07-06) — 재조사 지오/필터, URL 정규화, 유닛 간 중복, plan 노출 ──

from stages import ra_external  # noqa: E402
from stages import news_summary as ns_stage2  # noqa: E402
from orchestrator import _plan_layer_data  # noqa: E402


def test_ra_research_routes_geo_and_cleans_pool(monkeypatch):
    """REFLECT 재조사도 본조사와 동일하게 지오 라우팅 + 커뮤니티 필터를 거쳐야 한다."""
    captured = {}

    async def fake_search(query, *, freshness, client, count=5, geo=None):
        captured["geo"] = geo
        return [
            {"title": "보지냐 골키퍼 세계 랭킹 1위",
             "url": "https://bbs.ruliweb.com/community/board/300143/read/1",
             "description": "", "age": "", "source": "ruliweb"},
            {"title": "European utilities rally on heatwave demand",
             "url": "https://dw.com/en/european-utilities-rally/a-1",
             "description": "", "age": "", "source": "dw"},
        ]

    async def fake_fetch(items, top_n=5):
        return None

    async def fake_claims(pools, found, overrides):
        return []

    monkeypatch.setattr(ra_external, "_search_fallback", fake_search)
    monkeypatch.setattr(ra_external, "fetch_bodies", fake_fetch)
    monkeypatch.setattr(ra_external, "_extract_claims", fake_claims)

    found, _claims = asyncio.run(ra_external.run_ra_research(
        ["European utility stocks"], seen_urls=set(), market_scope="global"))
    assert captured["geo"] == {"country": "us", "search_lang": "en"}
    urls = [n.url for pool in found.values() for n in pool]
    assert urls == ["https://dw.com/en/european-utilities-rally/a-1"]


def test_clean_pool_keeps_distinct_article_id_queries():
    """기사 ID를 쿼리스트링에 싣는 사이트(theguru 등)는 no= 값이 다르면 별개 기사다."""
    items = [
        NewsItem(title="a", url="https://theguru.co.kr/news/article.html?no=103980"),
        NewsItem(title="b", url="https://theguru.co.kr/news/article.html?no=103981"),
    ]
    assert len(_clean_pool(items)) == 2


def test_clean_pool_strips_utm_prefixed_params():
    """utm_source 등 추적 파라미터만 다른 URL은 동일 문서 — 1건으로 dedup."""
    items = [
        NewsItem(title="a", url="https://example.com/news/1?utm_source=a"),
        NewsItem(title="b", url="https://example.com/news/1"),
    ]
    assert len(_clean_pool(items)) == 1


def test_ra_x_layer_dedupes_cross_unit_urls():
    """같은 URL이 q0·q1 풀에 모두 있으면 ra_x 레이어에는 1번만 나가야 한다."""
    ra = RaPacket(status="ok", x_search={
        "q0": [NewsItem(id="q0:n0", title="dup", url="https://ex.com/a")],
        "q1": [NewsItem(id="q1:n0", title="dup", url="https://ex.com/a")],
    })
    data = _ra_x_layer_data(ra)
    assert len(data["items"]) == 1


def test_news_summary_dedupes_cross_unit_urls(monkeypatch):
    """news_summary 입력에서도 유닛 간 동일 URL은 1건으로 합쳐져야 한다."""
    async def _run():
        plan = _mini_plan()
        ra = RaPacket(status="ok", x_search={
            "q0": [NewsItem(id="q0:n0", title="dup", url="https://dw.com/a")],
            "q1": [NewsItem(id="q1:n0", title="dup", url="https://dw.com/a")],
        })
        seen = {}

        class _FakeRole:
            def __init__(self, *a, **k):
                pass

            async def run(self, prompt, *a, **k):
                seen["prompt"] = prompt
                return ns_stage2._Summary(lines=[])

        monkeypatch.setattr(ns_stage2, "Role", _FakeRole)
        await ns_stage2.run_news_summary(plan, ra)
        return seen["prompt"]

    prompt = asyncio.run(_run())
    assert prompt.count("https://dw.com/a") == 1


def test_plan_layer_exposes_market_scope_and_queries():
    plan = _mini_plan(market_scope="global", search_queries=["x"],
                      sub_questions=[SubQuestion(id="q1", text="t",
                                                 search_queries=["y"])])
    data = _plan_layer_data(plan)
    assert data["market_scope"] == "global"
    assert data["search_queries"] == ["x"]
    assert data["sub_questions"][0]["search_queries"] == ["y"]
