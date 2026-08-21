# LLM CLI-Only Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every direct Claude/OpenAI LLM API call with authenticated Claude/Codex CLI execution, remove the three LLM API keys, and remove current Grok contract/UI exposure without touching data APIs.

**Architecture:** Keep logical `anthropic` and `openai` identities for stored-chat compatibility, but map them to explicit `claude_cli` and `codex_cli` executors. A shared Python subprocess boundary handles schemas, timeouts, process groups, logging, and API-key scrubbing; a small Node helper scrubs the same keys from all existing Codex subprocesses. No error path may instantiate an API client.

**Tech Stack:** Python 3.12, asyncio, Pydantic 2, FastAPI, Node.js ESM, Express, OpenAPI 3.1, pytest, node:test

**Spec:** `docs/superpowers/specs/2026-08-21-llm-cli-only-design.md`

## Global Constraints

- Preserve all market-data and service APIs and their credentials, including `OPENROUTER_API_KEY`.
- Remove only `CLAUDE_API_KEY`, `OPENAI_API_KEY`, and `XAI_API_KEY` from the project-local `.env`; do not add replacement API keys.
- Claude-owned roles use Claude CLI; OpenAI-owned roles use Codex CLI.
- Preserve existing role ordering and cross-model review intent; never fall back from a CLI to an API client.
- Keep historical stored chat records readable without migration.
- Update `openapi.yaml` in the same implementation change as provider contract behavior.
- New CLI usage must not be presented as a literal zero-dollar service cost; describe it as CLI subscription execution.
- Backend completion requires `node --check server.mjs` plus the relevant Node, OpenAPI, and Python suites.

## File Map

- `engine/cli_role.py`: provider-specific Claude/Codex CLI adapters and shared subprocess lifecycle.
- `engine/providers.py`: role-to-CLI routing, fallback order, and CLI usage metering; no SDK clients.
- `engine/app/settings.py`: models and binary-based CLI capabilities; no LLM API keys.
- `engine/routing.py`, `engine/app/main.py`: CLI executor names in profile/request overrides.
- `engine/sector/report_article.py`: explicit Claude CLI research call with web-tool allowlist.
- `engine/tests/test_cli_role.py`, `engine/tests/test_search_quality.py`, `engine/tests/test_routing.py`, `engine/tests/test_contracts.py`: Python TDD coverage.
- `lib/llm-cli-env.mjs`: Node child-environment API-key scrubber.
- `lib/llm-cli-env.test.mjs`: Node scrubber tests.
- `server.mjs`, `lib/summaries.mjs`: pass sanitized environments to existing Codex processes.
- `public/index.html`, `openapi.yaml`: current provider surface and CLI usage display.
- `test/contract/llm-provider-contract.test.mjs`: OpenAPI/browser Grok and historical compatibility assertions.
- `engine/requirements.txt`, `engine/poc/test_providers.py`, `engine/poc/test_workflow.py`, `CLAUDE.md`: remove obsolete API/Agent Framework paths and guidance.
- `.env`: local-only removal of the three LLM keys.

---

### Task 1: Add Claude and Codex CLI adapters

**Files:**
- Modify: `engine/tests/test_cli_role.py`
- Modify: `engine/cli_role.py`

**Interfaces:**
- Produces: `CLAUDE_CLI = "claude_cli"`, `CODEX_CLI = "codex_cli"`.
- Produces: `scrub_llm_api_env(source: Mapping[str, str]) -> dict[str, str]`.
- Produces: `claude_complete(model, instructions, prompt, *, response_format=None, effort=None, runner=None, tools=None, timeout=None)`.
- Produces: `codex_complete(model, instructions, prompt, *, response_format=None, effort=None, runner=None, timeout=None)`.
- Consumes later: `engine/providers.py` dispatches to the two completion functions.

- [ ] **Step 1: Write failing adapter and environment tests**

Add tests equivalent to:

```python
from cli_role import (
    CLAUDE_CLI,
    CODEX_CLI,
    _build_codex_argv,
    codex_complete,
    scrub_llm_api_env,
)

def test_scrub_llm_api_env_preserves_data_keys():
    env = {
        "CLAUDE_API_KEY": "c",
        "ANTHROPIC_API_KEY": "a",
        "OPENAI_API_KEY": "o",
        "CODEX_API_KEY": "cx",
        "XAI_API_KEY": "x",
        "OPENROUTER_API_KEY": "keep",
        "KOSIS_API_KEY": "keep-too",
    }
    child = scrub_llm_api_env(env)
    assert not ({"CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                 "CODEX_API_KEY", "XAI_API_KEY"} & child.keys())
    assert child["OPENROUTER_API_KEY"] == "keep"
    assert child["KOSIS_API_KEY"] == "keep-too"
    assert env["OPENAI_API_KEY"] == "o"

def test_codex_argv_is_ephemeral_read_only_and_schema_bound(tmp_path):
    schema = tmp_path / "schema.json"
    argv = _build_codex_argv("gpt-5.5", str(schema), "high", str(tmp_path))
    assert argv[:2] == ["codex", "exec"]
    assert "--ephemeral" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--output-schema") + 1] == str(schema)
    assert argv[argv.index("-C") + 1] == str(tmp_path)
    assert argv[-1] == "-"

def test_codex_structured_output_is_validated():
    seen = {}
    async def runner(argv, stdin_text, timeout, *, cwd, env):
        seen.update(argv=argv, stdin=stdin_text, env=env)
        return 0, '{"answer":"ok"}', ""
    out = asyncio.run(codex_complete(
        "gpt-5.5", "instr", "prompt", response_format=_Out, runner=runner,
        timeout=10,
    ))
    assert out == _Out(answer="ok")
    assert "instr\n\nprompt" == seen["stdin"]
    assert "OPENAI_API_KEY" not in seen["env"]
```

Update existing Claude tests to call `claude_complete`, and update fake runner
signatures to accept keyword-only `cwd` and `env`. Keep existing deadline,
process-group reap, parse retry, text, envelope, and tool allowlist coverage.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
cd engine && .venv/bin/python -m pytest -c pytest.ini tests/test_cli_role.py -q
```

Expected: FAIL because Codex adapter symbols and environment scrubbing do not exist.

- [ ] **Step 3: Implement the two adapters and shared runner**

Refactor `engine/cli_role.py` so completion owns one temporary directory for the
entire retry budget. The minimal structure is:

```python
CLAUDE_CLI = "claude_cli"
CODEX_CLI = "codex_cli"
_LLM_KEY_NAMES = frozenset({
    "CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "CODEX_API_KEY", "XAI_API_KEY",
})

def scrub_llm_api_env(source=None):
    source = os.environ if source is None else source
    return {key: value for key, value in source.items() if key not in _LLM_KEY_NAMES}

def _build_codex_argv(model, schema_path, effort, cwd):
    argv = [
        "codex", "exec", "--ephemeral", "--sandbox", "read-only",
        "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
        "-C", cwd,
    ]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["-c", f'model_reasoning_effort="{effort}"']
    if schema_path:
        argv += ["--output-schema", schema_path]
    return [*argv, "-"]
```

Use `asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE,
stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
env=env, start_new_session=True)`. Keep `_MAX_OUT`, total-deadline retries,
`CancelledError` propagation, group kill, and bounded reap. Claude parses its
JSON envelope; Codex parses stdout directly and validates with
`response_format.model_validate_json`. Both functions log executor, model,
prompt hash, elapsed time, and success only.

- [ ] **Step 4: Run the focused tests and confirm pass**

Run:

```bash
cd engine && .venv/bin/python -m pytest -c pytest.ini tests/test_cli_role.py -q
```

Expected: all CLI adapter tests PASS.

- [ ] **Step 5: Commit the adapter boundary**

```bash
git add engine/cli_role.py engine/tests/test_cli_role.py
git commit -m "feat(engine): add Claude and Codex CLI adapters"
```

---

### Task 2: Replace engine provider clients with CLI routing

**Files:**
- Modify: `engine/tests/test_cli_role.py`
- Modify: `engine/tests/test_search_quality.py`
- Modify: `engine/tests/test_routing.py`
- Modify: `engine/tests/test_contracts.py`
- Modify: `engine/providers.py`
- Modify: `engine/app/settings.py`
- Modify: `engine/routing.py`
- Modify: `engine/app/main.py`
- Modify: `engine/sector/report_article.py`

**Interfaces:**
- Consumes: `claude_complete`, `codex_complete`, `CLAUDE_CLI`, `CODEX_CLI` from Task 1.
- Produces: `ROLE_MAP` containing CLI executor names only.
- Produces: `CostMeter.record_cli(executor: str, model: str) -> None` and a
  summary containing `billing_mode="cli_subscription"` and `cli_runs`.
- Produces: `Settings.capabilities()` based on `shutil.which`.

- [ ] **Step 1: Write failing CLI-only routing tests**

Replace API fallback assertions with:

```python
def test_role_map_contains_only_cli_executors():
    legs = [provider for chain in ROLE_MAP.values() for provider, _, _ in chain]
    assert set(legs) <= {"claude_cli", "codex_cli"}
    assert "claude_cli" in legs and "codex_cli" in legs

def test_news_summary_preserves_cross_cli_order():
    chain = ROLE_MAP["news_summary"]
    assert chain[0] == ("claude_cli", "claude-sonnet-4-6", "low")
    assert chain[1][0] == "codex_cli"

def test_cli_meter_is_not_api_dollar_estimate():
    meter = CostMeter()
    meter.record_cli("claude_cli", "claude-sonnet-4-6")
    meter.record_cli("codex_cli", "gpt-5.5")
    summary = meter.summary()
    assert summary["billing_mode"] == "cli_subscription"
    assert summary["cli_runs"] == {"claude": 1, "codex": 1}
    assert summary["by_provider"] == {}

def test_role_falls_back_from_claude_cli_to_codex_cli(monkeypatch):
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
    monkeypatch.setattr(pv, "_capable", lambda executor: True)
    role = pv.Role("x", overrides={"x": [
        ("claude_cli", "claude-sonnet-4-6", "low"),
        ("codex_cli", "gpt-5.4-mini", "low"),
    ]})
    assert asyncio.run(role.run("question")) == "codex answer"
    assert calls == ["claude", "codex"]
```

In `test_routing.py`, expect user/profile overrides to use `codex_cli` and
`claude_cli`. In `test_contracts.py`, add a capability test that monkeypatches
`shutil.which` and proves capabilities depend on binaries rather than keys.

- [ ] **Step 2: Run routing tests and confirm failure**

Run:

```bash
cd engine && .venv/bin/python -m pytest -c pytest.ini \
  tests/test_cli_role.py tests/test_search_quality.py tests/test_routing.py tests/test_contracts.py -q
```

Expected: FAIL on API executor names, pricing assertions, and key-based capabilities.

- [ ] **Step 3: Implement CLI-only providers and settings**

In `engine/providers.py`:

- replace every `anthropic` leg with `claude_cli`;
- replace every `openai` leg with `codex_cli`;
- replace generic `cli` legs with `claude_cli` and remove their redundant
  Anthropic API fallback;
- delete `_PRICE_PER_M`, `_make_client`, `_patch_anthropic_nested_schema`, and
  all SDK response handling;
- dispatch each leg directly to the matching Task 1 adapter;
- record successful CLI runs before returning;
- preserve the fallback loop, logging, cancellation behavior, response type,
  and final `role={role_name} all providers failed` error shape.

`CostMeter.summary()` must return:

```python
{
    "by_provider": {},
    "total_usd": 0.0,
    "tokens": {},
    "billing_mode": "cli_subscription",
    "cli_runs": {"claude": claude_count, "codex": codex_count},
}
```

In `engine/app/settings.py`, remove the two LLM key fields and replace
capabilities with binary checks:

```python
def capabilities(self) -> dict[str, bool]:
    return {
        "claude_cli": shutil.which("claude") is not None,
        "codex_cli": shutil.which("codex") is not None,
    }
```

Update `engine/routing.py` and `engine/app/main.py` overrides to the explicit
CLI executor names. Update `engine/sector/report_article.py` to import
`claude_complete`, ensuring only research passes `WebSearch`/`WebFetch`.
Remove cache-pricing/API-specific comments in active stage files where touched;
`cache_prefix` remains a normal prompt prefix for both CLIs.

- [ ] **Step 4: Run routing tests and confirm pass**

Run the same four-file pytest command from Step 2.

Expected: PASS with no API client imports.

- [ ] **Step 5: Run broader engine regressions**

Run:

```bash
cd engine && .venv/bin/python -m pytest -c pytest.ini tests -m 'not live' -q
```

Expected: PASS; update only assertions that intentionally described API
provider names or prices, never unrelated financial behavior.

- [ ] **Step 6: Commit CLI-only engine routing**

```bash
git add engine/providers.py engine/app/settings.py engine/routing.py \
  engine/app/main.py engine/sector/report_article.py engine/tests
git commit -m "refactor(engine): route all LLM roles through CLIs"
```

---

### Task 3: Prevent API-key inheritance in Node Codex calls

**Files:**
- Create: `lib/llm-cli-env.mjs`
- Create: `lib/llm-cli-env.test.mjs`
- Modify: `server.mjs`
- Modify: `lib/summaries.mjs`

**Interfaces:**
- Produces: `createLlmCliEnv(source = process.env) -> Record<string, string>`.
- Consumes: every Node `spawn` that runs `codex` passes this object as `env`.

- [ ] **Step 1: Write the failing Node scrubber test**

Create `lib/llm-cli-env.test.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { createLlmCliEnv } from "./llm-cli-env.mjs";

test("createLlmCliEnv removes LLM keys and preserves data keys", () => {
  const source = {
    CLAUDE_API_KEY: "c", ANTHROPIC_API_KEY: "a",
    OPENAI_API_KEY: "o", CODEX_API_KEY: "cx", XAI_API_KEY: "x",
    OPENROUTER_API_KEY: "keep", KOSIS_API_KEY: "keep-too", PATH: "/bin",
  };
  const child = createLlmCliEnv(source);
  for (const key of ["CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "CODEX_API_KEY", "XAI_API_KEY"]) assert.equal(key in child, false);
  assert.equal(child.OPENROUTER_API_KEY, "keep");
  assert.equal(source.OPENAI_API_KEY, "o");
});
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `node --test lib/llm-cli-env.test.mjs`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement and wire the scrubber**

Create the helper:

```javascript
const LLM_API_KEYS = new Set([
  "CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
  "CODEX_API_KEY", "XAI_API_KEY",
]);

export function createLlmCliEnv(source = process.env) {
  return Object.fromEntries(Object.entries(source).filter(([key]) => !LLM_API_KEYS.has(key)));
}
```

Import it in `server.mjs` and `lib/summaries.mjs`. Replace `env: process.env`
in `spawnWithInput` and add `env: createLlmCliEnv()` to `runCodexSummary`.
Do not change non-LLM child processes.

- [ ] **Step 4: Run Node unit and syntax checks**

Run:

```bash
node --test lib/llm-cli-env.test.mjs lib/summaries.test.mjs
node --check server.mjs
node --check lib/llm-cli-env.mjs
node --check lib/summaries.mjs
```

Expected: PASS.

- [ ] **Step 5: Commit Node environment isolation**

```bash
git add lib/llm-cli-env.mjs lib/llm-cli-env.test.mjs lib/summaries.mjs server.mjs
git commit -m "fix(cli): scrub API keys from LLM subprocesses"
```

---

### Task 4: Align OpenAPI and browser provider behavior

**Files:**
- Create: `test/contract/llm-provider-contract.test.mjs`
- Modify: `openapi.yaml`
- Modify: `public/index.html`

**Interfaces:**
- Consumes: logical provider values remain `anthropic` and `openai`.
- Produces: all current provider enums exclude `grok`.
- Produces: new `answer_meta.cost.billing_mode="cli_subscription"` UI rendering.

- [ ] **Step 1: Write a failing contract/static UI test**

Create a test that loads `openapi.yaml` and `public/index.html` as text:

```javascript
test("current chat provider contract excludes Grok", async () => {
  const spec = await readFile(join(ROOT, "openapi.yaml"), "utf8");
  assert.doesNotMatch(spec, /enum: \[anthropic, openai, grok\]/);
  for (const name of ["ChatMessageRequest", "ChatSummary", "Chat", "ChatMessage"])
    assert.match(spec, new RegExp(`${name}[\\s\\S]*?enum: \\[anthropic, openai\\]`));
});

test("browser describes two CLI providers but retains historical cost reader", async () => {
  const html = await readFile(join(ROOT, "public/index.html"), "utf8");
  assert.doesNotMatch(html, /3사 교차검증/);
  assert.match(html, /Claude·Codex/);
  assert.match(html, /billing_mode/);
  assert.match(html, /grok:\s*"Grok"/); // old stored cost objects remain readable
});
```

- [ ] **Step 2: Run the contract test and confirm failure**

Run: `node --test test/contract/llm-provider-contract.test.mjs`

Expected: FAIL on the current Grok enums, three-provider copy, and missing CLI billing rendering.

- [ ] **Step 3: Update OpenAPI first, then browser behavior**

Change the four chat schema enums from `[anthropic, openai, grok]` to
`[anthropic, openai]`. Keep request fields, response fields, auth requirements,
and shapes unchanged.

In `public/index.html`:

- change the locked composer title from three-provider wording to Claude/Codex
  CLI wording;
- remove Grok from current provider label/model-selection paths;
- keep only the historical `answer_meta.cost.by_provider.grok` reader;
- when `cost.billing_mode === "cli_subscription"`, render CLI run counts and
  “프로젝트 API 과금 없음” without rendering `$0.000` as total service cost;
- leave old cost objects on the existing dollar-rendering branch.

- [ ] **Step 4: Validate contract and UI regressions**

Run:

```bash
engine/.venv/bin/python scripts/validate_openapi.py
node --test test/contract/llm-provider-contract.test.mjs test/e2e/chat-poll-rerender.test.mjs
node --check server.mjs
```

Expected: PASS.

- [ ] **Step 5: Commit contract and UI alignment**

```bash
git add openapi.yaml public/index.html test/contract/llm-provider-contract.test.mjs
git commit -m "fix(contract): remove active Grok provider surface"
```

---

### Task 5: Remove API dependencies, PoCs, and local keys

**Files:**
- Modify: `engine/requirements.txt`
- Delete: `engine/poc/test_providers.py`
- Delete: `engine/poc/test_workflow.py`
- Modify: `CLAUDE.md`
- Modify locally, not tracked: `.env`

**Interfaces:**
- Produces: engine runtime with no Agent Framework provider dependency.
- Produces: local environment with no Anthropic/OpenAI/xAI LLM key entries.

- [ ] **Step 1: Add a negative active-code scan to the verification checklist**

The required scan is:

```bash
rg -n -S 'AnthropicClient|OpenAIChatClient|CLAUDE_API_KEY|OPENAI_API_KEY|XAI_API_KEY' \
  engine server.mjs lib public openapi.yaml .env.example CLAUDE.md \
  --glob '!engine/tests/**' --glob '!engine/evals/**'
```

Expected before cleanup: matches in providers, settings, PoC, and guidance.

- [ ] **Step 2: Remove obsolete runtime and PoC dependencies**

Delete these lines from `engine/requirements.txt`:

```text
agent-framework-anthropic==1.0.0b260630
agent-framework-core==1.10.0
agent-framework-openai==1.10.0
```

Delete the two obsolete MAF/API PoC test files. Update `CLAUDE.md` so its pytest
warning no longer describes paid API PoCs; retain the instruction to use the
bounded non-live engine test command.

- [ ] **Step 3: Mechanically delete only the three local `.env` entries**

Run the explicit, value-blind rewrite:

```bash
sed -i -E '/^(CLAUDE_API_KEY|OPENAI_API_KEY|XAI_API_KEY)=/d' .env
```

Then verify names only, without printing values:

```bash
if awk -F= '/^(CLAUDE_API_KEY|OPENAI_API_KEY|XAI_API_KEY)=/{print $1}' .env | grep -q .; then
  echo 'LLM key names still present' >&2
  exit 1
fi
```

- [ ] **Step 4: Run dependency and source scans**

Run:

```bash
rg -n -S 'agent_framework|AnthropicClient|OpenAIChatClient' engine \
  --glob '!engine/evals/**' --glob '!engine/tests/**'
rg -n -S 'CLAUDE_API_KEY|OPENAI_API_KEY|XAI_API_KEY' \
  engine server.mjs lib public openapi.yaml .env.example CLAUDE.md \
  --glob '!engine/tests/**' --glob '!engine/evals/**'
```

Expected: no active production references. Deliberate scrubber constants,
negative tests, the approved spec/plan, and historical dated docs are allowed.
Confirm separately that data key names remain in `.env` without printing their values.

- [ ] **Step 5: Commit tracked cleanup**

```bash
git add engine/requirements.txt engine/poc CLAUDE.md
git commit -m "chore(engine): remove direct LLM API dependencies"
```

The ignored `.env` change is intentionally not committed.

---

### Task 6: Full verification and live CLI smoke

**Files:**
- Modify only if a verification failure exposes an in-scope defect.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: evidence that both authenticated CLIs work and no direct API path remains.

- [ ] **Step 1: Run all static, contract, Node, and engine tests**

Run:

```bash
node --check server.mjs
npm test
cd engine && .venv/bin/python -m pytest -c pytest.ini tests -m 'not live' -q
```

Expected: all commands exit 0. `npm test` already includes OpenAPI, Node, E2E,
and engine suites; the final explicit engine run preserves direct evidence.

- [ ] **Step 2: Verify installed CLI capabilities**

Run:

```bash
command -v claude
command -v codex
claude --version
codex --version
```

Expected: both binaries resolve and print versions.

- [ ] **Step 3: Run minimal adapter smokes with child key scrubbing**

From `engine/`, execute this exact smoke. It requests one structured response
per CLI; structured success also proves text transport and parsing. Do not print
environment values or auth files.

```bash
cd engine && env -u CLAUDE_API_KEY -u ANTHROPIC_API_KEY \
  -u OPENAI_API_KEY -u CODEX_API_KEY -u XAI_API_KEY \
  .venv/bin/python - <<'PY'
import asyncio
from pydantic import BaseModel
from cli_role import claude_complete, codex_complete

class Out(BaseModel):
    answer: str

async def main():
    prompt = "Reply with a JSON object whose answer field is exactly PONG."
    claude = await claude_complete(
        "claude-sonnet-4-6", "Return only the requested result.", prompt,
        response_format=Out, effort="low", timeout=180,
    )
    codex = await codex_complete(
        "gpt-5.4-mini", "Return only the requested result.", prompt,
        response_format=Out, effort="low", timeout=180,
    )
    assert claude.answer.strip() == "PONG"
    assert codex.answer.strip() == "PONG"
    print("Claude CLI and Codex CLI structured smokes passed")

asyncio.run(main())
PY
```

Expected: both text and structured calls succeed using saved CLI authentication.

- [ ] **Step 4: Inspect health and process state without deploying changes**

Run:

```bash
curl -i http://127.0.0.1:3000/api/session
pm2 list
```

Expected: the existing server responds and PM2 state is recorded. Do not restart
services unless the user separately asks to deploy/reload them; child environment
scrubbing makes stale PM2 API keys inert after the new code is next started.

- [ ] **Step 5: Review final diff and key scope**

Run:

```bash
git status --short
git diff HEAD~4 --check
git diff HEAD~4 --stat
awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}' .env | sort
```

Expected: only planned tracked files changed; the three LLM key names are absent,
and data API key names remain.

- [ ] **Step 6: Record verification result**

If no fixes were required, do not create an empty commit. If verification
exposes a scoped defect, return to the task that owns the affected interface,
add a failing regression test there, make the minimal fix, rerun that task's
focused suite and the full suite, then commit exactly those test and source
files with message `fix(cli): address CLI-only verification regression`.
