# chain_judgment eval (스펙 1부) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사건 기반 chain_judgment eval(frozen bundle 모드 + 교차 provider 저지 + calibration)을 구축하고 현재 파이프라인의 베이스라인을 측정한다.

**Architecture:** eval은 케이스별 frozen bundle(카드·지표·가격·RA 문서 snapshot)로 파이프라인을 돌리고(라이브 검색 차단), gpt-5.5 저지가 루브릭 5축을 채점한다. 저지는 봉인 metamorphic calibration을 첫 시도에 통과해야 유효. 배포 판정은 `availability: proven` 전향 케이스만 산입한다.

**Tech Stack:** Python 3.12 (engine/.venv), pytest, pydantic, 기존 Role/CostMeter 인프라.

**스펙:** `docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md` (v5, codex r5 승인) §1부

## Global Constraints

- 저지는 교차 provider **gpt-5.5 단독** — anthropic 폴백 금지 (self-preference 차단).
- 봉인 calibration 셋: **프롬프트 버전당 1회 평가, 첫 시도 통과 필수.** 실패 시 튜닝 fixture로만 수정 후 새 봉인 셋 재생성.
- invalid/타임아웃 저지 응답: 1회 재시도 후 `score=null` (0점 처리 금지).
- 회고 케이스는 `availability: unproven` — **dev·진단 전용, 배포 판정 불산입.**
- bundle 생성 시 날짜 불명 문서 **fail-closed 제외.**
- `as_of_violation`(bundle 밖 인용) = 0 필수.
- eval 실행은 순차 (병렬 금지 — 기존 run_eval 원칙).
- 기존 `golden.jsonl` 경로·동작 불변 (회귀 금지).
- 커밋 메시지는 작은따옴표로 감싼다. 엔진 재시작은 `pm2 restart attn-engine`만.
- Task 전부 완료 후 codex 교차 리뷰(Task 9) 통과 전에는 2부 착수 금지.
- 모든 명령은 `/home/ryze_yn/attn-viewer/engine`에서 실행. 테스트: `.venv/bin/python -m pytest`.

## File Structure

- `engine/evals/chain_judge.py` — 저지 호출·ChainJudgeResult·반복 채점 (신규)
- `engine/evals/fixtures/chain_judge/tuning/*.json` — 튜닝 fixture 5개 (신규)
- `engine/evals/calibration.py` — metamorphic 봉인 셋 생성·평가 (신규)
- `engine/evals/bundle.py` — EvalBundle·BundleSectorStore·capture·violation 검출 (신규)
- `engine/evals/build_chain_cases.py` — 후보 사건 리스트 CLI (신규)
- `engine/evals/golden_chain.jsonl` — 케이스 24개 (신규, Task 8에서 작성)
- `engine/evals/bundles/cj-XX/` — 케이스별 bundle (신규, Task 8에서 캡처)
- `engine/providers.py` — ROLE_MAP에 `chain_judge` 추가 (수정)
- `engine/orchestrator.py` — `overrides["eval_bundle"]` 스레딩 (수정)
- `engine/stages/ra_external.py` — bundle 문서 short-circuit (수정)
- `engine/stages/price_macro.py` — snapshot 인자 (수정)
- `engine/evals/metrics.py` — paired-validity·bootstrap CI (수정)
- `engine/evals/run_eval.py` — `--suite chain` (수정)
- 테스트: `engine/tests/test_chain_judge.py`, `test_calibration.py`, `test_eval_bundle.py`, `test_chain_metrics.py`

---

### Task 1: ChainJudgeResult 계약 + 저지 role

**Files:**
- Create: `engine/evals/chain_judge.py`
- Modify: `engine/providers.py` (ROLE_MAP 1줄)
- Test: `engine/tests/test_chain_judge.py`

**Interfaces:**
- Produces: `ChainAxisScore(score: float | None, reason: str, matched: list[str], missing: list[str])`, `ChainJudgeResult(case_id, axes: dict[str, ChainAxisScore], judge_model, judge_prompt_version, raw)`, `AXES = ("mechanism","state_link","verdict","evidence","countercase")`, `merge_repeats(a, b, tie) -> ChainJudgeResult`, `JUDGE_PROMPT_VERSION = "cj-v1"`
- Consumes: `providers.Role` (기존)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_chain_judge.py
from evals.chain_judge import AXES, ChainAxisScore, ChainJudgeResult, merge_repeats


def _res(scores: dict) -> ChainJudgeResult:
    axes = {a: ChainAxisScore(score=scores.get(a), reason="r", matched=[], missing=[])
            for a in AXES}
    return ChainJudgeResult(case_id="cj-01", axes=axes, judge_model="gpt-5.5",
                            judge_prompt_version="cj-v1", raw="{}")


def test_merge_repeats_agree_keeps_score():
    a = _res({ax: 1.0 for ax in AXES})
    b = _res({ax: 1.0 for ax in AXES})
    m = merge_repeats(a, b, tie=None)
    assert all(m.axes[ax].score == 1.0 for ax in AXES)


def test_merge_repeats_mismatch_uses_tiebreak():
    a = _res({"mechanism": 1.0, "state_link": 1.0, "verdict": 1.0,
              "evidence": 0.5, "countercase": 1.0})
    b = _res({"mechanism": 0.0, "state_link": 1.0, "verdict": 1.0,
              "evidence": 0.5, "countercase": 1.0})
    tie = _res({"mechanism": 0.0, "state_link": 1.0, "verdict": 1.0,
                "evidence": 0.5, "countercase": 1.0})
    m = merge_repeats(a, b, tie=tie)
    assert m.axes["mechanism"].score == 0.0     # 다수결 (b, tie)
    assert m.axes["state_link"].score == 1.0


def test_merge_repeats_null_propagates():
    a = _res({ax: None for ax in AXES})
    b = _res({ax: 1.0 for ax in AXES})
    m = merge_repeats(a, b, tie=None)
    assert all(m.axes[ax].score is None for ax in AXES)  # 한쪽 null → 케이스 무효
```

- [ ] **Step 2: 실패 확인**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_chain_judge.py -v`
Expected: FAIL — `ModuleNotFoundError: evals.chain_judge`

- [ ] **Step 3: 구현**

```python
# engine/evals/chain_judge.py
"""chain_judgment 저지 — 교차 provider(gpt-5.5) 루브릭 채점 (스펙 1부).

- 반복 2회 + 축 불일치 시 3회차 타이브레이크(다수결).
- invalid/타임아웃 1회 재시도 후 score=None (0점 처리 금지 — 스펙).
- anthropic 폴백 금지: 합성이 Claude 계열이라 self-preference가 생김.
"""
from __future__ import annotations

from pydantic import BaseModel

AXES = ("mechanism", "state_link", "verdict", "evidence", "countercase")
JUDGE_PROMPT_VERSION = "cj-v1"

_INSTR = """너는 금융 QA 답변의 근거 체인 채점자다. 답변을 루브릭 5축으로 채점한다.
반드시 제공된 evidence bundle 안의 근거만 실재로 인정하라 — bundle에 없는 인용·수치를
근거로 쓴 주장은 해당 축 0점이다. 유창함·문체는 채점 대상이 아니다.
- mechanism/state_link/verdict/countercase: 0 또는 1
- evidence: 루브릭 evidence 목록 중 답변에 실제로 등장한 항목 비율 (matched/missing 명시)"""


class ChainAxisScore(BaseModel):
    score: float | None
    reason: str = ""
    matched: list[str] = []
    missing: list[str] = []


class ChainJudgeResult(BaseModel):
    case_id: str
    axes: dict[str, ChainAxisScore]
    judge_model: str
    judge_prompt_version: str
    raw: str


class _JudgeOut(BaseModel):  # 저지 structured output (case_id 등은 코드가 채움)
    mechanism: ChainAxisScore
    state_link: ChainAxisScore
    verdict: ChainAxisScore
    evidence: ChainAxisScore
    countercase: ChainAxisScore


def _valid(r: ChainJudgeResult | None) -> bool:
    return r is not None and all(r.axes[a].score is not None for a in AXES)


def merge_repeats(a: ChainJudgeResult, b: ChainJudgeResult,
                  tie: ChainJudgeResult | None) -> ChainJudgeResult:
    """축별 병합: 일치→그대로, 불일치→3자 다수결. 한쪽 null → null (케이스 무효)."""
    axes: dict[str, ChainAxisScore] = {}
    for ax in AXES:
        sa, sb = a.axes[ax].score, b.axes[ax].score
        if sa is None or sb is None:
            axes[ax] = ChainAxisScore(score=None, reason="repeat null")
        elif sa == sb:
            axes[ax] = a.axes[ax]
        elif tie is not None and tie.axes[ax].score is not None:
            st = tie.axes[ax].score
            win = st if (st == sa or st == sb) else None  # 3자 전부 다르면 무효
            src = a if win == sa else (b if win == sb else None)
            axes[ax] = (src.axes[ax] if src else
                        ChainAxisScore(score=None, reason="no majority"))
        else:
            axes[ax] = ChainAxisScore(score=None, reason="mismatch, no tiebreak")
    return ChainJudgeResult(case_id=a.case_id, axes=axes, judge_model=a.judge_model,
                            judge_prompt_version=a.judge_prompt_version, raw=a.raw)


async def judge_once(case_id: str, answer_md: str, rubric: dict,
                     bundle_text: str, role) -> ChainJudgeResult | None:
    """1회 채점. 실패 시 1회 재시도, 재실패 None."""
    import json
    prompt = (f"[루브릭]\n{json.dumps(rubric, ensure_ascii=False)}\n\n"
              f"[답변]\n{answer_md}\n\n각 축을 채점하라.")
    for _ in range(2):
        try:
            out = await role.run(prompt, instructions=_INSTR,
                                 response_format=_JudgeOut,
                                 cache_prefix=f"[evidence bundle]\n{bundle_text}")
            data = out if isinstance(out, _JudgeOut) else _JudgeOut.model_validate(out)
            return ChainJudgeResult(
                case_id=case_id,
                axes={a: getattr(data, a) for a in AXES},
                judge_model=role.model, judge_prompt_version=JUDGE_PROMPT_VERSION,
                raw=data.model_dump_json())
        except Exception:  # noqa: BLE001 — invalid/timeout 공통
            continue
    return None


async def judge_case(case_id: str, answer_md: str, rubric: dict,
                     bundle_text: str, role) -> ChainJudgeResult | None:
    """반복 2회 + 불일치 축 있으면 3회차 다수결. 반환 None = 케이스 무효."""
    r1 = await judge_once(case_id, answer_md, rubric, bundle_text, role)
    r2 = await judge_once(case_id, answer_md, rubric, bundle_text, role)
    if not _valid(r1) or not _valid(r2):
        return None
    if all(r1.axes[a].score == r2.axes[a].score for a in AXES):
        return merge_repeats(r1, r2, tie=None)
    r3 = await judge_once(case_id, answer_md, rubric, bundle_text, role)
    merged = merge_repeats(r1, r2, tie=r3 if _valid(r3) else None)
    return merged if _valid(merged) else None
```

`engine/providers.py`의 ROLE_MAP dict에 1줄 추가 (`"audit"` 항목 아래):

```python
    "chain_judge": [("openai", settings.model_gpt, "medium")],  # 교차 저지 — anthropic 폴백 금지(self-preference)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_chain_judge.py -v`
Expected: PASS 3건

- [ ] **Step 5: Commit**

```bash
git add engine/evals/chain_judge.py engine/providers.py engine/tests/test_chain_judge.py
git commit -m 'feat(eval): chain_judge 계약 — 반복 채점·다수결·null 무효 (스펙 1부)'
```

---

### Task 2: 튜닝 fixture 5개 + self-test 러너

**Files:**
- Create: `engine/evals/fixtures/chain_judge/tuning/01_missing_mechanism.json` (외 4개)
- Create: `engine/evals/calibration.py` (self-test 부분)
- Test: `engine/tests/test_calibration.py`

**Interfaces:**
- Consumes: `chain_judge.judge_case`, `chain_judge.AXES`
- Produces: `run_selftest(judge_fn) -> list[str]` (실패 항목 설명 목록 — 빈 리스트 = 통과), `load_tuning_fixtures() -> list[dict]`

fixture 형식 (5개 공통 — 각각 결함 하나를 심은 합성 답변):

```json
{
  "id": "01_missing_mechanism",
  "answer_md": "마이크론 실적이 잘 나왔으니 하이닉스에 긍정적이다. 반대로 CAPEX 둔화 보도가 있어 조정 가능성도 있다 [근거:c-2].",
  "rubric": {
    "mechanism": "실적 서프라이즈를 수요/공급 메커니즘으로 분해했는가",
    "state_link": "현재 CAPEX 국면과 연결했는가",
    "verdict": "방향 판단 명시 여부",
    "evidence": ["마이크론 실적", "CAPEX"],
    "countercase": "반대 근거 유무"
  },
  "bundle_text": "c-1: 마이크론 FQ3 매출 서프라이즈 (발표문). c-2: 하이퍼스케일러 CAPEX 가이던스 하향 보도.",
  "expected": {"mechanism": 0, "verdict": 1, "countercase": 1}
}
```

5개 구성 (스펙): `01_missing_mechanism` (위), `02_fabricated_citation` (bundle에 없는 `[근거:c-99]` 수치 인용 → evidence 축에 그 항목 miss), `03_future_info` (bundle 밖 미래 사건 근거 → 해당 주장 축 0), `04_no_countercase` (반대 의견 전무 → countercase 0), `05_clean` (전 축 충족 → 전부 1). `expected`에는 **확실한 축만** 넣는다 (부분 명세 — 저지의 다른 축 판단은 검사하지 않음).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_calibration.py
import asyncio

from evals.calibration import load_tuning_fixtures, run_selftest
from evals.chain_judge import AXES, ChainAxisScore, ChainJudgeResult


def test_tuning_fixtures_load_and_shape():
    fx = load_tuning_fixtures()
    assert len(fx) == 5
    assert all(set(f) >= {"id", "answer_md", "rubric", "bundle_text", "expected"} for f in fx)


def test_selftest_passes_with_oracle_judge():
    fx = load_tuning_fixtures()
    oracle = {f["id"]: f["expected"] for f in fx}

    async def judge_fn(case_id, answer_md, rubric, bundle_text):
        exp = oracle[case_id]
        axes = {a: ChainAxisScore(score=float(exp.get(a, 1)), reason="")
                for a in AXES}
        return ChainJudgeResult(case_id=case_id, axes=axes, judge_model="fake",
                                judge_prompt_version="cj-v1", raw="{}")

    failures = asyncio.run(run_selftest(judge_fn))
    assert failures == []


def test_selftest_fails_with_always_one_judge():
    async def judge_fn(case_id, answer_md, rubric, bundle_text):
        axes = {a: ChainAxisScore(score=1.0, reason="") for a in AXES}
        return ChainJudgeResult(case_id=case_id, axes=axes, judge_model="fake",
                                judge_prompt_version="cj-v1", raw="{}")

    failures = asyncio.run(run_selftest(judge_fn))
    assert failures  # 결함 fixture들을 1점 주면 실패해야 함
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_calibration.py -v`
Expected: FAIL — `ModuleNotFoundError: evals.calibration`

- [ ] **Step 3: fixture 5개 JSON 작성 + 구현**

```python
# engine/evals/calibration.py
"""저지 calibration — 튜닝 fixture self-test + 봉인 metamorphic 셋 (스펙 1부).

튜닝 fixture(공개)는 프롬프트 개발용, 봉인 셋은 버전당 1회 평가·첫 시도 통과 필수.
둘을 분리해 tune/test 순환 오염을 차단한다 (codex r3-B8).
"""
from __future__ import annotations

import json
from pathlib import Path

_FIX = Path(__file__).parent / "fixtures" / "chain_judge"


def load_tuning_fixtures() -> list[dict]:
    return [json.loads(p.read_text())
            for p in sorted((_FIX / "tuning").glob("*.json"))]


async def run_selftest(judge_fn) -> list[str]:
    """judge_fn(case_id, answer_md, rubric, bundle_text) -> ChainJudgeResult|None.
    반환: 실패 설명 목록 (빈 리스트 = 통과)."""
    failures: list[str] = []
    for f in load_tuning_fixtures():
        res = await judge_fn(f["id"], f["answer_md"], f["rubric"], f["bundle_text"])
        if res is None:
            failures.append(f"{f['id']}: judge invalid")
            continue
        for ax, want in f["expected"].items():
            got = res.axes[ax].score
            ok = (got is not None and
                  (got == float(want) if want in (0, 1) else abs(got - want) < 0.26))
            if not ok:
                failures.append(f"{f['id']}: {ax} expected {want} got {got}")
    return failures
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_calibration.py -v`
Expected: PASS 3건

- [ ] **Step 5: Commit**

```bash
git add engine/evals/fixtures engine/evals/calibration.py engine/tests/test_calibration.py
git commit -m 'feat(eval): 저지 튜닝 fixture 5종 + self-test 러너'
```

---

### Task 3: 봉인 metamorphic calibration 셋

**Files:**
- Modify: `engine/evals/calibration.py`
- Test: `engine/tests/test_calibration.py` (추가)

**Interfaces:**
- Produces: `TRANSFORMS: dict[str, callable]` (`strip_countercase`, `ghost_citations`, `strip_verdict`, `inject_unsupported_numbers`, `identity`), `make_sealed_set(base_records: list[dict], version: str) -> list[dict]`, `run_sealed(judge_fn, sealed: list[dict]) -> list[str]`
- 봉인 항목 형식: `{id, base_id, transform, answer_md, rubric, bundle_text, expectation: {axis, relation: "zero"|"lower"}}`

metamorphic 원리: 변형 T를 가한 답변은 원본 대비 해당 축 점수가 **0이 되거나 반드시 낮아져야** 한다. 원본 절대 점수의 정답 라벨이 필요 없다 (인간 라벨 대체 — codex r3 합의).

- [ ] **Step 1: 실패하는 테스트 추가** (`test_calibration.py`에 append)

```python
from evals.calibration import TRANSFORMS, make_sealed_set, run_sealed


def _base_record():
    return {"id": "b1",
            "answer_md": ("## 결론\n위협적이지 않다.\n\n메커니즘: 추론 서빙 수요 확대 [근거:c-1]\n\n"
                          "## 반대 시나리오\nCAPEX 하향 시 부정적 [근거:c-2]"),
            "rubric": {"mechanism": "m", "state_link": "s", "verdict": "v",
                       "evidence": ["추론", "CAPEX"], "countercase": "c"},
            "bundle_text": "c-1: 추론 수요 보도. c-2: CAPEX 하향 보도."}


def test_transforms_change_text():
    base = _base_record()
    for name, fn in TRANSFORMS.items():
        out = fn(base["answer_md"])
        if name != "identity":
            assert out != base["answer_md"], name


def test_make_sealed_set_shape():
    sealed = make_sealed_set([_base_record(), _base_record() | {"id": "b2"}], version="cj-v1")
    assert len(sealed) == 10  # 5 transforms x 2 base
    assert all(s["expectation"]["relation"] in ("zero", "lower", "same") for s in sealed)


def test_run_sealed_catches_insensitive_judge():
    sealed = make_sealed_set([_base_record()], version="cj-v1")

    async def judge_fn(case_id, answer_md, rubric, bundle_text):  # 항상 만점
        from evals.chain_judge import AXES, ChainAxisScore, ChainJudgeResult
        axes = {a: ChainAxisScore(score=1.0, reason="") for a in AXES}
        return ChainJudgeResult(case_id=case_id, axes=axes, judge_model="fake",
                                judge_prompt_version="cj-v1", raw="{}")

    import asyncio
    failures = asyncio.run(run_sealed(judge_fn, sealed))
    assert failures  # 변형에 무감한 저지는 걸려야 함
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_calibration.py -v`
Expected: 신규 3건 FAIL (`ImportError: TRANSFORMS`)

- [ ] **Step 3: 구현** (`calibration.py`에 append)

```python
import re


def _strip_countercase(md: str) -> str:
    return re.sub(r"## 반대 시나리오.*", "", md, flags=re.S).strip()


def _ghost_citations(md: str) -> str:
    return re.sub(r"\[근거:[^\]]+\]", "[근거:ghost-999]", md)


def _strip_verdict(md: str) -> str:
    return re.sub(r"## 결론\n[^\n]*\n", "## 결론\n\n", md)


def _inject_unsupported_numbers(md: str) -> str:
    return md + "\n\n추가로 HBM 계약가가 항상 37.8% 상승해 왔다는 점이 결정적이다."


TRANSFORMS = {
    "strip_countercase": _strip_countercase,
    "ghost_citations": _ghost_citations,
    "strip_verdict": _strip_verdict,
    "inject_unsupported_numbers": _inject_unsupported_numbers,
    "identity": lambda md: md,
}

_EXPECT = {  # transform → (검사 축, 관계)
    "strip_countercase": ("countercase", "zero"),
    "ghost_citations": ("evidence", "lower"),
    "strip_verdict": ("verdict", "zero"),
    "inject_unsupported_numbers": ("evidence", "lower"),
    "identity": ("verdict", "same"),
}


def make_sealed_set(base_records: list[dict], version: str) -> list[dict]:
    sealed = []
    for rec in base_records:
        for name, fn in TRANSFORMS.items():
            ax, rel = _EXPECT[name]
            sealed.append({"id": f"{rec['id']}::{name}", "base_id": rec["id"],
                           "transform": name, "answer_md": fn(rec["answer_md"]),
                           "rubric": rec["rubric"], "bundle_text": rec["bundle_text"],
                           "base_answer_md": rec["answer_md"], "version": version,
                           "expectation": {"axis": ax, "relation": rel}})
    return sealed


async def run_sealed(judge_fn, sealed: list[dict]) -> list[str]:
    """봉인 셋 평가 — 원본과 변형본을 채점해 metamorphic 관계 검증."""
    failures: list[str] = []
    base_cache: dict[str, object] = {}
    for s in sealed:
        if s["base_id"] not in base_cache:
            base_cache[s["base_id"]] = await judge_fn(
                s["base_id"], s["base_answer_md"], s["rubric"], s["bundle_text"])
        base = base_cache[s["base_id"]]
        var = await judge_fn(s["id"], s["answer_md"], s["rubric"], s["bundle_text"])
        if base is None or var is None:
            failures.append(f"{s['id']}: judge invalid")
            continue
        ax, rel = s["expectation"]["axis"], s["expectation"]["relation"]
        b, v = base.axes[ax].score, var.axes[ax].score
        if b is None or v is None:
            failures.append(f"{s['id']}: null score")
        elif rel == "zero" and v != 0.0:
            failures.append(f"{s['id']}: {ax} expected 0 got {v}")
        elif rel == "lower" and not v < b:
            failures.append(f"{s['id']}: {ax} expected < {b} got {v}")
        elif rel == "same" and v != b:
            failures.append(f"{s['id']}: {ax} expected {b} got {v}")
    return failures
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_calibration.py -v`
Expected: PASS 6건

- [ ] **Step 5: Commit**

```bash
git add engine/evals/calibration.py engine/tests/test_calibration.py
git commit -m 'feat(eval): 봉인 metamorphic calibration 셋 — 변형·관계 검증'
```

---

### Task 4: EvalBundle + BundleSectorStore + violation 검출

**Files:**
- Create: `engine/evals/bundle.py`
- Test: `engine/tests/test_eval_bundle.py`

**Interfaces:**
- Consumes: `sector.contracts.SectorCard`, `sector.contracts.MetricObservation` (pydantic)
- Produces: `EvalBundle(root)` — `.manifest: dict`, `.store() -> BundleSectorStore`, `.ra_documents() -> list[dict]`, `.prices() -> dict`, `.bundle_text(max_chars=12000) -> str`; `BundleSectorStore.read_cards(days=14, axis=None, ...)`, `.read_metric(metric, last_n=90)`, `.get_state(key)`; `capture_bundle(store, out_dir, *, as_of, availability, ra_docs, prices) -> Path`; `find_violations(layers, final_meta, manifest) -> list[str]`
- bundle 디렉토리: `cards.jsonl`, `metrics/<name>.jsonl`, `ra_docs.jsonl`, `prices.json`, `manifest.json` (`{as_of, captured_at, availability, card_ids, urls, metric_names}`)

핵심 규칙: `capture_bundle`은 `ts <= as_of`인 카드·관측만 복사, `published_at` 없는 RA 문서는 **제외하고 제외 수를 manifest에 기록** (fail-closed). `find_violations`는 RA/뉴스 layer와 final citation의 URL이 manifest.urls에 없으면 위반으로 센다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_eval_bundle.py
import json

from evals.bundle import EvalBundle, capture_bundle, find_violations
from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore


def _seed_store(tmp_path):
    store = SectorStore(tmp_path / "sector")
    store.append_cards([
        SectorCard(id="c-old", ts="2026-07-01T00:00:00Z", axis="A", direction="positive",
                   magnitude=2, source_grade="A", title="old", interpreted_signal="",
                   raw_quote="q-old", url="https://a.example/1", entities=["SK하이닉스"]),
        SectorCard(id="c-new", ts="2026-07-15T00:00:00Z", axis="A", direction="positive",
                   magnitude=2, source_grade="A", title="new", interpreted_signal="",
                   raw_quote="q-new", url="https://a.example/2", entities=["SK하이닉스"]),
    ])
    store.append_observations([
        MetricObservation(metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd"),
        MetricObservation(metric="kr_semi_export", ts="2026-07-15", value=2.0, unit="k_usd"),
    ])
    return store


def test_capture_filters_by_as_of_and_fail_closed(tmp_path):
    store = _seed_store(tmp_path)
    out = capture_bundle(
        store, tmp_path / "b", as_of="2026-07-10", availability="unproven",
        ra_docs=[{"url": "https://n.example/x", "published_at": "2026-07-09", "text": "t"},
                 {"url": "https://n.example/undated", "text": "t"}],  # 날짜 불명 → 제외
        prices={"005930.KS": {"close": 254500, "ts": "2026-07-10"}})
    b = EvalBundle(out)
    cards = b.store().read_cards(days=None)
    assert [c.id for c in cards] == ["c-old"]                      # c-new(7/15) 제외
    obs = b.store().read_metric("kr_semi_export")
    assert [o.value for o in obs] == [1.0]
    assert b.manifest["dropped_undated_docs"] == 1                 # fail-closed 기록
    assert "https://n.example/x" in b.manifest["urls"]
    assert "https://n.example/undated" not in b.manifest["urls"]


def test_find_violations_flags_outside_urls(tmp_path):
    store = _seed_store(tmp_path)
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={})
    manifest = json.loads((out / "manifest.json").read_text())
    layers = [{"name": "ra_external",
               "data": {"documents": [{"url": "https://leak.example/future"}]}}]
    v = find_violations(layers, {}, manifest)
    assert v == ["https://leak.example/future"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_eval_bundle.py -v`
Expected: FAIL — `ModuleNotFoundError: evals.bundle`

- [ ] **Step 3: 구현**

```python
# engine/evals/bundle.py
"""frozen evidence bundle — chain eval의 유일한 증거 소스 (스펙 1부 r2-B4/r4-B4).

- capture: as_of 이하 카드·관측만, 날짜 불명 RA 문서 fail-closed 제외(수 기록).
- BundleSectorStore: SectorStore의 read_cards/read_metric/get_state 표면만 재현.
- find_violations: bundle 밖 URL 인용 검출 (as_of_violation).
"""
from __future__ import annotations

import json
from pathlib import Path

from sector.contracts import MetricObservation, SectorCard


class BundleSectorStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._cards = [SectorCard.model_validate_json(l)
                       for l in (self.root / "cards.jsonl").read_text().splitlines() if l.strip()]

    def read_cards(self, *, days: int | None = 14, axis: str | None = None,
                   **kw) -> list[SectorCard]:
        out = self._cards
        if axis:
            out = [c for c in out if c.axis == axis]
        return out  # bundle은 이미 as_of로 잘려 있음 — days 필터 불필요

    def read_metric(self, metric: str, *, last_n: int = 90) -> list[MetricObservation]:
        p = self.root / "metrics" / f"{metric}.jsonl"
        if not p.exists():
            return []
        rows = [MetricObservation.model_validate_json(l)
                for l in p.read_text().splitlines() if l.strip()]
        return rows[-last_n:]

    def get_state(self, key: str):
        return None


class EvalBundle:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text())

    def store(self) -> BundleSectorStore:
        return BundleSectorStore(self.root)

    def ra_documents(self) -> list[dict]:
        p = self.root / "ra_docs.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    def prices(self) -> dict:
        p = self.root / "prices.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def bundle_text(self, max_chars: int = 12000) -> str:
        """저지 입력용 평문 — 카드 제목·인용 + 지표 최근값 + RA 요약."""
        parts = [f"{c.id}: {c.title} — {c.raw_quote[:150]}"
                 for c in self.store().read_cards(days=None)]
        parts += [f"doc:{d['url']}: {d.get('text', '')[:150]}" for d in self.ra_documents()]
        return "\n".join(parts)[:max_chars]


def capture_bundle(store, out_dir: Path | str, *, as_of: str, availability: str,
                   ra_docs: list[dict], prices: dict) -> Path:
    out = Path(out_dir)
    (out / "metrics").mkdir(parents=True, exist_ok=True)
    cards = [c for c in store.read_cards(days=None) if c.ts[:10] <= as_of]
    (out / "cards.jsonl").write_text("\n".join(c.model_dump_json() for c in cards))
    metric_names = sorted(p.stem for p in (Path(store.root) / "metrics").glob("*.jsonl"))
    for m in metric_names:
        rows = [o for o in store.read_metric(m, last_n=10000) if o.ts[:10] <= as_of]
        (out / "metrics" / f"{m}.jsonl").write_text(
            "\n".join(o.model_dump_json() for o in rows))
    dated = [d for d in ra_docs if (d.get("published_at") or "")[:10] and
             d["published_at"][:10] <= as_of]
    (out / "ra_docs.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in dated))
    (out / "prices.json").write_text(json.dumps(prices, ensure_ascii=False))
    import time
    manifest = {"as_of": as_of, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "availability": availability,
                "card_ids": [c.id for c in cards],
                "urls": sorted({c.url for c in cards} | {d["url"] for d in dated}),
                "metric_names": metric_names,
                "dropped_undated_docs": len(ra_docs) - len(dated)}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return out


def find_violations(layers: list[dict], final_meta: dict, manifest: dict) -> list[str]:
    """RA/뉴스/sector layer가 실은 URL 중 manifest 밖 = as_of 위반."""
    allowed = set(manifest.get("urls", []))
    seen: list[str] = []
    for l in layers:
        data = l.get("data") or {}
        for d in data.get("documents", []) or []:
            u = d.get("url")
            if u and u not in allowed and u not in seen:
                seen.append(u)
        for c in data.get("cards", []) or []:
            u = c.get("url")
            if u and u not in allowed and u not in seen:
                seen.append(u)
    return seen
```

주의: `SectorCard` 필수 필드가 테스트의 생성 인자와 다르면(예: 추가 필수 필드) `engine/sector/contracts.py:13`을 열어 맞춘다 — 계약을 바꾸지 말고 테스트 fixture를 맞출 것.

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_eval_bundle.py -v`
Expected: PASS 2건

- [ ] **Step 5: Commit**

```bash
git add engine/evals/bundle.py engine/tests/test_eval_bundle.py
git commit -m 'feat(eval): frozen bundle — as_of 캡처·BundleSectorStore·위반 검출'
```

---

### Task 5: 파이프라인 bundle 모드 (orchestrator + 스테이지 스레딩)

**Files:**
- Modify: `engine/orchestrator.py` (sector 블록 ~L251-302, DISPATCH ~L218-220, 보충검색 2곳 ~L375·L436)
- Modify: `engine/stages/ra_external.py:421` (`run_ra_external`에 `bundle_docs` 인자)
- Modify: `engine/stages/price_macro.py:12` (`run_price_macro`에 `snapshot` 인자)
- Test: `engine/tests/test_bundle_mode.py`

**Interfaces:**
- Consumes: `evals.bundle.EvalBundle`
- Produces: `run_qa(..., overrides={"eval_bundle": "<path>"})` 동작 계약:
  1. sector 검색이 `EvalBundle.store()` 사용
  2. `run_ra_external(plan, overrides, bundle_docs=[...])` — bundle_docs가 `None`이 아니면 라이브 검색(네이버·구글RSS·toss·x_search) 전부 생략하고 bundle 문서로 RAPacket 구성
  3. `run_price_macro(plan, snapshot=bundle.prices())` — snapshot이 있으면 Yahoo 호출 없이 snapshot 값으로 packet 구성
  4. REFLECT 보충 검색 2곳: bundle 모드면 신규 문서 0 (즉시 종료 경로)

각 수정은 **기존 동작의 기본값 유지** (`bundle_docs=None`, `snapshot=None`이면 현행 그대로) — 라이브 경로 회귀 금지.

- [ ] **Step 1: 실패하는 테스트 작성** — 스테이지 단위 (orchestrator 통합은 Step 5에서 수동 스모크)

```python
# engine/tests/test_bundle_mode.py
import asyncio

from contracts import PlanPacket  # 실제 import 경로는 engine/contracts/ 확인 후 조정
from stages.price_macro import run_price_macro
from stages.ra_external import run_ra_external


def _plan() -> PlanPacket:
    # PlanPacket 필수 필드는 contracts 정의를 따른다 — 최소 생성 헬퍼가 이미
    # tests에 있으면 재사용 (grep "PlanPacket(" tests/)
    return PlanPacket(standalone_question="하이닉스 전망", tier=3,
                      search_queries=["하이닉스"], sub_questions=[])


def test_price_macro_snapshot_skips_network():
    snap = {"005930.KS": {"close": 254500.0, "ts": "2026-07-10"}}
    pkt = asyncio.run(run_price_macro(_plan(), snapshot=snap))
    quotes = {q.symbol: q for q in pkt.quotes}
    assert quotes["005930.KS"].price == 254500.0
    # 네트워크 미접근은 snapshot 경로가 httpx 호출 없이 즉시 반환하는 것으로 보장
    # (구현에서 snapshot 분기가 yahoo 모듈을 import조차 하지 않게 한다)


def test_ra_external_bundle_docs_short_circuit():
    docs = [{"url": "https://a.example/1", "title": "t", "text": "본문",
             "published_at": "2026-07-09"}]
    pkt = asyncio.run(run_ra_external(_plan(), None, bundle_docs=docs))
    assert [d.url for d in pkt.documents] == ["https://a.example/1"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_bundle_mode.py -v`
Expected: FAIL — `TypeError: unexpected keyword argument` (snapshot / bundle_docs)

- [ ] **Step 3: 스테이지 수정**

`price_macro.py` — 함수 서두에 snapshot 분기 (기존 로직 위):

```python
async def run_price_macro(plan: PlanPacket, snapshot: dict | None = None) -> PriceMacroPacket:
    if snapshot is not None:
        # eval bundle 모드 — 라이브 Yahoo/매크로 호출 금지 (스펙 1부 as_of 강제)
        quotes = [Quote(symbol=sym, price=v["close"], ts=v.get("ts", ""))
                  for sym, v in snapshot.items()]
        return PriceMacroPacket(quotes=quotes, macro=[])
    ...  # 기존 본문 그대로
```

(`Quote`/`PriceMacroPacket`의 실제 필드명은 `engine/contracts/` 정의에 맞춘다 — 필드가 다르면 테스트도 같은 이름으로 수정.)

`ra_external.py` — `run_ra_external` 서두:

```python
async def run_ra_external(plan: PlanPacket, overrides: dict | None = None,
                          *, bundle_docs: list[dict] | None = None, **kw):
    if bundle_docs is not None:
        # eval bundle 모드 — 라이브 검색 전면 생략, bundle 문서만 패킷화
        docs = [RADocument(url=d["url"], title=d.get("title", ""),
                           text=d.get("text", ""), published_at=d.get("published_at"))
                for d in bundle_docs]
        return _package(docs)  # 기존 패킷 조립 헬퍼 재사용 — 이름은 파일 내 확인
    ...  # 기존 본문
```

`orchestrator.py` — run_qa 초입(DISPATCH 전)에:

```python
    eval_bundle = None
    if overrides and overrides.get("eval_bundle"):
        from evals.bundle import EvalBundle
        eval_bundle = EvalBundle(overrides["eval_bundle"])
```

- DISPATCH(L218-220): `run_ra_external(plan, overrides, bundle_docs=eval_bundle.ra_documents() if eval_bundle else None)`, `run_price_macro(plan, snapshot=eval_bundle.prices() if eval_bundle else None)`
- sector 블록(L267): `_store = eval_bundle.store() if eval_bundle else _get_store()`
- 보충 검색 2곳(L375, L436): `if eval_bundle: supp_docs = []` 형태로 신규 문서 차단 (기존 "신규 0건 → REFLECT 종료" 규칙이 자동 작동)

- [ ] **Step 4: 통과 + 회귀 확인**

Run: `.venv/bin/python -m pytest tests/test_bundle_mode.py tests/ -v`
Expected: 신규 2건 PASS + 기존 테스트 전부 PASS (기본값 경로 회귀 없음)

- [ ] **Step 5: Commit**

```bash
git add engine/orchestrator.py engine/stages/ra_external.py engine/stages/price_macro.py engine/tests/test_bundle_mode.py
git commit -m 'feat(engine): eval bundle 모드 — 섹터·RA·가격을 frozen bundle로 대체, 라이브 검색 차단'
```

---

### Task 6: chain 지표 — paired-validity + bootstrap CI

**Files:**
- Modify: `engine/evals/metrics.py`
- Test: `engine/tests/test_chain_metrics.py`

**Interfaces:**
- Produces: `paired_valid(base: list[dict], cand: list[dict]) -> tuple[list[tuple], float]` (양쪽 유효(null 없는)한 케이스 쌍 목록, 유효 비율), `bootstrap_ci(deltas: list[float], n: int = 10000, seed: int = 42) -> tuple[float, float]` (95% CI), `axis_mean(results: list, axis: str) -> float | None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_chain_metrics.py
from evals.metrics import axis_mean, bootstrap_ci, paired_valid


def _rec(cid, mech):
    return {"id": cid, "chain_axes": {"mechanism": mech, "state_link": 1.0,
                                      "verdict": 1.0, "evidence": 1.0, "countercase": 1.0}}


def test_paired_valid_drops_null_and_reports_ratio():
    base = [_rec("a", 0.0), _rec("b", None), _rec("c", 1.0)]
    cand = [_rec("a", 1.0), _rec("b", 1.0), _rec("c", None)]
    pairs, ratio = paired_valid(base, cand)
    assert [p[0]["id"] for p in pairs] == ["a"]   # b: base null, c: cand null
    assert round(ratio, 2) == 0.33


def test_bootstrap_ci_positive_effect():
    lo, hi = bootstrap_ci([1.0] * 10, seed=42)
    assert lo > 0 and hi >= lo


def test_bootstrap_ci_mixed_effect_spans_zero():
    lo, hi = bootstrap_ci([1.0, -1.0] * 5, seed=42)
    assert lo <= 0 <= hi


def test_axis_mean_ignores_null():
    vals = axis_mean([_rec("a", 1.0), _rec("b", None)], "mechanism")
    assert vals == 1.0
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_chain_metrics.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현** (`metrics.py`에 append)

```python
import random as _random


def paired_valid(base: list[dict], cand: list[dict]) -> tuple[list[tuple], float]:
    """id로 짝지어 양쪽 모두 전 축 non-null인 쌍만 반환 (r3-B8 paired-validity).
    반환: (쌍 목록, 유효 비율). 비율 < 0.9면 호출측이 결과를 폐기해야 한다."""
    bmap = {r["id"]: r for r in base}
    pairs, total = [], 0
    for c in cand:
        b = bmap.get(c["id"])
        if b is None:
            continue
        total += 1
        def _ok(r):
            ax = r.get("chain_axes") or {}
            return ax and all(v is not None for v in ax.values())
        if _ok(b) and _ok(c):
            pairs.append((b, c))
    return pairs, (len(pairs) / total if total else 0.0)


def bootstrap_ci(deltas: list[float], n: int = 10000,
                 seed: int = 42) -> tuple[float, float]:
    """paired delta의 95% percentile bootstrap CI. seed 고정 — 재현성."""
    rng = _random.Random(seed)
    means = sorted(sum(rng.choices(deltas, k=len(deltas))) / len(deltas)
                   for _ in range(n))
    return means[int(n * 0.025)], means[int(n * 0.975)]


def axis_mean(results: list[dict], axis: str) -> float | None:
    vals = [r["chain_axes"][axis] for r in results
            if (r.get("chain_axes") or {}).get(axis) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_chain_metrics.py -v`
Expected: PASS 4건

- [ ] **Step 5: Commit**

```bash
git add engine/evals/metrics.py engine/tests/test_chain_metrics.py
git commit -m 'feat(eval): paired-validity·bootstrap CI·축 평균 지표'
```

---

### Task 7: run_eval `--suite chain`

**Files:**
- Modify: `engine/evals/run_eval.py`
- Test: 수동 스모크 (LLM·파이프라인 통합 — 단위 테스트 대상 아님. 로직 분기는 Task 6까지의 단위 테스트가 커버)

**Interfaces:**
- Consumes: `chain_judge.judge_case`, `calibration.run_selftest/make_sealed_set/run_sealed`, `bundle.EvalBundle/find_violations`, `metrics.axis_mean`, `providers.Role`
- Produces: CLI `--suite chain [--split dev|holdout] [--limit N]`; 레코드에 `chain_axes: dict`, `as_of_violations: list`, `availability`, `judge_raw` 필드; 리포트 md에 축별 평균 + `code_sha`·`judge_prompt_version`·케이스별 bundle `captured_at`

- [ ] **Step 1: 구현** — `run_eval.py`에 chain 경로 추가

```python
# main() 인자에 추가
    ap.add_argument("--suite", default="golden", choices=["golden", "chain"])
    ap.add_argument("--split", default="", choices=["", "dev", "holdout"])

# main() 분기 (기존 golden 경로는 그대로 두고):
    if args.suite == "chain":
        await run_chain_suite(args)
        return


async def run_chain_suite(args) -> None:
    import subprocess
    from evals.bundle import EvalBundle, find_violations
    from evals.calibration import run_selftest
    from evals.chain_judge import AXES, JUDGE_PROMPT_VERSION, judge_case
    from evals.metrics import axis_mean
    from providers import Role

    role = Role("chain_judge")

    async def judge_fn(cid, ans, rub, btxt):
        return await judge_case(cid, ans, rub, btxt, role)

    failures = await run_selftest(judge_fn)          # 튜닝 fixture 게이트
    if failures:
        raise SystemExit(f"judge self-test 실패 — 채점 중단: {failures}")

    rows = [json.loads(l) for l in (_HERE / "golden_chain.jsonl").read_text().splitlines()
            if l.strip()]
    if args.split:
        rows = [r for r in rows if r["split"] == args.split]
    if args.limit:
        rows = rows[:args.limit]
    ts = time.strftime("%Y%m%d-%H%M%S")
    records = []
    for row in rows:                                  # 순차 — 병렬 금지
        b = EvalBundle(_HERE / row["bundle_path"])
        layers, final = [], None
        async for ev in run_qa(row["question"],
                               overrides={"eval_bundle": str(_HERE / row["bundle_path"])},
                               user_id=os.environ.get("EVAL_PLAYBOOK_USER", "")):
            if ev.get("kind") == "layer":
                layers.append(ev)
            elif ev.get("kind") == "final":
                final = ev
        answer = (final or {}).get("answer", "")
        res = await judge_case(row["id"], answer, row["rubric"], b.bundle_text(), role)
        viol = find_violations(layers, (final or {}).get("meta") or {}, b.manifest)
        _, mn, hit = keyword_check(answer, [], row.get("must_not", []))
        rec = {"id": row["id"], "split": row["split"],
               "availability": b.manifest["availability"],
               "chain_axes": ({a: res.axes[a].score for a in AXES} if res
                              else {a: None for a in AXES}),
               "judge_raw": res.raw if res else None,
               "as_of_violations": viol, "must_not_hit": hit,
               "answer_md": answer,
               **question_metrics(layers, (final or {}).get("meta") or {})}
        records.append(rec)
        print(f"[{rec['id']}] axes={rec['chain_axes']} viol={len(viol)}")
    out_dir = _HERE / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"chain-{ts}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    lines = [f"# chain eval {ts} — {len(records)}문항 "
             f"(sha={sha}, judge={JUDGE_PROMPT_VERSION})", ""]
    for ax in AXES:
        lines.append(f"- **{ax}**: {axis_mean(records, ax)}")
    total_viol = sum(len(r["as_of_violations"]) for r in records)
    lines.append(f"- as_of_violation 합계: {total_viol} (0 필수)")
    null_cases = [r["id"] for r in records
                  if any(v is None for v in r["chain_axes"].values())]
    lines.append(f"- 저지 무효 케이스: {null_cases or '없음'}")
    (out_dir / f"chain-{ts}.md").write_text("\n".join(lines))
    print(f"saved: evals/out/chain-{ts}.jsonl / .md")
```

- [ ] **Step 2: 기존 suite 회귀 확인**

Run: `.venv/bin/python -m pytest tests/ -v` 그리고 `.venv/bin/python -m evals.run_eval --limit 1`
Expected: 테스트 전부 PASS, golden 1문항 정상 실행 (기존 경로 무변화)

- [ ] **Step 3: Commit**

```bash
git add engine/evals/run_eval.py
git commit -m 'feat(eval): --suite chain — self-test 게이트·bundle 실행·축 리포트'
```

---

### Task 8: 케이스 24개 작성 + bundle 캡처 + 베이스라인 측정

**Files:**
- Create: `engine/evals/build_chain_cases.py`
- Create: `engine/evals/golden_chain.jsonl`
- Create: `engine/evals/bundles/cj-01/ … cj-24/`

**Interfaces:**
- Consumes: `sector.store.SectorStore`, `bundle.capture_bundle`
- Produces: 후보 사건 목록 CLI + 캡처 CLI

- [ ] **Step 1: 후보 사건 리스트 CLI 작성**

```python
# engine/evals/build_chain_cases.py
"""chain eval 케이스 후보 — 카드 저장소에서 사건 후보를 뽑고 bundle을 캡처한다.

사용:
  .venv/bin/python -m evals.build_chain_cases list --since 2026-06-01
  .venv/bin/python -m evals.build_chain_cases capture --case cj-01 --as-of 2026-07-08 \
      --availability unproven
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evals.bundle import capture_bundle
from sector.api import _get_store

_HERE = Path(__file__).parent


def cmd_list(args) -> None:
    store = _get_store()
    cards = [c for c in store.read_cards(days=None)
             if c.ts[:10] >= args.since and c.magnitude >= 2]
    by_week = Counter()
    for c in cards:
        by_week[(c.ts[:7], c.axis)] += 1
    for c in sorted(cards, key=lambda c: (c.ts, -c.magnitude))[:120]:
        print(f"{c.ts[:10]} [{c.axis}/{c.magnitude}/{c.source_grade}] "
              f"{c.title[:80]}  ({c.id})")
    print("\n주별 분포:", dict(by_week))


def cmd_capture(args) -> None:
    out = capture_bundle(_get_store(), _HERE / "bundles" / args.case,
                         as_of=args.as_of, availability=args.availability,
                         ra_docs=json.loads(Path(args.ra_docs).read_text())
                         if args.ra_docs else [],
                         prices=json.loads(Path(args.prices).read_text())
                         if args.prices else {})
    print(f"captured: {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("list")
    p1.add_argument("--since", default="2026-06-01")
    p2 = sub.add_parser("capture")
    p2.add_argument("--case", required=True)
    p2.add_argument("--as-of", required=True)
    p2.add_argument("--availability", required=True, choices=["proven", "unproven"])
    p2.add_argument("--ra-docs", default="")
    p2.add_argument("--prices", default="")
    args = ap.parse_args()
    {"list": cmd_list, "capture": cmd_capture}[args.cmd](args)


if __name__ == "__main__":
    main()
```

Run: `.venv/bin/python -m evals.build_chain_cases list --since 2026-06-01`

- [ ] **Step 2: 케이스 24개 작성** — `list` 출력에서 사건을 골라 `golden_chain.jsonl` 작성.
  구성 규칙 (스펙 층화): 사건 유형(실적/모델·제품 발표/CAPEX·수급 신호/정책·규제)별 최소 4개,
  긍정·부정 결이 절반씩, 전부 `split: dev`·`availability: unproven`
  (holdout은 배포 후 전향 케이스로만 — r4-B4). 각 케이스의 rubric.evidence에는
  해당 bundle에 실존하는 카드·지표만 적는다 (기억으로 쓰지 않는다 — 스펙).
  케이스당 `as_of` = 사건 다음 날.

- [ ] **Step 3: bundle 24개 캡처**

```bash
for i in $(seq -w 1 24); do
  # as_of는 케이스별 — golden_chain.jsonl의 as_of 필드와 일치시켜 실행
  .venv/bin/python -m evals.build_chain_cases capture --case cj-$i \
    --as-of $(python3 -c "import json;print([json.loads(l) for l in open('evals/golden_chain.jsonl')][int('$i')-1]['as_of'])") \
    --availability unproven
done
```

각 bundle의 `manifest.json`에서 `card_ids`가 비어 있지 않은지 확인 — 비면 as_of·사건 선정 재검토.

- [ ] **Step 4: 봉인 calibration 생성 + 베이스라인 측정**

```bash
# dev 3문항 파일럿 (judge self-test 게이트 포함 동작 확인)
.venv/bin/python -m evals.run_eval --suite chain --split dev --limit 3
# 정상이면 dev 전체 베이스라인
.venv/bin/python -m evals.run_eval --suite chain --split dev
```

Expected: `evals/out/chain-*.md`에 축별 평균, `as_of_violation 합계: 0`, 저지 무효 케이스 ≤ 2 (유효율 90%+). 위반 > 0이면 Task 5의 누출 경로부터 수정.

봉인 셋: 베이스라인 jsonl에서 답변 2개를 골라 `make_sealed_set`으로 10개 생성 후
`engine/evals/fixtures/chain_judge/sealed-cj-v1.json`에 저장, `run_sealed` 1회 실행 —
**첫 시도 통과 필수** (실패 시 튜닝 fixture로 프롬프트 수정 → `JUDGE_PROMPT_VERSION` 올리고
새 봉인 셋 재생성 — 스펙 규칙).

- [ ] **Step 5: Commit**

```bash
git add engine/evals/build_chain_cases.py engine/evals/golden_chain.jsonl engine/evals/bundles engine/evals/fixtures/chain_judge/sealed-cj-v1.json engine/evals/out/chain-*.jsonl engine/evals/out/chain-*.md
git commit -m 'feat(eval): chain 케이스 24개 + bundle 캡처 + 베이스라인 측정'
```

---

### Task 9: 1부 codex 교차 리뷰 (전역 제약)

- [ ] **Step 1:** `codex exec --sandbox read-only -C /home/ryze_yn/attn-viewer -o <scratchpad>/codex-p1-impl-review.md "스펙 1부(docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md) 구현을 리뷰해라: engine/evals/{chain_judge,calibration,bundle,build_chain_cases}.py, run_eval.py --suite chain, orchestrator/스테이지 bundle 모드, 베이스라인 리포트(evals/out/chain-*.md). 관점: ①as_of 누출 경로 잔존 ②저지 계약 위반 ③기존 golden 경로 회귀 ④스펙-구현 불일치. [블로커]/[권고] 등급, 파일·라인 근거."`
- [ ] **Step 2:** 블로커 반영 → 재리뷰 승인까지 왕복 (docs/memory-chain-review-p1-*.md 기록)
- [ ] **Step 3:** 승인 후 베이스라인 수치를 유저에게 보고. 2부 착수는 그 다음.

---

## Self-Review 기록

- 스펙 §1부 커버리지: frozen bundle(T4·T5), fail-closed(T4), as_of_violation(T4·T7), 저지 교차 provider·anthropic 폴백 금지(T1), self-test(T2)·봉인 셋(T3)·첫 시도 통과(T8), 반복 채점·타이브레이크(T1), paired-validity·bootstrap CI(T6), 층화 케이스·회고=dev 전용(T8), 리포트 버전 기록(T7), 베이스라인 선측정(T8), codex 리뷰(T9) — 전부 태스크에 매핑됨.
- paired 비교 실행(`--compare`)은 후보가 생기는 3부 이후에만 쓰이므로 YAGNI로 제외 — `paired_valid`·`bootstrap_ci` 함수는 준비됨(T6).
- 전향 케이스 축적은 배포 후 운영 절차(capture CLI --availability proven) — 4부 계획에서 다룸.
- 타입 일치: `judge_fn(case_id, answer_md, rubric, bundle_text)` 시그니처가 T2·T3·T7에서 동일. `chain_axes` dict 형태가 T6·T7에서 동일.
- 실 코드 인접부(패킷 필드명, `_package` 헬퍼명)는 구현 시 파일에서 확인하도록 명시 — 계약 자체는 계획에 고정.
