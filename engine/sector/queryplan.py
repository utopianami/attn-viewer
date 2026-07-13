"""섹터 검색 플랜 — 게이트·스키마·규칙 플랜 (2026-07-13 LLM 쿼리 플래너 P1).

게이트는 키워드(비섹터 질문 비용 0), 플랜 생성은 LLM(plan_query, Task 3)이 기본이고
규칙(build_rule_plan)이 폴백 겸 대조군. 두 경로가 같은 SectorQueryPlan을 내므로
검색 실행부(search_with_plan)는 하나만 존재한다.
"""
from __future__ import annotations

import re
from typing import get_args

from pydantic import BaseModel, Field

from sector.contracts import SectorCard
from sector.entities import ENTITY_PATTERNS, extract_entities
from sector.metrics_registry import METRIC_REGISTRY

_SEGMENTS = ("hbm", "dram", "nand")
_EVENT_TYPES: set[str] = set(get_args(SectorCard.model_fields["event_type"].annotation))
_VALID_ENTITIES = {canon for canon, _ in ENTITY_PATTERNS}

# 섹터별 토픽 키워드 — 타 섹터 추가 시 여기만 등록 (확장 대비 필터 차원)
TOPIC_TERMS_BY_SECTOR: dict[str, tuple[str, ...]] = {
    "memory": ("메모리", "d램", "디램", "dram", "hbm", "낸드", "nand", "웨이퍼"),
}


class SectorQueryPlan(BaseModel):
    """LLM/규칙 공용 검색 계획. 필드 의미는 스펙(2026-07-13 design) §2."""
    sector: str = "memory"
    segments: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    days: int = 14
    keywords: list[str] = Field(default_factory=list)


def is_sector_question(question: str) -> bool:
    low = (question or "").lower()
    if not low:
        return False
    if extract_entities(question):
        return True
    if any(t in low for t in TOPIC_TERMS_BY_SECTOR["memory"]):
        return True
    return "반도체" in low and any(
        w in low for w in ("업황", "사이클", "가격", "수급", "수출"))


_SEGMENT_TERMS = {
    "hbm": ("hbm", "고대역폭"),
    "dram": ("d램", "디램", "dram"),
    "nand": ("낸드", "nand", "ssd"),
}
_MONTH_RE = re.compile(r"\d{1,2}\s*월")
_LONG_TERMS = ("지난달", "저번달", "분기", "올해", "작년", "상반기", "하반기", "한 달", "한달")


def build_rule_plan(question: str) -> SectorQueryPlan:
    """키워드 규칙 플랜 — LLM 폴백 겸 대조군. 미매칭이면 빈 필드(무필터 광역 검색)."""
    low = (question or "").lower()
    segs = [s for s, terms in _SEGMENT_TERMS.items() if any(t in low for t in terms)]
    mets = [m for m, info in METRIC_REGISTRY.items()
            if any(k in low for k in info["keywords"])][:4]
    days = 90 if (_MONTH_RE.search(question or "") or any(t in low for t in _LONG_TERMS)) else 14
    return SectorQueryPlan(segments=segs, entities=extract_entities(question or ""),
                           metrics=mets, days=days)


def sanitize_plan(p: SectorQueryPlan) -> SectorQueryPlan:
    """LLM 출력 정제 — 미등록 값 제거·클램프. 검증 실패값이 검색을 오염시키지 않게."""
    return SectorQueryPlan(
        sector="memory",
        segments=[s for s in p.segments if s in _SEGMENTS][:3],
        entities=[e for e in p.entities if e in _VALID_ENTITIES][:6],
        metrics=[m for m in p.metrics if m in METRIC_REGISTRY][:4],
        event_types=[t for t in p.event_types if t in _EVENT_TYPES][:4],
        days=max(7, min(90, int(p.days or 14))),
        keywords=[k.strip() for k in p.keywords if k and k.strip()][:8],
    )
