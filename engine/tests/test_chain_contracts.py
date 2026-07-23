# engine/tests/test_chain_contracts.py
import pytest
from pydantic import ValidationError

from app.settings import Settings
from contracts import (CHAIN_EDGES, CHAIN_SCHEMA_VERSION, LAYER_NAMES, SCHEMA_VERSION,
                       ChainEdge, ChainEdgeVerdict, ChainPacket, DraftAnswer,
                       EnvelopeMeta, PlanRef, PlaybookGateCheck, PlaybookGateOutcome,
                       TypedFact, VerdictPacket)


def test_global_schema_version_untouched_and_backcompat():
    assert SCHEMA_VERSION == 1                     # B1 — 전역 무변경
    assert CHAIN_SCHEMA_VERSION == 1
    old = VerdictPacket.model_validate({"schema_version": 1})   # 구 직렬화본
    assert old.chain_verdicts == []                             # 신규 필드 기본값


def test_typed_fact_metric_identity_fields():
    f = TypedFact(id="thesis:hbm-tightness:memory_price_usd_per_gb", value=0.1,
                  unit="USD/GB", metric="memory_price_usd_per_gb",
                  observation_id="a" * 16, period="2026-07")
    assert f.metric == "memory_price_usd_per_gb" and f.observation_id == "a" * 16
    assert TypedFact(id="x", value=1.0, unit="KRW").metric == ""  # 기존 생성부 무변경


def test_chain_edges_registry_nodes_match_judge_axes():
    from sector.judge import _VALID_AXIS
    nodes = {n for e in CHAIN_EDGES for n in e.split("->")}
    assert nodes == _VALID_AXIS                    # 드리프트 가드 (단일 진실원)
    assert "B->A" in CHAIN_EDGES and "A_prime->A" in CHAIN_EDGES and "C0->C" in CHAIN_EDGES
    assert "A->A" not in CHAIN_EDGES and "market->C" not in CHAIN_EDGES  # 곱집합 금지 (r1-B4)


def test_judge_emission_normalized_into_registry():
    from sector.judge import _DEFAULT_EDGE, _JudgeRow, _validate_row
    assert set(_DEFAULT_EDGE.values()) <= set(CHAIN_EDGES)
    row = _validate_row(_JudgeRow(idx=0, relevant=True, axis="A_prime",
                                  edge="A_prime → A"))          # 자유 문자열
    assert row.edge == "A_prime->A"                # 축 기반 결정적 폴백
    row2 = _validate_row(_JudgeRow(idx=0, relevant=True, axis="B", edge="B->A"))
    assert row2.edge == "B->A"                     # 실존 edge 보존


def test_extract_event_types_deterministic_and_opt_in():
    from sector.judge import _VALID_EVENT_TYPE
    from sector.queryplan import build_rule_plan, extract_event_types
    got = extract_event_types("SK하이닉스 HBM 증설로 공급 과잉 안 와?")
    assert "supply_signal" in got and set(got) <= _VALID_EVENT_TYPE
    assert extract_event_types("오늘 날씨 어때?") == []
    # 기본 off — 검색 경로(retrieve.py:126 event_type 스코어) 무변경 (v2 조정 1)
    assert build_rule_plan("HBM 증설 어때?").event_types == []
    rp = build_rule_plan("HBM 증설 어때?", include_event_types=True)
    assert "supply_signal" in rp.event_types       # thesis 스코어링 전용 opt-in


def test_is_memory_question_explicit_gate():
    from sector.queryplan import (build_rule_plan, is_memory_question,
                                  is_sector_question)

    def gate(q):
        return is_memory_question(q, build_rule_plan(q))

    # 음성 6건 — 전부 is_sector_question은 True (r2-2 경계 증명: 앞 4건은 엔티티,
    # 뒤 2건은 TSMC 엔티티+검색측 "웨이퍼" 토픽·삼성전자 엔티티). r3-2 추가 2건:
    # "웨이퍼" 단독·3사+"반도체" 일반어로는 게이트가 열리지 않는다
    negatives = ("엔비디아 CUDA 소프트웨어 매출 전망 어때?", "애플 아이폰 판매량 어때?",
                 "구글 광고 매출 성장 어때?", "삼성전자 갤럭시 스마트폰 신제품 어때?",
                 "TSMC 웨이퍼 가격 전망 어때?",
                 "삼성전자 파운드리 반도체 실적 어때?")
    for q in negatives:
        assert is_sector_question(q) and not gate(q)
    # 양성 — ① 토픽 키워드 ② segments ③ 3사+메모리 문맥
    assert gate("SK하이닉스 HBM 현물가 흐름 어때?")
    assert gate("낸드 업황 바닥 지났나?")
    assert gate("삼성전자 메모리 실적 어때?")
    assert not gate("")


def test_is_memory_question_latin_keyword_substring_false_positive_blocked():
    # 3부 T11 블로커5 — queryplan.py의 라틴 키워드 substring 매치가 "dram" in
    # "dramatically"처럼 무관 단어를 잡던 결함(codex repro). 다른 엔티티·토픽 없는
    # 순수 영문 문장은 메모리 게이트가 열리면 안 된다.
    from sector.queryplan import build_rule_plan, is_memory_question, is_sector_question

    def gate(q):
        return is_memory_question(q, build_rule_plan(q))

    q = "The result changed dramatically"
    assert not is_sector_question(q)
    assert not gate(q)


def test_chain_edge_value_space_and_kind():
    ChainEdge(edge_id="e0", edge="B->A", kind="observed", supporting_card_ids=["c1"])
    ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference")
    with pytest.raises(ValidationError):
        ChainEdge(edge_id="e2", edge="A->A", kind="observed")   # 미등록 edge
    with pytest.raises(ValidationError):
        ChainEdge(edge_id="e3", edge="B->A", kind="guessed")    # kind Literal


def test_chain_packet_meta_records_real_round_and_plan_ref():
    meta = EnvelopeMeta(round=1, plan_ref=PlanRef(tier=3, knowledge_cutoff="2026-07-21"))
    cp = ChainPacket(meta=meta, event="HBM 증설 발표", mechanism="공급 확대 기대",
                     edges=[ChainEdge(edge_id="e0", edge="A_prime->A", kind="inference")],
                     thesis_relation=[{"thesis_revision_id":
                                       "hbm-tightness@2026-07-21T00:00:00",
                                       "relation": "supports"}])
    assert cp.schema_version == CHAIN_SCHEMA_VERSION
    assert cp.meta.round == 1 and cp.meta.plan_ref.tier == 3   # 실제 라운드 (판정 3)
    with pytest.raises(ValidationError):
        ChainPacket(event="x", mechanism="y")       # meta 필수 — 기본 빈 meta 금지
    with pytest.raises(ValidationError):
        ChainPacket(meta=meta, event="x", mechanism="y",
                    thesis_relation=[{"thesis_revision_id": "t@1", "relation": "maybe"}])
    v = VerdictPacket(chain_verdicts=[ChainEdgeVerdict(edge_id="e0", grounded=False,
                                                       note="근거 없음")])
    assert v.chain_verdicts[0].grounded is False


def test_playbook_gate_contracts_and_validators():
    chk = PlaybookGateCheck(order=1, check="D램 가격 수준",
                            metric_id="memory_price_usd_per_gb",
                            selector={"meta_filter": {"category": "DRAM"}},
                            aggregation="last", comparator=">=", threshold=0.05,
                            unit="USD/GB", max_age_days=45)
    assert chk.window_days == 0 and chk.selector.series is None
    with pytest.raises(ValidationError):
        PlaybookGateCheck(order=1, check="x", metric_id="m", aggregation="median",
                          comparator=">=", threshold=1.0, unit="u", max_age_days=1)
    with pytest.raises(ValidationError):            # threshold 유한성 (권고 6)
        PlaybookGateCheck(order=1, check="x", metric_id="m", aggregation="last",
                          comparator=">=", threshold=float("nan"), unit="u",
                          max_age_days=1)
    out = PlaybookGateOutcome(order=1, metric_id="memory_price_usd_per_gb",
                              verdict="unavailable", unavailable_reason="no_metric")
    assert out.value is None
    with pytest.raises(ValidationError):            # verdict/reason 정합 (권고 6)
        PlaybookGateOutcome(order=1, metric_id="m", verdict="unavailable")
    with pytest.raises(ValidationError):
        PlaybookGateOutcome(order=1, metric_id="m", verdict="pass", value=None)


def test_layer_names_settings_default_and_scenario_flags():
    assert "thesis" in LAYER_NAMES and "chain" in LAYER_NAMES
    # env 오염 무관 — 인스턴스가 아니라 모델 필드 기본값 검사 (권고 3:
    # `DISABLE_P23=true pytest`에서도 통과해야 함)
    assert Settings.model_fields["disable_p23"].default is False
    assert Settings(disable_p23=True).disable_p23 is True
    assert DraftAnswer(answer_markdown="x").scenario_flags == []
