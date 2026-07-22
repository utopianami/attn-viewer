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


def _build_claude_argv(model: str, schema_json: str | None, effort: str | None) -> list[str]:
    argv = ["claude", "-p", "--model", model, "--output-format", "json",
            "--tools", "", "--no-session-persistence"]
    if schema_json:
        argv += ["--json-schema", schema_json]     # 인라인 JSON(파일 경로 아님 — 실측)
    if effort:
        argv += ["--effort", effort]
    return argv


async def _run_cli(argv: list[str], stdin_text: str, timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=tempfile.gettempdir(),                 # 고정 스크래치 cwd — 레포 접근 무의미화
        start_new_session=True)                    # 프로세스그룹 → 타임아웃 시 그룹 킬
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode()), timeout)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise RuntimeError(f"cli timeout after {timeout}s")
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
                       effort: str | None = None, runner=None) -> Any:
    runner = runner or _run_cli
    schema_json = (json.dumps(response_format.model_json_schema())
                   if response_format is not None else None)
    argv = _build_claude_argv(model, schema_json, effort)
    stdin_text = f"{instructions}\n\n{prompt}" if instructions else prompt

    last: Exception | None = None
    for _ in range(2):                             # 파싱 실패 1회 재시도
        rc, out, err = await runner(argv, stdin_text, _TIMEOUT)
        if rc != 0:
            raise RuntimeError(f"cli exit {rc}: {err[:400]}")
        try:
            if response_format is None:
                return _extract_text(out)
            return response_format.model_validate(_extract_structured(out))
        except Exception as exc:  # noqa: BLE001
            last = exc
            stdin_text += "\n\n직전 출력이 유효 JSON이 아니었다. 스키마에 맞는 JSON만 출력하라."
    raise RuntimeError(f"cli structured parse failed: {last}")
