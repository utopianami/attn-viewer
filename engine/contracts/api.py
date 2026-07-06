"""Node ↔ 엔진 HTTP 계약 (POST /v1/answer 요청 모델).

응답은 NDJSON 스트림 (events.py). think_level/providers는 v1에서 수신·기록만.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .packets import PlanSummary


class HistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str                        # user=원문 / assistant=답변 요약
    plan_summary: PlanSummary | None = None   # assistant 턴에만 (멀티턴 참조 해소)
    raw_layers: dict[str, Any] | None = None  # 직전 assistant 턴에만 (followup 재사용)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "qa"                    # WORKFLOWS 레지스트리 키 (미래: pulse/thesis)
    question: str = Field(min_length=1, max_length=4000)
    history: list[HistoryTurn] = Field(default_factory=list)
    run_id: str = ""                    # Node가 부여 — disconnect 시 취소 식별자
    chat_id: str = ""
    message_id: str = ""
    providers: list[str] = Field(default_factory=list)  # v1 기록만
    think_level: int = 2                                 # v1 기록만
    model_mode: Literal["", "fast", "deep"] = ""
    model: str = Field(default="", max_length=120)
