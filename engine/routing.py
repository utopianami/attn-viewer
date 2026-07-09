"""라우팅 Stage 1 — TRIAGE 결과 → 프로필 해석 (오케스트레이터 접합부, 순수 함수).

tier 안전 제어가 항상 프로필보다 우선한다 (스펙 §6 설계 보강).
"""
from __future__ import annotations

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
