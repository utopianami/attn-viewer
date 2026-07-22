"""라우팅 Stage 1 — 질문 유형별 워크플로우 프로필 (스펙 docs/workflow-routing-plan.html §6).

원칙: "소스 유지, 폭 축소만". 화이트리스트 필드만 조절 —
DA 이중→단일 / 뉴스 유닛 수(최소 1) / 웹 배경지식 on·off / 섹터 메모리 on·off /
REFLECT 라운드 한도 / RISK 모드. 검증 게이트·CALC·시세는 프로필이 못 건드린다.
tier 안전 제어(tier4 차단·tier3 RISK·G2/G4)는 항상 프로필보다 우선.
애매하면(확신 낮음·unknown) 풀코스 — 오분류의 대가가 "틀림"이 아니라 "느림"이 되게.
Stage 2(kg_search 착지 후)에서 fact_lookup 고속 경로가 이 스키마 위에 얹힌다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

QuestionType = Literal[
    "fact_lookup", "event_interpretation", "stock_judgment",
    "industry_analysis", "strategy_portfolio", "unknown",
]


class WorkflowProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    da_mode: Literal["dual", "single"] = "dual"          # Stage 1: off 금지
    news_units_cap: int = 3                              # 최소 1 (0콜 금지)
    web_enabled: bool = True
    sector_rag_enabled: bool = True
    # 과거사례 지식층(casemem) 주입 (Plan4-b) — 유저 리포트 출력을 바꾸는 변경이라
    # 기본 OFF. 스크린샷 검증 후 프로필별로 켠다(핸드오프 §주의).
    casemem_enabled: bool = False
    reflect_max_rounds: int = 2
    # off여도 tier>=3이면 RISK 강제 (tier 우선). auto = requires_countercase 따름
    risk_mode: Literal["force_on", "auto", "off"] = "auto"
    # 경량 모델 경로 (2026-07-09 ryze_yn: "간단한 건 sonnet으로 충분") —
    # planner/verifier/synthesizer를 sonnet으로. Stage 1 화이트리스트의 "모델 티어" 항목
    light_models: bool = False


PROFILES: dict[str, WorkflowProfile] = {
    "full": WorkflowProfile(name="full"),
    "fact_lookup": WorkflowProfile(
        name="fact_lookup", da_mode="single", news_units_cap=1,
        web_enabled=False, sector_rag_enabled=False,
        reflect_max_rounds=1, risk_mode="off", light_models=True),
    "event_interpretation": WorkflowProfile(
        name="event_interpretation", da_mode="single", risk_mode="auto"),
    "stock_judgment": WorkflowProfile(name="stock_judgment", risk_mode="auto"),
    "industry_analysis": WorkflowProfile(name="industry_analysis", risk_mode="force_on"),
    "strategy_portfolio": WorkflowProfile(name="strategy_portfolio", risk_mode="force_on"),
}

_LIGHT = {"fact_lookup", "event_interpretation"}  # tier3 발견 시 승급 대상


def select_profile(question_type: str, confidence: str) -> tuple[WorkflowProfile, str]:
    """유형+확신도 → 프로필. 애매하면 풀코스 (abstain)."""
    if confidence == "low":
        return PROFILES["full"], "분류 확신 낮음 → 풀코스"
    p = PROFILES.get(question_type)
    if p is None:
        return PROFILES["full"], f"미지 유형({question_type}) → 풀코스"
    return p, f"유형 {question_type} 프로필 적용"


def upgrade_if_needed(profile: WorkflowProfile, tier: int) -> tuple[WorkflowProfile, str | None]:
    """PLAN 승급 전용 규칙 — tier 3+(판단)인데 경량 프로필이면 풀코스로. 강등 없음."""
    if tier >= 3 and profile.name in _LIGHT:
        return PROFILES["full"], f"PLAN tier={tier} 판단 질문 — {profile.name} → full 승급"
    return profile, None
