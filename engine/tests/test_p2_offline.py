"""P2 claim 타입 라우팅 오프라인 테스트 — _ROUTE 게이트 배정 (LLM 스텁).

① regulation + ref 없음 → LLM 불경유 즉시 unverified
② regulation + ref 있음 → G1 후보
③ comparison + value → G2 대조 (조작값은 fail)
④ comparison value 없음(정성 비교) → G2 미적용, G1 후보(2차출처)
⑤ 신규 타입이 스키마를 통과하는지 (contracts Literal)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    AtomicClaim,
    ClaimNorm,
    ClaimTable,
    PlanPacket,
    RaPacket,
    TypedFact,
)
import stages.verify as verify_mod  # noqa: E402

_JUDGED: list[str] = []


async def _stub_g1(role_name, judged_by, claims, evidence, overrides):
    _JUDGED.extend(c.id for c in claims)
    return {c.id: ("supported", "stub", judged_by) for c in claims}


def _run(claims, tier=3, typed_facts=None):
    _JUDGED.clear()
    orig = verify_mod._g1_judge
    verify_mod._g1_judge = _stub_g1
    try:
        plan = PlanPacket(tier=tier, original_question="q", standalone_question="q",
                          knowledge_cutoff="2026-07-03")
        table = ClaimTable(claims=claims, typed_facts=typed_facts or [])
        return asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    finally:
        verify_mod._g1_judge = orig


def test_regulation_no_ref_rejected_fast():
    c = AtomicClaim(id="ra_x:c0", text="전자공시에 따르면 유상증자 결정", type="regulation",
                    source="ra_x", norm=ClaimNorm(entity="A", metric="유상증자",
                                                  source_type="secondary"))
    v = _run([c]).verdicts[0]
    assert v.final == "unverified" and "출처 없음" in v.note, (v.final, v.note)
    assert "ra_x:c0" not in _JUDGED, "ref 없는 regulation이 LLM 판정에 들어감"


def test_regulation_with_ref_judged():
    c = AtomicClaim(id="ra_x:c1", text="공시 인용", type="regulation", source="ra_x",
                    ref="https://dart.fss.or.kr/x",
                    norm=ClaimNorm(entity="A", metric="공시", source_type="secondary"))
    v = _run([c]).verdicts[0]
    assert "ra_x:c1" in _JUDGED and v.final == "verified", (v.final, _JUDGED)


def test_comparison_value_g2():
    fake = AtomicClaim(id="da_gpt:q0:c0", text="A 수익률이 500%로 B보다 높다",
                       type="comparison", source="da_gpt",
                       norm=ClaimNorm(entity="A", metric="수익률", value=500.0, unit="percent"))
    tf = [TypedFact(id="ret:A", value=298.4, unit="percent", label="A 수익률")]
    v = _run([fake], typed_facts=tf).verdicts[0]
    assert v.gates.g2 == "fail" and v.final != "verified", (v.gates, v.final)


def test_comparison_qualitative_no_g2():
    c = AtomicClaim(id="ra_x:c2", text="A 매출이 B보다 크다", type="comparison", source="ra_x",
                    norm=ClaimNorm(entity="A", metric="매출 비교", source_type="secondary"))
    v = _run([c]).verdicts[0]
    assert v.gates.g2 == "skip", "value 없는 정성 비교에 G2 적용됨"
    assert "ra_x:c2" in _JUDGED, "정성 비교가 G1 후보에서 빠짐"


def test_temporal_g3_and_g1():
    c = AtomicClaim(id="ra_x:c3", text="실적 발표는 7월 30일", type="temporal", source="ra_x",
                    norm=ClaimNorm(entity="A", metric="실적 발표일", as_of="2026-07-01",
                                   source_type="secondary"))
    look = AtomicClaim(id="ra_x:c4", text="미래 근거", type="temporal", source="ra_x",
                       norm=ClaimNorm(entity="A", metric="발표", as_of="2026-08-01",
                                      source_type="secondary"))
    vs = {v.claim_id: v for v in _run([c, look]).verdicts}
    assert vs["ra_x:c3"].gates.g3 == "pass" and vs["ra_x:c3"].final == "verified"
    assert vs["ra_x:c4"].final == "rejected", "no-lookahead 위반 미기각"


def test_secondary_context_judged():
    """2차 리뷰 #1 — 2차출처 context/risk가 무검증 verified로 새면 안 됨 (G1 후보)."""
    c = AtomicClaim(id="ra_x:c9", text="삼성전자가 대규모 유상증자를 발표했다", type="context",
                    source="ra_x", norm=ClaimNorm(entity="삼성전자", metric="유상증자",
                                                  source_type="secondary"))
    _run([c], tier=2)
    assert "ra_x:c9" in _JUDGED, "2차출처 context가 G1 후보에서 빠짐 (신뢰성 구멍)"
    # DA definition은 모델지식 허용 — 비후보 유지
    d = AtomicClaim(id="da_gpt:q0:c9", text="PER은 주가수익비율이다", type="definition",
                    source="da_gpt", norm=ClaimNorm(entity="", metric="정의"))
    _run([d], tier=3)
    assert "da_gpt:q0:c9" not in _JUDGED, "DA definition까지 판정하면 비용 낭비"


def test_per_bae_vs_ratio_anchor():
    """2차 리뷰 #2 — DA 'PER 23배'가 toss 승격 ratio 앵커(23.48)와 대조되어 G2 pass."""
    c = AtomicClaim(id="da_gpt:q0:c8", text="PER 약 23배", type="numeric", source="da_gpt",
                    norm=ClaimNorm(entity="삼성전자", metric="PER", value=23.0, unit="배"))
    tf = [TypedFact(id="toss:005930:per", value=23.48, unit="ratio", label="삼성전자 PER")]
    v = _run([c], tier=2, typed_facts=tf).verdicts[0]
    assert v.gates.g2 == "pass", (v.gates, v.note)
    # percent vs 배는 여전히 비호환 (5% ≠ 5배)
    c2 = AtomicClaim(id="da_gpt:q0:c7", text="5% 상승", type="numeric", source="da_gpt",
                     norm=ClaimNorm(entity="A", metric="수익률", value=5.0, unit="percent"))
    tf2 = [TypedFact(id="x:per", value=5.0, unit="배", label="PER")]
    v2 = _run([c2], tier=2, typed_facts=tf2).verdicts[0]
    assert v2.gates.g2 == "fail", "percent가 배 앵커와 우연 일치 — 그룹 분리 실패"


def test_da_comparison_no_value_unverified():
    """2차 리뷰 #5 — 값 없는 DA comparison은 게이트 0개 통과 verified 금지."""
    c = AtomicClaim(id="da_gpt:q0:c6", text="A 매출이 B보다 크다", type="comparison",
                    source="da_gpt", norm=ClaimNorm(entity="A", metric="매출 비교"))
    v = _run([c], tier=2).verdicts[0]
    assert v.final == "unverified" and "미정형" in v.note, (v.final, v.note)


if __name__ == "__main__":
    test_regulation_no_ref_rejected_fast()
    test_regulation_with_ref_judged()
    test_comparison_value_g2()
    test_comparison_qualitative_no_g2()
    test_temporal_g3_and_g1()
    test_secondary_context_judged()
    test_per_bae_vs_ratio_anchor()
    test_da_comparison_no_value_unverified()
    print("p2 offline: all passed")
