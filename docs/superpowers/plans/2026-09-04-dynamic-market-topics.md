# Dynamic Market Topics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate the next scheduled report as macro plus two ranked daily market topics, with evidence-backed direct and second-order impacts and full legacy compatibility.

**Architecture:** Keep the existing three-card `axes` reader and introduce an additive `topics_v1` discriminator. Broaden the existing raw-news relevance boundary, select three typed plans, validate scenario transmission deterministically, and let the viewer render labels from payload data. Preserve all historical files and permanently consume archived report IDs.

**Tech Stack:** Python 3.12, Pydantic 2, asyncio, Claude/Codex CLI routing, OpenAPI 3.1 YAML, Node.js 22, browser JavaScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-04-dynamic-market-topics-design.md`

## Global Constraints

- New generated reports use `format: "axes"` and `axisModel: "topics_v1"` with exactly `macro`, `topic1`, and `topic2`.
- Historical reports without `axisModel` remain valid only as exact `macro`, `memory`, and `other` card sets and are never rewritten.
- Model inference remains CLI-only; OpenAPI is a data contract, not a model provider.
- Every successful scenario has one direct and one indirect impact; stock impacts require company-specific evidence or become sector impacts.
- Memory collection remains intact but has no reserved topic slot or headline priority.
- UI behavior is mobile first and must be inspected at phone and desktop widths.
- Do not restart services or delete report data; generator changes activate through the fresh scheduled subprocess.
- Work directly on `main` because the user explicitly requested commits/pushes and the scheduled subprocess reads this working tree; push both `origin/main` and `public/main` after verified milestones.

---

### Task 1: Contract and Permanent Report Identity

**Files:**
- Modify: `engine/sector/report_contracts.py`
- Modify: `engine/sector/report_pipeline.py`
- Modify: `openapi.yaml`
- Test: `engine/tests/test_report_contracts.py`
- Test: `engine/tests/test_report_pipeline.py`
- Test: `test/contract/market-report.contract.test.mjs`

**Interfaces:**
- Produces: `Report.axisModel`, `Report.leadAxis`, `AxisCard.label`, `AxisCard.topicKey`, `AxisBeneficiary.causalChain`, `AxisBeneficiary.evidence`.
- Produces: `alloc_report_slot(root: Path, date: str) -> tuple[int, Path]` that treats archive IDs as consumed.

- [ ] **Step 1: Write failing old/new contract and archived-slot tests.** Build literal fixtures for one old fixed-axis report and one `topics_v1` report, reject a mixed set, and create active `-3` plus archived `-1/-2` before asserting the next sequence is `4`.
- [ ] **Step 2: Run the focused tests and confirm failures are caused by missing new fields/validation and archive scanning.** Run `cd engine && .venv/bin/pytest tests/test_report_contracts.py tests/test_report_pipeline.py -q` and `node --test test/contract/market-report.contract.test.mjs`.
- [ ] **Step 3: Add the minimal Pydantic and OpenAPI union contract.** Use cross-model validation for exact sets, distinct topic keys, lead membership, scenario coverage, and stock evidence; keep the legacy branch additive.
- [ ] **Step 4: Make allocation scan active report names, reservations, and recursive archive JSON names before atomically reserving the first unused sequence.** Do not move or delete files.
- [ ] **Step 5: Re-run the focused Python and Node contract tests until green, then run `python scripts/validate_market_report.py storage/rag/memory_sector/reports/2026-09-04-3.json`.**
- [ ] **Step 6: Commit and push both remotes.** Commit message: `feat: add dynamic topic report contract`.

### Task 2: Broad Topic Selection and Transmission Validation

**Files:**
- Modify: `engine/sector/report_filters.py`
- Modify: `engine/sector/report_axes.py`
- Modify: `engine/sector/report_pipeline.py`
- Test: `engine/tests/test_report_filters.py`
- Test: `engine/tests/test_report_axes.py`
- Test: `engine/tests/test_report_pipeline.py`

**Interfaces:**
- Consumes: the Task 1 `topics_v1` Pydantic fields.
- Produces: `run_axes_flow(...) -> tuple[list[AxisCard], list[str], str]`, where the last value is `leadAxis`.
- Produces: plans keyed by `macro`, `topic1`, and `topic2`, each carrying `label`, `topic_key`, ranking rationale, and assigned evidence titles.

- [ ] **Step 1: Write failing tests proving non-memory full-text evidence survives F1, selected topics are distinct, memory has no reserved slot, continuity follows `topicKey`, each scenario covers direct/indirect paths, and the lead card controls the report title.**
- [ ] **Step 2: Run `cd engine && .venv/bin/pytest tests/test_report_filters.py tests/test_report_axes.py tests/test_report_pipeline.py -q` and confirm each new test fails for the intended missing behavior.**
- [ ] **Step 3: Generalize F1 to market materiality while preserving title, excerpt, source, URL, and timestamp in the existing evidence objects.** Remove unconditional preference for memory cards.
- [ ] **Step 4: Replace fixed-axis splitting with ranked topic selection.** Require two distinct non-macro topic keys, use macro versus dynamic-topic prompt branches, and inject case memory only when a selected plan is tagged memory-related.
- [ ] **Step 5: Validate generated scenarios before card construction.** Require positive and negative, direct and indirect in each, non-empty causal chains, and stock evidence/name shape; perform one constrained regeneration then degrade explicitly on failure.
- [ ] **Step 6: Return and persist `leadAxis`; choose the audited lead card title instead of memory-first logic.** Match previous dynamic cards by topic key.
- [ ] **Step 7: Re-run focused tests, `cd engine && .venv/bin/python -m compileall -q sector`, and `node --check server.mjs`.**
- [ ] **Step 8: Commit and push both remotes.** Commit message: `feat: rank daily market report topics`.

### Task 2A: CLI-Only Failure Diagnostics and Article Fallback

**Files:**
- Modify: `engine/cli_role.py`
- Modify: `engine/providers.py`
- Modify: `engine/tests/test_cli_role.py`
- Test: `engine/tests/test_search_quality.py`

**Interfaces:**
- Consumes: Claude CLI JSON envelopes and the existing `Role` CLI fallback chain.
- Produces: a bounded non-secret failure diagnostic and Claude CLI to Codex CLI fallback for `report_article`.

- [ ] **Step 1: Write failing tests for a nonzero Claude exit whose JSON stdout contains `result` or `api_error_status`, and for `ROLE_MAP["report_article"]` falling from Claude CLI to Codex CLI without any API client.**
- [ ] **Step 2: Run `cd engine && .venv/bin/pytest tests/test_cli_role.py tests/test_search_quality.py -q` and confirm the diagnostic is lost and the report role has only one leg.**
- [ ] **Step 3: Add a helper that emits only allowlisted status metadata from JSON stdout, classifies known stderr failures to fixed non-secret codes, and otherwise emits no diagnostic text.** Never log prompt text, credentials, raw stderr, or full response envelopes.
- [ ] **Step 4: Add `(CODEX_CLI, settings.model_gpt, "high")` as the second `report_article` leg.** Keep all model API credentials scrubbed and do not add an HTTP client.
- [ ] **Step 5: Re-run the focused tests plus `cd engine && .venv/bin/pytest tests/test_report_axes.py tests/test_report_pipeline.py -q`; run Python compile and `git diff --check`.**
- [ ] **Step 6: Commit and push both remotes.** Commit message: `fix: keep report generation on resilient cli paths`.

### Task 3: Generic Reader, Editorial Tooling, and Health Checks

**Files:**
- Modify: `public/report.js`
- Modify: `public/style.css`
- Modify: `scripts/create-report-editorial.mjs`
- Modify: `engine/monitor/checks.py`
- Test: `test/api/report-editorial.test.mjs`
- Test: `test/e2e/report-readability.smoke.test.mjs`
- Test: `engine/tests/test_monitor_checks.py`

**Interfaces:**
- Consumes: exact card axis IDs plus `card.label` and `topicKey`.
- Produces: label/tone/DOM helpers that preserve legacy IDs and render new topic slots without normalization, plus readable transmission/evidence rows for new scenario impacts.

- [ ] **Step 1: Write failing Node/E2E/monitor tests for the generic report-list header, dynamic labels, exact navigation targets, unique DOM IDs, readable `causalChain`/stock `evidence`, new health-card sets, derived editorial keys, and a legacy rendering fixture.** The `#report` list header must say that generation starts every day at 06:30 and 18:30 KST and describe the scope as macro plus the day's key topics, not a memory-semiconductor value chain.
- [ ] **Step 2: Run `node --test test/api/report-editorial.test.mjs` and the focused monitor tests, then run the E2E smoke command from `package.json`; confirm expected failures.**
- [ ] **Step 3: Centralize card label and tone resolution.** Use `card.label` first, the old map only for old axes, exact axis data attributes for navigation, and unique panel/phenomenon IDs. Render optional impact `causalChain` and stock `evidence` as labeled reading rows without changing legacy cards.
- [ ] **Step 4: Make the editorial builder derive the expected card IDs from its base report while enforcing the corresponding old/new exact set.** Preserve all base evidence fields.
- [ ] **Step 5: Teach monitoring to accept either exact model and reject mixed/missing/duplicate sets.**
- [ ] **Step 6: Inspect the report list and detail at a narrow phone viewport and desktop viewport; verify the schedule/scope header, readable single-column cards, tab wrapping, keyboard navigation, and no horizontal overflow.**
- [ ] **Step 7: Re-run the focused tests, commit, and push both remotes.** Commit message: `feat: render dynamic report topics`.

### Task 4: Whole-System Verification and Scheduled Activation

**Files:**
- Modify only when a failing verification has a reproducible regression test in the relevant test file.

**Interfaces:**
- Consumes: Tasks 1-3 commits.
- Produces: verified code on both remotes and operational evidence from the next scheduled run.

- [ ] **Step 1: Run the full Node suite, browser E2E suite, and full Python suite with the repository's established commands; record exact pass/fail counts.**
- [ ] **Step 2: Run `node --check server.mjs`, validate one stored legacy payload and a generated new fixture against OpenAPI, and confirm `git diff --check` is clean.**
- [ ] **Step 3: Request a read-only Claude review of the complete committed diff; independently reproduce and fix every Critical or Important finding with a failing test first.**
- [ ] **Step 4: Run the full verification commands again on the final tree, commit any review fixes as `fix: harden dynamic topic reports`, and push both remotes.**
- [ ] **Step 5: Confirm PM2 remains four unique online processes and that no report subprocess is active before the slot. Do not restart it.**
- [ ] **Step 6: Monitor the 18:30 KST freshness collection and report subprocess logs. Confirm the new report has sequence at least 4, `axisModel=topics_v1`, exact three cards, valid `leadAxis`, direct/indirect scenario coverage, and no duplicate generation.**

### Task 3A: Per-Axis Evidence Routing and Beneficiary Breadth

**Files:**
- Modify: `engine/sector/report_axes.py`
- Test: `engine/tests/test_report_axes.py`

**Interfaces:**
- Produces: a deterministic per-axis anchor selection so macro sees macro data
  first, a memory topic can use memory metrics, and unrelated dynamic topics do
  not inherit memory anchors merely because memory data was collected.
- Produces: source-grounded stock validation and prior-card stock exclusions;
  unsupported or recycled company picks must be regenerated as independently
  grounded stocks or sectors.

- [ ] **Step 1: Add regressions for fair selector anchor coverage, macro-only
  macro anchors, an AI-infrastructure topic receiving AI/capex rather than memory
  anchors, rejection of a stock absent from assigned source/research/selected
  anchor material, and rejection of a stock already used by another card.**
- [ ] **Step 2: Confirm the regressions fail against the `2026-09-04-5` code path.**
- [ ] **Step 3: Route anchors per plan and include the assigned source material
  in scenario grounding. Derive memory/AI routing from matched evidence, not an
  unsupported selector label. Do not add a memory quota: two independently
  evidenced memory events remain eligible when rank places both in the top two.
  Keep all memory collectors and stored metrics intact.**
- [ ] **Step 4: Process cards by plan rank, pass canonical issuer IDs into later
  scenario generation, expose the exclusions in the retry prompt, validate
  issuer/ticker pairs deterministically (including dual listings and unknown
  tickers co-located with their company in original evidence), reject issuer-as-
  sector and same-polarity issuer aliases, then restore macro/topic1/topic2 display
  order. URL/source/metric metadata and model cluster summaries are not stock
  identity evidence.**
- [ ] **Step 5: Extend the semantic audit prompt to inspect beneficiary evidence
  and event-to-impact causality. Escape selector/phenomenon/scenario/audit
  payloads, cap sources per record while retaining timestamps, fail closed after
  a missing/schema-invalid beneficiary verdict or retry timeout, and keep only a
  genuine first-call transport outage from becoming a failed card. Assert every
  `REPORT_METRICS` entry has an explicit route.**
- [ ] **Step 6: Run the focused suite, independent review, fixes, then commit and
  push both remotes before generating the replacement live report.**

### Task 3B: Permanent Automatic Reading Layer

**Files:**
- Modify: `openapi.yaml`
- Modify: `engine/sector/report_contracts.py`
- Modify: `engine/sector/report_pipeline.py`
- Add: `engine/sector/report_readability.py`
- Test: `engine/tests/test_report_readability.py`
- Test: `engine/tests/test_report_pipeline.py`

**Interfaces:**
- Produces: an integrated `Report.editorial` with exact
  macro/topic1/topic2 takeaways and self provenance.
- Produces: `Report.readerModel="brief_v1"`, which makes the integrated overview
  and all card briefs mandatory while leaving unmarked historical files valid.
- Produces: a typed `AxisCard.brief` for all three generated cards, including an
  explicit degraded/error card.
- Produces: a typed `readerCopy` on every direct/indirect beneficiary while
  preserving the raw rationale, causal chain, evidence, and financials in place.
  It naturalizes metric/unit/comparison syntax, removes ticker codes, and binds
  every copied number to its original row, period, direction, comparison basis,
  and financial metric.
- Produces: a visible `readability` pipeline stage whose structured CLI result
  is replaced by a deterministic, fact-preserving fallback when necessary.
- Renders: concise readerCopy first and a nested, mobile-safe `원문 데이터 보기`
  disclosure with the complete unmodified row, so field length limits never hide
  late corrections.

- [ ] **Step 1: Add failing contract and pipeline tests proving a normal
  `topics_v1` generation contains the same overview/card-guide structure used by
  report `2026-09-04-3`, in the original report ID rather than a second overlay.**
- [ ] **Step 2: Define the Python reading-layer models and align OpenAPI
  descriptions and cardinalities while retaining historical fixed-axis and
  manually edited report compatibility.**
- [ ] **Step 3: Implement one structured CLI reading pass over safely delimited
  audited card JSON. Require exact axes, concise Korean prose, grounded numeric
  tokens, both scenario guides, and no changes to detailed source content.**
- [ ] **Step 4: Implement a deterministic non-empty fallback from card title,
  phenomenon, scenario theses, watch signals, and every beneficiary row. Expand
  raw metric/unit syntax into Korean prose, strip ticker codes, retain uncertainty
  labels, record generated versus fallback status in diagnostics, and keep replay
  deterministic and total for all upstream-valid strings.**
- [ ] **Step 5: Re-run focused Python/OpenAPI/Node/E2E tests and inspect the new
  report at mobile and desktop widths. Request independent review, fix all
  Critical/Important findings, then commit and push both remotes.**
