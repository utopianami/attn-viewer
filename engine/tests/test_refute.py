"""A2 — 반증 자세 검증 (동의 편향 완화): supported로 통과한 load-bearing claim에 반박 시도."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402
from contracts import AtomicClaim, ClaimNorm, ClaimTable, PlanPacket, RaPacket  # noqa: E402
import stages.verify as verify_mod  # noqa: E402


async def _g1_supported(role_name, judged_by, claims, evidence, overrides):
    return {c.id: ("supported", "stub", judged_by) for c in claims}


def _fixtures():
    plan = PlanPacket(tier=3, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-09")
    c = AtomicClaim(id="c1", text="삼성전자 4분기 흑자 전환", type="fact", source="ra_x",
                    load_bearing=True,
                    norm=ClaimNorm(entity="삼성전자", metric="흑자",
                                   source_type="secondary"))
    return plan, ClaimTable(claims=[c])


def test_flag_off_no_refute(monkeypatch):
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_supported)
    monkeypatch.setattr(settings, "refute_mode", "off", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    assert verdict.verdicts[0].final == "verified"


def test_flag_on_refuted_downgrades(monkeypatch):
    async def _refutes(role_name, claims, evidence, overrides):
        return {c.id: (True, "증거의 시점이 주장과 다름") for c in claims}
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_supported)
    monkeypatch.setattr(verify_mod, "_refute_judge", _refutes)
    monkeypatch.setattr(settings, "refute_mode", "on", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    v = verdict.verdicts[0]
    assert v.final == "unverified" and "반증" in v.note


def test_flag_on_stands(monkeypatch):
    async def _no_refute(role_name, claims, evidence, overrides):
        return {c.id: (False, "반박 근거 없음") for c in claims}
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_supported)
    monkeypatch.setattr(verify_mod, "_refute_judge", _no_refute)
    monkeypatch.setattr(settings, "refute_mode", "on", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    assert verdict.verdicts[0].final == "verified"
