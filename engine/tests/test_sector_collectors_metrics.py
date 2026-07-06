"""섹터 지표 수집기 테스트 — openrouter / status_pages / sdk_downloads / app_charts (P1 Task 5)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sector.store import SectorStore  # noqa: E402


# ─── openrouter ───────────────────────────────────────────────────────────────

def test_openrouter_models_snapshot_without_key(tmp_path, monkeypatch):
    from sector.collectors import openrouter as orc
    from app.settings import settings
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    models = {"data": [
        {"id": "anthropic/claude-sonnet-4.6", "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
        {"id": "meta-llama/tiny", "pricing": {"prompt": "0", "completion": "0"}},
    ]}
    def handler(request):
        assert request.url.path == "/api/v1/models"
        return httpx.Response(200, json=models)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(orc.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok" and "missing_key" in r.detail
    rows = store.read_metric("token_price")
    assert rows and abs(rows[0].value - 15.0) < 1e-6 and rows[0].meta["model"].startswith("anthropic/")


def test_openrouter_rankings_500_degrades_models_still_collected(tmp_path, monkeypatch):
    from sector.collectors import openrouter as orc
    from app.settings import settings
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key-abc")
    models = {"data": [
        {"id": "openai/gpt-5.5", "pricing": {"prompt": "0.000005", "completion": "0.000020"}},
        {"id": "deepseek/deepseek-r1", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
    ]}
    def handler(request):
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json=models)
        # rankings endpoint → 500
        return httpx.Response(500)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(orc.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "degraded"
    rows = store.read_metric("token_price")
    model_ids = {row.meta["model"] for row in rows}
    assert "openai/gpt-5.5" in model_ids
    assert "deepseek/deepseek-r1" in model_ids
    # meta-llama not tracked
    assert not any("meta-llama" in m for m in model_ids)


# ─── status_pages ─────────────────────────────────────────────────────────────

def test_status_pages_happy_path(tmp_path):
    from sector.collectors import status_pages as spc
    openai_data = {"incidents": [
        {"name": "API Slowdown", "status": "investigating"},
    ]}
    anthropic_data = {"incidents": []}

    def handler(request):
        host = request.url.host
        if "openai" in host:
            return httpx.Response(200, json=openai_data)
        if "anthropic" in host:
            return httpx.Response(200, json=anthropic_data)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(spc.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok"
    rows = store.read_metric("ai_status_incidents")
    by_provider = {row.meta["provider"]: row for row in rows}
    assert "openai" in by_provider and "anthropic" in by_provider
    assert by_provider["openai"].value == 1.0
    assert by_provider["openai"].meta["ongoing"] == ["API Slowdown"]
    assert by_provider["anthropic"].value == 0.0


def test_status_pages_one_provider_500_degrades(tmp_path):
    from sector.collectors import status_pages as spc
    anthropic_data = {"incidents": [{"name": "Partial Outage"}]}

    def handler(request):
        host = request.url.host
        if "openai" in host:
            return httpx.Response(500)
        if "anthropic" in host:
            return httpx.Response(200, json=anthropic_data)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(spc.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "degraded"
    rows = store.read_metric("ai_status_incidents")
    providers = {row.meta["provider"] for row in rows}
    assert "anthropic" in providers
    assert "openai" not in providers


# ─── sdk_downloads ────────────────────────────────────────────────────────────

def test_sdk_downloads_happy_path(tmp_path):
    from sector.collectors import sdk_downloads as sdk

    def handler(request):
        host = request.url.host
        path = request.url.path
        if "pypistats" in host:
            # /api/packages/{pkg}/recent
            pkg = path.split("/")[-2]
            counts = {"openai": 100_000, "anthropic": 50_000}
            return httpx.Response(200, json={"data": {"last_week": counts.get(pkg, 0)}})
        if "npmjs" in host:
            # /downloads/point/last-week/{pkg}  — pkg may contain '/' (e.g. @scope/name)
            pkg = path.split("last-week/")[-1]
            counts = {"openai": 200_000, "@anthropic-ai/sdk": 80_000}
            return httpx.Response(200, json={"downloads": counts.get(pkg, 0)})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(sdk.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok"
    rows = store.read_metric("sdk_downloads")
    # (pkg, ecosystem) pairs collected — note "openai" deduplicates (same key ts|openai)
    # at least anthropic(pypi) and @anthropic-ai/sdk(npm) should be present
    by_key = {(row.meta["pkg"], row.meta["ecosystem"]): row for row in rows}
    assert ("anthropic", "pypi") in by_key
    assert ("@anthropic-ai/sdk", "npm") in by_key
    assert by_key[("anthropic", "pypi")].value == 50_000.0
    assert by_key[("@anthropic-ai/sdk", "npm")].value == 80_000.0
    # openai appears in either ecosystem (pypi wins since it's collected first)
    openai_rows = [row for row in rows if row.meta["pkg"] == "openai"]
    assert openai_rows and openai_rows[0].value == 100_000.0


def test_sdk_downloads_one_source_500_degrades(tmp_path):
    from sector.collectors import sdk_downloads as sdk

    def handler(request):
        host = request.url.host
        path = request.url.path
        if "pypistats" in host:
            pkg = path.split("/")[-2]
            if pkg == "openai":
                return httpx.Response(500)  # one source fails
            return httpx.Response(200, json={"data": {"last_week": 50_000}})
        if "npmjs" in host:
            return httpx.Response(200, json={"downloads": 200_000})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(sdk.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "degraded"
    rows = store.read_metric("sdk_downloads")
    ecosystems = {row.meta["ecosystem"] for row in rows}
    # npm observations still collected despite pypi/openai failing
    assert "npm" in ecosystems
    pkgs = {row.meta["pkg"] for row in rows}
    assert "anthropic" in pkgs   # pypi/anthropic still OK


# ─── app_charts ───────────────────────────────────────────────────────────────

_US_FEED = {"feed": {"results": [
    {"name": "ChatGPT"},          # rank 1
    {"name": "Instagram"},        # rank 2 — not tracked
    {"name": "Gemini"},           # rank 3
    {"name": "TikTok"},           # rank 4 — not tracked
]}}

_KR_FEED = {"feed": {"results": [
    {"name": "YouTube"},          # rank 1 — not tracked
    {"name": "Claude - AI Assistant"},  # rank 2
    {"name": "Copilot"},          # rank 3
]}}


def test_app_charts_happy_path(tmp_path):
    from sector.collectors import app_charts as ac

    def handler(request):
        path = request.url.path
        if "/us/" in path:
            return httpx.Response(200, json=_US_FEED)
        if "/kr/" in path:
            return httpx.Response(200, json=_KR_FEED)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(ac.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok"
    rows = store.read_metric("app_rank")
    by_app_country = {(row.meta["app"], row.meta["country"]): row for row in rows}
    assert ("ChatGPT", "us") in by_app_country
    assert by_app_country[("ChatGPT", "us")].value == 1.0
    assert ("Gemini", "us") in by_app_country
    assert by_app_country[("Gemini", "us")].value == 3.0
    assert ("Claude", "kr") in by_app_country
    assert by_app_country[("Claude", "kr")].value == 2.0
    assert ("Copilot", "kr") in by_app_country
    assert by_app_country[("Copilot", "kr")].value == 3.0


def test_app_charts_one_country_500_degrades(tmp_path):
    from sector.collectors import app_charts as ac

    def handler(request):
        path = request.url.path
        if "/us/" in path:
            return httpx.Response(500)  # us fails
        if "/kr/" in path:
            return httpx.Response(200, json=_KR_FEED)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(ac.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "degraded" and "us" in r.detail
    rows = store.read_metric("app_rank")
    countries = {row.meta["country"] for row in rows}
    assert "kr" in countries
    assert "us" not in countries
