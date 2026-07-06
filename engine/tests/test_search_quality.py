"""검색 품질 보강 (2026-07-06 스펙) — 지오 파라미터·노이즈 필터·쿼리 선택."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.settings import settings  # noqa: E402
from contracts.packets import NewsItem  # noqa: E402
from stages.ra_external import _clean_pool  # noqa: E402
from stages.plan import _g0_merge, _PlanA, _PlanB, _SubQ  # noqa: E402
from tools.news import brave  # noqa: E402


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"results": [], "web": {"results": []}}


def test_news_search_passes_geo_params(monkeypatch):
    """news_search가 country와 search_lang 파라미터를 API로 전달하는가."""
    captured = {}

    async def fake_get(self, url, params=None, headers=None):
        captured.update(params or {})
        return _FakeResp()

    monkeypatch.setattr(settings, "brave_api_key", "test-key")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def _run():
        async with httpx.AsyncClient() as hc:
            await brave.news_search("European utility stocks", country="us",
                                    search_lang="en", client=hc)

    asyncio.run(_run())
    assert captured["country"] == "us"
    assert captured["search_lang"] == "en"


def test_news_search_defaults_stay_kr(monkeypatch):
    """news_search 기본값은 country=kr, search_lang=ko (기존 하드코딩과 동일)."""
    captured = {}

    async def fake_get(self, url, params=None, headers=None):
        captured.update(params or {})
        return _FakeResp()

    monkeypatch.setattr(settings, "brave_api_key", "test-key")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def _run():
        async with httpx.AsyncClient() as hc:
            await brave.news_search("유럽 전력주", client=hc)

    asyncio.run(_run())
    assert captured["country"] == "kr"
    assert captured["search_lang"] == "ko"


def test_web_search_passes_geo_params(monkeypatch):
    """web_search가 country와 search_lang 파라미터를 API로 전달하는가."""
    captured = {}

    async def fake_get(self, url, params=None, headers=None):
        captured.update(params or {})
        return _FakeResp()

    monkeypatch.setattr(settings, "brave_api_key", "test-key")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def _run():
        async with httpx.AsyncClient() as hc:
            await brave.web_search("US banking regulations", country="us",
                                   search_lang="en", client=hc)

    asyncio.run(_run())
    assert captured["country"] == "us"
    assert captured["search_lang"] == "en"


def test_web_search_defaults_stay_kr(monkeypatch):
    """web_search 기본값은 country=kr, search_lang=ko (기존 하드코딩과 동일)."""
    captured = {}

    async def fake_get(self, url, params=None, headers=None):
        captured.update(params or {})
        return _FakeResp()

    monkeypatch.setattr(settings, "brave_api_key", "test-key")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def _run():
        async with httpx.AsyncClient() as hc:
            await brave.web_search("한국 금융규제", client=hc)

    asyncio.run(_run())
    assert captured["country"] == "kr"
    assert captured["search_lang"] == "ko"


# 2026-07-06 yvon 피드백 실사고 — storage/users/yvon/chats/0bdf0cba... ra_x 레이어 원본 12건
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
