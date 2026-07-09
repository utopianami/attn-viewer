"""A1 — 역할 재제시 재감사 (arXiv 2606.05976). 플래그 off 기본, on일 때 승급 경로."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402
from contracts import AtomicClaim, ClaimNorm, ClaimTable, PlanPacket, RaPacket  # noqa: E402
import stages.verify as verify_mod  # noqa: E402


async def _g1_unsupported(role_name, judged_by, claims, evidence, overrides):
    return {c.id: ("unsupported", "stub", judged_by) for c in claims}


async def _reaudit_supported(role_name, judged_by, claims, evidence, overrides):
    return {c.id: ("supported", "재감사에서 근거 확인") for c in claims}


def _fixtures():
    plan = PlanPacket(tier=2, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-09")
    c = AtomicClaim(id="c1", text="삼성전자 HBM 공급 개시", type="fact", source="ra_x",
                    load_bearing=True,
                    norm=ClaimNorm(entity="삼성전자", metric="HBM",
                                   source_type="secondary"))
    return plan, ClaimTable(claims=[c])


def test_flag_off_no_reaudit(monkeypatch):
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_unsupported)
    monkeypatch.setattr(settings, "reaudit_mode", "off", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    v = verdict.verdicts[0]
    assert v.final == "unverified" and v.reaudit == ""


def test_flag_on_overturn(monkeypatch):
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_unsupported)
    monkeypatch.setattr(verify_mod, "_reaudit_judge", _reaudit_supported)
    monkeypatch.setattr(settings, "reaudit_mode", "on", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    v = verdict.verdicts[0]
    assert v.final == "verified" and v.reaudit == "overturned"


def test_flag_on_upheld(monkeypatch):
    async def _still_bad(role_name, judged_by, claims, evidence, overrides):
        return {c.id: ("unsupported", "여전히 무근거") for c in claims}
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_unsupported)
    monkeypatch.setattr(verify_mod, "_reaudit_judge", _still_bad)
    monkeypatch.setattr(settings, "reaudit_mode", "on", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    v = verdict.verdicts[0]
    assert v.final == "unverified" and v.reaudit == "upheld"
