"""토스증권 공식 Open API의 계약 기반 read-only 실행기.

`api-contracts/external/toss/openapi.json` 전체를 그대로 노출하지 않는다.
별도 검토된 `read-only-operations.json`의 14개 GET operationId만 실행하며,
경로·쿼리 필드는 고정한 OpenAPI 스냅샷으로 다시 검증한다.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote as urlquote

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT_DIR = _REPO_ROOT / "api-contracts" / "external" / "toss"
_OPENAPI_PATH = _CONTRACT_DIR / "openapi.json"
_ALLOWLIST_PATH = _CONTRACT_DIR / "read-only-operations.json"
_BASE_URL = "https://openapi.tossinvest.com"
_UA = "ryze-qa-engine/1.0"

_openapi: dict[str, Any] | None = None
_allowed: dict[str, dict[str, Any]] | None = None


class TossContractError(ValueError):
    """요청이 고정 계약 또는 안전 allowlist를 벗어났을 때 발생한다."""


def _load_contracts() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    global _openapi, _allowed
    if _openapi is None:
        _openapi = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    if _allowed is None:
        raw = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
        _allowed = {op["operationId"]: op for op in raw["operations"]}
    return _openapi, _allowed


def official_operation_ids() -> tuple[str, ...]:
    """검토된 공식 read-only operationId 목록."""
    _, allowed = _load_contracts()
    return tuple(allowed)


def _resolve_ref(spec: dict[str, Any], obj: dict[str, Any]) -> dict[str, Any]:
    ref = obj.get("$ref")
    if not ref:
        return obj
    if not ref.startswith("#/"):
        raise TossContractError(f"외부 $ref는 지원하지 않습니다: {ref}")
    cur: Any = spec
    for token in ref[2:].split("/"):
        cur = cur[token.replace("~1", "/").replace("~0", "~")]
    return cur


def _operation_contract(operation_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    spec, allowed = _load_contracts()
    gate = allowed.get(operation_id)
    if gate is None:
        raise TossContractError(f"허용되지 않은 공식 Toss operationId: {operation_id}")
    if gate.get("method") != "GET":
        raise TossContractError("공식 Toss allowlist는 GET만 허용합니다")
    path = gate["path"]
    path_item = spec.get("paths", {}).get(path)
    operation = (path_item or {}).get("get")
    if not operation or operation.get("operationId") != operation_id:
        raise TossContractError(f"OpenAPI 스냅샷과 allowlist가 불일치합니다: {operation_id}")
    return spec, operation, path


def _parameters(spec: dict[str, Any], operation: dict[str, Any], path: str) -> list[dict[str, Any]]:
    path_item = spec["paths"][path]
    raw = list(path_item.get("parameters", [])) + list(operation.get("parameters", []))
    return [_resolve_ref(spec, item) for item in raw]


def _schema(spec: dict[str, Any], parameter: dict[str, Any]) -> dict[str, Any]:
    return _resolve_ref(spec, parameter.get("schema") or {})


def _validate_value(name: str, value: Any, schema: dict[str, Any]) -> None:
    if value is None:
        return
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise TossContractError(f"{name}: 허용값은 {enum}입니다")
    typ = schema.get("type")
    if typ == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TossContractError(f"{name}: 정수여야 합니다")
    elif typ == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TossContractError(f"{name}: 숫자여야 합니다")
    elif typ == "boolean" and not isinstance(value, bool):
        raise TossContractError(f"{name}: boolean이어야 합니다")
    elif typ == "string" and not isinstance(value, str):
        raise TossContractError(f"{name}: 문자열이어야 합니다")
    if "minimum" in schema and value < schema["minimum"]:
        raise TossContractError(f"{name}: 최솟값은 {schema['minimum']}입니다")
    if "maximum" in schema and value > schema["maximum"]:
        raise TossContractError(f"{name}: 최댓값은 {schema['maximum']}입니다")
    if isinstance(value, str) and schema.get("pattern") and not re.fullmatch(schema["pattern"], value):
        raise TossContractError(f"{name}: OpenAPI pattern과 맞지 않습니다")


def _prepare_request(
    operation_id: str,
    path_params: dict[str, Any] | None,
    query: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    spec, operation, path = _operation_contract(operation_id)
    path_params = dict(path_params or {})
    query = dict(query or {})
    params = _parameters(spec, operation, path)
    known_path = {p["name"]: p for p in params if p.get("in") == "path"}
    known_query = {p["name"]: p for p in params if p.get("in") == "query"}

    extra_path = set(path_params) - set(known_path)
    extra_query = set(query) - set(known_query)
    if extra_path or extra_query:
        raise TossContractError(
            f"계약에 없는 파라미터: path={sorted(extra_path)}, query={sorted(extra_query)}"
        )
    missing = [
        p["name"]
        for p in params
        if p.get("required")
        and ((p.get("in") == "path" and path_params.get(p["name"]) is None)
             or (p.get("in") == "query" and query.get(p["name"]) is None))
    ]
    if missing:
        raise TossContractError(f"필수 파라미터 누락: {missing}")

    for name, value in path_params.items():
        _validate_value(name, value, _schema(spec, known_path[name]))
        encoded = urlquote(str(value), safe="")
        path = path.replace("{" + name + "}", encoded)
    if "{" in path or "}" in path:
        raise TossContractError("경로 파라미터가 완전히 치환되지 않았습니다")
    for name, value in query.items():
        _validate_value(name, value, _schema(spec, known_query[name]))
    return path, query


class OfficialTossClient:
    """OAuth client-credentials와 토큰 만료 처리를 포함한 공식 API 클라이언트."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        timeout_s: float = 20.0,
    ):
        try:
            from app.settings import settings
            configured_id = settings.toss_client_id
            configured_secret = settings.toss_client_secret
        except Exception:
            configured_id = configured_secret = ""
        self._client_id = client_id or os.environ.get("TOSS_CLIENT_ID") or configured_id
        self._client_secret = (
            client_secret or os.environ.get("TOSS_CLIENT_SECRET") or configured_secret
        )
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL, headers={"User-Agent": _UA}, timeout=timeout_s
        )
        self._token = ""
        self._expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def __aenter__(self) -> "OfficialTossClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._http.aclose()

    async def _access_token(self) -> str:
        if not self._client_id or not self._client_secret:
            raise TossContractError(
                "공식 Toss API 자격증명이 없습니다 "
                "(TOSS_CLIENT_ID, TOSS_CLIENT_SECRET 필요)"
            )
        if self._token and time.monotonic() < self._expires_at - 30:
            return self._token
        async with self._token_lock:
            if self._token and time.monotonic() < self._expires_at - 30:
                return self._token
            response = await self._http.post(
                "/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token")
            if not token:
                raise TossContractError("공식 Toss OAuth 응답에 access_token이 없습니다")
            self._token = str(token)
            self._expires_at = time.monotonic() + float(payload.get("expires_in") or 300)
            return self._token

    async def execute(
        self,
        operation_id: str,
        *,
        path_params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        path, checked_query = _prepare_request(operation_id, path_params, query)
        token = await self._access_token()
        response = await self._http.get(
            path,
            params=checked_query,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


async def execute_official(
    operation_id: str,
    *,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    client: OfficialTossClient | None = None,
) -> Any:
    """공식 allowlist의 operationId 하나를 실행한다."""
    if client is not None:
        return await client.execute(operation_id, path_params=path_params, query=query)
    async with OfficialTossClient() as owned:
        return await owned.execute(operation_id, path_params=path_params, query=query)
