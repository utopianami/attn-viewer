"""claude CLI 구조화 출력 실행기 — --tools ""(실측 유일 툴오프)·인라인 --json-schema·
세션 미영속·스크래치 cwd·프로세스그룹 타임아웃. 실패 raise → Role 폴백 체인이 이어받음.
실측(2026-07-22, codex 스모크): --json-schema는 인라인 JSON(파일 경로면 exit 1),
출력 envelope의 structured_output이 canonical, --allowedTools ""는 Read/Bash 못 막음."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
from typing import Any

from pydantic import BaseModel

_TIMEOUT = 600.0
_MAX_OUT = 2_000_000


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


async def _run_cli(argv: list[str], stdin_text: str, timeout: float) -> tuple[int, str, str]:
    scratch = tempfile.mkdtemp(prefix="cli_role_")  # 전용 스크래치 cwd(공유 /tmp 아님 — SF4)
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=scratch,
        start_new_session=True)                    # 프로세스그룹 → 킬 시 그룹 전체
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode()), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()                          # 좀비 방지(SF4)
        raise RuntimeError(f"cli timeout/cancel after {timeout}s")
    finally:
        import shutil as _sh
        _sh.rmtree(scratch, ignore_errors=True)
    return proc.returncode, out.decode(errors="replace")[:_MAX_OUT], err.decode(errors="replace")


def _envelope(stdout: str) -> dict:
    obj = json.loads(stdout)
    if not isinstance(obj, dict):
        raise RuntimeError("cli output is not a json object")
    if obj.get("is_error"):
        raise RuntimeError(f"cli reported error: {str(obj.get('result'))[:400]}")
    return obj


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


async def cli_complete(model: str, instructions: str, prompt: str, *,
                       response_format: type[BaseModel] | None = None,
                       effort: str | None = None, runner=None,
                       tools: list[str] | None = None,
                       timeout: float | None = None) -> Any:
    import hashlib
    import logging
    import time as _time
    runner = runner or _run_cli
    schema_json = (json.dumps(response_format.model_json_schema())
                   if response_format is not None else None)
    argv = _build_claude_argv(model, schema_json, effort, tools)
    stdin_text = f"{instructions}\n\n{prompt}" if instructions else prompt
    log = logging.getLogger("cli_role")
    phash = hashlib.sha256(stdin_text.encode()).hexdigest()[:12]
    t0 = _time.monotonic()

    def _runlog(ok: bool, note: str = ""):
        # CostMeter 부재 대체 계측(스펙 v3) — elapsed·모델·프롬프트 해시·성패
        log.info("cli_run model=%s prompt=%s elapsed_ms=%d ok=%s %s",
                 model, phash, int((_time.monotonic() - t0) * 1000), ok, note)

    last: Exception | None = None
    for _ in range(2):                             # 파싱 실패 1회 재시도
        try:
            rc, out, err = await runner(argv, stdin_text, timeout or _TIMEOUT)
        except Exception:
            _runlog(False, "spawn/timeout")
            raise
        if rc != 0:
            _runlog(False, f"exit={rc}")
            raise RuntimeError(f"cli exit {rc}: {err[:400]}")
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
