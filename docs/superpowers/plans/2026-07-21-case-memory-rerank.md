# 과거사례 지식층 (Case-Memory) — Plan 2: LLM 구조 리랭크 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 결정적 표면 검색(Plan 1)이 뽑은 후보 국면들을, **오늘 signal 조합의 구조적 정합성**으로 LLM이 재정렬하는 리랭크 단계(설계 §5-5단)를 추가한다. 표면 유사(키워드 겹침) vs 구조 유사(국면 시퀀스상 말이 되나)를 분리하는 CBR 핵심 방어.

**Architecture:** LLM 클라이언트에 하드 의존하지 않게 **`llm_fn` 콜러블 주입식**. `engine/casemem/rerank.py`에 `rerank_matches()` — 후보별 구조 점수(0~1)를 LLM에게 받아 `surface*ws + structural*wl`로 블렌드 후 재정렬. **never-raise**: llm_fn 예외·형식오류·타임아웃이면 표면 순서 그대로 폴백(관측성 카운트만). `query_case_memory`에 optional `llm_fn` 추가 — None이면 Plan 1 결정적 동작 그대로(하위호환). 실제 Claude 배선은 Plan 3.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest. LLM 프로바이더 비의존(주입).

## Global Constraints

- **결정성 보존**: llm_fn=None이면 Plan 1과 바이트 동일 동작. 리랭크는 순수 부가.
- **never-raise**: llm_fn이 던지거나 형식 안 맞으면 표면 순서 폴백. 예외 전파·무성 누락 금지. — 설계 §10
- **룩어헤드 차단 유지**: 리랭크는 이미 as-of 필터된 후보만 받는다(Plan 1이 차단). LLM엔 **국면 라벨·identifying_signals·오늘 signal만** 준다 — `outcome`·미래 국면 근거 절대 전달 금지. — 설계 §4.2·§7
- **LLM 자가확신도로 규칙 가중 금지**: 구조 점수는 **랭킹 재정렬**에만 쓴다. 확신도·assessment 산출 아님. — 설계 §6·§7
- **as-of는 여전히 유일 시계**: 리랭크가 시간 판단을 새로 하지 않는다.
- 프롬프트는 결정적으로 재현 가능해야(테스트): llm_fn은 `(prompt:str)->str` 단순 계약, 우리가 파싱.

---

## File Structure

- Create: `engine/casemem/rerank.py` — `LlmFn` 타입 별칭, `build_rerank_prompt()`, `parse_rerank_response()`, `rerank_matches()`.
- Modify: `engine/casemem/contracts.py` — `CaseMatch`에 `surface_score`·`structural_score`·`reranked: bool` 추가(관측성). `CaseQueryResult`에 `rerank_used: bool`·`rerank_failed: bool` 추가.
- Modify: `engine/casemem/query.py` — `query_case_memory(..., llm_fn=None)` 파라미터 + 리랭크 호출.
- Create: `engine/tests/test_casemem_rerank.py` — 프롬프트·파싱·리랭크·폴백 테스트.
- Modify: `engine/tests/test_casemem_query.py` — llm_fn 주입 경로 테스트.

---

### Task 1: CaseMatch/CaseQueryResult 관측성 필드 확장

**Files:**
- Modify: `engine/casemem/contracts.py`
- Test: `engine/tests/test_casemem_contracts.py` (기존 파일에 append)

**Interfaces:**
- Produces (수정): `CaseMatch`에 `surface_score: float = 0.0`, `structural_score: float | None = None`, `reranked: bool = False`. `CaseQueryResult`에 `rerank_used: bool = False`, `rerank_failed: bool = False`.
- 기존 `score` 필드는 **최종 랭킹 점수**로 유지(리랭크 후엔 블렌드값). `surface_score`는 표면 원점수 보존.

- [ ] **Step 1: Write the failing test**

```python
# append to engine/tests/test_casemem_contracts.py
def test_casematch_observability_defaults():
    from casemem.contracts import CaseMatch, CaseQueryResult
    m = CaseMatch(episode_id="e", matched_phase_order=0, score=0.5)
    assert m.surface_score == 0.0 and m.structural_score is None and m.reranked is False
    r = CaseQueryResult(as_of="2018-01-01", sector="memory", scanned=0,
                        dropped_after_as_of=0, dropped_sector=0)
    assert r.rerank_used is False and r.rerank_failed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_contracts.py::test_casematch_observability_defaults -v`
Expected: FAIL — `TypeError`/`ValidationError` (unknown field surface_score) 또는 AttributeError.

- [ ] **Step 3: Write minimal implementation**

`engine/casemem/contracts.py`의 `CaseMatch`를 수정:

```python
class CaseMatch(BaseModel):
    episode_id: str
    matched_phase_order: int
    score: float                          # 최종 랭킹 점수(리랭크 후엔 블렌드)
    surface_score: float = 0.0            # 표면 원점수 보존(관측성)
    structural_score: float | None = None # LLM 구조 점수(리랭크 시에만)
    reranked: bool = False
    next_phase_labels: list[str] = Field(default_factory=list)   # =예측
    evidence: list[Evidence] = Field(default_factory=list)
```

`CaseQueryResult`에 두 필드 추가:

```python
class CaseQueryResult(BaseModel):
    as_of: str
    sector: str
    matches: list[CaseMatch] = Field(default_factory=list)
    scanned: int
    dropped_after_as_of: int
    dropped_sector: int
    rerank_used: bool = False             # llm_fn 주입되어 리랭크 시도됨
    rerank_failed: bool = False           # 리랭크 시도했으나 폴백됨(관측성)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_contracts.py -v`
Expected: PASS (전체)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/contracts.py engine/tests/test_casemem_contracts.py
git commit -m "feat(casemem): CaseMatch/CaseQueryResult 리랭크 관측성 필드"
```

---

### Task 2: 프롬프트 빌더 + 응답 파서 (LLM 비의존, 순수 함수)

**Files:**
- Create: `engine/casemem/rerank.py`
- Test: `engine/tests/test_casemem_rerank.py`

**Interfaces:**
- Consumes: `CaseEpisode`, `CaseMatch` (Plan 1).
- Produces:
  - `LlmFn = Callable[[str], str]` (타입 별칭).
  - `def build_rerank_prompt(signals: list[str], candidates: list[tuple[CaseMatch, str, list[str]]]) -> str` — candidates=`(match, phase_label, phase_signals)`. 각 후보에 index 부여, 오늘 signal과 국면 identifying_signals만 노출(outcome·미래 금지). "각 후보를 구조적 정합성 0~1로 채점, JSON `[{"i":int,"s":float}]`만 출력" 지시.
  - `def parse_rerank_response(text: str, n: int) -> dict[int, float]` — 응답에서 JSON 배열 추출, `{index: score}` 반환. 파싱 불가·범위 밖(0~1 아님)·index 밖은 스킵. 완전 실패 시 `{}`.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_casemem_rerank.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseMatch
from casemem.rerank import build_rerank_prompt, parse_rerank_response


def _cand(eid, order, label, signals):
    return (CaseMatch(episode_id=eid, matched_phase_order=order, score=0.5,
                      surface_score=0.5), label, signals)


def test_prompt_exposes_signals_not_outcome():
    p = build_rerank_prompt(
        ["재고일수 상승"],
        [_cand("mem-2018", 1, "inventory_build", ["재고일수 상승", "고객 재고조정"])])
    assert "재고일수 상승" in p
    assert "inventory_build" in p
    assert "outcome" not in p.lower()          # 결과 누출 금지
    assert "0" in p and "1" in p               # 채점 범위 지시 존재


def test_parse_valid_json():
    got = parse_rerank_response('[{"i":0,"s":0.9},{"i":1,"s":0.2}]', n=2)
    assert got == {0: 0.9, 1: 0.2}


def test_parse_tolerates_prose_wrapping():
    got = parse_rerank_response('여기 결과: [{"i":0,"s":0.7}] 끝', n=1)
    assert got == {0: 0.7}


def test_parse_drops_out_of_range_and_bad_index():
    got = parse_rerank_response('[{"i":0,"s":1.5},{"i":9,"s":0.5},{"i":1,"s":0.3}]', n=2)
    assert got == {1: 0.3}                       # 1.5(범위밖)·index9(밖) 제외


def test_parse_total_garbage_returns_empty():
    assert parse_rerank_response("no json here", n=2) == {}
    assert parse_rerank_response("", n=2) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_rerank.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'casemem.rerank'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/casemem/rerank.py
"""LLM 구조 리랭크 — 표면 후보를 signal 조합의 구조적 정합성으로 재정렬(설계 §5-5).
LLM 프로바이더 비의존: (prompt:str)->str 콜러블 주입. never-raise 폴백."""
from __future__ import annotations

import json
import re
from typing import Callable

from casemem.contracts import CaseEpisode, CaseMatch

LlmFn = Callable[[str], str]

_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def build_rerank_prompt(signals: list[str],
                        candidates: list[tuple[CaseMatch, str, list[str]]]) -> str:
    lines = [
        "너는 메모리 반도체 사이클 분석가다. 오늘 관측된 signal 집합과, 과거 사례의 "
        "후보 국면들이 주어진다. 각 후보에 대해 '오늘 signal 조합이 이 국면의 구조와 "
        "얼마나 정합적인가'를 0~1로 채점하라(표면 단어 겹침이 아니라 구조적 의미).",
        "",
        "오늘 signal:",
    ]
    for s in signals:
        lines.append(f"  - {s}")
    lines.append("")
    lines.append("후보 국면:")
    for i, (_m, label, ph_signals) in enumerate(candidates):
        lines.append(f"  [{i}] 국면={label}")
        for ps in ph_signals:
            lines.append(f"        · {ps}")
    lines += [
        "",
        '오직 JSON 배열만 출력: [{"i":<index>,"s":<0~1 점수>}, ...]. 설명 금지.',
    ]
    return "\n".join(lines)


def parse_rerank_response(text: str, n: int) -> dict[int, float]:
    if not text:
        return {}
    m = _ARRAY.search(text)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[int, float] = {}
    if not isinstance(arr, list):
        return {}
    for item in arr:
        try:
            i = int(item["i"])
            s = float(item["s"])
        except Exception:  # noqa: BLE001
            continue
        if 0 <= i < n and 0.0 <= s <= 1.0:
            out[i] = s
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_rerank.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/rerank.py engine/tests/test_casemem_rerank.py
git commit -m "feat(casemem): 리랭크 프롬프트 빌더 + 관대한 JSON 파서(LLM 비의존)"
```

---

### Task 3: rerank_matches — 블렌드 재정렬 + never-raise 폴백

**Files:**
- Modify: `engine/casemem/rerank.py`
- Test: `engine/tests/test_casemem_rerank.py`

**Interfaces:**
- Consumes: `build_rerank_prompt`/`parse_rerank_response`(Task2), `CaseEpisode`/`CaseMatch`(Plan1), `LlmFn`.
- Produces: `def rerank_matches(matches: list[CaseMatch], signals: list[str], episodes_by_id: dict[str, CaseEpisode], llm_fn: LlmFn, *, ws: float = 0.4, wl: float = 0.6) -> tuple[list[CaseMatch], bool]` — 반환 `(재정렬된 matches, failed)`. 각 match의 matched phase의 identifying_signals를 episodes_by_id에서 찾아 후보 구성 → 프롬프트 → llm_fn → 파싱. 파싱된 후보만 `structural_score` 세팅·`score = ws*surface + wl*structural`·`reranked=True`. **파싱 0건이거나 llm_fn 예외면 원본 matches 그대로 반환 + failed=True**. 부분 성공(일부만 채점)이면 채점된 것만 블렌드, 나머지 surface 유지, failed=False.

- [ ] **Step 1: Write the failing test**

```python
# append to engine/tests/test_casemem_rerank.py
from casemem.contracts import CaseEpisode, Phase
from casemem.rerank import rerank_matches


def _ep(eid, order, label, signals):
    return CaseEpisode(id=eid, sector="memory", title=eid,
                       event_time="2018-01-01", knowable_at="2018-01-01",
                       phases=[Phase(order=order, label=label,
                                     period_start="2018-01-01", knowable_at="2018-01-01",
                                     identifying_signals=signals)])


def test_rerank_reorders_by_structural_score():
    # surface로는 A>B지만 구조 점수로 B>A 뒤집힘
    a = CaseMatch(episode_id="A", matched_phase_order=0, score=0.6, surface_score=0.6)
    b = CaseMatch(episode_id="B", matched_phase_order=0, score=0.5, surface_score=0.5)
    eps = {"A": _ep("A", 0, "capex_expansion", ["capex up"]),
           "B": _ep("B", 0, "inventory_build", ["inventory up"])}
    # A(index0)=0.1, B(index1)=0.9 로 응답하는 페이크 LLM
    def fake(prompt): return '[{"i":0,"s":0.1},{"i":1,"s":0.9}]'
    out, failed = rerank_matches([a, b], ["x"], eps, fake, ws=0.4, wl=0.6)
    assert failed is False
    assert out[0].episode_id == "B"                # 구조로 역전
    assert out[0].reranked is True
    assert abs(out[0].score - (0.4*0.5 + 0.6*0.9)) < 1e-9
    assert out[0].structural_score == 0.9


def test_rerank_llm_raises_falls_back():
    a = CaseMatch(episode_id="A", matched_phase_order=0, score=0.6, surface_score=0.6)
    eps = {"A": _ep("A", 0, "capex_expansion", ["capex up"])}
    def boom(prompt): raise RuntimeError("timeout")
    out, failed = rerank_matches([a], ["x"], eps, boom)
    assert failed is True
    assert out == [a]                              # 원본 순서·값 보존
    assert out[0].reranked is False


def test_rerank_empty_parse_falls_back():
    a = CaseMatch(episode_id="A", matched_phase_order=0, score=0.6, surface_score=0.6)
    eps = {"A": _ep("A", 0, "capex_expansion", ["capex up"])}
    out, failed = rerank_matches([a], ["x"], eps, lambda p: "garbage")
    assert failed is True
    assert out[0].reranked is False


def test_rerank_empty_matches_noop():
    out, failed = rerank_matches([], ["x"], {}, lambda p: "[]")
    assert out == [] and failed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_rerank.py -k rerank_ -v`
Expected: FAIL — `ImportError: cannot import name 'rerank_matches'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to engine/casemem/rerank.py

def _phase_signals(ep: CaseEpisode, order: int) -> list[str]:
    for p in ep.phases:
        if p.order == order:
            return p.identifying_signals
    return []


def rerank_matches(matches: list[CaseMatch], signals: list[str],
                   episodes_by_id: dict[str, CaseEpisode], llm_fn: LlmFn,
                   *, ws: float = 0.4, wl: float = 0.6) -> tuple[list[CaseMatch], bool]:
    if not matches:
        return matches, False
    candidates: list[tuple[CaseMatch, str, list[str]]] = []
    for m in matches:
        ep = episodes_by_id.get(m.episode_id)
        label = ""
        ph_signals: list[str] = []
        if ep is not None:
            for p in ep.phases:
                if p.order == m.matched_phase_order:
                    label, ph_signals = p.label, p.identifying_signals
                    break
        candidates.append((m, label, ph_signals))

    prompt = build_rerank_prompt(signals, candidates)
    try:
        raw = llm_fn(prompt)
    except Exception:  # noqa: BLE001 — never-raise, 표면 순서 폴백
        return matches, True
    scores = parse_rerank_response(raw, len(candidates))
    if not scores:
        return matches, True

    out: list[CaseMatch] = []
    for i, m in enumerate(matches):
        if i in scores:
            st = scores[i]
            m = m.model_copy(update={
                "structural_score": st,
                "score": ws * m.surface_score + wl * st,
                "reranked": True,
            })
        out.append(m)
    out.sort(key=lambda x: x.score, reverse=True)
    return out, False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_rerank.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/rerank.py engine/tests/test_casemem_rerank.py
git commit -m "feat(casemem): rerank_matches — 블렌드 재정렬 + never-raise 폴백"
```

---

### Task 4: query_case_memory에 llm_fn 배선 (하위호환)

**Files:**
- Modify: `engine/casemem/query.py`
- Modify: `engine/casemem/search.py` — `search_cases`가 `CaseMatch.surface_score`도 채우도록(현재 `score`만).
- Test: `engine/tests/test_casemem_query.py`

**Interfaces:**
- Consumes: `rerank_matches`(Task3), `search_cases`(Plan1).
- Produces (수정): `def query_case_memory(store, *, signals, as_of, sector="memory", k=5, llm_fn=None) -> CaseQueryResult`. llm_fn=None이면 Plan1 동작(rerank_used=False). 있으면 search 후 rerank_matches 호출, `rerank_used=True`, 폴백 시 `rerank_failed=True`.
- `search_cases`: 각 CaseMatch 생성 시 `surface_score=score`도 세팅(리랭크가 블렌드에 씀).

- [ ] **Step 1: Write the failing test**

```python
# append to engine/tests/test_casemem_query.py
def test_query_without_llm_is_deterministic(tmp_path):
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["재고일수 상승"], as_of="2018-07-01",
                            sector="memory")
    assert res.rerank_used is False and res.rerank_failed is False
    assert all(m.reranked is False for m in res.matches)
    assert all(m.surface_score == m.score for m in res.matches)   # 블렌드 안 됨


def test_query_with_llm_reranks(tmp_path):
    s = _seeded(tmp_path)
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        return '[{"i":0,"s":1.0}]'      # 첫 후보 구조점수 최대
    res = query_case_memory(s, signals=["재고일수 상승"], as_of="2018-07-01",
                            sector="memory", llm_fn=fake)
    assert res.rerank_used is True
    assert calls["n"] == 1
    assert res.matches and res.matches[0].reranked is True


def test_query_llm_failure_sets_rerank_failed(tmp_path):
    s = _seeded(tmp_path)
    def boom(prompt): raise RuntimeError("x")
    res = query_case_memory(s, signals=["재고일수 상승"], as_of="2018-07-01",
                            sector="memory", llm_fn=boom)
    assert res.rerank_used is True and res.rerank_failed is True
    assert all(m.reranked is False for m in res.matches)          # 폴백
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_query.py -k llm -v`
Expected: FAIL — `TypeError: query_case_memory() got an unexpected keyword argument 'llm_fn'`

- [ ] **Step 3: Write minimal implementation**

`search.py`에서 CaseMatch 생성부에 surface_score 추가:

```python
# engine/casemem/search.py — search_cases() 내 matches.append 수정
        matches.append(CaseMatch(episode_id=ep.id, matched_phase_order=mph.order,
                                 score=score, surface_score=score,
                                 next_phase_labels=next_labels,
                                 evidence=vis_ev))
```

`query.py` 수정:

```python
# engine/casemem/query.py
"""Case-Memory 단일 진입점 — 리포트/후속 API가 부르는 안정 계약.
결정적: as_of가 유일한 시계. llm_fn 주면 구조 리랭크(Plan2), None이면 순수 결정적."""
from __future__ import annotations

from casemem.contracts import CaseQueryResult, _parse_ts
from casemem.rerank import LlmFn, rerank_matches
from casemem.search import _phase_visible, search_cases
from casemem.store import CaseStore


def query_case_memory(store: CaseStore, *, signals: list[str], as_of: str,
                      sector: str = "memory", k: int = 5,
                      llm_fn: LlmFn | None = None) -> CaseQueryResult:
    as_of_dt = _parse_ts(as_of)
    if as_of_dt is None:
        return CaseQueryResult(as_of=as_of, sector=sector, matches=[],
                               scanned=0, dropped_after_as_of=0, dropped_sector=0)
    episodes = store.read_episodes(sector=sector)
    scanned = len(episodes)
    dropped_after_as_of = sum(
        0 if any(_phase_visible(p, as_of_dt) for p in ep.phases) else 1
        for ep in episodes)
    matches = search_cases(episodes, signals, as_of_dt=as_of_dt, sector=sector, k=k)

    rerank_used = False
    rerank_failed = False
    if llm_fn is not None and matches:
        rerank_used = True
        by_id = {ep.id: ep for ep in episodes}
        matches, rerank_failed = rerank_matches(matches, signals, by_id, llm_fn)

    return CaseQueryResult(as_of=as_of, sector=sector, matches=matches,
                           scanned=scanned, dropped_after_as_of=dropped_after_as_of,
                           dropped_sector=0, rerank_used=rerank_used,
                           rerank_failed=rerank_failed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_*.py -q`
Expected: PASS (전체 — 기존 + 신규)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/query.py engine/casemem/search.py engine/tests/test_casemem_query.py
git commit -m "feat(casemem): query에 llm_fn 리랭크 배선 — 하위호환(None=결정적)"
```

---

## Self-Review

- **Spec coverage**: 설계 §5-5단(구조 리랭크)=Task2·3, 관측성(§10)=Task1 필드+rerank_failed, 하위호환 결정성=Task4. **의도적 제외**: §6 증류·§7 검증 게이트(→Plan 4, §14 근거 얇음), 실제 Claude 배선(→Plan 3).
- **룩어헤드**: 리랭크 입력은 이미 as-of 필터된 matches. 프롬프트는 identifying_signals·라벨만(테스트 `test_prompt_exposes_signals_not_outcome`가 outcome 누출 감시). 미래 국면·evidence 미전달.
- **never-raise**: llm_fn 예외/빈파싱/형식오류 → 표면 폴백+rerank_failed. 예외 전파 0(Task3 3개 폴백 테스트).
- **결정성 보존**: llm_fn=None → Plan1 바이트 동일(Task4 `test_query_without_llm_is_deterministic`).
- **Placeholder scan**: 전 스텝 실제 코드·명령. TBD 없음.
- **Type consistency**: `LlmFn`(Task2)→rerank_matches(Task3)→query(Task4). `surface_score`(Task1)→search 채움(Task4)→rerank 블렌드(Task3). `rerank_matches` 반환 `(list, bool)`→query 언팩. 일치.
- **잔여 리스크(수용)**: 블렌드 가중 ws=0.4/wl=0.6은 초기 추정 — sector_rag 로그처럼 실사용 후 튜닝(설계 §5). LLM 비결정성은 실배선(Plan3)에서 temperature=0로 완화.

## 다음 Plan
- **Plan 3 (통합)**: `POST /api/case-memory/query` OpenAPI+server.mjs + 오케스트레이터 sector_rag 패턴 주입(SYNTHESIZE+AUDITOR) + `report_input.external_knowledge` seam 연결 + 실제 Claude llm_fn 배선(temperature=0) + workflow-review.html 현행화.
- **Plan 4 (증류·검증 — 리서치성)**: 코퍼스→국면/규칙 증류(§6) + 검증 게이트(§7, forward-captured proven, purged CV/PBO/Deflated Sharpe) + 파라메트릭 룩어헤드 완화(컷오프 맞춘 모델).
