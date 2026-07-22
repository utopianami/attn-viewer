# 시황 리포트 Phase 2 파이프라인 Implementation Plan · v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> v2: codex 계획 리뷰 r1(BLOCKER 12·SF 5·NIT 3) 전면 반영. 스펙 v3 준거.

**Goal:** Phase 1 `ReportInput`을 받아 필터→심화→합성→검증→결론조립을 거쳐 뷰어 호환 리포트 JSON을 결정적으로 생성·영속화하는 파이프라인.

**Architecture:** `engine/sector/`에 계약·필터·랭커·심화/합성·검증·결론조립·오케스트레이션. 필터=API(sonnet), 심화·합성=CLI(claude `-p --json-schema <인라인JSON> --tools ""`), CliRole은 `Role.run` try 최상단 분기(자체 프롬프트 조립 — run_prompt 미참조)로 통합, 실패 raise→API 폴백. 결론은 **verified claim만으로 코드가 조립**.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest(**pytest-asyncio 없음 — sync test + `asyncio.run()`**, test_refute.py:29 관례), node:test(+test/helpers/test-server.mjs). 실행: `cd engine && .venv/bin/python -m sector.report_pipeline`.

## Global Constraints (스펙 v3 verbatim)

- **never-raise + 진단**: 스테이지는 `StageResult`(output 필수·io·error) 반환, downstream-safe 빈 output. 오케스트레이터는 `.output` 언랩.
- **숫자는 코드가**: LLM 산술 금지. 수치 주장은 LLM이 `numeric_facts[{anchor_id, value}]`로 **선언**하고 **코드가 anchor 정체성으로 대조**. `finalOpinion.confidence`=verified 최소(코드).
- **결정성**: `effective_now` 1회 전파. `ts ≤ now`(일 단위 정밀) ∧ `ingested_at ≤ now`(파싱 가능 시). 빈/불파싱 ingested_at=통과(레거시 정책, 진단 카운트).
- **결론은 verified만**: overview/finalOpinion에 unverified/rejected 텍스트 유입 금지. rejected는 claims[]에서 제외 → `diagnostics.rejected_claims`.
- **claims[].evidence는 표시 문자열**, typed는 `evidence_refs`(additive). stage.items 문자열만.
- **CLI**: `--json-schema`는 인라인 JSON · 툴오프는 `--tools ""` · `--no-session-persistence` · 고정 cwd(스크래치) · 프로세스그룹 타임아웃 킬 · envelope `structured_output` 우선 파싱. (전부 codex 실측)
- **저장**: flat `reports/{id}.json`, `id="{KST YYYY-MM-DD}-{seq}"`, **예약(alloc)→조립(seq 주입)→저장(예약 경로)**. save는 예약 없는 경로 거부.
- **seam**: 가격반응·증권사·과거사례(casemem Plan1~3 라이브지만 사용자 완료 통보까지 미연결) → `diagnostics.seams_empty`, `precedent_grounded=false`.

**테스트 공통**: `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` 후 `from sector.x import ...`. 실행 `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/pytest tests/test_X.py -v`.

---

## File Structure

- T1 Create `engine/sector/report_contracts.py`
- T2 Create `engine/cli_role.py` · Modify `engine/providers.py`(_capable·Role.run·ROLE_MAP)
- T3 Modify `engine/sector/report_input.py` + 기존 테스트 픽스처
- T4 Create `engine/sector/report_metrics_allowlist.py`(상수 leaf) · `engine/sector/report_anchors.py`
- T5 Modify `engine/stages/playbook.py`(_score 추출) · Create `engine/sector/report_rules.py`
- T6 Create `engine/sector/report_filters.py` (f1+f2+f3 각각 테스트)
- T7 Create `engine/sector/report_synthesis.py`
- T8 Create `engine/sector/report_verify.py`
- T9 Create `engine/sector/report_assemble.py`
- T10 Create `engine/sector/report_pipeline.py` · Modify `AGENTS.md`(시스템 리포트 예외 1줄)
- T11 Modify `openapi.yaml` · Create `test/contract/market-report.contract.test.mjs`
- T12 Create `engine/tests/test_report_e2e.py`

---

### Task 1: 계약 (report_contracts.py)

**Files:** Create `engine/sector/report_contracts.py` · Test `engine/tests/test_report_contracts.py`

**Interfaces — Produces (이후 태스크 전부가 사용):**
- `EvidenceRef(kind: Literal["card","news","metric","price"], id: str, title="", ts="", excerpt="", source="", url="")`
- `EventCluster(cluster_id: str, title: str, topics: list[str]=[], axis="B", direction="neutral", members: list[EvidenceRef]=[], representative_excerpt="")`
- `Anchor(anchor_id: str, metric: str, entity="", period="", value: float, unit="", delta_pct: float|None=None, as_of="", source="")`
- `NumericFact(anchor_id: str, value: float)` — LLM 선언 수치, 코드 대조용
- `ReportClaim(claim_id: str, title: str, confidence: Confidence="낮", status: ClaimStatus="unverified", trigger="", mechanism="", evidence: list[str]=[], evidence_refs: list[EvidenceRef]=[], anchor_refs: list[str]=[], numeric_facts: list[NumericFact]=[], precedent="", precedent_grounded=False, counter="", stance="", matched_rules: list[str]=[], load_bearing=False, as_of="")` — `claim_id`는 합성이 `"c0","c1",…` 부여(인덱스 커플링 제거, codex NIT)
- `FinalOpinion(text: str, confidence: Confidence)`
- `StageIO(key, label, note="", in_count=0, out_count=0, dropped: list[dict]=[], elapsed_ms=0)`
- `StageResult(output: Any, io: StageIO, error: str|None=None)` — **output 필수**(기본값 없음 — 빈 결과도 명시)
- `PipelineStage(key, label, note="", items: list[str]=[], sources: list[dict]=[], io: dict|None=None)`
- `ReportPipeline(stages: list[PipelineStage]=[])` — Report.pipeline을 **타입으로 강제**(codex SF1)
- `ClaimVerdict(claim_id: str, status: ClaimStatus, reasons: list[str]=[], adjusted_confidence: Confidence="낮")`
- `Report(id, seq: int, generatedAt, title, window: dict, overview="", finalOpinion: FinalOpinion, claims: list[ReportClaim]=[], pipeline: ReportPipeline, diagnostics: dict={})`

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_contracts.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from pydantic import ValidationError
from sector.report_contracts import (
    Anchor, ClaimVerdict, EvidenceRef, EventCluster, FinalOpinion, NumericFact,
    PipelineStage, Report, ReportClaim, ReportPipeline, StageIO, StageResult,
)


def test_claim_defaults_safe_and_id_required():
    c = ReportClaim(claim_id="c0", title="t")
    assert c.confidence == "낮" and c.status == "unverified"
    assert c.evidence == [] and c.evidence_refs == [] and c.numeric_facts == []
    assert c.precedent_grounded is False and c.load_bearing is False
    with pytest.raises(ValidationError):
        ReportClaim(title="no-id")               # claim_id 필수


def test_stage_result_output_required():
    io = StageIO(key="f1", label="x")
    with pytest.raises(ValidationError):
        StageResult(io=io)                        # output 명시 필수(빈 결과도 명시)
    ok = StageResult(output=[], io=io)
    assert ok.output == [] and ok.error is None


def test_pipeline_items_are_strings_enforced():
    with pytest.raises(ValidationError):
        PipelineStage(key="f1", label="x", items=[{"title": "obj"}])   # 문자열만(뷰어 안전)
    p = ReportPipeline(stages=[PipelineStage(key="f1", label="x", items=["ok"])])
    assert p.stages[0].items == ["ok"]


def test_report_roundtrip_with_typed_pipeline():
    r = Report(id="2026-07-21-2", seq=2, generatedAt="x", title="t",
               window={"from": "a", "to": "b"},
               finalOpinion=FinalOpinion(text="hold", confidence="낮"),
               pipeline=ReportPipeline(stages=[]), diagnostics={})
    d = r.model_dump()
    assert d["pipeline"]["stages"] == [] and d["finalOpinion"]["confidence"] == "낮"


def test_numeric_fact_and_anchor():
    nf = NumericFact(anchor_id="memory_price_usd_per_gb:DRAM", value=3.5)
    a = Anchor(anchor_id="memory_price_usd_per_gb:DRAM", metric="memory_price_usd_per_gb",
               value=3.5, as_of="2026-07")
    assert nf.anchor_id == a.anchor_id
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`)
Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/pytest tests/test_report_contracts.py -v`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/sector/report_contracts.py
"""시황 리포트 Phase 2 계약 — 전 스테이지 공유. 뷰어 호환(evidence 문자열·items 문자열) +
additive 관측 필드(evidence_refs·io). 스펙 v3."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Confidence = Literal["낮", "중", "높"]
ClaimStatus = Literal["verified", "unverified", "rejected"]


class EvidenceRef(BaseModel):
    kind: Literal["card", "news", "metric", "price"]
    id: str
    title: str = ""
    ts: str = ""
    excerpt: str = ""
    source: str = ""
    url: str = ""


class EventCluster(BaseModel):
    cluster_id: str
    title: str
    topics: list[str] = Field(default_factory=list)
    axis: str = "B"
    direction: str = "neutral"
    members: list[EvidenceRef] = Field(default_factory=list)
    representative_excerpt: str = ""


class Anchor(BaseModel):
    anchor_id: str
    metric: str
    entity: str = ""
    period: str = ""
    value: float
    unit: str = ""
    delta_pct: float | None = None
    as_of: str = ""
    source: str = ""


class NumericFact(BaseModel):
    """LLM이 '이 anchor의 이 값을 인용했다'고 선언 — 코드가 정체성 대조(스펙: 숫자는 코드가)."""
    anchor_id: str
    value: float


class ReportClaim(BaseModel):
    claim_id: str
    title: str
    confidence: Confidence = "낮"
    status: ClaimStatus = "unverified"
    trigger: str = ""
    mechanism: str = ""
    evidence: list[str] = Field(default_factory=list)               # 뷰어 표시 문자열
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)  # typed(additive)
    anchor_refs: list[str] = Field(default_factory=list)
    numeric_facts: list[NumericFact] = Field(default_factory=list)
    precedent: str = ""
    precedent_grounded: bool = False
    counter: str = ""
    stance: str = ""
    matched_rules: list[str] = Field(default_factory=list)
    load_bearing: bool = False
    as_of: str = ""


class FinalOpinion(BaseModel):
    text: str
    confidence: Confidence


class StageIO(BaseModel):
    key: str
    label: str
    note: str = ""
    in_count: int = 0
    out_count: int = 0
    dropped: list[dict] = Field(default_factory=list)
    elapsed_ms: int = 0


class StageResult(BaseModel):
    output: Any                       # 필수 — 빈 결과도 [] / "" 로 명시(None 금지 규율)
    io: StageIO
    error: str | None = None


class PipelineStage(BaseModel):
    key: str
    label: str
    note: str = ""
    items: list[str] = Field(default_factory=list)   # 문자열만 — 뷰어 렌더 안전
    sources: list[dict] = Field(default_factory=list)
    io: dict | None = None                            # additive 관측치(뷰어 무시)


class ReportPipeline(BaseModel):
    stages: list[PipelineStage] = Field(default_factory=list)


class ClaimVerdict(BaseModel):
    claim_id: str
    status: ClaimStatus
    reasons: list[str] = Field(default_factory=list)
    adjusted_confidence: Confidence = "낮"


class Report(BaseModel):
    id: str
    seq: int
    generatedAt: str
    title: str
    window: dict
    overview: str = ""
    finalOpinion: FinalOpinion
    claims: list[ReportClaim] = Field(default_factory=list)
    pipeline: ReportPipeline
    diagnostics: dict = Field(default_factory=dict)
```

- [ ] **Step 4: Run — expect PASS** (5 passed)
- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_contracts.py engine/tests/test_report_contracts.py
git commit -m "feat(report): Phase2 계약 — claim_id·NumericFact·typed pipeline·output 필수"
```

---

### Task 2: CliRole + Role 통합 (cli_role.py · providers.py)

**Files:** Create `engine/cli_role.py` · Modify `engine/providers.py` · Test `engine/tests/test_cli_role.py`

**CLI 실측 전제(codex 스모크 2회 확인):** `--json-schema`=인라인 JSON(파일 경로면 exit 1) · envelope에 `structured_output`(canonical)과 `result`(문자열) 둘 다 · `--allowedTools ""`는 **Read/Bash 못 막음** → `--tools ""` · stdin 프롬프트 동작.

**Interfaces — Produces:**
- `async def cli_complete(model, instructions, prompt, *, response_format=None, effort=None, runner=None) -> Any` — 실패 raise(폴백 유발).
- `def _build_claude_argv(model: str, schema_json: str|None, effort: str|None) -> list[str]`
- `async def _run_cli(argv, stdin_text, timeout) -> tuple[int, str, str]` — **cwd=스크래치 고정**, 프로세스그룹 킬.
- providers: `_capable("cli")`= `shutil.which("claude") is not None`(cli_complete는 claude를 띄우므로 codex-only 설치는 불능 — codex B2), `Role.run` **try 최상단** cli 분기(자체 `cli_prompt` 조립 — `run_prompt`/`_make_client` 미참조), ROLE_MAP에 **프로덕션 role 추가**:
  - `"report_filter": [("anthropic", model_claude_sonnet, "low"), ("openai", model_gpt_mini, "low")]`
  - `"report_deepen": [("cli", "claude-opus-4-8", "high"), ("anthropic", model_claude, "high")]`
  - `"report_synth": [("cli", "claude-opus-4-8", "high"), ("anthropic", model_claude, "high")]`
  - 검증은 기존 `verifier`/`verifier_cross` 재사용.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_cli_role.py
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from pydantic import BaseModel
from cli_role import cli_complete, _build_claude_argv


class _Out(BaseModel):
    answer: str


_ENVELOPE = json.dumps({"type": "result", "is_error": False,
                        "result": "{\"answer\":\"ok\"}",
                        "structured_output": {"answer": "ok"}})


def test_parses_structured_output_field():
    async def runner(argv, stdin_text, timeout):
        return 0, _ENVELOPE, ""
    out = asyncio.run(cli_complete("claude-opus-4-8", "instr", "prompt",
                                   response_format=_Out, runner=runner))
    assert isinstance(out, _Out) and out.answer == "ok"


def test_falls_back_to_result_string():
    async def runner(argv, stdin_text, timeout):
        return 0, json.dumps({"is_error": False, "result": "{\"answer\":\"ok\"}"}), ""
    out = asyncio.run(cli_complete("m", "i", "p", response_format=_Out, runner=runner))
    assert out.answer == "ok"


def test_raises_on_nonzero_and_is_error():
    async def bad_rc(argv, s, t):
        return 1, "", "boom"
    with pytest.raises(Exception):
        asyncio.run(cli_complete("m", "i", "p", response_format=_Out, runner=bad_rc))
    async def err_env(argv, s, t):
        return 0, json.dumps({"is_error": True, "result": "refused"}), ""
    with pytest.raises(Exception):
        asyncio.run(cli_complete("m", "i", "p", response_format=_Out, runner=err_env))


def test_retries_parse_failure_once():
    state = []
    async def runner(argv, stdin_text, timeout):
        if not state:
            state.append(1)
            return 0, "not json", ""
        return 0, _ENVELOPE, ""
    out = asyncio.run(cli_complete("m", "i", "p", response_format=_Out, runner=runner))
    assert out.answer == "ok"


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


def test_role_falls_back_to_next_provider_when_cli_raises(monkeypatch):
    import providers as pv

    async def boom(*a, **k):
        raise RuntimeError("cli down")
    monkeypatch.setattr("cli_role.cli_complete", boom)
    monkeypatch.setattr(pv, "_capable", lambda p: True)

    class _Resp:
        value = None
        def __str__(self): return "api-answer"
        usage_details = {}

    class _Agent:
        async def run(self, prompt, options=None): return _Resp()

    class _Client:
        def as_agent(self, instructions=""): return _Agent()
    monkeypatch.setattr(pv, "_make_client", lambda p, m: _Client())
    role = pv.Role("x", overrides={"x": [("cli", "claude-opus-4-8", "high"),
                                         ("anthropic", "claude-opus-4-8", "high")]})
    out = asyncio.run(role.run("q"))
    assert out == "api-answer"                    # cli raise → 다음 체인으로 폴백
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: cli_role`)
- [ ] **Step 3: Write minimal implementation**

```python
# engine/cli_role.py
"""claude CLI 구조화 출력 실행기 — --tools ""(실측 유일 툴오프)·인라인 --json-schema·
세션 미영속·스크래치 cwd·프로세스그룹 타임아웃. 실패 raise → Role 폴백 체인이 이어받음."""
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
```

providers.py 수정 3곳:

```python
# (1) _capable — cli는 claude 바이너리 기준(cli_complete가 claude를 띄움)
import shutil

def _capable(provider: str) -> bool:
    if provider == "cli":
        return shutil.which("claude") is not None
    return settings.capabilities().get(provider, False)

# (2) Role.run 루프 — try: 최상단(self.provider 대입 직후)에 삽입.
#     run_prompt/_make_client 미참조(_make_client는 cli를 모름 → ValueError 남).
            try:
                self.provider, self.model = provider, model
                if provider == "cli":
                    from cli_role import cli_complete
                    cli_prompt = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
                    return await cli_complete(model, instr, cli_prompt,
                                              response_format=response_format,
                                              effort=effort or e)
                client = _make_client(provider, model)
                ...  # 기존 그대로 — cli raise는 기존 except가 잡아 다음 체인
```

```python
# (3) ROLE_MAP 추가(기존 dict 끝에)
    "report_filter": [("anthropic", settings.model_claude_sonnet, "low"),
                      ("openai", settings.model_gpt_mini, "low")],
    "report_deepen": [("cli", "claude-opus-4-8", "high"),
                      ("anthropic", settings.model_claude, "high")],
    "report_synth":  [("cli", "claude-opus-4-8", "high"),
                      ("anthropic", settings.model_claude, "high")],
```

- [ ] **Step 4: Run — expect PASS** (6 passed) + 전체 회귀 `.venv/bin/pytest -q` (providers 변경 무회귀)
- [ ] **Step 5: Commit**

```bash
git add engine/cli_role.py engine/providers.py engine/tests/test_cli_role.py
git commit -m "feat(cli): CliRole — 인라인 json-schema·--tools 오프·Role try 분기+폴백·report ROLE_MAP"
```

---

### Task 3: Phase 1 ingested_at 게이트 + now 필수화

**Files:** Modify `engine/sector/report_input.py` · Modify `engine/tests/test_report_input.py`(신규 테스트 + **기존 픽스처에 명시 ingested_at**)

**정책(스펙 v3):** `ingested_at` 파싱 가능 ∧ `> now` → 제외. **빈 값/불파싱 → 통과**(레거시 카드 1,038·관측 4,277 보호). 진단 `cards_ingested_unknown`/`raw_ingested_unknown` 카운트.

**주의(codex B4):** `store.append_cards`/`append_raw_news`가 실시계 `ingested_at`을 자동 스탬프(store.py:46/178) → **과거 now를 주입하는 기존 테스트들은 픽스처에 명시적 `ingested_at`(창 안)을 넣어야 통과 유지**. 기존 테스트 수정 대상: `test_assemble_window_is_deterministic_and_bounded`(카드 4개·raw 2개), `test_assemble_uses_injected_now_not_wall_clock`(카드 1개) — 각 항목에 `ingested_at=<해당 ts와 동일>` 추가.

- [ ] **Step 1: Write the failing test**

```python
# append engine/tests/test_report_input.py
def test_assemble_excludes_future_ingested_but_passes_legacy_empty(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([
        SectorCard(id="ok", ts="2026-07-21T15:00:00+00:00", axis="A", title="ok",
                   ingested_at="2026-07-21T15:05:00+00:00"),
        SectorCard(id="leak", ts="2026-07-21T15:00:00+00:00", axis="A", title="leak",
                   ingested_at="2026-07-21T23:00:00+00:00"),   # 미래 수집 → 제외
        SectorCard(id="legacy", ts="2026-07-21T15:00:00+00:00", axis="A", title="legacy",
                   ingested_at=""),                             # 레거시 빈 값 → 통과
    ])
    ri = assemble_report_input(s, window_hours=12, now=now, metrics=[])
    assert {c.id for c in ri.cards} == {"ok", "legacy"}
    assert ri.diagnostics.cards_ingested_unknown == 1           # legacy 카운트
```

주: store 자동 스탬프를 피하려고 세 카드 모두 명시 `ingested_at`. 빈 문자열은 store가 덮어쓸 수 있음 — 확인 후 덮어쓰면 index.jsonl 직접 기록으로 테스트 구성(Task 2의 test_sector_store 관례 참조).

- [ ] **Step 2: Run — expect FAIL** (leak 포함 + diagnostics 필드 없음)
- [ ] **Step 3: Write minimal implementation**

```python
# report_input.py — ReportInputDiagnostics에 필드 2개 추가
    cards_ingested_unknown: int = 0
    raw_ingested_unknown: int = 0

# assemble_report_input 내부, 창 필터 뒤:
def _ingested_gate(items, now):
    kept, dropped, unknown = [], 0, 0
    for it in items:
        raw = getattr(it, "ingested_at", "") or ""
        dt = _parse_ts(raw)
        if dt is None:
            unknown += 1        # 레거시/불파싱 → 통과(진단만)
            kept.append(it)
        elif dt <= now:
            kept.append(it)
        else:
            dropped += 1        # 미래 수집 → look-ahead 차단
    return kept, dropped, unknown

cards, c_ing_drop, c_unknown = _ingested_gate(cards, now)
raw_news, r_ing_drop, r_unknown = _ingested_gate(raw_news, now)
# c_ing_drop/r_ing_drop은 cards_dropped_future/raw_dropped_future에 합산,
# c_unknown/r_unknown은 diagnostics.cards_ingested_unknown/raw_ingested_unknown에.
# 시그니처: now: datetime  (기본값 제거 — 기존 호출자는 테스트 6곳뿐, 전부 now= 전달 중)
```

- [ ] **Step 4: Run — 신규 PASS + 기존 픽스처에 ingested_at 추가 후 전체 `tests/test_report_input.py -v` PASS**
- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_input.py engine/tests/test_report_input.py
git commit -m "feat(report): ingested_at look-ahead 게이트(레거시 빈값 통과) + now 필수화"
```

---

### Task 4: allowlist leaf + build_anchors

**Files:** Create `engine/sector/report_metrics_allowlist.py` · Create `engine/sector/report_anchors.py` · Modify `engine/sector/report_input.py`(re-export) · Test `engine/tests/test_report_anchors.py`

**Interfaces:**
- `report_metrics_allowlist.REPORT_METRICS: list[str]` — 상수 leaf(순환 import 불가). `report_input._REPORT_METRICS = REPORT_METRICS` **re-export 유지**(기존 테스트가 import — codex B5).
- `def build_anchors(store, *, now: datetime, metrics: list[str]|None=None) -> list[Anchor]` — **일 단위 cutoff**(`"2026-07"`→`"2026-07-01"` 정규화 후 `≤ now.date()`), `ingested_at` 게이트(파싱 가능∧>now 제외), **전량 읽기 후 컷**(`last_n=100_000` — 최신 400 슬라이스가 미래 행으로 히스토리를 밀어내는 버그 차단), 시리즈별 delta 코드 계산.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_anchors.py
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.store import SectorStore
from sector.contracts import MetricObservation
from sector.report_anchors import build_anchors


def _obs(ts, value, ing=""):
    return MetricObservation(metric="memory_price_usd_per_gb", ts=ts, value=value,
                             unit="$/GB", meta={"item": "DRAM"}, ingested_at=ing)


def test_delta_code_computed_and_day_precision_cutoff(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([_obs("2026-06", 3.0), _obs("2026-07", 3.5),
                           _obs("2026-07-31", 9.9)])       # 일 단위 미래 → 컷
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    anchors = build_anchors(s, now=now, metrics=["memory_price_usd_per_gb"])
    a = anchors[0]
    assert a.value == 3.5                                   # 7/31 관측이 아님(ts[:7] 비교 버그 방지)
    assert round(a.delta_pct, 1) == 16.7


def test_future_ingested_observation_excluded(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([_obs("2026-07", 3.5, ing="2026-07-01T00:00:00+00:00"),
                           _obs("2026-07", 8.8, ing="2026-07-20T00:00:00+00:00")])
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    anchors = build_anchors(s, now=now, metrics=["memory_price_usd_per_gb"])
    assert anchors and anchors[0].value == 3.5              # 7/20 수집분 look-ahead 차단


def test_allowlist_reexport_alive():
    from sector.report_input import _REPORT_METRICS
    from sector.report_metrics_allowlist import REPORT_METRICS
    assert _REPORT_METRICS is REPORT_METRICS
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Write minimal implementation**

```python
# engine/sector/report_metrics_allowlist.py — 상수만(leaf, 어디서든 import 안전)
REPORT_METRICS = [
    "memory_price_usd_per_gb", "kr_semi_production_index", "kr_semi_export",
    "memory_capex", "equip_revenue", "hyperscaler_capex", "ai_chip_revenue",
    "tw_monthly_revenue", "token_price", "openrouter_daily_tokens",
]
```

```python
# report_input.py — 기존 _REPORT_METRICS 정의를 교체(값 동일, 테스트 호환 re-export)
from sector.report_metrics_allowlist import REPORT_METRICS as _REPORT_METRICS
```

```python
# engine/sector/report_anchors.py
"""코드가 계산하는 typed 수치 anchor — cutoff(일 단위)·ingested_at 게이트·전량 읽기."""
from __future__ import annotations

from datetime import datetime, timezone

from sector.metrics_registry import METRIC_REGISTRY
from sector.report_contracts import Anchor
from sector.report_input import _parse_ts
from sector.report_metrics_allowlist import REPORT_METRICS


def _ts_date(ts: str) -> str:
    """'YYYY-MM' → 'YYYY-MM-01', 'YYYY-MM-DD' 그대로. 그 외 '' (제외)."""
    if len(ts) == 7:
        return ts + "-01"
    if len(ts) == 10:
        return ts
    return ""


def _group_key(meta: dict) -> str:
    for k in ("item", "model", "code", "token", "provider", "app", "country", "title"):
        if meta.get(k):
            return str(meta[k])
    return ""


def build_anchors(store, *, now: datetime, metrics: list[str] | None = None) -> list[Anchor]:
    names = metrics if metrics is not None else REPORT_METRICS
    cutoff = now.astimezone(timezone.utc).date().isoformat()
    out: list[Anchor] = []
    for m in names:
        info = METRIC_REGISTRY.get(m, {})
        try:
            rows = store.read_metric(m, last_n=100_000)     # 전량 → 슬라이스가 히스토리 안 밀어냄
        except Exception:  # noqa: BLE001
            continue
        ok = []
        for o in rows:
            d = _ts_date(o.ts)
            if not d or d > cutoff:                          # 일 단위 정밀 컷
                continue
            ing = _parse_ts(getattr(o, "ingested_at", "") or "")
            if ing is not None and ing > now:                # 수집시각 look-ahead 차단
                continue
            ok.append(o)
        groups: dict[str, list] = {}
        for o in ok:
            groups.setdefault(_group_key(o.meta), []).append(o)
        for gk, series in groups.items():
            series.sort(key=lambda o: _ts_date(o.ts))
            latest = series[-1]
            delta = None
            if len(series) >= 2 and series[-2].value:
                delta = (latest.value - series[-2].value) / abs(series[-2].value) * 100.0
            out.append(Anchor(anchor_id=f"{m}:{gk}", metric=m, entity=gk,
                              period=latest.ts, value=latest.value, unit=latest.unit,
                              delta_pct=delta, as_of=latest.ts,
                              source=info.get("label", m)))
    return out
```

- [ ] **Step 4: Run — expect PASS** + `tests/test_report_input.py -v` 회귀(re-export)
- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_metrics_allowlist.py engine/sector/report_anchors.py engine/sector/report_input.py engine/tests/test_report_anchors.py
git commit -m "feat(report): build_anchors — 일단위 cutoff·ingested 게이트·전량 읽기 + allowlist leaf"
```

---

### Task 5: playbook _score 추출 + rank_playbooks

**Files:** Modify `engine/stages/playbook.py` · Create `engine/sector/report_rules.py` · Test `engine/tests/test_report_rules.py`

**충실 추출(codex B6 — 실제 스코어링 규칙, playbook.py:100-118):** matchKeys/topics **set dedup** · topic은 `set(topics)-set(matchKeys)`(이중가산 금지) · 유비쿼터스 대형주 이름은 matchKey여도 **1점** · mk_hits 카운트. `match_playbook`은 추출 함수를 호출하는 래퍼로 리팩터(동작 보존 — 기존 `test_playbook_match.py` 22개 전부 통과 필수, 특히 유비쿼터스 테스트 :209).

**Interfaces:**
- playbook.py: `def _score(question: str, pb: dict) -> tuple[int, int, list[str]]` — (score, mk_hits, matched_keys). 기존 본문에서 그대로 추출.
- report_rules.py:
  - `def derive_topics(cluster: EventCluster, anchors: list[Anchor]) -> list[str]`
  - `def rank_playbooks(signal_text: str, playbooks: list[dict], *, allowed_conclusion_types: set[str], top_k: int = 5) -> list[dict]` — eligibility는 match_playbook과 동일(필수키·holdout_passed·conclusionType∈allowed·score≥2·mk_hits≥1), 정렬 `(-score, slug)`, slug dedup. **margin 규칙은 미적용**(단일 주입용 안전장치 — 다중 규칙 랭킹엔 해당 없음. 의도적 결정, 문서화).

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_rules.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_rules import rank_playbooks, derive_topics
from sector.report_contracts import EventCluster, EvidenceRef, Anchor


def _pb(slug, keys, topics, ctype="방향 판단", status="holdout_passed"):
    return {"slug": slug, "situation": slug, "triggers": [], "topics": topics,
            "conclusionType": ctype, "gates": [], "connection": "c",
            "status": status, "matchKeys": keys}


_ALLOWED = {"방향 판단", "종목 비교", "시점 판단", "리스크 점검"}


def test_rank_eligibility_and_order():
    pbs = [_pb("r-hbm", ["HBM 공급난"], ["메모리"]),
           _pb("r-two", ["HBM 공급난", "eSSD"], ["메모리"]),   # 2키 히트 → 더 높음
           _pb("r-topic-only", [], ["메모리"]),                # mk_hits 0 → 제외
           _pb("r-draft", ["HBM 공급난"], [], status="draft"),  # 미검증 → 제외
           _pb("r-type", ["HBM 공급난"], [], ctype="기타")]     # 타입 밖 → 제외
    text = "HBM 공급난 지속, eSSD 가격 상승, 메모리 업사이클"
    ranked = rank_playbooks(text, pbs, allowed_conclusion_types=_ALLOWED)
    assert [r["slug"] for r in ranked] == ["r-two", "r-hbm"]   # (-score, slug)
    assert ranked[0]["matched_keys"] == sorted(["HBM 공급난", "eSSD"])


def test_rank_dedups_matchkey_topic_double_count():
    # 같은 문자열이 matchKey이자 topic — 이중가산 금지(실제 스코어링 보존)
    pb = _pb("r-dup", ["HBM"], ["HBM"])
    ranked = rank_playbooks("HBM", [pb], allowed_conclusion_types=_ALLOWED)
    assert ranked and ranked[0]["score"] == 2                   # 2점(matchKey)만, 3점 아님


def test_derive_topics_includes_members_and_anchors():
    cl = EventCluster(cluster_id="c", title="MU 실적", axis="A",
                      members=[EvidenceRef(kind="news", id="n1", title="마이크론 서프라이즈")])
    a = Anchor(anchor_id="x:DRAM", metric="memory_price_usd_per_gb", entity="DRAM",
               value=3.5, as_of="2026-07")
    text = " ".join(derive_topics(cl, [a]))
    assert "마이크론" in text and "DRAM" in text and "MU 실적" in text
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Write minimal implementation**

playbook.py — 스코어링 본문(105-118행)을 함수로 추출, match_playbook은 호출로 교체:

```python
# engine/stages/playbook.py — match_playbook 위에 추가(본문 그대로 이동)
def _score(question: str, pb: dict) -> tuple[int, int, list[str]]:
    """(score, mk_hits, matched_keys). match_playbook과 rank_playbooks가 공유.
    규칙: set dedup · topic은 matchKeys 제외(이중가산 금지) · 유비쿼터스 이름 1점."""
    match_keys = [k for k in (pb.get("matchKeys") or []) if k]
    topics = [k for k in (pb.get("topics") or []) if k]
    match_key_set = set(match_keys)
    topic_only_set = set(topics) - match_key_set
    score = 0
    mk_hits = 0
    matched: list[str] = []
    for k in match_key_set:
        if k in question:
            mk_hits += 1
            matched.append(k)
            score += 1 if k in _UBIQUITOUS_NAMES else 2
    for k in topic_only_set:
        if k in question:
            score += 1
    return score, mk_hits, sorted(matched)

# match_playbook 내부 105-118행을 다음으로 교체(동작 동일):
        score, mk_hits, _ = _score(question, pb)
        scores.append((score, pb.get("slug", ""), pb, mk_hits))
```

```python
# engine/sector/report_rules.py
"""리포트용 다중 playbook 랭커 — match_playbook과 동일 eligibility·스코어링(_score 공유).
margin 규칙은 의도적으로 미적용: 단일 주입의 오매칭 안전장치라 다중 랭킹엔 해당 없음."""
from __future__ import annotations

from sector.report_contracts import Anchor, EventCluster
from stages.playbook import _REQUIRED_KEYS, _score


def derive_topics(cluster: EventCluster, anchors: list[Anchor]) -> list[str]:
    sig = [cluster.title, cluster.axis, *cluster.topics]
    sig += [m.title for m in cluster.members if m.title]
    for a in anchors:
        sig.append(a.metric)
        if a.entity:
            sig.append(a.entity)
    return [s for s in dict.fromkeys(sig) if s]


def rank_playbooks(signal_text: str, playbooks: list[dict], *,
                   allowed_conclusion_types: set[str], top_k: int = 5) -> list[dict]:
    scored = []
    for pb in sorted(playbooks, key=lambda p: p.get("slug", "") if isinstance(p, dict) else ""):
        if not isinstance(pb, dict) or not _REQUIRED_KEYS.issubset(pb.keys()):
            continue
        if pb.get("status") != "holdout_passed":
            continue
        if pb.get("conclusionType") not in allowed_conclusion_types:
            continue
        score, mk_hits, matched = _score(signal_text, pb)
        if score < 2 or mk_hits == 0:
            continue
        scored.append({"slug": pb["slug"], "situation": pb.get("situation", ""),
                       "connection": pb.get("connection", ""), "score": score,
                       "matched_keys": matched, "conclusionType": pb.get("conclusionType", "")})
    scored.sort(key=lambda r: (-r["score"], r["slug"]))
    seen, out = set(), []
    for r in scored:
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        out.append(r)
        if len(out) >= top_k:
            break
    return out
```

- [ ] **Step 4: Run — expect PASS** + **`tests/test_playbook_match.py -v` 전부 통과**(동작 보존 게이트, 유비쿼터스 :209 포함)
- [ ] **Step 5: Commit**

```bash
git add engine/stages/playbook.py engine/sector/report_rules.py engine/tests/test_report_rules.py
git commit -m "feat(report): playbook _score 추출(동작보존) + rank_playbooks 다중 랭커"
```

---

### Task 6: 필터 f1/f2/f3 (report_filters.py) — 3개 모두 테스트+코드

**Files:** Create `engine/sector/report_filters.py` · Test `engine/tests/test_report_filters.py`

**Interfaces (모두 async → `StageResult`, never-raise, `role.run(prompt, instructions=..., response_format=..., effort=...)` 주입):**
- `filter_relevance(raw_news, cards, *, role) -> StageResult` — output `list[EvidenceRef]`. **cards는 판정본이라 무조건 통과**(kind="card"로 변환·LLM 미경유, codex B7), raw_news만 40/배치 LLM. 중복 idx는 **첫 행 유지**. 배치 실패 fail-closed(해당 배치 drop+사유).
- `filter_importance(evidence, *, role) -> StageResult` — output `list[EvidenceRef]`. 40/배치, `{idx, impact, keep, reason}`.
- `cluster_events(evidence, *, role) -> StageResult` — output `list[EventCluster]`. **단일 글로벌 호출**(배치 분할하면 교차배치 중복이 못 묶임 — codex B7; f2 통과분은 수십 건 규모라 1콜 가능. 200건 캡+캡 시 note 기록). 실패 시 **1건=1클러스터 폴백**(fail-open 명시 — dedup만 잃고 재료는 보존).

- [ ] **Step 1: Write the failing tests**

```python
# engine/tests/test_report_filters.py
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import RawNewsDoc, SectorCard
from sector.report_contracts import EvidenceRef
from sector.report_filters import cluster_events, filter_importance, filter_relevance


class _RowsRole:
    def __init__(self, rows): self.rows = rows
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        return response_format(rows=self.rows)


class _RaiseRole:
    async def run(self, *a, **k): raise RuntimeError("llm down")


def test_f1_cards_pass_without_llm_and_news_filtered():
    raw = [RawNewsDoc(id="n1", title="MU HBM", created_at="2026-07-21T09:00:00+00:00"),
           RawNewsDoc(id="n2", title="날씨", created_at="2026-07-21T09:00:00+00:00")]
    cards = [SectorCard(id="c1", ts="2026-07-21T08:00:00+00:00", axis="A", title="카드")]
    role = _RowsRole([{"idx": 0, "relevant": True, "reason": "HBM"},
                      {"idx": 1, "relevant": False, "reason": "무관"},
                      {"idx": 0, "relevant": False, "reason": "중복행-무시"}])  # dup → 첫 행 유지
    res = asyncio.run(filter_relevance(raw, cards, role=role))
    ids = [e.id for e in res.output]
    assert "c1" in ids and "n1" in ids and "n2" not in ids     # 카드 무조건 통과
    assert res.output[0].kind == "card"                         # 카드 먼저, 안정 정렬
    assert res.io.in_count == 3 and res.io.out_count == 2
    assert any(d["reason"] == "무관" for d in res.io.dropped)


def test_f1_fail_closed_on_llm_error_but_cards_survive():
    raw = [RawNewsDoc(id="n1", title="x", created_at="2026-07-21T09:00:00+00:00")]
    cards = [SectorCard(id="c1", ts="2026-07-21T08:00:00+00:00", axis="A", title="카드")]
    res = asyncio.run(filter_relevance(raw, cards, role=_RaiseRole()))
    assert [e.id for e in res.output] == ["c1"]                # 뉴스만 fail-closed drop
    assert res.error is not None and res.io.dropped


def test_f2_keeps_by_impact():
    ev = [EvidenceRef(kind="news", id="n1", title="a"),
          EvidenceRef(kind="news", id="n2", title="b")]
    role = _RowsRole([{"idx": 0, "impact": "상", "keep": True, "reason": "임팩트"},
                      {"idx": 1, "impact": "하", "keep": False, "reason": "루틴"}])
    res = asyncio.run(filter_importance(ev, role=role))
    assert [e.id for e in res.output] == ["n1"]
    assert res.io.dropped[0]["reason"] == "루틴"


def test_f3_clusters_in_single_call_and_falls_open():
    ev = [EvidenceRef(kind="news", id="n1", title="아마존 $25B 조달 (로이터)"),
          EvidenceRef(kind="news", id="n2", title="Amazon debt financing (블룸버그)"),
          EvidenceRef(kind="news", id="n3", title="삼성 HBM4 인증")]

    class _ClusterRole:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            return response_format(clusters=[
                {"cluster_id": "e1", "title": "Amazon $25B 조달", "member_idxs": [0, 1],
                 "axis": "B", "direction": "pos"},
                {"cluster_id": "e2", "title": "삼성 HBM4 인증", "member_idxs": [2],
                 "axis": "A", "direction": "pos"}])
    res = asyncio.run(cluster_events(ev, role=_ClusterRole()))
    assert len(res.output) == 2
    assert [m.id for m in res.output[0].members] == ["n1", "n2"]   # 교차 중복이 한 클러스터로

    # LLM 실패 → 1건=1클러스터 fail-open(재료 보존)
    res2 = asyncio.run(cluster_events(ev, role=_RaiseRole()))
    assert len(res2.output) == 3 and res2.error is not None
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Write minimal implementation**

```python
# engine/sector/report_filters.py
"""f1 관련성(카드 무조건 통과) → f2 중요도 → f3 이벤트 클러스터(단일 콜).
전부 never-raise·StageResult. judge의 raise/80캡은 상속하지 않음(스펙 v3)."""
from __future__ import annotations

import time

from pydantic import BaseModel

from sector.report_contracts import EventCluster, EvidenceRef, StageIO, StageResult

_BATCH = 40
_CLUSTER_CAP = 200


class _RelRow(BaseModel):
    idx: int
    relevant: bool = False
    reason: str = ""


class _RelBatch(BaseModel):
    rows: list[_RelRow]


class _ImpRow(BaseModel):
    idx: int
    impact: str = "하"
    keep: bool = False
    reason: str = ""


class _ImpBatch(BaseModel):
    rows: list[_ImpRow]


class _ClusterRow(BaseModel):
    cluster_id: str
    title: str
    member_idxs: list[int] = []
    axis: str = "B"
    direction: str = "neutral"


class _ClusterOut(BaseModel):
    clusters: list[_ClusterRow]


def _news_ref(d) -> EvidenceRef:
    return EvidenceRef(kind="news", id=d.id, title=d.title,
                       ts=getattr(d, "created_at", ""), source=getattr(d, "source", ""),
                       url=getattr(d, "url", ""), excerpt=(getattr(d, "content", "") or "")[:280])


def _card_ref(c) -> EvidenceRef:
    return EvidenceRef(kind="card", id=c.id, title=c.title, ts=c.ts,
                       source=getattr(c, "source", ""), url=getattr(c, "url", ""),
                       excerpt=getattr(c, "interpreted_signal", "") or getattr(c, "raw_quote", ""))


def _first_by_idx(rows) -> dict:
    out: dict[int, object] = {}
    for r in rows:
        if r.idx not in out:                     # 중복 idx → 첫 행 유지(스펙)
            out[r.idx] = r
    return out


async def filter_relevance(raw_news, cards, *, role) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="f1", label="1차 필터 — 관련성",
                 in_count=len(raw_news) + len(cards))
    kept: list[EvidenceRef] = [_card_ref(c) for c in cards]    # 판정본 무조건 통과
    err = None
    for start in range(0, len(raw_news), _BATCH):
        batch = raw_news[start:start + _BATCH]
        prompt = "\n".join(f"{i}. {d.title}" for i, d in enumerate(batch))
        try:
            res = await role.run(prompt,
                                 instructions="메모리 반도체 밸류체인(수요·공급·가격·재고·AI수요·매크로 채널) 관련만 relevant=true.",
                                 response_format=_RelBatch, effort="low")
            rows = _first_by_idx(res.rows)
            for i, d in enumerate(batch):
                r = rows.get(i)
                if r is not None and r.relevant:
                    kept.append(_news_ref(d))
                else:
                    io.dropped.append({"title": d.title,
                                       "reason": (r.reason if r else "판정 누락") or "무관"})
        except Exception as exc:  # noqa: BLE001 — 배치 fail-closed
            err = str(exc)
            for d in batch:
                io.dropped.append({"title": d.title, "reason": f"llm 실패: {exc}"})
    io.out_count = len(kept)
    io.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return StageResult(output=kept, io=io, error=err)


async def filter_importance(evidence, *, role) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="f2", label="2차 필터 — 중요도", in_count=len(evidence))
    kept: list[EvidenceRef] = []
    err = None
    for start in range(0, len(evidence), _BATCH):
        batch = evidence[start:start + _BATCH]
        prompt = "\n".join(f"{i}. [{e.kind}] {e.title}" for i, e in enumerate(batch))
        try:
            res = await role.run(prompt,
                                 instructions="12시간 시황 판단에 임팩트 있는 항목만 keep=true. impact=상|중|하.",
                                 response_format=_ImpBatch, effort="low")
            rows = _first_by_idx(res.rows)
            for i, e in enumerate(batch):
                r = rows.get(i)
                if r is not None and r.keep:
                    kept.append(e)
                else:
                    io.dropped.append({"title": e.title,
                                       "reason": (r.reason if r else "판정 누락") or "임팩트 낮음"})
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            for e in batch:
                io.dropped.append({"title": e.title, "reason": f"llm 실패: {exc}"})
    io.out_count = len(kept)
    io.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return StageResult(output=kept, io=io, error=err)


async def cluster_events(evidence, *, role) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="f3", label="3차 필터 — 이벤트 dedup", in_count=len(evidence))
    items = evidence[:_CLUSTER_CAP]
    if len(evidence) > _CLUSTER_CAP:
        io.note = f"클러스터 입력 캡 {_CLUSTER_CAP}건(원 {len(evidence)}건) — 초과분 미클러스터"
    try:
        prompt = "\n".join(f"{i}. {e.title}" for i, e in enumerate(items))
        res = await role.run(prompt,
                             instructions="같은 사건을 다룬 항목들을 하나의 이벤트로 묶어라. 모든 idx는 정확히 한 클러스터에.",
                             response_format=_ClusterOut, effort="low")
        used: set[int] = set()
        clusters: list[EventCluster] = []
        for row in res.clusters:
            members = [items[i] for i in row.member_idxs
                       if 0 <= i < len(items) and i not in used]
            used.update(i for i in row.member_idxs if 0 <= i < len(items))
            if members:
                clusters.append(EventCluster(cluster_id=row.cluster_id, title=row.title,
                                             axis=row.axis, direction=row.direction,
                                             members=members))
        for i, e in enumerate(items):            # 누락 idx → 단독 클러스터(무성 누락 금지)
            if i not in used:
                clusters.append(EventCluster(cluster_id=f"solo-{e.id}", title=e.title,
                                             members=[e]))
        io.out_count = len(clusters)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=clusters, io=io, error=None)
    except Exception as exc:  # noqa: BLE001 — fail-open: 1건=1클러스터(재료 보존)
        clusters = [EventCluster(cluster_id=f"solo-{e.id}", title=e.title, members=[e])
                    for e in items]
        io.out_count = len(clusters)
        io.note = (io.note + " · " if io.note else "") + "클러스터 LLM 실패 → 1건=1클러스터"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=clusters, io=io, error=str(exc))
```

- [ ] **Step 4: Run — expect PASS** (5 passed)
- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_filters.py engine/tests/test_report_filters.py
git commit -m "feat(report): f1(카드 통과)+f2+f3(단일콜 클러스터·fail-open) — never-raise StageIO"
```

---

### Task 7: 심화 + 합성 (report_synthesis.py)

**Files:** Create `engine/sector/report_synthesis.py` · Test `engine/tests/test_report_synthesis.py`

**Interfaces:**
- `async def deepen(clusters, rules, anchors, *, role) -> StageResult` — output `str` 논증. rules/anchors를 프롬프트에 포함(미사용 금지 — codex B8).
- `async def synthesize_claims(deepen_text, clusters, anchors, rules, *, role) -> StageResult` — output `list[ReportClaim]`. LLM row는 `evidence_ids`/`anchor_refs`/`numeric_facts` **선언만**; 코드가 hydrate(실존 검증)·`claim_id="c{i}"` 부여·**`as_of`=evidence_refs의 max ts(코드 파생 — LLM 아님)**·표시 문자열 생성.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_synthesis.py
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import Anchor, EventCluster, EvidenceRef
from sector.report_synthesis import deepen, synthesize_claims


class _CliText:
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        assert "r-fx" in prompt and "usdkrw:krw" in prompt      # rules·anchors 실사용 확인
        return "논증 텍스트"


def test_deepen_includes_rules_and_anchors_in_prompt():
    cl = [EventCluster(cluster_id="c1", title="FX")]
    rules = [{"slug": "r-fx", "situation": "원화 급락", "connection": "환율→실적/수급 양가",
              "score": 4, "matched_keys": ["원/달러"], "conclusionType": "방향 판단"}]
    anchors = [Anchor(anchor_id="usdkrw:krw", metric="usdkrw", value=1450.0, as_of="2026-07-21")]
    res = asyncio.run(deepen(cl, rules, anchors, role=_CliText()))
    assert res.output == "논증 텍스트" and res.error is None


class _CliClaims:
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        return response_format(claims=[{
            "title": "환율發 수급 상충", "trigger": "원/달러 급등",
            "mechanism": "원화약세→실적↑ but 외국인 수급 양가", "confidence": "낮",
            "counter": "환율 되돌림 시 소멸", "stance": "수급 확인 우선",
            "load_bearing": True,
            "evidence_ids": ["n1", "made-up"],                 # 날조 1건 → drop
            "anchor_refs": ["usdkrw:krw", "ghost"],            # 실존만 유지
            "numeric_facts": [{"anchor_id": "usdkrw:krw", "value": 1450.0}],
            "matched_rules": ["r-fx"]}])


def test_synthesize_hydrates_ids_and_derives_as_of():
    ev = EvidenceRef(kind="news", id="n1", title="원/달러 급등", source="연합",
                     ts="2026-07-21T09:00:00+00:00")
    cl = [EventCluster(cluster_id="c1", title="FX", members=[ev])]
    anchors = [Anchor(anchor_id="usdkrw:krw", metric="usdkrw", value=1450.0, as_of="2026-07-21")]
    res = asyncio.run(synthesize_claims("논증", cl, anchors, [], role=_CliClaims()))
    c = res.output[0]
    assert c.claim_id == "c0" and c.status == "unverified"
    assert [e.id for e in c.evidence_refs] == ["n1"]            # 날조 drop
    assert c.evidence == ["원/달러 급등 (연합)"]                 # 표시 문자열
    assert c.anchor_refs == ["usdkrw:krw"]                      # 실존만
    assert c.numeric_facts[0].value == 1450.0
    assert c.as_of == "2026-07-21T09:00:00+00:00"               # 코드 파생(max member ts)
    assert any("made-up" in str(d) for d in res.io.dropped)
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Write minimal implementation**

```python
# engine/sector/report_synthesis.py
"""심화(규칙 대조 논증, CLI) + 합성(claims만 — 결론은 Task9 코드가).
LLM은 ID/수치 '선언'만, 코드가 hydrate·검증·as_of 파생(날조 차단, 스펙 v3)."""
from __future__ import annotations

import time

from pydantic import BaseModel

from sector.report_contracts import (
    Anchor, EventCluster, NumericFact, ReportClaim, StageIO, StageResult,
)


class _ClaimRow(BaseModel):
    title: str
    trigger: str = ""
    mechanism: str = ""
    confidence: str = "낮"
    counter: str = ""
    stance: str = ""
    load_bearing: bool = False
    evidence_ids: list[str] = []
    anchor_refs: list[str] = []
    numeric_facts: list[dict] = []      # {anchor_id, value}
    matched_rules: list[str] = []


class _ClaimsOut(BaseModel):
    claims: list[_ClaimRow]


def _fmt_anchor(a: Anchor) -> str:
    d = f" (Δ{a.delta_pct:+.1f}%)" if a.delta_pct is not None else ""
    return f"{a.anchor_id}: {a.value}{a.unit}{d} @{a.as_of} [{a.source}]"


def _fmt_rule(r: dict) -> str:
    return f"{r['slug']} (score {r['score']}, 키 {r['matched_keys']}): {r['connection']}"


async def deepen(clusters, rules, anchors, *, role) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="deepen", label="심화 — 규칙 대조", in_count=len(clusters))
    try:
        prompt = ("[관측 이벤트]\n" +
                  "\n".join(f"- {c.title} ({c.axis}/{c.direction}, 출처 {len(c.members)}건)"
                            for c in clusters) +
                  "\n\n[수치 anchor — 인용만, 산술 금지]\n" +
                  "\n".join(_fmt_anchor(a) for a in anchors) +
                  "\n\n[매칭 규칙 — 절차 참고용, 사실 인용 금지]\n" +
                  "\n".join(_fmt_rule(r) for r in rules) +
                  "\n\n나이브 단정 기각. 규칙에 비추어 여러 관측을 연결한 논증을 서술하라.")
        text = await role.run(prompt, instructions="메모리 반도체 시황 분석가.", effort="high")
        io.out_count = 1
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=str(text), io=io, error=None)
    except Exception as exc:  # noqa: BLE001
        io.note = f"심화 실패: {exc}"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output="", io=io, error=str(exc))


def _hydrate(ids: list[str], pool: dict, io: StageIO) -> list:
    out = []
    for i in ids:
        if i in pool:
            out.append(pool[i])
        else:
            io.dropped.append({"title": i, "reason": "미존재 evidence id(날조 의심)"})
    return out


async def synthesize_claims(deepen_text, clusters, anchors, rules, *, role) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="synth", label="합성 — 주장", in_count=len(clusters))
    try:
        pool = {m.id: m for c in clusters for m in c.members}
        anchor_ids = {a.anchor_id for a in anchors}
        prompt = (f"[논증]\n{deepen_text}\n\n[근거 id 풀]\n{sorted(pool)}\n"
                  f"[anchor id 풀]\n{sorted(anchor_ids)}\n\n"
                  "주장 카드만 생성(종합/최종의견 금지). 규칙 대조에서 나온 주장만. "
                  "evidence_ids/anchor_refs/numeric_facts는 반드시 위 풀의 id만.")
        res = await role.run(prompt, instructions="주장 합성기.",
                             response_format=_ClaimsOut, effort="high")
        claims: list[ReportClaim] = []
        for i, r in enumerate(res.claims):
            refs = _hydrate(r.evidence_ids, pool, io)
            nf = [NumericFact(**d) for d in r.numeric_facts
                  if isinstance(d, dict) and d.get("anchor_id") in anchor_ids]
            claims.append(ReportClaim(
                claim_id=f"c{i}", title=r.title, trigger=r.trigger, mechanism=r.mechanism,
                confidence=r.confidence if r.confidence in ("낮", "중", "높") else "낮",
                counter=r.counter, stance=r.stance, load_bearing=r.load_bearing,
                evidence_refs=refs,
                evidence=[f"{e.title} ({e.source})" if e.source else e.title for e in refs],
                anchor_refs=[a for a in r.anchor_refs if a in anchor_ids],
                numeric_facts=nf, matched_rules=r.matched_rules, status="unverified",
                as_of=max((e.ts for e in refs if e.ts), default="")))   # 코드 파생
        io.out_count = len(claims)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=claims, io=io, error=None)
    except Exception as exc:  # noqa: BLE001
        io.note = f"합성 실패: {exc}"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=[], io=io, error=str(exc))
```

- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_synthesis.py engine/tests/test_report_synthesis.py
git commit -m "feat(report): deepen(규칙·anchor 실사용)+synthesize(ID선언→코드 hydrate·as_of 파생)"
```

---

### Task 8: 검증 (report_verify.py) — 시점·숫자·A1·A2 전부

**Files:** Create `engine/sector/report_verify.py` · Test `engine/tests/test_report_verify.py`

**Interfaces:**
- `async def verify_claims(claims, anchors, *, cutoff, verifier, cross) -> StageResult` — output `list[ClaimVerdict]`.
- 게이트 순서(코드 먼저 — LLM 비용 절약·결정성):
  1. **시점(코드)**: `as_of` 파싱(`"YYYY-MM"`은 월초로) > cutoff → **rejected**. load_bearing인데 `as_of=""` → unverified+사유(게이트 우회 차단 — codex B9).
  2. **숫자(코드)**: 각 `numeric_facts`를 anchor_id로 조회, `|claimed-actual|/max(|actual|,1e-9) > 0.001` → **rejected**(정체성 대조 — 전역 근사 아님).
  3. **A1 재감사(verifier)**: load_bearing만. 프롬프트에 **evidence 표시줄+anchor 수치** 포함(제목만 금지 — codex B9). supported → verified, 아니면 unverified.
  4. **A2 반박(cross)**: A1 통과(verified) load_bearing만. 반증 발견 → unverified 강등+reason.
  - LLM 예외는 **fail-closed**(unverified+사유), 코드 게이트는 항상 실행.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_verify.py
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import Anchor, EvidenceRef, NumericFact, ReportClaim
from sector.report_verify import verify_claims

_CUT = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)


class _Yes:
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        return response_format(supported=True, reason="근거 충분")


class _No:
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        return response_format(supported=False, reason="반증 있음")


def _claim(**kw):
    base = dict(claim_id="c0", title="t", load_bearing=True,
                as_of="2026-07-21T09:00:00+00:00")
    base.update(kw)
    return ReportClaim(**base)


def _run(claims, anchors, verifier, cross):
    return asyncio.run(verify_claims(claims, anchors, cutoff=_CUT,
                                     verifier=verifier, cross=cross))


def test_lookahead_rejected_and_monthly_asof_parses():
    res = _run([_claim(as_of="2026-08-01T00:00:00+00:00"),
                _claim(claim_id="c1", as_of="2026-07")], [], _Yes(), _Yes())
    assert res.output[0].status == "rejected"                      # 미래 → 기각
    assert res.output[1].status == "verified"                      # 월 단위 파싱 OK


def test_missing_asof_on_load_bearing_is_unverified():
    res = _run([_claim(as_of="")], [], _Yes(), _Yes())
    v = res.output[0]
    assert v.status == "unverified" and any("as_of" in r for r in v.reasons)


def test_numeric_identity_mismatch_rejected():
    a = Anchor(anchor_id="fx:krw", metric="usdkrw", value=1450.0, as_of="2026-07-21")
    good = _claim(numeric_facts=[NumericFact(anchor_id="fx:krw", value=1450.0)])
    bad = _claim(claim_id="c1", numeric_facts=[NumericFact(anchor_id="fx:krw", value=1500.0)])
    res = _run([good, bad], [a], _Yes(), _Yes())
    assert res.output[0].status == "verified"
    assert res.output[1].status == "rejected"
    assert any("숫자" in r or "anchor" in r for r in res.output[1].reasons)


def test_a1_gets_evidence_and_anchors_in_prompt():
    seen = {}
    class _Spy:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            seen["p"] = prompt
            return response_format(supported=True, reason="ok")
    ev = EvidenceRef(kind="news", id="n1", title="원/달러 급등", source="연합")
    a = Anchor(anchor_id="fx:krw", metric="usdkrw", value=1450.0, as_of="2026-07-21")
    c = _claim(evidence=["원/달러 급등 (연합)"], evidence_refs=[ev],
               anchor_refs=["fx:krw"])
    _run([c], [a], _Spy(), _Yes())
    assert "원/달러 급등" in seen["p"] and "1450.0" in seen["p"]    # 근거·수치 실전달


def test_a2_refutation_downgrades_verified():
    res = _run([_claim()], [], _Yes(), _No())                       # A1 통과 → A2 반박
    v = res.output[0]
    assert v.status == "unverified" and any("반증" in r for r in v.reasons)


def test_llm_error_fail_closed():
    class _Boom:
        async def run(self, *a, **k): raise RuntimeError("down")
    res = _run([_claim()], [], _Boom(), _Yes())
    assert res.output[0].status == "unverified"                     # 예외 → 보수적
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Write minimal implementation**

```python
# engine/sector/report_verify.py
"""report 전용 검증 — 코드 게이트(시점·숫자 정체성) 먼저, 그 후 A1 재감사·A2 반박.
fail-closed: LLM 실패·근거 불충분이면 unverified. 스펙 v3."""
from __future__ import annotations

import time
from datetime import datetime

from pydantic import BaseModel

from sector.report_contracts import Anchor, ClaimVerdict, StageIO, StageResult
from sector.report_input import _parse_ts

_REL_TOL = 0.001


class _Support(BaseModel):
    supported: bool = False
    reason: str = ""


def _parse_asof(s: str):
    if len(s) == 7:                      # "YYYY-MM" → 월초(보수적)
        s = s + "-01T00:00:00+00:00"
    return _parse_ts(s)


def _evidence_block(c, anchors: dict) -> str:
    lines = [f"[주장] {c.title}", f"[논증] {c.mechanism}", "[근거]"]
    lines += [f"- {e}" for e in c.evidence]
    lines.append("[수치]")
    for ar in c.anchor_refs:
        a = anchors.get(ar)
        if a:
            lines.append(f"- {a.anchor_id} = {a.value}{a.unit} @{a.as_of}")
    return "\n".join(lines)


async def verify_claims(claims, anchors, *, cutoff: datetime, verifier, cross) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="verify", label="검증 — 시점/숫자/A1/A2", in_count=len(claims))
    amap = {a.anchor_id: a for a in anchors}
    verdicts: list[ClaimVerdict] = []

    for c in claims:
        reasons: list[str] = []
        # 1) 시점(코드)
        dt = _parse_asof(c.as_of) if c.as_of else None
        if c.as_of and dt is not None and dt > cutoff:
            verdicts.append(ClaimVerdict(claim_id=c.claim_id, status="rejected",
                                         reasons=[f"시점 위반: as_of {c.as_of} > cutoff"],
                                         adjusted_confidence="낮"))
            continue
        if c.load_bearing and (not c.as_of or dt is None):
            reasons.append("as_of 없음/불파싱 — 시점 게이트 미통과(보수)")
        # 2) 숫자 정체성(코드)
        numeric_bad = False
        for nf in c.numeric_facts:
            a = amap.get(nf.anchor_id)
            if a is None:
                reasons.append(f"숫자 anchor 미존재: {nf.anchor_id}")
                numeric_bad = True
            elif abs(nf.value - a.value) / max(abs(a.value), 1e-9) > _REL_TOL:
                reasons.append(f"숫자 불일치: {nf.anchor_id} 주장 {nf.value} ≠ anchor {a.value}")
                numeric_bad = True
        if numeric_bad:
            verdicts.append(ClaimVerdict(claim_id=c.claim_id, status="rejected",
                                         reasons=reasons, adjusted_confidence="낮"))
            continue
        # 3) A1 재감사(load-bearing만, 근거·수치 실전달)
        status, conf = c.status, c.confidence
        if c.load_bearing and not reasons:
            try:
                r = await verifier.run(
                    "중립 재판정: 아래 주장이 제시 근거·수치로 지지되는가.\n\n"
                    + _evidence_block(c, amap),
                    response_format=_Support, effort="medium")
                if r.supported:
                    status = "verified"
                else:
                    reasons.append(f"A1 근거부족: {r.reason}")
                    status, conf = "unverified", "낮"
            except Exception as exc:  # noqa: BLE001 — fail-closed
                reasons.append(f"A1 실패(보수): {exc}")
                status = "unverified"
        elif reasons:
            status = "unverified"
        # 4) A2 반박(verified만)
        if status == "verified":
            try:
                r2 = await cross.run(
                    "다음 주장을 반박할 근거를 찾아라. 발견 시 supported=false.\n\n"
                    + _evidence_block(c, amap),
                    response_format=_Support, effort="medium")
                if not r2.supported:
                    reasons.append(f"A2 반증: {r2.reason}")
                    status, conf = "unverified", "낮"
            except Exception as exc:  # noqa: BLE001
                reasons.append(f"A2 실패(유지): {exc}")   # 반박 실패는 verified 유지(감사는 이미 통과)
        verdicts.append(ClaimVerdict(claim_id=c.claim_id, status=status,
                                     reasons=reasons, adjusted_confidence=conf))

    io.out_count = len(verdicts)
    io.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return StageResult(output=verdicts, io=io, error=None)
```

- [ ] **Step 4: Run — expect PASS** (7 passed)
- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_verify.py engine/tests/test_report_verify.py
git commit -m "feat(report): verify — 시점(월파싱)·숫자 정체성·A1 근거전달·A2 반박, fail-closed"
```

---

### Task 9: 결론 조립 (report_assemble.py)

**Files:** Create `engine/sector/report_assemble.py` · Test `engine/tests/test_report_assemble.py`

**Interfaces:**
- `def assemble_report(claims, verdicts, *, stages: list[PipelineStage], now: datetime, window_hours: int, seq: int, title: str, stage_errors: list[str], seams_empty: list[str]) -> Report`
- verdict를 `claim_id`로 매핑(인덱스 아님). 3분류: rejected→claims[] 제외+`diagnostics.rejected_claims` / unverified→claims[] 유지·결론 미반영 / **verified→결론**. overview·finalOpinion.text=verified만 코드 조인(LLM 없음). confidence=verified 최소, **verified 0건이면 "낮" 고정**(all-unverified가 "높" 되는 버그 차단 — codex B10). `window`는 `window_hours` 사용(12 하드코딩 금지).

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_assemble.py
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import ClaimVerdict, EvidenceRef, ReportClaim
from sector.report_assemble import assemble_report

_NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _mk(cid, title, **kw):
    return ReportClaim(claim_id=cid, title=title, **kw)


def test_three_way_split_and_verified_only_conclusion():
    claims = [_mk("c0", "검증됨", stance="수급 확인 우선"),
              _mk("c1", "미검증"), _mk("c2", "기각됨")]
    verdicts = [ClaimVerdict(claim_id="c0", status="verified", adjusted_confidence="중"),
                ClaimVerdict(claim_id="c1", status="unverified", adjusted_confidence="낮"),
                ClaimVerdict(claim_id="c2", status="rejected", adjusted_confidence="낮")]
    r = assemble_report(claims, verdicts, stages=[], now=_NOW, window_hours=12,
                        seq=2, title="t", stage_errors=[], seams_empty=["case_memory"])
    assert {c.title for c in r.claims} == {"검증됨", "미검증"}      # rejected 제외
    assert r.diagnostics["rejected_claims"] == ["기각됨"]
    assert "검증됨" in r.overview and "미검증" not in r.overview     # 결론=verified만
    assert r.finalOpinion.text == "수급 확인 우선"
    assert r.finalOpinion.confidence == "중"


def test_no_verdict_claim_stays_unverified_out_of_conclusion():
    claims = [_mk("c0", "판정누락", confidence="높")]
    r = assemble_report(claims, [], stages=[], now=_NOW, window_hours=12,
                        seq=1, title="t", stage_errors=[], seams_empty=[])
    assert r.claims[0].status == "unverified"
    assert "판정누락" not in r.overview                              # 누락도 결론 미반영
    assert r.finalOpinion.confidence == "낮"                         # verified 0 → 낮 고정


def test_window_hours_and_diagnostics_fields():
    r = assemble_report([], [], stages=[], now=_NOW, window_hours=6,
                        seq=1, title="t", stage_errors=["f1: llm down"], seams_empty=["x"])
    assert r.window["from"].startswith("2026-07-21T15:00")           # KST 21:00−6h
    assert r.diagnostics["stage_errors"] == ["f1: llm down"]
    assert r.diagnostics["seams_empty"] == ["x"]
    assert r.id == "2026-07-21-1"                                    # KST 날짜
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Write minimal implementation**

```python
# engine/sector/report_assemble.py
"""검증 후 결론 조립 — 결론은 verified만, 코드가 결정적으로. LLM 재합성 금지(스펙 v3)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sector.report_contracts import (
    FinalOpinion, PipelineStage, Report, ReportPipeline,
)

_KST = timezone(timedelta(hours=9))
_RANK = {"낮": 0, "중": 1, "높": 2}
_INV = {v: k for k, v in _RANK.items()}


def assemble_report(claims, verdicts, *, stages, now, window_hours, seq, title,
                    stage_errors, seams_empty) -> Report:
    vmap = {v.claim_id: v for v in verdicts}
    for c in claims:
        v = vmap.get(c.claim_id)
        if v is not None:
            c.status = v.status
            c.confidence = v.adjusted_confidence
        else:
            c.status = "unverified"                 # 판정 누락 → 보수적(결론 미반영)
    rejected = [c for c in claims if c.status == "rejected"]
    kept = [c for c in claims if c.status != "rejected"]
    verified = [c for c in kept if c.status == "verified"]

    if verified:
        overview = " · ".join(c.title for c in verified)
        fo_text = next((c.stance for c in verified if c.stance), verified[0].title)
        conf = _INV[min(_RANK.get(c.confidence, 0) for c in verified)]
    else:
        overview = "검증된 주장 없음 — 판단 보류."
        fo_text, conf = "관망", "낮"                 # verified 0 → 낮 고정

    kst = now.astimezone(_KST)
    return Report(
        id=f"{kst.strftime('%Y-%m-%d')}-{seq}", seq=seq,
        generatedAt=kst.isoformat(), title=title,
        window={"from": (now - timedelta(hours=window_hours)).astimezone(_KST).isoformat(),
                "to": kst.isoformat()},
        overview=overview,
        finalOpinion=FinalOpinion(text=fo_text, confidence=conf),
        claims=kept,
        pipeline=ReportPipeline(stages=list(stages)),
        diagnostics={"seams_empty": list(seams_empty),
                     "stage_errors": list(stage_errors),
                     "rejected_claims": [c.title for c in rejected]})
```

- [ ] **Step 4: Run — expect PASS** (3 passed)
- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_assemble.py engine/tests/test_report_assemble.py
git commit -m "feat(report): assemble — claim_id 매핑·verified-only 결론·낮 고정·window_hours"
```

---

### Task 10: 오케스트레이션 + 영속화 + main (report_pipeline.py)

**Files:** Create `engine/sector/report_pipeline.py` · Modify `AGENTS.md` · Test `engine/tests/test_report_pipeline.py`

**Interfaces:**
- `def alloc_report_slot(root: Path, date_str: str) -> tuple[int, Path]` — `reports/` 아래 `os.open(O_CREAT|O_EXCL)` 빈 파일 예약, 충돌 시 seq+1.
- `async def run_report_pipeline(store, *, now: datetime, window_hours: int = 12, seq: int, playbook_corpus: str = "ryze_yn", roles: dict | None = None) -> Report` — **순수**(저장 안 함). roles 주입(테스트)·기본은 Role/ROLE_MAP. 전 스테이지 `.output` 언랩·StageIO→PipelineStage(items는 문자열)·error 수집.
- `def save_report(report: Report, path: Path) -> Path` — **예약 경로 필수**: `path`가 존재하지 않으면 `ValueError`(예약 없이 덮어쓰기 차단 — codex SF5). temp에 쓰고 `os.replace(path)`.
- `def main(argv: list[str]) -> int` — ① alloc ② run(seq 주입) ③ save(예약 경로).

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_pipeline.py
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sector.report_contracts import FinalOpinion, Report, ReportPipeline
from sector.report_pipeline import alloc_report_slot, save_report


def _rep(rid, seq):
    return Report(id=rid, seq=seq, generatedAt="x", title="t",
                  window={"from": "a", "to": "b"},
                  finalOpinion=FinalOpinion(text="hold", confidence="낮"),
                  pipeline=ReportPipeline(stages=[]), diagnostics={})


def test_alloc_reserves_and_increments(tmp_path):
    s1, p1 = alloc_report_slot(tmp_path, "2026-07-21")
    s2, p2 = alloc_report_slot(tmp_path, "2026-07-21")
    assert (s1, s2) == (1, 2) and p1 != p2
    assert p1.exists() and p1.parent.name == "reports"       # flat 예약 파일


def test_save_requires_reservation(tmp_path):
    seq, path = alloc_report_slot(tmp_path, "2026-07-21")
    out = save_report(_rep("2026-07-21-1", seq), path)
    assert json.loads(out.read_text())["finalOpinion"]["confidence"] == "낮"
    ghost = tmp_path / "reports" / "2026-07-21-9.json"        # 예약 안 된 경로
    with pytest.raises(ValueError):
        save_report(_rep("2026-07-21-9", 9), ghost)


def test_pipeline_end_to_end_with_fake_roles(tmp_path):
    from sector.store import SectorStore
    from sector.contracts import SectorCard
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([SectorCard(id="c1", ts="2026-07-21T15:00:00+00:00", axis="A",
                               title="SOX 강세", ingested_at="2026-07-21T15:05:00+00:00")])

    class _Rows:
        def __init__(self, key): self.key = key
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            name = response_format.__name__
            if name == "_ImpBatch":
                return response_format(rows=[{"idx": 0, "impact": "상", "keep": True,
                                              "reason": "임팩트"}])
            if name == "_ClusterOut":
                return response_format(clusters=[{"cluster_id": "e1", "title": "SOX 강세",
                                                  "member_idxs": [0]}])
            if name == "_ClaimsOut":
                return response_format(claims=[{
                    "title": "지수 훈풍", "stance": "보유", "load_bearing": True,
                    "confidence": "중", "evidence_ids": ["c1"], "matched_rules": []}])
            if name == "_Support":
                return response_format(supported=True, reason="ok")
            return "논증"                                        # deepen 텍스트

    roles = {k: _Rows(k) for k in
             ("filter", "importance", "cluster", "deepen", "synth", "verifier", "cross")}
    from sector.report_pipeline import run_report_pipeline
    rep = asyncio.run(run_report_pipeline(s, now=now, seq=1, roles=roles))
    assert rep.id == "2026-07-22-1"                            # KST(21:00Z=익일 06:00 KST)
    assert [st.key for st in rep.pipeline.stages] == \
        ["raw", "f1", "f2", "f3", "deepen", "synth", "verify"]
    assert rep.claims and rep.claims[0].status == "verified"
    assert "지수 훈풍" in rep.overview
    assert all(isinstance(i, str) for st in rep.pipeline.stages for i in st.items)
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Write minimal implementation** (전 스테이지 실배선 — 생략 없음)

```python
# engine/sector/report_pipeline.py
"""오케스트레이션(순수) + 영속화(예약 필수) + CLI 엔트리포인트.
싱글턴 시스템 리포트 — AGENTS.md '시스템 리포트 예외' 참조. 스펙 v3."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sector.report_anchors import build_anchors
from sector.report_assemble import assemble_report
from sector.report_contracts import PipelineStage, Report
from sector.report_filters import cluster_events, filter_importance, filter_relevance
from sector.report_input import _to_utc, assemble_report_input
from sector.report_rules import derive_topics, rank_playbooks
from sector.report_synthesis import deepen, synthesize_claims
from sector.report_verify import verify_claims

_ROOT = Path(__file__).resolve().parents[2] / "storage" / "rag" / "memory_sector"
_ALLOWED_TYPES = {"방향 판단", "종목 비교", "시점 판단", "리스크 점검"}
_SEAMS = ["price_reaction", "analyst_reports", "case_memory"]


def alloc_report_slot(root: Path, date_str: str) -> tuple[int, Path]:
    d = root / "reports"
    d.mkdir(parents=True, exist_ok=True)
    seq = 1
    while True:
        p = d / f"{date_str}-{seq}.json"
        try:
            os.close(os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            return seq, p
        except FileExistsError:
            seq += 1


def save_report(report: Report, path: Path) -> Path:
    if not path.exists():
        raise ValueError(f"예약되지 않은 경로: {path} — alloc_report_slot 먼저")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)                                     # 예약 파일 위 원자 교체
    return path


def _stage(io, items: list[str]) -> PipelineStage:
    return PipelineStage(key=io.key, label=io.label, note=io.note,
                         items=items[:20], io=io.model_dump())


def _default_roles(overrides=None):
    from providers import Role
    fil = Role("report_filter", overrides)
    return {"filter": fil, "importance": fil, "cluster": fil,
            "deepen": Role("report_deepen", overrides),
            "synth": Role("report_synth", overrides),
            "verifier": Role("verifier", overrides),
            "cross": Role("verifier_cross", overrides)}


async def run_report_pipeline(store, *, now: datetime, window_hours: int = 12,
                              seq: int, playbook_corpus: str = "ryze_yn",
                              roles: dict | None = None) -> Report:
    roles = roles or _default_roles()
    eff = _to_utc(now)
    errors: list[str] = []
    stages: list[PipelineStage] = []

    ri = assemble_report_input(store, window_hours=window_hours, now=eff)
    anchors = build_anchors(store, now=eff)
    stages.append(PipelineStage(
        key="raw", label="raw",
        sources=[{"name": "SectorCard", "items": [c.title for c in ri.cards[:10]]},
                 {"name": "SaveTicker raw", "items": [d.title for d in ri.raw_news[:10]]},
                 {"name": "anchors", "items": [f"{a.anchor_id}={a.value}{a.unit}"
                                               for a in anchors[:10]]}],
        io=ri.diagnostics.model_dump()))

    f1 = await filter_relevance(ri.raw_news, ri.cards, role=roles["filter"])
    if f1.error:
        errors.append(f"f1: {f1.error}")
    stages.append(_stage(f1.io, [e.title for e in f1.output]))

    f2 = await filter_importance(f1.output, role=roles["importance"])
    if f2.error:
        errors.append(f"f2: {f2.error}")
    stages.append(_stage(f2.io, [e.title for e in f2.output]))

    f3 = await cluster_events(f2.output, role=roles["cluster"])
    if f3.error:
        errors.append(f"f3: {f3.error}")
    stages.append(_stage(f3.io, [c.title for c in f3.output]))
    clusters = f3.output

    try:
        from stages.playbook import load_playbooks
        pbs = load_playbooks(playbook_corpus)
    except Exception as exc:  # noqa: BLE001 — never-raise
        pbs = []
        errors.append(f"playbook: {exc}")
    signal_text = " ".join(t for c in clusters for t in derive_topics(c, anchors))
    rules = rank_playbooks(signal_text, pbs, allowed_conclusion_types=_ALLOWED_TYPES)

    dp = await deepen(clusters, rules, anchors, role=roles["deepen"])
    if dp.error:
        errors.append(f"deepen: {dp.error}")
    stages.append(_stage(dp.io, [r["slug"] for r in rules]))

    sy = await synthesize_claims(dp.output, clusters, anchors, rules, role=roles["synth"])
    if sy.error:
        errors.append(f"synth: {sy.error}")
    stages.append(_stage(sy.io, [c.title for c in sy.output]))

    vf = await verify_claims(sy.output, anchors, cutoff=eff,
                             verifier=roles["verifier"], cross=roles["cross"])
    if vf.error:
        errors.append(f"verify: {vf.error}")
    stages.append(_stage(vf.io, [f"{v.claim_id}:{v.status}" for v in vf.output]))

    return assemble_report(sy.output, vf.output, stages=stages, now=eff,
                           window_hours=window_hours, seq=seq,
                           title="메모리 반도체 12시간 시황",
                           stage_errors=errors, seams_empty=_SEAMS)


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--now")
    ap.add_argument("--window", type=int, default=12)
    ap.add_argument("--root", default=str(_ROOT))
    args = ap.parse_args(argv)
    now = (datetime.fromisoformat(args.now) if args.now
           else datetime.now(timezone.utc))
    now = _to_utc(now)
    root = Path(args.root)
    from datetime import timedelta
    kst_date = now.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    seq, path = alloc_report_slot(root, kst_date)              # ① 예약
    from sector.store import SectorStore
    store = SectorStore(root)
    report = asyncio.run(run_report_pipeline(store, now=now,
                                             window_hours=args.window, seq=seq))  # ② 실행
    save_report(report, path)                                  # ③ 예약 경로에 저장
    print(report.id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

AGENTS.md — User Storage Rule 절 끝에 1줄 추가(codex r2-P8):

```markdown
Exception: singleton system reports (`storage/rag/memory_sector/reports/`) are
market data generated from public sources, not user analysis — global storage
and the public read-only routes are intentional.
```

- [ ] **Step 4: Run — expect PASS** (3 passed) + 전체 회귀 `.venv/bin/pytest -q`
- [ ] **Step 5: Commit**

```bash
git add engine/sector/report_pipeline.py engine/tests/test_report_pipeline.py AGENTS.md
git commit -m "feat(report): run_report_pipeline 전 스테이지 배선 + 예약制 저장 + main"
```

---

### Task 11: OpenAPI 계약 + 서버 통합 테스트

**Files:** Modify `openapi.yaml` · Create `test/contract/market-report.contract.test.mjs`

- [ ] **Step 1: Write the failing test** (실핸들러 왕복 — test/helpers/test-server.mjs 사용)

```javascript
// test/contract/market-report.contract.test.mjs
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

import { createTestRoot, requestJson, startTestServer } from "../helpers/test-server.mjs";

const REPORT = {
  id: "2026-07-21-1", seq: 1, generatedAt: "2026-07-21T09:00:00+09:00",
  title: "t", window: { from: "a", to: "b" },
  overview: "o", finalOpinion: { text: "hold", confidence: "낮" },
  claims: [{ claim_id: "c0", title: "claim", confidence: "중", status: "verified",
             evidence: ["SOX +1.8% (reuters)"], evidence_refs: [], anchor_refs: [],
             numeric_facts: [], matched_rules: [], load_bearing: true }],
  pipeline: { stages: [{ key: "f1", label: "1차", items: ["a"] }] },
  diagnostics: { seams_empty: [], stage_errors: [], rejected_claims: [] },
};

test("market report round-trips through real list/detail handlers", async (t) => {
  const root = await createTestRoot();
  const dir = join(root, "storage", "rag", "memory_sector", "reports");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, `${REPORT.id}.json`), JSON.stringify(REPORT));
  const app = await startTestServer({ root });
  t.after(() => app.stop({ removeRoot: true }));

  const list = await requestJson(app.url, "/api/market-reports");
  assert.equal(list.status, 200);
  const meta = list.body.reports.find((r) => r.id === REPORT.id);
  assert.ok(meta, "saved report appears in list");
  assert.equal(meta.claimCount, 1);

  const detail = await requestJson(app.url, `/api/market-reports/${REPORT.id}`);
  assert.equal(detail.status, 200);
  assert.equal(detail.body.report.finalOpinion.confidence, "낮");
  assert.ok(Array.isArray(detail.body.report.pipeline.stages));
  assert.ok(detail.body.report.claims.every(
    (c) => c.evidence.every((e) => typeof e === "string")));   // 뷰어 안전
});
```

주: `startTestServer`/`requestJson` 시그니처는 `test/api/server.behavior.test.mjs` 관례를 따른다(마켓리포트 dir이 root 하위가 아니면 helpers에 root 주입 경로 확인 후 맞춤).

- [ ] **Step 2: Run — expect FAIL 확인** `node --test test/contract/market-report.contract.test.mjs` (dir 미주입/스키마 없음 등 실제 사유 확인)
- [ ] **Step 3: 통과 구현** — helpers가 marketReportsDir을 root 기준으로 못 잡으면 server.mjs의 dir 해석을 root 기준으로 정렬. openapi.yaml `/api/market-reports/{id}` 응답을 명시 스키마로 교체:

```yaml
# openapi.yaml components.schemas 에 추가
    MarketReportClaim:
      type: object
      required: [claim_id, title, confidence, status]
      properties:
        claim_id: { type: string }
        title: { type: string }
        confidence: { type: string, enum: [낮, 중, 높] }
        status: { type: string, enum: [verified, unverified] }
        trigger: { type: string }
        mechanism: { type: string }
        evidence: { type: array, items: { type: string } }
        evidence_refs: { type: array, items: { type: object } }
        anchor_refs: { type: array, items: { type: string } }
        numeric_facts: { type: array, items: { type: object } }
        precedent: { type: string }
        precedent_grounded: { type: boolean }
        counter: { type: string }
        stance: { type: string }
        matched_rules: { type: array, items: { type: string } }
        load_bearing: { type: boolean }
        as_of: { type: string }
    MarketReport:
      type: object
      required: [id, seq, generatedAt, title, window, finalOpinion, claims, pipeline]
      properties:
        id: { type: string }
        seq: { type: integer }
        generatedAt: { type: string }
        title: { type: string }
        window: { type: object }
        overview: { type: string }
        finalOpinion:
          type: object
          required: [text, confidence]
          properties:
            text: { type: string }
            confidence: { type: string, enum: [낮, 중, 높] }
        claims: { type: array, items: { $ref: "#/components/schemas/MarketReportClaim" } }
        pipeline:
          type: object
          properties:
            stages: { type: array, items: { type: object } }
        diagnostics: { type: object }
# 기존 /api/market-reports/{id} 응답의 report: {type: object, additionalProperties: true}
# → report: { $ref: "#/components/schemas/MarketReport" } 로 교체
```

- [ ] **Step 4: PASS 확인** `node --test test/contract/market-report.contract.test.mjs` + `python3 scripts/validate_openapi.py`(구조·$ref 검증) + 기존 `npm test` 회귀
- [ ] **Step 5: Commit**

```bash
git add openapi.yaml test/contract/market-report.contract.test.mjs server.mjs
git commit -m "feat(report): OpenAPI MarketReport 스키마 + 실핸들러 왕복 계약 테스트"
```

---

### Task 12: 골든 end-to-end (replay)

**Files:** Create `engine/tests/test_report_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_report_e2e.py — 캡처 role 출력 replay: 같은 입력+같은 role 출력 → 같은 결과
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import RawNewsDoc, SectorCard
from sector.store import SectorStore
from sector.report_pipeline import run_report_pipeline

_NOW = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)


def _seed(tmp_path):
    s = SectorStore(tmp_path)
    s.append_cards([SectorCard(id="c1", ts="2026-07-21T15:00:00+00:00", axis="market",
                               title="美 반도체주 강세", ingested_at="2026-07-21T15:05:00+00:00")])
    s.append_raw_news([
        RawNewsDoc(id="n1", title="원/달러 급등", created_at="2026-07-21T16:00:00+00:00",
                   ingested_at="2026-07-21T16:05:00+00:00"),
        RawNewsDoc(id="n2", title="연예 뉴스", created_at="2026-07-21T16:00:00+00:00",
                   ingested_at="2026-07-21T16:05:00+00:00")])
    return s


class _Replay:
    """캡처된 role 출력 — 결정성 replay의 '고정 LLM'."""
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        name = getattr(response_format, "__name__", "")
        if name == "_RelBatch":
            return response_format(rows=[{"idx": 0, "relevant": True, "reason": "환율"},
                                         {"idx": 1, "relevant": False, "reason": "무관"}])
        if name == "_ImpBatch":
            return response_format(rows=[{"idx": i, "impact": "상", "keep": True,
                                          "reason": "임팩트"} for i in range(2)])
        if name == "_ClusterOut":
            return response_format(clusters=[{"cluster_id": "e1", "title": "환율+지수",
                                              "member_idxs": [0, 1]}])
        if name == "_ClaimsOut":
            return response_format(claims=[{
                "title": "환율發 수급 상충", "stance": "수급 확인 우선",
                "load_bearing": True, "confidence": "중",
                "evidence_ids": ["c1", "n1"], "matched_rules": []}])
        if name == "_Support":
            return response_format(supported=True, reason="ok")
        return "논증 replay"


def _run(store):
    roles = {k: _Replay() for k in
             ("filter", "importance", "cluster", "deepen", "synth", "verifier", "cross")}
    return asyncio.run(run_report_pipeline(store, now=_NOW, seq=1, roles=roles))


def test_replay_is_deterministic_and_viewer_shaped(tmp_path):
    s = _seed(tmp_path)
    r1, r2 = _run(s), _run(s)
    d1, d2 = r1.model_dump(), r2.model_dump()
    for d in (d1, d2):                       # 타이밍 필드 정규화(골든 동등성 제외)
        for st in d["pipeline"]["stages"]:
            if st.get("io"):
                st["io"].pop("elapsed_ms", None)
    assert d1 == d2                          # replay 결정성

    # 뷰어 스키마 형태
    assert [st["key"] for st in d1["pipeline"]["stages"]] == \
        ["raw", "f1", "f2", "f3", "deepen", "synth", "verify"]
    assert d1["claims"][0]["status"] == "verified"
    assert d1["claims"][0]["evidence"] == ["美 반도체주 강세", "원/달러 급등"]
    assert d1["finalOpinion"]["text"] == "수급 확인 우선"
    assert "환율發 수급 상충" in d1["overview"]
    assert d1["diagnostics"]["seams_empty"] == \
        ["price_reaction", "analyst_reports", "case_memory"]
    # f1이 무관 뉴스를 실제로 걸렀는지(드롭 사유 기록)
    f1 = next(st for st in d1["pipeline"]["stages"] if st["key"] == "f1")
    assert any(dd["reason"] == "무관" for dd in f1["io"]["dropped"])
```

- [ ] **Step 2: Run — expect FAIL → Step 3: (파이프라인 버그 있으면 수정) → Step 4: PASS + 전체 회귀 `.venv/bin/pytest -q`**
- [ ] **Step 5: Commit**

```bash
git add engine/tests/test_report_e2e.py
git commit -m "test(report): 골든 e2e replay — 결정성·뷰어 스키마·드롭 사유"
```

**라이브 스모크(게이트 밖, ship 체크리스트):** 실제 store로 `cd engine && .venv/bin/python -m sector.report_pipeline` 1회 → 뷰어 로그인 → 리포트 탭 스크린샷 확인(`verify-ui-with-screenshots`) + `update-workflow-review-after-ship` 수행.

---

## Self-Review (v2)

- **codex 계획 리뷰 12 BLOCKER 대응**: B1(인라인 스키마·--tools·cwd·structured_output) T2 / B2(try 최상단 분기·cli_prompt 자체조립·claude 전용 _capable·ROLE_MAP) T2 / B3(asyncio.run 전면) 전 태스크 / B4(픽스처 ingested_at·레거시 통과 정책) T3 / B5(일단위 cutoff·ingested 게이트·전량 읽기·re-export) T4 / B6(_score 충실 추출·동작보존 게이트) T5 / B7(카드 통과·dup first·f2/f3 실코드·단일콜 클러스터) T6 / B8(evidence_ids/numeric_facts/as_of 파생·rules/anchors 실사용) T7 / B9(A1 근거전달·A2 실구현·숫자 정체성·월 파싱·as_of 누락 정책) T8 / B10(verified-only·낮 고정·claim_id 매핑) T9 / B11(alloc→run→save·예약 필수 save) T10 / B12(T11 실테스트·T12 실코드) T11-12.
- **SF**: typed ReportPipeline·items 문자열 강제(T1) / window_hours(T9) / stage_errors(T9-10) / Role 폴백 테스트+ROLE_MAP(T2) / OpenAPI T11을 e2e 앞에 / 예약 없는 save 거부 테스트(T10).
- **Type consistency**: `StageResult(output 필수)`·`claim_id` 문자열 매핑·`NumericFact`가 T1→T7→T8→T9→T10 일관. roles dict 키(filter/importance/cluster/deepen/synth/verifier/cross)가 T10·T12 일치.
- **Placeholder scan**: 전 태스크 실코드·실명령·기대출력. "동일 골격" 위임 없음.
