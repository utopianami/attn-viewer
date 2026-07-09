"""PRICE 통화 라벨·PER/EPS 승격 오프라인 테스트 (2026-07-09 woojin 피드백 회귀).

버그: typed_fact unit이 KRW 하드코딩 — AAPL 313.39가 "KRW"로 라벨링.
갭: 해외 종목 PER/EPS 소스 부재 — "애플과 같은 PER이면" 질문 계산 불가.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import PlanPacket, TickerCandidate  # noqa: E402
import stages.price_macro as pm  # noqa: E402


async def _fake_quote(tokens, since=None, until=None, client=None):
    return [
        {"token": "005930", "symbol": "005930.KS", "cur": "KRW",
         "last": 276000.0, "base": 270000.0, "day_pct": 1.0, "as_of": "2026-07-09"},
        {"token": "AAPL", "symbol": "AAPL", "cur": "USD",
         "last": 313.39, "base": 310.0, "day_pct": 0.5, "as_of": "2026-07-09"},
        {"token": "NONE", "error": "시세 없음"},
    ]


async def _fake_macro():
    return {}


async def _fake_fundamentals(symbols, client=None):
    assert "AAPL" in symbols and "005930.KS" in symbols
    return {"AAPL": {"per": 37.58, "eps": 8.34, "cur": "USD"}}


def _plan():
    return PlanPacket(
        tier=2, original_question="q", standalone_question="q",
        knowledge_cutoff="2026-07-09",
        tickers=[TickerCandidate(name="삼성전자", code="005930", yahoo_symbol="005930.KS"),
                 TickerCandidate(name="애플", yahoo_symbol="AAPL")],
    )


def test_currency_label_from_quote(monkeypatch):
    """통화는 yahoo 실측값 — USD 종목이 KRW로 라벨링되면 안 된다."""
    monkeypatch.setattr(pm, "quote", _fake_quote)
    monkeypatch.setattr(pm, "collect_macro", _fake_macro)
    monkeypatch.setattr(pm, "fundamentals", _fake_fundamentals)
    packet = asyncio.run(pm.run_price_macro(_plan()))
    units = {f.id: f.unit for f in packet.typed_facts}
    assert units["price:005930"] == "KRW"
    assert units["price:AAPL"] == "USD"


def test_per_eps_promoted(monkeypatch):
    """fundamentals 결과가 PER(배)·EPS(통화) typed_fact로 승격된다."""
    monkeypatch.setattr(pm, "quote", _fake_quote)
    monkeypatch.setattr(pm, "collect_macro", _fake_macro)
    monkeypatch.setattr(pm, "fundamentals", _fake_fundamentals)
    packet = asyncio.run(pm.run_price_macro(_plan()))
    by_id = {f.id: f for f in packet.typed_facts}
    assert by_id["per:AAPL"].value == 37.58 and by_id["per:AAPL"].unit == "배"
    assert by_id["eps:AAPL"].value == 8.34 and by_id["eps:AAPL"].unit == "USD"
    assert "per:005930" not in by_id  # fundamentals 미제공 심볼은 승격 없음


def test_fundamentals_failure_isolated(monkeypatch):
    """fundamentals 예외가 시세 브랜치를 죽이면 안 됨 (never-raise)."""
    async def _boom(symbols, client=None):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(pm, "quote", _fake_quote)
    monkeypatch.setattr(pm, "collect_macro", _fake_macro)
    monkeypatch.setattr(pm, "fundamentals", _boom)
    packet = asyncio.run(pm.run_price_macro(_plan()))
    assert packet.status == "ok"
    assert any(f.id == "price:AAPL" for f in packet.typed_facts)


def test_toss_eps_promoted_to_typed_fact():
    """토스 epsKrw가 typed_fact로 승격된다 (PER만 승격하고 EPS를 버리던 갭)."""
    from contracts import DaPacket, PriceMacroPacket, RaPacket, TickerCandidate as TC
    from stages.assemble import run_assemble
    plan = PlanPacket(
        tier=2, original_question="q", standalone_question="q",
        knowledge_cutoff="2026-07-09",
        tickers=[TC(name="삼성전자", code="005930", yahoo_symbol="005930.KS")])
    ra = RaPacket(toss_company={"005930": {"info_per": 21.58, "info_eps_krw": 12372,
                                           "news": [], "trading_trend": []}})
    table = run_assemble(plan, DaPacket(), ra, PriceMacroPacket())
    by_id = {f.id: f for f in table.typed_facts}
    assert by_id["toss:005930:per"].value == 21.58
    assert by_id["toss:005930:eps"].value == 12372 and by_id["toss:005930:eps"].unit == "KRW"
