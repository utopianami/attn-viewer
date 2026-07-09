"""RISK 스테이지 — 반대 시나리오 (설계 §⑥′, tier 3만, fable·low).

bear case는 supporting_claim_ids 필수 — 미참조 항목은 코드가 "시나리오(미검증)" 자동 강등
(프롬프트 소원이 아니라 코드가 라벨링 — 2차 리뷰).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from contracts import BearCase, ClaimTable, EnvelopeMeta, PlanPacket, RiskPacket
from providers import Role


class _SO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Bear(_SO):
    text: str
    supporting_claim_ids: list[str] = Field(default_factory=list)


class _Risk(_SO):
    bear_cases: list[_Bear] = Field(default_factory=list)
    wrong_if: str = ""


_INSTR = """너는 금융 QA의 반대 시나리오(RISK) 단계다. 낙관 답변에 반대하는 bear case를 만든다.
- bear_cases: 2~4개. 각각 supporting_claim_ids에 근거가 되는 claim id를 반드시 채워라.
  근거 claim이 없으면 그 시나리오는 근거 없는 가정임을 알고 있어라 (그래도 중요하면 내라 — 코드가 '시나리오' 라벨을 단다).
- wrong_if: "이 분석이 틀릴 가능성이 가장 큰 지점" 한 문장.
- 과장 금지. 이해상충·최근 반대 신호를 우선하라."""


async def run_risk(plan: PlanPacket, table: ClaimTable, *,
                   round_: int = 0, overrides: dict | None = None,
                   force: bool = False) -> RiskPacket:
    """tier < 3이고 force 아님 → 즉시 passthrough (skipped 패킷 — 불변식 1)."""
    if plan.tier < 3 and not force:
        return RiskPacket(meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref()),
                          applicable=False)

    claim_view = "\n".join(
        f"- id={c.id} [{c.source}] {c.text}" for c in table.claims[:40]
    )
    role = Role("risk", overrides)
    try:
        val: _Risk = await role.run(
            f"[질문] {plan.standalone_question}\n[기준시점] {plan.knowledge_cutoff}\n\n"
            f"[수집된 claim 목록]\n{claim_view}",
            _INSTR, response_format=_Risk, effort="low",
        )
    except Exception:
        return RiskPacket(meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref()),
                          applicable=True)  # 빈 패킷 — 합성이 "리스크 분석 실패" 인지

    valid_ids = {c.id for c in table.claims}
    bears = []
    for b in val.bear_cases[:4]:
        ids = [i for i in b.supporting_claim_ids if i in valid_ids]
        bears.append(BearCase(
            text=b.text, supporting_claim_ids=ids,
            label="grounded" if ids else "scenario",   # 코드가 라벨링
        ))
    return RiskPacket(
        meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref()),
        applicable=True, bear_cases=bears, wrong_if=val.wrong_if,
    )
