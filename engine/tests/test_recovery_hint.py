"""A4 — 게이트 실패 사유별 결정론적 복구 힌트 (백지 재시작 금지)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    AtomicClaim, ClaimNorm, ClaimTable, NeededEvidence, PlanPacket, RaPacket,
)
import stages.verify as verify_mod  # noqa: E402


async def _stub_g1(role_name, judged_by, claims, evidence, overrides):
    return {c.id: ("unsupported", "offline stub", judged_by) for c in claims}


verify_mod._g1_judge = _stub_g1


def test_load_bearing_fail_hint():
    plan = PlanPacket(tier=2, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-09")
    c = AtomicClaim(id="c1", text="삼성전자 영업이익 10조", type="fact", source="ra_x",
                    load_bearing=True,
                    norm=ClaimNorm(entity="삼성전자", metric="영업이익",
                                   source_type="secondary"))
    table = ClaimTable(claims=[c])
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    research = [d for d in verdict.retry_directives if d.kind == "research"]
    assert research and research[0].recovery_hint
    assert "다른" in research[0].recovery_hint or "갭" in research[0].recovery_hint


def test_coverage_hole_hint_mentions_source():
    plan = PlanPacket(tier=1, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-09",
                      needed_evidence=[NeededEvidence(entity="삼성전자", metric="수출",
                                                      source_type="web")])
    from stages.assemble import run_assemble
    from contracts import DaPacket, PriceMacroPacket
    table = run_assemble(plan, DaPacket(), RaPacket(), PriceMacroPacket())
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    holes = [d for d in verdict.retry_directives if "[수집]" in d.reason]
    assert holes and "web" in holes[0].recovery_hint
