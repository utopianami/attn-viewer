"""M5 게이트 오프라인 테스트 — ASSEMBLER 충돌해소 · G2/G3/G4 코드 게이트 · AUDIT 숫자 대조.

LLM 불필요 (G1은 라이브 전용). 설계 M5 검증 기준 ①②를 코드 수준에서 커버:
① CALC 값이 DA 추정치를 이김 ② 조작 수치 네거티브 (미검증 라벨).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    AtomicClaim,
    CalcRequest,
    CalcResult,
    ClaimNorm,
    DaPacket,
    NeededEvidence,
    PlanPacket,
    PriceMacroPacket,
    RaPacket,
    TypedFact,
    UnitAnswer,
)
from stages.assemble import run_assemble  # noqa: E402
from stages.audit import run_audit  # noqa: E402
import stages.verify as verify_mod  # noqa: E402


async def _stub_g1(role_name, judged_by, claims, evidence, overrides):
    """오프라인 — G1 LLM 심판 무력화 (uncertain no-op). 코드 게이트만 검증."""
    return {c.id: ("uncertain", "offline stub", "code") for c in claims}


@pytest.fixture(autouse=True)
def _stub_g1_judge(monkeypatch):
    monkeypatch.setattr(verify_mod, "_g1_judge", _stub_g1)


def _plan(tier=2) -> PlanPacket:
    return PlanPacket(
        tier=tier, original_question="삼성전자 올해 얼마나 올랐어?",
        standalone_question="삼성전자 올해 수익률", knowledge_cutoff="2026-07-03",
        needed_evidence=[NeededEvidence(entity="삼성전자", metric="수익률", source_type="price")],
        metrics=["기간 수익률"],
    )


def _da_claim(cid, value, source="da_gpt", text=None) -> AtomicClaim:
    return AtomicClaim(
        id=cid, text=text or f"삼성전자 수익률 {value}%", type="numeric", source=source,
        unit_id="q0", norm=ClaimNorm(entity="삼성전자", metric="수익률", value=value, unit="percent"),
    )


def _packets(da_claims):
    da = DaPacket(unit_answers=[UnitAnswer(unit_id="q0", model="da_gpt", answer_text="a",
                                           claims=da_claims)])
    ra = RaPacket()
    pm = PriceMacroPacket(typed_facts=[
        TypedFact(id="ret:삼성전자", value=23.5, unit="percent", period="since 2026-01-02",
                  label="삼성전자 기간수익률", source="yahoo:005930.KS"),
        TypedFact(id="price:삼성전자", value=91000, unit="KRW", label="삼성전자 현재가",
                  source="yahoo:005930.KS"),
    ])
    return da, ra, pm


def test_conflict_calc_authority():
    """① 같은 claim_key에서 DA 추정치 vs 결정적 시세 → CALC/price 권위 채택."""
    da_claims = [_da_claim("da:q0:c0", 40.0)]  # DA가 40%라고 잘못 주장
    da, ra, pm = _packets(da_claims)
    # price claim은 assemble이 typed_facts에서 만든다 (수익률 23.5)
    table = run_assemble(_plan(), da, ra, pm)
    conflicts = [c for c in table.conflicts if "수익률" in c.claim_key]
    assert conflicts, "충돌이 감지돼야 함"
    cf = conflicts[0]
    assert cf.resolution == "calc", cf
    chosen = next(c for c in table.claims if c.id == cf.chosen_claim_id)
    assert chosen.source == "price" and abs(chosen.norm.value - 23.5) < 0.01
    # 패배한 DA claim은 uncertainty 강등
    loser = next(c for c in table.claims if c.id == "da:q0:c0")
    assert loser.uncertainty == "high"
    print("PASS conflict: CALC 권위가 DA를 이김")


def test_dada_disagreement():
    """DA-DA 불일치 — 채택 없음, 둘 다 집중검증 승격."""
    da_claims = [_da_claim("da_gpt:q0:c0", 40.0, "da_gpt"),
                 _da_claim("da_fable:q0:c0", 10.0, "da_fable")]
    da = DaPacket(unit_answers=[
        UnitAnswer(unit_id="q0", model="da_gpt", answer_text="a", claims=[da_claims[0]]),
        UnitAnswer(unit_id="q0", model="da_fable", answer_text="b", claims=[da_claims[1]]),
    ])
    table = run_assemble(_plan(), da, RaPacket(), PriceMacroPacket())
    assert table.da_disagreements, "DA-DA 불일치 감지"
    for cid in (table.da_disagreements[0].gpt_claim_id, table.da_disagreements[0].fable_claim_id):
        c = next(x for x in table.claims if x.id == cid)
        assert c.load_bearing and c.uncertainty == "high"
    print("PASS DA-DA: 불일치 → 집중검증 승격")


def test_coverage():
    """coverage 코드 매칭 — 슬롯 covered / uncovered."""
    plan = _plan()
    plan.needed_evidence.append(
        NeededEvidence(entity="삼성전자", metric="HBM 점유율", source_type="news"))
    da, ra, pm = _packets([_da_claim("da:q0:c0", 23.4)])
    table = run_assemble(plan, da, ra, pm)
    stat = {f"{ce.slot.metric}": ce.status for ce in table.coverage}
    assert stat["수익률"] == "covered", stat
    assert stat["HBM 점유율"] == "uncovered", stat
    print("PASS coverage: 슬롯 매칭 동작")


async def _g2_case():
    """② 조작 수치 네거티브 — 결정적 값과 안 맞는 DA 숫자는 G2 fail → unverified."""
    from stages.verify import run_verify
    da_claims = [_da_claim("da:q0:c0", 40.0), _da_claim("da:q0:c1", 23.4)]  # c1은 시세와 일치
    da, ra, pm = _packets(da_claims)
    plan = _plan()
    table = run_assemble(plan, da, ra, pm)
    calc = [CalcResult(request=CalcRequest(metric="기간 수익률"), ok=True,
                       result={"result": {"value": 23.5, "unit": "percent"},
                               "checks": {"units_consistent": True}, "errors": []})]
    # G1 심판은 오프라인 — Role 생성이 실패해도 uncertain 처리되도록 overrides로 빈 체인 회피 불가
    # → 여기서는 G2/G3 코드 게이트만 본다 (G1은 judge unavailable → uncertain no-op)
    v = await run_verify(plan, table, ra, calc, round_=2)  # round=2 → directive 생성 안 함
    vmap = {x.claim_id: x for x in v.verdicts}
    assert vmap["da:q0:c0"].gates.g2 == "fail", vmap["da:q0:c0"]
    assert vmap["da:q0:c0"].final in ("unverified", "rejected")
    assert vmap["da:q0:c1"].gates.g2 == "pass"
    print("PASS G2: 조작 수치 unverified 강등, 일치 수치 pass")


async def _g3_g4_case():
    from stages.verify import run_verify
    plan = _plan(tier=3)
    future = AtomicClaim(id="ra_x:c0", text="삼성전자 신제품 발표", type="fact", source="ra_x",
                         norm=ClaimNorm(entity="삼성전자", metric="발표", as_of="2026-08-01"))
    directive = AtomicClaim(id="da:q0:c9", text="지금 무조건 사세요", type="fact", source="da_gpt")
    ra = RaPacket(claims=[future])
    da = DaPacket(unit_answers=[UnitAnswer(unit_id="q0", model="da_gpt", answer_text="a",
                                           claims=[directive])])
    table = run_assemble(plan, da, ra, PriceMacroPacket())
    v = await run_verify(plan, table, ra, [], round_=2)
    vmap = {x.claim_id: x for x in v.verdicts}
    assert vmap["ra_x:c0"].gates.g3 == "fail" and vmap["ra_x:c0"].final == "rejected"
    assert vmap["da:q0:c9"].gates.g4 == "fail" and vmap["da:q0:c9"].final == "rejected"
    print("PASS G3/G4: no-lookahead 기각 + 지시어 기각")


async def _audit_case():
    da, ra, pm = _packets([])
    table = run_assemble(_plan(), da, ra, pm)
    calc = [CalcResult(request=CalcRequest(metric="기간 수익률"), ok=True,
                       result={"result": {"value": 23.5, "unit": "percent"},
                               "checks": {"units_consistent": True}, "errors": []})]
    answer = "삼성전자는 올해 23.5% 올랐고 현재가는 91,000원이다. 그런데 영업이익은 77.7조 늘었다. 지금 사세요."
    report, patched = await run_audit(answer, table, calc)
    kinds = {i.kind for i in report.issues}
    assert "numeric_unsupported" in kinds, report  # 77.7조는 근거 없음
    assert "[확인되지 않은 수치]" in patched
    assert "23.5%[확인되지 않은 수치]" not in patched  # 지지된 숫자는 라벨 없음
    assert report.directive_hits and "사세요" not in patched  # 완곡화
    print("PASS AUDIT: 신규 숫자 라벨 + 지지 숫자 통과 + 지시어 완곡화")


def main():
    test_conflict_calc_authority()
    test_dada_disagreement()
    test_coverage()
    asyncio.run(_g2_case())
    asyncio.run(_g3_g4_case())
    asyncio.run(_audit_case())
    print("\n6/6 PASS")


if __name__ == "__main__":
    main()
