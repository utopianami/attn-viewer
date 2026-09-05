"""역할→Claude/Codex CLI 매핑과 CLI 간 폴백 실행기."""

from __future__ import annotations

import contextvars
from typing import Any

from app.settings import settings
from cli_role import CLAUDE_CLI, CODEX_CLI

_CLI_EXECUTORS = frozenset({CLAUDE_CLI, CODEX_CLI})

# run 범위 CostMeter — 오케스트레이터가 질문마다 set. Role이 자동으로 집어 사용.
current_meter: contextvars.ContextVar["CostMeter | None"] = contextvars.ContextVar(
    "current_meter", default=None
)

# 역할 → 순서대로 (executor, model, effort) 폴백 체인
ROLE_MAP: dict[str, list[tuple[str, str, str]]] = {
    "planner":     [(CLAUDE_CLI, settings.model_claude, "low"),
                    (CODEX_CLI, settings.model_gpt, "low")],
    "plan_extract": [(CODEX_CLI, settings.model_gpt_mini, "low"),
                     (CLAUDE_CLI, settings.model_claude, "low")],
    "da_gpt":      [(CODEX_CLI, settings.model_gpt, "medium")],
    "da_fable":    [(CLAUDE_CLI, settings.model_claude, "medium")],
    "extract":     [(CODEX_CLI, settings.model_gpt_mini, "low"),
                    (CLAUDE_CLI, settings.model_claude, "low")],
    "calc_program": [(CODEX_CLI, settings.model_gpt, "medium")],
    "verifier":    [(CLAUDE_CLI, settings.model_claude, "medium")],
    "verifier_cross": [(CODEX_CLI, settings.model_gpt, "medium")],
    "risk":        [(CLAUDE_CLI, settings.model_claude, "low")],
    "synthesizer": [(CLAUDE_CLI, settings.model_claude, "high")],
    "audit":       [(CODEX_CLI, settings.model_gpt_mini, "low")],
    # thesis 교차 verifier (2부 T4): updater LLM과 다른 provider로 판정 —
    # Claude 폴백 금지(교차 검증 취지 훼손, self-preference 회피).
    "thesis_verifier": [(CODEX_CLI, settings.model_gpt_mini, "low")],
    # 테제 updater 제안 LLM (2부 T5): 경량 sonnet — 구조화 제안뿐, assessment 판단 없음.
    "thesis_updater": [(CLAUDE_CLI, settings.model_claude_sonnet, "low")],
    # ChainPacket 합성 제안 LLM (3부 T5): 경량 sonnet — 사건·edge·인용 ID 제안뿐,
    # 검증은 전부 코드(stages/chain.py). thesis_updater와 동형.
    "chain_synth": [(CLAUDE_CLI, settings.model_claude_sonnet, "low")],
    "chain_judge": [(CODEX_CLI, settings.model_gpt, "medium")],
    "news_summary": [(CLAUDE_CLI, settings.model_claude_sonnet, "low"),
                     (CODEX_CLI, settings.model_gpt_mini, "low")],
    # 배경지식 생성 (2026-07-09): 검색 대체 후 모델 지식이 소스 그 자체 — mini는 지식 깊이 부족.
    # sonnet 채택 (뉴스 요약과 동급 단가), 다운 시 gpt 본체 (mini 아님 — 품질 우선)
    "web_knowledge": [(CLAUDE_CLI, settings.model_claude_sonnet, "low"),
                      (CODEX_CLI, settings.model_gpt, "low")],
    "sector_judge": [(CLAUDE_CLI, settings.model_claude_sonnet, "low"),
                     (CODEX_CLI, settings.model_gpt_mini, "low")],
    # 섹터 검색 플래너 (2026-07-13): 질문 → SectorQueryPlan 구조화 출력. 경량이면 충분
    "sector_query": [(CLAUDE_CLI, settings.model_claude_sonnet, "low"),
                     (CODEX_CLI, settings.model_gpt_mini, "low")],
    "report_filter": [(CLAUDE_CLI, settings.model_claude_sonnet, "low"),
                      (CODEX_CLI, settings.model_gpt_mini, "low")],
    # deepen effort high→medium (2026-07-23): high가 -1·-2호 연속 40분 타임아웃 유발
    "report_deepen": [(CLAUDE_CLI, settings.model_claude, "medium")],
    "report_synth":  [(CLAUDE_CLI, settings.model_claude, "high")],
    "report_article": [(CLAUDE_CLI, settings.model_claude, "high"),
                       (CODEX_CLI, settings.model_gpt, "high")],
    # 읽기 편집은 감사된 카드의 문장·배치만 바꾸는 구조화 작업이다. 장문 추론용
    # Opus 역할과 분리해 06:30/18:30 예약 시간 안에 끝내되 교차 CLI 폴백은 유지한다.
    "report_readability": [(CLAUDE_CLI, settings.model_claude_sonnet, "low"),
                           (CODEX_CLI, settings.model_gpt_mini, "low")],
    # 과거사례 구조 리랭크 (Plan4-a, 2026-07-22): 0~1 채점 JSON — 경량이면 충분
    "casemem_rerank": [(CLAUDE_CLI, settings.model_claude_sonnet, "low"),
                       (CODEX_CLI, settings.model_gpt_mini, "low")],
    # 규칙 백테스트 판정 (Plan5 1단계, 2026-07-23): 트리거/귀결 판정만 — 집계·승격은 코드
    "rule_backtest": [(CLAUDE_CLI, settings.model_claude_sonnet, "low"),
                      (CODEX_CLI, settings.model_gpt_mini, "low")],
}


class CostMeter:
    """한 run의 CLI 실행 횟수. API 달러 비용으로 환산하지 않는다."""

    def __init__(self) -> None:
        self.cli_runs: dict[str, int] = {}

    def record_cli(self, executor: str, model: str) -> None:
        del model
        label = "claude" if executor == CLAUDE_CLI else "codex"
        self.cli_runs[label] = self.cli_runs.get(label, 0) + 1

    def summary(self) -> dict:
        return {
            "by_provider": {},
            "total_usd": 0.0,
            "tokens": {},
            "billing_mode": "cli_subscription",
            "cli_runs": dict(self.cli_runs),
        }


def _capable(executor: str) -> bool:
    return settings.capabilities().get(executor, False)


class Role:
    """역할별 CLI 실행 래퍼 — 명시된 CLI 체인 안에서만 폴백한다."""

    def __init__(self, role: str, overrides: dict | None = None, meter: "CostMeter | None" = None):
        chain = (overrides or {}).get(role) or ROLE_MAP.get(role)
        if chain is None:
            raise ValueError(f"unknown role: {role}")
        unsupported = sorted({executor for executor, _model, _effort in chain
                              if executor not in _CLI_EXECUTORS})
        if unsupported:
            raise ValueError(
                f"unsupported executor for role={role}: {', '.join(unsupported)}")
        self.role = role
        self.meter = meter if meter is not None else current_meter.get()
        self.chain = [(p, m, e) for (p, m, e) in chain if _capable(p)]
        if not self.chain:
            raise RuntimeError(f"no capable provider for role={role}")
        self.provider, self.model, self.effort = self.chain[0]

    async def run(self, prompt: str, instructions: str = "", *,
                  response_format: Any | None = None, effort: str | None = None,
                  cache_prefix: str | None = None, timeout: float | None = None):
        """CLI 체인을 순서대로 시도하고 API 클라이언트는 만들지 않는다."""
        instr = instructions or "You are a precise financial analysis assistant."
        last_err: Exception | None = None
        for executor, model, e in self.chain:
            try:
                self.provider, self.model = executor, model
                import cli_role
                cli_prompt = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
                complete = {
                    CLAUDE_CLI: cli_role.claude_complete,
                    CODEX_CLI: cli_role.codex_complete,
                }[executor]
                result = await complete(
                    model, instr, cli_prompt,
                    response_format=response_format, effort=effort or e,
                    timeout=timeout)
                if self.meter is not None:
                    self.meter.record_cli(executor, model)
                return result
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                import logging
                logging.getLogger("providers").info(
                    "role=%s leg %s/%s failed: %s", self.role, executor, model,
                    str(exc)[:200])
                continue
        raise RuntimeError(f"role={self.role} all providers failed: {last_err}")
