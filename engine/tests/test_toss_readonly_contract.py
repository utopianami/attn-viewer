"""Toss 공식/WTS read-only 계약 실행기의 오프라인 안전 회귀."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.registry import build_default_registry  # noqa: E402
from tools.toss.official import (  # noqa: E402
    TossContractError,
    _prepare_request,
    official_operation_ids,
)
from tools.toss.readonly import (  # noqa: E402
    WtsContractError,
    collect_community_aggregate,
    execute_wts_operation,
    load_wts_catalog,
    wts_operation_ids,
)


class _StubClient:
    base_url = "https://wts-info-api.tossinvest.com"

    def __init__(self):
        self.calls = []

    async def request_json(self, method, path, *, params=None, json=None):
        self.calls.append((method, path, params, json))
        return {"result": {"ok": True}}


def test_wts_catalog_is_explicit_and_account_safe():
    catalog = load_wts_catalog()
    operations = catalog["operations"]
    ids = [operation["operationId"] for operation in operations]
    assert len(ids) == len(set(ids)) >= 40
    assert all(operation["host"] in catalog["hosts"] for operation in operations)
    assert all(operation["method"] in {"GET", "POST"} for operation in operations)
    assert all(
        forbidden not in operation["path"].lower()
        for operation in operations
        for forbidden in ("/orders", "/accounts", "/holdings", "/login/")
    )
    community = next(op for op in operations if op["operationId"] == "getCommunityComments")
    assert community["exposure"] == "aggregate_only"
    assert "getCommunityComments" not in wts_operation_ids()


def test_wts_executor_only_uses_contract_path_and_fields():
    client = _StubClient()
    payload = asyncio.run(execute_wts_operation(
        "getWtsOverview",
        path_params={"productCode": "A005930"},
        client=client,  # type: ignore[arg-type]
    ))
    assert payload["result"]["ok"] is True
    assert client.calls == [
        ("GET", "/api/v2/stock-infos/A005930/overview", None, None)
    ]
    with pytest.raises(WtsContractError):
        asyncio.run(execute_wts_operation("getWtsOverview",
                                          path_params={"productCode": "A005930"},
                                          query={"invented": "x"},
                                          client=client))  # type: ignore[arg-type]
    with pytest.raises(WtsContractError):
        asyncio.run(execute_wts_operation("getCommunityComments"))
    with pytest.raises(WtsContractError):
        asyncio.run(execute_wts_operation("placeOrder"))


def test_guest_header_contract_rejects_login_material(monkeypatch):
    from app.settings import settings
    monkeypatch.setattr(
        settings,
        "toss_wts_guest_headers_json",
        json.dumps({"Authorization": "Bearer account-token"}),
    )
    monkeypatch.delenv("TOSS_WTS_GUEST_HEADERS_JSON", raising=False)
    with pytest.raises(WtsContractError, match="거부"):
        asyncio.run(execute_wts_operation("getServerTime"))


def test_community_tool_discards_raw_text_and_identity(monkeypatch):
    import tools.toss.readonly as module

    async def fake_execute(*args, **kwargs):
        return {"result": {"comments": [
            {
                "commentId": "c1",
                "content": "원문은 반환되면 안 됨",
                "author": {"id": "private-user-1", "nickname": "private-name"},
                "likeCount": 3,
                "replyCount": 2,
                "isHolding": True,
                "createdAt": "2026-07-23T10:00:00+09:00",
            },
            {
                "commentId": "c2",
                "content": "두 번째 원문",
                "author": {"id": "private-user-1"},
                "likeCount": 1,
                "createdAt": "2026-07-23T10:01:00+09:00",
            },
        ]}}

    monkeypatch.setattr(module, "_execute_wts_operation", fake_execute)
    result = asyncio.run(collect_community_aggregate("KR7005930003"))
    assert result["comment_count"] == 2
    assert result["unique_author_count"] == 1
    assert result["like_count"] == 4
    encoded = json.dumps(result, ensure_ascii=False)
    assert "원문" not in encoded
    assert "private-user" not in encoded
    assert "private-name" not in encoded


def test_official_allowlist_matches_openapi_and_validates_parameters():
    assert len(official_operation_ids()) == 14
    path, query = _prepare_request(
        "getRankings",
        {},
        {
            "type": "TOP_GAINERS",
            "marketCountry": "KR",
            "duration": "1w",
            "count": 10,
        },
    )
    assert path == "/api/v1/rankings"
    assert query["count"] == 10
    with pytest.raises(TossContractError):
        _prepare_request("getRankings", {}, {"type": "TOP_GAINERS"})
    with pytest.raises(TossContractError):
        _prepare_request("createOrder", {}, {})


def test_all_reviewed_operations_are_registered():
    registry = build_default_registry()
    assert registry.get("market_sector_momentum") is not None
    assert registry.get("price_yahoo_history") is not None
    assert registry.get("toss_wts_get_kr_daily_candles") is not None
    assert registry.get("toss_official_get_candles") is not None
    assert registry.get("toss_wts_get_community_comments") is None
