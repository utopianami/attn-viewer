"""프로바이더 팩토리 — 역할→모델 매핑 (M2 실측 API 확정).

역할 분리: 생산자(GPT) / 계획자·심판(Claude). ROLE_MAP은 데이터라
profile이 override 가능. 폴백 체인은 capability(키 존재) 순서대로.
2026-07-06 비용 절감: fable-5 → opus-4.8 (동일 옵션 형식 스모크 확인), grok 제거.

M2 확정:
- 에이전트 생성: client.as_agent(instructions=...)
- Claude thinking: options={"thinking":{"type":"adaptive"},"output_config":{"effort":...},"max_tokens":N}
- structured output: options={"response_format": Model} → resp.value
"""

from __future__ import annotations

import contextvars
from typing import Any

from app.settings import settings

# run 범위 CostMeter — 오케스트레이터가 질문마다 set. Role이 자동으로 집어 사용.
current_meter: contextvars.ContextVar["CostMeter | None"] = contextvars.ContextVar(
    "current_meter", default=None
)

# 역할 → 순서대로 (provider, model, effort) 폴백 체인
ROLE_MAP: dict[str, list[tuple[str, str, str]]] = {
    "planner":     [("anthropic", settings.model_claude, "low"), ("openai", settings.model_gpt, "low")],
    "plan_extract": [("openai", settings.model_gpt_mini, "low"), ("anthropic", settings.model_claude, "low")],
    "da_gpt":      [("openai", settings.model_gpt, "medium")],  # 2026-07-06 high→medium (설계 A/B 회귀 조항). GPT 다운 시 skip+표기
    "da_fable":    [("anthropic", settings.model_claude, "medium")],
    "extract":     [("openai", settings.model_gpt_mini, "low"), ("anthropic", settings.model_claude, "low")],
    "calc_program": [("openai", settings.model_gpt, "medium")],
    "verifier":    [("anthropic", settings.model_claude, "medium")],
    "verifier_cross": [("openai", settings.model_gpt, "medium")],  # da_fable claim 교차 채점
    "risk":        [("anthropic", settings.model_claude, "low")],
    "synthesizer": [("anthropic", settings.model_claude, "high")],
    "audit":       [("openai", settings.model_gpt_mini, "low")],
    # thesis 교차 verifier (2부 T4): updater LLM과 다른 provider로 판정 —
    # anthropic 폴백 금지(교차 검증 취지 훼손, self-preference 회피).
    "thesis_verifier": [("openai", settings.model_gpt_mini, "low")],
    # 테제 updater 제안 LLM (2부 T5): 경량 sonnet — 구조화 제안뿐, assessment 판단 없음.
    "thesis_updater": [("anthropic", settings.model_claude_sonnet, "low")],
    # ChainPacket 합성 제안 LLM (3부 T5): 경량 sonnet — 사건·edge·인용 ID 제안뿐,
    # 검증은 전부 코드(stages/chain.py). thesis_updater와 동형.
    "chain_synth": [("anthropic", settings.model_claude_sonnet, "low")],
    "chain_judge": [("openai", settings.model_gpt, "medium")],  # 교차 저지 — anthropic 폴백 금지(self-preference)
    "news_summary": [("anthropic", settings.model_claude_sonnet, "low"),
                     ("openai", settings.model_gpt_mini, "low")],
    # 배경지식 생성 (2026-07-09): 검색 대체 후 모델 지식이 소스 그 자체 — mini는 지식 깊이 부족.
    # sonnet 채택 (뉴스 요약과 동급 단가), 다운 시 gpt 본체 (mini 아님 — 품질 우선)
    "web_knowledge": [("anthropic", settings.model_claude_sonnet, "low"),
                      ("openai", settings.model_gpt, "low")],
    "sector_judge": [("anthropic", settings.model_claude_sonnet, "low"),
                     ("openai", settings.model_gpt_mini, "low")],
    # 섹터 검색 플래너 (2026-07-13): 질문 → SectorQueryPlan 구조화 출력. 경량이면 충분
    "sector_query": [("anthropic", settings.model_claude_sonnet, "low"),
                     ("openai", settings.model_gpt_mini, "low")],
    # 시황 리포트 파이프라인 (2026-07-22, 스펙 v3): 필터=API 경량, 심화·합성=CLI(하루 2회
    # 배치 — 속도 무관, agentic 추론 우선. 사용자 결정) → 실패 시 API opus 폴백.
    "report_filter": [("anthropic", settings.model_claude_sonnet, "low"),
                      ("openai", settings.model_gpt_mini, "low")],
    # deepen effort high→medium (2026-07-23): high가 -1·-2호 연속 40분 타임아웃 유발
    "report_deepen": [("cli", settings.model_claude, "medium"),
                      ("anthropic", settings.model_claude, "medium")],
    "report_synth":  [("cli", settings.model_claude, "high"),
                      ("anthropic", settings.model_claude, "high")],
    # Phase 4 (2026-07-23): 드래프트·완결 글 — CLI 우선, API opus 폴백.
    # 추가 조사(research)는 웹 도구가 CLI 전용이라 Role 체인을 안 탄다(report_article.py).
    "report_article": [("cli", settings.model_claude, "high"),
                       ("anthropic", settings.model_claude, "high")],
    # 과거사례 구조 리랭크 (Plan4-a, 2026-07-22): 0~1 채점 JSON — 경량이면 충분
    "casemem_rerank": [("anthropic", settings.model_claude_sonnet, "low"),
                       ("openai", settings.model_gpt_mini, "low")],
    # 규칙 백테스트 판정 (Plan5 1단계, 2026-07-23): 트리거/귀결 판정만 — 집계·승격은 코드
    "rule_backtest": [("anthropic", settings.model_claude_sonnet, "low"),
                      ("openai", settings.model_gpt_mini, "low")],
}

_EFFORT_MAX_TOKENS = {"low": 4000, "medium": 8000, "high": 16000}

# 백만 토큰당 USD (input, output) — 2026-07-06 공식 단가 실측 검증.
_PRICE_PER_M = {
    "anthropic": (5.0, 25.0),    # claude-opus-4-8 ($5/$25)
    "anthropic_sonnet": (3.0, 15.0),  # claude-sonnet-4-6 ($3/$15) — 2026-07-06 공식 단가 검증
    "openai": (5.0, 30.0),       # gpt-5.5 ($5/$30)
    "openai_mini": (0.75, 4.50),  # gpt-5.4-mini ($0.75/$4.50)
}


class CostMeter:
    """한 run(질문) 동안 provider별 토큰·비용 누적. 오케스트레이터가 인스턴스 하나를 공유."""

    def __init__(self) -> None:
        self.tokens: dict[str, list[int]] = {}   # bucket → [input, output]
        self.usd: dict[str, float] = {}          # provider(claude/openai) → USD

    def add(self, provider: str, model: str, inp: int, out: int,
            cache_read: int = 0, cache_write: int = 0) -> None:
        is_mini = "mini" in (model or "")
        if provider == "openai" and is_mini:
            bucket = "openai_mini"
        elif provider == "anthropic" and "sonnet" in (model or ""):
            bucket = "anthropic_sonnet"
        else:
            bucket = provider
        pin, pout = _PRICE_PER_M.get(bucket, (0.0, 0.0))
        # 캐시 단가 (anthropic): 읽기 = 입력의 10%, 쓰기 = 입력의 125%
        cost = (inp / 1e6 * pin + out / 1e6 * pout
                + cache_read / 1e6 * pin * 0.10 + cache_write / 1e6 * pin * 1.25)
        self._record(bucket, cost, inp + cache_read + cache_write, out)

    def add_usd(self, provider: str, usd: float, inp: int = 0, out: int = 0) -> None:
        """공급자가 직접 준 실비용 기록 (예: xAI cost_in_usd_ticks — 웹검색비 포함)."""
        self._record(provider, usd, inp, out)

    def _record(self, bucket: str, cost: float, inp: int, out: int) -> None:
        label = {"anthropic": "claude", "anthropic_sonnet": "claude",
                 "openai": "openai", "openai_mini": "openai"}.get(bucket, bucket)
        self.usd[label] = round(self.usd.get(label, 0.0) + cost, 4)
        t = self.tokens.setdefault(label, [0, 0])
        t[0] += inp
        t[1] += out

    def summary(self) -> dict:
        total = round(sum(self.usd.values()), 4)
        return {"by_provider": dict(self.usd), "total_usd": total,
                "tokens": {k: {"input": v[0], "output": v[1]} for k, v in self.tokens.items()}}


def _capable(provider: str) -> bool:
    if provider == "cli":
        # cli_complete는 claude 바이너리를 띄운다 — codex-only 설치는 불능(계획 리뷰 B2)
        import shutil
        return shutil.which("claude") is not None
    return settings.capabilities().get(provider, False)


_ANTHROPIC_SCHEMA_PATCHED = False


def _patch_anthropic_nested_schema() -> None:
    """구조화 출력 스키마의 중첩 object에 additionalProperties:false 재귀 주입.

    anthropic API가 모든 object에 additionalProperties:false를 요구하는데
    agent_framework(b260630)는 최상위에만 넣는다 — 중첩 모델($defs) 있는
    response_format이 전부 400 (2026-07-24 실측: report_filter 13연속 400,
    폴백 체인의 anthropic 레그 전멸). 프레임워크 수정판 나오면 제거."""
    global _ANTHROPIC_SCHEMA_PATCHED
    if _ANTHROPIC_SCHEMA_PATCHED:
        return
    from agent_framework_anthropic._chat_client import RawAnthropicClient

    def _rec(node):
        if isinstance(node, dict):
            # properties 있는 object만 — 자유형 dict({"type":"object"}만)는 잠그면
            # 항상 빈 객체가 강제되므로 건드리지 않는다
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
            for v in node.values():
                _rec(v)
        elif isinstance(node, list):
            for v in node:
                _rec(v)

    orig = RawAnthropicClient._prepare_response_format

    def patched(self, response_format):
        out = orig(self, response_format)
        _rec(out.get("schema"))
        return out

    RawAnthropicClient._prepare_response_format = patched
    _ANTHROPIC_SCHEMA_PATCHED = True


def _make_client(provider: str, model: str):
    if provider == "anthropic":
        from agent_framework.anthropic import AnthropicClient
        _patch_anthropic_nested_schema()
        return AnthropicClient(api_key=settings.claude_api_key, model=model)
    if provider == "openai":
        from agent_framework.openai import OpenAIChatClient
        return OpenAIChatClient(api_key=settings.openai_api_key, model=model)
    raise ValueError(f"unknown provider: {provider}")


class Role:
    """역할별 에이전트 실행 래퍼 — 폴백 체인 + effort/thinking 옵션 구성."""

    def __init__(self, role: str, overrides: dict | None = None, meter: "CostMeter | None" = None):
        chain = (overrides or {}).get(role) or ROLE_MAP.get(role)
        if chain is None:
            raise ValueError(f"unknown role: {role}")
        self.role = role
        self.meter = meter if meter is not None else current_meter.get()
        self.chain = [(p, m, e) for (p, m, e) in chain if _capable(p)]
        if not self.chain:
            raise RuntimeError(f"no capable provider for role={role}")
        self.provider, self.model, self.effort = self.chain[0]

    def _options(self, effort: str, response_format: Any | None) -> dict:
        opts: dict[str, Any] = {}
        if self.provider == "anthropic":
            # Claude: adaptive thinking + output_config.effort + max_tokens 필수
            opts["thinking"] = {"type": "adaptive"}
            opts["output_config"] = {"effort": effort}
            opts["max_tokens"] = _EFFORT_MAX_TOKENS.get(effort, 8000)
        elif self.provider == "openai":
            # Responses API는 structured output과 reasoning.effort 동시 허용
            # (2026-07-06 확인 — 기존 "parse()라 미허용" 주석은 chat.completions 시절 얘기).
            # 이전엔 미전달 = 모델 기본값이었으므로 ROLE_MAP effort가 이제야 실효.
            opts["reasoning"] = {"effort": effort}
        if response_format is not None:
            opts["response_format"] = response_format
        return opts

    async def run(self, prompt: str, instructions: str = "", *,
                  response_format: Any | None = None, effort: str | None = None,
                  cache_prefix: str | None = None, timeout: float | None = None):
        """폴백 체인을 순서대로 시도. structured면 resp.value, 아니면 str(resp).

        timeout: CLI 다리 총 데드라인(초). 스테이지 예산이 있는 호출부가 CLI 몫을
        잘라 API 폴백 시간을 보장할 때 쓴다(미지정 시 cli_role 기본 600s).
        API 다리는 호출부의 asyncio.wait_for가 감싼다 — 여기선 제한하지 않는다.

        cache_prefix: 같은 run 안에서 여러 콜이 공유하는 큰 컨텍스트(예: G1 증거).
        anthropic이면 system 블록 + cache_control(ephemeral, 5분)로 보내 반복분 90% 할인.
        타 프로바이더는 프롬프트 앞에 그대로 붙임 (OpenAI는 동일 접두사 자동 캐싱).
        """
        instr = instructions or "You are a precise financial analysis assistant."
        last_err: Exception | None = None
        for provider, model, e in self.chain:
            try:
                self.provider, self.model = provider, model
                if provider == "cli":
                    # CLI 실행기 분기 — _make_client는 cli를 모름(ValueError). raise 시
                    # 아래 except가 잡아 다음 체인(API)으로 — 폴백 의미 보존. CLI엔 캐시
                    # 없으므로 cache_prefix는 프롬프트 접두로.
                    import cli_role
                    cli_prompt = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
                    return await cli_role.cli_complete(
                        model, instr, cli_prompt,
                        response_format=response_format, effort=effort or e,
                        timeout=timeout)
                client = _make_client(provider, model)
                opts = self._options(effort or e, response_format)
                run_prompt = prompt
                if cache_prefix and provider == "anthropic":
                    # instructions를 agent가 아니라 system 블록으로 — 안 그러면
                    # MAF가 system을 문자열로 덮어써 cache_control이 소실됨
                    agent = client.as_agent()
                    opts["system"] = [
                        {"type": "text", "text": instr},
                        {"type": "text", "text": cache_prefix,
                         "cache_control": {"type": "ephemeral"}},
                    ]
                else:
                    agent = client.as_agent(instructions=instr)
                    if cache_prefix:
                        run_prompt = f"{cache_prefix}\n\n{prompt}"
                resp = await agent.run(run_prompt, options=opts)
                if self.meter is not None:
                    ud = getattr(resp, "usage_details", None) or {}
                    self.meter.add(provider, model,
                                   int(ud.get("input_token_count", 0) or 0),
                                   int(ud.get("output_token_count", 0) or 0),
                                   cache_read=int(ud.get("cache_read_input_token_count", 0) or 0),
                                   cache_write=int(ud.get("cache_creation_input_token_count", 0) or 0))
                if response_format is not None:
                    return resp.value
                return str(resp)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        raise RuntimeError(f"role={self.role} all providers failed: {last_err}")
