"""뉴스 검색 체인 오프라인 테스트 (2026-07-09 개편: kr=네이버→구글RSS, global=구글RSS. brave 없음).

각 단계 실패·빈 결과 시 다음 단계로 넘어가는 폴백 순서를 검증.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stages.ra_external as ra  # noqa: E402

_ROW = [{"title": "t", "url": "https://x.com/1", "description": "", "age": "", "source": "s"}]


def _stub(rows=None, exc=None, log=None, name=""):
    async def f(*a, **k):
        if log is not None:
            log.append(name)
        if exc:
            raise exc
        return rows or []
    return f


def test_kr_chain_order_naver_first(monkeypatch):
    log = []
    monkeypatch.setattr(ra, "naver_news_search", _stub(rows=_ROW, log=log, name="naver"))
    monkeypatch.setattr(ra, "gnews_search", _stub(rows=_ROW, log=log, name="gnews"))
    rows = asyncio.run(ra._search_fallback("삼성전자", freshness="pd", client=None,
                                           geo={"country": "kr", "search_lang": "ko"}))
    assert rows == _ROW and log == ["naver"]  # 네이버가 주면 거기서 끝


def test_kr_chain_falls_through(monkeypatch):
    """네이버 실패(스코프 미활성 등) → 구글RSS(ko). 전부 비면 빈 결과."""
    log = []
    monkeypatch.setattr(ra, "naver_news_search", _stub(exc=RuntimeError("024"), log=log, name="naver"))
    monkeypatch.setattr(ra, "gnews_search", _stub(rows=_ROW, log=log, name="gnews"))
    rows = asyncio.run(ra._search_fallback("삼성전자", freshness="pd", client=None,
                                           geo={"country": "kr", "search_lang": "ko"}))
    assert rows == _ROW and log == ["naver", "gnews"]


def test_global_chain_skips_naver(monkeypatch):
    log = []
    monkeypatch.setattr(ra, "naver_news_search", _stub(rows=_ROW, log=log, name="naver"))
    monkeypatch.setattr(ra, "gnews_search", _stub(rows=_ROW, log=log, name="gnews"))
    rows = asyncio.run(ra._search_fallback("Micron HBM", freshness="pw", client=None,
                                           geo={"country": "us", "search_lang": "en"}))
    assert rows == _ROW and log == ["gnews"]  # 해외는 네이버 건너뜀


def test_all_fail_returns_empty(monkeypatch):
    monkeypatch.setattr(ra, "naver_news_search", _stub(exc=RuntimeError()))
    monkeypatch.setattr(ra, "gnews_search", _stub(exc=RuntimeError()))
    rows = asyncio.run(ra._search_fallback("q", freshness="pd", client=None,
                                           geo={"country": "kr", "search_lang": "ko"}))
    assert rows == []
