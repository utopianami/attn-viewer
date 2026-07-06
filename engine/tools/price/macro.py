"""매크로 지표 세트 — PRICE·MACRO 브랜치의 global scope 수집 (질문당 1회).

어떤 유닛이든 같은 시장 배경 위에서 답하도록 공통 컨텍스트를 결정적으로 수집한다.
전부 야후 심볼 (한국 종목과 같은 chart API — 코드 재사용). 세트는 settings 이관 대상.
"""

from __future__ import annotations

from typing import Any

import httpx

from .yahoo import _UA, quote

# 기본 매크로 세트 (docs 계획 §1.1). label → 야후 심볼.
DEFAULT_MACRO_SET: dict[str, str] = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
    "USD/KRW": "KRW=X",
    "US10Y": "^TNX",     # 미 10년물 금리
    "WTI": "CL=F",       # WTI 유가
    "VIX": "^VIX",
}


async def collect_macro(
    macro_set: dict[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """매크로 세트의 현재값 + 전일대비 %. 개별 지표 실패는 격리(never-raise).

    반환: {label: {symbol, last, day_pct, as_of} | {error}}
    """
    macro_set = macro_set or DEFAULT_MACRO_SET
    own = client is None
    client = client or httpx.AsyncClient(headers=_UA, timeout=25, verify=False)
    try:
        symbols = list(macro_set.values())
        rows = await quote(symbols, client=client)
        by_symbol = {r.get("symbol", r.get("token")): r for r in rows}
        out: dict[str, Any] = {}
        for label, sym in macro_set.items():
            r = by_symbol.get(sym) or {}
            if "error" in r or not r:
                out[label] = {"symbol": sym, "error": r.get("error", "no data")}
            else:
                out[label] = {
                    "symbol": sym,
                    "last": r["last"],
                    "day_pct": round(r["day_pct"], 2),
                    "as_of": r.get("as_of"),
                }
        return out
    finally:
        if own:
            await client.aclose()
