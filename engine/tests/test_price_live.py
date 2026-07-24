"""야후 시세 + 매크로 라이브 스모크 (네트워크 필요).

    engine/.venv/bin/python -m pytest engine/tests/test_price_live.py -v -s
"""

import asyncio
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.price.macro import collect_macro  # noqa: E402
from tools.price.yahoo import daily_history, quote, resolve_symbols  # noqa: E402


def test_resolve_symbols():
    assert resolve_symbols("005930") == ["005930.KS", "005930.KQ"]
    assert resolve_symbols("AAPL") == ["AAPL"]
    assert resolve_symbols("6981.T") == ["6981.T"]
    # 한글명 → universe 매칭
    assert resolve_symbols("삼성전자") == ["005930.KS", "005930.KQ"]


def test_quote_korean_with_return():
    rows = asyncio.run(quote(["삼성전자"], since="2026-01-02"))
    r = rows[0]
    assert "error" not in r, r
    assert r["symbol"] == "005930.KS"
    assert r["last"] > 0 and "ret_pct" in r and "mult" in r
    print(f"\n삼성전자: {r['last']:,}원 (전일 {r['day_pct']:+.1f}%, YTD {r['ret_pct']:+.1f}% ={r['mult']:.2f}x, as_of {r['as_of']})")


def test_daily_history_contract():
    result = asyncio.run(daily_history("005930", count=5))
    assert "error" not in result, result
    assert result["symbol"] == "005930.KS"
    assert len(result["candles"]) == 5
    assert result["candles"] == sorted(result["candles"], key=lambda row: row["date"])
    assert all(row["close"] > 0 for row in result["candles"])


def test_macro_set():
    macro = asyncio.run(collect_macro())
    assert "KOSPI" in macro and "USD/KRW" in macro
    ok = [k for k, v in macro.items() if "error" not in v]
    assert len(ok) >= 5, f"too many macro failures: {macro}"
    print("\nmacro:")
    for label, v in macro.items():
        if "error" in v:
            print(f"  {label}: ⚠️ {v['error']}")
        else:
            print(f"  {label}: {v['last']:,} ({v['day_pct']:+.2f}%)")
