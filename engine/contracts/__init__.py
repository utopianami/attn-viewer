"""엔진 계약 패키지 (M0) — 스키마가 계약이다.

- packets: 스테이지 간 패킷 (PlanPacket → ... → FinalAnswer)
- events: 엔진→Node NDJSON 이벤트
- api: Node→엔진 HTTP 요청
"""

from .api import AnswerRequest, HistoryTurn
from .events import (
    ErrorEvent,
    FinalEvent,
    HeartbeatEvent,
    LayerEvent,
    ProgressEvent,
    parse_event,
)
from .packets import (
    LAYER_NAMES,
    SCHEMA_VERSION,
    AtomicClaim,
    AuditIssue,
    AuditReport,
    BearCase,
    BranchPacket,
    CalcRequest,
    CalcResult,
    ClaimNorm,
    ClaimTable,
    ClaimVerdict,
    Conflict,
    CoverageEntry,
    DaDisagreement,
    DaPacket,
    DraftAnswer,
    EnvelopeMeta,
    EvidenceRichness,
    FinalAnswer,
    FiscalPeriod,
    GateResult,
    NeededEvidence,
    NewsItem,
    PlanPacket,
    PlanRef,
    PlanSummary,
    PriceMacroPacket,
    RaPacket,
    RetryDirective,
    RiskPacket,
    SubQuestion,
    SynthInput,
    TickerCandidate,
    TrendPacket,
    TypedFact,
    UnitAnswer,
    VerdictPacket,
    normalize_claim_key,
)

__all__ = [
    "AnswerRequest", "HistoryTurn",
    "ErrorEvent", "FinalEvent", "HeartbeatEvent", "LayerEvent", "ProgressEvent", "parse_event",
    "LAYER_NAMES", "SCHEMA_VERSION",
    "AtomicClaim", "AuditIssue", "AuditReport", "BearCase", "BranchPacket",
    "CalcRequest", "CalcResult", "ClaimNorm", "ClaimTable", "ClaimVerdict",
    "Conflict", "CoverageEntry", "DaDisagreement", "DaPacket", "DraftAnswer",
    "EnvelopeMeta", "EvidenceRichness", "FinalAnswer", "FiscalPeriod", "GateResult",
    "NeededEvidence", "NewsItem", "PlanPacket", "PlanRef", "PlanSummary",
    "PriceMacroPacket", "RaPacket", "RetryDirective", "RiskPacket", "SubQuestion",
    "SynthInput", "TickerCandidate", "TrendPacket", "TypedFact", "UnitAnswer",
    "VerdictPacket", "normalize_claim_key",
]
