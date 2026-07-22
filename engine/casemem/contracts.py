"""Case-Memory 계약 — bitemporal(event_time·knowable_at). 결정적, LLM 없음."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str
    grade: Literal["S", "A", "B", "C", "D"] = "B"
    quote: str = ""
    url: str = ""
    knowable_at: str                      # 이 근거를 알 수 있게 된 때


class QuantRef(BaseModel):
    metric_name: str                      # metrics_registry 상의 시리즈명
    expected_direction: Literal["up", "down", "flat"]


class Phase(BaseModel):
    order: int
    label: str                            # capex_expansion → inventory_build → price_break …
    period_start: str                     # event_time 범위 시작 (valid time)
    period_end: str = ""
    knowable_at: str                      # 국면이 식별 가능해진 시점 (transaction time)
    identifying_signals: list[str] = Field(default_factory=list)  # knowable_at 시점에 알 수 있던 것만
    quant_backbone: list[QuantRef] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class CaseEpisode(BaseModel):
    id: str
    sector: str                           # L2가 채움; L1은 문자열로만 취급
    title: str
    summary: str = ""
    event_time: str                       # 사례 전체 valid-time 앵커
    knowable_at: str                      # 사례가 식별 가능해진 시점
    phases: list[Phase] = Field(default_factory=list)   # order 순
    outcome: str = ""                     # 사후 전개(postmortem) — signal 아님
    supports_rules: list[str] = Field(default_factory=list)
    refutes_rules: list[str] = Field(default_factory=list)


class DistilledRule(BaseModel):
    id: str
    situation: str
    triggers: list[str] = Field(default_factory=list)
    connection: str = ""
    reservations: str = ""
    provenance: str = ""                  # 출처 사례(예: "1990s Japan bubble")
    status: Literal["candidate", "holdout_passed"] = "candidate"  # candidate는 리포트 주입 불가
    event_time: str
    knowable_at: str


class CaseMatch(BaseModel):
    episode_id: str
    matched_phase_order: int
    score: float                          # 최종 랭킹 점수(리랭크 후엔 블렌드)
    surface_score: float = 0.0            # 표면 원점수 보존(관측성)
    structural_score: float | None = None # LLM 구조 점수(리랭크 시에만)
    reranked: bool = False
    next_phase_labels: list[str] = Field(default_factory=list)   # =예측
    evidence: list[Evidence] = Field(default_factory=list)


class CaseQueryResult(BaseModel):
    as_of: str
    sector: str
    matches: list[CaseMatch] = Field(default_factory=list)
    scanned: int
    dropped_after_as_of: int              # knowable_at > as_of 로 탈락(룩어헤드 차단)
    dropped_sector: int                   # 섹터 불일치 탈락
    rerank_used: bool = False             # llm_fn 주입되어 리랭크 시도됨
    rerank_failed: bool = False           # 리랭크 시도했으나 폴백됨(관측성)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    """ISO8601(Z/offset/naive/날짜만) → aware UTC. 파싱 불가 시 None."""
    if not ts:
        return None
    raw = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _to_utc(dt)
