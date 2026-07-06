"""메모리 섹터 P1 계약 — 카드·지표·수집 결과 (스펙: docs/memory-sector-rag-plan_claude.md §2-1)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Axis = Literal["A", "A_prime", "B", "C", "C0", "E", "P", "market"]
EventType = Literal["demand_signal", "supply_signal", "price_signal", "earnings",
                    "filing", "policy", "speaker", "product_policy", "market_reaction"]


class SectorCard(BaseModel):
    id: str
    ts: str                                   # ISO8601
    axis: Axis
    entities: list[str] = Field(default_factory=list)
    speaker: str | None = None
    edge: str = ""                            # 예: "B->A"
    event_type: EventType = "demand_signal"
    memory_segment: Literal["hbm", "dram", "nand", "mixed"] = "mixed"
    direction: Literal["pos", "neg", "neutral", "mixed"] = "neutral"
    magnitude: int = 1                        # 1~3
    time_horizon: Literal["immediate", "next_quarter", "next_2_4_quarters"] = "immediate"
    source_grade: Literal["S", "A", "B", "C", "D"] = "B"
    title: str
    raw_quote: str = ""                       # 원문 인용 (사실)
    interpreted_signal: str = ""              # LLM 해석 — 원문과 분리
    numeric: dict[str, Any] | None = None     # {"value":..., "unit":...}
    url: str = ""
    source: str = ""


class MetricObservation(BaseModel):
    metric: str                               # jsonl 파일명이 됨 (영숫자·_)
    ts: str                                   # "YYYY-MM-DD" 또는 "YYYY-MM"
    value: float
    unit: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)

    def key(self) -> str:
        """metric 내 dedup 키 — 같은 날짜·같은 대상 1회.

        판별자를 전부 결합해야 함: pypi/npm 동명 패키지, 국가별 앱 순위,
        지표 item(생산/출하/재고)이 같은 ts에 공존 (Task 5 구현자 발견).
        """
        parts = [self.ts] + [str(self.meta.get(k, "")) for k in
                             ("model", "code", "pkg", "ecosystem", "token",
                              "provider", "app", "country", "item", "title")]
        return "|".join(parts)


class RawNewsItem(BaseModel):
    """수집기 출력 — 판정(judge) 전 뉴스 원료."""
    id: str
    title: str
    preview: str = ""
    content: str = ""
    source: str = ""
    url: str = ""
    published_at: str = ""
    grade_hint: Literal["S", "A", "B", "C", "D"] | None = None   # 예: 공시=S, (카더라)=D
    extra: dict[str, Any] = Field(default_factory=dict)


class CollectorResult(BaseModel):
    name: str
    kind: Literal["news", "metric"]
    items: list[RawNewsItem] = Field(default_factory=list)
    observations: list[MetricObservation] = Field(default_factory=list)
    status: Literal["ok", "degraded", "missing_key", "error"] = "ok"
    detail: str = ""
    took_ms: int = 0
