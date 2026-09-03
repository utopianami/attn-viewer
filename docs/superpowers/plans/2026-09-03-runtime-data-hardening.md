# Runtime and Data Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the current application contract while eliminating duplicate schedulers, process-unsafe writes, wasteful blog jobs, misleading monitoring, and non-idempotent PM2 startup.

**Architecture:** FastAPI serves requests only; one dedicated scheduler worker coordinates bounded collection/report/monitor processes. Advisory locks and atomic replacement protect shared storage, while a versioned PM2/systemd/logrotate configuration makes deployment repeatable.

**Tech Stack:** Node.js 22, Express, Python 3.12, FastAPI, asyncio, `fcntl`, PM2, systemd, OpenAPI YAML, Node test runner, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-runtime-data-hardening-design.md`

## Global Constraints

- Keep existing route authentication and response behavior unchanged except for the documented optional `BlogPreview.items[].publishedAt` field.
- Update `openapi.yaml` in the same change as the BlogPreview response addition.
- Keep all document and blog corpus runtime files in their current user-scoped locations.
- Do not erase operational data; back up changed JSONL and quarantine unreferenced files.
- Write tests first and observe the intended failure before production edits.
- Run `node --check server.mjs`, OpenAPI validation, Node tests, E2E at mobile and desktop widths, and offline Python tests before deployment.

---

### Task 1: Isolate Scheduled Work From FastAPI

**Files:**
- Create: `engine/app/scheduler_worker.py`
- Create: `engine/runtime_io.py`
- Create: `engine/sector/collect_pipeline.py`
- Modify: `engine/app/main.py:35-58`
- Modify: `engine/sector/scheduler.py:12-36`
- Modify: `engine/sector/report_scheduler.py:106-136`
- Test: `engine/tests/test_scheduler_worker.py`
- Test: `engine/tests/test_sector_api.py:66-116`
- Test: `engine/tests/test_report_scheduler.py:91-151`

**Interfaces:**
- Produces: `scheduler_worker.run() -> int`, `collect_pipeline.main() -> int`, `try_singleton_lock(path)`, and `sector.scheduler.run_collection_subprocess(timeout_s: float) -> int | None`.
- Consumes: existing scheduler `start(app)` functions and `settings.sector_storage_dir`.

- [ ] **Step 1: Write failing isolation and lifecycle tests**

```python
def test_fastapi_lifespan_does_not_start_schedulers(monkeypatch):
    # Patch each scheduler start to fail if called, enter app lifespan, and assert health works.

def test_second_scheduler_worker_cannot_acquire_singleton(tmp_path):
    # Hold the lock once and assert the second nonblocking acquisition returns false.

def test_collection_subprocess_timeout_terminates_and_reaps(monkeypatch):
    # Fake a never-ending child and assert terminate/kill/wait occur within the bound.
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd engine && .venv/bin/python -m pytest tests/test_scheduler_worker.py tests/test_sector_api.py tests/test_report_scheduler.py -q`

Expected: missing worker/collection APIs and FastAPI still invoking scheduler starts.

- [ ] **Step 3: Implement API-only lifespan and scheduler worker**

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield

async def _run_worker() -> int:
    with try_singleton_lock(lock_path) as acquired:
        if not acquired:
            return 0
        tasks = [task for task in await start_all(state) if task is not None]
        await stop_event.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        return 0
```

Implement collection as `python -m sector.collect_pipeline` with terminate, 30-second grace, kill, and reap behavior. Reuse it in the periodic scheduler and report freshness guard.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `cd engine && .venv/bin/python -m pytest tests/test_scheduler_worker.py tests/test_sector_api.py tests/test_report_scheduler.py -q`

- [ ] **Step 5: Commit**

```bash
git add engine/app/main.py engine/app/scheduler_worker.py engine/runtime_io.py engine/sector/collect_pipeline.py engine/sector/scheduler.py engine/sector/report_scheduler.py engine/tests/test_scheduler_worker.py engine/tests/test_sector_api.py engine/tests/test_report_scheduler.py
git commit -m "fix: isolate engine schedulers from the API"
```

### Task 2: Serialize Sector and Monitor Storage

**Files:**
- Modify: `engine/runtime_io.py`
- Modify: `engine/sector/store.py:27-252`
- Modify: `engine/monitor/runner.py:149-155`
- Modify: `engine/monitor/alert.py:83-118`
- Test: `engine/tests/test_runtime_io.py`
- Test: `engine/tests/test_sector_store.py`
- Test: `engine/tests/test_sector_raw_store.py`
- Test: `engine/tests/test_monitor_runner.py`
- Test: `engine/tests/test_monitor_alert.py`

**Interfaces:**
- Produces: `exclusive_file_lock(path, blocking=True)` and `atomic_write_text(path, text)`.
- Consumes: filesystem paths already owned by `SectorStore` and monitor functions.

- [ ] **Step 1: Write process-concurrency regression tests**

```python
def test_duplicate_metric_append_is_serialized_across_processes(tmp_path):
    # Start four forked processes together, append the same observations, assert one logical row.

def test_concurrent_alert_processing_writes_one_valid_state(tmp_path):
    # Start competing processes, assert state JSON parses and the first alert is recorded once.

def test_atomic_write_leaves_no_tmp_file(tmp_path):
    atomic_write_text(tmp_path / "state.json", '{"ok": true}')
    assert list(tmp_path.glob("*.tmp")) == []
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd engine && .venv/bin/python -m pytest tests/test_runtime_io.py tests/test_sector_store.py tests/test_sector_raw_store.py tests/test_monitor_runner.py tests/test_monitor_alert.py -q`

Expected: duplicated metric/raw rows or shared temp-file rename errors under contention.

- [ ] **Step 3: Implement file locks and atomic writes**

```python
@contextmanager
def exclusive_file_lock(path: Path, *, blocking: bool = True):
    with path.open("a+") as lock_file:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(lock_file.fileno(), flags)
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
```

Wrap every complete `SectorStore` read/check/write transaction and the monitor alert state transaction. Use unique temporary paths and `os.replace` for state, status, and health.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `cd engine && .venv/bin/python -m pytest tests/test_runtime_io.py tests/test_sector_store.py tests/test_sector_raw_store.py tests/test_monitor_runner.py tests/test_monitor_alert.py -q`

- [ ] **Step 5: Commit**

```bash
git add engine/runtime_io.py engine/sector/store.py engine/monitor/runner.py engine/monitor/alert.py engine/tests/test_runtime_io.py engine/tests/test_sector_store.py engine/tests/test_sector_raw_store.py engine/tests/test_monitor_runner.py engine/tests/test_monitor_alert.py
git commit -m "fix: serialize shared runtime storage"
```

### Task 3: Stop Empty Blog Refreshes and Temporary-File Leaks

**Files:**
- Modify: `lib/blogs.mjs:283-312`
- Modify: `lib/blogs-router.mjs:225-264`
- Modify: `lib/summaries.mjs:1-171`
- Modify: `scripts/crawl_naver_blog.mjs:181-276`
- Modify: `openapi.yaml:2467-2488`
- Test: `lib/blogs.test.mjs`
- Test: `lib/summaries.test.mjs`

**Interfaces:**
- Produces: optional `BlogPreview.items[].publishedAt` ISO string and `hasNewEligiblePost(preview, newestLocal, crawlSince) -> boolean`.
- Consumes: Naver `item.addDate`, existing `crawlSince`, and existing local latest log number.

- [ ] **Step 1: Write failing eligibility, contract, cleanup, and staging tests**

```javascript
test("empty corpus skips remote posts older than crawlSince", () => {
  assert.equal(hasNewEligiblePost({items: [{logNo: "10", publishedAt: "2026-07-01T00:00:00.000Z"}]}, 0, "2026-07-14T00:00:00.000Z"), false);
});

test("runCodexSummary removes output-last-message after success", async () => {
  // Put a fake codex executable first on PATH, run the real function, and assert no blog-summary file remains.
});
```

Add a crawler fixture whose body parse fails after download and assert no final raw HTML is published.

- [ ] **Step 2: Run tests and confirm RED**

Run: `node --test lib/blogs.test.mjs lib/summaries.test.mjs`

Expected: missing eligibility export, leaked output file, and raw file left before parse completion.

- [ ] **Step 3: Implement eligible-preview and guaranteed cleanup**

```javascript
export function hasNewEligiblePost(preview, newestLocal, crawlSince) {
  const newest = preview.items[0];
  if (!newest || Number(newest.logNo) <= newestLocal) return false;
  if (!newestLocal && crawlSince && Date.parse(newest.publishedAt || "") < Date.parse(crawlSince)) return false;
  return true;
}
```

Return `publishedAt` when Naver supplies a valid `addDate`, use the helper in the scheduler, unlink summary output in `finally`, and promote raw staging only after parse succeeds.

- [ ] **Step 4: Update and validate OpenAPI**

Add optional `publishedAt: {type: string, format: date-time}` to `BlogPreview.items[]`.

Run: `npm run check:openapi && node --test test/contract/openapi-routes.test.mjs`

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `node --test lib/blogs.test.mjs lib/summaries.test.mjs`

- [ ] **Step 6: Commit**

```bash
git add lib/blogs.mjs lib/blogs-router.mjs lib/summaries.mjs scripts/crawl_naver_blog.mjs openapi.yaml lib/blogs.test.mjs lib/summaries.test.mjs
git commit -m "fix: make blog refreshes eligible and temporary"
```

### Task 4: Report Real Collector and Engine Health

**Files:**
- Modify: `engine/sector/collectors/dart_edgar.py:61-126`
- Modify: `engine/sector/runner.py:16-67`
- Modify: `engine/monitor/runner.py:55-155`
- Modify: `engine/monitor/checks.py`
- Modify: `engine/monitor/scheduler.py`
- Test: `engine/tests/test_sector_collectors_news.py`
- Test: `engine/tests/test_monitor_checks.py`
- Test: `engine/tests/test_monitor_runner.py`

**Interfaces:**
- Produces: correct DART/EDGAR status; backward-compatible `_run` metadata in `status.json`; `check_engine_health(result) -> list[CheckResult]`.
- Consumes: an injected `engine_probe` in tests and the local health URL in the scheduler worker.

- [ ] **Step 1: Write failing status and health tests**

```python
def test_dart_edgar_all_sources_failed_is_error(monkeypatch):
    assert result.status == "error"

def test_dart_edgar_partial_failure_is_degraded(monkeypatch):
    assert result.status == "degraded"

def test_engine_probe_timeout_is_alert(tmp_path):
    report = run_checks(storage_root=tmp_path, engine_probe=lambda: {"error": "timeout"})
    assert any(r.pipeline == "engine" and r.level == "alert" for r in report.results)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd engine && .venv/bin/python -m pytest tests/test_sector_collectors_news.py tests/test_monitor_checks.py tests/test_monitor_runner.py -q`

Expected: all-source DART/EDGAR failure reports `ok`, and no engine check exists.

- [ ] **Step 3: Implement collector aggregation, run metadata, and engine probe**

Count attempted and failed sources explicitly. Persist `_run` with UUID, timestamps, and state without removing existing collector keys, and exclude underscore-prefixed metadata from collector-status iteration. Make network probing opt-in/injected so ordinary offline calls remain hermetic; the production monitor scheduler injects the local engine probe.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `cd engine && .venv/bin/python -m pytest tests/test_sector_collectors_news.py tests/test_monitor_checks.py tests/test_monitor_runner.py -q`

- [ ] **Step 5: Commit**

```bash
git add engine/sector/collectors/dart_edgar.py engine/sector/runner.py engine/monitor/runner.py engine/monitor/checks.py engine/monitor/scheduler.py engine/tests/test_sector_collectors_news.py engine/tests/test_monitor_checks.py engine/tests/test_monitor_runner.py
git commit -m "fix: expose collector and engine health accurately"
```

### Task 5: Repair the P23 Regression Contract

**Files:**
- Modify: `engine/tests/test_p23_off_identity.py`
- Modify: `engine/tests/p23_harness.py`
- Modify: `engine/tests/fixtures/p23_off_golden.json`

**Interfaces:**
- Produces: a current-revision off-arm structural snapshot with explicit metadata.
- Consumes: existing behavioral off-arm assertions in `test_p23_integration.py`.

- [ ] **Step 1: Preserve the observed RED result**

Run: `cd engine && .venv/bin/python -m pytest tests/test_p23_off_identity.py tests/test_p23_integration.py -q`

Expected: exact off-arm snapshot failure caused by macro and sector-momentum additions.

- [ ] **Step 2: Rename the invariant and recapture the fixture**

Change pre-P3 wording to current off-arm structural snapshot wording and capture from the clean feature revision. Keep exact equality and the separate no-thesis/no-chain behavioral assertions.

Run: `cd engine && .venv/bin/python -m tests.p23_harness --capture`

- [ ] **Step 3: Confirm GREEN**

Run: `cd engine && .venv/bin/python -m pytest tests/test_p23_off_identity.py tests/test_p23_integration.py -q`

- [ ] **Step 4: Commit**

```bash
git add engine/tests/test_p23_off_identity.py engine/tests/p23_harness.py engine/tests/fixtures/p23_off_golden.json
git commit -m "test: refresh the P23 off-arm structural contract"
```

### Task 6: Add Idempotent Operations and Reversible Repair

**Files:**
- Create: `ecosystem.config.cjs`
- Create: `ops/pm2-ryze_yn.service`
- Create: `ops/logrotate-attn-viewer`
- Create: `scripts/repair_runtime_data.py`
- Create: `engine/tests/test_repair_runtime_data.py`
- Modify: `README.md:128-166`

**Interfaces:**
- Produces: one named PM2 application per role and a default-dry-run `repair_runtime_data.py` with explicit `--apply --backup-root` mutation gate.
- Consumes: current repository root, user corpus root, memory-sector root, and `/tmp/blog-summary-*` inventory.

- [ ] **Step 1: Write failing repair-script tests**

```python
def test_dry_run_reports_duplicates_without_mutating(tmp_path):
    before = data.read_bytes()
    report = repair(root, apply=False, backup_root=None)
    assert report["duplicate_rows"] == 1
    assert data.read_bytes() == before

def test_apply_backs_up_dedupes_and_quarantines(tmp_path):
    report = repair(root, apply=True, backup_root=backup)
    assert backup_copy.exists()
    assert report["duplicate_rows_removed"] == 1
    assert quarantined_orphan.exists()
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd engine && .venv/bin/python -m pytest tests/test_repair_runtime_data.py -q`

Expected: repair module is missing.

- [ ] **Step 3: Implement dry-run-first reversible repair**

Deduplicate raw news by `id`, metrics by the current `MetricObservation.key()` fields, back up every modified file preserving relative paths, and move orphan/tmp files into the backup quarantine. Refuse `--apply` without an unused backup directory.

- [ ] **Step 4: Add operations manifests and README procedure**

Define exactly one viewer, engine, scheduler, bridge, and non-restarting ngrok entry. Use restart delay/backoff and memory caps. Add a systemd `RestartSec=5`, and daily/20MiB copy-truncate log rotation with seven compressed generations.

- [ ] **Step 5: Run repair and configuration tests**

Run: `cd engine && .venv/bin/python -m pytest tests/test_repair_runtime_data.py -q`

Run: `node --check ecosystem.config.cjs && systemd-analyze verify ops/pm2-ryze_yn.service`

- [ ] **Step 6: Commit**

```bash
git add ecosystem.config.cjs ops/pm2-ryze_yn.service ops/logrotate-attn-viewer scripts/repair_runtime_data.py engine/tests/test_repair_runtime_data.py README.md
git commit -m "ops: make deployment idempotent and repair reversible"
```

### Task 7: Verify, Deploy, Repair, Commit, and Push

**Files:**
- Verify all files changed by Tasks 1-6.
- Operational install targets: `/etc/systemd/system/pm2-ryze_yn.service`, `/etc/logrotate.d/attn-viewer`, user crontab, `/home/ryze_yn/.pm2/dump.pm2`.

**Interfaces:**
- Consumes: all code, manifest, and repair interfaces above.
- Produces: a clean `main`, one live instance per service role, validated storage, and pushed commits.

- [ ] **Step 1: Run the full offline gate**

Run: `npm test`

Expected: exit 0; Node 84 plus new tests, E2E 11, and all offline Python tests pass.

- [ ] **Step 2: Back up operational state**

Create a timestamped directory outside the repository and copy PM2 dump, crontab, systemd unit, PM2 logs, and every data file the repair report will modify.

- [ ] **Step 3: Fast-forward the operating checkout and install configs**

Fast-forward `main` to the feature branch, install the checked-in systemd and logrotate files, remove only the exact PM2 `@reboot` crontab line, and reload systemd configuration.

- [ ] **Step 4: Quiesce PM2 once and apply the data repair**

Stop the named duplicated applications, create and validate an unused path under `/home/ryze_yn/attn-viewer-ops-backups/`, run `scripts/repair_runtime_data.py --apply --backup-root "$audit_backup_root"`, then start/reload `ecosystem.config.cjs` once and `pm2 save` once.

- [ ] **Step 5: Verify live behavior**

Run health, session, market-report list/detail, PM2 uniqueness, systemd state, JSON/JSONL integrity, duplicate-key, temp-file, and orphan scans. Run a monitor-only smoke check; do not force an out-of-slot report.

- [ ] **Step 6: Push**

```bash
git push origin main
git push public main
```

If one remote rejects because its history differs, leave the successful push intact and report the exact rejection without force-pushing.
