"""시황 리포트 Phase 2 계약 — 전 스테이지 공유. 뷰어 호환(evidence 문자열·items 문자열) +
additive 관측 필드(evidence_refs·io). 스펙 v3."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Confidence = Literal["낮", "중", "높"]
ClaimStatus = Literal["verified", "unverified", "rejected"]


class EvidenceRef(BaseModel):
    kind: Literal["card", "news", "metric", "price"]
    id: str
    title: str = ""
    ts: str = ""
    excerpt: str = ""
    source: str = ""
    url: str = ""


class EventCluster(BaseModel):
    cluster_id: str
    title: str
    topics: list[str] = Field(default_factory=list)
    axis: str = "B"
    direction: str = "neutral"
    members: list[EvidenceRef] = Field(default_factory=list)
    representative_excerpt: str = ""


class Anchor(BaseModel):
    anchor_id: str
    metric: str
    entity: str = ""
    period: str = ""
    value: float
    unit: str = ""
    delta_pct: float | None = None
    as_of: str = ""
    source: str = ""
    # 사실성 감사(2026-07-23) P0-2: 비교의 정체성을 코드가 명시 — LLM이 QoQ를
    # YoY로 추측 표기한 확정 오류 2건(SK -35.8%, GOOGL +28.1%)의 근본 수정
    prev_period: str = ""
    prev_value: float | None = None
    comparison_kind: str = ""     # MoM|QoQ|YoY|nM|DoD|nD — 기간 차로 코드가 판정


class NumericFact(BaseModel):
    """LLM이 '이 anchor의 이 값을 인용했다'고 선언 — 코드가 정체성 대조(스펙: 숫자는 코드가).

    field="delta_pct"면 anchor.delta_pct와 대조(변화율 인용 지원 — code review B2)."""

    anchor_id: str
    value: float
    field: Literal["value", "delta_pct"] = "value"


class ReportClaim(BaseModel):
    claim_id: str
    title: str
    confidence: Confidence = "낮"
    status: ClaimStatus = "unverified"
    trigger: str = ""
    mechanism: str = ""
    evidence: list[str] = Field(default_factory=list)               # 뷰어 표시 문자열
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)  # typed(additive)
    anchor_refs: list[str] = Field(default_factory=list)
    numeric_facts: list[NumericFact] = Field(default_factory=list)
    precedent: str = ""
    precedent_grounded: bool = False
    precedent_case_ids: list[str] = Field(default_factory=list)  # 검증된 episode_id 보존
    counter: str = ""
    stance: str = ""
    matched_rules: list[str] = Field(default_factory=list)
    watch_signals: list[str] = Field(default_factory=list)  # 관찰 선행 신호+현재 상태(벤치마크 ⑥)
    load_bearing: bool = False
    as_of: str = ""


class FinalOpinion(BaseModel):
    text: str
    confidence: Confidence


class StageIO(BaseModel):
    key: str
    label: str
    note: str = ""
    in_count: int = 0
    out_count: int = 0
    dropped: list[dict] = Field(default_factory=list)
    elapsed_ms: int = 0


class StageResult(BaseModel):
    output: Any                       # 필수 — 빈 결과도 [] / "" 로 명시
    io: StageIO
    error: str | None = None

    @field_validator("output")
    @classmethod
    def _no_none(cls, v):             # Any 타입이라 검증으로 None 차단(code review SF5)
        if v is None:
            raise ValueError("StageResult.output은 None 금지 — 빈 결과는 []/\"\"로")
        return v


class PipelineStage(BaseModel):
    key: str
    label: str
    note: str = ""
    items: list[str] = Field(default_factory=list)   # 문자열만 — 뷰어 렌더 안전
    sources: list[dict] = Field(default_factory=list)
    io: dict | None = None                            # additive 관측치(뷰어 무시)


class ReportPipeline(BaseModel):
    stages: list[PipelineStage] = Field(default_factory=list)


class ClaimVerdict(BaseModel):
    claim_id: str
    status: ClaimStatus
    reasons: list[str] = Field(default_factory=list)
    adjusted_confidence: Confidence = "낮"


class ResearchQuestion(BaseModel):
    """드래프트가 남긴 구멍 — '논증 완성에 무엇이 더 필요한가' (Phase 4)."""

    qid: str
    question: str
    why_needed: str = ""       # 어느 논증 단계의 어떤 구멍인가
    expected_form: str = ""    # 수치|사실|전망
    search_hint: str = ""


class ResearchSource(BaseModel):
    url: str
    title: str = ""
    published: str = ""        # 발행 시점(알 수 있으면 ISO/자연어)


class ResearchFinding(BaseModel):
    qid: str
    answer: str = ""
    numbers: list[str] = Field(default_factory=list)   # 답에서 쓴 수치 문자열(감사용)
    sources: list[ResearchSource] = Field(default_factory=list)
    label: Literal["근거", "가정"] = "가정"            # 출처 없으면 코드가 '가정' 강등
    error: str = ""


class ArticleDraft(BaseModel):
    """12h 재료로 만든 글 뼈대 — 핵심 질문·지배 방정식·섹션 논지·조사 질문."""

    core_question: str
    one_line: str = ""                    # 잠정 한 줄 요약(헤드라인 후보)
    governing_equation: str = ""
    skeleton: list[str] = Field(default_factory=list)
    research_questions: list[ResearchQuestion] = Field(default_factory=list)


ReadabilityAxis = Literal["macro", "memory", "other", "topic1", "topic2"]
ReadabilityTone = Literal["positive", "negative", "neutral", "warning"]


# Reuters의 선물 RIC처럼 점 없이 대소문자가 섞인 코드(LCOc1, GCcv1)는
# 일반 단어와 구분하려고 IGNORECASE가 없는 별도 패턴으로 검사한다.
_READER_MIXED_CASE_RIC_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{1,6}[a-z]{1,2}[0-9]{1,3}(?![A-Za-z0-9])"
)


class _StrictReadabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReportEditorialTakeaway(_StrictReadabilityModel):
    axis: ReadabilityAxis
    title: str = Field(min_length=1, max_length=30)
    text: str = Field(min_length=1, max_length=180)


class ReportEditorial(_StrictReadabilityModel):
    """원문 사실을 바꾸지 않고 같은 리포트에 붙이는 읽기 순서 계층.

    자동 산출물은 baseReportId가 자신의 id이고, 기존 수동 편집본은 별도 원본
    id를 가리킨다. 두 형태를 모두 보존한다.
    """

    label: str = Field(min_length=1, max_length=30)
    baseReportId: str = Field(min_length=1, max_length=80)
    baseGeneratedAt: str
    editedAt: str
    headline: str = Field(min_length=1, max_length=100)
    deck: str = Field(min_length=1, max_length=240)
    takeaways: list[ReportEditorialTakeaway] = Field(min_length=3, max_length=3)

    @field_validator("baseGeneratedAt", "editedAt")
    @classmethod
    def _aware_datetime(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("읽기 편집 시각은 ISO 8601 date-time이어야 함") from exc
        if parsed.tzinfo is None:
            raise ValueError("읽기 편집 시각에는 timezone이 필요")
        return value

    @model_validator(mode="after")
    def _unique_axes(self):
        axes = [item.axis for item in self.takeaways]
        if len(set(axes)) != 3:
            raise ValueError("편집 요약은 서로 다른 세 축이 정확히 하나씩 필요")
        return self


class AxisBriefKeyNumber(_StrictReadabilityModel):
    label: str = Field(min_length=1, max_length=30)
    value: str = Field(min_length=1, max_length=40)
    context: str = Field(min_length=1, max_length=80)
    tone: ReadabilityTone


class AxisBriefFlowItem(_StrictReadabilityModel):
    label: str = Field(min_length=1, max_length=50)
    detail: str = Field(min_length=1, max_length=100)
    tone: ReadabilityTone


class AxisBriefScenarioGuide(_StrictReadabilityModel):
    polarity: Literal["positive", "negative"]
    condition: str = Field(min_length=1, max_length=180)
    outcome: str = Field(min_length=1, max_length=180)


class AxisBriefWatchItem(_StrictReadabilityModel):
    label: str = Field(min_length=1, max_length=50)
    current: str = Field(min_length=1, max_length=120)
    trigger: str = Field(min_length=1, max_length=180)


class AxisBrief(_StrictReadabilityModel):
    headline: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=320)
    keyNumbers: list[AxisBriefKeyNumber] = Field(min_length=1, max_length=6)
    flow: list[AxisBriefFlowItem] = Field(min_length=2, max_length=5)
    scenarioGuide: list[AxisBriefScenarioGuide] = Field(min_length=2, max_length=2)
    watchlist: list[AxisBriefWatchItem] = Field(min_length=1, max_length=5)
    bottomLine: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def _one_guide_per_polarity(self):
        if {item.polarity for item in self.scenarioGuide} != {"positive", "negative"}:
            raise ValueError("시나리오 가이드는 positive/negative가 정확히 하나씩 필요")
        return self


def _iter_reader_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_reader_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_reader_strings(item)


def _reader_surface_contract_problem(value: object) -> bool:
    """brief_v1의 모든 표시 문자열에 readerCopy와 같은 금지 규칙을 적용한다."""
    internal = re.compile(
        r"(?:(?<![A-Za-z0-9_])[A-Za-z0-9][A-Za-z0-9.,]*_[A-Za-z0-9_]+(?![A-Za-z0-9_])|"
        r"(?<![A-Za-z])(?:QoQ|MoM|YoY|DoD|WoW|CAPEX|backlog)(?![A-Za-z])|"
        r"@\d{4}-\d{2}(?:-\d{2})?|\d[\d,.]*\s*b원)", re.I)
    known_ticker = re.compile(
        r"(?:\d{4,6}\.[A-Za-z0-9]{1,8}|"
        r"(?<![A-Za-z0-9.])(?:LRCX|AMAT|KLAC|MU|GOOGL|GOOG|MSFT|AMZN|ORCL|AVGO|"
        r"BRCM|META|NVDA|INTC|QCOM|AAPL|TSLA|TSM|BRK(?:-[AB])?)"
        r"(?:\.[A-Za-z0-9]{1,8})?(?![A-Za-z0-9.]))", re.I)
    contextual = re.compile(
        r"(?<![A-Za-z0-9])(?:종목\s*코드|티커|ticker)\s*[:：]?\s*"
        r"[A-Za-z0-9][A-Za-z0-9=.-]{0,63}", re.I)
    qualified = re.compile(
        r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9]{1,15}(?:-[A-Za-z0-9]{1,8})?"
        r"(?:\.[A-Za-z0-9]{1,8})+|[A-Za-z][A-Za-z0-9]{1,31}=[A-Za-z0-9]{1,32}|"
        r"\d{4,6}(?:\.[A-Za-z0-9]{1,8})+)(?![A-Za-z0-9])", re.I)
    parenthesized = re.compile(
        r"\(\s*(?P<code>[A-Za-z0-9][A-Za-z0-9=.-]{0,63})\s*\)", re.I)
    allowed = {
        "AI", "GPU", "CPU", "HBM", "DRAM", "NAND", "CPI", "PPI", "GDP",
        "ETF", "FX", "USD", "KRW", "JPY", "EUR", "API", "KST", "UTC",
        "ASML", "KLA", "TSMC", "KOSIS", "FRED", "SEC", "IMF", "BIS", "OECD",
        "EIA", "IEA", "BEA", "BLS", "FED", "BOJ", "ECB", "PBOC", "RBNZ",
        "CME", "WSJ", "CNBC", "USTR", "FDA", "FTC", "FCC", "EPA", "MOF",
        "NBS", "CEO", "IPO", "EPS", "EBITDA", "FCF", "PMI", "SOFR", "TIPS",
        "JGB", "DXY", "WTI", "LNG", "ADR", "YTD", "QT", "TAM", "ASP", "MOU",
        "UAE", "EU", "GMT", "EDT", "SGT",
    }
    for text in _iter_reader_strings(value):
        if (internal.search(text) or known_ticker.search(text)
                or contextual.search(text) or qualified.search(text)
                or _READER_MIXED_CASE_RIC_RE.search(text)):
            return True
        if any(match.group("code") not in allowed
               for match in parenthesized.finditer(text)):
            return True
    return False


class AxisBeneficiaryReaderCopy(_StrictReadabilityModel):
    """원시 분석 필드를 보존하면서 화면에 쓰는 자연어 사본."""

    displayName: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=320)
    causalChain: str = Field(min_length=1, max_length=320)
    evidence: str = Field(max_length=500)
    financials: str = Field(max_length=500)

    @model_validator(mode="after")
    def _reader_facing_text_only(self):
        ticker_suffix = re.compile(
            r"\s*\((?P<code>[^()\s]{1,64})\)\s*$",
        )
        internal = re.compile(
            r"(?:(?<![A-Za-z0-9_])[A-Za-z0-9][A-Za-z0-9.,]*_[A-Za-z0-9_]+(?![A-Za-z0-9_])|"
            r"(?<![A-Za-z])(?:QoQ|MoM|YoY|DoD|WoW|CAPEX|backlog)(?![A-Za-z])|"
            r"@\d{4}-\d{2}(?:-\d{2})?|\d[\d,.]*\s*b원)",
            re.I,
        )
        ticker_token = re.compile(
            r"(?:\d{4,6}\.[A-Z]{1,4}|"
            r"(?<![A-Z0-9.])(?:LRCX|AMAT|KLAC|MU|GOOGL|GOOG|MSFT|AMZN|ORCL|AVGO|"
            r"BRCM|META|NVDA|INTC|QCOM|AAPL|TSLA|TSM|BRK(?:-[AB])?)"
            r"(?:\.[A-Z]{1,4})?(?![A-Z0-9.]))",
            re.I,
        )
        contextual_ticker = re.compile(
            r"(?<![A-Za-z0-9])(?:종목\s*코드|티커|ticker)\s*[:：]?\s*"
            r"[A-Za-z0-9][A-Za-z0-9=.-]{0,63}",
            re.I,
        )
        qualified_ticker = re.compile(
            r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9]{1,15}(?:-[A-Za-z0-9]{1,8})?"
            r"(?:\.[A-Za-z0-9]{1,8})+|[A-Za-z][A-Za-z0-9]{1,31}=[A-Za-z0-9]{1,32}|"
            r"\d{4,6}(?:\.[A-Za-z0-9]{1,8})+)(?![A-Za-z0-9])", re.I
        )
        parenthesized_code = re.compile(
            r"\(\s*(?P<code>[A-Za-z0-9][A-Za-z0-9=.-]{0,63})\s*\)", re.I)
        non_ticker_acronyms = {
            "AI", "GPU", "CPU", "HBM", "DRAM", "NAND", "CPI", "PPI",
            "GDP", "ETF", "FX", "USD", "KRW", "JPY", "EUR", "API", "KST", "UTC",
            "ASML", "KLA", "TSMC", "KOSIS", "FRED", "SEC", "IMF", "BIS", "OECD",
            "EIA", "IEA", "BEA", "BLS", "FED", "BOJ", "ECB", "PBOC", "RBNZ",
            "CME", "WSJ", "CNBC", "USTR", "FDA", "FTC", "FCC", "EPA", "MOF",
            "NBS", "CEO", "IPO", "EPS", "EBITDA", "FCF", "PMI", "SOFR", "TIPS",
            "JGB", "DXY", "WTI", "LNG", "ADR", "YTD", "QT", "TAM", "ASP", "MOU",
            "UAE", "EU", "GMT", "EDT", "SGT",
        }
        values = (
            self.displayName, self.rationale, self.causalChain,
            self.evidence, self.financials,
        )
        if any(internal.search(value) for value in values):
            raise ValueError("readerCopy 읽기 문장에는 내부 metric·비교 약어·b원 표기를 쓰지 않음")
        if any(ticker_token.search(value) or contextual_ticker.search(value)
               or qualified_ticker.search(value)
               or _READER_MIXED_CASE_RIC_RE.search(value)
               for value in values):
            raise ValueError("readerCopy 읽기 문장에는 내부 ticker를 쓰지 않음")
        if any(
                match.group("code") not in non_ticker_acronyms
                for value in values for match in parenthesized_code.finditer(value)):
            raise ValueError("readerCopy 읽기 문장에는 괄호 ticker를 쓰지 않음")
        # 표시명 끝의 괄호가 allowlist 설명 약어가 아니면 위 검사와 같은 의미다.
        if ticker_suffix.search(self.displayName):
            suffix = ticker_suffix.search(self.displayName).group("code").upper()
            if (re.fullmatch(r"[A-Z0-9][A-Z0-9=.-]{0,63}", suffix)
                    and suffix not in non_ticker_acronyms):
                raise ValueError("readerCopy 표시명에는 괄호 ticker를 쓰지 않음")
        return self


class Report(BaseModel):
    id: str
    seq: int
    generatedAt: str
    title: str
    window: dict
    overview: str = ""
    finalOpinion: FinalOpinion
    claims: list[ReportClaim] = Field(default_factory=list)
    pipeline: ReportPipeline
    diagnostics: dict = Field(default_factory=dict)
    article: str = ""                                  # Phase 4 — 완결 논증 글(markdown), 빈 값=미생성
    article_meta: dict = Field(default_factory=dict)   # skeleton·질문·리서치 요약·미확인 수치
    # 발행 안전성(2026-07-24 리뷰): 검증 통과 주장 0건이면 hold — 제목·결론 단정 금지
    publish_status: Literal["ok", "hold"] = "hold"
    # v2 3축 카드(2026-07-24 재설계): format=="axes"면 cards가 결과물 본체 —
    # claims/최종의견/완결 글은 미사용(legacy 전용)
    format: Literal["legacy", "axes"] = "legacy"
    # topics_v1가 없으면 역사적 macro/memory/other 축 계약이다.
    axisModel: Literal["topics_v1"] | None = None
    leadAxis: Literal["macro", "topic1", "topic2"] | None = None
    # 새 자동 산출물만 식별하는 계약 버전. 과거 topics_v1에는 없을 수 있지만,
    # 값이 있으면 editorial + 전 카드 brief가 더 이상 선택 필드가 아니다.
    readerModel: Literal["brief_v1"] | None = Field(
        default=None, exclude_if=lambda value: value is None)
    editorial: ReportEditorial | None = Field(
        default=None, exclude_if=lambda value: value is None)
    cards: list["AxisCard"] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_axis_contract(self):
        if self.editorial and self.editorial.baseReportId == self.id:
            if (self.editorial.baseGeneratedAt != self.generatedAt
                    or self.editorial.editedAt != self.generatedAt):
                raise ValueError(
                    "self-integrated editorial은 baseGeneratedAt/editedAt이 "
                    "Report.generatedAt과 같아야 함")
        if self.format != "axes":
            if (self.axisModel is not None or self.leadAxis is not None
                    or self.readerModel is not None):
                raise ValueError("axisModel/leadAxis/readerModel은 axes 형식에서만 사용")
            return self

        axes = [card.axis for card in self.cards]
        if self.axisModel is None:
            if len(axes) != 3 or set(axes) != {"macro", "memory", "other"}:
                raise ValueError("기존 axes 리포트는 macro/memory/other 카드가 정확히 하나씩 필요")
            if self.leadAxis is not None:
                raise ValueError("leadAxis는 topics_v1 리포트에만 사용")
            if self.readerModel is not None:
                raise ValueError("readerModel은 topics_v1 리포트에만 사용")
            if self.editorial and {item.axis for item in self.editorial.takeaways} != {
                    "macro", "memory", "other"}:
                raise ValueError("기존 axes 편집 요약은 macro/memory/other 축이어야 함")
            return self

        if len(axes) != 3 or set(axes) != {"macro", "topic1", "topic2"}:
            raise ValueError("topics_v1 리포트는 macro/topic1/topic2 카드가 정확히 하나씩 필요")

        by_axis = {card.axis: card for card in self.cards}
        if not self.leadAxis or self.leadAxis not in by_axis:
            raise ValueError("leadAxis는 리포트 카드 중 하나여야 함")
        if self.title != by_axis[self.leadAxis].title:
            raise ValueError("리포트 제목은 leadAxis 카드 제목과 같아야 함")
        if self.editorial and {item.axis for item in self.editorial.takeaways} != {
                "macro", "topic1", "topic2"}:
            raise ValueError("topics_v1 편집 요약은 macro/topic1/topic2 축이어야 함")
        if self.readerModel == "brief_v1":
            if self.editorial is None or self.editorial.baseReportId != self.id:
                raise ValueError("readerModel=brief_v1은 self-integrated editorial이 필요")
            if any(card.brief is None for card in self.cards):
                raise ValueError("readerModel=brief_v1은 모든 카드의 brief가 필요")
            reader_surface = {
                "editorial": {
                    "headline": self.editorial.headline,
                    "deck": self.editorial.deck,
                    "takeaways": [item.model_dump() for item in self.editorial.takeaways],
                },
                "briefs": [card.brief.model_dump() for card in self.cards if card.brief],
            }
            if _reader_surface_contract_problem(reader_surface):
                raise ValueError(
                    "readerModel=brief_v1 표시 문장에는 내부 metric·비교 약어·ticker를 쓸 수 없음")
            if any(item.readerCopy is None
                   for card in self.cards for scenario in card.scenarios
                   for item in scenario.beneficiaries):
                raise ValueError("readerModel=brief_v1은 모든 영향 항목의 readerCopy가 필요")
            for card in self.cards:
                for scenario in card.scenarios:
                    for item in scenario.beneficiaries:
                        if item.evidence.strip() and not item.readerCopy.evidence.strip():
                            raise ValueError("readerCopy는 원본 근거를 비울 수 없음")
                        if item.financials.strip() and not item.readerCopy.financials.strip():
                            raise ValueError("readerCopy는 원본 재무 수치를 비울 수 없음")
                        ticker_match = (re.search(
                            r"\s*\((?P<ticker>[^()\s]{1,64})\)\s*$",
                            item.name) if item.kind == "stock" else None)
                        base_name = (item.name[:ticker_match.start()].strip()
                                     if ticker_match else item.name.strip())
                        display_aliases = {base_name}
                        if ticker_match:
                            ticker = ticker_match.group("ticker").upper()
                            display_aliases.update(filter(None, ({
                                "005930.KS": "삼성전자", "000660.KS": "SK하이닉스",
                                "LRCX": "램리서치", "AMAT": "어플라이드 머티어리얼즈",
                                "KLAC": "KLA", "MU": "마이크론", "GOOGL": "알파벳",
                                "GOOG": "알파벳", "META": "메타", "MSFT": "마이크로소프트",
                                "AMZN": "아마존", "ORCL": "오라클", "AVGO": "브로드컴",
                                "BRCM": "브로드컴", "NVDA": "엔비디아", "INTC": "인텔",
                                "QCOM": "퀄컴", "AAPL": "애플", "TSLA": "테슬라",
                                "TSM": "TSMC", "BRK": "버크셔 해서웨이",
                            }.get(ticker),)))
                            root = re.split(r"[.\-=]", ticker, maxsplit=1)[0]
                            mapped_root = {
                                "LRCX": "램리서치", "AMAT": "어플라이드 머티어리얼즈",
                                "KLAC": "KLA", "MU": "마이크론", "GOOGL": "알파벳",
                                "GOOG": "알파벳", "META": "메타", "MSFT": "마이크로소프트",
                                "AMZN": "아마존", "ORCL": "오라클", "AVGO": "브로드컴",
                                "BRCM": "브로드컴", "NVDA": "엔비디아", "INTC": "인텔",
                                "QCOM": "퀄컴", "AAPL": "애플", "TSLA": "테슬라",
                                "TSM": "TSMC", "BRK": "버크셔 해서웨이",
                            }.get(root)
                            if mapped_root:
                                display_aliases.add(mapped_root)
                            tokens = tuple(dict.fromkeys((ticker, root)))
                            if root in {"ASML", "KLA"}:
                                tokens = ((ticker,) if ticker != root else ())
                            patterns = [re.compile(
                                rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
                                re.I,
                            ) for token in tokens]
                            if any(pattern.search(value)
                                   for pattern in patterns for value in (
                                    item.readerCopy.displayName, item.readerCopy.rationale,
                                    item.readerCopy.causalChain, item.readerCopy.evidence,
                                    item.readerCopy.financials)):
                                raise ValueError("readerCopy는 원본 종목 ticker를 노출할 수 없음")
                        if item.readerCopy.displayName.strip() not in display_aliases:
                            raise ValueError("readerCopy 표시명은 원본 영향 대상을 바꿀 수 없음")

        keys: list[str] = []
        for card in self.cards:
            if not card.label.strip() or not card.topicKey.strip() or not card.title.strip():
                raise ValueError("topics_v1 카드는 label, topicKey, title이 필요")
            keys.append(card.topicKey.strip())
            if card.axis == "macro" and (card.label != "거시" or card.topicKey != "macro"):
                raise ValueError("macro 카드는 label=거시, topicKey=macro여야 함")
            if card.error:
                if card.scenarios:
                    raise ValueError("오류 카드는 scenarios가 비어 있어야 함")
                continue
            polarities = [scenario.polarity for scenario in card.scenarios]
            if len(polarities) != 2 or set(polarities) != {"positive", "negative"}:
                raise ValueError("정상 카드는 positive/negative 시나리오가 정확히 하나씩 필요")
            for scenario in card.scenarios:
                directions = {item.direction for item in scenario.beneficiaries}
                if not {"direct", "indirect"}.issubset(directions):
                    raise ValueError("각 시나리오는 direct/indirect 영향을 모두 포함해야 함")
                for item in scenario.beneficiaries:
                    required_fields = {"kind", "direction", "polarity", "causalChain", "evidence"}
                    if not required_fields.issubset(item.model_fields_set):
                        raise ValueError("topics_v1 영향에는 의미 필드를 모두 명시해야 함")
                    if not item.causalChain.strip():
                        raise ValueError("모든 영향에는 causalChain이 필요")
                    if item.kind == "stock":
                        if not re.fullmatch(r".+\s\([^)]+\)", item.name.strip()):
                            raise ValueError("종목명은 회사명 (티커) 형식이어야 함")
                        if not item.evidence.strip():
                            raise ValueError("종목 영향에는 회사별 evidence가 필요")
        if len(set(keys)) != 3:
            raise ValueError("topics_v1 카드 topicKey는 서로 달라야 함")
        return self


# ── v2 3축 카드 계약 (2026-07-24 재설계 — 매크로/메모리/그 외) ────────────────
class AxisBeneficiary(BaseModel):
    name: str                                       # 섹터 또는 종목명(티커 병기)
    kind: Literal["sector", "stock"] = "sector"
    direction: Literal["direct", "indirect"] = "direct"
    polarity: Literal["benefit", "damage"] = "benefit"
    rationale: str = ""                             # 전이 경로 — 수치 라벨 포함
    financials: str = ""                            # 필요시 재무·현황 미니 분석
    causalChain: str = ""                           # 사건→산업/기업 전이 경로
    evidence: str = ""                              # stock이면 회사별 근거 필수
    readerCopy: AxisBeneficiaryReaderCopy | None = Field(
        default=None, exclude_if=lambda value: value is None)

    @field_validator("name")
    @classmethod
    def _visible_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("영향 대상 이름은 보이는 문자가 필요")
        return value


class AxisScenario(BaseModel):
    polarity: Literal["positive", "negative"]
    thesis: str                                     # 시나리오 + 성립 조건
    beneficiaries: list[AxisBeneficiary] = Field(default_factory=list)

    @field_validator("thesis")
    @classmethod
    def _visible_thesis(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("시나리오 thesis는 보이는 문자가 필요")
        return value


class AxisCard(BaseModel):
    axis: Literal["macro", "memory", "other", "topic1", "topic2"]
    label: str = ""                                 # 독자 표시용 동적 축 라벨
    topicKey: str = ""                              # 위치와 독립적인 안정 주제 키
    title: str = ""                                 # 수치 포함 헤드라인(내부 용어 금지)
    brief: AxisBrief | None = Field(                 # 원문 앞에 놓는 구조화 독서 가이드
        default=None, exclude_if=lambda value: value is None)
    phenomenon: str = ""                            # 현상 분석(markdown, 수치 라벨)
    deep_dive: dict = Field(default_factory=dict)   # {topic, conclusion, findings[]}
    scenarios: list[AxisScenario] = Field(default_factory=list)
    watch_signals: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    error: str = ""                                 # 축 실패 사유(빈 값=정상)

    @field_validator("error")
    @classmethod
    def _visible_error_or_empty(cls, value: str) -> str:
        if value and not value.strip():
            raise ValueError("오류 사유는 비어 있거나 보이는 문자가 필요")
        return value


Report.model_rebuild()
