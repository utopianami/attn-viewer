"""섹터 지표 수집기 테스트 — openrouter / status_pages / sdk_downloads / app_charts (P1 Task 5)."""
import asyncio
import datetime as dt
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
        if "anthropic" in host or "claude" in host:
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
        if "anthropic" in host or "claude" in host:
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


# ─── 공통: 키 게이트 수집기는 키 없으면 HTTP 호출 자체가 없어야 함 ─────────────

def _trap_client():
    """호출되면 즉시 실패하는 클라이언트 — missing_key 경로 검증용."""
    def handler(request):
        raise AssertionError(f"missing_key인데 HTTP 호출 발생: {request.url}")
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ─── mops_tw ──────────────────────────────────────────────────────────────────

_MOPS_CSV = ("﻿出表日期,資料年月,公司代號,公司名稱,產業別,營業收入-當月營收,營業收入-上月營收,"
             "營業收入-去年當月營收,營業收入-上月比較增減(%),營業收入-去年同月增減(%),"
             "累計營業收入-當月累計營收,累計營業收入-去年累計營收,累計營業收入-前期比較增減(%),備註\n"
             "1150707,11506,2330,台積電,半導體業,263710000,250000000,207870000,5.4,26.8,"
             "1500000000,1200000000,25.0,-\n"
             "1150707,11506,9999,無關公司,其他,100,90,80,1,1,10,8,2,-\n")


def test_mops_filters_and_converts_roc_date(tmp_path):
    from sector.collectors import mops_tw

    def handler(request):
        return httpx.Response(200, content=_MOPS_CSV.encode("utf-8"))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(mops_tw.collect(SectorStore(tmp_path), client=client))
    assert r.status == "ok"
    assert len(r.observations) == 1
    o = r.observations[0]
    assert o.metric == "tw_monthly_revenue"
    assert o.ts == "2026-06" and o.meta["name"] == "TSMC" and o.meta["yoy"] == 26.8
    assert o.meta["mom"] == 5.4                      # 전월비 — 모멘텀 지표 (2026-07-07 추가)
    assert o.value == 263710000.0
    assert o.meta["code"] == "2330"


def test_mops_fetch_failure_is_error(tmp_path):
    from sector.collectors import mops_tw

    def handler(request):
        return httpx.Response(500)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(mops_tw.collect(SectorStore(tmp_path), client=client))
    assert r.status == "error" and not r.observations


# ─── customs_kr ───────────────────────────────────────────────────────────────

def test_customs_kr_missing_key_no_http(tmp_path, monkeypatch):
    from sector.collectors import customs_kr
    from app.settings import settings
    monkeypatch.setattr(settings, "data_go_kr_api_key", "")
    r = asyncio.run(customs_kr.collect(SectorStore(tmp_path), client=_trap_client()))
    assert r.status == "missing_key" and "data_go_kr_api_key" in r.detail


def test_customs_kr_happy_path(tmp_path, monkeypatch):
    """2026-07-07 실측 XML 스키마 — prlstMmUtPrviExpAcrs (10일 잠정치, 반도체=Amt01)."""
    from sector.collectors import customs_kr
    from app.settings import settings
    monkeypatch.setattr(settings, "data_go_kr_api_key", "test-customs-key")
    xml = ("""<?xml version="1.0" encoding="UTF-8" standalone="yes"?><response>"""
           """<header><resultCode>00</resultCode><resultMsg>정상서비스.</resultMsg></header>"""
           """<body><items>"""
           """<item><itemUsdAmt00>          17,995,463</itemUsdAmt00>"""
           """<itemUsdAmt01>           8,538,616</itemUsdAmt01>"""
           """<priodDt>01~10</priodDt><priodMon>202605</priodMon><priodYear>2026</priodYear></item>"""
           """<item><itemUsdAmt00>35,000,000</itemUsdAmt00><itemUsdAmt01>17,000,000</itemUsdAmt01>"""
           """<priodDt>01~20</priodDt><priodMon>202605</priodMon><priodYear>2026</priodYear></item>"""
           """</items></body></response>""")

    def handler(request):
        assert "prlstMmUtPrviExpAcrs" in str(request.url)
        assert request.url.params["serviceKey"] == "test-customs-key"
        return httpx.Response(200, content=xml.encode("utf-8"))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(customs_kr.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok"
    rows = store.read_metric("kr_semi_export")
    assert len(rows) == 2                                  # 구간별(01~10, 01~20) 공존
    early = next(o for o in rows if o.meta["item"] == "01~10")
    assert early.ts == "2026-05" and early.value == 8538616.0
    share = store.read_metric("kr_semi_export_share")
    assert share and abs(next(o.value for o in share if o.meta["item"] == "01~10") - 47.45) < 0.1


def test_customs_kr_unexpected_shape_degrades(tmp_path, monkeypatch):
    from sector.collectors import customs_kr
    from app.settings import settings
    monkeypatch.setattr(settings, "data_go_kr_api_key", "test-customs-key")

    def handler(request):
        return httpx.Response(200, json={"cmmMsgHeader": {"returnAuthMsg": "SERVICE_KEY_IS_NOT_REGISTERED"}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(customs_kr.collect(SectorStore(tmp_path), client=client))
    assert r.status == "degraded" and ("XML parse" in r.detail or "resultCode" in r.detail)


# ─── kosis ────────────────────────────────────────────────────────────────────

def test_kosis_missing_key_no_http(tmp_path, monkeypatch):
    from sector.collectors import kosis
    from app.settings import settings
    monkeypatch.setattr(settings, "kosis_api_key", "")
    r = asyncio.run(kosis.collect(SectorStore(tmp_path), client=_trap_client()))
    assert r.status == "missing_key" and "kosis_api_key" in r.detail


def test_kosis_happy_path(tmp_path, monkeypatch):
    from sector.collectors import kosis
    from app.settings import settings
    monkeypatch.setattr(settings, "kosis_api_key", "test-kosis-key")
    payload = [
        {"PRD_DE": "202605", "DT": "112.3", "C1_NM": "반도체 및 부품",
         "ITM_NM": "생산자제품 재고지수(계절조정)"},
        {"PRD_DE": "202605", "DT": "140.0", "C1_NM": "반도체 및 부품",
         "ITM_NM": "산업생산지수(원지수)"},          # 원지수는 제외돼야 함
        {"PRD_DE": "202605", "DT": "50.0", "C1_NM": "자동차", "ITM_NM": "산업생산지수(계절조정)"},
    ]

    def handler(request):
        assert request.url.params["tblId"] == "DT_1F02011"
        assert request.url.params["itmId"] == "ALL"
        assert request.url.params["apiKey"] == "test-kosis-key"
        return httpx.Response(200, json=payload)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(kosis.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok"
    rows = store.read_metric("kr_semi_production_index")
    assert len(rows) == 1
    assert rows[0].ts == "2026-05" and rows[0].value == 112.3
    assert rows[0].meta["item"] == "생산자제품 재고지수(계절조정)"


def test_kosis_error_dict_degrades(tmp_path, monkeypatch):
    from sector.collectors import kosis
    from app.settings import settings
    monkeypatch.setattr(settings, "kosis_api_key", "test-kosis-key")

    def handler(request):
        return httpx.Response(200, json={"err": "20", "errMsg": "필수요청변수 누락"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(kosis.collect(SectorStore(tmp_path), client=client))
    assert r.status == "degraded" and "err" in r.detail


# ─── ecos ─────────────────────────────────────────────────────────────────────

def test_ecos_missing_key_no_http(tmp_path, monkeypatch):
    from sector.collectors import ecos
    from app.settings import settings
    monkeypatch.setattr(settings, "ecos_api_key", "")
    r = asyncio.run(ecos.collect(SectorStore(tmp_path), client=_trap_client()))
    assert r.status == "missing_key" and "ecos_api_key" in r.detail


def test_ecos_happy_path(tmp_path, monkeypatch):
    from sector.collectors import ecos
    from app.settings import settings
    monkeypatch.setattr(settings, "ecos_api_key", "test-ecos-key")
    payload = {"StatisticSearch": {"list_total_count": 2, "row": [
        {"TIME": "202605", "DATA_VALUE": "88.5", "ITEM_NAME1": "D램"},
        {"TIME": "202605", "DATA_VALUE": "10.0", "ITEM_NAME1": "자동차"},
    ]}}

    def handler(request):
        assert "/StatisticSearch/test-ecos-key/json/kr/1/100/402Y014/M/" in request.url.path
        return httpx.Response(200, json=payload)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(ecos.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok"
    rows = store.read_metric("kr_dram_export_price_index")
    assert len(rows) == 1
    assert rows[0].ts == "2026-05" and rows[0].value == 88.5
    assert rows[0].meta["item"] == "D램"


def test_ecos_result_error_degrades(tmp_path, monkeypatch):
    from sector.collectors import ecos
    from app.settings import settings
    monkeypatch.setattr(settings, "ecos_api_key", "test-ecos-key")

    def handler(request):
        return httpx.Response(200, json={"RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키 오류"}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(ecos.collect(SectorStore(tmp_path), client=client))
    assert r.status == "degraded" and "INFO-100" in r.detail


# ─── datalab ──────────────────────────────────────────────────────────────────

def test_datalab_missing_key_no_http(tmp_path, monkeypatch):
    from sector.collectors import datalab
    from app.settings import settings
    monkeypatch.setattr(settings, "naver_client_id", "")
    monkeypatch.setattr(settings, "naver_client_secret", "")
    r = asyncio.run(datalab.collect(SectorStore(tmp_path), client=_trap_client()))
    assert r.status == "missing_key" and "naver_client_id" in r.detail


def test_datalab_happy_path(tmp_path, monkeypatch):
    from sector.collectors import datalab
    from app.settings import settings
    monkeypatch.setattr(settings, "naver_client_id", "test-id")
    monkeypatch.setattr(settings, "naver_client_secret", "test-secret")
    payload = {"startDate": "2026-04-07", "endDate": "2026-07-06", "timeUnit": "week", "results": [
        {"title": "chatgpt", "keywords": ["챗지피티", "ChatGPT"],
         "data": [{"period": "2026-06-01", "ratio": 100.0}, {"period": "2026-06-08", "ratio": 88.1}]},
        {"title": "claude", "keywords": ["클로드 AI", "Claude"],
         "data": [{"period": "2026-06-01", "ratio": 20.5}]},
    ]}

    def handler(request):
        assert request.method == "POST"
        assert request.headers["X-Naver-Client-Id"] == "test-id"
        assert request.headers["X-Naver-Client-Secret"] == "test-secret"
        return httpx.Response(200, json=payload)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(datalab.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok"
    rows = store.read_metric("search_interest_kr")
    assert len(rows) == 3
    by_key = {(row.meta["app"], row.ts): row.value for row in rows}
    assert by_key[("chatgpt", "2026-06-01")] == 100.0
    assert by_key[("chatgpt", "2026-06-08")] == 88.1
    assert by_key[("claude", "2026-06-01")] == 20.5


# ─── yahoo_metrics ────────────────────────────────────────────────────────────

def test_yahoo_metrics_ok_and_error_rows(tmp_path, monkeypatch):
    import datetime
    from sector.collectors import yahoo_metrics as ym

    async def fake_quote(tokens, client=None):
        assert "005930.KS" in tokens and "NVDA" in tokens
        return [
            {"token": "005930.KS", "symbol": "005930.KS", "cur": "KRW",
             "last": 61000.0, "day_pct": 1.5, "as_of": "2026-07-06"},
            {"token": "NVDA", "error": "시세 없음 (NVDA)"},
        ]
    monkeypatch.setattr(ym, "quote", fake_quote)
    store = SectorStore(tmp_path)
    r = asyncio.run(ym.collect(store))
    store.append_observations(r.observations)
    assert r.status == "ok"
    assert "errors" in r.detail and "NVDA" in r.detail
    rows = store.read_metric("stock_price")
    assert len(rows) == 1
    o = rows[0]
    assert o.ts == datetime.date.today().isoformat()
    assert o.value == 61000.0
    assert o.meta["token"] == "005930.KS" and o.meta["day_pct"] == 1.5


def test_yahoo_metrics_all_errors_degrades(tmp_path, monkeypatch):
    from sector.collectors import yahoo_metrics as ym

    async def fake_quote(tokens, client=None):
        return [{"token": t, "error": "시세 없음"} for t in tokens]
    monkeypatch.setattr(ym, "quote", fake_quote)
    r = asyncio.run(ym.collect(SectorStore(tmp_path)))
    assert r.status == "degraded" and not r.observations


# ─── stanford_dam ─────────────────────────────────────────────────────────────

_DAM_CSV = (
    "date,category,series,metric,value,unit,source,n_samples,representative,notes\n"
    "2023-06-01,DRAM,Modern DRAM Series,usd_per_gb,2.5,USD/GB,src1,10,chip1,\"\"\n"
    "2024-01-01,NAND,NAND Flash Series,usd_per_gb,0.08,USD/GB,src2,5,chip2,\"\"\n"
    "2023-03-01,DRAM,Bad Value Series,usd_per_gb,not_a_number,USD/GB,src3,1,chip3,\"\"\n"
    "2022-12-01,DRAM,Old Series,usd_per_gb,3.5,USD/GB,src4,3,chip4,\"\"\n"
)


def test_stanford_dam_fixture_csv(tmp_path):
    """픽스처 CSV: 2행 유효 + 1행 값깨짐 + 1행 2022년 → 관측 2건·ts 변환·meta 검증."""
    from sector.collectors import stanford_dam as dam

    def handler(request):
        assert "dam.stanford.edu" in request.url.host
        return httpx.Response(200, text=_DAM_CSV)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(dam.collect(store, client=client))
    store.append_observations(r.observations)
    assert r.status == "ok"
    assert len(r.observations) == 2
    rows = store.read_metric("memory_price_usd_per_gb")
    by_ts = {o.ts: o for o in rows}
    # DRAM row: ts "2023-06"
    assert "2023-06" in by_ts
    dram_obs = by_ts["2023-06"]
    assert dram_obs.value == 2.5
    assert dram_obs.unit == "USD/GB"
    assert dram_obs.meta["item"] == "DRAM|Modern DRAM Series"
    assert dram_obs.meta["category"] == "DRAM"
    # NAND row: ts "2024-01"
    assert "2024-01" in by_ts
    nand_obs = by_ts["2024-01"]
    assert nand_obs.meta["category"] == "NAND"
    # 2022 row filtered, broken value skipped
    assert "2022-12" not in by_ts


def test_stanford_dam_http_500_degrades(tmp_path):
    """HTTP 500 → status=degraded, 관측 없음."""
    from sector.collectors import stanford_dam as dam

    def handler(request):
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = asyncio.run(dam.collect(SectorStore(tmp_path), client=client))
    assert r.status == "degraded"
    assert not r.observations


# ─── earnings_cal ─────────────────────────────────────────────────────────────

def test_earnings_cal_filters_watchlist_and_isolates_days(tmp_path):
    from sector.collectors import earnings_cal
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)                      # 하루 실패 격리 (날짜 무관)
        return httpx.Response(200, json={"data": {"rows": [
            {"symbol": "NVDA", "name": "NVIDIA Corp", "time": "time-after-hours"},
            {"symbol": "ZZZZ", "name": "무관 회사", "time": ""},
        ]}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(earnings_cal.collect(store, client=client))
    store.append_observations(r.observations)
    rows = [o for o in store.read_metric("earnings_calendar", last_n=100)
            if o.meta.get("provider") == "nasdaq"]                 # 국내 예상(rule)은 별도
    assert rows and all(o.meta["item"] == "NVDA" for o in rows)   # 감시 종목만
    assert r.status == "degraded" and "day_fail" in r.detail       # 실패일 기록


# ─── capex ────────────────────────────────────────────────────────────────────

def test_capex_collects_quarters_abs_values(tmp_path):
    from sector.collectors import capex
    payload = {"timeseries": {"result": [{"quarterlyCapitalExpenditure": [
        {"asOfDate": "2026-03-31", "reportedValue": {"raw": -30.9e9}},
        {"asOfDate": "2025-12-31", "reportedValue": {"raw": -29.9e9}}, None]}]}}
    def handler(request):
        assert "quarterlyCapitalExpenditure" in str(request.url)
        return httpx.Response(200, json=payload)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(capex.collect(store, client=client))
    store.append_observations(r.observations)
    rows = store.read_metric("hyperscaler_capex", last_n=50)
    assert rows and all(o.value > 0 for o in rows)          # 절대값
    assert {o.meta["token"] for o in rows} == {"MSFT", "GOOGL", "AMZN", "META"}
    assert any(o.ts == "2026-03" and abs(o.value - 30.9) < 0.01 for o in rows)


# ─── earnings_cal — 국내 실적일 관례 기반 예상 ────────────────────────────────

def test_kr_earnings_estimates_july_window():
    """7/1 기준: 삼성 잠정(7월 첫 주)·하이닉스 콜(7월 하순)·삼성 확정(7월 하순)이 21일 창에 잡힌다."""
    from sector.collectors.earnings_cal import kr_earnings_estimates
    obs = kr_earnings_estimates(dt.date(2026, 7, 1), days_ahead=30)
    by = {(o.meta["item"], o.meta["event"]): o for o in obs}
    assert ("삼성전자", "잠정실적") in by
    assert ("SK하이닉스", "실적발표·콜") in by
    assert ("삼성전자", "확정실적·콜") in by
    for o in obs:
        assert o.meta["kind"] == "est" and o.meta["provider"] == "rule"
        assert o.metric == "earnings_calendar"
        d = dt.date.fromisoformat(o.ts)
        assert d.weekday() < 5                              # 주말 아님
        assert dt.date(2026, 7, 1) <= d <= dt.date(2026, 7, 31)


def test_kr_earnings_estimates_excludes_past_and_far():
    """7/8 기준: 이미 지난 삼성 잠정(7월 초)은 안 만들고, 21일 밖(10월)은 없다."""
    from sector.collectors.earnings_cal import kr_earnings_estimates
    obs = kr_earnings_estimates(dt.date(2026, 7, 8), days_ahead=21)
    events = {(o.meta["item"], o.meta["event"]) for o in obs}
    assert ("삼성전자", "잠정실적") not in events            # 7/7쯤 — 과거
    assert ("SK하이닉스", "실적발표·콜") in events           # 7월 하순
    for o in obs:
        assert dt.date.fromisoformat(o.ts) >= dt.date(2026, 7, 8)


def test_kr_earnings_estimates_year_boundary():
    """12/29 기준: 해를 넘겨 1월 초 삼성 잠정이 잡힌다."""
    from sector.collectors.earnings_cal import kr_earnings_estimates
    obs = kr_earnings_estimates(dt.date(2025, 12, 29), days_ahead=21)
    sam = [o for o in obs if o.meta["event"] == "잠정실적"]
    assert sam and sam[0].ts.startswith("2026-01")


def test_kr_earnings_estimates_quiet_window_empty():
    """5/20 기준: 21일 창(~6/10)에 국내 실적 이벤트 없음."""
    from sector.collectors.earnings_cal import kr_earnings_estimates
    assert kr_earnings_estimates(dt.date(2026, 5, 20), days_ahead=21) == []


def test_earnings_cal_collect_includes_kr_estimates(tmp_path, monkeypatch):
    """collect()가 나스닥 실패와 무관하게 국내 예상 이벤트를 함께 방출한다."""
    from sector.collectors import earnings_cal
    monkeypatch.setattr(earnings_cal._dt, "date",
                        type("D", (dt.date,), {"today": staticmethod(lambda: dt.date(2026, 7, 8))}))
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    store = SectorStore(tmp_path)
    r = asyncio.run(earnings_cal.collect(store, client=client))
    store.append_observations(r.observations)
    rows = store.read_metric("earnings_calendar", last_n=100)
    assert any(o.meta.get("kind") == "est" for o in rows)


# ─── supply — 메모리 3사 capex + 장비 4사 매출 ───────────────────────────────

def test_supply_collects_memory_capex_and_equip_revenue(tmp_path):
    from sector.collectors import supply
    def payload(kind, a, b):
        return {"timeseries": {"result": [{kind: [
            {"asOfDate": "2026-03-31", "reportedValue": {"raw": a}},
            {"asOfDate": "2025-12-31", "reportedValue": {"raw": b}}, None]}]}}
    def handler(request):
        u = str(request.url)
        if "quarterlyCapitalExpenditure" in u:
            return httpx.Response(200, json=payload("quarterlyCapitalExpenditure", -12.5e12, -11.0e12))
        assert "quarterlyTotalRevenue" in u
        return httpx.Response(200, json=payload("quarterlyTotalRevenue", 9.2e9, 8.5e9))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(supply.collect(store, client=client))
    store.append_observations(r.observations)
    cap = store.read_metric("memory_capex", last_n=50)
    eq = store.read_metric("equip_revenue", last_n=50)
    assert {o.meta["token"] for o in cap} == {"005930.KS", "000660.KS", "MU"}
    assert {o.meta["token"] for o in eq} == {"ASML", "AMAT", "LRCX", "KLAC"}
    assert all(o.value > 0 for o in cap + eq)               # 절대값
    assert r.status == "ok"


def test_ai_chips_collects_quarterly_revenue(tmp_path):
    from sector.collectors import ai_chips
    payload = {"timeseries": {"result": [{"quarterlyTotalRevenue": [
        {"asOfDate": "2026-03-31", "reportedValue": {"raw": 44.1e9}},
        {"asOfDate": "2025-12-31", "reportedValue": {"raw": 39.3e9}}]}]}}
    def handler(request):
        assert "quarterlyTotalRevenue" in str(request.url)
        return httpx.Response(200, json=payload)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = SectorStore(tmp_path)
    r = asyncio.run(ai_chips.collect(store, client=client))
    store.append_observations(r.observations)
    rows = store.read_metric("ai_chip_revenue", last_n=50)
    assert {o.meta["token"] for o in rows} == {"NVDA", "AMD", "AVGO"}
    assert r.status == "ok" and all(o.value > 0 for o in rows)
