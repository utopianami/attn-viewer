"""시황 리포트 Phase 2 계약 — 전 스테이지 공유. 뷰어 호환(evidence 문자열·items 문자열) +
additive 관측 필드(evidence_refs·io). 스펙 v3."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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
