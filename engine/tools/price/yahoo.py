"""야후 파이낸스 시세 — 하네스 quote.py 로직을 async httpx로 이식.

철칙: 웹 검색 요약으로 시세를 대체하지 않는다 (YTD/52주/목표가 혼동). 일별 종가 시계열만.
한국 종목명/6자리코드 → universe_kospi.json으로 .KS/.KQ 해석.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

import httpx

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_CRUMB = "https://query1.finance.yahoo.com/v1/test/getcrumb"
_SUMMARY = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
_UA = {"User-Agent": "Mozilla/5.0"}
_UNIVERSE_PATH = Path(__file__).with_name("universe_kospi.json")

_universe: list[dict] | None = None


def _load_universe() -> list[dict]:
    global _universe
    if _universe is None:
        try:
            _universe = json.loads(_UNIVERSE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _universe = []
    return _universe


def _name_to_code(name: str, uni: list[dict]) -> str | None:
    for it in uni:
        if it.get("name") == name:
            return it.get("code")
    cand = [it for it in uni if name in it.get("name", "")]
    return cand[0]["code"] if len(cand) == 1 else None


def resolve_symbols(token: str) -> list[str]:
    """토큰 하나 → 시도할 야후 심볼 목록(.KS→.KQ 순). quote.py candidates() 이식."""
    t = token.strip()
    if any(ch in t for ch in ".^="):  # 이미 야후 심볼 (6981.T, ^KS11, KRW=X, CL=F)
        return [t]
    if t.isascii() and t.isalpha() and t.isupper():  # 미국 티커 (AAPL)
        return [t]
    if t.isdigit() and len(t) == 6:  # 한국 코드
        return [f"{t}.KS", f"{t}.KQ"]
    code = _name_to_code(t, _load_universe())  # 한글명
    if code:
        return [f"{code}.KS", f"{code}.KQ"]
    return []


async def _fetch(client: httpx.AsyncClient, symbol: str, p1: int, p2: int):
    r = await client.get(
        _CHART.format(symbol=symbol),
        params={"period1": p1, "period2": p2, "interval": "1d"},
    )
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    cl = res["indicators"]["quote"][0]["close"]
    pairs = [(t, c) for t, c in zip(ts, cl) if c is not None]
    return pairs, res.get("meta", {})


async def quote(
    tokens: list[str],
    since: str | None = None,
    until: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """여러 종목의 시세/수익률/배수. since 있으면 기준일→현재 수익률·배수 포함.

    반환 각 항목: {token, symbol, cur, base, last, day_pct, [ret_pct, mult], as_of}
    또는 해석 실패 시 {token, error}. never-raise (per-token 에러 격리).
    """
    now = _dt.datetime.now()
    until_dt = _dt.datetime.strptime(until, "%Y-%m-%d") if until else now
    since_dt = (
        _dt.datetime.strptime(since, "%Y-%m-%d")
        if since
        else until_dt - _dt.timedelta(days=10)
    )
    p1, p2 = int(since_dt.timestamp()), int(until_dt.timestamp()) + 86400

    own = client is None
    client = client or httpx.AsyncClient(headers=_UA, timeout=25, verify=False)
    try:
        out: list[dict[str, Any]] = []
        for token in tokens:
            cands = resolve_symbols(token)
            if not cands:
                out.append({"token": token, "error": "해석 불가 — 6자리 코드/야후 심볼로 지정"})
                continue
            row: dict[str, Any] | None = None
            last_err = None
            for sym in cands:
                try:
                    pairs, meta = await _fetch(client, sym, p1, p2)
                    if pairs:
                        row = {"token": token, "symbol": sym, "pairs": pairs, "meta": meta}
                        break
                except Exception as e:  # noqa: BLE001
                    last_err = str(e)
            if row is None:
                out.append({"token": token, "error": f"시세 없음 ({','.join(cands)}) {last_err or ''}".strip()})
                continue

            pairs, meta = row.pop("pairs"), row.pop("meta")
            row["cur"] = meta.get("currency", "")
            row["base_t"], row["base"] = pairs[0]
            row["last_t"], row["last"] = pairs[-1]
            prev = pairs[-2][1] if len(pairs) >= 2 else row["base"]
            row["day_pct"] = (row["last"] / prev - 1) * 100 if prev else 0.0
            if since:
                row["ret_pct"] = (row["last"] / row["base"] - 1) * 100 if row["base"] else 0.0
                row["mult"] = row["last"] / row["base"] if row["base"] else 0.0
            row["as_of"] = _dt.datetime.fromtimestamp(row["last_t"]).strftime("%Y-%m-%d")
            out.append(row)
        return out
    finally:
        if own:
            await client.aclose()


async def daily_history(
    token: str,
    *,
    count: int = 30,
    until: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """일별 종가 시계열을 반환하는 계약형 Yahoo 차트 도구.

    반환은 오래된 날짜부터 정렬된 ``candles``와 실제 해석된 ``symbol``을 포함한다.
    종목 하나의 실패는 ``error`` 필드로 반환하고 예외를 바깥으로 전파하지 않는다.
    """
    count = min(max(int(count), 2), 300)
    now = _dt.datetime.now()
    until_dt = _dt.datetime.strptime(until, "%Y-%m-%d") if until else now
    since_dt = until_dt - _dt.timedelta(days=max(14, count * 3))
    p1, p2 = int(since_dt.timestamp()), int(until_dt.timestamp()) + 86400

    own = client is None
    client = client or httpx.AsyncClient(headers=_UA, timeout=25, verify=False)
    try:
        candidates = resolve_symbols(token)
        if not candidates:
            return {"token": token, "error": "해석 불가 — 6자리 코드/야후 심볼로 지정"}
        last_error = ""
        for symbol in candidates:
            try:
                pairs, meta = await _fetch(client, symbol, p1, p2)
                if not pairs:
                    continue
                selected = pairs[-count:]
                return {
                    "token": token,
                    "symbol": symbol,
                    "currency": meta.get("currency", ""),
                    "candles": [
                        {
                            "date": _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                            "close": float(close),
                        }
                        for ts, close in selected
                    ],
                }
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return {
            "token": token,
            "error": f"시세 없음 ({','.join(candidates)}) {last_error}".strip(),
        }
    finally:
        if own:
            await client.aclose()


async def fundamentals(
    symbols: list[str],
    client: httpx.AsyncClient | None = None,
) -> dict[str, dict[str, Any]]:
    """심볼별 밸류에이션 기초 — {symbol: {per, eps, cur}} (TTM 기준).

    chart API에는 PER/EPS가 없어 quoteSummary(crumb 인증, yfinance 방식) 사용.
    해외 종목 PER 소스 부재로 "PER 비교" 질문이 계산 불가였던 갭 해소 (2026-07-09 woojin 피드백).
    never-raise — crumb 실패 시 빈 dict, 심볼 단위 실패는 생략.
    """
    if not symbols:
        return {}
    own = client is None
    client = client or httpx.AsyncClient(headers=_UA, timeout=25, verify=False)
    out: dict[str, dict[str, Any]] = {}
    try:
        try:
            # fc.yahoo.com은 404가 정상 — 세션 쿠키 수집이 목적 (raise 금지)
            await client.get("https://fc.yahoo.com")
            crumb = (await client.get(_CRUMB)).text.strip()
        except Exception:
            return {}
        if not crumb or "<" in crumb:  # HTML 에러 페이지 방어
            return {}

        async def _one(sym: str) -> None:
            try:
                r = await client.get(
                    _SUMMARY.format(symbol=sym),
                    params={"modules": "summaryDetail,defaultKeyStatistics", "crumb": crumb},
                )
                r.raise_for_status()
                res = r.json()["quoteSummary"]["result"][0]
                sd = res.get("summaryDetail") or {}
                ks = res.get("defaultKeyStatistics") or {}
                per = (sd.get("trailingPE") or {}).get("raw")
                eps = (ks.get("trailingEps") or {}).get("raw")
                if per is not None or eps is not None:
                    out[sym] = {"per": per, "eps": eps, "cur": sd.get("currency") or ""}
            except Exception:
                return  # 심볼 단위 격리

        import asyncio as _asyncio
        await _asyncio.gather(*(_one(s) for s in symbols))
        return out
    finally:
        if own:
            await client.aclose()
