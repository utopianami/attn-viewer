"""Task 5: bundle 모드 — cutoff 고정·라이브 경로 봉인 테스트.

monkeypatch 대상은 ra_external.py에 실존하는 모듈 수준 함수로 봉인:
  - naver_news_search, gnews_search (raising=True — 실존 확인 포함)
  - _search_fallback, _collect_web_knowledge, collect_feed, collect_company

price_macro 봉인 대상: collect_macro (module-level import)
"""

import asyncio

import pytest

from contracts.packets import PlanPacket


def _plan() -> PlanPacket:
    return PlanPacket(tier=2, original_question="하이닉스 전망",
                      standalone_question="하이닉스 전망",
                      knowledge_cutoff="2026-07-10")


def test_price_macro_snapshot_no_network(monkeypatch):
    import stages.price_macro as pm

    def _boom(*a, **k):
        raise AssertionError("live fetch called in snapshot mode")

    # 라이브 fetch 경로 전부 봉인 — snapshot 분기가 호출하면 즉시 실패
    monkeypatch.setattr(pm, "collect_macro", _boom, raising=True)
    monkeypatch.setattr(pm, "quote", _boom, raising=True)
    for name in dir(pm):
        if name.startswith("_fetch"):
            monkeypatch.setattr(pm, name, _boom, raising=False)

    # r2-B5: 실제 quote() 반환 스키마(token·last — yahoo.py:79, price_macro.py:33)만 사용
    snap = {"quotes": [{"token": "005930.KS", "last": 254500.0, "cur": "KRW"}],
            "macro": {}}
    from stages.price_macro import run_price_macro
    pkt = asyncio.run(run_price_macro(_plan(), snapshot=snap))
    assert pkt.quotes and pkt.quotes[0]["token"] == "005930.KS"
    assert pkt.macro == {}
    # typed_facts에 통화 반영 확인
    assert pkt.typed_facts and pkt.typed_facts[0].unit == "KRW"


def test_ra_external_bundle_items_no_live(monkeypatch):
    import stages.ra_external as ra

    def _boom(*a, **k):
        raise AssertionError("live search called in bundle mode")

    # raising=True — 실존 함수명 확인 (최소 2개)
    monkeypatch.setattr(ra, "naver_news_search", _boom, raising=True)
    monkeypatch.setattr(ra, "gnews_search", _boom, raising=True)
    # 나머지 수집 경로도 봉인 (raising=False — 이름 변경 대비)
    monkeypatch.setattr(ra, "_search_fallback", _boom, raising=False)
    monkeypatch.setattr(ra, "_collect_web_knowledge", _boom, raising=False)
    monkeypatch.setattr(ra, "collect_feed", _boom, raising=False)
    monkeypatch.setattr(ra, "collect_company", _boom, raising=False)

    # r2-B5: NewsItem은 extra-forbid — 반드시 실계약으로 생성 후 model_dump()
    from contracts.packets import NewsItem
    item = NewsItem(id="n1", title="t", url="https://a.example/1",
                    published_at="2026-07-09", summary="s")

    from stages.ra_external import run_ra_external
    pkt = asyncio.run(run_ra_external(_plan(), None, bundle_items=[item.model_dump()]))
    got = [n for lst in pkt.web_knowledge.values() for n in lst]
    assert [n.url for n in got] == ["https://a.example/1"]
