"""도구 레지스트리 + 스테이지별 allowlist (계획 §4).

두 계급:
- deterministic: executor 코드가 직접 호출 (finance_math, price, toss). @tool 바인딩 금지.
- agent_search: 탐색적 검색만 에이전트에 @tool로 바인딩 (brave/tavily).

allowlist는 코드가 집행하는 경계 — 프롬프트가 아니라 registry가 스테이지별 허용 도구를 강제.
required_env는 부팅 시 검증 → capability 맵 → /healthz 노출 + degrade 판단.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Literal

ToolKind = Literal["deterministic", "http", "agent_search"]
DegradePolicy = Literal["skip", "fallback", "fail"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: ToolKind
    fn: Callable | None = None          # deterministic/http 호출 진입점
    required_env: tuple[str, ...] = ()
    timeout_s: float = 20.0
    degrade: DegradePolicy = "skip"
    note: str = ""

    def env_ok(self) -> bool:
        # os.environ만 보면 .env(pydantic-settings) 로드 키를 놓쳐 healthz tools가
        # 전부 false로 표시되는 관측 버그 (2026-07-09) — settings 필드도 확인
        from app.settings import settings
        return all(os.environ.get(k) or getattr(settings, k.lower(), "")
                   for k in self.required_env)


# 스테이지별 allowlist — 순서 = 폴백 순서 (계획 §4.2, 2차 리뷰 반영).
STAGE_ALLOWLIST: dict[str, list[str]] = {
    "ra_x": ["brave_news"],                          # 당일 실시간 (tavily 제거 2026-07-09)
    "ra_web": ["brave_news"],                        # 배경지식 웹서핑
    "ra_toss": ["toss_feed", "toss_company"],        # 토스 트렌드·회사
    "price_macro": ["price_yahoo", "macro_yahoo"],   # v2: toss_price 폴백 추가
    "calc": ["finance_math"],
    "planner": [],                                   # blind by code
    "da": [],                                        # blind by code
}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def allowed(self, stage: str) -> list[ToolSpec]:
        """스테이지 allowlist 순서대로, env 충족한 도구만 반환 (폴백 체인)."""
        names = STAGE_ALLOWLIST.get(stage, [])
        out = []
        for n in names:
            spec = self._tools.get(n)
            if spec and spec.env_ok():
                out.append(spec)
        return out

    def capabilities(self) -> dict[str, bool]:
        """/healthz용 — 도구별 env 충족 여부."""
        return {name: spec.env_ok() for name, spec in self._tools.items()}


def build_default_registry() -> ToolRegistry:
    """엔진 기본 도구 등록. 실제 fn 바인딩은 M4 executor 배선에서."""
    from .calc import run as calc_run
    from .price.macro import collect_macro
    from .price.yahoo import quote
    from .toss import collect_company, collect_feed

    reg = ToolRegistry()
    # 결정적 (executor 직접 호출) — finance_math는 never-raise run() 래퍼
    reg.register(ToolSpec("finance_math", "deterministic", fn=calc_run, note="FinQA 계산"))
    reg.register(ToolSpec("price_yahoo", "deterministic", fn=quote, note="야후 일별 종가"))
    reg.register(ToolSpec("macro_yahoo", "deterministic", fn=collect_macro, note="매크로 세트"))
    reg.register(ToolSpec("toss_feed", "deterministic", fn=collect_feed, note="토스 피드 4탭"))
    reg.register(ToolSpec("toss_company", "deterministic", fn=collect_company, note="토스 회사 번들"))
    # 검색 (에이전트 @tool — fn은 M4에서, env 게이팅만 지금)
    reg.register(ToolSpec("brave_news", "agent_search", required_env=("BRAVE_API_KEY",), degrade="fallback"))
    return reg
