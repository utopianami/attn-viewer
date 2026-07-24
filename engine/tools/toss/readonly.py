"""토스 WTS 내부 API의 계약 기반 read-only 실행기.

WTS는 공식 공개 API가 아니므로 호출 경계를 코드로 좁힌다. 이 모듈은
`wts-read-only-operations.json`에 명시된 조회 작업만 실행하고, 계좌·주문·개인화
경로와 로그인 우회는 허용하지 않는다. 커뮤니티는 원문을 반환하지 않고 집계만 한다.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote as urlquote

from .client import TossClient

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CATALOG_PATH = (
    _REPO_ROOT / "api-contracts" / "external" / "toss"
    / "wts-read-only-operations.json"
)
_MAX_ARGUMENT_BYTES = 16_384
_GUEST_HEADER_NAMES = {"browser-tab-id", "app-version", "x-xsrf-token"}


class WtsContractError(ValueError):
    """WTS 요청이 검토된 계약 또는 개인정보 경계를 벗어났을 때 발생한다."""


@lru_cache(maxsize=1)
def load_wts_catalog() -> dict[str, Any]:
    raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    if raw.get("schemaVersion") != 1 or not isinstance(raw.get("operations"), list):
        raise WtsContractError("WTS read-only 계약 형식이 올바르지 않습니다")
    return raw


@lru_cache(maxsize=1)
def _operation_map() -> dict[str, dict[str, Any]]:
    return {op["operationId"]: op for op in load_wts_catalog()["operations"]}


def wts_operation_ids(*, exposed_only: bool = True) -> tuple[str, ...]:
    """계약에 있는 WTS 작업 목록. 기본값은 원문 노출 가능한 도구만 반환한다."""
    return tuple(
        op["operationId"]
        for op in load_wts_catalog()["operations"]
        if not exposed_only or op.get("exposure") == "tool"
    )


def _guest_headers() -> dict[str, str]:
    try:
        from app.settings import settings
        encoded = settings.toss_wts_guest_headers_json
    except Exception:
        encoded = ""
    encoded = os.environ.get("TOSS_WTS_GUEST_HEADERS_JSON") or encoded
    if not encoded:
        return {}
    try:
        raw = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise WtsContractError("TOSS_WTS_GUEST_HEADERS_JSON이 유효한 JSON이 아닙니다") from exc
    if not isinstance(raw, dict):
        raise WtsContractError("TOSS_WTS_GUEST_HEADERS_JSON은 객체여야 합니다")
    normalized = {str(k).lower(): str(v) for k, v in raw.items() if v is not None}
    forbidden = set(normalized) - _GUEST_HEADER_NAMES
    if forbidden:
        raise WtsContractError(
            "게스트 설정에는 공개 WTS 헤더만 허용합니다: "
            f"{sorted(_GUEST_HEADER_NAMES)} (거부: {sorted(forbidden)})"
        )
    return normalized


def _checked_dict(value: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise WtsContractError(f"{label}는 객체여야 합니다")
    try:
        size = len(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise WtsContractError(f"{label}는 JSON 값만 포함해야 합니다") from exc
    if size > _MAX_ARGUMENT_BYTES:
        raise WtsContractError(f"{label}가 너무 큽니다 ({size} bytes)")
    return dict(value)


def _validate_keys(
    values: dict[str, Any],
    *,
    allowed: list[str],
    required: list[str],
    label: str,
) -> None:
    extra = set(values) - set(allowed)
    missing = [name for name in required if values.get(name) is None]
    if extra:
        raise WtsContractError(f"{label}에 계약 외 필드가 있습니다: {sorted(extra)}")
    if missing:
        raise WtsContractError(f"{label} 필수 필드 누락: {missing}")


def _prepare_wts_request(
    operation_id: str,
    *,
    path_params: dict[str, Any] | None,
    query: dict[str, Any] | None,
    body: dict[str, Any] | None,
    allow_aggregate: bool,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    op = _operation_map().get(operation_id)
    if op is None:
        raise WtsContractError(f"허용되지 않은 WTS operationId: {operation_id}")
    if op.get("exposure") != "tool" and not (
        allow_aggregate and op.get("exposure") == "aggregate_only"
    ):
        raise WtsContractError(f"{operation_id} 응답은 원문 도구로 노출할 수 없습니다")

    path_values = _checked_dict(path_params, "path_params")
    query_values = _checked_dict(query, "query")
    body_values = _checked_dict(body, "body")
    allowed_path = op.get("requiredPathParams", [])
    _validate_keys(
        path_values,
        allowed=allowed_path,
        required=allowed_path,
        label="path_params",
    )
    _validate_keys(
        query_values,
        allowed=op.get("allowedQueryParams", []),
        required=op.get("requiredQueryParams", []),
        label="query",
    )
    _validate_keys(
        body_values,
        allowed=op.get("allowedBodyFields", []),
        required=op.get("requiredBodyFields", []),
        label="body",
    )
    if op["method"] == "GET" and body_values:
        raise WtsContractError("GET 작업에는 body를 보낼 수 없습니다")

    path = op["path"]
    for name, value in path_values.items():
        text = str(value)
        if not text or len(text) > 160 or any(ord(ch) < 32 for ch in text):
            raise WtsContractError(f"안전하지 않은 경로 값: {name}")
        path = path.replace("{" + name + "}", urlquote(text, safe=""))
    if "{" in path or "}" in path:
        raise WtsContractError("경로 파라미터가 완전히 치환되지 않았습니다")

    # 대량수집 오용 방지. 실제 계약의 가장 큰 차트 count는 300이다.
    for values in (query_values, body_values):
        for key in ("count", "size"):
            if key not in values:
                continue
            try:
                number = int(values[key])
            except (TypeError, ValueError) as exc:
                raise WtsContractError(f"{key}는 정수여야 합니다") from exc
            if not 1 <= number <= 300:
                raise WtsContractError(f"{key}는 1~300 범위여야 합니다")
    product_codes = body_values.get("productCodes")
    if product_codes is not None:
        if not isinstance(product_codes, list) or not all(
            isinstance(code, str) and code for code in product_codes
        ):
            raise WtsContractError("productCodes는 비어 있지 않은 문자열 배열이어야 합니다")
        if len(product_codes) > 200:
            raise WtsContractError("productCodes는 최대 200개입니다")
    return op, path, query_values, body_values


async def _execute_wts_operation(
    operation_id: str,
    *,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    client: TossClient | None = None,
    allow_aggregate: bool = False,
) -> Any:
    op, path, checked_query, checked_body = _prepare_wts_request(
        operation_id,
        path_params=path_params,
        query=query,
        body=body,
        allow_aggregate=allow_aggregate,
    )
    catalog = load_wts_catalog()
    base_url = catalog["hosts"][op["host"]]
    headers: dict[str, str] = {}
    if op.get("auth") == "guest":
        headers = _guest_headers()
        if not headers:
            raise WtsContractError(
                f"{operation_id}은 공개 게스트 헤더 설정이 필요합니다 "
                "(로그인 쿠키·Authorization은 허용하지 않음)"
            )
    if client is not None:
        if client.base_url != base_url:
            raise WtsContractError(
                f"{operation_id} 호스트는 {base_url}인데 다른 TossClient가 전달됐습니다"
            )
        return await client.request_json(
            op["method"], path, params=checked_query or None, json=checked_body or None
        )
    async with TossClient(base_url=base_url, headers=headers) as owned:
        return await owned.request_json(
            op["method"], path, params=checked_query or None, json=checked_body or None
        )


async def execute_wts_operation(
    operation_id: str,
    *,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    client: TossClient | None = None,
) -> Any:
    """계약상 ``exposure=tool``인 WTS 작업 하나를 실행한다."""
    return await _execute_wts_operation(
        operation_id,
        path_params=path_params,
        query=query,
        body=body,
        client=client,
        allow_aggregate=False,
    )


async def collect_market_snapshot(
    *,
    ranking_size: int = 100,
    event_from: str | None = None,
    event_to: str | None = None,
) -> dict[str, Any]:
    """랭킹·지표·환율·거래정보·경제일정을 한 시점에 수집한다."""
    requests = {
        "ranking": execute_wts_operation(
            "getRealtimeRanking", query={"size": min(max(ranking_size, 1), 100)}
        ),
        "indicators": execute_wts_operation("getMarketIndicators"),
        "exchange_rates": execute_wts_operation("getExchangeRates"),
        "trading_info": execute_wts_operation("getTradingInfo"),
        "economic_events": execute_wts_operation(
            "getEconomicEvents",
            query={k: v for k, v in {
                "from": event_from, "to": event_to
            }.items() if v},
        ),
    }
    results = await asyncio.gather(*requests.values(), return_exceptions=True)
    payload: dict[str, Any] = {
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "contract": "wts-read-only-operations/v1",
        "status": "ok",
        "data": {},
        "errors": {},
    }
    for name, result in zip(requests, results):
        if isinstance(result, BaseException):
            payload["errors"][name] = str(result)[:300]
        else:
            payload["data"][name] = result
    if payload["errors"]:
        payload["status"] = "degraded" if payload["data"] else "error"
    return payload


def _find_comment_rows(value: Any) -> list[dict[str, Any]]:
    """스키마 변동을 견디되 댓글처럼 보이는 첫 배열만 고른다."""
    if isinstance(value, list):
        dicts = [item for item in value if isinstance(item, dict)]
        if dicts and any(
            {"commentId", "content", "createdAt", "author"} & set(item)
            for item in dicts
        ):
            return dicts
        for item in value:
            found = _find_comment_rows(item)
            if found:
                return found
    elif isinstance(value, dict):
        for key in ("comments", "body", "content", "items", "data", "result"):
            if key in value:
                found = _find_comment_rows(value[key])
                if found:
                    return found
        for item in value.values():
            found = _find_comment_rows(item)
            if found:
                return found
    return []


def _nested_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    for key in ("author", "user", "profile", "writer"):
        child = row.get(key)
        if isinstance(child, dict):
            for name in names:
                if name in child:
                    return child[name]
    return None


def _author_token(row: dict[str, Any]) -> Any:
    for name in ("userId", "authorId", "profileId", "writerId"):
        if name in row:
            return row[name]
    for key in ("author", "user", "profile", "writer"):
        child = row.get(key)
        if isinstance(child, dict):
            for name in ("userId", "authorId", "profileId", "writerId", "id"):
                if name in child:
                    return child[name]
    return None


async def collect_community_aggregate(
    subject_id: str,
    *,
    sort: str = "RECENT",
    last_comment_id: str | None = None,
) -> dict[str, Any]:
    """댓글 원문·닉네임·프로필을 즉시 폐기하고 비식별 활동량만 반환한다."""
    query = {
        "subjectType": "STOCK",
        "subjectId": subject_id,
        "commentSortType": sort,
    }
    if last_comment_id:
        query["lastCommentId"] = last_comment_id
    raw = await _execute_wts_operation(
        "getCommunityComments", query=query, allow_aggregate=True
    )
    rows = _find_comment_rows(raw)
    author_tokens: set[str] = set()
    like_count = reply_count = holding_count = 0
    timestamps: list[str] = []
    for row in rows:
        author = _author_token(row)
        if author is not None:
            # 토큰은 메모리에서 고유수 계산에만 쓰고 반환·저장하지 않는다.
            author_tokens.add(str(author))
        like_count += int(_nested_value(
            row, "likeCount", "reactionCount", "agreeCount"
        ) or 0)
        reply_count += int(_nested_value(
            row, "replyCount", "childCommentCount"
        ) or 0)
        holding = _nested_value(
            row, "isHolding", "hasStock", "stockOwner", "isStockOwner"
        )
        holding_count += int(bool(holding))
        created = _nested_value(row, "createdAt", "createdDate", "updatedAt")
        if created:
            timestamps.append(str(created))
    return {
        "subject_type": "STOCK",
        "subject_id": subject_id,
        "sort": sort,
        "comment_count": len(rows),
        "unique_author_count": len(author_tokens),
        "like_count": like_count,
        "reply_count": reply_count,
        "holding_badge_count": holding_count,
        "window_start": min(timestamps) if timestamps else None,
        "window_end": max(timestamps) if timestamps else None,
        "evidence_grade": "D",
        "privacy": "aggregate_only; raw text and author identifiers discarded",
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
