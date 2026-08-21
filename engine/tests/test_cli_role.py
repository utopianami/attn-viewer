import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from pydantic import BaseModel

import cli_role
from cli_role import _build_claude_argv, claude_complete


class _Out(BaseModel):
    answer: str


class _NestedOut(BaseModel):
    required_value: str
    default_value: str = ""


class _OutWithNestedDefaults(BaseModel):
    nested: _NestedOut
    optional_note: str | None = None


_ENVELOPE = json.dumps({"type": "result", "is_error": False,
                        "result": "{\"answer\":\"ok\"}",
                        "structured_output": {"answer": "ok"}})


def test_scrub_llm_api_env_preserves_data_keys_and_parent():
    """Deleting the copied keys, data API keys, or the source mapping is a bug."""
    source = {
        "CLAUDE_API_KEY": "claude-secret",
        "ANTHROPIC_API_KEY": "anthropic-secret",
        "OPENAI_API_KEY": "openai-secret",
        "CODEX_API_KEY": "codex-secret",
        "XAI_API_KEY": "xai-secret",
        "OPENROUTER_API_KEY": "keep-openrouter",
        "KOSIS_API_KEY": "keep-kosis",
        "PATH": "/bin",
    }

    child = cli_role.scrub_llm_api_env(source)

    assert not ({"CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                 "CODEX_API_KEY", "XAI_API_KEY"} & child.keys())
    assert child["OPENROUTER_API_KEY"] == "keep-openrouter"
    assert child["KOSIS_API_KEY"] == "keep-kosis"
    assert child["PATH"] == "/bin"
    assert source["OPENAI_API_KEY"] == "openai-secret"


def test_codex_argv_is_ephemeral_read_only_and_schema_bound(tmp_path):
    """Codex must not inherit a writable/project-aware agent execution mode."""
    schema_path = tmp_path / "schema.json"

    argv = cli_role._build_codex_argv(
        "gpt-5.5", str(schema_path), "high", str(tmp_path))

    assert argv[:2] == ["codex", "exec"]
    assert "--ephemeral" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in argv
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert argv[argv.index("--output-schema") + 1] == str(schema_path)
    assert argv[argv.index("--model") + 1] == "gpt-5.5"
    assert argv[argv.index("-C") + 1] == str(tmp_path)
    assert 'model_reasoning_effort="high"' in argv
    assert argv[-1] == "-"


def test_codex_structured_output_uses_schema_and_scrubbed_env(monkeypatch):
    """Missing schema validation or inherited API auth would restore API-style execution."""
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-leak")
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-survive")
    seen = {}

    async def runner(argv, stdin_text, timeout, *, cwd, env):
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        seen.update(
            stdin=stdin_text,
            timeout=timeout,
            cwd=cwd,
            env=env,
            schema=json.loads(schema_path.read_text(encoding="utf-8")),
        )
        return 0, '{"answer":"ok"}', ""

    out = asyncio.run(cli_role.codex_complete(
        "gpt-5.5", "instr", "prompt",
        response_format=_Out, effort="high", runner=runner, timeout=10.0))

    assert out == _Out(answer="ok")
    assert seen["stdin"] == "instr\n\nprompt"
    assert seen["timeout"] <= 10.0
    assert seen["schema"]["additionalProperties"] is False
    assert seen["schema"]["required"] == ["answer"]
    assert "OPENAI_API_KEY" not in seen["env"]
    assert "CODEX_API_KEY" not in seen["env"]
    assert seen["env"]["OPENROUTER_API_KEY"] == "must-survive"
    assert not Path(seen["cwd"]).exists()


def test_codex_schema_is_strict_for_root_and_nested_default_fields():
    """Codex rejects object schemas unless every property is required and closed."""
    seen = {}

    async def runner(argv, stdin_text, timeout, *, cwd, env):
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        seen["schema"] = schema
        return 0, json.dumps({
            "nested": {"required_value": "ok", "default_value": ""},
            "optional_note": None,
        }), ""

    out = asyncio.run(cli_role.codex_complete(
        "gpt-5.5", "instr", "prompt", response_format=_OutWithNestedDefaults,
        effort="low", runner=runner, timeout=10.0))

    root = seen["schema"]
    nested = root["$defs"]["_NestedOut"]
    assert root["additionalProperties"] is False
    assert root["required"] == ["nested", "optional_note"]
    assert nested["additionalProperties"] is False
    assert nested["required"] == ["required_value", "default_value"]
    assert out.nested.required_value == "ok"
    assert out.optional_note is None


def test_claude_complete_uses_scrubbed_env_and_temporary_cwd(monkeypatch):
    """Claude subprocesses must not silently prefer a parent-shell API key."""
    monkeypatch.setenv("CLAUDE_API_KEY", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-survive")
    seen = {}

    async def runner(argv, stdin_text, timeout, *, cwd, env):
        seen.update(argv=argv, stdin=stdin_text, cwd=cwd, env=env)
        return 0, json.dumps({"is_error": False, "result": "plain answer"}), ""

    out = asyncio.run(cli_role.claude_complete(
        "claude-sonnet-4-6", "instr", "prompt", runner=runner, timeout=10.0))

    assert out == "plain answer"
    assert seen["argv"][0] == "claude"
    assert seen["stdin"] == "instr\n\nprompt"
    assert "CLAUDE_API_KEY" not in seen["env"]
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert seen["env"]["OPENROUTER_API_KEY"] == "must-survive"
    assert not Path(seen["cwd"]).exists()


def test_parses_structured_output_field():
    async def runner(argv, stdin_text, timeout, **kwargs):
        return 0, _ENVELOPE, ""
    out = asyncio.run(claude_complete("claude-opus-4-8", "instr", "prompt",
                                      response_format=_Out, runner=runner))
    assert isinstance(out, _Out) and out.answer == "ok"


def test_falls_back_to_result_string():
    async def runner(argv, stdin_text, timeout, **kwargs):
        return 0, json.dumps({"is_error": False, "result": "{\"answer\":\"ok\"}"}), ""
    out = asyncio.run(claude_complete("m", "i", "p", response_format=_Out, runner=runner))
    assert out.answer == "ok"


def test_raises_on_nonzero_and_is_error():
    async def bad_rc(argv, s, t, **kwargs):
        return 1, "", "boom"
    with pytest.raises(Exception):
        asyncio.run(claude_complete("m", "i", "p", response_format=_Out, runner=bad_rc))

    async def err_env(argv, s, t, **kwargs):
        return 0, json.dumps({"is_error": True, "result": "refused"}), ""
    with pytest.raises(Exception):
        asyncio.run(claude_complete("m", "i", "p", response_format=_Out, runner=err_env))


def test_retries_parse_failure_once():
    state = []

    async def runner(argv, stdin_text, timeout, **kwargs):
        if not state:
            state.append(1)
            return 0, "not json", ""
        return 0, _ENVELOPE, ""
    out = asyncio.run(claude_complete("m", "i", "p", response_format=_Out, runner=runner))
    assert out.answer == "ok"


def test_plain_text_mode():
    async def runner(argv, stdin_text, timeout, **kwargs):
        return 0, json.dumps({"is_error": False, "result": "그냥 텍스트"}), ""
    out = asyncio.run(claude_complete("m", "i", "p", runner=runner))
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


def test_role_falls_back_from_claude_cli_to_codex_cli(monkeypatch):
    """A Claude outage may use Codex CLI, but must not reopen an API path."""
    import providers as pv
    calls = []

    async def claude_down(*args, **kwargs):
        calls.append("claude")
        raise RuntimeError("claude down")

    async def codex_ok(*args, **kwargs):
        calls.append("codex")
        return "codex answer"

    monkeypatch.setattr("cli_role.claude_complete", claude_down)
    monkeypatch.setattr("cli_role.codex_complete", codex_ok)
    monkeypatch.setattr(pv, "_capable", lambda p: True)
    role = pv.Role("x", overrides={"x": [
        ("claude_cli", "claude-sonnet-4-6", "low"),
        ("codex_cli", "gpt-5.4-mini", "low"),
    ]})
    out = asyncio.run(role.run("q"))

    assert out == "codex answer"
    assert calls == ["claude", "codex"]


def test_retry_shares_total_deadline():
    """파싱 재시도가 데드라인을 새로 받으면 CLI 다리 혼자 스테이지 예산을
    소진한다(07-27 axis_split 5연속 1200s 타임아웃) — 총합 timeout 강제."""
    seen = []

    async def runner(argv, stdin_text, timeout, **kwargs):
        seen.append(timeout)
        await asyncio.sleep(0.05)
        if len(seen) == 1:
            return 0, "not json", ""              # 1차: 파싱 실패 → 재시도
        return 0, _ENVELOPE, ""
    out = asyncio.run(claude_complete("m", "i", "p", response_format=_Out,
                                      runner=runner, timeout=10.0))
    assert out.answer == "ok"
    assert seen[0] <= 10.0
    assert seen[1] < seen[0]                      # 2차는 잔여 시간만


def test_deadline_exhausted_skips_retry():
    async def runner(argv, stdin_text, timeout, **kwargs):
        await asyncio.sleep(0.06)
        return 0, "not json", ""                  # 항상 파싱 실패
    with pytest.raises(RuntimeError):
        # 총 데드라인 0.05s — 잔여 ≤5s 가드에 걸려 시도 자체가 차단된다
        asyncio.run(claude_complete("m", "i", "p", response_format=_Out,
                                    runner=runner, timeout=0.05))


class _HangProc:
    """spawn은 됐지만 영원히 안 끝나는 자식 — 07-28 06:30 회차 axis_split
    침묵 1200s의 재현체(킬 후 회수까지 행)."""
    pid = 424242
    returncode = None

    async def communicate(self, data=None):
        await asyncio.Event().wait()

    async def wait(self):
        await asyncio.Event().wait()


def test_run_cli_deadline_covers_hung_reap(monkeypatch):
    """communicate 타임아웃 → 킬 → wait()가 행이어도 데드라인+회수상한 안에
    RuntimeError로 탈출해야 한다(무한 대기 = 스테이지 예산 통째 소진)."""
    import time

    import cli_role

    async def fake_spawn(*a, **k):
        return _HangProc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    killed = []
    monkeypatch.setattr("os.killpg", lambda pgid, sig: killed.append(pgid))
    monkeypatch.setattr(cli_role, "_REAP_TIMEOUT_S", 0.05)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="cli timeout"):
        # 외곽 가드 2s — 구멍이 있으면 행이 아니라 TimeoutError로 즉시 실패
        asyncio.run(asyncio.wait_for(cli_role._run_cli(["claude"], "p", 0.1), 2))
    assert time.monotonic() - t0 < 1.0
    assert killed == [_HangProc.pid]


def test_run_cli_deadline_covers_hung_spawn(monkeypatch):
    """create_subprocess_exec 자체가 행이어도 데드라인이 문다 — 기존 코드는
    스폰이 wait_for 바깥이라 무한 대기 구멍이었다."""
    import time

    import cli_role

    async def hang_spawn(*a, **k):
        await asyncio.Event().wait()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", hang_spawn)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="cli timeout"):
        asyncio.run(asyncio.wait_for(cli_role._run_cli(["claude"], "p", 0.1), 2))
    assert time.monotonic() - t0 < 1.0


def test_claude_complete_logs_entry(caplog):
    """시작 로그 — 완료 로그만 있으면 행 지점을 못 가른다(07-28 회차:
    cli_run 부재가 'CLI에 도달했는가'조차 판별 불가하게 만든 실측)."""
    import logging

    async def runner(argv, stdin_text, timeout, **kwargs):
        return 0, _ENVELOPE, ""
    with caplog.at_level(logging.INFO, logger="cli_role"):
        asyncio.run(claude_complete("m", "i", "p", response_format=_Out,
                                    runner=runner, timeout=7.0))
    assert any("cli_start" in r.getMessage() for r in caplog.records)
