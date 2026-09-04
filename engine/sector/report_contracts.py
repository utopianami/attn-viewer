"""시황 리포트 Phase 2 계약 — 전 스테이지 공유. 뷰어 호환(evidence 문자열·items 문자열) +
additive 관측 필드(evidence_refs·io). 스펙 v3."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
    cards: list["AxisCard"] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_axis_contract(self):
        if self.format != "axes":
            if self.axisModel is not None or self.leadAxis is not None:
                raise ValueError("axisModel/leadAxis는 axes 형식에서만 사용")
            return self

        axes = [card.axis for card in self.cards]
        if self.axisModel is None:
            if len(axes) != 3 or set(axes) != {"macro", "memory", "other"}:
                raise ValueError("기존 axes 리포트는 macro/memory/other 카드가 정확히 하나씩 필요")
            if self.leadAxis is not None:
                raise ValueError("leadAxis는 topics_v1 리포트에만 사용")
            return self

        if len(axes) != 3 or set(axes) != {"macro", "topic1", "topic2"}:
            raise ValueError("topics_v1 리포트는 macro/topic1/topic2 카드가 정확히 하나씩 필요")

        by_axis = {card.axis: card for card in self.cards}
        if not self.leadAxis or self.leadAxis not in by_axis:
            raise ValueError("leadAxis는 리포트 카드 중 하나여야 함")
        if self.title != by_axis[self.leadAxis].title:
            raise ValueError("리포트 제목은 leadAxis 카드 제목과 같아야 함")

        keys: list[str] = []
        for card in self.cards:
            if not card.label.strip() or not card.topicKey.strip():
                raise ValueError("topics_v1 카드는 label과 topicKey가 필요")
            keys.append(card.topicKey.strip())
            if card.axis == "macro" and (card.label != "거시" or card.topicKey != "macro"):
                raise ValueError("macro 카드는 label=거시, topicKey=macro여야 함")
            if card.error:
                continue
            polarities = [scenario.polarity for scenario in card.scenarios]
            if len(polarities) != 2 or set(polarities) != {"positive", "negative"}:
                raise ValueError("정상 카드는 positive/negative 시나리오가 정확히 하나씩 필요")
            for scenario in card.scenarios:
                directions = {item.direction for item in scenario.beneficiaries}
                if not {"direct", "indirect"}.issubset(directions):
                    raise ValueError("각 시나리오는 direct/indirect 영향을 모두 포함해야 함")
                for item in scenario.beneficiaries:
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


class AxisScenario(BaseModel):
    polarity: Literal["positive", "negative"]
    thesis: str                                     # 시나리오 + 성립 조건
    beneficiaries: list[AxisBeneficiary] = Field(default_factory=list)


class AxisCard(BaseModel):
    axis: Literal["macro", "memory", "other", "topic1", "topic2"]
    label: str = ""                                 # 독자 표시용 동적 축 라벨
    topicKey: str = ""                              # 위치와 독립적인 안정 주제 키
    title: str = ""                                 # 수치 포함 헤드라인(내부 용어 금지)
    phenomenon: str = ""                            # 현상 분석(markdown, 수치 라벨)
    deep_dive: dict = Field(default_factory=dict)   # {topic, conclusion, findings[]}
    scenarios: list[AxisScenario] = Field(default_factory=list)
    watch_signals: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    error: str = ""                                 # 축 실패 사유(빈 값=정상)


Report.model_rebuild()
