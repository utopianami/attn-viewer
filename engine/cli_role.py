"""claude CLI 구조화 출력 실행기 — --tools ""(실측 유일 툴오프)·인라인 --json-schema·
세션 미영속·스크래치 cwd·프로세스그룹 타임아웃. 실패 raise → Role 폴백 체인이 이어받음.
실측(2026-07-22, codex 스모크): --json-schema는 인라인 JSON(파일 경로면 exit 1),
출력 envelope의 structured_output이 canonical, --allowedTools ""는 Read/Bash 못 막음."""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import tempfile
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel

_TIMEOUT = 600.0
_MAX_OUT = 2_000_000
_REAP_TIMEOUT_S = 10.0   # 킬 후 회수(wait) 상한 — 무한 대기 금지(07-28 침묵 행 실측)
CLAUDE_CLI = "claude_cli"
CODEX_CLI = "codex_cli"
_LLM_API_ENV_KEYS = frozenset({
    "CLAUDE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "XAI_API_KEY",
})
_SAFE_ERROR_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,63}$", re.ASCII)
_SENSITIVE_ERROR_TOKEN = re.compile(
    r"bearer|secret|token|password|credential|authorization|api_?key|^sk_", re.IGNORECASE)
_BEARER_VALUE = re.compile(r"\bbearer\s+[^\s,;]+", re.IGNORECASE)
_ASSIGNED_SECRET = re.compile(
    r"\b([a-z][a-z0-9_]*(?:api_key|token|secret|password|authorization|auth)[a-z0-9_]*)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_SK_TOKEN = re.compile(r"\bsk-[a-z0-9_-]+", re.IGNORECASE)


def scrub_llm_api_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a child environment without direct LLM API credentials."""
    values = os.environ if source is None else source
    return {key: value for key, value in values.items()
            if key not in _LLM_API_ENV_KEYS}


def _strict_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adapt Pydantic JSON Schema objects to Codex strict-output rules."""
    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                properties = node.get("properties")
                if not isinstance(properties, dict):
                    raise ValueError(
                        "Codex structured output does not support free-form objects")
                node["additionalProperties"] = False
                node["required"] = list(properties)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(schema)
    return schema


def _build_claude_argv(model: str, schema_json: str | None, effort: str | None,
                       tools: list[str] | None = None) -> list[str]:
    # tools 지정 시 해당 도구만 허용 + 자동 승인(--allowedTools — headless 권한 게이트 실측
    # 2026-07-23: --tools만 주면 "권한 승인 필요"로 도구 실행이 안 됨)
    tool_arg = ",".join(tools) if tools else ""
    argv = ["claude", "-p", "--model", model, "--output-format", "json",
            "--tools", tool_arg, "--no-session-persistence"]
    if tools:
        argv += ["--allowedTools", tool_arg]
    if schema_json:
        argv += ["--json-schema", schema_json]     # 인라인 JSON(파일 경로 아님 — 실측)
    if effort:
        argv += ["--effort", effort]
    return argv


def _build_codex_argv(model: str, schema_path: str | None, effort: str | None,
                      cwd: str) -> list[str]:
    argv = [
        "codex", "exec",
        "--ephemeral",
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "-C", cwd,
    ]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["-c", f'model_reasoning_effort="{effort}"']
    if schema_path:
        argv += ["--output-schema", schema_path]
    return [*argv, "-"]


async def _run_cli(argv: list[str], stdin_text: str, timeout: float, *,
                   cwd: str | None = None,
                   env: Mapping[str, str] | None = None) -> tuple[int, str, str]:
    owned_scratch = tempfile.mkdtemp(prefix="cli_role_") if cwd is None else None
    scratch = cwd or owned_scratch
    proc = None

    async def _read_limited(stream: asyncio.StreamReader, name: str) -> bytes:
        captured = bytearray()
        while True:
            chunk = await stream.read(64 * 1024)
            if not chunk:
                return bytes(captured)
            if len(captured) + len(chunk) > _MAX_OUT:
                raise RuntimeError(f"cli {name} exceeds {_MAX_OUT} bytes")
            captured.extend(chunk)

    async def _feed_stdin(stream: asyncio.StreamWriter) -> None:
        try:
            stream.write(stdin_text.encode())
            await stream.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            stream.close()
            try:
                await stream.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

    async def _spawn_and_talk():
        # 스폰까지 데드라인 안 — 바깥 wait_for가 스폰 행도 문다(07-28 06:30 회차:
        # axis_split이 로그 한 줄 없이 스테이지 예산 1200s를 통째 소진한 실측.
        # 기존 코드는 create_subprocess_exec가 wait_for 밖이라 무한 대기 구멍)
        nonlocal proc
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=scratch,
            env=dict(env) if env is not None else None,
            start_new_session=True)                # 프로세스그룹 → 킬 시 그룹 전체
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        tasks = [
            asyncio.create_task(_read_limited(proc.stdout, "stdout")),
            asyncio.create_task(_read_limited(proc.stderr, "stderr")),
            asyncio.create_task(_feed_stdin(proc.stdin)),
        ]
        try:
            out, err, _ = await asyncio.gather(*tasks)
            await proc.wait()
            return out, err
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _reap():
        if proc is None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            # 회수도 상한 — SIGKILL 후 wait()가 안 돌아오는 경우(워처 경합·D 상태)
            # 좀비는 OS에 맡기고 전진한다. 무한 대기가 침묵 행의 본체였다.
            await asyncio.wait_for(proc.wait(), _REAP_TIMEOUT_S)
        except asyncio.TimeoutError:
            pass

    try:
        out, err = await asyncio.wait_for(_spawn_and_talk(), timeout)
    except asyncio.CancelledError:
        # 취소는 반드시 그대로 전파 — RuntimeError로 바꾸면 Role 폴백이 이어받아
        # 바깥 스테이지 wait_for가 무력화됨(codex P4 B2: never-hang 붕괴)
        await _reap()
        raise
    except asyncio.TimeoutError:
        await _reap()                              # 좀비 방지(SF4)
        raise RuntimeError(f"cli timeout after {timeout}s")
    except Exception:
        await _reap()
        raise
    finally:
        if owned_scratch:
            import shutil as _sh
            _sh.rmtree(owned_scratch, ignore_errors=True)
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


def _envelope(stdout: str) -> dict:
    obj = json.loads(stdout)
    if not isinstance(obj, dict):
        raise RuntimeError("cli output is not a json object")
    if obj.get("is_error"):
        raise RuntimeError(f"cli reported error: {str(obj.get('result'))[:400]}")
    return obj


def _sanitize_stderr(stderr: str) -> str:
    """Redact common credential forms before a CLI failure reaches logs."""
    clean = _BEARER_VALUE.sub("Bearer [REDACTED]", stderr)
    clean = _ASSIGNED_SECRET.sub(r"\1=[REDACTED]", clean)
    return _SK_TOKEN.sub("[REDACTED]", clean)


def _failure_diagnostic(stdout: str, stderr: str) -> str:
    """Return bounded safe metadata or sanitized stderr, never a result envelope."""
    try:
        envelope = json.loads(stdout)
    except (json.JSONDecodeError, RecursionError):
        envelope = None
    if isinstance(envelope, dict):
        status = envelope.get("api_error_status")
        if (isinstance(status, int) and not isinstance(status, bool)
                and 100 <= status <= 599):
            return f"api_error_status={status}"
        if isinstance(status, str) and re.fullmatch(r"[1-5][0-9]{2}", status):
            return f"api_error_status={status}"
        for key in ("error_status", "error_type", "error_code", "type", "code"):
            value = envelope.get(key)
            if (isinstance(value, str)
                    and _SAFE_ERROR_TOKEN.fullmatch(value)
                    and not _SENSITIVE_ERROR_TOKEN.search(value)):
                return f"{key}={value}"
    return _sanitize_stderr(stderr)[:400]


def _extract_structured(stdout: str) -> Any:
    obj = _envelope(stdout)
    if obj.get("structured_output") is not None:   # canonical(실측)
        return obj["structured_output"]
    if "result" in obj:
        return json.loads(obj["result"])
    raise RuntimeError("cli output has neither structured_output nor result")


def _extract_text(stdout: str) -> str:
    obj = _envelope(stdout)
    return str(obj.get("result", stdout))


async def claude_complete(model: str, instructions: str, prompt: str, *,
                          response_format: type[BaseModel] | None = None,
                          effort: str | None = None, runner=None,
                          tools: list[str] | None = None,
                          timeout: float | None = None) -> Any:
    import hashlib
    import logging
    import shutil
    import time as _time
    runner = runner or _run_cli
    scratch = tempfile.mkdtemp(prefix="claude_role_")
    schema_json = (json.dumps(response_format.model_json_schema())
                   if response_format is not None else None)
    argv = _build_claude_argv(model, schema_json, effort, tools)
    stdin_text = f"{instructions}\n\n{prompt}" if instructions else prompt
    child_env = scrub_llm_api_env()
    log = logging.getLogger("cli_role")
    phash = hashlib.sha256(stdin_text.encode()).hexdigest()[:12]
    t0 = _time.monotonic()

    def _runlog(ok: bool, note: str = ""):
        # CostMeter 부재 대체 계측(스펙 v3) — elapsed·모델·프롬프트 해시·성패
        log.info("cli_run executor=claude model=%s prompt=%s elapsed_ms=%d ok=%s %s",
                 model, phash, int((_time.monotonic() - t0) * 1000), ok, note)

    # timeout은 재시도를 포함한 총 데드라인 — 시도마다 새로 주면 호출부의 스테이지
    # 예산(예: axis_split 1200s)을 CLI 다리 혼자 소진한다(07-27 저녁 회차 실측)
    total = timeout or _TIMEOUT
    # 시작 로그 — 완료 로그만으로는 행 지점(CLI 도달 여부·스폰·API 폴백)을 못
    # 가른다(07-28 회차: axis_split 무로그 1200s가 원인 규명을 막은 실측)
    log.info("cli_start executor=claude model=%s prompt=%s timeout=%ds",
             model, phash, int(total))
    last: Exception | None = None
    try:
        for _ in range(2):                         # 파싱 실패 1회 재시도
            remaining = total - (_time.monotonic() - t0)
            if remaining <= 5:
                last = last or RuntimeError(f"cli deadline {total}s 소진")
                break
            try:
                rc, out, err = await runner(
                    argv, stdin_text, remaining, cwd=scratch, env=child_env)
            except Exception:
                _runlog(False, "spawn/timeout")
                raise
            if rc != 0:
                _runlog(False, f"exit={rc}")
                diagnostic = _failure_diagnostic(out, err)
                suffix = f": {diagnostic}" if diagnostic else ""
                raise RuntimeError(f"cli exit {rc}{suffix}")
            try:
                if response_format is None:
                    val = _extract_text(out)
                else:
                    val = response_format.model_validate(_extract_structured(out))
                _runlog(True)
                return val
            except Exception as exc:  # noqa: BLE001
                last = exc
                stdin_text += "\n\n직전 출력이 유효 JSON이 아니었다. 스키마에 맞는 JSON만 출력하라."
        _runlog(False, f"parse: {last}")
        raise RuntimeError(f"cli structured parse failed: {last}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


async def codex_complete(model: str, instructions: str, prompt: str, *,
                         response_format: type[BaseModel] | None = None,
                         effort: str | None = None, runner=None,
                         timeout: float | None = None) -> Any:
    """Run Codex non-interactively with saved CLI auth and schema validation."""
    import hashlib
    import logging
    import shutil
    import time as _time

    runner = runner or _run_cli
    scratch = tempfile.mkdtemp(prefix="codex_role_")
    schema_path: str | None = None
    if response_format is not None:
        schema_file = Path(scratch, "schema.json")
        schema_file.write_text(
            json.dumps(_strict_output_schema(response_format.model_json_schema())),
            encoding="utf-8")
        schema_path = str(schema_file)
    argv = _build_codex_argv(model, schema_path, effort, scratch)
    stdin_text = f"{instructions}\n\n{prompt}" if instructions else prompt
    child_env = scrub_llm_api_env()
    log = logging.getLogger("cli_role")
    phash = hashlib.sha256(stdin_text.encode()).hexdigest()[:12]
    t0 = _time.monotonic()
    total = timeout or _TIMEOUT
    last: Exception | None = None
    log.info("cli_start executor=codex model=%s prompt=%s timeout=%ds",
             model, phash, int(total))
    try:
        for _ in range(2):
            remaining = total - (_time.monotonic() - t0)
            if remaining <= 5:
                last = last or RuntimeError(f"cli deadline {total}s 소진")
                break
            rc, out, err = await runner(
                argv, stdin_text, remaining, cwd=scratch, env=child_env)
            if rc != 0:
                raise RuntimeError(f"codex cli exit {rc}: {err[:400]}")
            try:
                value = (out.strip() if response_format is None
                         else response_format.model_validate_json(out))
                log.info("cli_run executor=codex model=%s prompt=%s elapsed_ms=%d ok=True",
                         model, phash, int((_time.monotonic() - t0) * 1000))
                return value
            except Exception as exc:  # noqa: BLE001
                last = exc
                stdin_text += "\n\n직전 출력이 유효 JSON이 아니었다. 스키마에 맞는 JSON만 출력하라."
        log.info("cli_run executor=codex model=%s prompt=%s elapsed_ms=%d ok=False",
                 model, phash, int((_time.monotonic() - t0) * 1000))
        raise RuntimeError(f"codex cli structured parse failed: {last}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
