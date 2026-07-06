"""엔진 → Node NDJSON 이벤트 계약.

스트림 = 한 줄 한 이벤트. Node(engine-client.mjs)가 유일 소비자.
heartbeat 10~15s 주기 (2차 리뷰: SYNTH 침묵 구간 abort 방지).
layer는 round 필드 필수 — REFLECT 재라운드 시 같은 이름 layer는 최신 교체(이전 보존).
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .packets import LAYER_NAMES  # noqa: F401  (어휘 단일 진실원 재노출)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def ndjson(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False) + "\n"


class HeartbeatEvent(_Event):
    type: Literal["heartbeat"] = "heartbeat"


class LayerEvent(_Event):
    """→ ChatArtifacts.layers 항목. 스테이지 완료 즉시 방출 (중간 표시 UX)."""

    type: Literal["layer"] = "layer"
    name: str                          # LAYER_NAMES 어휘
    round: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    createdAt: str = Field(default_factory=_now_iso)


class ProgressEvent(_Event):
    """가벼운 진행 알림 (layer보다 잦음 — 예: '뉴스 검색 중')."""

    type: Literal["progress"] = "progress"
    stage: str
    detail: str = ""


class FinalEvent(_Event):
    type: Literal["final"] = "final"
    answer: str
    meta: dict[str, Any] = Field(default_factory=dict)  # FinalAnswer.model_dump()


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    message: str
    partial: bool = False              # 일부 layer는 이미 방출됨


AnyEvent = HeartbeatEvent | LayerEvent | ProgressEvent | FinalEvent | ErrorEvent


def parse_event(line: str) -> AnyEvent:
    """NDJSON 한 줄 → 이벤트 (Node 측 계약 검증·테스트용)."""
    raw = json.loads(line)
    kind = raw.get("type")
    cls = {
        "heartbeat": HeartbeatEvent,
        "layer": LayerEvent,
        "progress": ProgressEvent,
        "final": FinalEvent,
        "error": ErrorEvent,
    }.get(kind)
    if cls is None:
        raise ValueError(f"unknown event type: {kind!r}")
    return cls.model_validate(raw)
