import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from pydantic import BaseModel

from cli_role import _build_claude_argv, cli_complete


class _Out(BaseModel):
    answer: str


_ENVELOPE = json.dumps({"type": "result", "is_error": False,
                        "result": "{\"answer\":\"ok\"}",
                        "structured_output": {"answer": "ok"}})


def test_parses_structured_output_field():
    async def runner(argv, stdin_text, timeout):
        return 0, _ENVELOPE, ""
    out = asyncio.run(cli_complete("claude-opus-4-8", "instr", "prompt",
                                   response_format=_Out, runner=runner))
    assert isinstance(out, _Out) and out.answer == "ok"


def test_falls_back_to_result_string():
    async def runner(argv, stdin_text, timeout):
        return 0, json.dumps({"is_error": False, "result": "{\"answer\":\"ok\"}"}), ""
    out = asyncio.run(cli_complete("m", "i", "p", response_format=_Out, runner=runner))
    assert out.answer == "ok"


def test_raises_on_nonzero_and_is_error():
    async def bad_rc(argv, s, t):
        return 1, "", "boom"
    with pytest.raises(Exception):
        asyncio.run(cli_complete("m", "i", "p", response_format=_Out, runner=bad_rc))

    async def err_env(argv, s, t):
        return 0, json.dumps({"is_error": True, "result": "refused"}), ""
    with pytest.raises(Exception):
        asyncio.run(cli_complete("m", "i", "p", response_format=_Out, runner=err_env))


def test_retries_parse_failure_once():
    state = []

    async def runner(argv, stdin_text, timeout):
        if not state:
            state.append(1)
            return 0, "not json", ""
        return 0, _ENVELOPE, ""
    out = asyncio.run(cli_complete("m", "i", "p", response_format=_Out, runner=runner))
    assert out.answer == "ok"


def test_plain_text_mode():
    async def runner(argv, stdin_text, timeout):
        return 0, json.dumps({"is_error": False, "result": "그냥 텍스트"}), ""
    out = asyncio.run(cli_complete("m", "i", "p", runner=runner))
    assert out == "그냥 텍스트"


def test_argv_inline_schema_tools_off():
    schema = json.dumps(_Out.model_json_schema())
    argv = _build_claude_argv("claude-opus-4-8", schema, "high")
    assert argv[0] == "claude" and "-p" in argv
    i = argv.index("--json-schema")
    json.loads(argv[i + 1])                       # 인라인 JSON — 파일 경로 아님
    j = argv.index("--tools")
    assert argv[j + 1] == ""                      # 실측: 이게 진짜 툴 오프
    assert "--allowedTools" not in argv           # 실측: Read/Bash 못 막음
    assert "--no-session-persistence" in argv


def test_role_falls_back_to_next_provider_when_cli_raises(monkeypatch):
    import providers as pv

    async def boom(*a, **k):
        raise RuntimeError("cli down")
    monkeypatch.setattr("cli_role.cli_complete", boom)
    monkeypatch.setattr(pv, "_capable", lambda p: True)

    class _Resp:
        value = None
        usage_details = {}

        def __str__(self):
            return "api-answer"

    class _Agent:
        async def run(self, prompt, options=None):
            return _Resp()

    class _Client:
        def as_agent(self, instructions=""):
            return _Agent()

    monkeypatch.setattr(pv, "_make_client", lambda p, m: _Client())
    role = pv.Role("x", overrides={"x": [("cli", "claude-opus-4-8", "high"),
                                         ("anthropic", "claude-opus-4-8", "high")]})
    out = asyncio.run(role.run("q"))
    assert out == "api-answer"                    # cli raise → 다음 체인으로 폴백


def test_retry_shares_total_deadline():
    """파싱 재시도가 데드라인을 새로 받으면 CLI 다리 혼자 스테이지 예산을
    소진한다(07-27 axis_split 5연속 1200s 타임아웃) — 총합 timeout 강제."""
    seen = []

    async def runner(argv, stdin_text, timeout):
        seen.append(timeout)
        await asyncio.sleep(0.05)
        if len(seen) == 1:
            return 0, "not json", ""              # 1차: 파싱 실패 → 재시도
        return 0, _ENVELOPE, ""
    out = asyncio.run(cli_complete("m", "i", "p", response_format=_Out,
                                   runner=runner, timeout=10.0))
    assert out.answer == "ok"
    assert seen[0] <= 10.0
    assert seen[1] < seen[0]                      # 2차는 잔여 시간만


def test_deadline_exhausted_skips_retry():
    async def runner(argv, stdin_text, timeout):
        await asyncio.sleep(0.06)
        return 0, "not json", ""                  # 항상 파싱 실패
    with pytest.raises(RuntimeError):
        # 총 데드라인 0.05s — 잔여 ≤5s 가드에 걸려 시도 자체가 차단된다
        asyncio.run(cli_complete("m", "i", "p", response_format=_Out,
                                 runner=runner, timeout=0.05))
