"""주가 시계열 — 대시보드 스파크라인용 (P2 지원, 2026-07-07).

기존 tools.price.yahoo._fetch 재사용. 저장하지 않고 온디맨드 + api.py에서 1시간 캐시
(일봉이라 충분). 종목별 실패 격리 — 죽은 종목은 error 필드로.
"""
from __future__ import annotations

import datetime as _dt

import httpx

from tools.price.yahoo import _UA, _fetch

TICKERS: list[tuple[str, str]] = [
    ("005930.KS", "삼성전자"), ("000660.KS", "SK하이닉스"), ("MU", "마이크론"),
    ("TSM", "TSMC"), ("NVDA", "엔비디아"), ("^SOX", "SOX"),
    ("SKHY", "하이닉스 ADR"),   # 2026-07-10 나스닥 상장 (ADR 10 = 원주 1) — 미국장 시세
]

# 거시 배경 (계획 §1 "M 거시 = 전 구간 배경" — 2026-07-13 미-이란 전쟁 국면에서 구현)
# 상승 = 대체로 주식 역풍 (환율=외인 이탈, 유가=인플레, 금리=할인율, VIX=공포)
MACRO_TICKERS: list[tuple[str, str]] = [
    ("KRW=X", "원달러"), ("BZ=F", "브렌트유"), ("^TNX", "미10년물"), ("^VIX", "VIX"),
]


def adr_premium(series: list[dict], usdkrw: float | None) -> dict | None:
    """SKHY ADR×10×환율 vs 원주(000660.KS) 괴리율.

    양 시장 마감 시차가 내재 — 미국이 하루 늦게(또는 먼저) 반영하므로
    asof 날짜를 함께 반환해 화면이 '시차 있음'을 표시할 수 있게 한다.
    """
    if not usdkrw:
        return None
    by = {s.get("token"): s for s in series if not s.get("error")}
    adr, local = by.get("SKHY"), by.get("000660.KS")
    if not (adr and adr.get("last") and local and local.get("last")):
        return None
    equiv = adr["last"] * 10 * usdkrw
    return {"premium_pct": round((equiv / local["last"] - 1) * 100, 1),
            "adr_usd": adr["last"], "local_krw": local["last"],
            "usdkrw": round(usdkrw, 1),
            "adr_asof": adr["points"][-1][0] if adr.get("points") else "",
            "local_asof": local["points"][-1][0] if local.get("points") else ""}


async def price_series(days: int = 90, client: httpx.AsyncClient | None = None) -> dict:
    now = _dt.datetime.now()
    p1 = int((now - _dt.timedelta(days=days)).timestamp())
    p2 = int(now.timestamp()) + 86400
    own = client is None
    client = client or httpx.AsyncClient(headers=_UA, timeout=25, verify=False)
    async def fetch_one(sym: str, name: str) -> dict:
        try:
            pairs, _meta = await _fetch(client, sym, p1, p2)
        except Exception as exc:  # noqa: BLE001 — 종목 격리
            return {"token": sym, "name": name, "error": str(exc)[:120]}
        points = [[_dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d"), round(c, 2)]
                  for t, c in pairs]
        last = points[-1][1] if points else None
        prev = points[-2][1] if len(points) > 1 else None
        day_pct = round((last / prev - 1) * 100, 2) if last and prev else None
        return {"token": sym, "name": name, "points": points,
                "last": last, "day_pct": day_pct}

    try:
        series = [await fetch_one(sym, name) for sym, name in TICKERS]
        macro = [await fetch_one(sym, name) for sym, name in MACRO_TICKERS]
        fx = next((m.get("last") for m in macro if m.get("token") == "KRW=X"), None)
        return {"series": series, "macro": macro,
                "as_of": now.isoformat(timespec="minutes"),
                "adr_premium": adr_premium(series, fx)}
    finally:
        if own:
            await client.aclose()
