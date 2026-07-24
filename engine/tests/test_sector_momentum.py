"""최근 업종 모멘텀 수집·채팅 배선의 오프라인 회귀."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    AtomicClaim,
    ClaimNorm,
    DaPacket,
    NeededEvidence,
    PlanPacket,
    PriceMacroPacket,
    RaPacket,
    UnitAnswer,
)
from stages.assemble import run_assemble  # noqa: E402
from tools.toss.sector_momentum import (  # noqa: E402
    SectorLeader,
    SectorMomentumResult,
    SectorMomentumRow,
    collect_sector_momentum,
    is_sector_momentum_request,
    parse_lookback_sessions,
)


def _result() -> SectorMomentumResult:
    return SectorMomentumResult(
        status="ok",
        as_of="2026-07-23",
        base_session="2026-07-20",
        lookback_sessions=3,
        universe_requested=200,
        universe_valid=180,
        coverage_pct=90.0,
        sector_count=2,
        positive_sector_count=2,
        sectors=[
            SectorMomentumRow(
                rank=1,
                sector_code="G45",
                sector_name="반도체와반도체장비",
                member_count=8,
                median_return_pct=7.2,
                equal_weight_return_pct=7.5,
                market_cap_weighted_return_pct=6.8,
                breadth_positive_pct=87.5,
                leaders=[
                    SectorLeader(
                        code="005930", name="삼성전자",
                        return_pct=9.1, source="toss_wts",
                    )
                ],
            ),
            SectorMomentumRow(
                rank=2,
                sector_code="G25",
                sector_name="조선",
                member_count=5,
                median_return_pct=4.1,
                equal_weight_return_pct=4.0,
                market_cap_weighted_return_pct=3.8,
                breadth_positive_pct=80.0,
            ),
        ],
        sources=["toss_wts"],
        methodology="KOSPI 표본; WICS; 3거래세션 종가 수익률 중앙값",
    )


def test_sector_question_detection_and_lookback():
    question = "최근 2~3일 오른 섹터를 업종별로 분류해줘"
    assert is_sector_momentum_request(question, "kr")
    assert parse_lookback_sessions(question) == 3
    assert not is_sector_momentum_request("삼성전자 최근 뉴스 알려줘", "kr")
    assert not is_sector_momentum_request(question, "global")


def test_sector_aggregation_aligns_date_and_ranks(monkeypatch):
    import tools.toss.sector_momentum as module

    items = [
        {"code": f"00000{i}", "name": f"종목{i}", "marcap": 100 - i}
        for i in range(1, 7)
    ]
    monkeypatch.setattr(module, "_universe", lambda limit: (items, {}))
    observations = {
        "000001": ("S1", "반도체", 10.0, "2026-07-20", "2026-07-23", 100),
        "000002": ("S1", "반도체", 4.0, "2026-07-20", "2026-07-23", 80),
        "000003": ("S2", "조선", 6.0, "2026-07-20", "2026-07-23", 60),
        # 종료일은 같아도 거래정지 등으로 시작 세션이 다르면 집계에서 제외한다.
        "000004": ("S2", "조선", 99.0, "2026-07-19", "2026-07-23", 40),
        "000005": ("S1", "반도체", 99.0, "2026-07-20", "2026-07-22", 20),
        "000006": ("S2", "조선", 2.0, "2026-07-20", "2026-07-23", 10),
    }

    async def fake_observation(client, item, *, lookback, cutoff):
        row = observations.get(item["code"])
        if row is None:
            return None, "missing_history"
        sector_code, sector_name, ret, base_date, as_of, cap = row
        return {
            "code": item["code"],
            "name": item["name"],
            "sector_code": sector_code,
            "sector_name": sector_name,
            "market_cap": cap,
            "return_pct": ret,
            "base_date": base_date,
            "as_of": as_of,
            "source": "toss_wts",
        }, ""

    monkeypatch.setattr(module, "_stock_observation", fake_observation)
    result = asyncio.run(collect_sector_momentum(
        lookback_sessions=3, cutoff="2026-07-23", universe_size=30, min_members=2
    ))
    assert result.status == "partial"
    assert result.as_of == "2026-07-23"
    assert result.universe_valid == 4
    assert result.excluded["stale_as_of"] == 1
    assert result.excluded["different_base_session"] == 1
    assert [row.sector_name for row in result.sectors] == ["반도체", "조선"]
    assert result.sectors[0].median_return_pct == 7.0
    assert result.sectors[1].median_return_pct == 4.0


def test_price_macro_runs_sector_scan_without_tickers(monkeypatch):
    import stages.price_macro as module

    async def fake_macro():
        return {}

    async def fake_sector(**kwargs):
        assert kwargs["lookback_sessions"] == 3
        assert kwargs["cutoff"] == "2026-07-23"
        return _result()

    async def fake_fundamentals(*args, **kwargs):
        return {}

    monkeypatch.setattr(module, "collect_macro", fake_macro)
    monkeypatch.setattr(module, "collect_sector_momentum", fake_sector)
    monkeypatch.setattr(module, "fundamentals", fake_fundamentals)
    plan = PlanPacket(
        tier=2,
        original_question="최근 2-3일 오른 섹터 분류해줘",
        standalone_question="최근 2-3일 오른 코스피 업종 분류",
        knowledge_cutoff="2026-07-23",
        market_scope="kr",
        needed_evidence=[
            NeededEvidence(
                entity="KOSPI/KOSDAQ sectors",
                metric="2~3거래일 수익률",
                source_type="price",
            )
        ],
    )
    packet = asyncio.run(module.run_price_macro(plan))
    assert packet.status == "ok"
    assert not packet.quotes
    assert packet.extra_series[0]["kind"] == "sector_momentum"
    assert any(f.id == "sector_ret:G45" for f in packet.typed_facts)
    assert any(c.id == "price:sector_momentum:coverage" for c in packet.claims)

    table = run_assemble(plan, DaPacket(), RaPacket(), packet)
    assert table.coverage[0].status == "covered"


def test_missing_data_statement_does_not_fake_price_coverage():
    plan = PlanPacket(
        tier=2,
        original_question="업종",
        standalone_question="업종",
        knowledge_cutoff="2026-07-23",
        needed_evidence=[
            NeededEvidence(
                entity="코스피 업종지수",
                metric="업종별 등락률",
                source_type="price",
            )
        ],
    )
    missing = AtomicClaim(
        id="da:q0:missing",
        text="코스피 업종별 등락률은 차트 데이터 접근이 안 되어 확인 불가",
        type="context",
        source="da_gpt",
        norm=ClaimNorm(entity="코스피 업종지수", metric="업종별 등락률"),
    )
    da = DaPacket(unit_answers=[
        UnitAnswer(
            unit_id="q0", model="da_gpt", answer_text="확인 불가", claims=[missing]
        )
    ])
    table = run_assemble(plan, da, RaPacket(), PriceMacroPacket())
    assert table.coverage[0].status == "uncovered"
