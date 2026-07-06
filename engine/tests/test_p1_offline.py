"""P1 검색 개선 오프라인 테스트 — answerability 프리패스 · curation 폴백 · id 부여.

LLM 불필요. 커버:
① coverage 구멍(required) → 보완 쿼리 직결
② DA-DA 불일치 → "최신 공식 수치" 쿼리 직결 (P1-4)
③ obtainability=unavailable 슬롯은 보완 대상 아님
④ curated_items() — 선별 반영·미수행 전량 폴백·미판정 유닛 통과
⑤ _assign_ids — 빈 id만 채움
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    AtomicClaim,
    ClaimNorm,
    ClaimTable,
    CoverageEntry,
    DaDisagreement,
    NeededEvidence,
    NewsItem,
    RaPacket,
)
from stages.answerability import _prepass  # noqa: E402
from stages.ra_external import _assign_ids  # noqa: E402


def _slot(entity="카카오", metric="영업이익", required=True, obtainability="public"):
    return NeededEvidence(entity=entity, metric=metric, source_type="news",
                          required=required, obtainability=obtainability)


def test_prepass_coverage_hole():
    table = ClaimTable(coverage=[
        CoverageEntry(slot=_slot(), status="uncovered"),
        CoverageEntry(slot=_slot(metric="매출", required=False), status="uncovered"),
        CoverageEntry(slot=_slot(metric="내부자료", obtainability="unavailable"),
                      status="uncovered"),
        CoverageEntry(slot=_slot(metric="PER"), status="covered"),
    ])
    supp = _prepass(table)
    qs = [q for s in supp for q in s.search_queries]
    assert any("영업이익" in q for q in qs), qs
    assert not any("매출" in q for q in qs), "required=False는 보완 대상 아님"
    assert not any("내부자료" in q for q in qs), "unavailable은 보완 대상 아님"
    assert not any("PER" in q for q in qs), "covered는 보완 대상 아님"


def test_prepass_da_disagreement():
    c1 = AtomicClaim(id="g1", text="영업이익 5000억", type="numeric", source="da_gpt",
                     norm=ClaimNorm(entity="카카오", metric="영업이익", value=5000, unit="억"))
    c2 = AtomicClaim(id="f1", text="영업이익 4000억", type="numeric", source="da_fable",
                     norm=ClaimNorm(entity="카카오", metric="영업이익", value=4000, unit="억"))
    table = ClaimTable(claims=[c1, c2], da_disagreements=[
        DaDisagreement(claim_key=c1.claim_key, gpt_claim_id="g1", fable_claim_id="f1")])
    supp = _prepass(table)
    assert supp and "최신 공식 수치" in supp[0].search_queries[0], supp


def test_curated_items():
    items = [NewsItem(id="q0:n0", title="관련"), NewsItem(id="q0:n1", title="노이즈")]
    ra = RaPacket(x_search={"q0": items, "q1": [NewsItem(id="q1:n0", title="미판정")]},
                  curated={"q0": ["q0:n0"]})
    got = ra.curated_items()
    assert [n.id for n in got["q0"]] == ["q0:n0"], "curation 선별 반영"
    assert [n.id for n in got["q1"]] == ["q1:n0"], "curation이 못 본 유닛은 통과"
    assert "q0" in RaPacket(x_search={"q0": items}).curated_items(), "미수행 시 전량 폴백"


def test_assign_ids():
    pools = {"q0": [NewsItem(title="a"), NewsItem(id="keep", title="b")]}
    _assign_ids(pools)
    assert pools["q0"][0].id == "q0:n0" and pools["q0"][1].id == "keep"


def test_g1_cache_carryover():
    """G1 캐리오버 — supported는 재판정 없이 재사용, 실패분은 재판정 대상."""
    import asyncio
    import stages.verify as verify_mod
    from contracts import PlanPacket

    judged: list[str] = []

    async def _spy(role_name, judged_by, claims, evidence, overrides):
        judged.extend(c.id for c in claims)
        return {c.id: ("supported", "spy", judged_by) for c in claims}

    orig = verify_mod._g1_judge
    verify_mod._g1_judge = _spy
    try:
        plan = PlanPacket(tier=3, original_question="q", standalone_question="q",
                          knowledge_cutoff="2026-07-03")
        c = AtomicClaim(id="ra_x:c0", text="사실 주장", type="fact", source="ra_x",
                        norm=ClaimNorm(entity="A", metric="사건", source_type="secondary"))
        table = ClaimTable(claims=[c])
        cache: dict = {}
        v1 = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), [],
                                               g1_cache=cache))
        assert judged == ["ra_x:c0"] and cache["ra_x:c0"][0] == "supported"
        judged.clear()
        v2 = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), [],
                                               round_=1, g1_cache=cache))
        assert judged == [], "supported 캐시가 있는데 재판정함"
        assert v2.verdicts[0].final == "verified", "캐시 verdict 미반영"
    finally:
        verify_mod._g1_judge = orig


def test_norm_age():
    from datetime import date, timedelta
    from stages.ra_external import _norm_age
    today = date.today()
    assert _norm_age("3일 전") == (today - timedelta(days=3)).isoformat()
    assert _norm_age("2 hours ago") == today.isoformat()
    assert _norm_age("1주 전") == (today - timedelta(days=7)).isoformat()
    assert _norm_age("2 months ago") == (today - timedelta(days=60)).isoformat()
    assert _norm_age("2026-07-01T09:30:00Z") == "2026-07-01"
    assert _norm_age("어제") == (today - timedelta(days=1)).isoformat()
    assert _norm_age("TechCrunch") == "", "해석 불가는 빈 문자열 (시점 불명 중립)"
    assert _norm_age("") == ""


def test_audit_composite_and_evidence_anchor():
    """복합 수사(1조 9,421억원) 합산 대조 + 근거 원문 숫자 앵커 + new_fact 코드 필터."""
    import asyncio
    from contracts import ClaimTable
    from stages import audit as audit_mod

    async def _no_llm(*a, **k):
        raise RuntimeError("offline")
    orig = audit_mod.Role.run
    audit_mod.Role.run = _no_llm  # ③ 신규엔티티 mini 스킵 경로
    try:
        answer = "카카오 1분기 매출은 1조 9,421억원, 영업이익 2,114억원이다. 목표가는 99만원이다."
        evidence = ["카카오 실적 발표 — 매출 1조9421억원, 영업이익 2,114억원 기록"]
        report, patched = asyncio.run(audit_mod.run_audit(
            answer, ClaimTable(), [], evidence_texts=evidence))
        unsupported = [i.detail for i in report.issues if i.kind == "numeric_unsupported"]
        assert not any("9,421" in d for d in unsupported), f"복합 수사 오탐: {unsupported}"
        assert not any("2,114" in d for d in unsupported), f"근거 숫자 오탐: {unsupported}"
        assert any("99만원" in d for d in unsupported), "진짜 무근거 숫자(99만원) 미탐"
        assert "99만원[확인되지 않은 수치]" in patched
    finally:
        audit_mod.Role.run = orig


if __name__ == "__main__":
    test_prepass_coverage_hole()
    test_prepass_da_disagreement()
    test_curated_items()
    test_assign_ids()
    test_norm_age()
    print("p1 offline: all passed")
