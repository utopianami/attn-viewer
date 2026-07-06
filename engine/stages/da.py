"""DA 스테이지 — 블라인드 독립 답변 (도구 금지, 교차검증 앵커).

전체 질문 유닛: gpt-5.5·medium + opus-4.8·medium 이중 블라인드 (불일치 = 검증 신호)
각 서브질문 유닛: gpt-5.5·medium
유닛 프롬프트에 [전체 질문 + 서브질문 전체 목록]을 넣어 맥락을 준다 (2026-07-02 지시).
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from contracts import AtomicClaim, ClaimNorm, DaPacket, EnvelopeMeta, PlanPacket, UnitAnswer
from providers import Role


class _Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    type: str = "fact"  # fact|numeric|price|definition|risk|comparison|regulation|temporal
    uncertainty: str = "medium"
    entity: str = ""
    metric: str = ""
    value: float | None = None   # 숫자 주장이면 수치 (G2 대조용 — 없으면 검증 불가)
    unit: str = ""               # percent|KRW|조원|배 등
    period: str = ""             # "2026Q1", "2025년" 등


class _DaAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    claims: list[_Claim] = Field(default_factory=list)


_INSTR = """너는 금융 QA의 독립 답변(DA) 단계다. 검색·도구 없이 네가 아는 지식만으로 답한다.
모르면 모른다고 하라. 추측이면 uncertainty=high로 표시하라. 지어내지 마라.
answer는 간결하게. claims는 답의 핵심 주장을 원자 단위로.
- claims는 답변당 6~10개. 한 claim에 검증 가능한 사실 정확히 1개 — 더 쪼개지도 뭉치지도 마라.
- 각 claim에 entity(회사/지수), metric(무엇의 값인지)을 채워라 (검증 매칭에 필수).
- type: fact(사실) | numeric(수치) | price(시세) | definition(정의) | risk(위험) |
  comparison(A가 B보다 — 비교) | temporal(일정·발표일).
- 숫자 주장(type=numeric|price|comparison)은 value(숫자), unit(percent|KRW|조원|억원|배), period(해당 기간)를 반드시 채워라.
  value 없는 숫자 주장은 검증이 불가능해 미검증 처리된다."""


def _unit_prompt(plan: PlanPacket, target_id: str, target_text: str) -> str:
    subs = "\n".join(f"  {s.id}. {s.text}" for s in plan.sub_questions)
    return (
        f"[전체 질문] {plan.standalone_question}\n"
        f"[전체 질문의 하위 질문들]\n{subs or '  (없음)'}\n"
        f"[기준 시점] {plan.knowledge_cutoff}\n\n"
        f"위 맥락을 파악한 상태에서 다음 질문에만 답하라:\n[{target_id}] {target_text}"
    )


async def _one(role_name: str, model_label: str, plan: PlanPacket,
               unit_id: str, unit_text: str, overrides: dict | None) -> UnitAnswer:
    role = Role(role_name, overrides)
    val: _DaAnswer = await role.run(
        _unit_prompt(plan, unit_id, unit_text), _INSTR, response_format=_DaAnswer,
    )
    claims = []
    for i, c in enumerate(val.claims):
        # regulation은 DA에 없음 — DA는 출처 좌표(ref)가 없어 G1_STRICT를 구조적으로
        # 통과 불가, 매번 즉시 미검증 + REFLECT 낭비 (2차 리뷰 #3). fact로 강등.
        ctype = c.type if c.type in {"fact", "numeric", "price", "definition", "risk",
                                     "comparison", "temporal"} else "fact"
        unc = c.uncertainty if c.uncertainty in {"low", "medium", "high"} else "medium"
        claims.append(AtomicClaim(
            id=f"{model_label}:{unit_id}:c{i}",
            text=c.text, type=ctype, source=model_label,  # type: ignore[arg-type]
            unit_id=unit_id, uncertainty=unc,  # type: ignore[arg-type]
            norm=ClaimNorm(entity=c.entity, metric=c.metric,
                           value=c.value, unit=c.unit, period=c.period),
        ))
    return UnitAnswer(unit_id=unit_id, model=model_label, answer_text=val.answer, claims=claims)  # type: ignore[arg-type]


async def run_da(plan: PlanPacket, overrides: dict | None = None) -> DaPacket:
    """블라인드 답변 — 전체질문 이중(GPT+Fable), 서브질문 GPT. never-raise는 오케스트레이터."""
    tasks = [
        _one("da_gpt", "da_gpt", plan, "q0", plan.standalone_question, overrides),
        _one("da_fable", "da_fable", plan, "q0", plan.standalone_question, overrides),
    ]
    for sq in plan.sub_questions:
        tasks.append(_one("da_gpt", "da_gpt", plan, sq.id, sq.text, overrides))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    answers, errors = [], []
    for r in results:
        if isinstance(r, BaseException):
            errors.append(str(r))
        else:
            answers.append(r)

    status = "ok" if not errors else ("degraded" if answers else "error")
    return DaPacket(
        meta=EnvelopeMeta(round=plan.meta.round, plan_ref=plan.plan_ref()),
        status=status,  # type: ignore[arg-type]
        error="; ".join(errors)[:400] or None,
        unit_answers=answers,
    )
