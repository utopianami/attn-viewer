"""토스 차트 수집 (PRICE·MACRO 브랜치의 한국 종목 실시간 폴백 후보).

일봉/분봉. longshot-wiki toss-invest.md의 페이지네이션 규칙 이식:
캔들은 최신→과거 정렬, nextDateTime 커서로 과거로 페이지네이션.
"""

from __future__ import annotations

import urllib.parse

from .client import TossClient
from .models import Candle

CHART_BASE = "/api/v1/c-chart/kr-s"


def _norm_pref(code: str) -> str:
    c = code.strip().upper()
    return c if c.startswith("A") else f"A{c}"


async def daily_candles(
    code: str, count: int = 300, client: TossClient | None = None
) -> list[Candle]:
    """일봉 최근 count개 (max 300)."""
    own = client is None
    client = client or TossClient()
    try:
        data = await client.get_json(
            f"{CHART_BASE}/{_norm_pref(code)}/day:1", params={"count": count}
        )
    finally:
        if own:
            await client.__aexit__()
    raw = (data or {}).get("result", {}).get("candles", []) or []
    return [Candle.model_validate(c) for c in raw]


async def minute_candles(
    code: str,
    from_kst: str,
    count: int = 300,
    client: TossClient | None = None,
) -> tuple[list[Candle], str | None]:
    """1분봉 한 페이지. from_kst 예: '2026-07-02T15:31:00+09:00'.

    반환: (candles, next_cursor). next_cursor를 다음 호출 from_kst에 넣어 과거로 진행.
    """
    own = client is None
    client = client or TossClient()
    try:
        params = {
            "count": count,
            "from": from_kst,
            "useAdjustedRate": "true",
        }
        # from은 이미 인코딩된 ISO — httpx가 재인코딩하지 않도록 쿼리스트링 수동 구성
        qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        data = await client.get_json(f"{CHART_BASE}/{_norm_pref(code)}/min:1?{qs}")
    finally:
        if own:
            await client.__aexit__()
    result = (data or {}).get("result", {})
    candles = [Candle.model_validate(c) for c in result.get("candles", []) or []]
    return candles, result.get("nextDateTime")
