"""도구 레지스트리 + 스테이지별 allowlist (계획 §4).

두 계급:
- deterministic: executor 코드가 직접 호출 (finance_math, price, toss). @tool 바인딩 금지.
- agent_search: 탐색적 검색만 에이전트에 @tool로 바인딩 (brave/tavily).

allowlist는 코드가 집행하는 경계 — 프롬프트가 아니라 registry가 스테이지별 허용 도구를 강제.
required_env는 부팅 시 검증 → capability 맵 → /healthz 노출 + degrade 판단.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import partial
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
    "ra_x": ["naver_news", "gnews_rss"],             # 당일 실시간 (2026-07-09: brave·tavily 제거)
    "ra_web": [],                                    # 배경지식 — LLM 직접 생성 (검색 도구 없음)
    "ra_toss": ["toss_feed", "toss_company", "toss_market_snapshot"],
    "price_macro": [
        "price_yahoo", "price_yahoo_history", "market_sector_momentum",
        "macro_yahoo",
    ],
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
    from .price.yahoo import daily_history, fundamentals, quote
    from .toss import (
        collect_community_aggregate,
        collect_company,
        collect_feed,
        collect_market_snapshot,
        collect_sector_momentum,
        execute_official,
        execute_wts_operation,
        official_operation_ids,
    )
    from .toss.readonly import load_wts_catalog

    reg = ToolRegistry()
    # 결정적 (executor 직접 호출) — finance_math는 never-raise run() 래퍼
    reg.register(ToolSpec("finance_math", "deterministic", fn=calc_run, note="FinQA 계산"))
    reg.register(ToolSpec("price_yahoo", "deterministic", fn=quote, note="야후 일별 종가"))
    reg.register(ToolSpec(
        "price_yahoo_history", "deterministic", fn=daily_history,
        note="야후 일봉 시계열",
    ))
    reg.register(ToolSpec(
        "price_yahoo_fundamentals", "deterministic", fn=fundamentals,
        note="야후 PER/EPS",
    ))
    reg.register(ToolSpec("macro_yahoo", "deterministic", fn=collect_macro, note="매크로 세트"))
    reg.register(ToolSpec("toss_feed", "deterministic", fn=collect_feed, note="토스 피드 4탭"))
    reg.register(ToolSpec("toss_company", "deterministic", fn=collect_company, note="토스 회사 번들"))
    reg.register(ToolSpec(
        "toss_market_snapshot", "deterministic", fn=collect_market_snapshot,
        note="토스 랭킹·지표·환율·경제일정 스냅샷",
    ))
    reg.register(ToolSpec(
        "toss_community_aggregate", "deterministic", fn=collect_community_aggregate,
        note="토스 커뮤니티 비식별 집계(원문·작성자 미노출)",
    ))
    reg.register(ToolSpec(
        "market_sector_momentum", "deterministic", fn=collect_sector_momentum,
        note="Toss WICS + 일봉, Yahoo 폴백 KOSPI 업종 모멘텀",
        timeout_s=45.0,
        degrade="fallback",
    ))

    def _snake(value: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()

    # WTS 계약의 exposure=tool 작업을 operationId별로 등록한다. 게스트 전용 작업은
    # 공개 게스트 헤더가 있을 때만 capability=true이며 로그인 쿠키는 받지 않는다.
    for operation in load_wts_catalog()["operations"]:
        if operation.get("exposure") != "tool":
            continue
        operation_id = operation["operationId"]
        reg.register(ToolSpec(
            name=f"toss_wts_{_snake(operation_id)}",
            kind="deterministic",
            fn=partial(execute_wts_operation, operation_id),
            required_env=(
                ("TOSS_WTS_GUEST_HEADERS_JSON",)
                if operation.get("auth") == "guest" else ()
            ),
            note=(
                f"WTS {operation.get('category')} / {operation_id} "
                f"(evidence {operation.get('evidenceGrade')})"
            ),
        ))

    # 공식 OpenAPI의 검토된 14개 GET도 개별 도구로 등록한다. 자격증명이 없으면
    # health capability만 false이고 WTS/Yahoo 폴백에는 영향이 없다.
    for operation_id in official_operation_ids():
        reg.register(ToolSpec(
            name=f"toss_official_{_snake(operation_id)}",
            kind="deterministic",
            fn=partial(execute_official, operation_id),
            required_env=("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET"),
            note=f"공식 Toss OpenAPI read-only / {operation_id}",
            degrade="fallback",
        ))
    # 검색 (에이전트 @tool — fn은 M4에서, env 게이팅만 지금)
    reg.register(ToolSpec("naver_news", "agent_search", required_env=("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"), degrade="fallback"))
    reg.register(ToolSpec("gnews_rss", "agent_search", degrade="fallback", note="구글뉴스 RSS — 무키"))
    return reg
