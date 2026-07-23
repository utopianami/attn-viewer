"""엔진 스테이지 간 계약 — 패킷 스키마 (M0).

프롬프트가 아니라 스키마가 계약이다. 모든 스테이지 경계는 이 모델들을 통과한다.
2차 적대 리뷰 반영: EnvelopeMeta(round 관통) · provenance 다중출처 · DA-DA 규칙 필드 ·
retry_directives(replan) · RiskPacket supporting_claim_ids · coverage 3값 · SynthInput 캐리.

원칙:
- 우리 계약은 strict하게 (외부 응답 모델과 달리 extra 금지 — 드리프트 조기 발견)
- 수집 원본은 raw 필드에 전량 보존 (사용자 지시: 잘라내지 않는다)
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
CHAIN_SCHEMA_VERSION = 1  # ChainPacket 전용 (3부 T2)

# judge._INSTR 인과 사슬의 명시 열거 (곱집합 금지, B4) — 노드 집합은
# judge._VALID_AXIS와 드리프트 가드 테스트로 결속 (test_chain_contracts.py)
CHAIN_EDGES = (
    "C0->C", "C->B", "B->A_prime", "B->A", "A_prime->A", "E->A", "P->A", "market->A",
)

# layer 이름 고정 어휘 — 프론트 렌더러가 참조하는 단일 진실원
LAYER_NAMES = (
    "triage", "plan", "playbook", "da_blind", "ra_x", "ra_web", "news_summary", "sector_rag",
    "toss_trend", "toss_company", "price", "macro", "claims", "calc", "verify", "risk", "audit",
    "trace", "thesis", "chain",
)

Tier = Literal[0, 1, 2, 3, 4]
SourceType = Literal["news", "price", "macro", "web", "company"]
ClaimSource = Literal[
    "da_gpt", "da_fable", "ra_x", "ra_web", "toss_trend", "toss_company",
    "price", "macro", "calc",
]
BranchStatus = Literal["ok", "partial", "skipped", "degraded", "error"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- envelope

class PlanRef(_Strict):
    """하류 스테이지가 계획 전체 없이도 판단할 수 있는 요약 — 전 패킷 관통."""

    tier: Tier
    knowledge_cutoff: str  # YYYY-MM-DD


class EnvelopeMeta(_Strict):
    """모든 패킷 공통 메타 (2차 리뷰: round·plan_ref 관통 미명세 해소)."""

    round: int = 0  # REFLECT 라운드 (0 = 첫 실행)
    plan_ref: PlanRef | None = None


# ---------------------------------------------------------------- plan

class TickerCandidate(_Strict):
    name: str
    code: str | None = None            # 6자리 (한국)
    yahoo_symbol: str | None = None    # 005930.KS, AAPL, 6981.T
    confidence: Literal["high", "medium", "low"] = "high"
    source: Literal["dict_match", "llm", "unresolved"] = "dict_match"
    verified: bool = False             # PRICE 응답 종목명 역검증 통과 여부


class SubQuestion(_Strict):
    id: str                            # "q1", "q2"...
    text: str
    depends_on: str | None = None      # 선행 질문 id (bridge)
    search_queries: list[str] = Field(default_factory=list)  # 의존 질문은 비움


class NeededEvidence(_Strict):
    """자유 문장 금지 — claim_key와 코드 매칭 가능한 슬롯."""

    entity: str
    metric: str
    period: str = ""
    source_type: SourceType
    required: bool = True
    obtainability: Literal["public", "estimated", "unavailable"] = "public"


class FiscalPeriod(_Strict):
    """검색 전 확정 금지 — 수집 후 ASSEMBLER가 late-binding 확정."""

    expression: str                    # 원문 표현 ("지난 분기")
    calendar_period: str | None = None   # "2026Q2"
    last_reported_period: str | None = None  # "2026Q1"
    basis: Literal["calendar", "reported", "unclear"] = "unclear"
    resolved: bool = False


class EvidenceRichness(_Strict):
    grade: Literal["A", "B", "C"]
    prelim: bool = True                # PLAN 잠정치 / ASSEMBLER 확정치
    reason: str = ""
    research_strategy: Literal[
        "normal", "contrarian_check", "first_principles", "abstain_more"
    ] = "normal"


class PlanPacket(_Strict):
    schema_version: int = SCHEMA_VERSION
    meta: EnvelopeMeta = Field(default_factory=EnvelopeMeta)

    tier: Tier
    original_question: str
    standalone_question: str           # 재작성 (원문과 같을 수 있음)

    event_time_start: str | None = None   # 질문이 다루는 사건 기간
    event_time_end: str | None = None
    knowledge_cutoff: str                 # 어느 시점의 지식으로 답할지 (기본=오늘)

    tickers: list[TickerCandidate] = Field(default_factory=list)
    unresolved_entities: list[str] = Field(default_factory=list)
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)      # 전체질문(q0)용 검색어
    contrast_questions: list[str] = Field(default_factory=list)  # 검색 전용
    needed_evidence: list[NeededEvidence] = Field(default_factory=list)
    news_mode: Literal["live", "archive", "off"] = "live"
    market_scope: Literal["kr", "global", "mixed"] = "kr"  # 검색 언어·국가 라우팅 (2026-07-06)
    fiscal_periods: list[FiscalPeriod] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    richness: EvidenceRichness | None = None

    g0_notes: list[str] = Field(default_factory=list)  # G0 게이트 판정 기록

    def units(self) -> list[tuple[str, str]]:
        """실행 유닛 목록: [("q0", 전체질문), ("q1", 서브1), ...]"""
        out = [("q0", self.standalone_question or self.original_question)]
        out += [(sq.id, sq.text) for sq in self.sub_questions]
        return out

    def plan_ref(self) -> PlanRef:
        return PlanRef(tier=self.tier, knowledge_cutoff=self.knowledge_cutoff)


# ---------------------------------------------------------------- claims

def normalize_claim_key(entity: str, metric: str, period: str = "") -> str:
    """claim_key = entity|metric|period — 공백/대소문자 정규화 (거짓 충돌 방지의 1차)."""

    def norm(s: str) -> str:
        return " ".join(s.strip().lower().split())

    return f"{norm(entity)}|{norm(metric)}|{norm(period)}"


class ClaimNorm(_Strict):
    entity: str = ""
    metric: str = ""
    period: str = ""
    unit: str = ""
    value: float | None = None
    source_type: str = ""              # primary|secondary|model|synth
    as_of: str = ""                    # 근거의 시점 (G3 검사 대상)


class AtomicClaim(_Strict):
    id: str
    text: str
    # P2-1 (F3): comparison="A가 B보다", regulation="공시·규정 인용", temporal="일정·발표일"
    type: Literal["fact", "numeric", "price", "definition", "risk", "context",
                  "comparison", "regulation", "temporal"]
    source: ClaimSource
    provenance: list[ClaimSource] = Field(default_factory=list)  # dedup 병합 시 다중 출처
    unit_id: str = "q0"
    norm: ClaimNorm = Field(default_factory=ClaimNorm)
    claim_key: str = ""
    uncertainty: Literal["low", "medium", "high"] = "medium"
    load_bearing: bool = False
    ref: str = ""                      # doc id / URL (근거 좌표)
    derived: bool = False              # LLM 합성물 (toss_trend_synth 등) — G1 증거 자격 없음

    @model_validator(mode="after")
    def _fill(self) -> "AtomicClaim":
        if not self.provenance:
            self.provenance = [self.source]
        if not self.claim_key and (self.norm.entity or self.norm.metric):
            self.claim_key = normalize_claim_key(
                self.norm.entity, self.norm.metric, self.norm.period
            )
        return self


# ---------------------------------------------------------------- branches

class BranchPacket(_Strict):
    """3 브랜치 공통 겉봉투 — 불변식 1: 어떤 경우에도 이 패킷은 fan-in에 도착한다."""

    schema_version: int = SCHEMA_VERSION
    meta: EnvelopeMeta = Field(default_factory=EnvelopeMeta)
    branch: Literal["da", "ra_ext", "price_macro"]
    status: BranchStatus = "ok"
    error: str | None = None
    truncated_units: list[str] = Field(default_factory=list)  # 타임아웃으로 잘린 유닛 (G1이 인지)
    trace: list[str] = Field(default_factory=list)


class UnitAnswer(_Strict):
    unit_id: str
    model: Literal["da_gpt", "da_fable"]
    answer_text: str
    claims: list[AtomicClaim] = Field(default_factory=list)


class DaPacket(BranchPacket):
    branch: Literal["da"] = "da"
    unit_answers: list[UnitAnswer] = Field(default_factory=list)


class NewsSummaryLine(_Strict):
    text: str
    url: str = ""


class NewsSummaryPacket(_Strict):
    """큐레이션 뉴스의 질문-관점 요약 (news_summary 역할, sonnet) — UI 패널 + 합성 투입."""

    lines: list[NewsSummaryLine] = Field(default_factory=list)
    as_of: str = ""


class NewsItem(_Strict):
    id: str = ""
    title: str
    summary: str = ""
    content: str = ""                  # 전문 (전량 보존)
    url: str = ""
    published_at: str = ""
    source_name: str = ""
    feed_count: int = 1
    tabs: list[str] = Field(default_factory=list)


class TrendPacket(_Strict):
    """toss_trend 합성 결과 — derived claim으로 편입 (컨텍스트 아님, 2차 리뷰)."""

    trends: list[dict[str, Any]] = Field(default_factory=list)  # {label, stocks, news_ids}
    articles: list[NewsItem] = Field(default_factory=list)      # 근거 원본 전량 보존
    as_of: str = ""


class RaPacket(BranchPacket):
    branch: Literal["ra_ext"] = "ra_ext"
    x_narrative: str = ""              # 실시간 검색 서사 (grok 제거로 현재 미사용 — 스키마 호환 유지)
    x_search: dict[str, list[NewsItem]] = Field(default_factory=dict)   # unit_id → 뉴스 (brave)
    web_knowledge: dict[str, list[NewsItem]] = Field(default_factory=dict)
    toss_trend: TrendPacket | None = None
    toss_company: dict[str, Any] = Field(default_factory=dict)          # code → 번들 raw
    claims: list[AtomicClaim] = Field(default_factory=list)             # 5.5-mini 추출분
    collector_status: dict[str, BranchStatus] = Field(default_factory=dict)
    curated: dict[str, list[str]] = Field(default_factory=dict)  # unit_id → 선별 NewsItem id (P1-2)

    def curated_items(self) -> dict[str, list[NewsItem]]:
        """curation 통과분만 (하류 verify/synth 전달용). curation 미수행이면 전량 반환.

        원본 전량은 x_search/web_knowledge에 그대로 보존 (raw 보존 원칙).
        """
        pools: dict[str, list[NewsItem]] = {}
        for src in (self.x_search, self.web_knowledge):
            for uid, items in src.items():
                pools.setdefault(uid, []).extend(items)
        if not self.curated:
            return pools
        out: dict[str, list[NewsItem]] = {}
        for uid, items in pools.items():
            if uid not in self.curated:
                out[uid] = items       # curation이 못 본 유닛(재조사분 등)은 통과
                continue
            keep = set(self.curated[uid])
            picked = [n for n in items if n.id in keep]
            if picked:
                out[uid] = picked
        return out


class TypedFact(_Strict):
    """finance_math 입력 단위 — 하네스 numeric_policy 계약."""

    id: str
    value: float
    unit: str
    period: str = ""
    label: str = ""
    source: str = ""                   # 근거 좌표 (toss:..., yahoo:...)
    metric: str = ""                   # METRIC_REGISTRY 키 (3부 T2, 기존 생성부 무변경)
    observation_id: str = ""           # MetricObservation 결속 (3부 T2, 기존 생성부 무변경)


class PriceMacroPacket(BranchPacket):
    branch: Literal["price_macro"] = "price_macro"
    quotes: list[dict[str, Any]] = Field(default_factory=list)     # yahoo.quote() rows (raw 보존)
    macro: dict[str, Any] = Field(default_factory=dict)            # collect_macro() 결과
    extra_series: list[dict[str, Any]] = Field(default_factory=list)  # 유닛별 추가 체크분
    typed_facts: list[TypedFact] = Field(default_factory=list)
    claims: list[AtomicClaim] = Field(default_factory=list)


# ---------------------------------------------------------------- assembler → verify

class Conflict(_Strict):
    claim_key: str
    claim_ids: list[str]
    resolution: Literal["calc", "primary", "freshness", "unresolved"] = "unresolved"
    chosen_claim_id: str | None = None


class DaDisagreement(_Strict):
    """DA-DA 불일치 — 채택 없음, 집중 검증 신호 (2차 리뷰)."""

    claim_key: str
    gpt_claim_id: str
    fable_claim_id: str


class CoverageEntry(_Strict):
    slot: NeededEvidence
    status: Literal["covered", "uncovered", "unobtainable", "ambiguous"]
    matched_claim_ids: list[str] = Field(default_factory=list)


class CalcRequest(_Strict):
    """CALC 스테이지 입력 — GPT가 작성할 program의 대상."""

    metric: str
    unit_id: str = "q0"
    typed_fact_ids: list[str] = Field(default_factory=list)
    note: str = ""


class ClaimTable(_Strict):
    schema_version: int = SCHEMA_VERSION
    meta: EnvelopeMeta = Field(default_factory=EnvelopeMeta)
    claims: list[AtomicClaim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    da_disagreements: list[DaDisagreement] = Field(default_factory=list)
    coverage: list[CoverageEntry] = Field(default_factory=list)     # 1차 판정 = 코드
    calc_requests: list[CalcRequest] = Field(default_factory=list)
    typed_facts: list[TypedFact] = Field(default_factory=list)
    richness: EvidenceRichness | None = None                        # 확정 재산출본
    fiscal_periods: list[FiscalPeriod] = Field(default_factory=list)  # late-binding 확정본
    global_context: dict[str, Any] = Field(default_factory=dict)    # macro 등 표시용


class CalcResult(_Strict):
    request: CalcRequest
    program: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None      # finance_math run() 출력 그대로
    ok: bool = False


class GateResult(_Strict):
    g1: Literal["pass", "fail", "skip"] = "skip"
    g2: Literal["pass", "fail", "skip"] = "skip"
    g3: Literal["pass", "fail", "skip"] = "skip"
    g4: Literal["pass", "fail", "skip"] = "skip"


class ClaimVerdict(_Strict):
    claim_id: str
    gates: GateResult = Field(default_factory=GateResult)
    final: Literal["verified", "unverified", "rejected"]
    judged_by: Literal["fable", "gpt", "code"] = "code"  # 교차 채점 기록
    note: str = ""
    reaudit: Literal["", "upheld", "overturned"] = ""  # A1 역할 재제시 재감사 결과


class RetryDirective(_Strict):
    kind: Literal["research", "replan"]
    unit_id: str = "q0"
    queries: list[str] = Field(default_factory=list)  # research: 신규 확장 쿼리 강제
    reason: str = ""
    recovery_hint: str = ""  # A4: 실패 사유별 다음 유효 복구 단계 (코드가 결정)


class ChainEdgeVerdict(_Strict):
    edge_id: str
    grounded: bool
    note: str = ""


class VerdictPacket(_Strict):
    schema_version: int = SCHEMA_VERSION
    meta: EnvelopeMeta = Field(default_factory=EnvelopeMeta)
    verdicts: list[ClaimVerdict] = Field(default_factory=list)
    retry_directives: list[RetryDirective] = Field(default_factory=list)
    coverage_holes: list[CoverageEntry] = Field(default_factory=list)
    chain_verdicts: list[ChainEdgeVerdict] = Field(default_factory=list)  # 3부 T2

    @property
    def round(self) -> int:
        return self.meta.round


# ---------------------------------------------------------------- risk → synth → audit

class BearCase(_Strict):
    text: str
    supporting_claim_ids: list[str] = Field(default_factory=list)
    # 코드가 집행: supporting 비면 자동 "scenario" (RISK 프롬프트가 아니라 코드가 라벨링)
    label: Literal["grounded", "scenario"] = "scenario"


class RiskPacket(_Strict):
    schema_version: int = SCHEMA_VERSION
    meta: EnvelopeMeta = Field(default_factory=EnvelopeMeta)
    applicable: bool = False           # tier < 3 → False (skipped)
    bear_cases: list[BearCase] = Field(default_factory=list)
    wrong_if: str = ""                 # "내가 틀릴 가능성이 가장 큰 지점"


class SynthInput(_Strict):
    """직렬 노드 캐리 규칙 — risk가 상류 패킷을 래핑해 synthesizer에 전달 (2차 리뷰)."""

    verdict: VerdictPacket
    claim_table: ClaimTable
    calc_results: list[CalcResult] = Field(default_factory=list)
    risk: RiskPacket


# ---------------------------------------------------------------- chain / playbook (3부 T2)

class ThesisRelation(_Strict):
    thesis_revision_id: str
    relation: Literal["supports", "contradicts"]


class ChainEdge(_Strict):
    edge_id: str
    edge: str
    kind: Literal["observed", "inference"]
    supporting_card_ids: list[str] = Field(default_factory=list)
    metric_fact_ids: list[str] = Field(default_factory=list)
    contradicting_card_ids: list[str] = Field(default_factory=list)

    @field_validator("edge")
    @classmethod
    def _edge_registered(cls, v: str) -> str:
        if v not in CHAIN_EDGES:
            raise ValueError(f"unregistered chain edge: {v!r}")
        return v


class ChainPacket(_Strict):
    """인과 사슬(사건→메커니즘→edge) 판정 — meta 필수(생성 시점 round·plan_ref 강제, 판정 3)."""

    schema_version: int = CHAIN_SCHEMA_VERSION
    meta: EnvelopeMeta
    event: str
    mechanism: str
    edges: list[ChainEdge] = Field(default_factory=list)
    thesis_relation: list[ThesisRelation] = Field(default_factory=list)
    verdict: str = ""


class PlaybookGateSelector(_Strict):
    series: str | None = None
    meta_filter: dict = Field(default_factory=dict)


class PlaybookGateCheck(_Strict):
    order: int
    check: str
    metric_id: str
    selector: PlaybookGateSelector = Field(default_factory=PlaybookGateSelector)
    aggregation: Literal["last", "mean_window", "yoy"]
    window_days: int = 0
    comparator: Literal[">=", "<=", ">", "<", "=="]
    threshold: float
    unit: str
    max_age_days: int

    @field_validator("threshold")
    @classmethod
    def _threshold_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("threshold must be finite")
        return v


class PlaybookGateOutcome(_Strict):
    order: int
    metric_id: str
    value: float | None = None
    verdict: Literal["pass", "fail", "unavailable"]
    evidence_observation_id: str = ""
    unavailable_reason: Literal["", "no_metric", "unit_mismatch", "stale_data"] = ""

    @model_validator(mode="after")
    def _verdict_reason_consistent(self) -> "PlaybookGateOutcome":
        if self.verdict == "unavailable":
            if not self.unavailable_reason or self.value is not None:
                raise ValueError(
                    "unavailable verdict requires unavailable_reason set and value None"
                )
        else:
            if self.value is None or self.unavailable_reason != "":
                raise ValueError(
                    "pass/fail verdict requires value set and unavailable_reason empty"
                )
        return self


class DraftAnswer(_Strict):
    schema_version: int = SCHEMA_VERSION
    meta: EnvelopeMeta = Field(default_factory=EnvelopeMeta)
    answer_markdown: str
    unit_answers: dict[str, str] = Field(default_factory=dict)  # unit_id → sub-answer
    citations: list[dict[str, str]] = Field(default_factory=list)
    scenario_flags: list[str] = Field(default_factory=list)  # 3부 T2


class AuditIssue(_Strict):
    kind: Literal["numeric_unsupported", "numeric_mismatch", "directive", "new_fact",
                  "citation_mismatch"]
    sentence: str
    detail: str = ""


class AuditReport(_Strict):
    numeric_total: int = 0
    numeric_supported: int = 0
    issues: list[AuditIssue] = Field(default_factory=list)
    directive_hits: list[str] = Field(default_factory=list)
    severe: bool = False               # 상수 기준: unsupported ≥1 또는 상대오차 >5%
    skipped: bool = False              # GPT 다운 시 skip + 표기 (Fable 승격 금지)
    # P5 (F1, AAR): (문장, 인용 URL) entailment 판정의 entail 비율. None = 판정 쌍 없음
    provenance_soundness: float | None = None


class PlanSummary(_Strict):
    """멀티턴용 — FINALIZER가 final meta에 넣고 Node가 저장 (2차 리뷰)."""

    tier: Tier
    knowledge_cutoff: str
    tickers: list[TickerCandidate] = Field(default_factory=list)
    fiscal_periods: list[FiscalPeriod] = Field(default_factory=list)


class FinalAnswer(_Strict):
    schema_version: int = SCHEMA_VERSION
    answer_markdown: str
    degraded: list[str] = Field(default_factory=list)
    audit: AuditReport = Field(default_factory=AuditReport)
    plan_summary: PlanSummary | None = None
    models_used: list[str] = Field(default_factory=list)
    rounds: int = 0
    elapsed_s: float = 0.0
    cost: dict[str, Any] = Field(default_factory=dict)  # {by_provider:{claude,openai}, total_usd, tokens}
