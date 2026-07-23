import asyncio

from contracts import (ChainEdge, ChainEdgeVerdict, ChainPacket, ClaimTable, DaPacket,
                       EnvelopeMeta, PlanPacket, TypedFact, UnitAnswer)
from stages.synthesize import run_synthesize, validate_scenarios

_CHAIN = ChainPacket(meta=EnvelopeMeta(), event="HBM 증설 보도",
                     mechanism="공급 확대 기대", edges=[
    ChainEdge(edge_id="e0", edge="B->A", kind="observed",
              supporting_card_ids=["card-1"]),
    ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference")])
_VERDICTS = [ChainEdgeVerdict(edge_id="e0", grounded=True),
             ChainEdgeVerdict(edge_id="e1", grounded=False)]
_FACTS = [TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB",
                    label="D램 현물가 (ddr5_16gb)")]

# 권고 2 반영: 근거 없는 수량("2건 이상") 제거 — 숫자 불변식과 충돌 금지
_GOOD = """결론.

## 긍정 시나리오
- 체인: e0 (B->A) 경로 유지
- 지표: D램 현물가 (ddr5_16gb) 상승 지속
- 유효 조건: 하이퍼스케일러 발주 유지 보도 확인
- 기각 조건: 발주 축소 보도

## 부정 시나리오
- 체인: e0 역전 — 발주 둔화
- 지표: D램 현물가 (ddr5_16gb) 하락 전환
- 유효 조건: 재고 경고 보도 누적
- 기각 조건: 가격 반등
"""


def test_validate_good_and_missing_section():
    assert validate_scenarios(_GOOD, _CHAIN, _FACTS, _VERDICTS) == []
    bad = _GOOD.split("## 부정 시나리오")[0]
    assert any("부정 시나리오" in i
               for i in validate_scenarios(bad, _CHAIN, _FACTS, _VERDICTS))


def test_validate_rejects_fake_edge_ungrounded_and_empty_payload():
    fake = _GOOD.replace("체인: e0", "체인: e9")
    assert any("체인" in i for i in validate_scenarios(fake, _CHAIN, _FACTS, _VERDICTS))
    ungrounded = _GOOD.replace("체인: e0 (B->A) 경로 유지", "체인: e1 경유") \
                      .replace("체인: e0 역전 — 발주 둔화", "체인: e1 역전")
    # grounded=True edge 0개 인용 → 불인정 (r1-B6)
    assert any("체인" in i
               for i in validate_scenarios(ungrounded, _CHAIN, _FACTS, _VERDICTS))
    empty = _GOOD.replace("- 유효 조건: 하이퍼스케일러 발주 유지 보도 확인", "- 유효 조건:")
    assert any("유효 조건" in i
               for i in validate_scenarios(empty, _CHAIN, _FACTS, _VERDICTS))


def test_validate_metric_contract():
    no_metric = _GOOD.replace("D램 현물가 (ddr5_16gb)", "임의 지표")
    assert any("지표" in i
               for i in validate_scenarios(no_metric, _CHAIN, _FACTS, _VERDICTS))
    # facts 없음 → '지표 없음'만 허용 (권고 2 — 계약 정합 fixture)
    ok = _GOOD.replace("- 지표: D램 현물가 (ddr5_16gb) 상승 지속", "- 지표: 지표 없음") \
              .replace("- 지표: D램 현물가 (ddr5_16gb) 하락 전환", "- 지표: 지표 없음")
    assert validate_scenarios(ok, _CHAIN, [], _VERDICTS) == []
    assert any("지표" in i for i in validate_scenarios(_GOOD, _CHAIN, [], _VERDICTS))


def _plan_da():
    plan = PlanPacket(tier=3, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")
    da = DaPacket(unit_answers=[UnitAnswer(unit_id="q0", model="da_gpt",
                                           answer_text="a")])
    return plan, da


def test_resynthesis_once_then_flag(monkeypatch):
    answers = ["시나리오 절 없는 답", "여전히 없는 답"]
    prompts = []
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, ctx, instr, **kw):
            prompts.append(ctx)
            return answers[len(prompts) - 1]
    monkeypatch.setattr("stages.synthesize.Role", _FakeRole)
    plan, da = _plan_da()
    draft = asyncio.run(run_synthesize(plan, da, chain=_CHAIN,
                                       chain_verdicts=_VERDICTS,
                                       scenario_required=True))
    assert len(prompts) == 2                             # 정확 1회 재합성
    assert "시나리오 계약 미충족" in prompts[1]
    assert draft.scenario_flags                          # 재실패 플래그
    assert draft.answer_markdown == "여전히 없는 답"


def test_success_and_off_path_single_call(monkeypatch):
    calls = []
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, ctx, instr, **kw):
            calls.append((ctx, instr))
            return _GOOD
    monkeypatch.setattr("stages.synthesize.Role", _FakeRole)
    plan, da = _plan_da()
    draft = asyncio.run(run_synthesize(
        plan, da, claim_table=ClaimTable(typed_facts=_FACTS),   # 권고 2 — facts 실존과 정합
        chain=_CHAIN, chain_verdicts=_VERDICTS, scenario_required=True))
    assert len(calls) == 1 and draft.scenario_flags == []
    ctx, instr = calls[0]
    assert "## 긍정 시나리오" in instr                   # 계약 지시
    assert "[인과 체인]" in ctx and "공급 확대 기대" in ctx  # mechanism 렌더 (r1-B5)
    calls.clear()
    asyncio.run(run_synthesize(plan, da))                # off-path
    assert len(calls) == 1
    assert "## 긍정 시나리오" not in calls[0][1] and "[인과 체인]" not in calls[0][0]
