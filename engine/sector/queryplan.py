"""섹터 검색 플랜 — 게이트·스키마·규칙 플랜 (2026-07-13 LLM 쿼리 플래너 P1).

게이트는 키워드(비섹터 질문 비용 0), 플랜 생성은 LLM(plan_query, Task 3)이 기본이고
규칙(build_rule_plan)이 폴백 겸 대조군. 두 경로가 같은 SectorQueryPlan을 내므로
검색 실행부(search_with_plan)는 하나만 존재한다.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import date
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


@dataclass
class PlanOutcome:
    plan: SectorQueryPlan        # 검색에 실제 쓸 플랜
    rule_plan: SectorQueryPlan   # 대조 로그용 규칙 플랜 (LLM 기여 사후 측정)
    fallback: bool               # True = LLM 실패로 규칙 플랜 사용
    planner_ms: int


_PLANNER_INSTRUCTIONS = (
    "너는 메모리 반도체 섹터 데이터베이스의 검색 플래너다. 사용자 질문을 보고 "
    "어떤 데이터를 꺼내올지 SectorQueryPlan JSON으로만 답한다. "
    "질문과 무관한 필드는 빈 목록으로 둔다. 과잉 선택 금지 — 답변에 꼭 필요한 것만.")


def _planner_prompt(question: str) -> str:
    metrics_menu = "\n".join(f"- {name}: {info['label']} — {info['desc']}"
                             for name, info in METRIC_REGISTRY.items())
    return f"""오늘: {date.today().isoformat()}
질문: {question}

아래 메뉴에서 이 질문에 답하는 데 필요한 것만 고른다.

[metrics 메뉴 — 이 이름만 사용]
{metrics_menu}

[segments] {", ".join(_SEGMENTS)} — 질문이 특정 메모리 종류를 다룰 때만
[entities] {", ".join(sorted(_VALID_ENTITIES))}
[event_types] {", ".join(sorted(_EVENT_TYPES))}
[days] 검색 기간(일). 기본 14. 질문이 과거 기간·특정 월을 언급하면 넓힌다 (최대 90)
[keywords] 뉴스 카드 제목·해석 텍스트와 대조할 한국어 키워드 최대 8개 —
질문의 핵심 개념과 동의어·연관어 (예: "따라잡아?" → 점유율, 인증, 수율)"""


def _make_role(overrides: dict | None):
    """테스트 대역 주입 지점 — monkeypatch 대상."""
    from providers import Role
    return Role("sector_query", overrides)


async def plan_query(question: str, overrides: dict | None = None,
                     timeout: float = 5.0) -> PlanOutcome | None:
    """게이트 → LLM 플랜 (실패 시 규칙 플랜). never-raise."""
    if not is_sector_question(question or ""):
        return None
    rule = build_rule_plan(question)
    t0 = time.monotonic()
    try:
        role = _make_role(overrides)
        raw = await asyncio.wait_for(
            role.run(_planner_prompt(question), _PLANNER_INSTRUCTIONS,
                     response_format=SectorQueryPlan),
            timeout)
        ms = int((time.monotonic() - t0) * 1000)
        got = raw if isinstance(raw, SectorQueryPlan) \
            else SectorQueryPlan.model_validate_json(str(raw))
        plan = sanitize_plan(got)
        if not (plan.segments or plan.entities or plan.metrics or plan.keywords):
            plan = rule  # 플래너가 전부 비웠으면 규칙이 더 안전
        return PlanOutcome(plan=plan, rule_plan=rule, fallback=False, planner_ms=ms)
    except Exception:  # noqa: BLE001 — 타임아웃·API 오류·검증 실패 전부 규칙 강등
        return PlanOutcome(plan=rule, rule_plan=rule, fallback=True,
                           planner_ms=int((time.monotonic() - t0) * 1000))
