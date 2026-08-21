"""모니터 계약 — 다른 contracts 모듈들과 클래스명 충돌 없음(CheckResult/HealthReport)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Axis = Literal["stability", "consistency", "accuracy"]
Level = Literal["ok", "warn", "alert"]

_ORDER = {"ok": 0, "warn": 1, "alert": 2}


class CheckResult(BaseModel):
    check: str                                # 점검 이름 (예: collect_recency)
    pipeline: str                             # 대상 (collector:rss, report, metric:…)
    axis: Axis
    level: Level
    detail: str = ""


class HealthReport(BaseModel):
    at: str
    worst: Level = "ok"
    results: list[CheckResult] = Field(default_factory=list)

    @staticmethod
    def worst_of(results: list[CheckResult]) -> Level:
        return max((r.level for r in results), key=lambda x: _ORDER[x], default="ok")
