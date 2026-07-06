"""CALC 스테이지 — FinQA식 결정적 계산 (설계 §⑤, numeric_policy).

LLM 암산 금지: GPT(gpt-5.5·med)가 typed_facts 기반 #n 스텝 프로그램만 작성하고,
실행은 finance_math.evaluate()가 결정적으로 한다. 모델이 안 만든 숫자만 답에 들어간다.

fan-in 뒤 배치 — ASSEMBLER가 만든 calc_requests + 증거 유래 typed_facts로 계산.
결과는 source="calc" claim으로 claim table에 편입 → 충돌 해소 시 최우선 권위.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from contracts import AtomicClaim, CalcResult, ClaimNorm, ClaimTable, PlanPacket
from providers import Role
from tools.calc.finance_math import FinanceMathError, evaluate
from tools.calc.formulas_kr import match_formula, render_template

_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
_MAX_PROGRAMS = 4


class _SO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Step(_SO):
    op: str                      # add|subtract|multiply|divide|exp|greater|table_*|pp_to_bps|bps_to_pp
    args: list[str]              # typed_fact id / 이전 스텝 out / 숫자 리터럴 문자열("100")
    out: str


class _Program(_SO):
    metric: str                  # 어떤 calc_request에 대한 프로그램인지
    unit_id: str = "q0"
    steps: list[_Step] = Field(default_factory=list)
    passthrough_fact_id: str = ""  # 요청 값이 이미 typed_fact에 있으면 그 id (계산 불필요)
    skip_reason: str = ""        # typed_facts로 계산 불가능하면 스텝 비우고 사유


class _MissingInput(_SO):
    metric: str                  # 어떤 요청의 입력이 부족한지
    needed: str                  # 부족한 사실 서술 ("2025년 연간 DPS", "EPS(TTM)")


class _Programs(_SO):
    programs: list[_Program] = Field(default_factory=list)
    # P3-3 (F8) 2단 구조: 공식 매칭 → 입력이 typed_facts에 없으면 지어내지 말고 보고
    missing_inputs: list[_MissingInput] = Field(default_factory=list)


_INSTR = """너는 금융 QA의 결정적 계산(CALC) 단계다. 계산하지 마라 — 계산 '프로그램'만 작성한다.
2단으로 진행한다 (F8 공식 계획):
① 각 요청을 [공식 템플릿]과 매칭하고 필요한 입력이 [typed_facts]에 있는지 판정하라.
② 입력이 전부 있으면 템플릿 모양대로 프로그램을 작성하고, 없으면 missing_inputs에
   {metric, needed(부족한 사실 하나를 특정: "2025년 연간 주당배당금")}를 보고하라. 값을 지어내지 마라.
규칙 (numeric_policy):
- 각 요청 metric마다 program 1개. 연산: add|subtract|multiply|divide|exp|greater|pp_to_bps|bps_to_pp만.
- args는 typed_fact id, 이전 스텝의 out 이름, 숫자 리터럴("100"), 또는 단위 있는 상수("2500000:KRW")만.
- percent change(상대%): subtract → divide(기준) → multiply "100".
- add/subtract는 두 피연산자 단위가 같아야 한다 — 상수에 단위가 필요하면 "값:단위" 형태로.
- 두 percent의 차이는 pp다 (subtract가 자동 처리).
- 요청 값이 이미 typed_facts에 그대로 있으면 steps 대신 passthrough_fact_id에 그 id를 적어라 (identity 연산 금지).
- 주어진 typed_facts만으로 계산 불가능하면 steps를 비우고 skip_reason에 이유를 적고 missing_inputs에도 보고하라."""


def _coerce_args(args: list[str]) -> list:
    """숫자 리터럴 → float, "값:단위" → {"const":값,"unit":단위} (finance_math 규약)."""
    out = []
    for a in args:
        if _NUM_RE.match(a):
            out.append(float(a))
            continue
        if ":" in a:
            head, _, unit = a.partition(":")
            if _NUM_RE.match(head) and unit:
                out.append({"const": float(head), "unit": unit})
                continue
        out.append(a)
    return out


async def run_calc(plan: PlanPacket, table: ClaimTable,
                   overrides: dict | None = None,
                   ) -> tuple[list[CalcResult], list[AtomicClaim], list[dict]]:
    """calc_requests → 공식 매칭 → 프로그램 작성(GPT 1콜) → 결정적 실행 → calc claim.

    never-raise: 실패한 요청은 ok=False CalcResult로 남긴다 (침묵 저하 금지).
    반환 3번째: missing_inputs [{metric, needed}] — answerability 보완질문으로 합류 (P3-3).
    """
    requests = table.calc_requests[:_MAX_PROGRAMS]
    if not requests or not table.typed_facts:
        return [], [], []

    facts_view = "\n".join(
        f"- {f.id}: {f.value} {f.unit} ({f.label}{', ' + f.period if f.period else ''})"
        for f in table.typed_facts
    )
    reqs_view = "\n".join(f"- [{r.unit_id}] {r.metric}" + (f" ({r.note})" if r.note else "")
                          for r in requests)
    # P3-1: 요청 metric에 매칭되는 한국 공식 템플릿을 few-shot으로 주입
    tmpl_keys = {k for k in (match_formula(r.metric) for r in requests) if k}
    tmpl_view = "\n\n".join(render_template(k) for k in sorted(tmpl_keys))
    prompt = (
        f"[질문] {plan.standalone_question}\n[기준시점] {plan.knowledge_cutoff}\n\n"
        f"[typed_facts]\n{facts_view}\n\n"
        + (f"[공식 템플릿 — 매칭되면 이 모양대로 작성]\n{tmpl_view}\n\n" if tmpl_view else "")
        + f"[계산 요청]\n{reqs_view}"
    )

    role = Role("calc_program", overrides)
    try:
        val: _Programs = await role.run(prompt, _INSTR, response_format=_Programs)
    except Exception as exc:  # noqa: BLE001
        return [CalcResult(request=r, ok=False,
                           result={"errors": [f"program writer failed: {exc}"]})
                for r in requests], [], []

    # (metric, unit_id) 키 — 같은 metric이 여러 유닛에 있으면 덮어쓰지 않도록 (codex #13)
    by_key = {(p.metric.strip(), p.unit_id): p for p in val.programs}
    by_metric = {p.metric.strip(): p for p in val.programs}
    results: list[CalcResult] = []
    claims: list[AtomicClaim] = []
    fact_payload = [f.model_dump() for f in table.typed_facts]

    facts_by_id = {f.id: f for f in table.typed_facts}
    for r in requests:
        prog = by_key.get((r.metric.strip(), r.unit_id)) or by_metric.get(r.metric.strip())
        # passthrough — 요청 값이 이미 typed_fact로 존재 (identity 연산 불필요)
        if prog is not None and prog.passthrough_fact_id in facts_by_id:
            f = facts_by_id[prog.passthrough_fact_id]
            results.append(CalcResult(
                request=r, ok=True,
                result={"result": {"value": f.value, "unit": f.unit},
                        "checks": {"units_consistent": True, "pp_checked": True,
                                   "reexec_equal": None},
                        "errors": [], "passthrough": f.id}))
            claims.append(AtomicClaim(
                id=f"calc:{r.metric[:30]}", type="numeric", source="calc",
                text=f"{r.metric} = {f.value} {f.unit} (결정적 수집값 {f.id})",
                unit_id=r.unit_id, load_bearing=True, uncertainty="low",
                norm=ClaimNorm(entity=(plan.tickers[0].name if plan.tickers else ""),
                               metric=r.metric, unit=f.unit, value=f.value,
                               source_type="primary", as_of=plan.knowledge_cutoff),
                ref=f.source,
            ))
            continue
        if prog is None or not prog.steps:
            reason = (prog.skip_reason if prog else "no program") or "insufficient facts"
            results.append(CalcResult(request=r, ok=False, result={"errors": [reason]}))
            continue
        steps = [{"op": s.op, "args": _coerce_args(s.args), "out": s.out} for s in prog.steps]
        try:
            out = evaluate({"typed_facts": fact_payload, "program": steps})
        except FinanceMathError as exc:
            results.append(CalcResult(request=r, program=steps, ok=False,
                                      result={"errors": [str(exc)]}))
            continue
        ok = not out.get("errors") and out.get("checks", {}).get("units_consistent", False)
        # 결과 단위 sanity — %성 metric에 KRW가 나오는 류의 조용한 오답 차단 (codex #14)
        if ok and out.get("result"):
            m_lower = r.metric.lower()
            wants_pct = any(k in m_lower for k in ("%", "률", "율", "수익", "괴리", "성장", "yoy"))
            got_unit = str(out["result"].get("unit", "")).lower()
            if wants_pct and got_unit not in ("percent", "pp", "ratio", "bps"):
                ok = False
                out.setdefault("errors", []).append(
                    f"unit sanity: {r.metric} 요청에 {got_unit} 반환")
        results.append(CalcResult(request=r, program=steps, result=out, ok=ok))
        if ok and out.get("result"):
            rv = out["result"]
            claims.append(AtomicClaim(
                id=f"calc:{r.metric[:30]}", type="numeric", source="calc",
                text=f"{r.metric} = {rv['value']} {rv['unit']} (결정적 계산)",
                unit_id=r.unit_id, load_bearing=True, uncertainty="low",
                norm=ClaimNorm(
                    entity=(plan.tickers[0].name if plan.tickers else ""),
                    metric=r.metric, unit=rv["unit"],
                    value=float(rv["value"]) if not isinstance(rv["value"], bool) else None,
                    source_type="primary", as_of=plan.knowledge_cutoff,
                ),
                ref="finance_math",
            ))
    # 요청과 느슨히 매칭되는 것만 (요청에 없는 metric의 missing 보고는 환각 가능성).
    # 빈 metric은 substring 매칭을 항상 통과하므로 먼저 배제 (2차 리뷰 #6)
    req_metrics = [r.metric.strip().lower() for r in requests]
    missing = []
    for m in val.missing_inputs[:4]:
        mm = m.metric.strip().lower()
        if not mm or not m.needed.strip():
            continue
        if any(mm in rm or rm in mm for rm in req_metrics):
            missing.append({"metric": m.metric, "needed": m.needed})
    return results, claims, missing
