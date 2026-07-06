"""M2 PoC — 3사 프로바이더 실 API 스모크 (실 키 사용, CI 금지).

    engine/.venv/bin/python -m pytest engine/poc/test_providers.py -v -s

확정된 API (2026-07-02 실측):
- 에이전트 생성: client.as_agent(instructions=...)  (create_agent 아님)
- 실행: await agent.run(text, options={...}) → resp.value (structured), str(resp) (text)
- structured output: options={"response_format": PydanticModel} — OpenAI/Anthropic 모두 OK
- Fable thinking: options={"thinking": {"type": "adaptive"},
                            "output_config": {"effort": "low|medium|high"}, "max_tokens": N}
  ※ "thinking.type.enabled"/budget_tokens는 Fable 미지원 — adaptive+effort로 대체
  ※ thinking + response_format 동시 동작 OK
"""

import asyncio
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402


class _Plan(BaseModel):
    tier: int
    tickers: list[str]


class _Calc(BaseModel):
    multiple: float


def _need(key: str):
    if not key:
        pytest.skip("API key missing")


# ---------------------------------------------------------------- basic chat

def test_openai_basic():
    _need(settings.openai_api_key)
    from agent_framework.openai import OpenAIChatClient

    async def run():
        c = OpenAIChatClient(api_key=settings.openai_api_key, model=settings.model_gpt)
        return str(await c.as_agent(instructions="terse").run("Reply exactly: PONG"))

    out = asyncio.run(run())
    print(f"\n[openai/{settings.model_gpt}] {out[:80]!r}")
    assert out.strip()


def test_anthropic_basic():
    _need(settings.claude_api_key)
    from agent_framework.anthropic import AnthropicClient

    async def run():
        c = AnthropicClient(api_key=settings.claude_api_key, model=settings.model_claude)
        return str(await c.as_agent(instructions="terse").run("Reply exactly: PONG"))

    out = asyncio.run(run())
    print(f"\n[anthropic/{settings.model_claude}] {out[:80]!r}")
    assert out.strip()



# ---------------------------------------------------------------- structured output

def test_openai_structured_output():
    _need(settings.openai_api_key)
    from agent_framework.openai import OpenAIChatClient

    async def run():
        c = OpenAIChatClient(api_key=settings.openai_api_key, model=settings.model_gpt)
        r = await c.as_agent(instructions="Extract plans.").run(
            "삼성전기 올해 왜 올랐어? 종목코드 009150", options={"response_format": _Plan}
        )
        return r.value

    plan = asyncio.run(run())
    print(f"\n[openai SO] tier={plan.tier} tickers={plan.tickers}")
    assert isinstance(plan, _Plan) and plan.tier in range(5)


def test_anthropic_structured_output():
    _need(settings.claude_api_key)
    from agent_framework.anthropic import AnthropicClient

    async def run():
        c = AnthropicClient(api_key=settings.claude_api_key, model=settings.model_claude)
        r = await c.as_agent(instructions="Extract plans.").run(
            "삼성전기 올해 왜 올랐어? 종목코드 009150", options={"response_format": _Plan}
        )
        return r.value

    plan = asyncio.run(run())
    print(f"\n[anthropic SO] tier={plan.tier} tickers={plan.tickers}")
    assert isinstance(plan, _Plan)


# ---------------------------------------------------------------- thinking + effort

def test_fable_thinking_effort_with_structured_output():
    """Fable extended thinking(adaptive) + effort + structured output 동시."""
    _need(settings.claude_api_key)
    from agent_framework.anthropic import AnthropicClient

    async def run(effort: str):
        c = AnthropicClient(api_key=settings.claude_api_key, model=settings.model_claude)
        r = await c.as_agent(instructions="Think then answer.").run(
            "무라타 3330엔→11745엔은 몇 배? multiple 필드에.",
            options={
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": effort},
                "max_tokens": 6000,
                "response_format": _Calc,
            },
        )
        return r.value

    low = asyncio.run(run("low"))
    print(f"\n[fable thinking effort=low +SO] multiple={low.multiple}")
    assert abs(low.multiple - 3.527) < 0.05  # 11745/3330 ≈ 3.527
