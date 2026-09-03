# Runtime and Data Hardening Design

## Goal

Keep the current HTTP and UI behavior while making scheduled work single-owner,
making runtime writes safe across processes, stopping wasteful blog refreshes,
and making the checked-in PM2 configuration repeatable.

## Constraints

- `openapi.yaml` remains the source of truth for every HTTP shape.
- Existing authenticated and public route behavior must not change.
- Documents and blog corpus files remain under their current user-scoped paths.
- Market-sector reports remain global public market data as currently designed.
- Scheduled collection, report generation, and monitoring must each run once per
  configured interval even if an API process is duplicated accidentally.
- Deployment must preserve the current `.env` and storage trees.
- Existing duplicate data and logs are cleaned only after a backup and only
  after the writers have been fixed and quiesced.

## Architecture

### 1. Separate API serving from scheduled work

The FastAPI lifespan will no longer start collection, report, and monitor
schedulers. A dedicated `python -m app.scheduler_worker` process owns all three
loops. The worker holds a non-blocking advisory singleton lock for its lifetime;
a second worker exits cleanly instead of running duplicate schedules.

Long sector collection runs execute in a child process with a hard timeout.
This isolates CLI and collector pipe failures from both the API event loop and
the scheduler coordinator. The report freshness guard uses the same bounded
collection subprocess rather than calling `collect_all` in-process.

The worker handles SIGTERM/SIGINT, cancels every scheduler task, awaits task
termination, and releases its singleton lock. The HTTP API still exposes the
same routes and still allows the existing explicit manual collection endpoint.

### 2. Serialize shared runtime writes

A small file-I/O module provides:

- `exclusive_file_lock(path, blocking=True)` using `fcntl.flock`;
- `atomic_write_text(path, text)` using a PID/UUID-specific temporary file,
  `fsync`, and `os.replace`.

`SectorStore` serializes each full read/check/write transaction for cards,
metrics, raw news, state, and status. Atomic replacement is used for state and
status. This ensures that accidental concurrent API or maintenance writers do
not create duplicate logical rows or overwrite one another.

Monitor health and alert state use the same primitives. Alert decision, JSONL
append, notification attempt, and state update are one locked transaction so a
duplicate monitor cannot send the same alert twice.

Existing read behavior remains unchanged. Readers continue to tolerate malformed
historical lines, although the deployment migration will leave none.

### 3. Make blog refresh eligibility explicit

Naver preview items retain their publication time as optional `publishedAt`.
The OpenAPI `BlogPreview` schema documents that field. A pure eligibility
function determines whether the newest remote post is both newer than local
state and eligible under `crawlSince`.

For an empty local corpus, a remote newest post older than `crawlSince` is not a
new eligible post. Its last-check record reports `hasNew: false` and no crawl
job is launched. Missing or unparsable publication time preserves the current
fallback behavior so genuinely new blogs are not silently skipped.

Codex summary output files are removed in a `finally` path after success,
non-zero exit, spawn error, or timeout. Crawler raw HTML is first written to a
staging file and is promoted only after parsing succeeds, preventing new raw
orphans while keeping current article and metadata formats.

### 4. Make monitoring represent real availability

The DART/EDGAR collector returns `error` when every configured source fails and
`degraded` when some sources fail. `ok` means all attempted source requests
succeeded, even if no new filings exist.

Collection status records a run identifier, start time, finish time, and final
collector result snapshot atomically. The existing per-collector keys and fields
stay available so current API consumers remain compatible.

The monitor can optionally probe the engine health URL. The scheduler worker
uses the configured local engine URL and records an alert on connection failure,
timeout, non-200 response, or invalid health payload. Tests pass an injected
probe so offline test runs never contact the live service.

### 5. Replace mutable PM2 commands with a versioned manifest

`ecosystem.config.cjs` defines exactly one instance each for:

- `attn-viewer`;
- `attn-engine`;
- `attn-scheduler`;
- `attn-vault-bridge`;
- `attn-ngrok` when explicitly enabled.

All processes use the repository as `cwd`, load the existing `.env` behavior,
apply restart delay/backoff and memory caps, and write to named PM2 logs. README
operations use `pm2 startOrReload ecosystem.config.cjs --update-env`, which is
idempotent by application name.

System startup has one owner: systemd. The user crontab PM2 resurrection entry
is removed during deployment. The systemd unit is regenerated/replaced with a
single PM2 startup unit and a restart delay. The active PM2 list is rebuilt from
the manifest and then saved once.

OS logrotate covers both PM2 application logs and the PM2 daemon log. Rotation
uses copy-truncate because PM2 processes keep their log descriptors open.

## Regression contract

The P23 off-arm snapshot is a same-codebase structural regression fixture, not
an eternal copy of a pre-P3 commit. It is recaptured after the unrelated sector
momentum and macro additions. Behavioral tests continue to require that the off
arm emits no thesis or chain layer. Future intentional non-P23 changes require
an explicit snapshot review rather than silently weakening equality.

## Deployment and data migration

Deployment occurs only after all offline tests pass:

1. Back up the current PM2 dump, crontab, systemd unit, monitor state, memory
   sector JSONL files, blog orphan inventory, and PM2 logs.
2. Stop the duplicated PM2 applications once.
3. Remove only exact duplicate JSONL rows, preserving the first full payload and
   making no semantic merges.
4. Move unreferenced blog raw HTML and leaked summary temporary files into a
   timestamped quarantine directory instead of irreversibly deleting them.
5. Install the systemd and logrotate configuration, remove the PM2 crontab line,
   and start the versioned ecosystem exactly once.
6. Save the clean PM2 process list.

Rollback restores the backed-up systemd unit, crontab, PM2 dump, and data files,
then resurrects the old dump. Quarantined files are recoverable by moving them
back to their original locations.

## Acceptance criteria

- `npm test` exits zero with no failing tests.
- `node --check server.mjs` and OpenAPI validation pass.
- OpenAPI route coverage still passes.
- PM2 contains one online viewer, engine, scheduler, and bridge; ngrok is either
  one online process or deliberately disabled with its account-limit cause
  documented.
- systemd is active and the PM2 `@reboot` crontab entry is absent.
- `/api/session` preserves its anonymous 401 response.
- `/healthz` returns 200 promptly.
- The market-report list and detail endpoints preserve their current payloads.
- No malformed JSON/JSONL, duplicate sector keys, monitor `.tmp` files, leaked
  `/tmp/blog-summary-*`, or unquarantined blog raw orphans remain.
- A controlled scheduler smoke run produces one collection/status update and
  one monitor health update without starting a report outside its configured
  schedule.
