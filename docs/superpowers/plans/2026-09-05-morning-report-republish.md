# Morning Report Republish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permanently prevent process-language headlines and accept only collector-verified Taiwan securities, then republish the 2026-09-05 06:30 KST report manually.

**Architecture:** Keep the report contract fail-closed. Strengthen the shared reader rule and fallback copy sanitizer at the presentation boundary, and share the MOPS tracked-company registry with scenario grounding instead of broadening ticker syntax indiscriminately. Publish only after contract, pipeline, and mobile checks pass.

**Tech Stack:** Python 3, Pydantic, pytest, Node.js OpenAPI contract tests, PM2.

**Spec:** User requirements in the active conversation and `/home/ryze_yn/attn-viewer/AGENTS.md`.

## Global Constraints

- CLI model providers only; no OpenAI API model calls.
- Mobile-first report presentation.
- Preserve the 06:30 and 18:30 KST schedule.
- Do not publish a degraded or reader-contract-invalid report.
- Keep rejected reports recoverable; do not hard-delete them.

---

### Task 1: Reader-safe fallback copy

**Files:**
- Modify: `engine/sector/report_readability.py`
- Modify: `engine/sector/report_reader_rules.py`
- Modify: `openapi.yaml`
- Test: `engine/tests/test_report_readability.py`
- Test: `test/contract/market-report.contract.test.mjs`

**Interfaces:**
- Consumes: `AxisCard.deep_dive.conclusion` and generated `ReportReadability` strings.
- Produces: `_editorial_conclusion_text(value) -> str` and `reader_scan_first_problem(value) -> bool` that reject process narration while preserving the factual clause.

- [ ] **Step 1: Write the failing tests**

  Add the two production phrases beginning `심층 연구는 ... 실패했다` and `연구는 헤드라인 ... 보여준다` to fallback and generated-draft tests. Assert factual clauses remain, while process narration is absent. Add matching OpenAPI rejection fixtures.

- [ ] **Step 2: Run tests to verify RED**

  Run `engine/.venv/bin/pytest -q engine/tests/test_report_readability.py -k 'process_narration or production_research'` and the focused Node contract test. Expected: the current fallback exposes the phrases or the current contract accepts them.

- [ ] **Step 3: Implement the minimum sanitizer and contract change**

  Strip only sentence-leading research-process narration, prefer the post-em-dash factual clause when present, and extend the Python/OpenAPI scan-first rule to reject those same process forms. Do not globally remove legitimate mentions of published studies.

- [ ] **Step 4: Run focused and neighboring tests to verify GREEN**

  Run the focused tests plus all reader-rule/readability contract tests. Expected: all pass and correction facts remain visible.

- [ ] **Step 5: Commit**

  Commit the production and regression-test changes as one reader-copy fix.

### Task 2: Verified MOPS securities in scenario validation

**Files:**
- Modify: `engine/sector/collectors/mops_tw.py`
- Modify: `engine/sector/report_axes.py`
- Test: `engine/tests/test_report_axes.py`
- Test: `engine/tests/test_sector_collectors_metrics.py`

**Interfaces:**
- Consumes: collector-owned `TRACKED_COMPANIES: dict[str, str]` and exact `Anchor.entity` values.
- Produces: scenario validation that accepts registered bare MOPS codes, canonicalizes `2330` with `TSM`, rejects unregistered codes and inferred `.TW` suffixes, and retains both direct and indirect paths.

- [ ] **Step 1: Write the failing tests**

  Add fixtures for `TSMC (2330)` grounded by `tw_monthly_revenue:2330`, rejection of `가상기업 (9999)` and `TSMC (2330.TW)`, and duplicate issuer detection between `TSMC (TSM)` and `TSMC (2330)`.

- [ ] **Step 2: Run tests to verify RED**

  Run the three focused pytest cases. Expected: verified bare code is rejected by the current stock-name grammar.

- [ ] **Step 3: Share the registry and tighten generation guidance**

  Export the existing collector registry, import it into the validator, register exact bare codes and issuer aliases, preserve exact anchor entities, and put the verified identifiers plus “do not infer suffixes; use a real sector when unavailable” in the scenario prompt.

- [ ] **Step 4: Run focused and neighboring tests to verify GREEN**

  Run `engine/tests/test_report_axes.py` and `engine/tests/test_sector_collectors_metrics.py`. Expected: verified codes pass; fabricated identifiers fail; existing US/Korean behavior remains intact.

- [ ] **Step 5: Commit**

  Commit the registry and scenario-contract change as one grounding fix.

### Task 3: Merge, verify, and republish the morning slot

**Files:**
- Runtime output: `storage/rag/memory_sector/reports/2026-09-05-*.json`
- Recoverable rejects: `storage/rag/memory_sector/rejected-reports/`

**Interfaces:**
- Consumes: the fixed report pipeline and the `2026-09-05T06:30:00+09:00` scheduled-fire identity.
- Produces: one public, contract-valid 2026-09-05 morning report and an unchanged next automatic fire at 18:30 KST.

- [ ] **Step 1: Run full verification in the isolated worktree**

  Run Python, Node, OpenAPI, and UI suites; inspect the complete output and failure counts.

- [ ] **Step 2: Review and integrate**

  Run independent/Claude CLI review, address verified findings, fast-forward `main`, rerun merge-target checks, and push both configured Git remotes.

- [ ] **Step 3: Generate the 06:30 report manually**

  Confirm no collection/report process is active, invoke the scheduler run with the morning scheduled-fire identity, and wait for completion without starting a duplicate collector.

- [ ] **Step 4: Validate publication and mobile rendering**

  Require `publish_status=ok`, all three cards, positive/negative plus direct/indirect paths, no process boilerplate, concise title, OpenAPI validation, and clean narrow/desktop report views.

- [ ] **Step 5: Confirm the next automatic run**

  Verify PM2 has one process per service and scheduler logs/settings still identify 2026-09-05 18:30 KST as the next automatic report.
