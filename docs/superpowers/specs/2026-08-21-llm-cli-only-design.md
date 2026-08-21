# LLM API to CLI-Only Execution Design

**Date:** 2026-08-21  
**Status:** Approved in chat; awaiting written-spec review

## Context

The project currently mixes two execution modes:

- direct Anthropic and OpenAI SDK calls authenticated with project `.env` keys;
- authenticated `claude` and `codex` CLI subprocesses.

Grok/xAI inference was removed from the active engine on 2026-07-06, but
`XAI_API_KEY` remains in the local `.env`, and stale `grok` values remain in the
browser and root OpenAPI contract. Historical chat records may still contain
Grok model and cost metadata.

The requested outcome is to stop direct LLM API-key billing while preserving
the existing Claude-versus-OpenAI role split. External market-data and service
APIs are explicitly out of scope and must continue to work.

## Goals

1. Run every active Claude role through the authenticated `claude` CLI.
2. Run every active OpenAI role through the authenticated `codex` CLI.
3. Remove all direct Anthropic, OpenAI, and xAI client paths and their project
   environment variables.
4. Preserve role ownership, cross-model review, structured Pydantic responses,
   stage timeouts, and explicit fallback order where practical.
5. Make the runtime fail clearly when a required CLI binary or CLI login is
   unavailable. It must never fall back to an API client.
6. Keep the root OpenAPI contract aligned with the implemented provider surface.

## Non-goals

- Do not remove or convert data APIs, including OpenRouter datasets,
  data.go.kr, KOSIS, ECOS, DART, Naver, Toss, Yahoo/WTS, RSS, or status pages.
- Do not remove `OPENROUTER_API_KEY`. It fetches model-market data and does not
  invoke Grok inference.
- Do not change document auth, user storage, public sharing, or market-data
  collection behavior.
- Do not migrate or rewrite historical stored chat/report records.
- Do not promise that CLI usage has no quota or subscription impact. The goal
  is no direct project API-key invocation or per-call API billing.

## Approaches Considered

### A. Preserve provider roles with two CLI adapters — selected

Map Anthropic-owned roles to Claude CLI and OpenAI-owned roles to Codex CLI.
Cross-provider fallback chains become cross-CLI chains. This preserves the
current diversity and independent-review intent while removing API clients.

### B. Route every role through Claude CLI

This is simpler, but removes the independent OpenAI judge/producer perspective
and weakens cross-validation.

### C. Route every role through Codex CLI

This also simplifies execution, but removes the Claude planner/verifier split
and changes the established report pipeline more than necessary.

## Architecture

### Logical providers and executors

The browser and stored chat contract retain the logical provider identifiers
`anthropic` and `openai` for backward compatibility. Their implementation
becomes CLI-only:

| Logical provider | Executor | Authentication |
| --- | --- | --- |
| `anthropic` | `claude -p` | existing Claude CLI account session |
| `openai` | `codex exec` | existing Codex/ChatGPT CLI account session |

Internally, role chains use explicit executor names such as `claude_cli` and
`codex_cli`; a generic `cli` value is not sufficient because capability checks,
arguments, schemas, and output formats differ between the two programs.

The current role map remains semantically stable:

- every `anthropic` leg becomes `claude_cli`;
- every `openai` leg becomes `codex_cli`;
- report roles already using the generic Claude CLI become `claude_cli`;
- a role that previously had Anthropic-to-OpenAI fallback keeps the same order
  as Claude-CLI-to-Codex-CLI fallback;
- redundant same-model API fallbacks after an existing Claude CLI leg are
  removed;
- roles intentionally restricted to one provider remain restricted to the
  corresponding one CLI.

Profile and request-specific overrides in `engine/routing.py` and
`engine/app/main.py` follow the same mapping.

### CLI adapter boundary

`engine/cli_role.py` becomes the single Python execution boundary with two
provider-specific adapters behind one stable completion interface.

Both adapters must provide:

- text and Pydantic structured output;
- per-role model and reasoning/effort selection;
- ephemeral sessions;
- a dedicated temporary working directory;
- process-group cancellation and a hard total timeout;
- bounded stdout/stderr capture;
- one structured-output parse retry within the original timeout;
- provider/model/elapsed/success logging without prompt contents or secrets.

Claude CLI keeps its validated `--json-schema` envelope flow and explicit tool
allowlist. Normal roles use no tools. The report research stage remains the only
path allowed to enable Claude `WebSearch` and `WebFetch`.

Codex CLI uses non-interactive `codex exec`, `--ephemeral`, a read-only sandbox,
an empty temporary working directory, and `--output-schema` for structured
responses. The adapter passes the full instructions and prompt through stdin.
It ignores project execution rules and user runtime customizations that could
add unrelated tools, while continuing to use the saved CLI login. This follows
the [official Codex non-interactive contract](https://developers.openai.com/codex/noninteractive):
final output goes to stdout, structured output accepts a schema file, and saved
CLI authentication is reused.

### Environment and authentication isolation

Remove these exact entries from the project-local `.env`:

- `CLAUDE_API_KEY`
- `OPENAI_API_KEY`
- `XAI_API_KEY`

Remove `claude_api_key` and `openai_api_key` from Python settings. There is no
active xAI setting or client to retain. Do not add `ANTHROPIC_API_KEY`,
`CODEX_API_KEY`, or another replacement secret.

Deleting `.env` entries alone is insufficient because PM2 or a parent shell can
retain old variables. Every Python and Node CLI subprocess therefore receives a
copy of the parent environment with provider API-key variables removed:

- Claude child: `CLAUDE_API_KEY`, `ANTHROPIC_API_KEY`;
- Codex child: `OPENAI_API_KEY`, `CODEX_API_KEY`;
- all LLM children: `XAI_API_KEY`.

This sanitization is local to the child process. It must not remove data API
keys or mutate the parent process environment.

### Capability and health reporting

LLM capability is determined by executable availability, not key presence.
Health output reports the two concrete capabilities, `claude_cli` and
`codex_cli`. Missing login is detected by a real invocation failure and appears
in the existing stage/degraded error path; no API fallback is attempted.

### API contract and browser compatibility

The root `openapi.yaml` is updated in the same change as the runtime:

- narrow all chat provider enums from `anthropic | openai | grok` to
  `anthropic | openai`;
- retain the existing request and response shapes so stored chats and the
  browser do not require migration.

The browser removes claims that three providers are active and removes Grok
from current provider labels/selections. Historical answer metadata remains
readable: old Grok model or cost fields may still be rendered, but they cannot
be selected or emitted by new requests.

### Cost and observability

The API pricing table and token-based API billing calculation are removed from
the active executor path. New runs record CLI executor/model/run counts and
elapsed time instead of estimating a dollar charge from API token prices.
Historical cost objects remain valid and render unchanged.

The UI must not label new CLI subscription usage as a literal `$0` service cost.
It should identify the execution as Claude CLI/Codex CLI and, where shown, say
that no project API charge was measured.

### Error handling

- Missing binary: the role is unavailable before execution.
- Missing/expired CLI login: the subprocess error is surfaced and the next
  configured CLI leg may run.
- Timeout or cancellation: kill the whole subprocess group, reap it with a
  bounded timeout, then continue only to another configured CLI leg.
- Invalid structured output: retry once within the original deadline, then
  fail the leg.
- Exhausted chain: preserve the existing `all providers failed` failure shape
  so stage degradation and report retry logic continue to work.
- At no point may an error instantiate an Anthropic, OpenAI, or xAI API client.

## Cleanup

- Remove Anthropic/OpenAI API client factories, schema patches, pricing tables,
  and key-based capability checks from `engine/providers.py`.
- Remove Agent Framework provider dependencies that have no remaining runtime
  consumer.
- Replace or remove live PoC tests whose only purpose is calling the direct APIs.
- Update comments and operational docs that describe API fallback or API keys.
  Historical dated design documents remain historical records and are not
  rewritten.

## Testing

Implementation follows TDD. Tests cover:

1. Claude and Codex argument construction, including read-only/ephemeral mode,
   schema handling, effort mapping, and permitted tools.
2. Child environment scrubbing without deleting any data-service variables.
3. Text and structured output parsing for both CLIs.
4. Timeout, cancellation, process-group cleanup, parse retry, and output bounds.
5. Role mapping and same-order cross-CLI fallback with no API client path.
6. Binary-based health capabilities.
7. Node Codex subprocesses receiving the sanitized environment.
8. OpenAPI and browser provider values excluding new Grok usage while retaining
   historical record rendering.
9. Existing orchestrator, sector, report, contract, and Node regression suites.

Before completion, run at minimum:

```bash
node --check server.mjs
npm test
engine/.venv/bin/python -m pytest engine/tests
```

Also run one minimal text/structured smoke through each installed CLI, then
verify no active code references `CLAUDE_API_KEY`, `OPENAI_API_KEY`,
`XAI_API_KEY`, `AnthropicClient`, or `OpenAIChatClient`. The key-name scan may
retain only deliberate negative assertions/tests and this design document.

## Acceptance Criteria

- A normal QA run, sector update, and report pipeline can only reach Claude or
  Codex through subprocesses.
- Direct Anthropic/OpenAI/xAI SDK calls are absent from production code.
- The three project-local LLM key entries are absent from `.env`.
- Parent-process LLM API keys cannot leak into spawned Claude/Codex executions.
- All data APIs and their credentials remain untouched.
- Current OpenAPI chat provider enums match the runtime (`anthropic`, `openai`).
- Existing stored records load without migration.
- Automated tests and the required server syntax check pass.

## Rollback

Rollback restores the previous code and settings, but API keys are not restored
automatically. Re-enabling direct API execution would require an explicit new
decision and fresh credential provisioning.
