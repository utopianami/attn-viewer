import inspect

from contracts import DaPacket, PlanPacket, UnitAnswer
from sector.thesis_contracts import Evidence, Statement
from sector.thesis_guard import quantity_literal
from stages.synthesize import _render_context
from stages.thesis_context import ThesisPick, render_thesis_section, thesis_typed_facts
from tests.test_thesis_contracts import make_rev


def _pick(freshness="fresh", **kw):
    return ThesisPick(rev=make_rev(**kw), freshness=freshness, score=3)


def _st(text):
    sup = [Evidence(card_id=f"c{i}", canonical_url=f"https://p{i}.com/1",
                    publisher_id=f"p{i}.com", quote="q") for i in (1, 2)]
    return Statement(statement_id="s1", text=text, supporting=sup)


def test_render_boundary_label_and_no_numbers():
    sec = render_thesis_section([_pick()])
    assert "[배경 판" in sec and "사실 근거로 단정 인용하지" in sec
    assert "HBM 수요가 공급을 앞선다" in sec            # make_rev statement text
    assert quantity_literal(sec) == []                  # 수량 literal 0 (코드 검증)
    assert "0.1" not in sec and "revision_id" not in sec and "2026-07-21" not in sec
    assert render_thesis_section([]) == ""


def test_render_degraded_label_and_bad_statement_dropped():
    sec = render_thesis_section([
        _pick(freshness="degraded",
              statements=[_st("HBM 수요가 공급을 앞선다"), _st("가격 12% 급등")])])
    assert "입력 일부 노후" in sec
    assert "12%" not in sec                             # 주입 시점 이중 차단


def test_thesis_typed_facts_carry_metric_identity():
    facts = thesis_typed_facts([_pick()])
    assert facts[0].id == "thesis:hbm-tightness:memory_price_usd_per_gb"
    assert facts[0].metric == "memory_price_usd_per_gb"
    assert facts[0].observation_id == "x" * 16          # make_rev key_metrics 그대로
    assert facts[0].value == 0.1 and facts[0].period == "2026-07"


def _ctx(**kw):
    plan = PlanPacket(tier=2, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")
    da = DaPacket(unit_answers=[UnitAnswer(unit_id="q0", model="da_gpt",
                                           answer_text="a")])
    return _render_context(plan, da, None, None, None, None, [], None, **kw)


def test_synthesize_off_path_identical():
    base = _ctx()
    assert _ctx(thesis_section="") == base              # off 경로 동일 컨텍스트
    with_t = _ctx(thesis_section="[배경 판 — 섹터 현재 가설 (자동 합성·경향 참고)]\n- x")
    assert "[배경 판" in with_t and "[배경 판" not in base


def test_audit_evidence_helper_excludes_thesis_by_signature():
    from orchestrator import _audit_evidence
    params = inspect.signature(_audit_evidence).parameters
    assert "thesis_section" not in params and "thesis_picks" not in params
    from contracts import RaPacket
    texts, docs = _audit_evidence(RaPacket(), "", [], [], [])
    assert isinstance(texts, list) and isinstance(docs, dict)


def test_effective_toggle_resolved_from_run_overrides():
    # B2 — orchestrator 소스에 결정 시점이 하나뿐인지 (run override > settings)
    import inspect as _i
    import orchestrator
    src = _i.getsource(orchestrator.run_qa)
    assert 'get("disable_p23", settings.disable_p23)' in src
    assert src.count("effective_disable_p23 =") == 1    # run당 1회 결정
