"""토스 인베스트 전용 HTTP 클라이언트.

- 무인증, User-Agent만 필요 (docs/toss-api-inventory.md)
- 실측 안정 설정: 요청 간격 30~50ms, 동시 10~20, 429 백오프 2→4→6s
- 프록시 슬롯: 기본 None. 차단 시 NodeMaven 등 표준 http 프록시 URL 주입
  (하네스는 RYZE_TOSS_PROXY를 썼지만 이 호스트는 직접 호출 가능 확인됨 — 2026-07-02)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

INFO_HOST = "https://wts-info-api.tossinvest.com"
CERT_HOST = "https://wts-cert-api.tossinvest.com"
API_HOST = "https://wts-api.tossinvest.com"
USER_AGENT = "Mozilla/5.0"

# 실측 안정치 (longshot-wiki toss-invest.md, 2026-05-04 confirmed)
MAX_CONCURRENCY = 10
MIN_INTERVAL_S = 0.04
BACKOFF_S = (2.0, 4.0, 6.0)
TIMEOUT_S = 15.0


class TossClient:
    """레이트리밋·429 백오프가 내장된 토스 API 클라이언트.

    사용법:
        async with TossClient() as c:
            data = await c.get_json("/api/v2/stock-infos/A005930/overview")
    """

    def __init__(
        self,
        proxy_url: str | None = None,
        timeout_s: float = TIMEOUT_S,
        *,
        base_url: str = INFO_HOST,
        headers: dict[str, str] | None = None,
    ):
        proxy = proxy_url or os.environ.get("TOSS_PROXY_URL") or None
        request_headers = {"User-Agent": USER_AGENT}
        request_headers.update(headers or {})
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=request_headers,
            timeout=timeout_s,
            proxy=proxy,
        )
        self._sem = asyncio.Semaphore(MAX_CONCURRENCY)
        self._pace_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def __aenter__(self) -> "TossClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._client.aclose()

    async def _pace(self) -> None:
        # 전역 최소 간격 — 동시성과 별개로 발사 간격을 벌린다.
        async with self._pace_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait = self._last_request_at + MIN_INTERVAL_S - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = loop.time()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async with self._sem:
            for attempt, backoff in enumerate((*BACKOFF_S, None)):
                await self._pace()
                resp = await self._client.request(method, path, **kwargs)
                if resp.status_code != 429:
                    resp.raise_for_status()
                    return resp
                if backoff is None:
                    resp.raise_for_status()  # 백오프 소진 → 429 그대로 raise
                await asyncio.sleep(backoff)
        raise AssertionError("unreachable")

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = await self._request("GET", path, params=params)
        return resp.json()

    async def post_json(self, path: str, json: dict[str, Any]) -> Any:
        resp = await self._request("POST", path, json=json)
        return resp.json()

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """계약 실행기용 공용 진입점.

        임의 URL 허용 여부는 상위 WTS 계약 실행기가 결정하고, 이 클라이언트는
        선택된 호스트 안에서 레이트리밋·백오프만 담당한다.
        """
        resp = await self._request(method.upper(), path, params=params, json=json)
        return resp.json()
