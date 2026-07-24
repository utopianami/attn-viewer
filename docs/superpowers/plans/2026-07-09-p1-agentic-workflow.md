# P1 에이전틱 워크플로우 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 P1 스코프 구현 — C1 평가 하네스, 라우팅 Stage 1(TRIAGE 유형 분류+프로필), A3 유사 쿼리 dedup, A4 복구 피드백, A1 역할 재제시(플래그), A2 반증 자세(플래그).

**Architecture:** 기존 고정 파이프라인(orchestrator.py의 run_qa)은 유지. TRIAGE가 질문 유형을 분류하고 프로필(설정 묶음)을 골라 각 단계의 "폭"만 조절한다(Stage 1: 소스 유지·폭 축소만). REFLECT 루프는 유사 쿼리 감지·복구 힌트로 질을 올리고, A1/A2는 설정 플래그(기본 off)로 landed 후 C1 하네스로 A/B한다.

**Tech Stack:** Python 3.12 + pydantic v2 (engine/), pytest (오프라인 테스트 — LLM 콜은 전부 스텁), 기존 Role/providers 패턴.

## Global Constraints

- 스펙: `docs/workflow-routing-plan.html` v2.2 (D1~D3 승인 2026-07-09) — Stage 1 화이트리스트/금지 목록 준수.
- **불변식 (절대 유지)**: ① 브랜치 never-raise — 생략해도 skipped 패킷이 fan-in에 도착 ② 모든 숫자는 CALC/시세만 — `enforce` 경로 무손상 ③ `EnvelopeMeta.round` 관통 ④ tier 안전 제어(tier4 차단·tier3 RISK·G2/G4)가 프로필보다 항상 우선.
- **Stage 1 금지**: DA 완전 off 금지(최소 single) · 뉴스 0콜 금지(최소 1유닛) · 검증 게이트 축소 금지 · CALC/시세 끔 금지.
- `LAYER_NAMES` 고정 어휘 변경 금지 — 프로필 정보는 기존 `triage` layer의 data dict에 넣는다.
- A1/A2는 settings 플래그 기본 "off" — 실험은 한 번에 하나(C1로 측정).
- 테스트: 오프라인(LLM 스텁) — 기존 컨벤션은 `tests/test_gates_m5.py` 참고 (`sys.path.insert`, `asyncio.run`, 모듈 함수 몽키패치).
- 커밋 메시지: 한국어 conventional commits (`feat(engine): ...`), 본문 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- 테스트 실행: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/<file> -q`
- 참고: 실험(측정) 순서는 C1→라우팅→A1→A3+A4→A2지만, 코드 랜딩 순서는 아래 태스크 순서를 따른다 (A1/A2는 플래그 off로 landed).

---

### Task 1: C1 평가 하네스 — 골든셋 + 코드 지표

**Files:**
- Create: `engine/evals/__init__.py` (빈 파일)
- Create: `engine/evals/golden.jsonl`
- Create: `engine/evals/metrics.py`
- Create: `engine/evals/run_eval.py`
- Test: `engine/tests/test_eval_metrics.py`

**Interfaces:**
- Produces: `metrics.question_metrics(layers: list[dict], final_meta: dict) -> dict` — 이후 태스크의 A/B 측정이 이 함수 출력(JSONL 레코드)을 사용.
- Produces: `evals/golden.jsonl` 각 행 스키마 `{"id": str, "type": str, "question": str, "must_include": list[str], "must_not": list[str], "note": str}`

- [ ] **Step 1: 골든셋 작성** — `engine/evals/golden.jsonl`에 35행 (유형 5종 × 7문항). 유형 값은 `fact_lookup | event_interpretation | stock_judgment | industry_analysis | strategy_portfolio`. 각 행은 실존 한국 시장 질문으로, `must_include`는 답변에 반드시 있어야 할 키워드(엔티티·개념, 시변 숫자 금지), `must_not`은 금지 표현(예: 매매 지시어). 예시 행 (이 형식으로 35행 전부 작성 — 아래 5행을 포함하고 유형별 6행씩 추가):

```jsonl
{"id": "fl-01", "type": "fact_lookup", "question": "삼성전자 PER 몇 배야?", "must_include": ["PER", "삼성전자"], "must_not": ["매수하세요", "매도하세요"], "note": "단일 지표 조회 — 숫자에 출처 필요"}
{"id": "ei-01", "type": "event_interpretation", "question": "오늘 SK하이닉스 왜 움직였어?", "must_include": ["SK하이닉스"], "must_not": ["매수하세요"], "note": "당일 원인 해석 — 뉴스 근거 인용 기대"}
{"id": "sj-01", "type": "stock_judgment", "question": "삼성전자 지금 사도 될까?", "must_include": ["리스크", "삼성전자"], "must_not": ["매수하세요", "무조건"], "note": "판단형 — RISK 반대 시나리오 포함 기대"}
{"id": "ia-01", "type": "industry_analysis", "question": "메모리 반도체 업황 어때?", "must_include": ["메모리"], "must_not": ["매수하세요"], "note": "산업 분석 — 수요/공급 양면 기대"}
{"id": "sp-01", "type": "strategy_portfolio", "question": "지금 반도체 비중 늘려도 돼?", "must_include": ["리스크"], "must_not": ["무조건"], "note": "전략형 — 전제 명시·반대 시나리오 필수"}
```

- [ ] **Step 2: 실패하는 테스트 작성** — `engine/tests/test_eval_metrics.py`:

```python
"""C1 평가 하네스 — metrics 오프라인 테스트 (LLM 불필요)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.metrics import question_metrics, keyword_check  # noqa: E402


def _layers():
    return [
        {"kind": "layer", "name": "triage", "round": 0,
         "data": {"route": "deep", "profile": "fact_lookup", "question_type": "fact_lookup",
                  "type_confidence": "high"}},
        {"kind": "layer", "name": "verify", "round": 0,
         "data": {"counts": {"verified": 8, "unverified": 2, "rejected": 0},
                  "retry_directives": [], "coverage_holes": 1}},
        {"kind": "layer", "name": "verify", "round": 1,
         "data": {"counts": {"verified": 9, "unverified": 1, "rejected": 0},
                  "retry_directives": [], "coverage_holes": 0}},
    ]


def _final_meta():
    return {"rounds": 1, "elapsed_s": 42.5,
            "cost": {"total_usd": 0.31},
            "audit": {"numeric_total": 10, "numeric_supported": 9,
                      "provenance_soundness": 0.8, "severe": False},
            "degraded": []}


def test_question_metrics_basic():
    m = question_metrics(_layers(), _final_meta())
    assert m["verified_ratio"] == 0.9          # 마지막 verify 라운드 기준 9/10
    assert m["numeric_supported_ratio"] == 0.9
    assert m["rounds"] == 1
    assert m["elapsed_s"] == 42.5
    assert m["cost_usd"] == 0.31
    assert m["profile"] == "fact_lookup"
    assert m["severe"] is False


def test_question_metrics_empty_layers():
    m = question_metrics([], {"rounds": 0, "elapsed_s": 1.0, "cost": {},
                              "audit": {}, "degraded": ["da"]})
    assert m["verified_ratio"] is None
    assert m["degraded"] == ["da"]


def test_keyword_check():
    ok, missing, hit = keyword_check("삼성전자 PER는 12배 수준입니다",
                                     must_include=["PER", "삼성전자"],
                                     must_not=["매수하세요"])
    assert ok and missing == [] and hit == []
    ok2, missing2, hit2 = keyword_check("지금 매수하세요",
                                        must_include=["PER"], must_not=["매수하세요"])
    assert not ok2 and missing2 == ["PER"] and hit2 == ["매수하세요"]
```

- [ ] **Step 3: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_eval_metrics.py -q` / Expected: `ModuleNotFoundError: No module named 'evals'`

- [ ] **Step 4: 구현** — `engine/evals/metrics.py`:

```python
"""C1 평가 하네스 — 코드 지표 (골든셋 실행 결과 → 레코드).

LLM 심판이 아니라 코드 지표가 본체 (스펙 §2 C1 — 동의 편향 회피):
verified_ratio(마지막 verify 라운드) · numeric_supported_ratio · provenance ·
rounds · cost · elapsed · keyword_check(골든셋 must_include/must_not).
"""
from __future__ import annotations

from typing import Any


def question_metrics(layers: list[dict], final_meta: dict) -> dict[str, Any]:
    """한 질문의 layer 스트림 + final meta → 지표 레코드."""
    verify_last: dict | None = None
    profile = None
    qtype = None
    for l in layers:
        if l.get("name") == "verify":
            verify_last = l.get("data") or {}
        elif l.get("name") == "triage":
            profile = (l.get("data") or {}).get("profile")
            qtype = (l.get("data") or {}).get("question_type")
    verified_ratio = None
    if verify_last:
        counts = verify_last.get("counts") or {}
        total = sum(counts.values())
        if total:
            verified_ratio = round(counts.get("verified", 0) / total, 3)
    audit = final_meta.get("audit") or {}
    nt, ns = audit.get("numeric_total", 0), audit.get("numeric_supported", 0)
    return {
        "profile": profile,
        "question_type": qtype,
        "verified_ratio": verified_ratio,
        "numeric_supported_ratio": round(ns / nt, 3) if nt else None,
        "provenance_soundness": audit.get("provenance_soundness"),
        "severe": audit.get("severe", False),
        "rounds": final_meta.get("rounds", 0),
        "elapsed_s": final_meta.get("elapsed_s", 0.0),
        "cost_usd": (final_meta.get("cost") or {}).get("total_usd", 0.0),
        "degraded": final_meta.get("degraded", []),
    }


def keyword_check(answer_md: str, must_include: list[str],
                  must_not: list[str]) -> tuple[bool, list[str], list[str]]:
    """골든셋 키워드 검사. 반환: (통과, 누락된 must_include, 걸린 must_not)."""
    missing = [k for k in must_include if k not in answer_md]
    hit = [k for k in must_not if k in answer_md]
    return (not missing and not hit), missing, hit
```

`engine/evals/run_eval.py` (라이브 실행기 — 테스트 대상 아님, 수동 도구):

```python
"""골든셋 실행기 — `.venv/bin/python -m evals.run_eval --limit 5 --type fact_lookup`.

질문마다 run_qa를 돌려 layer/final을 수집, metrics 레코드를 JSONL로 저장.
요약(md)에 유형별 평균 + 수동 샘플링용 무작위 5문항 답변 전문 포함.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from pathlib import Path

from evals.metrics import keyword_check, question_metrics
from orchestrator import run_qa

_HERE = Path(__file__).parent


async def _one(row: dict) -> dict:
    layers, final = [], None
    async for ev in run_qa(row["question"]):
        if ev.get("kind") == "layer":
            layers.append(ev)
        elif ev.get("kind") == "final":
            final = ev
    meta = (final or {}).get("meta") or {}
    answer = (final or {}).get("answer", "")
    rec = {"id": row["id"], "type": row["type"], "question": row["question"],
           **question_metrics(layers, meta)}
    ok, missing, hit = keyword_check(answer, row.get("must_include", []),
                                     row.get("must_not", []))
    rec.update({"keyword_ok": ok, "missing": missing, "must_not_hit": hit,
                "answer_md": answer})
    return rec


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--type", default="")
    args = ap.parse_args()
    rows = [json.loads(l) for l in (_HERE / "golden.jsonl").read_text().splitlines() if l.strip()]
    if args.type:
        rows = [r for r in rows if r["type"] == args.type]
    if args.limit:
        rows = rows[:args.limit]
    out_dir = _HERE / "out"
    out_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    records = []
    for row in rows:  # 순차 — 비용·레이트리밋 통제 (병렬 금지)
        rec = await _one(row)
        records.append(rec)
        print(f"[{rec['id']}] verified={rec['verified_ratio']} "
              f"elapsed={rec['elapsed_s']}s cost=${rec['cost_usd']}")
    (out_dir / f"report-{ts}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    # 요약 + 수동 샘플링 5문항
    lines = [f"# eval {ts} — {len(records)}문항", ""]
    for t in sorted({r["type"] for r in records}):
        sub = [r for r in records if r["type"] == t]
        vr = [r["verified_ratio"] for r in sub if r["verified_ratio"] is not None]
        lines.append(f"- **{t}** n={len(sub)} verified_avg="
                     f"{round(sum(vr)/len(vr), 3) if vr else 'n/a'} "
                     f"elapsed_avg={round(sum(r['elapsed_s'] for r in sub)/len(sub), 1)}s "
                     f"cost_avg=${round(sum(r['cost_usd'] for r in sub)/len(sub), 3)}")
    lines.append("\n## 수동 샘플링 (5문항 — 눈으로 확인)")
    for r in random.sample(records, min(5, len(records))):
        lines.append(f"\n### {r['id']} {r['question']}\n\n{r['answer_md'][:3000]}")
    (out_dir / f"report-{ts}.md").write_text("\n".join(lines))
    print(f"saved: evals/out/report-{ts}.jsonl / .md")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_eval_metrics.py -q` / Expected: `3 passed`
- [ ] **Step 6: Commit** — `git add engine/evals engine/tests/test_eval_metrics.py && git commit -m "feat(engine): C1 평가 하네스 — 골든셋 35문항 + 코드 지표 + 실행기"`

---

### Task 2: WorkflowProfile 계약 + 프로필 레지스트리

**Files:**
- Create: `engine/profiles.py`
- Test: `engine/tests/test_profiles.py`

**Interfaces:**
- Produces: `QuestionType` Literal, `WorkflowProfile` (pydantic), `PROFILES: dict[str, WorkflowProfile]`, `select_profile(question_type: str, confidence: str) -> tuple[WorkflowProfile, str]`, `upgrade_if_needed(profile, tier: int) -> tuple[WorkflowProfile, str | None]` — Task 3(triage)·Task 4(orchestrator)가 사용.

- [ ] **Step 1: 실패하는 테스트** — `engine/tests/test_profiles.py`:

```python
"""라우팅 Stage 1 — 프로필 선택·승급 규칙 (스펙 §6: 화이트리스트, 애매→풀코스, 승급 전용)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiles import PROFILES, select_profile, upgrade_if_needed  # noqa: E402


def test_registry_has_all_types_and_full():
    for k in ("fact_lookup", "event_interpretation", "stock_judgment",
              "industry_analysis", "strategy_portfolio", "full"):
        assert k in PROFILES


def test_stage1_whitelist_invariants():
    """Stage 1 금지 목록 — 어떤 프로필도 소스를 제거하지 못한다."""
    for p in PROFILES.values():
        assert p.da_mode in ("dual", "single")      # off 금지
        assert p.news_units_cap >= 1                # 뉴스 0콜 금지
        assert 1 <= p.reflect_max_rounds <= 2


def test_select_low_confidence_falls_back_to_full():
    p, reason = select_profile("fact_lookup", "low")
    assert p.name == "full" and "확신" in reason


def test_select_unknown_type_falls_back_to_full():
    p, _ = select_profile("unknown", "high")
    assert p.name == "full"


def test_select_known_type():
    p, _ = select_profile("fact_lookup", "high")
    assert p.name == "fact_lookup"
    assert p.da_mode == "single" and p.reflect_max_rounds == 1
    assert p.risk_mode == "off"


def test_upgrade_tier3_forces_full():
    """PLAN이 tier 3(판단)으로 판정하면 경량 프로필은 풀코스로 승급 (승급 전용)."""
    p, _ = select_profile("fact_lookup", "high")
    up, reason = upgrade_if_needed(p, tier=3)
    assert up.name == "full" and reason
    # 이미 무거운 프로필은 그대로 (강등 없음)
    same, r2 = upgrade_if_needed(PROFILES["full"], tier=3)
    assert same.name == "full" and r2 is None
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_profiles.py -q` / Expected: `ModuleNotFoundError: No module named 'profiles'`

- [ ] **Step 3: 구현** — `engine/profiles.py`:

```python
"""라우팅 Stage 1 — 질문 유형별 워크플로우 프로필 (스펙 docs/workflow-routing-plan.html §6).

원칙: "소스 유지, 폭 축소만". 화이트리스트 필드만 조절 —
DA 이중→단일 / 뉴스 유닛 수(최소 1) / 웹 배경지식 on·off / 섹터 메모리 on·off /
REFLECT 라운드 한도 / RISK 모드. 검증 게이트·CALC·시세는 프로필이 못 건드린다.
tier 안전 제어(tier4 차단·tier3 RISK·G2/G4)는 항상 프로필보다 우선.
애매하면(확신 낮음·unknown) 풀코스 — 오분류의 대가가 "틀림"이 아니라 "느림"이 되게.
Stage 2(kg_search 착지 후)에서 fact_lookup 고속 경로가 이 스키마 위에 얹힌다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

QuestionType = Literal[
    "fact_lookup", "event_interpretation", "stock_judgment",
    "industry_analysis", "strategy_portfolio", "unknown",
]


class WorkflowProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    da_mode: Literal["dual", "single"] = "dual"          # Stage 1: off 금지
    news_units_cap: int = 3                              # 최소 1 (0콜 금지)
    web_enabled: bool = True
    sector_rag_enabled: bool = True
    reflect_max_rounds: int = 2
    # off여도 tier>=3이면 RISK 강제 (tier 우선). auto = requires_countercase 따름
    risk_mode: Literal["force_on", "auto", "off"] = "auto"


PROFILES: dict[str, WorkflowProfile] = {
    "full": WorkflowProfile(name="full"),
    "fact_lookup": WorkflowProfile(
        name="fact_lookup", da_mode="single", news_units_cap=1,
        web_enabled=False, sector_rag_enabled=False,
        reflect_max_rounds=1, risk_mode="off"),
    "event_interpretation": WorkflowProfile(
        name="event_interpretation", da_mode="single", risk_mode="auto"),
    "stock_judgment": WorkflowProfile(name="stock_judgment", risk_mode="auto"),
    "industry_analysis": WorkflowProfile(name="industry_analysis", risk_mode="force_on"),
    "strategy_portfolio": WorkflowProfile(name="strategy_portfolio", risk_mode="force_on"),
}

_LIGHT = {"fact_lookup", "event_interpretation"}  # tier3 발견 시 승급 대상


def select_profile(question_type: str, confidence: str) -> tuple[WorkflowProfile, str]:
    """유형+확신도 → 프로필. 애매하면 풀코스 (abstain)."""
    if confidence == "low":
        return PROFILES["full"], "분류 확신 낮음 → 풀코스"
    p = PROFILES.get(question_type)
    if p is None:
        return PROFILES["full"], f"미지 유형({question_type}) → 풀코스"
    return p, f"유형 {question_type} 프로필 적용"


def upgrade_if_needed(profile: WorkflowProfile, tier: int) -> tuple[WorkflowProfile, str | None]:
    """PLAN 승급 전용 규칙 — tier 3+(판단)인데 경량 프로필이면 풀코스로. 강등 없음."""
    if tier >= 3 and profile.name in _LIGHT:
        return PROFILES["full"], f"PLAN tier={tier} 판단 질문 — {profile.name} → full 승급"
    return profile, None
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_profiles.py -q` / Expected: `7 passed`
- [ ] **Step 5: Commit** — `git commit -m "feat(engine): 라우팅 Stage 1 프로필 레지스트리 — 화이트리스트 차등 + 승급 전용 규칙"`

---

### Task 3: TRIAGE 확장 — 유형 분류 + confidence + requires_countercase

**Files:**
- Modify: `engine/stages/triage.py`
- Test: `engine/tests/test_triage_offline.py`

**Interfaces:**
- Consumes: `profiles.QuestionType`
- Produces: `TriageResult`에 신규 필드 `question_type: str = "unknown"`, `type_confidence: str = "medium"`, `requires_countercase: bool = False` — Task 4가 사용. 기존 필드·기존 호출부(`run_triage(question, history, overrides) -> tuple[TriageResult, str]`)는 불변.

- [ ] **Step 1: 실패하는 테스트** — `engine/tests/test_triage_offline.py`:

```python
"""TRIAGE 확장 오프라인 — LLM 스텁으로 분류 필드·폴백 검증."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stages.triage as triage_mod  # noqa: E402
from stages.triage import TriageResult, run_triage  # noqa: E402


class _StubRole:
    def __init__(self, payload):
        self.payload = payload

    async def run(self, prompt, instructions="", **kw):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_deep_prefix_defaults_to_unknown_full():
    """/deep 강제는 LLM 없이 — 유형은 unknown(→풀코스), countercase False."""
    r, q = asyncio.run(run_triage("/deep 삼성전자 어때?"))
    assert r.route == "deep" and q == "삼성전자 어때?"
    assert r.question_type == "unknown" and r.requires_countercase is False


def test_llm_classification_parsed(monkeypatch):
    payload = triage_mod._TriageLLM(
        route="deep", needs_fresh_data=True, reason="새 질문",
        question_type="stock_judgment", type_confidence="high",
        requires_countercase=True)
    monkeypatch.setattr(triage_mod, "Role", lambda *a, **k: _StubRole(payload))
    r, _ = asyncio.run(run_triage("삼성전자 오를까?"))
    assert r.question_type == "stock_judgment"
    assert r.type_confidence == "high"
    assert r.requires_countercase is True


def test_invalid_type_falls_back_to_unknown(monkeypatch):
    payload = triage_mod._TriageLLM(
        route="deep", needs_fresh_data=True, reason="",
        question_type="banana", type_confidence="sky", requires_countercase=False)
    monkeypatch.setattr(triage_mod, "Role", lambda *a, **k: _StubRole(payload))
    r, _ = asyncio.run(run_triage("아무거나"))
    assert r.question_type == "unknown" and r.type_confidence == "low"


def test_llm_failure_defaults(monkeypatch):
    monkeypatch.setattr(triage_mod, "Role",
                        lambda *a, **k: _StubRole(RuntimeError("down")))
    r, _ = asyncio.run(run_triage("질문"))
    assert r.route == "deep" and r.question_type == "unknown"
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_triage_offline.py -q` / Expected: FAIL (`question_type` 필드 없음 / `_TriageLLM`에 인자 없음)

- [ ] **Step 3: 구현** — `engine/stages/triage.py` 수정. `TriageResult`/`_TriageLLM`에 필드 추가, 프롬프트에 분류 지침 추가, 파싱 검증:

```python
# TriageResult에 추가 (기존 필드 아래):
    question_type: str = "unknown"       # profiles.QuestionType — 애매하면 unknown(→풀코스)
    type_confidence: str = "medium"      # high | medium | low
    requires_countercase: bool = False   # 원인론·시장영향·전망 요구 → RISK lite 신호

# _TriageLLM에 추가:
    question_type: str = "unknown"
    type_confidence: str = "medium"
    requires_countercase: bool = False
```

`_INSTR` 끝에 이어붙일 분류 지침 (기존 지침 뒤에 그대로 추가):

```python
_INSTR += """

추가로 deep 질문의 종류를 분류하라 (라우팅에 실제 사용되니 신중히):
question_type:
- fact_lookup: 수치·사실 하나를 정확히 찾으면 끝 ("영업이익 얼마야?", "PER 몇 배?")
- event_interpretation: 특정 사건·등락의 원인/의미 해석 ("오늘 왜 빠졌어?", "이 공시 무슨 의미?")
- stock_judgment: 개별 종목의 전망/매력 판단 ("오를 거 같아?", "지금 사도 될까?")
- industry_analysis: 산업/섹터 단위 분석 ("메모리 업황 어때?", "조선업 사이클 어디쯤?")
- strategy_portfolio: 사용자 행동·비중·타이밍 ("비중 늘려도 돼?", "분할매수 언제부터?")
- unknown: 위 어디에도 확실히 안 들어감 (→ 시스템이 가장 무거운 경로로 처리하니 안전)
type_confidence: high(확실) / medium / low(애매 — low면 시스템이 풀코스로 처리)
requires_countercase: 답변에 "반대 해석·다른 원인 가능성·전망"이 실질적으로 필요하면 true
  (원인 해석·전망·판단 질문은 대체로 true, 순수 과거 사실 확인은 false)
followup/smalltalk이면 question_type은 unknown으로 두면 된다."""
```

`run_triage` 파싱부 교체 (기존 `try` 블록 내부):

```python
    _VALID_TYPES = {"fact_lookup", "event_interpretation", "stock_judgment",
                    "industry_analysis", "strategy_portfolio", "unknown"}
    role = Role("plan_extract", overrides)  # mini
    try:
        r: _TriageLLM = await role.run(ctx, _INSTR, response_format=_TriageLLM)
        route = r.route if r.route in {"deep", "followup", "smalltalk"} else "deep"
        qtype = r.question_type if r.question_type in _VALID_TYPES else "unknown"
        conf = r.type_confidence if r.type_confidence in {"high", "medium", "low"} else "low"
        if qtype == "unknown":
            conf = "low"   # 미지 유형은 확신도도 낮음으로 — select_profile이 풀코스 선택
        return TriageResult(
            route=route, needs_fresh_data=bool(r.needs_fresh_data), reason=r.reason,
            question_type=qtype, type_confidence=conf,
            requires_countercase=bool(r.requires_countercase)), question
    except Exception:
        return TriageResult(route="deep", needs_fresh_data=True,
                            reason="triage 실패→deep"), question
```

(`/deep` 조기 반환은 기존 그대로 — 신규 필드는 기본값으로 unknown/medium/False가 되고, unknown은 select_profile에서 풀코스로 간다. `_VALID_TYPES`는 모듈 상수로 빼도 된다.)

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_triage_offline.py -q` / Expected: `4 passed`
- [ ] **Step 5: 기존 테스트 회귀 확인** — Run: `.venv/bin/python -m pytest tests/test_contracts.py tests/test_gates_m5.py -q` / Expected: 전부 PASS
- [ ] **Step 6: Commit** — `git commit -m "feat(engine): TRIAGE 유형 5종 분류 + 확신도 + requires_countercase — 라우팅 신호"`

---

### Task 4: 오케스트레이터 프로필 적용 (라우팅 Stage 1 본체)

**Files:**
- Create: `engine/routing.py` (순수 함수 — 테스트 대상)
- Modify: `engine/orchestrator.py` (TRIAGE 직후 + DISPATCH + REFLECT 상한 + RISK)
- Modify: `engine/stages/da.py:80-90` (mode 파라미터)
- Modify: `engine/stages/ra_external.py:421-450` (units_cap·web_enabled 파라미터)
- Modify: `engine/stages/risk.py:36-41` (force 파라미터)
- Test: `engine/tests/test_routing.py`

**Interfaces:**
- Consumes: `profiles.select_profile/upgrade_if_needed`, `TriageResult` 신규 필드 (Task 2·3)
- Produces: `routing.resolve(triage: TriageResult) -> tuple[WorkflowProfile, str]`, `routing.risk_forced(profile, triage, tier) -> bool`
- Produces: `run_da(plan, overrides, mode: str = "dual")`, `run_ra_external(plan, overrides, units_cap: int | None = None, web_enabled: bool = True)`, `run_risk(plan, table, *, round_=0, overrides=None, force: bool = False)`

- [ ] **Step 1: 실패하는 테스트** — `engine/tests/test_routing.py`:

```python
"""라우팅 Stage 1 — 프로필 해석 순수 함수 (오케스트레이터 접합부 검증)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profiles import PROFILES  # noqa: E402
from routing import resolve, risk_forced  # noqa: E402
from stages.triage import TriageResult  # noqa: E402


def _t(**kw):
    base = dict(route="deep", question_type="fact_lookup", type_confidence="high")
    base.update(kw)
    return TriageResult(**base)


def test_resolve_picks_type_profile():
    p, reason = resolve(_t())
    assert p.name == "fact_lookup" and reason


def test_resolve_low_confidence_full():
    p, _ = resolve(_t(type_confidence="low"))
    assert p.name == "full"


def test_risk_forced_by_tier():
    """tier 3은 프로필이 off여도 RISK 강제 — tier 안전 제어 우선."""
    assert risk_forced(PROFILES["fact_lookup"], _t(), tier=3) is True


def test_risk_forced_by_countercase_auto():
    t = _t(question_type="event_interpretation", requires_countercase=True)
    assert risk_forced(PROFILES["event_interpretation"], t, tier=2) is True
    t2 = _t(question_type="event_interpretation", requires_countercase=False)
    assert risk_forced(PROFILES["event_interpretation"], t2, tier=2) is False


def test_risk_off_profile_low_tier():
    assert risk_forced(PROFILES["fact_lookup"], _t(), tier=1) is False


def test_risk_force_on_profile():
    assert risk_forced(PROFILES["strategy_portfolio"], _t(question_type="strategy_portfolio"), tier=2) is True
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_routing.py -q` / Expected: `ModuleNotFoundError: No module named 'routing'`

- [ ] **Step 3: `engine/routing.py` 구현**:

```python
"""라우팅 Stage 1 — TRIAGE 결과 → 프로필 해석 (오케스트레이터 접합부, 순수 함수).

tier 안전 제어가 항상 프로필보다 우선한다 (스펙 §6 설계 보강).
"""
from __future__ import annotations

from profiles import WorkflowProfile, select_profile
from stages.triage import TriageResult


def resolve(triage: TriageResult) -> tuple[WorkflowProfile, str]:
    """deep 경로 진입 시 프로필 선택. followup/smalltalk에서는 호출하지 않는다."""
    return select_profile(triage.question_type, triage.type_confidence)


def risk_forced(profile: WorkflowProfile, triage: TriageResult, tier: int) -> bool:
    """RISK 실행 여부 — tier 3+는 무조건, force_on 프로필은 항상,
    auto는 requires_countercase(RISK lite 신호)를 따른다."""
    if tier >= 3:
        return True
    if profile.risk_mode == "force_on":
        return True
    if profile.risk_mode == "auto":
        return bool(triage.requires_countercase)
    return False
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_routing.py -q` / Expected: `6 passed`

- [ ] **Step 5: 스테이지 파라미터 추가** — 각 파일에 아래 시그니처 변경 (기본값이 현행 동작과 동일 = 무프로필 호출 호환):

`engine/stages/da.py:80` — `run_da`:

```python
async def run_da(plan: PlanPacket, overrides: dict | None = None,
                 mode: str = "dual") -> DaPacket:
    """블라인드 답변 — 전체질문 이중(GPT+Fable), 서브질문 GPT.
    mode="single"이면 q0 이중 블라인드를 GPT 단일로 축소 (프로필 Stage 1)."""
    tasks = [_one("da_gpt", "da_gpt", plan, "q0", plan.standalone_question, overrides)]
    if mode == "dual":
        tasks.append(_one("da_fable", "da_fable", plan, "q0", plan.standalone_question, overrides))
    for sq in plan.sub_questions:
        tasks.append(_one("da_gpt", "da_gpt", plan, sq.id, sq.text, overrides))
```

(이하 기존 코드 그대로 — `tasks` 조립부만 교체)

`engine/stages/ra_external.py:421` — `run_ra_external`에 `units_cap: int | None = None, web_enabled: bool = True` 파라미터 추가. 내부에서:

```python
    cap = min(units_cap, _MAX_X_UNITS) if units_cap else _MAX_X_UNITS
```

기존 `len(units) < _MAX_X_UNITS` 비교(라인 444 부근)를 `len(units) < cap`으로 교체. web_knowledge 수집 태스크 조립부는 `if web_enabled and ...`로 감싼다 (`web_slots` 소비 지점 — 라인 346 부근의 결과가 쓰이는 곳에서 gate). 파일을 열어 정확한 조립 지점을 확인하고 최소 변경으로.

`engine/stages/risk.py:36` — `run_risk`에 `force: bool = False` 추가, 게이트 교체:

```python
async def run_risk(plan: PlanPacket, table: ClaimTable, *,
                   round_: int = 0, overrides: dict | None = None,
                   force: bool = False) -> RiskPacket:
    """tier < 3이고 force 아님 → 즉시 passthrough (skipped 패킷 — 불변식 1)."""
    if plan.tier < 3 and not force:
        return RiskPacket(meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref()),
                          applicable=False)
```

- [ ] **Step 6: 오케스트레이터 접합** — `engine/orchestrator.py` 수정 4곳:

(a) import에 `from routing import resolve, risk_forced` · `from profiles import upgrade_if_needed` 추가.

(b) TRIAGE layer 방출부(라인 144-145) 교체 — deep일 때 프로필 선택·노출:

```python
    profile = None
    profile_reason = ""
    if triage.route == "deep" or (triage.route == "followup" and triage.needs_fresh_data):
        profile, profile_reason = resolve(triage)
    yield _layer("triage", {"route": triage.route, "needs_fresh_data": triage.needs_fresh_data,
                            "reason": triage.reason,
                            "question_type": triage.question_type,
                            "type_confidence": triage.type_confidence,
                            "requires_countercase": triage.requires_countercase,
                            "profile": profile.name if profile else None,
                            "profile_reason": profile_reason})
```

(c) PLAN 직후(tier4 차단 뒤) 승급 — 그리고 승급 기록:

```python
    from profiles import PROFILES
    if profile is None:
        profile = PROFILES["full"]     # smalltalk/followup 우회로가 아닌 안전 기본값
    profile, upgrade_reason = (lambda p, r: (p, r))(*upgrade_if_needed(profile, plan.tier))
    if upgrade_reason:
        yield _layer("triage", {"route": "deep", "profile": profile.name,
                                "profile_reason": upgrade_reason, "upgraded": True})
```

(승급 layer는 같은 `triage` 이름 재사용 — LAYER_NAMES 불변 제약. round 기본 0 유지.)

(d) DISPATCH 호출부(라인 182-186) 교체:

```python
    da, ra, pm = await asyncio.gather(
        _safe(run_da(plan, overrides, mode=profile.da_mode), da_fb),
        _safe(run_ra_external(plan, overrides,
                              units_cap=profile.news_units_cap,
                              web_enabled=profile.web_enabled), ra_fb),
        _safe(run_price_macro(plan)), pm_fb),
    )
```

(주의 — 위는 형태 예시. 실제 편집 시 기존 3줄에서 인자만 추가한다.)

(e) SECTOR_RAG 블록(라인 214-232)을 `if profile.sector_rag_enabled:`로 감싸고, else에 `yield _layer("sector_rag", {"skipped": True, "reason": f"프로필 {profile.name} — 섹터 메모리 생략"})` — 침묵 저하 금지.

(f) REFLECT 상한 — `while verdict.retry_directives and round_ < _MAX_ROUNDS:` (라인 327)를:

```python
    reflect_cap = min(_MAX_ROUNDS, profile.reflect_max_rounds)
    while verdict.retry_directives and round_ < reflect_cap:
```

answerability의 `round_ < _MAX_ROUNDS`(라인 296)도 `round_ < reflect_cap`으로.

(g) RISK 호출(라인 386) 교체:

```python
    risk = await run_risk(plan, table, round_=round_, overrides=overrides,
                          force=risk_forced(profile, triage, plan.tier))
```

- [ ] **Step 7: 회귀 + 신규 테스트** — Run: `.venv/bin/python -m pytest tests/test_routing.py tests/test_profiles.py tests/test_triage_offline.py tests/test_gates_m5.py tests/test_contracts.py -q` / Expected: 전부 PASS. 추가로 문법: `.venv/bin/python -c "import orchestrator"` OK.
- [ ] **Step 8: Commit** — `git commit -m "feat(engine): 프로필 라우팅 Stage 1 — TRIAGE 유형→프로필 적용 (DA/RA 폭·REFLECT 한도·RISK·섹터), 승급 전용"`

---

### Task 5: A3 유사 쿼리 dedup/재작성

**Files:**
- Create: `engine/stages/query_sim.py`
- Modify: `engine/orchestrator.py` (answerability supp 필터 라인 295, REFLECT 수집 필터 라인 345-347)
- Modify: `engine/stages/verify.py` (directive 쿼리 생성 라인 337-359)
- Test: `engine/tests/test_query_sim.py`

**Interfaces:**
- Produces: `query_sim.similar(a: str, b: str, threshold: float = 0.6) -> bool`, `query_sim.any_similar(q: str, seen: set[str]) -> bool`, `query_sim.variant(q: str, tried: set[str]) -> str | None` — orchestrator·verify가 사용.

- [ ] **Step 1: 실패하는 테스트** — `engine/tests/test_query_sim.py`:

```python
"""A3 — 유사 쿼리 감지·변형 (exact-string dedup의 공회전 방지 강화)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stages.query_sim import any_similar, similar, variant  # noqa: E402


def test_exact_and_near_duplicate():
    assert similar("삼성전자 영업이익 확인", "삼성전자 영업이익 확인")
    assert similar("삼성전자 영업이익 확인", "삼성전자 영업이익 최신 확인")  # 1토큰 차이
    assert not similar("삼성전자 영업이익", "SK하이닉스 HBM 점유율")


def test_korean_no_space_bigram():
    """토큰이 안 갈리는 붙여쓰기 — 2-gram 폴백으로 잡는다."""
    assert similar("삼성전자영업이익", "삼성전자 영업이익")


def test_any_similar():
    seen = {"삼성전자 영업이익 확인", "코스피 전망"}
    assert any_similar("삼성전자 영업이익 최신 확인", seen)
    assert not any_similar("현대차 전기차 판매량", seen)


def test_variant_produces_new_query():
    tried = {"삼성전자 영업이익 확인"}
    v = variant("삼성전자 영업이익 확인", tried)
    assert v is not None
    assert v not in tried
    assert v != "삼성전자 영업이익 확인"


def test_variant_exhausted_returns_none():
    q = "삼성전자 영업이익 확인"
    tried = {q}
    seen = set(tried)
    for _ in range(6):
        v = variant(q, seen)
        if v is None:
            break
        seen.add(v)
    assert variant(q, seen) is None
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_query_sim.py -q` / Expected: `ModuleNotFoundError`

- [ ] **Step 3: 구현** — `engine/stages/query_sim.py`:

```python
"""A3 — 재조사 쿼리 유사도 감지·변형 (dexter scratchpad 패턴의 코드 레벨 이식).

exact-string seen_queries는 "확인"→"최신 확인" 같은 미세 변형 공회전을 못 막는다.
토큰 Jaccard + (한국어 붙여쓰기 대비) 문자 2-gram Jaccard 중 max로 판정.
변형(variant)은 접미 수식어 순환 — 같은 검색의 반복 대신 각도를 바꾼다.
"""
from __future__ import annotations

_SUFFIXES = ["최신", "공시 기준", "발표 수치", "뉴스", "분기 실적"]


def _tokens(s: str) -> set[str]:
    return set(s.lower().split())


def _bigrams(s: str) -> set[str]:
    t = "".join(s.lower().split())
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similar(a: str, b: str, threshold: float = 0.6) -> bool:
    return max(_jaccard(_tokens(a), _tokens(b)),
               _jaccard(_bigrams(a), _bigrams(b))) >= threshold


def any_similar(q: str, seen: set[str]) -> bool:
    return any(similar(q, s) for s in seen)


def variant(q: str, tried: set[str]) -> str | None:
    """q와 유사한 시도가 이미 있을 때 각도를 바꾼 변형 반환. 소진되면 None."""
    base = q
    for suf in _SUFFIXES:
        cand = f"{base} {suf}".strip()
        if cand not in tried and not any_similar(cand, tried):
            return cand
    return None
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_query_sim.py -q` / Expected: `5 passed`

- [ ] **Step 5: 접합** — `engine/orchestrator.py`:
  - import: `from stages.query_sim import any_similar, variant`
  - 라인 295 `supp_queries = [q for q in ans.queries() if q not in seen_queries][:4]` → `supp_queries = [q for q in ans.queries() if not any_similar(q, seen_queries)][:4]`
  - REFLECT 수집(라인 345-347): `if q not in seen_queries:` → 아래로 교체:

```python
            for q in d.queries:
                if not any_similar(q, seen_queries):
                    research_queries.append(q)
                else:
                    v = variant(q, seen_queries | set(research_queries))
                    if v:
                        research_queries.append(v)
```

  - replan 분기의 `if q not in seen_queries:`(라인 340)도 `if not any_similar(q, seen_queries):`로.

  `engine/stages/verify.py` directive 생성부(라인 337-359)의 세 곳 `if q not in seen_queries:` → `from stages.query_sim import any_similar` 후 `if not any_similar(q, seen_queries):`로 교체.

- [ ] **Step 6: 회귀 확인** — Run: `.venv/bin/python -m pytest tests/test_query_sim.py tests/test_gates_m5.py -q && .venv/bin/python -c "import orchestrator"` / Expected: PASS
- [ ] **Step 7: Commit** — `git commit -m "feat(engine): A3 유사 쿼리 감지·변형 — REFLECT 공회전 방지 (Jaccard+2gram)"`

---

### Task 6: A4 결정론적 복구 피드백

**Files:**
- Modify: `engine/contracts/packets.py:367-372` (RetryDirective)
- Modify: `engine/stages/verify.py:331-366` (directive 생성 시 hint)
- Modify: `engine/orchestrator.py:127-128` (verify layer에 hint 노출)
- Test: `engine/tests/test_recovery_hint.py`

**Interfaces:**
- Produces: `RetryDirective.recovery_hint: str = ""` — 사유별 다음 유효 복구 단계. layer `verify.data.retry_directives[].recovery_hint`.

- [ ] **Step 1: 실패하는 테스트** — `engine/tests/test_recovery_hint.py`:

```python
"""A4 — 게이트 실패 사유별 결정론적 복구 힌트 (백지 재시작 금지)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    AtomicClaim, ClaimNorm, ClaimTable, NeededEvidence, PlanPacket, RaPacket,
)
import stages.verify as verify_mod  # noqa: E402


async def _stub_g1(role_name, judged_by, claims, evidence, overrides):
    return {c.id: ("unsupported", "offline stub", judged_by) for c in claims}


verify_mod._g1_judge = _stub_g1


def test_load_bearing_fail_hint():
    plan = PlanPacket(tier=2, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-09")
    c = AtomicClaim(id="c1", text="삼성전자 영업이익 10조", type="fact", source="ra_x",
                    load_bearing=True,
                    norm=ClaimNorm(entity="삼성전자", metric="영업이익",
                                   source_type="secondary"))
    table = ClaimTable(claims=[c])
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    research = [d for d in verdict.retry_directives if d.kind == "research"]
    assert research and research[0].recovery_hint
    assert "다른" in research[0].recovery_hint or "갭" in research[0].recovery_hint


def test_coverage_hole_hint_mentions_source():
    plan = PlanPacket(tier=1, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-09",
                      needed_evidence=[NeededEvidence(entity="삼성전자", metric="수출",
                                                      source_type="web")])
    from stages.assemble import run_assemble
    from contracts import DaPacket, PriceMacroPacket
    table = run_assemble(plan, DaPacket(), RaPacket(), PriceMacroPacket())
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    holes = [d for d in verdict.retry_directives if "[수집]" in d.reason]
    assert holes and "web" in holes[0].recovery_hint
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_recovery_hint.py -q` / Expected: FAIL (`recovery_hint` 필드 없음)

- [ ] **Step 3: 구현** — `contracts/packets.py` RetryDirective에 추가:

```python
class RetryDirective(_Strict):
    kind: Literal["research", "replan"]
    unit_id: str = "q0"
    queries: list[str] = Field(default_factory=list)  # research: 신규 확장 쿼리 강제
    reason: str = ""
    recovery_hint: str = ""   # A4: 실패 사유별 다음 유효 복구 단계 (코드가 결정)
```

`stages/verify.py` directive 생성 3곳에 hint 추가:

```python
        # 사유① — load-bearing 실패
                directives.append(RetryDirective(
                    kind="research", unit_id=c.unit_id, queries=[q],
                    reason=f"[검증] load-bearing 미지지: {c.text[:80]}",
                    recovery_hint="같은 사실을 다른 표현·다른 매체로 재검색. "
                                  "재검색도 무근거면 갭 인정(unobtainable)이 정답 — 재주장 금지"))
        # 사유② — 미해소 충돌
                    directives.append(RetryDirective(
                        kind="research", unit_id=src.unit_id, queries=[q],
                        reason=f"[검증] 미해소 충돌: {cf.claim_key}",
                        recovery_hint="두 값의 발표 시점·기준(연결/별도, 분기/연간)을 명시해 검색 — "
                                      "충돌은 대개 기준 차이"))
        # 사유③ — 커버리지 구멍
                directives.append(RetryDirective(
                    kind="research", unit_id="q0", queries=[q],
                    reason=f"[수집] 커버리지 구멍: {ce.slot.entity}/{ce.slot.metric}",
                    recovery_hint=f"source_type={ce.slot.source_type} 계열 우선, "
                                  "없으면 대체 소스(news↔web) 순서로"))
```

`orchestrator.py` `_verify_layer_data`(라인 127-128)에 hint 노출:

```python
        "retry_directives": [{"kind": d.kind, "reason": d.reason, "queries": d.queries,
                              "recovery_hint": d.recovery_hint}
                             for d in verdict.retry_directives],
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_recovery_hint.py tests/test_contracts.py tests/test_gates_m5.py -q` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(engine): A4 복구 힌트 — 게이트 실패 사유별 다음 단계를 코드가 명시 (RetryDirective.recovery_hint)"`

---

### Task 7: A1 역할 재제시 (플래그, 기본 off)

**Files:**
- Modify: `engine/app/settings.py` (`reaudit_mode: str = "off"` — env `REAUDIT_MODE`)
- Modify: `engine/contracts/packets.py:359-364` (ClaimVerdict)
- Modify: `engine/stages/verify.py` (재감사 패스)
- Test: `engine/tests/test_reaudit.py`

**Interfaces:**
- Produces: `ClaimVerdict.reaudit: Literal["", "upheld", "overturned"] = ""`. `settings.reaudit_mode == "on"`일 때만 동작. 재감사 함수 `_reaudit_judge(role_name, judged_by, claims, evidence, overrides) -> dict[str, tuple[str, str]]` (claim_id → (verdict, note)) — 테스트가 몽키패치.

- [ ] **Step 1: 실패하는 테스트** — `engine/tests/test_reaudit.py`:

```python
"""A1 — 역할 재제시 재감사 (arXiv 2606.05976). 플래그 off 기본, on일 때 승급 경로."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402
from contracts import AtomicClaim, ClaimNorm, ClaimTable, PlanPacket, RaPacket  # noqa: E402
import stages.verify as verify_mod  # noqa: E402


async def _g1_unsupported(role_name, judged_by, claims, evidence, overrides):
    return {c.id: ("unsupported", "stub", judged_by) for c in claims}


async def _reaudit_supported(role_name, judged_by, claims, evidence, overrides):
    return {c.id: ("supported", "재감사에서 근거 확인") for c in claims}


def _fixtures():
    plan = PlanPacket(tier=2, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-09")
    c = AtomicClaim(id="c1", text="삼성전자 HBM 공급 개시", type="fact", source="ra_x",
                    load_bearing=True,
                    norm=ClaimNorm(entity="삼성전자", metric="HBM",
                                   source_type="secondary"))
    return plan, ClaimTable(claims=[c])


def test_flag_off_no_reaudit(monkeypatch):
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_unsupported)
    monkeypatch.setattr(settings, "reaudit_mode", "off", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    v = verdict.verdicts[0]
    assert v.final == "unverified" and v.reaudit == ""


def test_flag_on_overturn(monkeypatch):
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_unsupported)
    monkeypatch.setattr(verify_mod, "_reaudit_judge", _reaudit_supported)
    monkeypatch.setattr(settings, "reaudit_mode", "on", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    v = verdict.verdicts[0]
    assert v.final == "verified" and v.reaudit == "overturned"


def test_flag_on_upheld(monkeypatch):
    async def _still_bad(role_name, judged_by, claims, evidence, overrides):
        return {c.id: ("unsupported", "여전히 무근거") for c in claims}
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_unsupported)
    monkeypatch.setattr(verify_mod, "_reaudit_judge", _still_bad)
    monkeypatch.setattr(settings, "reaudit_mode", "on", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    v = verdict.verdicts[0]
    assert v.final == "unverified" and v.reaudit == "upheld"
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_reaudit.py -q` / Expected: FAIL (`reaudit` 필드/`_reaudit_judge` 없음)

- [ ] **Step 3: 구현** — `app/settings.py`의 Settings에 `reaudit_mode: str = "off"` 필드 추가 (pydantic-settings — env `REAUDIT_MODE` 자동 매핑, 기존 필드 명명 규칙 확인 후 동일하게). `contracts/packets.py` ClaimVerdict에 `reaudit: Literal["", "upheld", "overturned"] = ""` 추가. `stages/verify.py`에 재감사 함수 + 접합:

```python
_REAUDIT_INSTR = """아래 [저장된 메모]는 이전 세션에서 기록된 주장이다. 지금 [수집 증거]와 대조해
각 주장이 지지되는지 독립적으로 판정하라. 이 주장이 맞다/틀리다는 선입견 없이 중립적으로.
- supported: 증거가 주장을 직접 지지 / unsupported: 모순 또는 전혀 무근거 / uncertain: 애매
note에 한 줄 근거."""


async def _reaudit_judge(role_name: str, judged_by: str, claims: list[AtomicClaim],
                         evidence: str, overrides: dict | None) -> dict[str, tuple[str, str]]:
    """A1 역할 재제시 — 실패 claim을 '저장된 메모'(외부 역할)로 중립 재제시해 재감사.
    자기불신 프레이밍 금지 (과교정 방지 — 원 논문 70% 과교정 경고)."""
    if not claims:
        return {}
    view = "\n".join(f"- id={c.id} {c.text}" for c in claims)
    role = Role(role_name, overrides)
    try:
        val: _Verdicts = await role.run(
            f"[저장된 메모]\n{view}", _REAUDIT_INSTR,
            response_format=_Verdicts, effort="medium", cache_prefix=evidence)
    except Exception:
        return {}
    valid = {"supported", "unsupported", "uncertain"}
    return {v.claim_id: (v.verdict if v.verdict in valid else "uncertain", v.note)
            for v in val.verdicts}
```

`run_verify` 집계 후 · REFLECT 판단 전에 접합 (verdicts 리스트 완성 직후):

```python
    # ── A1 역할 재제시 (REAUDIT_MODE=on, A/B) — load-bearing 실패 claim만
    from app.settings import settings as _settings
    if getattr(_settings, "reaudit_mode", "off") == "on" and load_bearing_failed:
        pool = load_bearing_failed[:8]
        fable_made = [c for c in pool if c.source == "da_fable"]
        others = [c for c in pool if c.source != "da_fable"]
        re_map: dict[str, tuple[str, str]] = {}
        re_map.update(await _reaudit_judge("verifier", "fable", others, evidence, overrides))
        re_map.update(await _reaudit_judge("verifier_cross", "gpt", fable_made, evidence, overrides))
        by_id = {v.claim_id: v for v in verdicts}
        for cid, (rv, rnote) in re_map.items():
            v = by_id.get(cid)
            if v is None:
                continue
            if rv == "supported" and v.gates.g3 != "fail" and v.gates.g4 != "fail":
                v.final = "verified"
                v.reaudit = "overturned"
                v.note = (v.note + f"; 재감사 승급: {rnote}")[:300]
            else:
                v.reaudit = "upheld"
        load_bearing_failed = [c for c in pool
                               if by_id.get(c.id) and by_id[c.id].final != "verified"] \
                              + load_bearing_failed[8:]
```

(주의: G3/G4 rejected는 재감사로 못 뒤집는다 — 시점·지시어는 코드 게이트. ClaimVerdict는 pydantic strict라 mutation 가능 여부 확인 — `_Strict`는 frozen 아님, 직접 할당 가능.)

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_reaudit.py tests/test_gates_m5.py -q` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(engine): A1 역할 재제시 재감사 — REAUDIT_MODE 플래그 (기본 off, A/B용)"`

---

### Task 8: A2 반증 자세 (플래그, 기본 off)

**Files:**
- Modify: `engine/app/settings.py` (`refute_mode: str = "off"` — env `REFUTE_MODE`)
- Modify: `engine/stages/verify.py` (반증 패스)
- Test: `engine/tests/test_refute.py`

**Interfaces:**
- Produces: `_refute_judge(role_name, claims, evidence, overrides) -> dict[str, tuple[bool, str]]` (claim_id → (refuted, note)). 반증 성공 시 해당 verdict `final="unverified"`, note에 "반증:" 접두 기록. `settings.refute_mode == "on"`일 때만.

- [ ] **Step 1: 실패하는 테스트** — `engine/tests/test_refute.py`:

```python
"""A2 — 반증 자세 검증 (동의 편향 완화): supported로 통과한 load-bearing claim에 반박 시도."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402
from contracts import AtomicClaim, ClaimNorm, ClaimTable, PlanPacket, RaPacket  # noqa: E402
import stages.verify as verify_mod  # noqa: E402


async def _g1_supported(role_name, judged_by, claims, evidence, overrides):
    return {c.id: ("supported", "stub", judged_by) for c in claims}


def _fixtures():
    plan = PlanPacket(tier=3, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-09")
    c = AtomicClaim(id="c1", text="삼성전자 4분기 흑자 전환", type="fact", source="ra_x",
                    load_bearing=True,
                    norm=ClaimNorm(entity="삼성전자", metric="흑자",
                                   source_type="secondary"))
    return plan, ClaimTable(claims=[c])


def test_flag_off_no_refute(monkeypatch):
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_supported)
    monkeypatch.setattr(settings, "refute_mode", "off", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    assert verdict.verdicts[0].final == "verified"


def test_flag_on_refuted_downgrades(monkeypatch):
    async def _refutes(role_name, claims, evidence, overrides):
        return {c.id: (True, "증거의 시점이 주장과 다름") for c in claims}
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_supported)
    monkeypatch.setattr(verify_mod, "_refute_judge", _refutes)
    monkeypatch.setattr(settings, "refute_mode", "on", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    v = verdict.verdicts[0]
    assert v.final == "unverified" and "반증" in v.note


def test_flag_on_stands(monkeypatch):
    async def _no_refute(role_name, claims, evidence, overrides):
        return {c.id: (False, "반박 근거 없음") for c in claims}
    monkeypatch.setattr(verify_mod, "_g1_judge", _g1_supported)
    monkeypatch.setattr(verify_mod, "_refute_judge", _no_refute)
    monkeypatch.setattr(settings, "refute_mode", "on", raising=False)
    plan, table = _fixtures()
    verdict = asyncio.run(verify_mod.run_verify(plan, table, RaPacket(), []))
    assert verdict.verdicts[0].final == "verified"
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_refute.py -q` / Expected: FAIL

- [ ] **Step 3: 구현** — settings에 `refute_mode: str = "off"`. `stages/verify.py`:

```python
class _R(_SO):
    claim_id: str
    refuted: bool = False
    note: str = ""


class _Refutes(_SO):
    judgements: list[_R] = Field(default_factory=list)


_REFUTE_INSTR = """너는 반증 담당이다. 아래 각 주장이 **틀렸다고 가정**하고 [수집 증거]에서
반박 근거를 적극적으로 찾아라 — 시점 불일치, 주체 혼동, 수치 기준 차이, 모순 보도.
반박 근거를 실제로 찾았을 때만 refuted=true (못 찾으면 false — 추측 금지). note에 근거 한 줄."""


async def _refute_judge(role_name: str, claims: list[AtomicClaim],
                        evidence: str, overrides: dict | None) -> dict[str, tuple[bool, str]]:
    """A2 — 동의 편향 완화: supported 통과분에 반증 역할 별도 패스."""
    if not claims:
        return {}
    view = "\n".join(f"- id={c.id} {c.text}" for c in claims)
    try:
        val: _Refutes = await Role(role_name, overrides).run(
            f"[반증 대상 주장]\n{view}", _REFUTE_INSTR,
            response_format=_Refutes, effort="medium", cache_prefix=evidence)
    except Exception:
        return {}
    return {j.claim_id: (bool(j.refuted), j.note) for j in val.judgements}
```

`run_verify` 접합 — A1 블록 뒤 (verdicts 완성 후):

```python
    # ── A2 반증 자세 (REFUTE_MODE=on, A/B) — supported로 통과한 load-bearing만
    if getattr(_settings, "refute_mode", "off") == "on":
        by_id = {v.claim_id: v for v in verdicts}
        passed = [c for c in table.claims
                  if c.load_bearing and by_id.get(c.id)
                  and by_id[c.id].final == "verified"
                  and by_id[c.id].gates.g1 == "pass"][:8]
        # 반증 심판은 G1 심판의 반대 모델 — 같은 모델이 자기 판정을 재확인하는 편향 회피
        fable_judged = [c for c in passed if by_id[c.id].judged_by == "fable"]
        gpt_judged = [c for c in passed if by_id[c.id].judged_by == "gpt"]
        r_map: dict[str, tuple[bool, str]] = {}
        r_map.update(await _refute_judge("verifier_cross", fable_judged, evidence, overrides))
        r_map.update(await _refute_judge("verifier", gpt_judged, evidence, overrides))
        for cid, (refuted, rnote) in r_map.items():
            if refuted:
                v = by_id[cid]
                v.final = "unverified"
                v.note = (v.note + f"; 반증: {rnote}")[:300]
                c = next((x for x in table.claims if x.id == cid), None)
                if c is not None and c.load_bearing:
                    load_bearing_failed.append(c)
```

(A2 반증으로 강등된 claim은 load_bearing_failed에 합류 → REFLECT 사유①이 재조사 — 반증이 재검색으로 이어지는 자연 결합.)

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_refute.py tests/test_reaudit.py tests/test_gates_m5.py -q` / Expected: PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(engine): A2 반증 자세 검증 — REFUTE_MODE 플래그 (동의 편향 완화, 기본 off)"`

---

### Task 9: 전체 회귀 + 문서 현행화 + 가시화

**Files:**
- Modify: `docs/workflow-review.html` (현행 설명서 — 사용자 필수 지시)
- Modify: `public/html/index.html` (목록 설명)
- Modify: `docs/workflow-routing-plan.html` (§8 구현 상태)

- [ ] **Step 1: 전체 오프라인 테스트** — Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_eval_metrics.py tests/test_profiles.py tests/test_triage_offline.py tests/test_routing.py tests/test_query_sim.py tests/test_recovery_hint.py tests/test_reaudit.py tests/test_refute.py tests/test_contracts.py tests/test_gates_m5.py tests/test_registry.py -q` / Expected: 전부 PASS
- [ ] **Step 2: 스모크 (라이브 1문항)** — Run: `.venv/bin/python -m evals.run_eval --limit 1 --type fact_lookup` / Expected: triage layer에 `profile: "fact_lookup"`, 완주 + 레코드 저장. (API 키 없으면 skip하고 보고에 명시)
- [ ] **Step 3: workflow-review.html 현행화** — 사용자 지시 (memory: update-workflow-review-after-ship). 반영 내용: ⓪ TRIAGE 카드에 유형 5종 분류·confidence·requires_countercase 추가, TRIAGE 뒤 "프로필 선택" 노드 신설(화이트리스트 차등·승급 전용·애매→풀코스), REFLECT 카드에 유사 쿼리 감지·recovery_hint, VERIFY 카드에 A1/A2 플래그(기본 off, A/B용) 설명, 상단 howto에 "2026-07-09 라우팅 Stage 1" 변경 요약 추가. 그래프 flow 다이어그램의 TRIAGE 노드 설명도 갱신.
- [ ] **Step 4: 목록·계획 문서 갱신** — `public/html/index.html`의 workflow-review 항목 설명을 "라우팅 Stage 1 반영 (2026-07-09)"로, `docs/workflow-routing-plan.html` §8에 "P1 구현 완료 항목" 체크 추가.
- [ ] **Step 5: 스크린샷 검증** — playwright로 workflow-review.html 캡처 후 눈 확인 (memory: verify-ui-with-screenshots).
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(engine): P1 에이전틱 워크플로우 개선 — 라우팅 Stage 1 + REFLECT 질 개선 + A1/A2 플래그 + C1 하네스, 문서 현행화"`

---

## Self-Review

- **스펙 커버리지**: C1(Task 1) · 라우팅 Stage 1(Task 2-4: 분류기·프로필·화이트리스트·승급 전용·tier 우선·skipped 유지·layer 노출) · A3(Task 5) · A4(Task 6) · A1(Task 7 플래그) · A2(Task 8 플래그) · workflow-review 현행화(Task 9). Stage 2(kg 후 고속 경로)·D2(RA §3 병합)·C2/C3은 P1 범위 밖 — 스펙과 일치.
- **테스트 매트릭스**: 프로필 불변식(whitelist), tier 우선(risk_forced), 승급 전용, 오분류 폴백(unknown/low→full) 커버. "5유형 × 불변식" — test_profiles의 전 프로필 루프가 담당.
- **타입 일관성**: `TriageResult.question_type/type_confidence/requires_countercase` (Task 3 정의 = Task 4 test 사용), `WorkflowProfile.da_mode/news_units_cap/web_enabled/sector_rag_enabled/reflect_max_rounds/risk_mode` (Task 2 = Task 4), `RetryDirective.recovery_hint` (Task 6), `ClaimVerdict.reaudit` (Task 7) — 확인됨.
- **주의**: Task 4 Step 5-6의 orchestrator/ra_external 편집은 라인 번호가 선행 태스크로 밀릴 수 있음 — 편집 전 반드시 해당 파일을 Read로 현재 상태 확인. `settings.py`는 열어서 기존 필드 스타일에 맞출 것.
