"""검색 품질 보강 (2026-07-06 스펙) — 지오 파라미터·노이즈 필터·쿼리 선택."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.settings import settings  # noqa: E402
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
