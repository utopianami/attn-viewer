from __future__ import annotations

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from time import perf_counter

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import Report
from sector.report_pipeline import alloc_report_slot, save_report


def _scenario(polarity: str, *, with_readability: bool) -> dict:
    impact = "benefit" if polarity == "positive" else "damage"
    beneficiaries = [
        {
            "name": "직접 섹터",
            "kind": "sector",
            "direction": "direct",
            "polarity": impact,
            "rationale": "직접 영향",
            "financials": "",
            "causalChain": "사건 → 직접 영향",
            "evidence": "카드 근거",
        },
        {
            "name": "SK하이닉스 (000660.KS)",
            "kind": "stock",
            "direction": "indirect",
            "polarity": impact,
            "rationale": "간접 영향",
            "financials": "memory_capex 000660.KS 7,865.37b원(-35.8% QoQ, 2026-03)",
            "causalChain": "사건 → 직접 영향 → 간접 영향",
            "evidence": "memory_capex 000660.KS 7,865.37b원(-35.8% QoQ, 2026-03)",
        },
    ]
    if with_readability:
        beneficiaries[0]["readerCopy"] = {
            "displayName": "직접 섹터",
            "rationale": "핵심 사건의 영향을 가장 먼저 받는 업종이다.",
            "causalChain": "핵심 사건이 수요를 바꾸고 직접 수혜 또는 피해로 이어진다.",
            "evidence": "카드에 수록된 업종 근거를 확인했다.",
            "financials": "",
        }
        beneficiaries[1]["readerCopy"] = {
            "displayName": "SK하이닉스",
            "rationale": "직접 영향이 공급망을 거쳐 SK하이닉스 실적에 간접적으로 번진다.",
            "causalChain": "핵심 사건에서 시작된 변화가 공급망을 거쳐 SK하이닉스에 전달된다.",
            "evidence": "SK하이닉스의 2026년 3월 분기 전사 설비투자는 7,865.37십억 원으로, 전분기보다 35.8% 감소했다.",
            "financials": "전사 설비투자 감소 폭은 전분기 대비 35.8%다.",
        }
    return {
        "polarity": polarity,
        "thesis": f"{polarity} 조건이 성립한다",
        "beneficiaries": beneficiaries,
    }


def _brief(axis: str) -> dict:
    return {
        "headline": f"{axis}를 한 문장으로 읽는다",
        "summary": "무슨 일이 있었고 왜 중요한지 짧게 설명한다.",
        "keyNumbers": [
            {"label": "핵심 변화", "value": "+12%", "context": "카드 원문 기준", "tone": "positive"}
        ],
        "flow": [
            {"label": "사건", "detail": "수요가 변했다", "tone": "neutral"},
            {"label": "전이", "detail": "관련 산업으로 번진다", "tone": "positive"},
        ],
        "scenarioGuide": [
            {"polarity": "positive", "condition": "수요가 이어진다", "outcome": "실적 기대가 높아진다"},
            {"polarity": "negative", "condition": "수요가 꺾인다", "outcome": "실적 기대가 낮아진다"},
        ],
        "watchlist": [
            {"label": "수요", "current": "현재 증가", "trigger": "증가세 유지 여부"}
        ],
        "bottomLine": "다음 수요 지표가 방향을 가른다.",
    }


def _topics_report(*, with_readability: bool = True) -> dict:
    generated_at = "2026-09-04T18:30:00+09:00"
    cards = []
    for axis, label, key, title in (
        ("macro", "거시", "macro", "금리 4.5%가 다음 방향을 가른다"),
        ("topic1", "AI 전력", "ai-power", "AI 전력 수요가 12% 늘었다"),
        ("topic2", "방산 수출", "defense", "방산 수주가 시장의 두 번째 축이다"),
    ):
        card = {
            "axis": axis,
            "label": label,
            "topicKey": key,
            "title": title,
            "phenomenon": f"{title}. 핵심 변화는 +12%다.",
            "deep_dive": {"topic": label, "conclusion": f"{label}의 다음 확인점이다."},
            "scenarios": [
                _scenario("positive", with_readability=with_readability),
                _scenario("negative", with_readability=with_readability),
            ],
            "watch_signals": [f"{label} 수요가 이어지는지 확인"],
            "sources": [],
            "error": "",
        }
        if with_readability:
            card["brief"] = _brief(axis)
        cards.append(card)
    report = {
        "id": "2026-09-04-6",
        "seq": 6,
        "generatedAt": generated_at,
        "title": cards[1]["title"],
        "window": {"from": "2026-09-04T06:30:00+09:00", "to": generated_at},
        "overview": "",
        "finalOpinion": {"text": "3축 카드 참조", "confidence": "낮"},
        "claims": [],
        "pipeline": {"stages": []},
        "diagnostics": {},
        "publish_status": "ok",
        "format": "axes",
        "axisModel": "topics_v1",
        "leadAxis": "topic1",
        "cards": cards,
    }
    if with_readability:
        report["readerModel"] = "brief_v1"
        report["editorial"] = {
            "label": "읽기 편집본",
            "baseReportId": report["id"],
            "baseGeneratedAt": generated_at,
            "editedAt": generated_at,
            "headline": "topic1를 한 문장으로 읽는다",
            "deck": "가장 중요한 변화와 다음 확인점을 먼저 읽는다.",
            "takeaways": [
                {"axis": axis, "title": label, "text": f"{label}의 핵심과 확인점이다."}
                for axis, label in (("macro", "거시"), ("topic1", "AI 전력"),
                                    ("topic2", "방산 수출"))
            ],
        }
    return report


def test_topics_report_preserves_typed_integrated_readability_layer():
    """회귀: Pydantic 직렬화가 자동 읽기 계층을 버리면 뷰어는 예전 원문 UI로 돌아간다."""
    report = Report.model_validate(_topics_report())

    assert report.editorial.baseReportId == report.id
    assert report.editorial.editedAt == report.generatedAt
    assert [item.axis for item in report.editorial.takeaways] == ["macro", "topic1", "topic2"]
    assert report.cards[0].brief.summary.startswith("무슨 일이")
    assert report.model_dump()["cards"][0]["brief"]["flow"][1]["label"] == "전이"
    assert report.cards[0].scenarios[0].beneficiaries[1].readerCopy.displayName == "SK하이닉스"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report["editorial"].__setitem__("headline", "가" * 101),
        lambda report: report["editorial"].__setitem__("takeaways", report["editorial"]["takeaways"][:2]),
        lambda report: report["cards"][0]["brief"].__setitem__("keyNumbers", []),
        lambda report: report["cards"][0]["brief"].__setitem__(
            "scenarioGuide", [report["cards"][0]["brief"]["scenarioGuide"][0]] * 2
        ),
        lambda report: report["cards"][0]["brief"].__setitem__("unexpected", "ignored"),
    ],
)
def test_readability_contract_rejects_shapes_the_viewer_cannot_render(mutation):
    """회귀: 길이·카디널리티가 OpenAPI와 어긋나면 자동 산출물을 발행하면 안 된다."""
    payload = _topics_report()
    mutation(payload)

    with pytest.raises(ValidationError):
        Report.model_validate(payload)


def test_historical_topics_report_without_readability_still_validates():
    """저장된 과거 topics_v1 JSON에는 읽기 계층이 없어도 하위 호환된다."""
    report = Report.model_validate(_topics_report(with_readability=False))

    assert report.editorial is None
    assert report.readerModel is None
    assert all(card.brief is None for card in report.cards)


def test_new_topics_report_without_readability_cannot_be_published(tmp_path):
    """과거 payload 조회 호환성이 새 발행의 읽기 계층 우회로가 되면 안 된다."""
    report = Report.model_validate(_topics_report(with_readability=False))
    seq, path, token = alloc_report_slot(tmp_path, "2026-09-04")
    report = report.model_copy(update={"id": f"2026-09-04-{seq}", "seq": seq})

    with pytest.raises(ValueError, match="topics_v1.*readerModel=brief_v1"):
        save_report(report, path, token)

    assert not path.exists()
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("missing", ["editorial", "brief", "readerCopy"])
def test_reader_model_makes_the_permanent_reading_layer_a_contract(missing):
    """새 generator marker가 붙으면 -5 같은 dense-only payload로 회귀할 수 없다."""
    payload = _topics_report()
    if missing == "editorial":
        payload.pop("editorial")
    elif missing == "brief":
        payload["cards"][1].pop("brief")
    else:
        payload["cards"][1]["scenarios"][0]["beneficiaries"][0].pop("readerCopy")

    with pytest.raises(ValidationError, match="readerModel|읽기|brief|editorial"):
        Report.model_validate(payload)


def test_reader_model_headline_must_belong_to_the_lead_axis():
    """화면 최상단 문구가 leadAxis와 다른 축을 대표하면 핵심 주제 선택이 무의미해진다."""
    payload = _topics_report()
    payload["editorial"]["headline"] = payload["cards"][2]["brief"]["headline"]

    with pytest.raises(ValidationError, match="headline|헤드라인|leadAxis"):
        Report.model_validate(payload)


@pytest.mark.parametrize(("qualified", "bare"), [
    ("VRT.N", "VRT"),
    ("DX-Y.NYB", "DX-Y"),
    ("SIEGn.DE", "SIEGn"),
    ("GHCPIY=ECI", "GHCPIY"),
    ("^GSPC", "GSPC"),
    ("9988.HK", "9988.HK"),
    (".SPX", "SPX"),
    (".IXIC", "IXIC"),
    (".SOX", "SOX"),
    (".KS11", "KS11"),
    ("US10YT=RR", "US10YT"),
    ("US2US10=TWEB", "US2US10"),
])
def test_reader_model_rejects_ticker_discovered_outside_beneficiary_names(
        qualified, bare):
    """출처에 명시된 종목·시장 코드가 brief의 bare root로 새면 안 된다."""
    payload = _topics_report()
    payload["cards"][1]["sources"] = [{
        "title": f"시장 데이터 {qualified} 흐름 발표",
        "url": "https://example.com/market-data",
    }]
    payload["cards"][1]["brief"]["summary"] = f"시장 데이터 {bare} 흐름을 확인한다."

    with pytest.raises(ValidationError, match="ticker|내부 표기|읽기"):
        Report.model_validate(payload)


@pytest.mark.parametrize("field", ["evidence", "financials"])
def test_reader_model_cannot_hide_populated_original_beneficiary_details(field):
    """원본에 있는 근거·재무 내용을 빈 readerCopy로 가리면 콘텐츠 불변이 아니다."""
    payload = _topics_report()
    beneficiary = payload["cards"][0]["scenarios"][0]["beneficiaries"][1]
    assert beneficiary[field].strip()
    beneficiary["readerCopy"][field] = ""

    with pytest.raises(ValidationError, match="readerCopy|근거|재무|읽기"):
        Report.model_validate(payload)


def test_reader_model_contract_cannot_rename_an_impact_subject():
    payload = _topics_report()
    payload["cards"][0]["scenarios"][0]["beneficiaries"][1]["readerCopy"][
        "displayName"
    ] = "테슬라"

    with pytest.raises(ValidationError, match="표시명|대상"):
        Report.model_validate(payload)


@pytest.mark.parametrize("mutation", [
    lambda report: report["cards"][0]["scenarios"][0].__setitem__("thesis", " \n "),
    lambda report: report["cards"][0]["scenarios"][0]["beneficiaries"][0].__setitem__(
        "name", " \n "),
    lambda report: (
        report["cards"][2].__setitem__("scenarios", []),
        report["cards"][2].__setitem__("error", " \n "),
    ),
])
def test_topics_report_rejects_whitespace_only_required_reader_inputs(mutation):
    payload = _topics_report()
    mutation(payload)

    with pytest.raises(ValidationError, match="보이는|시나리오|영향|오류"):
        Report.model_validate(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda copy: copy.__setitem__("displayName", "SK하이닉스 (000660.KS)"),
        lambda copy: copy.__setitem__("displayName", "SK하이닉스(000660.ks)"),
        lambda copy: copy.__setitem__("displayName", "memory_capex"),
        lambda copy: copy.__setitem__(
            "evidence", "memory_capex 000660.KS 7,865.37b원(-35.8% QoQ, 2026-03)"),
        lambda copy: copy.__setitem__("evidence", "램리서치 LRCX 실적 근거다."),
        lambda copy: copy.__setitem__("evidence", "NVIDIA (NVDA) 실적 근거다."),
        lambda copy: copy.__setitem__("evidence", "NewCo 종목코드 ZZZZ 공시 근거다."),
        lambda copy: copy.__setitem__("evidence", "버크셔 해서웨이 (BRK-B) 공시 근거다."),
        lambda copy: copy.__setitem__("evidence", "NewCo ZZZZ.O 공시 근거다."),
        lambda copy: copy.__setitem__("evidence", "Berkshire Hathaway BRK-B 공시 근거다."),
        lambda copy: copy.__setitem__("evidence", "엔비디아 NVDA.O 실적 근거다."),
        lambda copy: copy.__setitem__("evidence", "메타 META 실적 근거다."),
        lambda copy: copy.__setitem__("evidence", "유가 선물 LCOc1 움직임을 확인했다."),
        lambda copy: copy.__setitem__("evidence", "금 선물 GCcv1 움직임을 확인했다."),
        lambda copy: copy.__setitem__("financials", "매출은 12% qoq, 3% WoW 늘었다."),
        lambda copy: copy.__setitem__("financials", "매출은 12% qoq가 늘었다."),
        lambda copy: copy.__setitem__("rationale", "CAPEX가 늘고 backlog에 영향을 준다."),
        lambda copy: copy.__setitem__("rationale", "   "),
    ],
)
def test_reader_copy_contract_rejects_internal_identifiers_and_empty_prose(mutate):
    """읽기 필드는 티커·내부 metric·약어 또는 빈 문장으로 원시 뷰를 재현할 수 없다."""
    payload = _topics_report()
    copy = payload["cards"][0]["scenarios"][0]["beneficiaries"][1]["readerCopy"]
    mutate(copy)

    with pytest.raises(ValidationError, match="readerCopy|읽기|내부|ticker|공백"):
        Report.model_validate(payload)


@pytest.mark.parametrize("text", [
    "메타 META 실적이 시장을 이끈다.",
    "시놉시스 SNPS 실적이 시장을 이끈다.",
    "유가 선물 LCOc1 움직임을 먼저 본다.",
    "금 선물 GCcv1 움직임을 먼저 본다.",
])
def test_scan_first_copy_rejects_bare_equity_and_mixed_case_ric_tickers(text):
    """editorial/brief에도 소스 종목·RIC가 독자를 위한 문장으로 새면 안 된다."""
    payload = _topics_report()
    payload["cards"][1]["brief"]["summary"] = text

    with pytest.raises(ValidationError, match="읽기|내부|ticker|표시"):
        Report.model_validate(payload)


def test_reader_copy_keeps_explanatory_parenthesized_acronyms():
    """ticker 제거가 설명용 AI/GPU 괄호까지 무조건 삭제하지 않는다."""
    payload = _topics_report()
    payload["cards"][0]["scenarios"][0]["beneficiaries"][1]["readerCopy"]["evidence"] = (
        "인공지능(AI) 가속기(GPU) 수요를 회사 공시에서 확인했다."
    )

    Report.model_validate(payload)


def test_reader_copy_requires_canonical_uppercase_for_parenthesized_acronyms():
    """OpenAPI와 런타임 계약이 (AI)는 보존하고 (ai)는 그대로 발행하지 않는다."""
    payload = _topics_report()
    payload["cards"][0]["scenarios"][0]["beneficiaries"][1]["readerCopy"]["evidence"] = (
        "인공지능(ai) 수요를 확인했다."
    )

    with pytest.raises(ValidationError, match="ticker|괄호|읽기"):
        Report.model_validate(payload)


def test_fallback_canonicalizes_lowercase_parenthesized_acronyms():
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = "인공지능(ai) 수요를 확인했다."
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = layer.beneficiaryCopies["topic1:positive:0"].evidence
    assert "(AI)" in text
    assert "(ai)" not in text


@pytest.mark.parametrize(("raw_name", "leaked_ticker"), [
    ("NewCo (ZZZZ.O)", "ZZZZ"),
    ("Berkshire Hathaway (BRK-B)", "BRK"),
    ("삼성전자 (005930.KS)", "005930.KS"),
    ("ASML (ASML.AS)", "ASML.AS"),
])
def test_reader_copy_rejects_even_the_root_of_its_source_ticker(raw_name, leaked_ticker):
    """거래소 suffix만 빼서 원시 ticker를 노출하는 편집도 허용하지 않는다."""
    payload = _topics_report()
    beneficiary = payload["cards"][0]["scenarios"][0]["beneficiaries"][1]
    beneficiary["name"] = raw_name
    beneficiary["readerCopy"]["displayName"] = raw_name.split(" (")[0]
    beneficiary["readerCopy"]["evidence"] = f"회사 {leaked_ticker}의 공시를 확인했다."

    with pytest.raises(ValidationError, match="readerCopy|ticker|종목"):
        Report.model_validate(payload)


def test_historical_serialization_omits_absent_optional_readability_fields():
    """회귀: optional은 JSON null이 아니라 생략되어야 기존 OpenAPI 계약을 만족한다."""
    report = Report.model_validate(_topics_report(with_readability=False))
    dumped = report.model_dump()

    assert "editorial" not in dumped
    assert all("brief" not in card for card in dumped["cards"])


@pytest.mark.parametrize("field", ["baseGeneratedAt", "editedAt"])
def test_self_integrated_editorial_requires_report_generation_timestamp(field):
    """회귀: self base 자동 편집본은 별도 시각의 사후 overlay로 위장할 수 없다."""
    payload = _topics_report()
    payload["editorial"][field] = "2026-09-04T18:31:00+09:00"

    with pytest.raises(ValidationError, match="self-integrated"):
        Report.model_validate(payload)


def test_manual_editorial_overlay_keeps_distinct_base_and_later_edit_time_compatibility():
    """기존 -3 같은 별도 id 수동 편집본은 self-integrated 시간 규칙 대상이 아니다."""
    payload = _topics_report()
    payload.pop("readerModel")
    payload["editorial"].update({
        "baseReportId": "2026-09-04-1",
        "baseGeneratedAt": "2026-09-04T06:30:00+09:00",
        "editedAt": "2026-09-04T15:36:20+09:00",
    })

    report = Report.model_validate(payload)
    assert report.editorial.baseReportId == "2026-09-04-1"


def _draft_payload(*, invented: bool = False) -> dict:
    number = "99.9%" if invented else "+12%"
    return {
        "headline": "topic1를 한 문장으로 읽는다",
        "deck": "세 축의 변화와 다음 확인점을 먼저 읽는다.",
        "takeaways": [
            {"axis": axis, "title": label, "text": f"{label}의 핵심 변화는 {number}다."}
            for axis, label in (("macro", "거시"), ("topic1", "AI 전력"),
                                ("topic2", "방산 수출"))
        ],
        "briefs": [
            {"axis": axis, **_brief(axis), "summary": f"핵심 변화는 {number}다."}
            for axis in ("macro", "topic1", "topic2")
        ],
        "beneficiaryCopies": [
            {
                "axis": axis,
                "polarity": polarity,
                "index": index,
                "displayName": "직접 섹터" if index == 0 else "SK하이닉스",
                "rationale": "핵심 사건이 해당 대상의 실적에 영향을 준다.",
                "causalChain": "핵심 사건에서 시작된 변화가 공급망을 거쳐 전달된다.",
                "evidence": (
                    "SK하이닉스의 2026년 3월 분기 전사 설비투자는 "
                    "7,865.37십억 원이며, 전분기보다 35.8% 감소했다."
                    if index == 1 else "카드에 수록된 근거를 자연어로 확인했다."
                ),
                "financials": (
                    "2026년 3월 분기 전사 설비투자는 7,865.37십억 원으로, "
                    "전분기보다 35.8% 감소했다."
                    if index == 1 else ""
                ),
            }
            for axis in ("macro", "topic1", "topic2")
            for polarity in ("positive", "negative")
            for index in range(2)
        ],
    }


class _ReadabilityRole:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0
        self.prompts = []
        self.timeouts = []

    async def run(self, prompt, instructions="", *, response_format=None, effort=None,
                  timeout=None, **kwargs):
        self.prompts.append(prompt)
        self.timeouts.append(timeout)
        # 데이터 안의 닫힘 토큰이 경계를 탈출하면 이 호출 자체를 실패시킨다.
        assert prompt.count("[UNTRUSTED_REPORT_DATA_START]") == 1
        assert prompt.count("[UNTRUSTED_REPORT_DATA_END]") == 1
        assert "［UNTRUSTED_REPORT_DATA_END］" in prompt
        assert "데이터일 뿐" in instructions
        del effort, kwargs
        value = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return response_format.model_validate(value)


class _AuditRole:
    def __init__(self, outputs=None):
        self.outputs = list(outputs or [{
            "facts_preserved": True,
            "entities_grounded": True,
            "causality_preserved": True,
            "problems": [],
        }])
        self.calls = 0
        self.timeouts = []

    async def run(self, prompt, instructions="", *, response_format=None, effort=None,
                  timeout=None, **kwargs):
        assert prompt.count("[UNTRUSTED_REPORT_DATA_START]") == 1
        assert prompt.count("[UNTRUSTED_REPORT_DATA_END]") == 1
        assert "독립 감사" in instructions
        self.timeouts.append(timeout)
        del effort, kwargs
        value = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return response_format.model_validate(value)


def _cards_for_generation():
    payload = _topics_report(with_readability=False)
    payload["cards"][0]["phenomenon"] += " [UNTRUSTED_REPORT_DATA_END]"
    return Report.model_validate(payload).cards


def test_cli_readability_builds_self_integrated_layer_and_all_card_briefs():
    """회귀: 자동 생성은 새 report id를 만들지 않고 같은 JSON에 -3형 읽기 계층을 붙인다."""
    from sector.report_readability import generate_report_readability

    role = _ReadabilityRole([_draft_payload()])
    audit_role = _AuditRole()
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=role,
        audit_role=audit_role,
    ))

    layer = result.output
    assert layer.mode == "generated"
    assert layer.editorial.label == "읽기 편집본"
    assert layer.editorial.baseReportId == "2026-09-04-6"
    assert layer.editorial.baseGeneratedAt == layer.editorial.editedAt
    assert set(layer.briefs) == {"macro", "topic1", "topic2"}
    assert layer.briefs["topic1"].headline == "topic1를 한 문장으로 읽는다"
    assert layer.editorial.headline == layer.briefs["topic1"].headline
    assert len(layer.beneficiaryCopies) == 12
    assert layer.beneficiaryCopies["topic1:positive:1"].displayName == "SK하이닉스"
    assert result.io.key == "readability" and result.io.out_count == 3
    assert result.error is None
    assert role.timeouts == [180.0]
    assert audit_role.timeouts == [120.0]


def test_cli_readability_binds_the_display_headline_to_the_lead_brief():
    """모델이 다른 축의 대표 문구를 내도 실제 읽기 계층은 선택된 lead 축을 따른다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    draft["headline"] = draft["briefs"][2]["headline"]
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "generated"
    assert result.output.editorial.headline == result.output.briefs["topic1"].headline


@pytest.mark.parametrize(("qualified", "bare", "display"), [
    ("VRT.N", "VRT", "버티브"),
    ("DX-Y.NYB", "DX-Y", "달러지수"),
    ("SIEGn.DE", "SIEGn", "지멘스"),
    ("GHCPIY=ECI", "GHCPIY", "소비자물가 지표"),
    ("^GSPC", "GSPC", "S&P 500 지수"),
    ("9988.HK", "9988.HK", "알리바바"),
    (".SPX", "SPX", "S&P 500 지수"),
    (".IXIC", "IXIC", "나스닥 종합지수"),
    (".SOX", "SOX", "필라델피아 반도체지수"),
    (".KS11", "KS11", "코스피"),
    ("US10YT=RR", "US10YT", "미국 10년물 국채금리"),
    ("US2US10=TWEB", "US2US10", "미국 2년·10년 금리차"),
])
def test_cli_readability_rejects_bare_ticker_learned_from_card_sources(
        qualified, bare, display):
    """beneficiary 밖 출처의 코드도 읽기 표면의 금칙어 인벤토리에 들어간다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].title = f"{bare} 흐름이 달라졌다"
    cards[1].sources = [{
        "title": f"시장 데이터 {qualified} 흐름 발표",
        "url": "https://example.com/market-data",
    }]
    draft = _draft_payload()
    draft["briefs"][1]["headline"] = f"{bare} 흐름이 달라졌다"
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    serialized = json.dumps(result.output.model_dump(), ensure_ascii=False)
    assert result.output.mode == "fallback"
    assert bare.upper() not in serialized.upper()
    assert display in result.output.editorial.headline


def test_explicit_source_ticker_inventory_uses_only_strong_context():
    """원문 ticker 추출이 URL·내부 키·기술 세대·U.S.를 ticker로 오인하면 안 된다."""
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{
        "title": (
            "버티브 VRT.N, 달러 DX-Y.NYB, 지멘스 SIEGn.DE, "
            "물가 GHCPIY=ECI, 주가 ^GSPC·.SPX·.IXIC·.SOX·.KS11, "
            "알리바바 9988.HK, 금리 US10YT=RR·US2US10=TWEB, "
            "환율 KRW=KFTC, 원유 CL=F를 점검한다"
        ),
        "phenomenon": (
            "U.S.·NON-U.S.·Canada-U.S. 시장의 CXL2.0·PCIe5 전환과 "
            "DDR5=PC·DDR=D 규격, Y2=HBM 공장, SX8P=STOXX 지수, "
            "role=report_article 기록과 www.TickerPerks.com 주소"
        ),
        "url": "https://example.com/story?idxno=275775",
    }])

    assert replacements["VRT"] == "버티브"
    assert "VRT.N" in replacements and "CL=F" in replacements
    for full, root in [
        ("DX-Y.NYB", "DX-Y"),
        ("SIEGN.DE", "SIEGN"),
        ("GHCPIY=ECI", "GHCPIY"),
        ("^GSPC", "GSPC"),
        ("9988.HK", None),
        (".SPX", "SPX"),
        (".IXIC", "IXIC"),
        (".SOX", "SOX"),
        (".KS11", "KS11"),
        ("US10YT=RR", "US10YT"),
        ("US2US10=TWEB", "US2US10"),
    ]:
        assert full in replacements
        if root is not None:
            assert root in replacements
    assert not ({
        "U", "NON-U", "CANADA-U", "IDXNO", "ROLE", "PERKS", "CXL2", "PCIE5",
    } & set(replacements))
    # 제품 설명용 등호는 ticker 인벤토리에 넣지 않는다. 읽기 폴백의
    # 문장 자연화와 알려진 코드 치환이 각각 처리한다.
    assert "DDR5=PC" not in replacements
    assert "DDR=D" not in replacements
    assert "Y2=HBM" not in replacements
    assert replacements["SX8P=STOXX"] == "유럽 기술주 지수"
    assert "DDR5" not in replacements and "DDR" not in replacements
    assert "KRW=KFTC" in replacements and "KRW" not in replacements
    meta = explicit_source_ticker_replacements([{
        "evidence": "Meta Platforms Inc (META.O) 회사 공시를 확인했다.",
    }])
    assert "META.O" in meta and "META" not in meta


@pytest.mark.parametrize("phrase", [
    "U.S. 시장", "non-U.S. 매출", "ex-U.S. 매출", "Canada-U.S. 교역",
    "www.TickerPerks.com 혜택",
    "simplywall.st 자료", "ad-hoc-news.de 기사", "yna.co 보도",
    "zdnet.co.kr 기사", "CFI.co 자료", "investor.nvidia.com 공시",
    "META.com 공지", "example.com/foo_bar 원문", "example.com/news_2026.html 원문",
])
def test_reader_surface_preserves_geographic_abbreviations(phrase):
    """지리 약어·도메인을 ticker나 코드 지시문으로 오인하지 않는다."""
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(phrase) is False


@pytest.mark.parametrize("phrase", [
    "U.S. 시장", "non-U.S. 매출", "ex-U.S. 매출", "Canada-U.S. 교역",
    "www.TickerPerks.com 혜택",
    "simplywall.st 자료", "ad-hoc-news.de 기사", "yna.co 보도",
    "zdnet.co.kr 기사", "CFI.co 자료", "investor.nvidia.com 공시",
    "META.com 공지", "미국(U.S.) 시장", "로이터(Reuters.com) 보도",
    "example.com/foo_bar 원문", "example.com/news_2026.html 원문",
])
def test_fallback_preserves_geographic_abbreviations(phrase):
    """CLI 폴백의 ticker 제거도 정상 지리 약어·도메인을 삭제하지 않는다."""
    from sector.report_readability import _fallback_reader_text

    rendered = _fallback_reader_text(phrase, 160, "시장 흐름을 확인한다.")

    assert phrase in rendered


def test_source_code_naturalization_uses_surrounding_phrase_without_duplication():
    """실제 원문 문맥의 설명식·지수 RIC를 중복이나 붙은말 없이 읽게 바꾼다."""
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    raw = (
        "DDR4/DDR5=PC·서버용 D램 세대, DDR=D램 규격 세대, "
        "유럽 기술주 SX8P(SX8P=STOXX 유럽 기술업종), Siemens SIEGn.DE"
    )
    replacements = explicit_source_ticker_replacements([{"phenomenon": raw}])

    assert replace_source_tickers(raw, replacements) == (
        "DDR4/DDR5는 PC·서버용 D램 세대, DDR은 D램 규격 세대, "
        "유럽 기술주 지수, 지멘스"
    )

    wrapped = "지멘스(Siemens SIEGn.DE)가 투자한다"
    wrapped_replacements = explicit_source_ticker_replacements([{"title": wrapped}])
    assert replace_source_tickers(wrapped, wrapped_replacements) == "지멘스가 투자한다"


def test_memory_definition_is_not_learned_as_a_market_ticker():
    """제품 정의의 등호를 동적 ticker로 배워 정상 약어까지 금지하면 안 된다."""
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "HBM=D램이고 LPDDR=D램 계열이다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replacements == {}
    assert _fallback_reader_text(
        raw,
        180,
        "메모리 규격을 확인한다.",
        ticker_replacements=replacements,
    ) == "HBM은 D램이고 LPDDR은 D램 계열이다."


def test_known_hbm_factory_code_does_not_repeat_the_following_noun():
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(
        "Y2=HBM 공장 투자가 늘었다.", 180, "투자를 확인한다."
    ) == "신규 HBM 공장 투자가 늘었다."


def test_fallback_preserves_company_words_inside_source_domains():
    """회사 영문 별칭을 번역하더라도 출처 주소 자체는 바꾸지 않는다."""
    from sector.report_readability import _fallback_reader_text

    for raw in (
        "공시는 investor.nvidia.com에서 확인한다.",
        "공지 원문은 META.com에서 확인한다.",
        "자료는 amazon.com에서 확인한다.",
        "공시는 investor.NVIDIA.COM에서 확인한다.",
        "공지 원문은 META.COM에서 확인한다.",
        "자료는 AMAZON.COM에서 확인한다.",
    ):
        assert _fallback_reader_text(raw, 180, "출처를 확인한다.") == raw


@pytest.mark.parametrize("raw", [
    "J.P. Morgan은 전망을 높였다.",
    "U.K. 시장은 강세였다.",
    "U.N. 회의가 열렸다.",
])
def test_repeated_initials_are_not_mistaken_for_exchange_tickers(raw):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is False
    assert _fallback_reader_text(raw, 180, "시장 흐름을 확인한다.") == raw


def test_title_case_company_wordmark_is_readable_prose_not_a_bare_ticker():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    raw = "AMD·Meta·OpenAI 투자가 늘었다."
    assert reader_text_problem(raw) is False
    assert _fallback_reader_text(raw, 180, "투자를 확인한다.") == raw


@pytest.mark.parametrize(("raw", "expected"), [
    ("idx=25 장전 버전", "장전 버전."),
    ("role=report_article 장전 버전", "장전 버전."),
    ("idx=33/34 동일 이벤트", "동일 이벤트."),
    ("idx=6,7 장전", "장전."),
    ("idx=32·33 비교", "비교."),
    ("(idx=21,26 유사) 시장은 변했다.", "시장은 변했다."),
    ("idx=25/26 확인", "확인."),
    ("EPS=3.50달러로 집계됐다.", "주당순이익은 3.50달러로 집계됐다."),
])
def test_fallback_naturalizes_internal_assignments(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is True
    rendered = _fallback_reader_text(raw, 180, "시장 지표를 확인한다.")
    assert rendered == expected
    assert reader_text_problem(rendered) is False


@pytest.mark.parametrize(("raw", "expected"), [
    ("HBM=고대역폭메모리 수요가 늘었다.", "HBM은 고대역폭 메모리 수요가 늘었다."),
    ("AI=인공지능 투자가 늘었다.", "AI는 인공지능 투자가 늘었다."),
    ("CAPEX=설비투자", "설비투자."),
    ("QoQ=전분기 대비", "전분기 대비."),
    ("EPS=주당순이익", "주당순이익."),
])
def test_fallback_naturalizes_korean_term_definitions(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is True
    rendered = _fallback_reader_text(raw, 180, "용어를 확인한다.")
    assert rendered == expected
    assert reader_text_problem(rendered) is False


@pytest.mark.parametrize(("raw", "expected"), [
    ("MOU=양해각서를 체결했다.", "MOU, 즉 양해각서를 체결했다."),
    ("KEYTRUDA=면역항암제 매출이 늘었다.", "KEYTRUDA, 즉 면역항암제 매출이 늘었다."),
])
def test_generic_korean_definition_avoids_guessing_acronym_particles(raw, expected):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 180, "용어를 확인한다.") == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("ROE=15%를 기록했다.", "자기자본이익률은 15%를 기록했다."),
    ("GPU=H100 공급이 늘었다.", "GPU, 즉 H100 공급이 늘었다."),
    ("CAPEX=1200억 원이다.", "설비투자는 1200억 원이다."),
])
def test_fallback_naturalizes_generic_ascii_assignments_without_raising(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    rendered = _fallback_reader_text(raw, 220, "지표를 확인한다.")
    assert rendered == expected
    assert reader_text_problem(rendered) is False


@pytest.mark.parametrize(("raw", "expected"), [
    ("코스피 3,187로 마감했다.", "코스피 3,187로 마감했다."),
    ("PER 12.7로 낮아졌다.", "PER 12.7로 낮아졌다."),
    ("지수는 3,180으로 마감했다.", "지수는 3,180으로 마감했다."),
])
def test_numeric_particle_repair_respects_rieul_digits(raw, expected):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 220, "지수를 확인한다.") == expected


@pytest.mark.parametrize("raw", [
    "메타 메타버스 사업 손실이 늘었다.",
    "애플 애플리케이션 생태계가 커졌다.",
    "인텔 인텔리전스 수요가 늘었다.",
])
def test_repeated_name_collapse_does_not_delete_compound_words(raw):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 220, "기업을 확인한다.") == raw


@pytest.mark.parametrize(("raw", "expected"), [
    ("다우지수 .DJI는 624포인트 상승했다.", "다우지수는 624포인트 상승했다."),
    ("닛케이지수 .N225는 내렸다.", "닛케이지수는 내렸다."),
    ("대만 지수 .TWII는 올랐다.", "대만 지수는 올랐다."),
    ("필라델피아 반도체 지수(.SOX)는 상승했다.", "필라델피아 반도체 지수는 상승했다."),
    ("나스닥 지수 .IXIC은 올랐다.", "나스닥 지수는 올랐다."),
])
def test_end_to_end_fallback_preserves_label_before_leading_dot_index(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 180, "지수 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("창업판 가격지수(.CNT)는 올랐다.", "창업판 가격지수는 올랐다."),
    ("CSI300 통신서비스 지수(.CSI000916)는 내렸다.",
     "CSI300 통신서비스 지수는 내렸다."),
    ("타이베이 증시<.TWII>는 올랐다.", "타이베이 증시는 올랐다."),
    ("CSI300 지수(.CSI300)는 올랐다.", "CSI300 지수는 올랐다."),
    ("반도체 관련주(.CSIH30184)는 올랐다.", "반도체 관련주는 올랐다."),
    ("비철금속 기업(.CSISNMIM)은 올랐다.", "비철금속 기업은 올랐다."),
    ("필수소비재(.CSICS)는 내렸다.", "필수소비재는 내렸다."),
    ("필수소비재(.CSICS) 및 금융(.CSI300FS)과 비교했다.",
     "필수소비재 및 금융과 비교했다."),
    ("시장 .MIAPJ0000PUS 흐름", "시장 해당 시장 지표 흐름."),
])
def test_unknown_leading_dot_index_uses_readable_label_or_generic(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert replacements
    assert _fallback_reader_text(
        raw, 220, "지수 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize("raw", [
    ".NET 플랫폼 수요가 늘었다.",
    "닷넷(.NET) 플랫폼 수요가 늘었다.",
    "\"제시\".LS증권이 전망했다.",
])
def test_dot_technology_and_glued_publisher_names_are_not_market_codes(raw):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is False
    assert _fallback_reader_text(raw, 220, "문장을 확인한다.") == raw


@pytest.mark.parametrize(("raw", "expected"), [
    ("달러 인덱스 <=USD>는 올랐다.", "달러 인덱스는 올랐다."),
    ("달러화 약세<=USD>가 이어졌다.", "달러화 약세가 이어졌다."),
    ("원화 <KRW=>는 강세였다.", "원화는 강세였다."),
    ("필리핀 페소 <PHP=>는 약세였다.", "필리핀 페소는 약세였다."),
])
def test_empty_market_wrappers_keep_the_existing_readable_label(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert replacements
    assert _fallback_reader_text(
        raw, 220, "환율을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("시장이 올랐다. .N", "시장이 올랐다."),
    ("시장이 올랐다.[.N][US/]", "시장이 올랐다."),
    ("[MKTS/GLOB] 시장이 올랐다.[O/R]", "시장이 올랐다."),
    ("[TOP/CMTY] 원자재 가격이 올랐다.", "원자재 가격이 올랐다."),
])
def test_reuters_routing_metadata_is_removed_from_reader_copy(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is True
    rendered = _fallback_reader_text(raw, 220, "시장을 확인한다.")
    assert rendered == expected
    assert reader_text_problem(rendered) is False


def test_fallback_naturalizes_known_ticker_before_hyphenated_company_name():
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(
        "NVDA-Groq 계약은 200억 달러다.", 180, "계약을 확인한다."
    ) == "엔비디아-Groq 계약은 200억 달러다."


@pytest.mark.parametrize(("source", "prose"), [
    ("온세미 ON.O는 매출을 발표했다.", "Demand was on track."),
    ("서비스나우 NOW.N은 실적을 발표했다.", "Now demand rises."),
    ("팀 TEAM.O는 계약을 발표했다.", "The team expanded."),
])
def test_dynamic_bare_tickers_do_not_delete_case_distinct_english_words(source, prose):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        reader_surface_problem,
    )

    replacements = explicit_source_ticker_replacements([{"title": source}])

    assert _fallback_reader_text(
        prose, 180, "설명을 확인한다.", ticker_replacements=replacements
    ) == prose
    assert reader_surface_problem(prose, forbidden_tokens=replacements) is False


def test_known_one_letter_ric_is_not_hidden_as_a_person_initialism():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        reader_text_problem,
    )

    raw = "Dominion Energy D.N."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replacements == {"D.N": "도미니언 에너지"}
    assert reader_text_problem(raw) is True
    assert _fallback_reader_text(
        raw, 180, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == "Dominion Energy."


@pytest.mark.parametrize(("raw", "expected"), [
    ("기업 $X 상승", "기업 US스틸 상승."),
    ("기업 $Z 상승", "기업 해당 기업 상승."),
])
def test_every_one_letter_cashtag_has_a_safe_reader_fallback(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert any(token.startswith("$") for token in replacements)
    assert _fallback_reader_text(
        raw, 180, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_paired_algebra_placeholders_are_not_rewritten_as_stock_tickers():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "단가 효과 $X, 용량 증설 $Y를 각각 계산한다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert "$X" not in replacements and "$Y" not in replacements
    assert _fallback_reader_text(
        raw, 220, "효과를 계산한다.", ticker_replacements=replacements
    ) == "단가 효과 변수 X, 용량 증설 변수 Y를 각각 계산한다."


@pytest.mark.parametrize(("raw", "expected"), [
    ("해운업종 ISHIP.T은 2.91% 상승했다.", "해운업종은 2.91% 상승했다."),
    ("애플의 APPL.O 중국산 메모리 문제", "애플의 중국산 메모리 문제."),
    ("아틀라시안TEAM.O은 올랐다.", "아틀라시안은 올랐다."),
    ("마이크로칩 TechMCHP.O은 올랐다.", "마이크로칩 테크놀로지는 올랐다."),
    ("관련 기업 보도: 9984.T", "관련 기업 보도: 소프트뱅크."),
    ("RHM.DE는 라인메탈의 코드다.", "라인메탈은 라인메탈의 코드다."),
    ("〔근거: 블룸버그·9432.T〕", "〔근거: 블룸버그·NTT〕"),
        ("모건스탠리 전망 $MS", "모건스탠리 전망."),
])
def test_actual_source_company_and_index_codes_have_readable_identity(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 300, "관련 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_dollar_ticker_vendor_annotations_do_not_repeat_company_names():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "파운드리(UMC 2303/$UMC·GlobalFoundries $GFS)의 투자"
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw, 300, "파운드리 투자를 확인한다.", ticker_replacements=replacements
    ) == "파운드리(UMC·GlobalFoundries)의 투자."


def test_one_letter_stock_ticker_is_only_forbidden_in_strong_context():
    from sector.report_reader_rules import (
        reader_surface_problem,
        replace_source_tickers,
        source_ticker_replacements,
    )

    replacements = source_ticker_replacements([("포드 (F)", "stock")])

    assert replacements == {"(F)": "포드"}
    assert replace_source_tickers(
        "포드 (F) 실적과 포드 F 판매, F-150 및 비타민 F 수요", replacements
    ) == "포드 실적과 포드 판매, F-150 및 비타민 F 수요"
    assert reader_surface_problem(
        "포드 (F) 실적", forbidden_tokens=replacements) is True
    assert reader_surface_problem(
        "F-150 및 비타민 F 수요", forbidden_tokens=replacements) is False


@pytest.mark.parametrize(("raw_name", "raw", "expected"), [
    ("Micron Technology (MU)", "Micron Technology (MU)는 성장했다.",
     "마이크론은 성장했다."),
    ("C3.ai (AI)", "C3.ai (AI)는 성장했다.", "C3.ai는 성장했다."),
    ("TKO Group Holdings (TKO)", "TKO Group Holdings (TKO)는 성장했다.",
     "TKO Group Holdings는 성장했다."),
])
def test_beneficiary_wrapper_is_removed_once_without_spacing_or_duplication(
        raw_name, raw, expected):
    from sector.report_readability import _plain_reader_sentence
    from sector.report_reader_rules import reader_identity, source_ticker_replacements

    identity = reader_identity(raw_name, kind="stock")
    replacements = source_ticker_replacements([(raw_name, "stock")])
    assert _plain_reader_sentence(
        raw, display_name=identity.display_name, ticker=identity.ticker,
        fallback="기업 흐름을 확인한다.", limit=220,
        ticker_replacements=replacements,
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("엔비디아(NVDA) 실적이 좋다.", "엔비디아 실적이 좋다."),
    ("엔비디아(NVIDIA) 실적이 좋다.", "엔비디아 실적이 좋다."),
    ("마이크론(Micron) 매출이 늘었다.", "마이크론 매출이 늘었다."),
    ("메타(META) 투자가 늘었다.", "메타 투자가 늘었다."),
])
def test_no_space_known_company_wrapper_does_not_duplicate_the_name(raw, expected):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 220, "기업을 확인한다.") == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("세일즈포스(CRM.N) 및 시놉시스 SNPS.O는 올랐다.",
     "세일즈포스 및 시놉시스는 올랐다."),
    ("Amazon.com AMZN.O 및 Alphabet의 GOOGL.O Google 투자가 늘었다.",
     "아마존 및 알파벳의 구글 투자가 늘었다."),
    ("구글(GOOGL)이 투자했다.", "구글이 투자했다."),
    ("엔비디아(NVDA, AI 가속기 기업)가 투자했다.",
     "엔비디아(AI 가속기 기업)가 투자했다."),
])
def test_existing_company_label_wins_over_adjacent_ticker_annotation(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("오늘 강세인 ABCD.O는 상승했다.", "오늘 강세인 해당 기업은 상승했다."),
    ("미국 ABCD.O는 상승했다.", "미국 해당 기업은 상승했다."),
    ("투자자들은 ABCD.O를 매수했다.", "투자자들은 해당 기업을 매수했다."),
])
def test_unknown_ric_does_not_treat_an_adjacent_common_noun_as_company(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize("raw", [
    "기업은 CRM 시스템을 도입했다.",
    "CRM(Customer Relationship Management)을 개선했다.",
])
def test_crm_industry_term_is_not_rewritten_as_salesforce(raw):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 280, "기업 흐름을 확인한다.") == raw


def test_crm_term_stays_intact_even_when_report_sources_include_salesforce_ric():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([
        {"title": "세일즈포스 CRM.N은 실적을 발표했다."},
        {"title": "기업은 CRM 시스템을 도입했다."},
    ])

    assert replacements["CRM.N"] == "세일즈포스"
    assert "CRM" not in replacements
    assert _fallback_reader_text(
        "기업은 CRM 시스템을 도입했다.",
        280,
        "기업 흐름을 확인한다.",
        ticker_replacements=replacements,
    ) == "기업은 CRM 시스템을 도입했다."


@pytest.mark.parametrize(("raw", "expected"), [
    (
        "마벨 테크놀로지(Marvell Technology) MRVL.O는 성장했다.",
        "마벨 테크놀로지는 성장했다.",
    ),
    (
        "웨스턴디지털WDC.O와 샌디스크SNDK.O가 공급했다.",
        "웨스턴디지털과 샌디스크가 공급했다.",
    ),
    ("중신궈지(SMIC) 0981.HK는 증설했다.", "중신궈지는 증설했다."),
    ("램 리서치LRCX.O와 KLAKLAC.O가 올랐다.", "램 리서치와 KLA가 올랐다."),
    (
        "엔비디아(Nvidia Corporation) NVDA.O는 발표했다.",
        "엔비디아는 발표했다.",
    ),
])
def test_corpus_company_label_structures_remove_only_the_attached_ric(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("매출(전년 대비) ABCD.O는 늘었다.", "매출(전년 대비) 해당 기업은 늘었다."),
    ("가격(AI) ABCD.O는 올랐다.", "가격(AI) 해당 기업은 올랐다."),
])
def test_non_company_parentheses_do_not_absorb_a_following_unknown_ric(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("주가는ABCD.O가 올랐다.", "주가는 해당 기업이 올랐다."),
    ("미국은ABCD.O를 제재했다.", "미국은 해당 기업을 제재했다."),
    ("쇼피파이SHOP.TO가 올랐다.", "쇼피파이가 올랐다."),
    ("해운업종UNKNOWN.O가 올랐다.", "해운업종 해당 기업이 올랐다."),
])
def test_glued_ric_after_a_sentence_fragment_keeps_the_company_identity(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("MAGS.P는 하락했다.", "매그니피센트 세븐 ETF는 하락했다."),
    ("ABX.TO는 하락했다.", "해당 기업은 하락했다."),
    ("DBX.O는 하락했다.", "해당 기업은 하락했다."),
    ("OREP.PA는 하락했다.", "해당 기업은 하락했다."),
])
def test_full_ticker_is_not_split_at_a_known_suffix_root(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    code = raw.split("는", 1)[0]
    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert code in replacements
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("Reuters.com NVDA.O는 실적을 발표했다.",
     "Reuters.com 엔비디아는 실적을 발표했다."),
    ("Example.Co AMZN.O는 상승했다.", "Example.Co 아마존은 상승했다."),
    ("Amazon.com AMZN.O는 상승했다.", "아마존은 상승했다."),
])
def test_unrelated_domain_does_not_absorb_a_following_known_ric(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_concatenated_known_domain_alias_and_ric_is_one_company():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "AMAZON.COMAMZN.O Amazon.com은 투자했다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert "COMAMZN.O" not in replacements
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == "아마존은 투자했다."


def test_unrelated_english_parenthesis_does_not_absorb_unknown_ric():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "보고서(New York) UNKNOWN.O가 공개됐다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == "보고서(New York) 해당 기업이 공개됐다."


@pytest.mark.parametrize(("raw", "expected", "display"), [
    ("버라이즌(Verizon) VZ.N은 투자했다.",
     "버라이즌은 투자했다.", "버라이즌"),
    ("케이던스 디자인 시스템즈(Cadence Design Systems) CDNS.O는 올랐다.",
     "케이던스 디자인 시스템즈는 올랐다.", "Cadence Design Systems"),
    ("선전 롱시스 일렉트로닉스(Shenzhen Longsys Electronics) 301308.SZ는 증설했다.",
     "선전 롱시스 일렉트로닉스는 증설했다.",
     "Shenzhen Longsys Electronics"),
])
def test_bilingual_company_gloss_teaches_unknown_ric_identity(raw, expected, display):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{
        "title": raw,
        "raw_quote": raw,
    }])
    qualified = next(token for token in replacements if "." in token)

    assert replacements[qualified] == display
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("데이터 센터 기업 IREN IREN.O는 계약했다.",
     "데이터 센터 기업 IREN은 계약했다."),
    ("글로벌 지수 제공업체 MSCI(MSCI.N)는 발표했다.",
     "글로벌 지수 제공업체 MSCI는 발표했다."),
])
def test_unknown_ric_does_not_erase_an_existing_company_wordmark(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert not any(
        token in {"IREN", "MSCI"} and display == "해당 기업"
        for token, display in replacements.items()
    )
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_unknown_bare_exchange_symbol_does_not_erase_a_company_wordmark():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    sources = [{
        "title": "AZIO AI는 서버를 공급한다.",
        "raw_quote": "AZIO AI Holdings, Inc.(Nasdaq: AZIO)는 계약을 확대했다.",
    }]
    replacements = explicit_source_ticker_replacements(sources)

    assert "AZIO" not in replacements
    assert _fallback_reader_text(
        sources[0]["title"], 280, "기업 흐름을 확인한다.",
        ticker_replacements=replacements,
    ) == sources[0]["title"]


@pytest.mark.parametrize(("raw", "expected", "display"), [
    ("MasTec MTZ.N은 수주를 발표했다.", "MasTec은 수주를 발표했다.", "MasTec"),
    ("Klarna Group KLAR.N은 상장했다.", "Klarna Group은 상장했다.",
     "Klarna"),
    ("뉴욕타임스 NYT.N은 보도했다.", "뉴욕타임스는 보도했다.", "뉴욕타임스"),
    ("넥스트에라 에너지 NEE.N은 증설했다.",
     "넥스트에라 에너지는 증설했다.", "넥스트에라 에너지"),
])
def test_readable_adjacent_company_label_teaches_unknown_full_ric(
        raw, expected, display):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{
        "title": raw,
        "raw_quote": raw,
    }])
    qualified = next(token for token in replacements if "." in token)

    assert replacements[qualified] == display
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("리오틴토(Rio Tinto) RIO.AX, RIO.L는 투자했다.",
     "리오틴토는 투자했다."),
    ("비야디(BYD) 0285.HK, 002594.SZ의 판매가 늘었다.",
     "비야디의 판매가 늘었다."),
    ("쇼피지(Shopify) SHOP.TO, SHOP.O는 투자했다.",
     "쇼피지는 투자했다."),
])
def test_alternate_listing_code_sequence_is_one_company_annotation(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{
        "title": raw,
        "raw_quote": raw,
    }])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("징둥닷컴(JD.com) 9618.HK, JD.O가 발표했다.",
     "징둥닷컴이 발표했다."),
    ("중국건설은행(China Construction Bank Corp)601939.SS, 0939.HK는 발표했다.",
     "중국건설은행은 발표했다."),
])
def test_known_bilingual_alternate_listing_does_not_repeat_the_english_alias(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_malformed_repeated_wordmark_and_numeric_ric_keep_company_identity():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "AlphabetGOOGL.O, ASMLASML.AS 및 TSMC TSMC2330.TW는 투자했다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == "알파벳, ASML 및 TSMC는 투자했다."


def test_taiwan_semiconductor_bilingual_wrapper_and_ric_are_one_identity():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "대만 반도체 제조사(Taiwan Semiconductor Manufacturing Co) <2330.TW>는 발표했다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == "대만 반도체 제조사는 발표했다."


@pytest.mark.parametrize(("raw", "expected"), [
    ("United Parcel Service UPS.N는 발표했다.",
     "United Parcel Service는 발표했다."),
    ("스텔란티스 STLAM.MI, STLA.N의 주가는 하락했다.",
     "스텔란티스의 주가는 하락했다."),
    ("제너럴 모터스 GM.N의 주가는 하락했다.",
     "제너럴 모터스의 주가는 하락했다."),
    ("도요타 7203.T, TM.N 주가는 하락했다.",
     "도요타 주가는 하락했다."),
    ("혼다 7267.T, HMC.N 주가는 하락했다.",
     "혼다 주가는 하락했다."),
])
def test_actual_company_listing_annotations_collapse_to_one_readable_name(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_adjacent_readable_index_names_do_not_gain_generic_placeholders():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = ("유럽 기술주 .SX8P는 상승했고 MSCI All Country World Index "
           ".MIWO00000PUS는 보합이었다.")
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw, 280, "시장 흐름을 확인한다.", ticker_replacements=replacements
    ) == "유럽 기술주는 상승했고 MSCI All Country World Index는 보합이었다."


@pytest.mark.parametrize(("raw", "expected"), [
    ("아마존닷컴 AMZN.O는 투자했다.", "아마존닷컴은 투자했다."),
    ("Meta META.O는 투자했다.", "Meta는 투자했다."),
    ("마이크론 테크놀로지 MU.O는 증설했다.",
     "마이크론 테크놀로지는 증설했다."),
    ("웨스턴 디지털 WDC.O는 증설했다.",
     "웨스턴 디지털은 증설했다."),
    ("네이버 035420.KS는 발표했다.", "네이버는 발표했다."),
    ("Amazon Web Services AMZN.O는 투자했다.",
     "아마존웹서비스는 투자했다."),
])
def test_existing_company_or_business_name_wins_over_its_routing_code(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("S&P 500 정보기술 부문 .SPLRCT는 상승했다.",
     "S&P 500 정보기술 부문은 상승했다."),
    ("S&P 500 기술 섹터 .SPLRCT는 상승했다.",
     "S&P 500 기술 섹터는 상승했다."),
    ("STAR50 지수(.STAR50)는 상승했다.", "STAR50 지수는 상승했다."),
])
def test_existing_index_label_wins_over_its_routing_code(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "시장 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("벤치마크 코스피(KOSPI) .KS11 지수는 상승했다.",
     "벤치마크 코스피 지수는 상승했다."),
    ("EM 아시아 IT 지수(<.MIMS0IT00PUS>)는 급등했다.",
     "EM 아시아 IT 지수는 급등했다."),
    ("중국 CSI 5G 통신 지수(<.CSI931079>)는 급등했다.",
     "중국 CSI 5G 통신 지수는 급등했다."),
    ("Nikkei .N225 지수는 상승했고 Topix .TOPX 지수는 보합이었다.",
     "Nikkei 지수는 상승했고 Topix 지수는 보합이었다."),
])
def test_descriptive_index_label_wins_over_nested_or_adjacent_market_code(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"raw_quote": raw}])
    assert _fallback_reader_text(
        raw, 320, "시장 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_bare_index_acronym_does_not_repeat_its_index_suffix():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "SOX 지수가 오르면 관련주가 뒤따른다."
    replacements = explicit_source_ticker_replacements([{
        "title": "필라델피아 반도체 지수 .SOX는 상승했다.",
        "raw_quote": raw,
    }])
    assert _fallback_reader_text(
        raw, 280, "시장 흐름을 확인한다.", ticker_replacements=replacements
    ) == "필라델피아 반도체지수가 오르면 관련주가 뒤따른다."


@pytest.mark.parametrize(("raw", "expected"), [
    ("대만 달러(<TWD=TP>)는 0.2% 상승했다.",
     "대만 달러는 0.2% 상승했다."),
    ("필리핀 페소(<PHP=>)와 말레이시아 링깃(<MYR=>)은 각각 0.2% 하락했다.",
     "필리핀 페소와 말레이시아 링깃은 각각 0.2% 하락했다."),
    ("한국 원화(<KRW=KFTC>)는 0.1% 하락했다.",
     "한국 원화는 0.1% 하락했다."),
])
def test_readable_currency_label_wins_over_wrapped_market_code(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"raw_quote": raw}])
    assert _fallback_reader_text(
        raw, 320, "환율 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("메타가 신제품을 발표. $META.", "메타가 신제품을 발표."),
    ("Microsoft (NASDAQ:MSFT | MSFT Price Prediction)", "마이크로소프트."),
    ("NVIDIA’s (NVDA) Infrastructure Narrative",
     "엔비디아의 Infrastructure Narrative."),
    ("CXMT Corp's 688825.SS 주식", "CXMT Corp's 주식."),
    ("Meta Platforms, Inc. META.O: META CEO", "메타: 메타 CEO."),
    ("엔비디아와 아마존 웹 서비스(Amazon Web Services)가 협력했다.",
     "엔비디아와 아마존 웹 서비스가 협력했다."),
    ("Micron Technology (MU.", "마이크론."),
    ("서비스나우(ServiceNow, NOW.N)는 발표했다.",
     "서비스나우는 발표했다."),
    ("호가되었으며,", "호가되었으며."),
])
def test_actual_source_metadata_is_removed_as_one_readable_unit(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"raw_quote": raw}])
    assert _fallback_reader_text(
        raw, 400, "관련 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("샌디스크 SNDK.", "샌디스크"),
    ("코어WeaveCRWV.O는 계약했다.", "코어위브는 계약했다"),
    ("MU Stock - Micron Technology", "마이크론 주식"),
    ("Microsoft Stock (MSFT)", "마이크로소프트 주식"),
    ("Micron Technology Inc (MU)", "마이크론"),
])
def test_malformed_vendor_headings_are_rewritten_as_single_readable_names(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", sentence=False,
        ticker_replacements=replacements,
    ) == expected


def test_trailing_period_bare_ticker_is_removed_inside_a_full_market_sentence():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "마이크론 MU.O는 4.2%, 웨스턴 디지털 WDC.O는 6.8%, 샌디스크 SNDK."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == "마이크론은 4.2%, 웨스턴 디지털은 6.8%, 샌디스크."


@pytest.mark.parametrize(("raw", "expected"), [
    ("MU|Micron Technology Inc|가격:819.470|Chg%:-80.730 - TradingKey",
     "마이크론|가격:819.470|Chg%:-80.730 - TradingKey"),
    ("Micron Technology (MU 5.25%)",
     "마이크론(5.25%)"),
])
def test_company_alias_duplicates_collapse_across_vendor_delimiters(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", sentence=False,
        ticker_replacements=replacements,
    ) == expected


def test_trailing_cashtags_are_removed_when_readable_companies_already_exist():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "스페이스X가 엔비디아와 파트너십을 체결했다 $SPCX $NVDA"
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.",
        ticker_replacements=replacements,
    ) == "스페이스X가 엔비디아와 파트너십을 체결했다."


@pytest.mark.parametrize(("raw", "expected"), [
    ("엔비디아 Groq 3 LPX 본격 양산 돌입 $NVDA $SPCX",
     "엔비디아 Groq 3 LPX 본격 양산 돌입"),
    ("블랙스톤과 아폴로, 반도체 금융 지원 참여 논의 중. $AVGO",
     "블랙스톤과 아폴로, 반도체 금융 지원 참여 논의 중"),
    ("딜은 AI 데이터센터 지원을 위한 엔비디아 노력의 일환 - FT. $NVDA $GS",
     "딜은 AI 데이터센터 지원을 위한 엔비디아 노력의 일환 - FT"),
    ("오픈AI, AMD 헬리오스 대규모 도입 전망 $AMD",
     "오픈AI, AMD 헬리오스 대규모 도입 전망"),
    ("구글, 자본지출이 크게 증가할 것으로 전망, $GOOGL",
     "구글, 자본지출이 크게 증가할 것으로 전망"),
])
def test_trailing_cashtag_cluster_is_treated_as_source_routing_metadata(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", sentence=False,
        ticker_replacements=replacements,
    ) == expected


def test_bilingual_company_glosses_with_corporate_suffixes_do_not_duplicate():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = ("마이크로소프트(Microsoft) MSFT.O, "
           "알파벳(Alphabet Inc.)의 구글(Google) GOOGL.O, "
           "오라클(Oracle Corp) ORCL.N")
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", sentence=False,
        ticker_replacements=replacements,
    ) == "마이크로소프트, 알파벳의 구글, 오라클"


def test_line_join_does_not_insert_a_period_after_a_comma():
    from sector.report_readability import _fallback_reader_text

    raw = "블룸버그는 소식통을 인용해,\n아마존이 채권을 발행한다고 보도했다."
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다."
    ) == "블룸버그는 소식통을 인용해, 아마존이 채권을 발행한다고 보도했다."


@pytest.mark.parametrize(("raw", "expected"), [
    ("Amazon, Microsoft, ... outpaced supply",
     "Amazon, Microsoft, outpaced supply"),
    ("컨센서스 밑돈 SK하이닉스 2분기 실적, ...월가 관전 포인트",
     "컨센서스 밑돈 SK하이닉스 2분기 실적, 월가 관전 포인트"),
])
def test_source_ellipsis_after_a_comma_does_not_create_comma_period(
        raw, expected):
    from sector.report_readability import _clean_text

    assert _clean_text(raw) == expected


def test_year_range_is_not_rewritten_as_an_impossible_calendar_month():
    from sector.report_readability import _fallback_reader_text

    raw = "both target 1.4nm mass production around 2028-29, Samsung follows"
    text = _fallback_reader_text(raw, 280, "생산 일정을 확인한다.")

    assert "2028-29" in text
    assert "2028년 29월" not in text


@pytest.mark.parametrize(("raw", "expected"), [
    ("중국은행(Bank of China) 601988.SS, 3988.HK은 발표했다.",
     "중국은행은 발표했다."),
    ("캐나다구스(Canada Goose) GOOS.TO, GOOS.N가 성장했다.",
     "캐나다구스가 성장했다."),
])
def test_alternate_listing_bilingual_gloss_allows_lowercase_connectors(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("징둥닷컴(9618.HK, JD.O)이 발표했다.", "징둥닷컴이 발표했다."),
    ("HSBC HSBA.L, 0005.HK는 매각했다.", "HSBC는 매각했다."),
    ("CITIC Securities 600030.SS, 6030.HK는 성장했다.",
     "CITIC Securities는 성장했다."),
])
def test_multi_listing_wordmark_or_parenthesized_codes_are_one_identity(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("온세미(Onsemi ON.O)는 공급했다.", "온세미는 공급했다."),
    ("파워칩세미컨덕터(PSMC) 6770.TW는 증설했다.",
     "파워칩세미컨덕터는 증설했다."),
    ("아날로그 디바이스(Analog Devices) ADI.O는 발표했다.",
     "아날로그 디바이스는 발표했다."),
])
def test_bilingual_company_code_inside_or_after_parentheses_is_one_identity(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("미국(New York ABCD.O)은 발표했다.", "미국(New York)은 발표했다."),
    ("장소(San Francisco SF.N)는 바뀌었다.",
     "장소(San Francisco)는 바뀌었다."),
    ("보고서(Annual Review AR.N)은 공개됐다.",
     "보고서(Annual Review)는 공개됐다."),
    ("기술(Artificial Intelligence AI.N)은 중요하다.",
     "기술(Artificial Intelligence)은 중요하다."),
])
def test_parenthesized_prose_is_not_mistaken_for_a_company_annotation(
        raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "관련 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected_fragments"), [
    ("NVDA.O, ZXCV.O는 각각 상승했다.", ("엔비디아", "해당 기업")),
    ("엔비디아 NVDA.O, APLD.O는 각각 상승했다.",
     ("엔비디아", "어플라이드 디지털")),
    ("알파벳 GOOGL.O, XYZ.N은 각각 상승했다.", ("알파벳", "해당 기업")),
])
def test_comma_separated_different_company_codes_are_not_collapsed(
        raw, expected_fragments):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    rendered = _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements)

    assert all(fragment in rendered for fragment in expected_fragments)


@pytest.mark.parametrize("raw", [
    "경제지표 ABCD.O는 상승했다.",
    "투자전략 ABCD.O를 검토했다.",
    "위험자산 ABCD.O는 하락했다.",
    "실업수당 ABCD.O는 늘었다.",
    "소비심리 ABCD.O가 악화됐다.",
    "회의(London) LON.N은 열렸다.",
    "행사(Annual Review) AR.N은 열렸다.",
])
def test_unconfirmed_natural_language_before_ric_is_not_a_company_identity(raw):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    rendered = _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements)

    assert "해당 기업" in rendered


@pytest.mark.parametrize(("raw", "preserved"), [
    ("설명(Artificial Intelligence) AI.N은 중요하다.",
     "설명(Artificial Intelligence)"),
    ("업무 절차(Business Process) BP.N을 개선했다.",
     "업무 절차(Business Process)"),
    ("보고서(Annual Review) AR.N을 냈다.", "보고서(Annual Review)"),
])
def test_ticker_root_subsequence_does_not_erase_an_unrelated_definition(raw, preserved):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    rendered = _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    )
    assert preserved in rendered


@pytest.mark.parametrize("raw", [
    "스페이스X SPCX.O는 투자했다.",
    "스페이스XSPCX.O는 투자했다.",
])
def test_spacex_alias_stays_intact_before_its_market_code(raw):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == "스페이스X는 투자했다."


def test_digit_leading_alphanumeric_ric_is_naturalized_but_domain_is_preserved():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        reader_text_problem,
    )

    raw = "키옥시아(Kioxia) 285A.T와 2news.co.kr 보도를 확인했다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replacements["285A.T"] == "키옥시아"
    assert reader_text_problem(raw) is True
    rendered = _fallback_reader_text(
        raw, 280, "기업 흐름을 확인한다.", ticker_replacements=replacements
    )
    assert rendered == "키옥시아와 2news.co.kr 보도를 확인했다."
    assert reader_text_problem(rendered) is False


@pytest.mark.parametrize("raw", [
    "SK하이닉스의 설비투자(CAPEX)는 늘었다.",
    "SK하이닉스의 CAPEX(설비투자)는 늘었다.",
    "SK하이닉스의 CAPEX(CAPEX=설비투자)는 늘었다.",
])
def test_capex_definition_collapses_to_one_readable_term(raw):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(
        raw, 280, "설비투자를 확인한다."
    ) == "SK하이닉스의 설비투자는 늘었다."


def test_company_code_definition_collapses_to_the_readable_company_name():
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(
        "〔근거: 로이터, NVDA=엔비디아〕",
        280,
        "근거를 확인한다.",
    ) == "〔근거: 로이터, 엔비디아〕"


@pytest.mark.parametrize("raw", [
    "자료는 SEC.GOV/company_facts에서 확인한다.",
    "자료는 EXAMPLE.IO/path_name에서 확인한다.",
    "자료는 GOV.UK/path_name에서 확인한다.",
    "자료는 SEC.gov?id=25에서 확인한다.",
])
def test_uppercase_domains_and_url_queries_are_preserved(raw):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is False
    assert _fallback_reader_text(raw, 220, "출처를 확인한다.") == raw


@pytest.mark.parametrize("raw", [
    "자료는 Example.Co에서 확인한다.",
    "자료는 Example.US/path에서 확인한다.",
    "문의는 press@example.co로 보낸다.",
    "문의는 PRESS@EXAMPLE.CO로 보낸다.",
])
def test_mixed_case_domains_and_email_addresses_are_preserved(raw):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is False
    assert _fallback_reader_text(raw, 220, "출처를 확인한다.") == raw


@pytest.mark.parametrize(("raw", "expected"), [
    ("회사는 ABCD.O를 인수했다.", "회사는 해당 기업을 인수했다."),
    ("주가는 ABCD.O가 올랐다.", "주가는 해당 기업이 올랐다."),
    ("오늘 ABCD.O는 상승했다.", "오늘 해당 기업은 상승했다."),
])
def test_ambiguous_ric_context_uses_generic_subject_without_deleting_prose(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 180, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize("raw", [
    "판매량은 9988개다.",
    "지수는 688825포인트다.",
])
def test_bare_numeric_values_are_not_rewritten_as_companies(raw):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 180, "수치를 확인한다.") == raw


@pytest.mark.parametrize("raw", [
    "A sales rep said demand rose.",
    "SOX compliance costs rose.",
    "The trade mags published forecasts.",
])
def test_bare_ticker_roots_do_not_rewrite_ordinary_english_prose(raw):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 180, "시장 설명을 확인한다.") == raw


@pytest.mark.parametrize(("raw", "qualified", "expected"), [
    ("알리바바 9988.HK 실적", "9988.HK", "알리바바 실적"),
    ("CXMT 688825.SS 실적", "688825.SS", "CXMT 실적"),
])
def test_numeric_companies_require_a_qualified_source_ticker(raw, qualified, expected):
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert qualified in replacements
    assert qualified.split(".", 1)[0] not in replacements
    assert replace_source_tickers(raw, replacements) == expected


def test_numeric_reuters_suffix_uses_company_name_without_duplication():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "삼성전자(005930.K)는 내렸다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replacements == {"005930.K": "삼성전자"}
    assert _fallback_reader_text(
        raw, 180, "주가를 확인한다.", ticker_replacements=replacements
    ) == "삼성전자는 내렸다."


@pytest.mark.parametrize(("raw", "expected"), [
    ("소프트뱅크 9984.T은 상승했다.", "소프트뱅크는 상승했다."),
    ("어드반테스트 6857.T는 상승했다.", "어드반테스트는 상승했다."),
    ("TSMC <2330.TW>는 증설했다.", "TSMC는 증설했다."),
    ("위스트론(Wistron, 3231.TW)이 투자했다.", "위스트론이 투자했다."),
])
def test_unknown_numeric_ric_keeps_the_adjacent_readable_company_name(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replacements
    assert _fallback_reader_text(
        raw, 180, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("한화 000880.KS는 올랐다.", "한화는 올랐다."),
    ("두산 000150.KS는 올랐다.", "두산은 올랐다."),
    ("기아 000270.KS는 올랐다.", "기아는 올랐다."),
    ("현대 005380.KS는 올랐다.", "현대는 올랐다."),
    ("이베이 035720.KS는 올랐다.", "이베이는 올랐다."),
    ("3M 031100.KS는 올랐다.", "3M은 올랐다."),
    ("LG에너지솔루션 373220.KS는 올랐다.", "LG에너지솔루션은 올랐다."),
    ("HD현대일렉트릭 267260.KS는 올랐다.", "HD현대일렉트릭은 올랐다."),
])
def test_unknown_numeric_ric_preserves_broad_company_labels(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 180, "기업 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_numeric_ric_does_not_learn_a_transition_word_as_company_name():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "6857.T로 7% 하락했고, 이어 5711.T가 6.37% 하락했다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replacements["5711.T"] == "미쓰비시머티리얼"
    assert _fallback_reader_text(
        raw, 240, "종목 흐름을 확인한다.", ticker_replacements=replacements
    ) == "어드반테스트로 7% 하락했고, 이어 미쓰비시머티리얼이 6.37% 하락했다."


@pytest.mark.parametrize(("raw_name", "ordinary", "display"), [
    ("C3.ai (AI)", "AI 투자가 늘었다.", "C3.ai"),
    ("Gartner (IT)", "IT 지출이 늘었다.", "Gartner"),
    ("TSMC (ADR)", "ADR 시장이 커졌다.", "TSMC"),
    ("ASML (EU)", "EU 규제가 바뀌었다.", "ASML"),
    ("Onsemi (ON)", "Demand was ON track.", "온세미"),
])
def test_ambiguous_beneficiary_suffix_only_hides_its_wrapper(
        raw_name, ordinary, display):
    from sector.report_reader_rules import (
        reader_surface_problem,
        replace_source_tickers,
        source_ticker_replacements,
    )

    code = raw_name.rsplit("(", 1)[1].rstrip(")")
    replacements = source_ticker_replacements([(raw_name, "stock")])
    assert replacements == {f"({code})": display}
    assert replace_source_tickers(ordinary, replacements) == ordinary
    assert reader_surface_problem(ordinary, forbidden_tokens=replacements) is False


@pytest.mark.parametrize(("raw_name", "rationale"), [
    ("ASML (ASML.AS)", "ASML의 EUV 장비 수요가 늘어난다."),
    ("IBM (IBM.N)", "IBM의 매출이 늘어난다."),
    ("AMD (AMD.O)", "AMD의 가속기 매출이 늘어난다."),
])
def test_fallback_keeps_registered_wordmark_subjects_in_beneficiary_prose(
        raw_name, rationale):
    from sector.report_readability import _plain_reader_sentence
    from sector.report_reader_rules import reader_identity, source_ticker_replacements

    identity = reader_identity(raw_name, kind="stock")
    replacements = source_ticker_replacements([(raw_name, "stock")])

    assert _plain_reader_sentence(
        rationale,
        display_name=identity.display_name,
        ticker=identity.ticker,
        fallback="기업 흐름을 확인한다.",
        limit=220,
        ticker_replacements=replacements,
    ) == rationale


def test_prefixed_one_letter_ticker_never_rewrites_model_numbers():
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    raw = "포드 (NYSE:F)는 판매했다. F-150 판매도 늘었다."
    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert "F" not in replacements
    assert _fallback_reader_text(
        raw, 220, "판매를 확인한다.", ticker_replacements=replacements
    ) == "포드는 판매했다. F-150 판매도 늘었다."


@pytest.mark.parametrize("raw", [
    "전년(2026) 매출은 늘었다.",
    "내년(2027) 증설을 계획했다.",
    "80,000장(2027) 공급을 계획했다.",
    "29조원(2025) 매출을 기록했다.",
    "코드는 (005930)이다.",
])
def test_fallback_preserves_bare_parenthesized_years_and_numbers(raw):
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 220, "수치를 확인한다.") == raw


@pytest.mark.parametrize(("raw", "code", "expected"), [
    ("NvidiaNVDA.O 실적", "NVDA.O", "엔비디아 실적"),
    ("AmazonAMZN.O 투자", "AMZN.O", "아마존 투자"),
    ("WeaveCRWV.O 실적", "CRWV.O", "Weave 실적"),
    ("FedExFDX.N 배송", "FDX.N", "FedEx 배송"),
    ("Siemens EnergyENR1n.DE 투자", "ENR1N.DE", "Siemens Energy 투자"),
    ("CXMT Corp688825.SS 증설", "688825.SS", "CXMT Corp 증설"),
    ("Global0625.HK 실적", "0625.HK", "Global 실적"),
])
def test_source_ticker_naturalization_splits_missing_company_space(
        raw, code, expected):
    """뉴스의 회사명+RIC 공백 누락이 회사명 전체를 ticker로 삼키지 않는다."""
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert code in replacements
    assert raw.split(".", 1)[0].upper() not in replacements
    assert replace_source_tickers(raw, replacements) == expected


def test_dollar_ticker_keeps_registered_wordmarks_but_naturalizes_other_codes():
    """$ 표기가 AMD·IBM 같은 정식 회사명을 금칙어로 만들면 안 된다."""
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    raw = "$AMD $IBM $ARM $SAP $ASML $KLA $VRT"
    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert not ({"AMD", "IBM", "ARM", "SAP", "ASML", "KLA"} & set(replacements))
    assert replacements["VRT"] == "버티브"
    assert replace_source_tickers(raw, replacements) == "AMD IBM ARM SAP ASML KLA 버티브"


@pytest.mark.parametrize(("raw", "expected"), [
    ("S&P500(^GSPC) 흐름", "S&P500 흐름"),
    ("나스닥종합(^IXIC) 흐름", "나스닥종합 흐름"),
    ("필라델피아 반도체지수(^SOX) 흐름", "필라델피아 반도체지수 흐름"),
    ("코스피(.KS11) 흐름", "코스피 흐름"),
])
def test_parenthesized_index_code_keeps_existing_readable_label(raw, expected):
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replace_source_tickers(raw, replacements) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("nVent Electric(NVT.N, NYSE)가 수주했다", "엔벤트 일렉트릭이 수주했다"),
    ("CXMT 688825.SS가 증설했다", "CXMT가 증설했다"),
    ("CXMT 688825.SS 증설", "CXMT 증설"),
    ("페트로브라스 <PETR4.SA>는 투자했다", "페트로브라스는 투자했다"),
    ("마이크론($MU)이 공급했다", "마이크론이 공급했다"),
])
def test_wrapped_or_adjacent_source_code_preserves_existing_company_name(raw, expected):
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replace_source_tickers(raw, replacements) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("원·달러 환율 KRW=X", "원·달러 환율"),
    ("WTI CL=F", "WTI 원유"),
    ("엔·달러 환율 JPY=X", "엔·달러 환율"),
    ("일본 2년물 금리 JP2YTN=JBTC", "일본 2년물 금리"),
])
def test_market_code_naturalization_keeps_or_adds_readable_name(raw, expected):
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replace_source_tickers(raw, replacements) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("엔화 JPY=가 다시 주목받는다.", "엔화가 다시 주목받는다."),
    ("유로화 EUR=는 강세다.", "유로화는 강세다."),
    ("현물 금 XAU=은 상승했다.", "현물 금은 상승했다."),
])
def test_empty_market_code_particle_is_not_parsed_as_a_definition(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])
    assert _fallback_reader_text(
        raw, 260, "시장 흐름을 확인한다.", ticker_replacements=replacements
    ) == expected


def test_market_code_allowlists_cover_actual_corpus_families_without_definitions():
    """시장 vendor/RIC는 읽는 이름으로, 약어 정의·통화 root는 그대로 둔다."""
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    raw = (
        "XAU= JPY= BTC= US30YT=RR DE10YT=RR JP10YTN=JBTC "
        "GBP=D3 TWD=TP THB=TH ARS=RASL INR=IN "
        ".N225 .TWII .SSEC .STOXX .DXY $F $C $SPCX $FILE "
        "HBM=고대역폭메모리 CAPEX=설비투자"
    )
    replacements = explicit_source_ticker_replacements([{"title": raw}])
    rendered = replace_source_tickers(raw, replacements)

    for code, label in {
        "XAU=": "현물 금",
        "JPY=": "엔·달러 환율",
        "BTC=": "비트코인",
        "US30YT=RR": "미국 30년물 국채금리",
        "DE10YT=RR": "독일 10년물 국채금리",
        "JP10YTN=JBTC": "일본 10년물 국채금리",
        ".N225": "닛케이 225 지수",
        ".TWII": "대만 가권지수",
        ".SSEC": "상하이종합지수",
        ".STOXX": "STOXX 유럽 600 지수",
        ".DXY": "달러지수",
        "$F": "포드",
        "$C": "씨티그룹",
        "SPCX": "스페이스X",
    }.items():
        assert replacements[code] == label
        assert label in rendered
    assert all(code in replacements for code in (
        "GBP=D3", "TWD=TP", "THB=TH", "ARS=RASL", "INR=IN",
    ))
    assert not ({"GBP", "TWD", "THB", "ARS", "INR", "FILE"} & set(replacements))
    assert "$FILE" in rendered
    assert "HBM=고대역폭메모리" in rendered
    assert "CAPEX=설비투자" in rendered


@pytest.mark.parametrize("code", [
    "TSEM.TA",
    "KSP.I",
    "REP.MC",
    "MAGS.P",
    "005930.K",
    "<MILA00000PUS>",
    "<TWII>",
    "<.MIMS0IT00PUS>",
    "(.CSI931079)",
    "<.MISU00000PUS>",
])
def test_source_inventory_recognizes_actual_exchange_and_bracketed_index_codes(code):
    """실제 뉴스 카드의 거래소·괄호형 지수 RIC를 읽기 계층이 빠뜨리지 않는다."""
    from sector.report_reader_rules import explicit_source_ticker_replacements

    assert explicit_source_ticker_replacements([{"title": f"시장 {code} 흐름"}])


@pytest.mark.parametrize("raw", [
    "시장 ^GSPC 흐름",
    "시장 ^IXIC 흐름",
    "기업 $T 실적",
    "기업 $X 실적",
])
def test_reader_surface_rejects_caret_and_single_letter_cashtags(raw):
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is True


def test_one_letter_cashtag_does_not_turn_plain_letters_into_company_names():
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        reader_surface_problem,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([
        {"title": "$F 판매와 F-150 출하"},
    ])

    assert "$F" in replacements
    assert "F" not in replacements
    assert replace_source_tickers(
        "포드 $F와 F-150 판매", replacements) == "포드와 F-150 판매"
    assert reader_surface_problem(
        "비타민 F 수요", forbidden_tokens=replacements) is False


def test_source_numeric_ticker_does_not_turn_calendar_year_into_company():
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([
        {"title": "AAC Tech 2018.HK 실적"},
    ])

    assert "2018.HK" in replacements
    assert "2018" not in replacements
    assert replace_source_tickers(
        "2018년 이후 수요가 늘었다", replacements) == "2018년 이후 수요가 늘었다"


def test_context_inventory_requires_code_like_uppercase_not_company_prose():
    from sector.report_reader_rules import explicit_source_ticker_replacements

    assert explicit_source_ticker_replacements([
        {"title": "ticker Nvidia 관련 설명"},
    ]) == {}


@pytest.mark.parametrize("acronym", ["AI", "USD", "ETF"])
def test_dollar_prefixed_acronym_does_not_forbid_the_plain_acronym(acronym):
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        reader_surface_problem,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([
        {"title": f"${acronym} 관련 흐름"},
    ])

    assert acronym not in replacements
    assert replace_source_tickers(f"${acronym} 수요", replacements) == f"{acronym} 수요"
    assert reader_surface_problem(
        f"{acronym} 수요", forbidden_tokens=replacements) is False


@pytest.mark.parametrize("acronym", [
    "NPU", "ASIC", "TPU", "FPGA", "SoC", "HBM3E", "LPDDR5X",
])
def test_reader_surface_preserves_parenthesized_chip_acronyms(acronym):
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(f"차세대 가속기({acronym}) 수요") is False


@pytest.mark.parametrize(("raw", "expected"), [
    ("달러지수 DX-Y.NYB 상승", "달러지수 상승"),
    ("S&P 500 ^GSPC 상승", "S&P 500 상승"),
    ("원유 CL=F 가격", "원유 가격"),
])
def test_source_naturalization_deduplicates_existing_market_names(raw, expected):
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        replace_source_tickers,
    )

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replace_source_tickers(raw, replacements) == expected


def test_dynamic_forbidden_roots_preserve_confirmed_company_wordmarks():
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        reader_surface_problem,
    )

    unknown = explicit_source_ticker_replacements([
        {"title": "ZZZZ ZZZZ.O 실적"},
    ])
    assert unknown == {"ZZZZ.O": "ZZZZ"}
    assert reader_surface_problem(
        "ZZZZ 흐름", forbidden_tokens=unknown) is False

    index = explicit_source_ticker_replacements([
        {"title": "시장 .STOXX 및 SPX .SPX 흐름"},
    ])
    assert reader_surface_problem(
        "STOXX 유럽 600 지수 흐름", forbidden_tokens=index) is False
    assert reader_surface_problem(
        "SPX 흐름", forbidden_tokens=index) is True


def test_unknown_exchange_context_keeps_a_bare_symbol_in_forbidden_inventory():
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        reader_surface_problem,
    )

    replacements = explicit_source_ticker_replacements([
        {"title": "시장 데이터 (NYSE:XYZ) 흐름 발표"},
    ])

    assert replacements == {"XYZ": "해당 기업"}
    assert reader_surface_problem(
        "시장 데이터 XYZ 흐름을 확인한다.",
        forbidden_tokens=replacements,
    ) is True


@pytest.mark.parametrize("raw", [
    "원·달러 환율은 1368.7원이다.",
    "매출은 1234.56달러다.",
    "S&P 500 지수는 7674.37pt다.",
    "투자액은 1234.5억원이다.",
])
def test_reader_rules_preserve_uncommaed_four_digit_decimals(raw):
    """네 자리 정수부의 소수는 숫자이지 숫자형 거래소 ticker가 아니다."""
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem(raw) is False
    assert _fallback_reader_text(raw, 180, "수치를 확인한다.") == raw


def test_reader_rules_still_reject_numeric_exchange_ticker():
    from sector.report_reader_rules import reader_text_problem

    assert reader_text_problem("삼성전자 005930.KS 실적") is True


@pytest.mark.parametrize(("raw", "expected"), [
    (
        "Micron: This Isn't Peak Memory Yet (NASDAQ:MU)",
        "마이크론: This Isn't Peak Memory Yet.",
    ),
    ("NVIDIA (NASDAQ:NVDA)는 발표했다.", "엔비디아는 발표했다."),
    ("Example Corp (NYSE:XYZ)는 발표했다.", "Example Corp는 발표했다."),
])
def test_fallback_removes_exchange_prefixed_ticker_wrappers(raw, expected):
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import (
        explicit_source_ticker_replacements,
        reader_text_problem,
    )

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert replacements
    assert reader_text_problem(raw) is True
    assert _fallback_reader_text(
        raw,
        180,
        "관련 기업 흐름을 확인한다.",
        ticker_replacements=replacements,
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    (
        "타워 세미컨덕터(Tower Semiconductor TSEM.TA)는 전망을 높였다.",
        "타워 세미컨덕터는 전망을 높였다.",
    ),
    (
        "킨스판(Kingspan KSP.I)이 데이터센터 수요를 확인했다.",
        "킨스판이 데이터센터 수요를 확인했다.",
    ),
    (
        "에너지 기업 RepsolREP.MC는 실적을 발표했다.",
        "에너지 기업 렙솔은 실적을 발표했다.",
    ),
    (
        "매그니피센트 세븐 ETF MAGS.P는 하락했다.",
        "매그니피센트 세븐 ETF는 하락했다.",
    ),
    ("엔비디아(Nvidia NVDA.O)는 발표했다.", "엔비디아는 발표했다."),
    ("구글(Google GOOGL.O)은 투자했다.", "구글은 투자했다."),
    ("아마존(Amazon AMZN.O)은 증설했다.", "아마존은 증설했다."),
    ("렙솔(Repsol REP.MC)은 생산했다.", "렙솔은 생산했다."),
])
def test_fallback_collapses_company_name_plus_ric_wrappers(raw, expected):
    """원문 회사명과 RIC를 함께 싼 표기를 canonical 이름 하나로 접는다."""
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw,
        180,
        "관련 기업 흐름을 확인한다.",
        ticker_replacements=replacements,
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    (
        "Should You Sell Micron ($MU) Before Earnings?",
        "Should You Sell 마이크론 Before Earnings?",
    ),
    ("Micron MU Stock 흐름", "마이크론 Stock 흐름."),
])
def test_fallback_collapses_duplicates_after_company_alias_translation(raw, expected):
    """후속 영문 회사명 번역 뒤 생긴 canonical 이름 중복도 마지막에 접는다."""
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw,
        180,
        "관련 기업 흐름을 확인한다.",
        ticker_replacements=replacements,
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("닛케이 225 .N225는 0.3% 하락했다.", "닛케이 225는 0.3% 하락했다."),
    ("상하이 종합지수 .SSEC는 상승했다.", "상하이 종합지수는 상승했다."),
    ("대만 가권지수 .TWII는 올랐다.", "대만 가권지수는 올랐다."),
    (
        "European STOXX 600 .STOXX는 약세였다.",
        "European STOXX 600은 약세였다.",
    ),
])
def test_fallback_deduplicates_readable_index_names(raw, expected):
    """폴백은 이미 쓰인 지수명 뒤 RIC만 없애고 이름을 반복하지 않는다."""
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw,
        180,
        "시장 흐름을 확인한다.",
        ticker_replacements=replacements,
    ) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("버티브 VRT.N은 수요가 늘었다.", "버티브는 수요가 늘었다."),
    ("Meta Platforms Inc (META.O)가 투자했다.", "메타가 투자했다."),
    (
        "nVent Electric(NVT.N, NYSE)가 수주했다.",
        "엔벤트 일렉트릭이 수주했다.",
    ),
])
def test_fallback_repairs_particles_after_ticker_naturalization(raw, expected):
    """ticker를 자연어 이름으로 바꾼 뒤 공백과 한글 조사를 함께 교정한다."""
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import explicit_source_ticker_replacements

    replacements = explicit_source_ticker_replacements([{"title": raw}])

    assert _fallback_reader_text(
        raw,
        180,
        "관련 기업 흐름을 확인한다.",
        ticker_replacements=replacements,
    ) == expected


@pytest.mark.parametrize("raw", [
    "현물 은 가격이 3% 올랐다.",
    "금과 은 가격이 함께 올랐다.",
    "삼성전자 이 회사는 투자를 늘렸다.",
])
def test_particle_repair_preserves_separate_nouns_and_demonstratives(raw):
    """일반 문장의 은(銀)·지시어 '이'를 조사로 오인해 합치지 않는다."""
    from sector.report_readability import _fallback_reader_text

    assert _fallback_reader_text(raw, 180, "시장 흐름을 확인한다.") == raw


def test_ungrounded_numbers_are_retried_then_valid_cli_output_is_used():
    """회귀: 카드에 없는 숫자를 읽기 계층이 새 사실처럼 만들면 첫 출력을 채택하지 않는다."""
    from sector.report_readability import generate_report_readability

    role = _ReadabilityRole([_draft_payload(invented=True), _draft_payload()])
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=role,
        audit_role=_AuditRole(),
    ))

    assert role.calls == 2
    assert result.output.mode == "generated"
    assert "99.9" not in json.dumps(result.output.model_dump(), ensure_ascii=False)
    assert "재시도" in result.io.note


def test_cli_copy_must_cover_every_beneficiary_at_its_exact_position():
    """CLI가 한 영향 항목을 누락하거나 다른 항목에 덮어쓰면 원시 문장이 화면으로 새면 안 된다."""
    from sector.report_readability import generate_report_readability

    incomplete = _draft_payload()
    incomplete["beneficiaryCopies"].pop()
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([incomplete]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert len(result.output.beneficiaryCopies) == 12


def test_cli_copy_accepts_semantically_equivalent_plain_korean_number_notation():
    """b원·음수 약어를 자연어로 풀어도 같은 값이면 독립 의미감사까지 진행한다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    item = next(copy for copy in draft["beneficiaryCopies"]
                if copy["axis"] == "topic1"
                and copy["polarity"] == "positive"
                and copy["index"] == 1)
    item["evidence"] = (
        "SK하이닉스의 2026년 3월 분기 전사 설비투자는 7,865.37십억 원이며, "
        "전분기보다 35.8% 감소했다."
    )
    audit = _AuditRole()
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=audit,
    ))

    assert result.output.mode == "generated"
    assert audit.calls == 1
    assert "7,865.37십억 원" in result.output.beneficiaryCopies[
        "topic1:positive:1"].evidence


def test_reader_structure_ordinals_are_not_mistaken_for_market_numbers():
    """'2차 파급' 같은 독서 구조 표현은 카드에 숫자 2 근거가 없다고 거절하지 않는다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    draft["briefs"][1]["flow"][1]["detail"] = "관련 산업으로 2차 파급이 이어진다."
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "generated"
    assert "2차 파급" in result.output.briefs["topic1"].flow[1].detail


def test_cli_failure_uses_reproducible_meaningful_fallback_without_invented_numbers():
    """회귀: 편집 CLI가 죽어도 발행 가능한 읽기 구조가 항상, 결정적으로 남는다."""
    from sector.report_readability import generate_report_readability

    async def run_once():
        return await generate_report_readability(
            report_id="2026-09-04-6",
            generated_at="2026-09-04T18:30:00+09:00",
            lead_axis="topic1",
            cards=_cards_for_generation(),
            role=_ReadabilityRole([RuntimeError("CLI unavailable")]),
            audit_role=_AuditRole(),
        )

    first = asyncio.run(run_once())
    second = asyncio.run(run_once())

    assert first.output.model_dump() == second.output.model_dump()
    assert first.output.mode == "fallback"
    assert first.output.editorial.headline.startswith("AI 전력 수요가 12%")
    assert set(first.output.briefs) == {"macro", "topic1", "topic2"}
    assert all(brief.flow and brief.scenarioGuide and brief.watchlist
               for brief in first.output.briefs.values())
    assert first.error == "RuntimeError"


def test_fallback_turns_ticker_metric_rows_into_plain_korean_sentences():
    """CLI 장애 때도 사용자 예시의 ticker/metric/QoQ/b원 행을 그대로 노출하지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    samsung, lam = cards[1].scenarios[0].beneficiaries
    samsung.name = "삼성전자 (005930.KS)"
    samsung.evidence = "memory_capex 005930.KS 18,176.96b원(+42.5% QoQ, 2026-03)"
    samsung.financials = samsung.evidence
    lam.name = "램리서치 (LRCX)"
    lam.evidence = (
        "equip_revenue LRCX 6.72십억(+15.1% QoQ @2026-06), "
        "AMAT 7.91십억(+12.8% QoQ)"
    )
    lam.financials = "LRCX 분기매출 6.72십억(+15.1% QoQ, 직전 5.84)"

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    samsung_copy = layer.beneficiaryCopies["topic1:positive:0"]
    lam_copy = layer.beneficiaryCopies["topic1:positive:1"]
    visible = json.dumps([samsung_copy.model_dump(), lam_copy.model_dump()], ensure_ascii=False)

    assert samsung_copy.displayName == "삼성전자"
    assert "2026년 3월 분기" in samsung_copy.evidence
    assert "전사 설비투자" in samsung_copy.evidence
    assert "18조 1,769억 6천만 원" in samsung_copy.evidence
    assert "전분기보다 42.5% 증가" in samsung_copy.evidence
    assert lam_copy.displayName == "램리서치"
    assert "램리서치의 2026년 6월 분기 매출" in lam_copy.evidence
    assert "어플라이드 머티어리얼즈" in lam_copy.evidence
    assert "어플라이드 머티어리얼즈의 최근 분기 매출" in lam_copy.evidence
    assert "어플라이드 머티어리얼즈의 2026년 6월" not in lam_copy.evidence
    assert "전분기보다 15.1% 증가" in lam_copy.evidence
    assert "달러" not in lam_copy.evidence, "원문에 없는 통화를 회사로부터 추론하지 않는다"
    assert not any(token in visible for token in (
        "005930.KS", "LRCX", "AMAT", "memory_capex", "equip_revenue", "QoQ", "b원",
    ))


@pytest.mark.parametrize(("raw", "forbidden", "expected"), [
    ("CAPEX 18,176.96b_local(+42.5% QoQ @2026-03)", "b_local", "현지 통화"),
    ("매출 44.92b_usd", "b_usd", "달러"),
    ("매출 41,171,955k_usd", "k_usd", "달러"),
    ("매출 1.5b_gbp", "b_gbp", "파운드"),
    ("매출 1.5m_cny", "m_cny", "위안"),
    ("매출 1.5b_hkd", "b_hkd", "홍콩달러"),
    ("매출 1.5m_sgd", "m_sgd", "싱가포르달러"),
    ("매출 1.5k_cad", "k_cad", "캐나다달러"),
    ("매출 1.5k_aud", "k_aud", "호주달러"),
    ("매출 1.5b_chf", "b_chf", "통화 수치"),
])
def test_fallback_naturalizes_numeric_prefix_snake_case_units(raw, forbidden, expected):
    """실제 저장 corpus의 b_local/b_usd/k_usd도 내부 행 그대로 노출하지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = raw
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    text = layer.beneficiaryCopies["topic1:positive:0"].evidence

    assert forbidden not in text
    assert "_" not in text
    assert expected in text


@pytest.mark.parametrize(("source", "candidate"), [
    ("매출은 44.92b_usd다.", "매출은 44.92십억 달러다."),
    ("매출은 41,171,955k_usd다.", "매출은 41,171,955천 달러다."),
    ("설비투자는 18,176.96b_local이다.", "설비투자는 18,176.96십억 현지 통화다."),
])
def test_generated_copy_accepts_plain_units_for_numeric_snake_source(source, candidate):
    """프롬프트가 요구한 내부 단위 자연화가 자체 숫자 감사에서 거절되면 안 된다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = candidate

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "generated"
    assert result.error is None


def test_fallback_is_total_for_oversized_numeric_snake_source():
    """비정상적으로 긴 숫자 하나가 결정적 폴백과 정규 발행을 중단시키지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = "매출 " + ("9" * 5000) + "b_local"

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = layer.beneficiaryCopies["topic1:positive:0"].evidence
    assert text.strip()
    assert len(text) <= 500
    assert "b_local" not in text


def test_fallback_naturalizes_the_entire_scan_first_brief_not_only_beneficiaries():
    """CLI 장애여도 headline/flow/guide/watch에 원시 약어·ticker·단위가 남지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    card = cards[1]
    card.title = "주가가 -1.9% DoD 하락했다"
    card.phenomenon = "CAPEX가 GOOGL +25.9% QoQ와 함께 늘었다."
    card.scenarios[0].thesis = "3Q26 매출이 +10% QoQ 증가한다."
    card.scenarios[0].beneficiaries[0].causalChain = "CAPEX 지속(GOOGL +25.9% QoQ)"
    card.watch_signals = ["설비투자 7,865.37b_local 확인"]

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    visible = json.dumps({
        "editorial": layer.editorial.model_dump(),
        "brief": layer.briefs["topic1"].model_dump(),
    }, ensure_ascii=False)

    assert "2026년 3분기" in visible
    assert "알파벳" in visible
    assert "현지 통화" in visible
    assert not any(token in visible for token in (
        "DoD", "QoQ", "CAPEX", "GOOGL", "b_local",
    ))


def test_fallback_reader_copy_is_total_for_long_valid_upstream_fields():
    """원본 계약은 길이 제한이 없다. CLI 장애 폴백이 긴 필드 때문에 리포트를 중단하면 안 된다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.name = "가" * 101
    beneficiary.rationale = "긴 영향 설명이다. " * 100
    beneficiary.causalChain = "핵심 사건에서 공급망으로 전이된다. " * 100
    beneficiary.evidence = "확인된 근거다. " * 100
    beneficiary.financials = "확인된 수치다. " * 100

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    copy = layer.beneficiaryCopies["topic1:positive:0"]
    assert len(copy.displayName) <= 100
    assert len(copy.rationale) <= 320
    assert len(copy.causalChain) <= 320
    assert len(copy.evidence) <= 500
    assert len(copy.financials) <= 500


@pytest.mark.parametrize("raw_name", [
    "AI_infrastructure", "memory_capex", "산업 QoQ", "시장 @2026-06", "규모 7b원",
])
def test_fallback_sanitizes_internal_syntax_even_when_it_appears_in_a_raw_name(raw_name):
    """넓은 upstream 계약이 허용한 이름도 읽기 계약을 깨뜨려 폴백을 raise하게 둘 수 없다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].name = raw_name

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert layer.beneficiaryCopies["topic1:positive:0"].displayName == "관련 대상"


def test_fallback_keeps_nonempty_reader_detail_when_raw_is_only_a_known_metric_token():
    """metric 토큰만 있어도 문장화 결과가 빈 필드가 되어 전체 Report를 깨지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = "equip_revenue"
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert layer.beneficiaryCopies["topic1:positive:0"].evidence.strip()
    assert "equip_revenue" not in layer.beneficiaryCopies["topic1:positive:0"].evidence


@pytest.mark.parametrize("raw", ["123_metric", "12.3_metric", "999_test_value", "0_x"])
def test_fallback_totality_for_digit_leading_internal_metric(raw):
    """넓은 upstream 문자열이 어떤 내부 metric이어도 폴백은 항상 유효해야 한다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = f"지표는 {raw}이다."
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = layer.beneficiaryCopies["topic1:positive:0"].evidence
    assert raw not in text
    assert text.strip()


@pytest.mark.parametrize(("raw_name", "expected"), [
    ("LRCX 장비", "램리서치 장비"),
    ("NAVER 035420.KS 관련주", "NAVER 관련주"),
    ("U.S. 전력 인프라", "U.S. 전력 인프라"),
    ("non-U.S. 매출 기업", "non-U.S. 매출 기업"),
    ("Canada-U.S. 교역", "Canada-U.S. 교역"),
])
def test_fallback_naturalizes_embedded_tickers_in_display_names(raw_name, expected):
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].name = raw_name
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert layer.beneficiaryCopies["topic1:positive:0"].displayName == expected


@pytest.mark.parametrize("raw_name", [
    "범용 메모리(DRAM)",
    "AI 가속기(GPU)",
    "소비자물가(CPI)",
    "반도체 전공정 장비(ASML)",
    "미국 달러·달러현금(머니마켓)",
])
def test_fallback_sector_display_name_preserves_explanatory_parentheses(raw_name):
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.kind = "sector"
    beneficiary.name = raw_name
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert layer.beneficiaryCopies["topic1:positive:0"].displayName == raw_name


def test_report_contract_does_not_treat_sector_explanation_as_a_source_ticker():
    """종목이 아닌 섹터의 (머니마켓)은 source-ticker 결속 검사 대상이 아니다."""
    payload = _topics_report()
    beneficiary = payload["cards"][0]["scenarios"][0]["beneficiaries"][0]
    beneficiary["name"] = "미국 달러·달러현금(머니마켓)"
    beneficiary["readerCopy"].update({
        "displayName": "미국 달러·달러현금(머니마켓)",
        "rationale": "달러와 머니마켓이 방어 자산 역할을 한다.",
    })

    Report.model_validate(payload)


def test_fallback_removes_other_company_tickers_from_reader_detail():
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.evidence = (
        "NAVER 035420.KS 공시와 NVIDIA (NVDA), 브로드컴 (BRCM) 매출을 근거로 본다."
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = layer.beneficiaryCopies["topic1:positive:0"].evidence
    assert "NAVER" in text and "엔비디아" in text and "브로드컴" in text
    assert not any(ticker in text for ticker in ("035420.KS", "(NVDA)", "NVDA", "(BRCM)", "BRCM"))


def test_fallback_removes_unknown_parenthesized_ticker_but_keeps_explanatory_acronym():
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.kind = "stock"
    beneficiary.name = "NewCo (ZZZZ)"
    beneficiary.evidence = (
        "NewCo (ZZZZ) 공시는 인공지능(AI) 가속기(GPU) 수요를 다룬다."
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    text = layer.beneficiaryCopies["topic1:positive:0"].evidence

    assert "ZZZZ" not in text
    assert "(AI)" in text and "(GPU)" in text


@pytest.mark.parametrize("acronym", [
    "AWS", "LLM", "DUV", "ARR", "AGI", "GW", "MW", "CDS", "ICT", "IDM",
])
def test_unlisted_parenthesized_market_and_technology_acronyms_are_preserved(acronym):
    """강한 ticker 근거가 없는 괄호 약어는 원문 설명으로 보존한다."""
    from sector.report_readability import _fallback_reader_text
    from sector.report_reader_rules import reader_text_problem

    raw = f"관련 시장({acronym}) 신호를 확인한다."
    assert reader_text_problem(raw) is False
    assert _fallback_reader_text(raw, 180, "시장 신호를 확인한다.") == raw


def test_non_stock_identity_keeps_explanatory_parenthesized_acronym():
    from sector.report_reader_rules import reader_identity

    identity = reader_identity("클라우드(AWS)", kind="sector")

    assert identity.display_name == "클라우드(AWS)"
    assert identity.ticker == ""


@pytest.mark.parametrize("raw_name", [
    "유럽 자동차(DE)",
    "일반 상품(CAT)",
    "상태(ON)",
    "남부 전력(SO)",
])
def test_non_stock_identity_does_not_turn_sector_acronyms_into_companies(
        raw_name):
    from sector.report_reader_rules import reader_identity

    identity = reader_identity(raw_name, kind="sector")

    assert identity.display_name == raw_name
    assert identity.ticker == ""


def test_fallback_readability_stays_fast_enough_for_scheduler_recovery():
    """CLI 장애 시 결정적 폴백이 예약 실행 시간을 잠식하지 않는다."""
    from sector.report_readability import fallback_report_readability

    started = perf_counter()
    fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
    )

    assert perf_counter() - started < 3.0


def test_fallback_preserves_parenthesized_source_institution_acronym():
    """출처 기관 약어는 ticker 형태 추정만으로 지우지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].financials = (
        "〔근거: 수치 앵커(KOSIS)〕 매출은 10억 원이다."
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert "(KOSIS)" in layer.beneficiaryCopies["topic1:positive:0"].financials


def test_reader_copy_contract_preserves_parenthesized_source_institution_acronym():
    payload = _topics_report()
    payload["cards"][0]["scenarios"][0]["beneficiaries"][1]["readerCopy"]["evidence"] = (
        "통계청 수치 앵커(KOSIS)를 확인했다."
    )

    Report.model_validate(payload)


@pytest.mark.parametrize("ticker", ["EMBJ3.S", "LCOc1", "GCcv1", "JP10YTN=JBTC"])
def test_reader_contract_removes_reuters_and_alphanumeric_source_tickers(ticker):
    payload = _topics_report()
    beneficiary = payload["cards"][0]["scenarios"][0]["beneficiaries"][1]
    beneficiary["name"] = f"테스트 기업 ({ticker})"
    beneficiary["readerCopy"]["displayName"] = "테스트 기업"

    Report.model_validate(payload)

    beneficiary["readerCopy"]["evidence"] = f"테스트 기업 {ticker} 공시를 확인했다."
    with pytest.raises(ValidationError, match="ticker|읽기|내부"):
        Report.model_validate(payload)


@pytest.mark.parametrize(("section", "value"), [
    ("editorial", "equip_revenue가 늘었다."),
    ("brief", "램리서치 LRCX 매출을 확인한다."),
    ("brief", "매출은 전분기보다 12% QoQ 증가했다."),
])
def test_reader_contract_applies_clean_text_rule_to_all_scan_first_surfaces(section, value):
    payload = _topics_report()
    if section == "editorial":
        payload["editorial"]["deck"] = value
    else:
        payload["cards"][1]["brief"]["summary"] = value

    with pytest.raises(ValidationError, match="metric|ticker|읽기|표시"):
        Report.model_validate(payload)


@pytest.mark.parametrize(("raw_name", "evidence", "forbidden"), [
    ("NewCo (ZZZZ.O)", "NewCo 종목코드 ZZZZ.O 공시를 확인했다.", "ZZZZ"),
    ("Berkshire Hathaway (BRK-B)", "Berkshire Hathaway BRK-B 공시를 확인했다.", "BRK-B"),
    ("엔비디아 (NVDA)", "NVDA.O 공시를 확인했다.", "NVDA"),
    ("관련 섹터", "NewCo ZZZZ.O 공시를 확인했다.", "ZZZZ.O"),
    ("관련 섹터", "Berkshire Hathaway BRK-B 공시를 확인했다.", "BRK-B"),
    ("Embraer (EMBJ3.S)", "Embraer EMBJ3.S 공시를 확인했다.", "EMBJ3.S"),
    ("Brent (LCOc1)", "Brent 종목코드 LCOc1 자료를 확인했다.", "LCOc1"),
    ("Gold (GCcv1)", "Gold 종목코드 GCcv1 자료를 확인했다.", "GCcv1"),
    ("원자재 선물", "유가 선물 LCOc1과 금 선물 GCcv1 움직임을 확인했다.", "LCOc1"),
    ("Japan 10Y (JP10YTN=JBTC)", "JP10YTN=JBTC 자료를 확인했다.", "JP10YTN=JBTC"),
])
def test_fallback_removes_contextual_hyphenated_and_exchange_tickers(
        raw_name, evidence, forbidden):
    """유효한 upstream ticker 변형 하나가 폴백 전체를 중단시키거나 화면에 새면 안 된다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.name = raw_name
    beneficiary.evidence = evidence

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    copy = layer.beneficiaryCopies["topic1:positive:0"]

    assert forbidden not in json.dumps(copy.model_dump(), ensure_ascii=False)
    assert "GCcv1" not in json.dumps(copy.model_dump(), ensure_ascii=False)
    assert copy.displayName == raw_name.split(" (")[0]


@pytest.mark.parametrize("ticker", ["lcoc1", "LcOc1", "gccv1"])
def test_fallback_removes_case_variants_of_known_pointless_rics(ticker):
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = (
        f"원자재 선물 {ticker} 움직임을 확인했다."
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert ticker not in layer.beneficiaryCopies["topic1:positive:0"].evidence


@pytest.mark.parametrize("term", ["PCIe5", "CXL2.0", "Reuters.com", "Node.js", "Xe2", "Gen2"])
def test_reader_contract_and_fallback_preserve_technical_and_source_terms(term):
    """제품 세대·프로토콜·출처 도메인은 거래소 ticker가 아니다."""
    from sector.report_readability import fallback_report_readability

    payload = _topics_report()
    payload["cards"][1]["brief"]["summary"] = f"{term} 관련 신호를 확인한다."
    Report.model_validate(payload)

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = f"{term} 관련 신호를 확인했다."
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    assert term in layer.beneficiaryCopies["topic1:positive:0"].evidence


def test_dynamic_source_ticker_is_removed_from_every_scan_first_surface():
    """고정 사전에 없는 당일 종목 ticker도 그 리포트 안에서는 화면에 노출하지 않는다."""
    payload = _topics_report()
    stock = payload["cards"][0]["scenarios"][0]["beneficiaries"][1]
    stock["name"] = "팔란티어 (PLTR)"
    stock["readerCopy"]["displayName"] = "팔란티어"
    payload["cards"][1]["brief"]["summary"] = "PLTR 계약 확대를 확인한다."

    with pytest.raises(ValidationError, match="ticker|읽기|내부|표시"):
        Report.model_validate(payload)


def test_fallback_naturalizes_dynamic_source_ticker_across_the_whole_report():
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    stock = cards[0].scenarios[0].beneficiaries[1]
    stock.name = "팔란티어 (PLTR)"
    cards[1].title = "PLTR 계약 확대가 오늘 시장의 핵심이다"
    cards[1].phenomenon = "PLTR 계약 확대가 확인됐다."
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    rendered = json.dumps(layer.model_dump(), ensure_ascii=False)
    assert "PLTR" not in rendered
    assert "팔란티어" in rendered


@pytest.mark.parametrize(("raw_name", "expected"), [
    ("퀄컴 (QCOM)", "퀄컴"),
    ("AMD (AMD)", "AMD"),
    ("IBM (IBM)", "IBM"),
    ("SAP (SAP)", "SAP"),
    ("ARM (ARM)", "ARM"),
    ("Meta Platforms (META.O)", "메타"),
    ("Lam Research Corporation (LRCX.O)", "램리서치"),
    ("Applied Materials Inc (AMAT.O)", "어플라이드 머티어리얼즈"),
])
def test_fallback_identity_is_valid_for_alias_and_ticker_named_companies(raw_name, expected):
    """정규화 표시명과 최종 Report 계약은 같은 원천 규칙을 사용해야 한다."""
    from sector.report_readability import fallback_report_readability

    payload = _topics_report(with_readability=False)
    cards = Report.model_validate(payload).cards
    stock = cards[0].scenarios[0].beneficiaries[1]
    stock.name = raw_name
    layer = fallback_report_readability(
        report_id=payload["id"], generated_at=payload["generatedAt"],
        lead_axis=payload["leadAxis"], cards=cards,
    )
    for card in cards:
        card.brief = layer.briefs[card.axis]
        for scenario in card.scenarios:
            for index, beneficiary in enumerate(scenario.beneficiaries):
                beneficiary.readerCopy = layer.beneficiaryCopies[
                    f"{card.axis}:{scenario.polarity}:{index}"
                ]
    payload.update({
        "readerModel": "brief_v1", "editorial": layer.editorial.model_dump(),
        "cards": [card.model_dump() for card in cards],
    })

    report = Report.model_validate(payload)
    assert report.cards[0].scenarios[0].beneficiaries[1].readerCopy.displayName == expected


@pytest.mark.parametrize("phrase", [
    "BV-NAND 양산 수율은 98%다.",
    "AI-PC 수요가 늘었다.",
    "US-EU 협상이 이어진다.",
    "EMIB-T 패키징 전환을 확인했다.",
])
def test_fallback_preserves_hyphenated_technology_and_relation_terms(phrase):
    """하이픈이 있다는 이유만으로 기술명·지역 관계어를 ticker처럼 지우지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = phrase
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert phrase.split()[0] in layer.beneficiaryCopies["topic1:positive:0"].evidence


@pytest.mark.parametrize("ticker", ["DX-Y.NYB", "BRK-B.N"])
def test_fallback_consumes_the_whole_multi_suffix_ticker(ticker):
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = f"시장 지표 {ticker}를 확인했다."
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    text = layer.beneficiaryCopies["topic1:positive:0"].evidence

    assert ticker not in text
    assert ".NYB" not in text and ".N" not in text


def test_fallback_expands_internal_terms_next_to_korean_particles_and_full_dates():
    """한글 조사는 Unicode word라 `\b` 치환을 우회하므로 ASCII 경계로 문장화한다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.evidence = (
        "매출 +12% qoq가 늘고 +3% MoM와 함께 CAPEX가 증가했다. "
        "backlog에 반영된 시점은 @2026-09-03이다."
    )

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = layer.beneficiaryCopies["topic1:positive:0"].evidence
    assert "전분기 대비가" in text
    assert "전월 대비와" in text
    assert "설비투자가" in text and "수주잔고에" in text
    assert "2026년 9월 3일 기준이다" in text
    assert not any(token.lower() in text.lower() for token in (
        "qoq", "mom", "capex", "backlog", "@2026", "기준-03",
    ))


def test_fallback_repairs_comparison_abbreviation_particle_agreement():
    """`MoM이`를 풀어 쓸 때 조사까지 자연스러운 `전월 대비가`가 되어야 한다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[1].beneficiaries[0].rationale = (
        "재고는 +13.7% MoM이 늘어 가격 압박이 커졌다."
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = layer.beneficiaryCopies["topic1:negative:0"].rationale
    assert "전월 대비가" in text
    assert "전월 대비이" not in text


def test_fallback_consumes_postposition_after_equipment_metric_row():
    """장비 숫자 행을 문장으로 바꾼 뒤 원문 조사 `.로`가 잔재하면 안 된다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[1].beneficiaries[1]
    beneficiary.name = "반도체 장비 (KLAC)"
    beneficiary.financials = (
        "equip_revenue KLAC 3.66b(+7.0% QoQ)로, 장비 수요가 확인됐다."
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = layer.beneficiaryCopies["topic1:negative:1"].financials
    assert ".로" not in text and ".," not in text
    assert "장비 수요가 확인됐다" in text


@pytest.mark.parametrize("field", ["evidence", "financials"])
@pytest.mark.parametrize("metric", ["memory_capex", "equip_revenue"])
def test_specialized_fallback_preserves_unverified_numeric_qualification(field, metric):
    """내부 metric 행을 문장화해도 미확인 수치를 확정치로 세탁하지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    if metric == "memory_capex":
        beneficiary.name = "삼성전자 (005930.KS)"
        raw = "memory_capex 005930.KS 18,176.96b원(+42.5% QoQ, 2026-03) ⚠미확인 수치: 18,176.96b원"
    else:
        beneficiary.name = "램리서치 (LRCX)"
        raw = "equip_revenue LRCX 6.72b (+15.1% QoQ @2026-06) ⚠미확인 수치: 6.72b"
    setattr(beneficiary, field, raw)

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = getattr(layer.beneficiaryCopies["topic1:positive:0"], field)
    assert "〔수치 미확인" in text


def test_specialized_fallback_keeps_context_after_the_metric_row():
    """숫자 행을 문장화하면서 뒤의 회사별 정성 근거를 버리지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.name = "삼성전자 (005930.KS)"
    beneficiary.evidence = (
        "memory_capex 005930.KS 18,176.96b원(+42.5% QoQ, 2026-03). "
        "회사 공시에서 신규 평택 공장 승인을 확인했다."
    )

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    text = layer.beneficiaryCopies["topic1:positive:0"].evidence
    assert "18조 1,769억 6천만 원" in text
    assert "신규 평택 공장 승인" in text


def test_followup_research_is_available_to_the_editor_and_numeric_grounding():
    """-3의 핵심 수치처럼 findings-only 근거도 자동 brief가 안전하게 사용할 수 있다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[2].deep_dive["findings"] = [{
        "label": "근거",
        "answer": "후속 조사에서 방산 수주 증가율 77%를 확인했다.",
        "numbers": ["77%"],
        "sources": [{"title": "공식 수주 발표", "published": "2026-09-04"}],
    }]
    draft = _draft_payload()
    draft["takeaways"][2]["text"] = "방산 수주 증가율 77%의 지속 여부를 확인한다."
    draft["briefs"][2]["summary"] = "후속 조사로 확인한 방산 수주 증가율은 77%다."
    draft["briefs"][2]["keyNumbers"] = [{
        "label": "방산 수주", "value": "77%", "context": "후속 조사", "tone": "positive",
    }]
    role = _ReadabilityRole([draft])

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=role,
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "generated"
    assert "77%" in result.output.briefs["topic2"].summary
    assert "77%" in role.prompts[0]


def test_followup_research_failure_is_visible_to_generation_audit_and_fallback():
    """추가 조사 실패는 의미 자격이므로 scan-first 계층에서 숨기지 않는다."""
    from sector.report_readability import (fallback_report_readability,
                                           generate_report_readability)

    cards = _cards_for_generation()
    cards[2].deep_dive = {
        "topic": "방산 계약 검증",
        "conclusion": "현재 근거 범위에서 방향을 보류한다.",
        "findings": [],
        "research_failed": "web timeout",
    }
    fallback = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    assert "추가 연구 제한" in fallback.briefs["topic2"].summary
    assert "web timeout" in fallback.briefs["topic2"].bottomLine

    role = _ReadabilityRole([_draft_payload()])
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=role,
        audit_role=_AuditRole(),
    ))
    assert result.output.mode == "generated"
    assert "researchFailed" in role.prompts[0] and "web timeout" in role.prompts[0]


def test_fallback_scan_first_copy_keeps_qualitative_followup_research_correction():
    """숫자가 없는 후속 확인도 CLI 장애 때 pre-research 현상 뒤에 숨기지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[2].deep_dive = {
        "topic": "방산 계약 승인 검증",
        "conclusion": "",
        "findings": [{
            "label": "근거",
            "answer": "후속 공식 발표에서 최종 승인 거절을 확인했다.",
            "numbers": [],
            "sources": [],
        }],
    }

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert "최종 승인 거절" in layer.briefs["topic2"].summary
    assert "최종 승인 거절" in layer.editorial.takeaways[2].text


def test_fallback_keeps_second_followup_correction_after_a_long_first_finding():
    """첫 번째 조사가 길어도 두 번째 핵심 정정을 단일 clip으로 잃지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[2].deep_dive = {
        "topic": "방산 계약 검증",
        "conclusion": "",
        "findings": [
            {"label": "근거", "answer": "긴 배경 설명이다. " * 40,
             "numbers": [], "sources": []},
            {"label": "근거", "answer": "후속 공식 발표에서 최종 승인 거절을 확인했다.",
             "numbers": [], "sources": []},
        ],
    }
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert "최종 승인 거절" in layer.briefs["topic2"].summary
    assert "최종 승인 거절" in layer.briefs["topic2"].bottomLine
    assert "최종 승인 거절" in layer.editorial.takeaways[2].text


def test_semantic_audit_rejects_invented_cause_even_when_number_exists():
    """같은 +12%에 원문에 없는 원인을 붙인 편집은 숫자 membership만으로 통과하지 않는다."""
    from sector.report_readability import generate_report_readability

    malicious = _draft_payload()
    malicious["briefs"][1]["summary"] = "AI 전력 수요 +12%는 정부 계약 덕분이다."
    audit = _AuditRole([{
        "facts_preserved": False,
        "entities_grounded": False,
        "causality_preserved": False,
        "problems": ["정부 계약 원인은 원문에 없음"],
    }])
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([malicious]),
        audit_role=audit,
    ))

    serialized = json.dumps(result.output.model_dump(), ensure_ascii=False)
    assert audit.calls == 2
    assert result.output.mode == "fallback"
    assert "테슬라" not in serialized and "정부 계약" not in serialized
    assert result.error == "semantic_drift"


def test_fallback_preserves_uncertainty_labels_instead_of_upgrading_claims():
    """편집 장애가 〔가정〕/〔수치 미확인〕을 지워 확정 사실처럼 만들면 안 된다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].title = "AI 전력 수요 +77% 〔수치 미확인〕"
    cards[1].phenomenon = "AI 전력 수요는 +77% 늘었다. 〔가정〕"
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    serialized = json.dumps(layer.model_dump(), ensure_ascii=False)
    assert "〔수치 미확인〕" in layer.editorial.headline
    assert "〔가정〕" in serialized
    assert "+77%" not in [item.value for item in layer.briefs["topic1"].keyNumbers]


def test_long_fallback_keeps_a_trailing_warning_attached_to_its_number():
    """긴 문장을 자를 때 뒤쪽 감사 경고만 잘려 수치가 확정치로 보이면 안 된다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].title = "AI 전력 수요를 점검한다"
    cards[1].phenomenon = (
        "AI 전력 수요는 +77% 늘었다. " + "긴 배경 설명이다. " * 40
        + "⚠미확인 수치: +77%"
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    brief = layer.briefs["topic1"]
    assert "〔수치 미확인: +77%〕" in brief.summary
    assert "+77%" not in [item.value for item in brief.keyNumbers]


def test_fallback_does_not_append_unrelated_late_cautions_or_cut_brackets():
    """clip은 앞 문장과 무관한 후반 가정을 끌어오거나 표식을 반쪽으로 자르지 않는다."""
    from sector.report_readability import _clip

    source = (
        "확인된 변화는 12%다 〔근거: 공식 발표〕. "
        + "검증된 배경 설명이다. " * 35
        + "후반 추정치는 99%다 〔가정: 별도 사건에 대한 추정〕"
    )
    clipped = _clip(source, 320, "원문 참조")

    assert "〔근거: 공식 발표〕" in clipped
    assert "99%" not in clipped and "〔가정:" not in clipped
    assert clipped.count("〔") == clipped.count("〕")


def test_clip_keeps_nearby_numericless_assumption_attached_to_retained_claim():
    """숫자 뒤 짧게 붙은 〔가정〕이 경계 밖이라는 이유로 확정치처럼 잘리면 안 된다."""
    from sector.report_readability import _clip

    source = ("배경 설명 " * 55)[:300] + " 수요 +77% 증가 가능 조건 조건 조건 〔가정〕"
    assert 320 < source.index("〔가정〕") < 380

    clipped = _clip(source, 320, "원문 참조")

    assert "+77%" in clipped
    assert "〔가정〕" in clipped
    assert len(clipped) <= 320


def test_calculation_mismatch_number_is_not_promoted_by_fallback():
    """감사 단계의 계산 불일치 값도 강조 keyNumber 후보에서 제외한다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].title = "계산을 다시 확인한다"
    cards[1].phenomenon = "성장률은 +88%다. ⚠계산 불일치: +88%"
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    brief = layer.briefs["topic1"]
    assert "〔계산 불일치: +88%〕" in brief.summary
    assert "+88%" not in [item.value for item in brief.keyNumbers]


def test_fallback_key_numbers_keep_scale_units_and_skip_dates_and_unverified_values():
    """CLI 장애 폴백도 67만원/$30B를 67/$30으로 축소하거나 날짜를 지표로 올리지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    card = cards[1]
    card.title = "목표가와 계약 규모를 확인한다"
    card.phenomenon = (
        "기준 목표가는 67만원이다. 낙관 목표가는 470만원이다. 계약은 $30B다. "
        "9월 발표이며 6개월 동안 집행된다. ⚠미확인 수치: 1.9%"
    )
    card.deep_dive = {"topic": card.label, "conclusion": "목표가와 계약 규모가 핵심이다."}

    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )
    numbers = layer.briefs["topic1"].keyNumbers
    values = [item.value for item in numbers]

    assert values[:3] == ["67만원", "470만원", "300억 달러"]
    assert not ({"9월", "6개월", "6개", "1.9%"} & set(values))
    assert len({item.context for item in numbers[:3]}) >= 2


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("신규 발행은 +7~10조엔 순증이다.", "+7~10조엔"),
        ("고용은 +5.3만~+5.6만명 범위다.", "+5.3만~+5.6만명"),
        ("계약 규모는 US$30B다.", "300억 달러"),
        ("조달액은 130억 달러다.", "130억 달러"),
        ("MMF 자산은 7조9,800억 달러다.", "7조9,800억 달러"),
        ("총액은 79조3,187억원이다.", "79조3,187억원"),
        ("잔액은 8조1,561억원이다.", "8조1,561억원"),
        ("투자액은 5억 8,230만 달러다.", "5억 8,230만 달러"),
        ("계약은 $500 billion 규모다.", "$500 billion"),
        ("투자는 €4.3 billion이다.", "€4.3 billion"),
        ("차입은 $39.6bn이다.", "$39.6bn"),
        ("밸류는 HK$69.67 million이다.", "HK$69.67 million"),
        ("공급은 20 million barrels/day다.", "20 million barrels/day"),
        ("금리는 25 basis points 움직였다.", "25 basis points"),
        ("금리 변화는 +10bp다.", "+10bp"),
        ("증산 폭은 +548,000 bpd다.", "+548,000 bpd"),
        ("리테일 단가는 $0.090/GB다.", "$0.090/GB"),
        ("HBM 단가는 $297/TBps다.", "$297/TBps"),
        ("용량 단가는 0.105USD/GB다.", "0.105USD/GB"),
        ("대역폭 단가는 312.0USD per TB/s다.", "312.0USD per TB/s"),
        ("차입액은 C$2.6bn이다.", "C$2.6bn"),
        ("조달액은 A$4.2bn이다.", "A$4.2bn"),
        ("거래액은 SGD 3.08bn이다.", "SGD 3.08bn"),
        ("매출은 RMB 8.5bn이다.", "RMB 8.5bn"),
        ("원유 공급은 20백만 배럴/일이다.", "20백만 배럴/일"),
        ("감산 규모는 60만 배럴/일이다.", "60만 배럴/일"),
        ("재고는 1.03억 배럴/일 감소했다.", "1.03억 배럴/일"),
        ("WTI는 91.18달러/배럴이다.", "91.18달러/배럴"),
        ("전력 단가는 150원/kWh다.", "150원/kWh"),
        ("WTI는 $91.18/bbl이다.", "$91.18/bbl"),
    ],
)
def test_fallback_key_numbers_preserve_complete_compound_expressions(source, expected):
    """범위·통화·스케일을 부분 토큰으로 잘라 다른 값처럼 보이게 하지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].title = "복합 수치를 점검한다"
    cards[1].phenomenon = source
    cards[1].deep_dive = {"topic": cards[1].label, "conclusion": "복합 수치가 핵심이다."}
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert layer.briefs["topic1"].keyNumbers[0].value == expected


def test_fallback_plain_text_removes_markdown_without_losing_uncertainty():
    """원문의 강조 문법과 감사 각주는 읽기 문장으로 정리하되 불확실성은 남긴다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[0].title = "**환율**과 `금리`를 함께 본다"
    cards[0].phenomenon = (
        "# 무슨 일이 있었나\n**엔달러 155.93엔**이 움직였다.\n"
        "⚠미확인 수치: 1.9%"
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="macro",
        cards=cards,
    )

    rendered = json.dumps(layer.model_dump(), ensure_ascii=False)
    assert "**" not in rendered and "`" not in rendered
    assert "무슨 일이 있었나. 엔달러" in layer.briefs["macro"].summary
    assert "〔수치 미확인: 1.9%〕" in layer.briefs["macro"].summary
    assert "1.9%" not in [item.value for item in layer.briefs["macro"].keyNumbers]


@pytest.mark.parametrize("source", ["운송량은 20 boats다.", "대기 기간은 5 months다."])
def test_fallback_does_not_turn_an_english_word_prefix_into_a_scale(source):
    """단문 첫 글자 B/M을 billion/million 약어로 잘못 잘라 강조하지 않는다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].title = "정성 설명을 확인한다"
    cards[1].phenomenon = source
    cards[1].deep_dive = {"topic": cards[1].label, "conclusion": "정성 설명이다."}
    cards[1].scenarios = []
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert layer.briefs["topic1"].keyNumbers[0].value == "정성 신호"


def test_fallback_number_context_stays_bound_to_the_number_it_explains():
    """긴 한 문장 안의 뒤 수치가 앞 지표 설명을 문맥으로 재사용하면 안 된다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].title = "금리와 실업률을 구분한다"
    cards[1].phenomenon = (
        "금리는 3%로 유지됐지만 "
        + "정책 배경이 길게 이어진다 " * 8
        + "실업률은 5%로 상승했다."
    )
    cards[1].deep_dive = {"topic": cards[1].label, "conclusion": "두 지표를 함께 확인한다."}
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    key_numbers = {item.value: item.context for item in layer.briefs["topic1"].keyNumbers}
    assert "금리" in key_numbers["3%"] and "3%" in key_numbers["3%"]
    assert "실업률" in key_numbers["5%"] and "5%" in key_numbers["5%"]
    assert all(value.endswith((".", "!", "?", "。", "！", "？", "…"))
               for value in key_numbers.values())


def test_fallback_long_key_number_context_marks_omitted_tail_instead_of_dangling():
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].phenomenon = (
        "노무라는 두 회사 목표가를 각각 67만원과 470만원으로 두고 "
        + "긴 투자 배경을 설명했다 " * 8
        + "두 종목이 저평가라고 주장했다."
    )
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    contexts = [item.context for item in layer.briefs["topic1"].keyNumbers]
    assert all(context.endswith((".", "!", "?", "。", "！", "？", "…"))
               for context in contexts)
    assert all(not context.endswith(("라고", "했고", "이며", "으로"))
               for context in contexts)
    assert all(context.count("〔") == context.count("〕") for context in contexts)
    assert all(context.count("(") == context.count(")") for context in contexts)


def test_number_context_drops_an_unmatched_leading_audit_fragment():
    from sector.report_readability import _number_context

    source = (
        "〔근거: " + "긴 배경 설명 " * 12
        + "〕, KB증권은 삼성전자 목표가 60만원을 제시했다."
    )
    start = source.index("60만원")
    context = _number_context(source, start, start + len("60만원"))

    assert "60만원" in context
    assert context.count("〔") == context.count("〕")
    assert context.count("(") == context.count(")")


def test_numeric_sweep_warning_is_not_promoted_or_trusted():
    """`〔수치 검증: 확인되지 않았다〕` 값은 생성·폴백 모두 확정 근거가 아니다."""
    from sector.report_readability import fallback_report_readability, _grounded_number_tokens

    cards = _cards_for_generation()
    cards[1].title = "수치 검증이 필요한 사건"
    cards[1].phenomenon = (
        "성장률은 26%라고 제시됐다. "
        "〔수치 검증: 다음 수치는 수집 재료에서 확인되지 않았다 — 26%〕"
    )
    cards[1].deep_dive = {"topic": cards[1].label, "conclusion": "추가 확인이 필요하다."}
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    assert "26%" not in _grounded_number_tokens(cards[1])
    assert "26%" not in [item.value for item in layer.briefs["topic1"].keyNumbers]


def test_fallback_does_not_promote_six_month_comparison_period_as_millions():
    """`6M`은 이 코퍼스의 6개월 비교기간이며 600만이라는 핵심 수치가 아니다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].title = "메모리 단가와 비교기간을 구분한다"
    cards[1].phenomenon = "HBM 가격은 $16.5/GB(+3.1% 6M), $297/TBps(-4.8% 6M)다."
    cards[1].deep_dive = {"topic": cards[1].label, "conclusion": "가격 방향을 확인한다."}
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    values = [item.value for item in layer.briefs["topic1"].keyNumbers]
    assert "$16.5/GB" in values and "+3.1%" in values
    assert "$297/TBps" in values and "-4.8%" in values
    assert "6M" not in values


def test_fallback_does_not_infer_value_judgment_from_a_number_sign():
    """비용·금리 상승의 `+`를 자동으로 긍정 색상에 연결하면 의미가 뒤집힌다."""
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    cards[1].title = "비용 방향을 확인한다"
    cards[1].phenomenon = "전쟁 비용이 커지며 WTI는 +0.8% 올랐다."
    cards[1].deep_dive = {"topic": cards[1].label, "conclusion": "비용의 영향을 확인한다."}
    layer = fallback_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
    )

    key_number = layer.briefs["topic1"].keyNumbers[0]
    assert key_number.value == "+0.8%"
    assert key_number.tone == "neutral"


def test_clip_keeps_a_numericless_assumption_qualifier_on_a_long_claim():
    """긴 정성 주장도 끝의 `〔가정〕`만 잘려 확정 사실처럼 보여서는 안 된다."""
    from sector.report_readability import _clip

    source = (
        "AI 수요 증가는 반드시 기업 이익을 끌어올린다. "
        + "조건부 전망 설명 " * 9
        + "〔가정〕"
    )

    clipped = _clip(source, 100, "원문 참조")

    assert "AI 수요 증가" in clipped
    assert "〔가정〕" in clipped


def test_clip_keeps_a_far_trailing_assumption_when_its_claim_started_before_cutoff():
    """같은 문장이 계속되는 한 경계 뒤 거리와 무관하게 감사 자격을 함께 보존한다."""
    from sector.report_readability import _clip

    source = (
        "AI 수요 증가는 반드시 기업 이익을 끌어올린다. "
        + "긴 설명 " * 31
        + "〔가정〕"
    )
    clipped = _clip(source, 100, "원문 참조")

    assert "AI 수요 증가" in clipped
    assert "〔가정〕" in clipped


def test_clip_does_not_attach_an_unseen_late_assumption_to_retained_facts():
    """잘린 뒤에 새로 시작한 전망의 `〔가정〕`을 앞 확정 사실에 고아로 붙이지 않는다."""
    from sector.report_readability import _clip

    prefix = ("확인된 사실과 배경이다. " * 30)[:325]
    source = prefix + ". 별도 장기 전망은 약세다 〔가정〕"

    clipped = _clip(source, 320, "원문 참조")

    assert "별도 장기 전망" not in clipped
    assert "〔가정〕" not in clipped


def test_plain_reader_sentence_marks_a_long_single_sentence_as_truncated():
    """hard clip이 조사·접속사에서 끊긴 문장 조각을 완성 문장처럼 저장하지 않는다."""
    from sector.report_readability import _plain_reader_sentence

    source = "AI 수요가 HBM 공급망을 거쳐 전력과 냉각 설비 수요로 번지면서 " * 12
    text = _plain_reader_sentence(
        source,
        display_name="관련 대상",
        ticker="",
        fallback="원문을 확인한다.",
        limit=100,
    )

    assert len(text) <= 100
    assert text.endswith((".", "!", "?", "。", "！", "？", "〕"))
    assert "원문" in text


def test_generated_readability_rejects_number_attached_to_korean_text():
    """한글 조사 바로 뒤에 붙은 새 수치도 결정적 숫자 감사에서 빠지면 안 된다."""
    from sector.report_readability import generate_report_readability

    malicious = _draft_payload()
    malicious["briefs"][1]["summary"] = "AI 기업 매출99% 증가는 확정됐다."
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([malicious]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("field", ["evidence", "financials"])
def test_generated_copy_cannot_omit_populated_original_detail(field):
    """생성기가 원본 상세를 빈 문장으로 대체하면 결정적 fallback으로 강등한다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 1)
    copy[field] = ""
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "reader_copy_coverage"


def test_cli_copy_cannot_rename_the_beneficiary_at_a_valid_position():
    """axis/polarity/index가 맞아도 표시 대상 자체를 다른 회사로 바꿀 수 없다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    stock = next(item for item in draft["beneficiaryCopies"]
                 if item["axis"] == "topic1"
                 and item["polarity"] == "positive"
                 and item["index"] == 1)
    stock["displayName"] = "테슬라"

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "reader_copy_coverage"


@pytest.mark.parametrize("field", ["evidence", "financials"])
def test_generated_copy_cannot_replace_numeric_original_detail_with_a_placeholder(field):
    """nonempty만 맞추고 원본의 핵심 숫자를 전부 빼는 편집도 거절한다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    stock = next(item for item in draft["beneficiaryCopies"]
                 if item["axis"] == "topic1"
                 and item["polarity"] == "positive"
                 and item["index"] == 1)
    stock[field] = "관련 자료를 확인했다."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("field", ["rationale", "causalChain", "evidence", "financials"])
def test_generated_copy_cannot_move_another_beneficiary_number_onto_this_row(field):
    """축 전체에 있는 숫자라도 다른 수혜주의 회사 근거로 재부착하면 거절한다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    direct = next(item for item in draft["beneficiaryCopies"]
                  if item["axis"] == "topic1"
                  and item["polarity"] == "positive"
                  and item["index"] == 0)
    direct[field] = (
        "직접 섹터의 2026년 3월 분기 전사 설비투자는 "
        "7,865.37십억 원이며, 전분기보다 35.8% 감소했다."
    )

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_ticker_digits_are_not_numeric_evidence_for_reader_copy_claims():
    """000660.KS의 660은 기업 식별자이지 매출·투자 수치가 아니다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    stock = next(item for item in draft["beneficiaryCopies"]
                 if item["axis"] == "topic1"
                 and item["polarity"] == "positive"
                 and item["index"] == 1)
    stock["rationale"] = "SK하이닉스의 확인된 매출 수치는 660이다."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("evidence", [
    "SK하이닉스의 2035년 11월 분기 전사 설비투자는 7,865.37십억 원이며, 전분기보다 35.8% 감소했다.",
    "SK하이닉스의 2026년 3월 분기 영업이익은 7,865.37십억 원이며, 전분기보다 35.8% 감소했다.",
    "SK하이닉스의 2026년 3월 분기 전사 설비투자와 관련된 영업이익은 7,865.37십억 원이며, 전분기보다 35.8% 감소했다.",
    "SK하이닉스의 2026년 3월 분기 전사 설비투자는 7,865.37십억 원이며, 전분기보다 35.8% 증가했다.",
    "SK하이닉스의 2026년 3월 분기 전사 설비투자는 7,865.37십억 원이며, 전분기보다 -35.8% 증가했다.",
    "SK하이닉스의 2026년 3월 분기 전사 설비투자는 7,865.37십억 원이며, 전년보다 35.8% 감소했다.",
])
def test_generated_copy_preserves_period_metric_and_comparison_direction(evidence):
    """숫자 bag이 같아도 기간·지표·증감 방향을 바꾸면 다른 사실이다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    stock = next(item for item in draft["beneficiaryCopies"]
                 if item["axis"] == "topic1"
                 and item["polarity"] == "positive"
                 and item["index"] == 1)
    stock["evidence"] = evidence

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"
    assert "99%" not in json.dumps(result.output.model_dump(), ensure_ascii=False)


def test_generated_copy_cannot_swap_values_between_financial_metrics():
    """숫자 집합이 같아도 매출과 영업이익의 값이 뒤바뀌면 다른 사실이다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.evidence = "직접 섹터의 매출은 10억 원이고 영업이익은 3억 원이다."
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = "직접 섹터의 매출은 3억 원이고 영업이익은 10억 원이다."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_copy_binds_each_direction_to_its_local_metric_clause():
    """인접한 반대 방향 수치가 서로의 증가·감소 단어를 빌려 검증을 우회하지 않는다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = (
        "매출 +10% 증가, 영업이익 -5% 감소."
    )
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = "매출 10% 감소, 영업이익 -5% 감소."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_copy_binds_each_comparison_basis_to_its_local_metric_clause():
    """인접 수치 사이에서 전분기/전년 비교 기준만 맞바꿔도 거절한다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = (
        "매출 +10% QoQ, 영업이익 -5% YoY."
    )
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = "매출 +10% 전년 대비, 영업이익 -5% 전분기 대비."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize(("source", "candidate"), [
    ("2026년 매출 10억 원, 2025년 영업이익 5억 원.",
     "2025년 매출 10억 원, 2026년 영업이익 5억 원."),
    ("2026년 1분기 매출 10억 원, 2025년 4분기 영업이익 5억 원.",
     "2025년 4분기 매출 10억 원, 2026년 1분기 영업이익 5억 원."),
])
def test_generated_copy_binds_each_value_to_its_local_period(source, candidate):
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = candidate

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_copy_binds_each_value_to_its_company():
    """동일 지표의 peer 비교에서도 회사별 값을 맞바꿀 수 없다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = (
        "램리서치 매출 10억 원, ASML 매출 3억 원."
    )
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = "램리서치 매출 3억 원, ASML 매출 10억 원."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize(("source", "candidate"), [
    ("2025년과 2026년 매출은 각각 10억 원과 20억 원이다.",
     "2025년과 2026년 매출은 각각 20억 원과 10억 원이다."),
    ("램리서치와 ASML 매출은 각각 10억 원과 20억 원이다.",
     "램리서치와 ASML 매출은 각각 20억 원과 10억 원이다."),
    ("갑회사와 을회사의 매출은 각각 10억 원과 20억 원이다.",
     "갑회사와 을회사의 매출은 각각 20억 원과 10억 원이다."),
    ("크루소와 코어위브의 매출은 각각 10억 원과 20억 원이다.",
     "크루소와 코어위브의 매출은 각각 20억 원과 10억 원이다."),
    ("A사/B사의 매출은 각각 10억 원과 20억 원이다.",
     "A사/B사의 매출은 각각 20억 원과 10억 원이다."),
    ("매출과 영업이익은 각각 10억 원과 3억 원이다.",
     "매출과 영업이익은 각각 3억 원과 10억 원이다."),
    ("전년과 전분기 증가율은 각각 10%와 5%다.",
     "전년과 전분기 증가율은 각각 5%와 10%다."),
    ("증가율과 감소율은 각각 10%와 5%다.",
     "증가율과 감소율은 각각 5%와 10%다."),
])
def test_generated_copy_preserves_respectively_order(source, candidate):
    """`각각`이 결속한 기간·기업과 값의 순서를 뒤집을 수 없다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = candidate

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize(("source", "candidate"), [
    ("매출은 전년 대비 77% 급등했다.", "매출은 전년 대비 77% 급락했다."),
    ("매출은 전년 대비 77% 폭등했다.", "매출은 전년 대비 77% 폭락했다."),
    ("전망치를 77% 상향했다.", "전망치를 77% 하향했다."),
])
def test_generated_copy_preserves_extended_direction_vocabulary(source, candidate):
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1" and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = candidate
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize(("source", "candidate"), [
    ("매출은 지난해보다 77% 상승했다.", "매출은 지난달보다 77% 상승했다."),
    ("매출은 작년 대비 77% 상승했다.", "매출은 지난달 대비 77% 상승했다."),
    ("매출은 직전 연도보다 77% 상승했다.", "매출은 직전 달보다 77% 상승했다."),
])
def test_generated_copy_preserves_natural_language_comparison_basis(source, candidate):
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1" and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = candidate
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("metric", ["EBITDA", "EPS", "총이익"])
def test_generated_copy_preserves_additional_financial_metric_binding(metric):
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = (
        f"매출과 {metric}는 각각 10억 원과 3억 원이다."
    )
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1" and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = f"매출과 {metric}는 각각 3억 원과 10억 원이다."
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_key_number_context_cannot_rebind_an_unknown_issuer():
    """구조화된 context 뒤쪽에 쓴 회사명도 원문 수치 주체와 결속한다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].phenomenon = "크루소의 2026년 매출은 10억 원이다."
    draft = _draft_payload()
    draft["briefs"][1]["keyNumbers"] = [{
        "label": "매출", "value": "10억 원",
        "context": "코어위브의 2026년 실적", "tone": "neutral",
    }]
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("metric", ["EBITDA", "EPS", "총이익", "ARPU", "GMV"])
def test_key_number_cannot_relabel_revenue_as_another_metric(metric):
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].phenomenon = "2026년 매출은 10억 원이다."
    draft = _draft_payload()
    draft["briefs"][1]["keyNumbers"] = [{
        "label": metric, "value": "10억 원",
        "context": "2026년 실적", "tone": "neutral",
    }]
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize(("source", "candidate"), [
    ("삼성전자의 2026년 상반기 매출은 10억 원이다.",
     "삼성전자의 2026년 하반기 매출은 10억 원이다."),
    ("삼성전자의 올해 1분기 매출은 10억 원이다.",
     "삼성전자의 올해 2분기 매출은 10억 원이다."),
    ("삼성전자의 2026년 연초 매출은 10억 원이다.",
     "삼성전자의 2026년 연말 매출은 10억 원이다."),
])
def test_generated_copy_preserves_half_quarter_and_year_edge_periods(source, candidate):
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1" and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = candidate
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("company", ["테슬라", "코어위브"])
def test_generated_reader_detail_cannot_add_an_unrelated_company(company):
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    beneficiary = cards[1].scenarios[0].beneficiaries[0]
    beneficiary.rationale = "수요 확대의 직접 수혜를 받는다."
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1" and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["rationale"] = f"{company}가 직접 수혜를 받는다."
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_brief_scenario_guide_keeps_numbers_bound_to_its_polarity():
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].thesis = "수요가 10% 증가하면 상방 시나리오가 열린다."
    cards[1].scenarios[1].thesis = "수요가 5% 감소하면 하방 시나리오가 열린다."
    draft = _draft_payload()
    draft["briefs"][1]["scenarioGuide"] = [
        {"polarity": "positive", "condition": "수요가 5% 감소한다.",
         "outcome": "하방 압력이 커진다."},
        {"polarity": "negative", "condition": "수요가 10% 증가한다.",
         "outcome": "상방 여력이 커진다."},
    ]
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize(("source", "candidate"), [
    ("향후 매출은 77% 증가할 수 있다 〔가정〕.", "향후 매출 증가는 확정됐다."),
    ("조건부 전망이다 〔가정〕.", "최종 결과로 확정됐다."),
    ("매출은 약 10억 원으로 추정한다.", "매출은 10억 원으로 확정됐다."),
])
def test_generated_copy_cannot_upgrade_an_assumption_to_a_fact(source, candidate):
    """숫자를 빼더라도 가정·추정·조건부 문장을 확정 사실로 세탁할 수 없다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = candidate

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_copy_cannot_move_an_assumption_marker_to_a_confirmed_number():
    """필드에 가정 표식이 남았다는 이유로 다른 숫자의 확정 승격을 허용하지 않는다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = (
        "매출은 77% 증가할 수 있다 〔가정〕. 영업이익은 12% 증가했다."
    )
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = (
        "매출은 77% 증가했다. 영업이익은 12% 증가할 수 있다 〔가정〕."
    )

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("surface", ["beneficiary", "brief"])
def test_plain_language_assumption_cannot_be_upgraded_to_a_fact(surface):
    """괄호 표식이 없어도 `가정한다`는 수치의 불확실성 자격이다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    source = "향후 매출은 77% 증가한다고 가정한다."
    draft = _draft_payload()
    if surface == "beneficiary":
        cards[1].scenarios[0].beneficiaries[0].evidence = source
        copy = next(item for item in draft["beneficiaryCopies"]
                    if item["axis"] == "topic1"
                    and item["polarity"] == "positive"
                    and item["index"] == 0)
        copy["evidence"] = "향후 매출은 77% 증가했다."
    else:
        cards[1].phenomenon = source
        draft["briefs"][1]["summary"] = "향후 매출은 77% 증가했다."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("qualifier", ["추산한다", "추산된다"])
def test_plain_language_estimate_cannot_be_upgraded_to_a_fact(qualifier):
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = (
        f"향후 매출은 77% 증가할 것으로 {qualifier}."
    )
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1" and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = "향후 매출은 77% 증가했다."
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards, role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize(("raw_name", "raw_evidence", "expected"), [
    ("퀄컴 (QCOM)", "퀄컴 (QCOM) 회사 공시를 확인했다.", "퀄컴 회사 공시"),
    ("Meta Platforms Inc (META.O)",
     "Meta Platforms Inc (META.O) 회사 공시를 확인했다.", "메타 회사 공시"),
    ("Lam Research Corporation (LRCX.O)",
     "Lam Research Corporation (LRCX.O) 회사 공시를 확인했다.", "램리서치 회사 공시"),
])
def test_fallback_removes_parenthesized_source_ticker_before_company_naturalization(
        raw_name, raw_evidence, expected):
    from sector.report_readability import fallback_report_readability

    cards = _cards_for_generation()
    stock = cards[1].scenarios[0].beneficiaries[1]
    stock.name = raw_name
    stock.evidence = raw_evidence
    layer = fallback_report_readability(
        report_id="2026-09-04-6", generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1", cards=cards,
    )
    text = layer.beneficiaryCopies["topic1:positive:1"].evidence

    assert expected in text
    assert "(" not in text and ")" not in text


def test_generated_copy_can_preserve_a_qualified_assumption_number_verbatim():
    """가정 수치는 강조 지표가 아니지만 같은 행의 자격 있는 읽기 사본에는 남아야 한다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    source = "향후 매출은 77% 증가할 수 있다 〔가정〕."
    cards[1].scenarios[0].beneficiaries[0].evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = source

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "generated"
    assert "〔가정〕" in result.output.beneficiaryCopies["topic1:positive:0"].evidence


@pytest.mark.parametrize(("source", "candidate"), [
    ("직접 섹터의 2026년 1분기 매출은 10억 원이다.",
     "직접 섹터의 2027년 4분기 매출은 10억 원이다."),
    ("직접 섹터의 FY2026 매출은 10억 원이다.",
     "직접 섹터의 FY2035 매출은 10억 원이다."),
    ("직접 섹터의 3Q26 매출은 10억 원이다.",
     "직접 섹터의 3Q35 매출은 10억 원이다."),
    ("직접 섹터의 FY26 매출은 10억 원이다.",
     "직접 섹터의 FY35 매출은 10억 원이다."),
    ("직접 섹터의 2026년 매출은 10억 원이다.",
     "직접 섹터의 2035년 매출은 10억 원이다."),
    ("직접 섹터의 6M 매출은 10억 원이다.",
     "직접 섹터의 12M 매출은 10억 원이다."),
    ("직접 섹터의 6개월 매출은 10억 원이다.",
     "직접 섹터의 12개월 매출은 10억 원이다."),
    ("연준은 9월 금리를 동결하고 매출은 10억 원이다.",
     "연준은 10월 금리를 동결하고 매출은 10억 원이다."),
    ("8월 NFP 이후 매출은 10억 원이다.",
     "7월 NFP 이후 매출은 10억 원이다."),
])
def test_generated_copy_cannot_change_quarter_or_fiscal_year(source, candidate):
    """월뿐 아니라 분기·회계연도도 원시 근거와 정확히 결속한다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = source
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = candidate

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_copy_can_naturalize_compact_quarter_without_false_rejection():
    """3Q26→2026년 3분기는 같은 기간의 가독성 변환이다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].scenarios[0].beneficiaries[0].evidence = (
        "직접 섹터의 3Q26 매출은 10억 원이다."
    )
    draft = _draft_payload()
    copy = next(item for item in draft["beneficiaryCopies"]
                if item["axis"] == "topic1"
                and item["polarity"] == "positive"
                and item["index"] == 0)
    copy["evidence"] = "직접 섹터의 2026년 3분기 매출은 10억 원이다."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "generated"
    assert result.error is None


def test_generated_brief_cannot_introduce_a_period_absent_from_its_axis():
    """beneficiary뿐 아니라 scan-first 카드 요약도 새 기간을 만들어낼 수 없다."""
    from sector.report_readability import generate_report_readability

    draft = _draft_payload()
    draft["briefs"][1]["summary"] = "AI 전력 수요는 2035년 4분기에 확정된다."
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_key_number_binds_label_value_and_context_as_one_fact():
    """수치는 같아도 key-number의 지표·기업 label/context를 바꾸면 거절한다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].phenomenon = "삼성전자의 2026년 매출은 10억 원이다. 핵심 변화는 +12%다."
    draft = _draft_payload()
    draft["briefs"][1]["keyNumbers"] = [{
        "label": "영업이익",
        "value": "10억 원",
        "context": "테슬라 실적",
        "tone": "positive",
    }]

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_brief_cannot_upgrade_an_axis_assumption_to_a_fact():
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[1].phenomenon = (
        "기존 변화는 +12%다. 향후 AI 전력 수요는 증가할 수 있다 〔가정〕."
    )
    draft = _draft_payload()
    draft["briefs"][1]["summary"] = "향후 AI 전력 수요 증가는 확정됐다."
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_readability_rejects_number_attached_to_ascii_metric_text():
    """`growth99%` 같은 compact 영문 metric도 새 수치 감사를 우회하지 못한다."""
    from sector.report_readability import generate_report_readability

    malicious = _draft_payload()
    malicious["briefs"][1]["summary"] = "AI 기업 growth99% 증가는 확정됐다."
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([malicious]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


@pytest.mark.parametrize("summary", [
    "AI 기업 growth99억 원 매출은 확정됐다.",
    "AI 기업 revenue99 USD 매출은 확정됐다.",
    "AI 전력 설비 ASML99GW 계약은 확정됐다.",
])
def test_generated_readability_rejects_ascii_attached_numbers_with_clear_units(summary):
    """ASCII 식별자에 붙어도 통화·금액·전력 단위가 있으면 숫자 감사 대상이다."""
    from sector.report_readability import generate_report_readability

    malicious = _draft_payload()
    malicious["briefs"][1]["summary"] = summary
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([malicious]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"


def test_generated_readability_rejects_whitespace_only_required_copy():
    """형식상 필드만 있고 읽을 내용이 없는 CLI 출력은 발행 가능한 편집본이 아니다."""
    from sector.report_readability import generate_report_readability

    empty = _draft_payload()
    empty["briefs"][1]["summary"] = "   "
    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([empty]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ValidationError"
    assert result.output.briefs["topic1"].summary.strip()


def test_semantic_audit_cannot_approve_a_candidate_while_reporting_problems():
    """감사 boolean과 problems가 충돌하면 안전하게 거절해야 한다."""
    from sector.report_readability import generate_report_readability

    audit = _AuditRole([{
        "facts_preserved": True,
        "entities_grounded": True,
        "causality_preserved": True,
        "problems": ["정부 계약 원인은 원문에 없음"],
    }])
    malicious = _draft_payload()
    malicious["briefs"][1]["summary"] = "AI 전력 수요 +12%는 정부 계약 덕분이다."

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=_cards_for_generation(),
        role=_ReadabilityRole([malicious]),
        audit_role=audit,
    ))

    assert result.output.mode == "fallback"
    assert result.error == "semantic_drift"


def test_assumption_only_number_cannot_be_laundered_into_a_generated_key_fact():
    """추가 연구의 '가정' 숫자는 감사자가 실수해도 공식 확인치로 승격되지 않는다."""
    from sector.report_readability import generate_report_readability

    cards = _cards_for_generation()
    cards[2].deep_dive["findings"] = [{
        "label": "가정",
        "answer": "방산 수주 증가율을 77%로 가정한다.",
        "numbers": ["77%"],
        "sources": [],
    }]
    draft = _draft_payload()
    draft["takeaways"][2]["text"] = "공식 조사로 방산 수주 77%를 확인했다."
    draft["briefs"][2]["summary"] = "공식 조사로 방산 수주 77%를 확인했다."
    draft["briefs"][2]["keyNumbers"] = [{
        "label": "공식 수주", "value": "77%", "context": "공식 조사", "tone": "positive",
    }]

    result = asyncio.run(generate_report_readability(
        report_id="2026-09-04-6",
        generated_at="2026-09-04T18:30:00+09:00",
        lead_axis="topic1",
        cards=cards,
        role=_ReadabilityRole([draft]),
        audit_role=_AuditRole(),
    ))

    assert result.output.mode == "fallback"
    assert result.error == "ungrounded_numeric_tokens"
    assert "77%" not in [item.value for item in result.output.briefs["topic2"].keyNumbers]


def test_pipeline_persists_readability_and_records_editorial_cli(monkeypatch, tmp_path):
    """회귀: 독립 유틸만 동작하고 정규 axes 파이프라인 JSON에서 빠지는 배선 오류를 막는다."""
    from sector import report_axes
    from sector.report_pipeline import run_report_pipeline
    from sector.store import SectorStore

    cards = _cards_for_generation()
    for card in cards:
        card.deep_dive["findings"] = [{
            "label": "근거",
            "answer": (
                "공식 자료에서 핵심 변화 +12%와 전사 설비투자 "
                "7,865.37b원, -35.8% QoQ를 확인했다."
            ),
            "numbers": ["+12%", "7,865.37b원", "-35.8%"],
            "sources": [{"title": "공식 자료", "published": "2026-09-04"}],
        }]

    async def fake_axes_flow(**kwargs):
        del kwargs
        return deepcopy(cards), [], "topic1"

    monkeypatch.setattr(report_axes, "run_axes_flow", fake_axes_flow)
    role = _ReadabilityRole([_draft_payload()])
    report = asyncio.run(run_report_pipeline(
        SectorStore(tmp_path),
        now=__import__("datetime").datetime.fromisoformat("2026-09-04T09:30:00+00:00"),
        seq=6,
        roles={"article": role, "cross": _AuditRole()},
        report_format="axes",
        live_research=False,
    ))

    assert report.id == "2026-09-04-6"
    assert report.readerModel == "brief_v1"
    assert report.editorial and report.editorial.baseReportId == report.id
    assert all(card.brief is not None for card in report.cards if not card.error)
    assert all(beneficiary.readerCopy is not None
               for card in report.cards for scenario in card.scenarios
               for beneficiary in scenario.beneficiaries)
    assert report.diagnostics["readability"]["mode"] == "generated"
    stage = next(stage for stage in report.pipeline.stages if stage.key == "readability")
    assert len(stage.io["llm_calls"]) == 2
    assert report.publish_status == "ok"
