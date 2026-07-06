"""M0 contracts — 직렬화 라운드트립·claim_key 정규화·이벤트 파싱 (LLM 불필요, CI 상시)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    AnswerRequest,
    AtomicClaim,
    BearCase,
    ClaimNorm,
    ClaimTable,
    ClaimVerdict,
    Conflict,
    CoverageEntry,
    DaPacket,
    EnvelopeMeta,
    FinalAnswer,
    FiscalPeriod,
    GateResult,
    LayerEvent,
    NeededEvidence,
    PlanPacket,
    PlanRef,
    PriceMacroPacket,
    RaPacket,
    RetryDirective,
    RiskPacket,
    SubQuestion,
    SynthInput,
    TickerCandidate,
    UnitAnswer,
    VerdictPacket,
    normalize_claim_key,
    parse_event,
)
from contracts.events import FinalEvent, HeartbeatEvent  # noqa: E402


def _sample_plan() -> PlanPacket:
    return PlanPacket(
        tier=2,
        original_question="삼성전기 올해 왜 올랐어?",
        standalone_question="삼성전기 2026년 주가 상승 원인은?",
        knowledge_cutoff="2026-07-02",
        tickers=[TickerCandidate(name="삼성전기", code="009150", yahoo_symbol="009150.KS")],
        sub_questions=[
            SubQuestion(id="q1", text="삼성전기 MLCC 업황은?", search_queries=["삼성전기 MLCC 2026"]),
            SubQuestion(id="q2", text="삼성전기 최대 고객사의 실적은?", depends_on="q1"),
        ],
        contrast_questions=["삼성전기 하락 요인은?"],
        needed_evidence=[
            NeededEvidence(entity="삼성전기", metric="2026 YTD 수익률", source_type="price"),
            NeededEvidence(entity="삼성전기", metric="최근 실적", period="2026Q1",
                           source_type="company", obtainability="public"),
        ],
        fiscal_periods=[FiscalPeriod(expression="올해", calendar_period="2026YTD",
                                     basis="calendar", resolved=True)],
    )


# ------------------------------------------------------------ claim_key

def test_claim_key_normalization():
    a = normalize_claim_key("삼성전자", "영업이익률", "2026Q1")
    b = normalize_claim_key("  삼성전자 ", "영업이익률  ", "2026q1")
    assert a == b == "삼성전자|영업이익률|2026q1"


def test_claim_key_autofill_and_provenance():
    c = AtomicClaim(
        id="c1", text="삼성전자 영업이익률은 10%", type="numeric", source="da_gpt",
        norm=ClaimNorm(entity="삼성전자", metric="영업이익률", period="2026Q1", value=10, unit="percent"),
    )
    assert c.claim_key == "삼성전자|영업이익률|2026q1"
    assert c.provenance == ["da_gpt"]  # 자동 채움


# ------------------------------------------------------------ roundtrips

def _roundtrip(model):
    cls = type(model)
    dumped = model.model_dump_json()
    parsed = cls.model_validate_json(dumped)
    assert parsed == model, cls.__name__
    return parsed


def test_plan_roundtrip_and_units():
    p = _roundtrip(_sample_plan())
    units = p.units()
    assert units[0] == ("q0", "삼성전기 2026년 주가 상승 원인은?")
    assert [u[0] for u in units] == ["q0", "q1", "q2"]
    assert p.plan_ref() == PlanRef(tier=2, knowledge_cutoff="2026-07-02")


def test_branch_packets_roundtrip():
    meta = EnvelopeMeta(round=0, plan_ref=PlanRef(tier=2, knowledge_cutoff="2026-07-02"))
    da = DaPacket(meta=meta, unit_answers=[
        UnitAnswer(unit_id="q0", model="da_gpt", answer_text="MLCC 회복 때문일 것"),
        UnitAnswer(unit_id="q0", model="da_fable", answer_text="로봇 신사업 기대"),
    ])
    ra = RaPacket(meta=meta, status="partial", truncated_units=["q2"],
                  collector_status={"x_search": "ok", "toss_trend": "degraded"})
    pm = PriceMacroPacket(meta=meta, macro={"KOSPI": {"last": 7648.09, "day_pct": -7.89}})
    for pkt in (da, ra, pm):
        _roundtrip(pkt)
    assert da.branch == "da" and ra.branch == "ra_ext" and pm.branch == "price_macro"


def test_verdict_and_reflect_roundtrip():
    v = VerdictPacket(
        meta=EnvelopeMeta(round=1),
        verdicts=[ClaimVerdict(claim_id="c1", final="unverified", judged_by="gpt",
                               gates=GateResult(g1="fail"))],
        retry_directives=[RetryDirective(kind="research", unit_id="q1",
                                         queries=["삼성전기 MLCC 가동률 2026"])],
    )
    v2 = _roundtrip(v)
    assert v2.round == 1  # meta.round 관통


def test_synth_input_carries_upstream():
    """직렬 캐리 규칙 — risk가 상류 패킷을 래핑."""
    si = SynthInput(
        verdict=VerdictPacket(),
        claim_table=ClaimTable(conflicts=[Conflict(claim_key="a|b|c", claim_ids=["c1", "c2"])]),
        risk=RiskPacket(applicable=True, bear_cases=[
            BearCase(text="경쟁 심화 시나리오"),  # supporting 없음 → scenario 기본
        ]),
    )
    si2 = _roundtrip(si)
    assert si2.risk.bear_cases[0].label == "scenario"


def test_final_answer_roundtrip():
    f = FinalAnswer(answer_markdown="# 답", degraded=["toss"], models_used=["fable-5", "gpt-5.5"])
    _roundtrip(f)


def test_strict_rejects_unknown_field():
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        PlanPacket.model_validate({**_sample_plan().model_dump(), "unknown_field": 1})


# ------------------------------------------------------------ events / api

def test_ndjson_event_roundtrip():
    ev = LayerEvent(name="plan", round=0, data={"tier": 2})
    line = ev.ndjson()
    assert line.endswith("\n")
    back = parse_event(line)
    assert isinstance(back, LayerEvent) and back.data["tier"] == 2

    assert isinstance(parse_event(HeartbeatEvent().ndjson()), HeartbeatEvent)
    fin = parse_event(FinalEvent(answer="답", meta={"rounds": 1}).ndjson())
    assert isinstance(fin, FinalEvent)


def test_answer_request():
    req = AnswerRequest(question="삼성전기 올해 왜 올랐어?", run_id="r1", chat_id="c1")
    assert req.mode == "qa" and req.think_level == 2
    # Node가 보낼 JSON 형태 그대로 파싱되는지
    raw = json.loads(req.model_dump_json())
    assert AnswerRequest.model_validate(raw) == req
