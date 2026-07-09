"""라우팅 Stage 1 — TRIAGE 결과 → 프로필 해석 (오케스트레이터 접합부, 순수 함수).

tier 안전 제어가 항상 프로필보다 우선한다 (스펙 §6 설계 보강).
"""
from __future__ import annotations

from app.settings import settings
from profiles import WorkflowProfile, select_profile
from stages.triage import TriageResult


def resolve(triage: TriageResult) -> tuple[WorkflowProfile, str]:
    """deep 경로 진입 시 프로필 선택. followup/smalltalk에서는 호출하지 않는다."""
    return select_profile(triage.question_type, triage.type_confidence)


def risk_forced(profile: WorkflowProfile, triage: TriageResult, tier: int) -> bool:
    """RISK 실행 여부 — tier 3+는 무조건, force_on 프로필은 항상,
    auto는 requires_countercase(RISK lite 신호)를 따른다."""
    if tier >= 3:
        return True
    if profile.risk_mode == "force_on":
        return True
    if profile.risk_mode == "auto":
        return bool(triage.requires_countercase)
    return False


def role_overrides(profile: WorkflowProfile, overrides: dict | None) -> dict | None:
    """경량 프로필의 sonnet 모델 배치 — 호출자 overrides가 항상 우선 (병합).

    da_fable 제외 (경량 프로필은 DA 단일=gpt라 미사용), AUDIT은 감사 독립성(gpt) 유지,
    교차 심판(verifier_cross=gpt) 유지 — 바꾸는 건 planner/verifier/synthesizer만.
    """
    if not profile.light_models:
        return overrides
    light = {
        "planner": [("anthropic", settings.model_claude_sonnet, "low"),
                    ("openai", settings.model_gpt, "low")],
        "verifier": [("anthropic", settings.model_claude_sonnet, "medium")],
        "synthesizer": [("anthropic", settings.model_claude_sonnet, "medium"),
                        ("openai", settings.model_gpt, "medium")],
    }
    return {**light, **(overrides or {})}
