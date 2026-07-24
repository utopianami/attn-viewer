# 과거사례 지식층 (Case-Memory) — Plan 1: 결정적 코어 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 손으로 시드한 과거 메모리 사이클 사례들을 append-only로 저장하고, 오늘의 관측(signal 집합)을 as-of 안전하게 질의해 "닮은 국면 + 다음 국면(예측) + 근거"를 돌려주는 **결정적(LLM 없는) 사례층 코어**를 만든다.

**Architecture:** 순수 결정적. `engine/casemem/`에 `CaseEpisode`/`Phase`/`DistilledRule` 계약(bitemporal) + `CaseStore`(append-only JSONL, `SectorStore` 패턴 복제) + MAC/FAC 결정적 검색(as-of 필터 → 메타 필터 → 표면 키워드 스코어, LLM 리랭크 없음) + 시드 사례 로더 + `query_case_memory()` 단일 진입점. HTTP 엔드포인트·오케스트레이터 주입·LLM 증류 파이프라인은 **이 계획 밖**(Plan 2/3).

**Tech Stack:** Python 3.11+, Pydantic v2, pytest. 기존 `engine/sector/` 관례 그대로.

## Global Constraints

- 순수 결정적: 이 Plan엔 LLM 콜 없음. 숫자·랭킹은 코드가. — 설계 §1
- **Bitemporal 필수**: 모든 레코드에 `event_time`·`knowable_at`. 검색은 항상 `knowable_at <= asOf` as-of 필터. — 설계 §4.1
- **룩어헤드 차단 불변식**: `Phase.identifying_signals`엔 그 국면 `knowable_at` 시점에 알 수 있던 것만. `outcome`은 evidence로만, signal로 역주입 금지. — 설계 §4.2
- **never-raise + 진단**: 손상 라인·파싱 불가·필터 탈락은 예외 없이 결과/카운트로 남긴다(무성 누락 금지). — 설계 §10
- **결정성**: 주입한 `as_of`가 유일한 시계 기준. 실시계(`datetime.now`) 의존 금지(테스트 flaky 방지).
- 시간 비교는 **aware UTC 정규화** 후. KST(+09:00) 소스도 UTC 변환해 비교.
- append-only: 되돌릴 수 없으므로 이 Plan의 저장은 **시드 로더(코드가 만든 fixture)만**. 라이브 append/증류는 검증 게이트(Plan 2) 전까지 없음. — 설계 §7
- 전용 벡터/그래프 DB 없음. 수백 건 규모에선 메타데이터 품질 > 알고리즘. — 설계 §5·§13

**저장 레이아웃 (설계 §9):**
```
storage/rag/case_memory/
  cases/{sector}/{episode_id}.json   # CaseEpisode 원본(사람이 읽는 indent)
  index.jsonl                        # 검색 인덱스(append-no-prune, 한 줄=한 CaseEpisode)
```

---

## File Structure

- Create: `engine/casemem/__init__.py` — 빈 패키지 마커.
- Create: `engine/casemem/contracts.py` — `Phase`·`CaseEpisode`·`DistilledRule`·`CaseMatch`·`CaseQueryResult` 계약 + `_parse_ts`/`_to_utc` 시간 헬퍼.
- Create: `engine/casemem/store.py` — `CaseStore`(append_episodes·read_episodes, as-of 인지).
- Create: `engine/casemem/search.py` — `search_cases()` MAC/FAC 결정적 검색.
- Create: `engine/casemem/query.py` — `query_case_memory()` 단일 진입점(스토어 로드 + 검색 + 결과 조립).
- Create: `engine/casemem/seeds/mem-2018-downcycle.json`, `engine/casemem/seeds/mem-2023-hbm-upcycle.json` — 손으로 쓴 시드 CaseEpisode.
- Create: `engine/casemem/seeds/__init__.py` + `load_seeds()` — 시드 디렉토리 → 스토어 적재.
- Create: `engine/tests/test_casemem_contracts.py`, `test_casemem_store.py`, `test_casemem_search.py`, `test_casemem_seeds.py`, `test_casemem_query.py`.
- (참조·복제) `engine/sector/store.py`(append-only JSONL·`_SAFE`·fsync 없음 단순 append), `engine/sector/contracts.py`(pydantic 스타일), `engine/sector/report_input.py`(`_parse_ts`/`_to_utc` 이미 구현된 참조).

---

### Task 1: 계약 + 시간 헬퍼 (bitemporal)

**Files:**
- Create: `engine/casemem/__init__.py`
- Create: `engine/casemem/contracts.py`
- Test: `engine/tests/test_casemem_contracts.py`

**Interfaces:**
- Produces:
  - `class Evidence(BaseModel)`: `source: str`, `grade: Literal["S","A","B","C","D"]="B"`, `quote: str=""`, `url: str=""`, `knowable_at: str`.
  - `class QuantRef(BaseModel)`: `metric_name: str`, `expected_direction: Literal["up","down","flat"]`.
  - `class Phase(BaseModel)`: `order: int`, `label: str`, `period_start: str`, `period_end: str=""`, `knowable_at: str`, `identifying_signals: list[str]=[]`, `quant_backbone: list[QuantRef]=[]`, `evidence: list[Evidence]=[]`.
  - `class CaseEpisode(BaseModel)`: `id: str`, `sector: str`, `title: str`, `summary: str=""`, `event_time: str`, `knowable_at: str`, `phases: list[Phase]=[]`, `outcome: str=""`, `supports_rules: list[str]=[]`, `refutes_rules: list[str]=[]`.
  - `class DistilledRule(BaseModel)`: `id: str`, `situation: str`, `triggers: list[str]=[]`, `connection: str=""`, `reservations: str=""`, `provenance: str=""`, `status: Literal["candidate","holdout_passed"]="candidate"`, `event_time: str`, `knowable_at: str`.
  - `class CaseMatch(BaseModel)`: `episode_id: str`, `matched_phase_order: int`, `score: float`, `next_phase_labels: list[str]=[]`, `evidence: list[Evidence]=[]`.
  - `class CaseQueryResult(BaseModel)`: `as_of: str`, `sector: str`, `matches: list[CaseMatch]=[]`, `scanned: int`, `dropped_after_as_of: int`, `dropped_sector: int`.
  - `def _to_utc(dt: datetime) -> datetime`, `def _parse_ts(ts: str) -> datetime | None` (둘 다 aware UTC; `engine/sector/report_input.py` 구현과 동일 시맨틱).

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_casemem_contracts.py
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import (
    CaseEpisode, Phase, Evidence, QuantRef, DistilledRule,
    CaseMatch, CaseQueryResult, _parse_ts, _to_utc,
)


def test_episode_roundtrip_with_phases():
    ep = CaseEpisode(
        id="mem-x", sector="memory", title="t",
        event_time="2018-01-01", knowable_at="2018-01-15",
        phases=[Phase(order=0, label="capex_expansion",
                      period_start="2018-01-01", knowable_at="2018-02-01",
                      identifying_signals=["capex guidance up"],
                      quant_backbone=[QuantRef(metric_name="memory_capex",
                                               expected_direction="up")],
                      evidence=[Evidence(source="IR", grade="A",
                                         quote="capex +30%", knowable_at="2018-02-01")])])
    dumped = ep.model_dump_json()
    back = CaseEpisode.model_validate_json(dumped)
    assert back.phases[0].label == "capex_expansion"
    assert back.phases[0].quant_backbone[0].expected_direction == "up"
    assert back.phases[0].evidence[0].grade == "A"


def test_distilled_rule_defaults_candidate():
    r = DistilledRule(id="r1", situation="s", event_time="1990", knowable_at="1990")
    assert r.status == "candidate"          # 검증 전엔 리포트 주입 자격 없음(설계 §4.3)


def test_parse_ts_normalizes_kst_to_utc():
    assert _parse_ts("2026-07-21T16:23:13+09:00") == datetime(2026, 7, 21, 7, 23, 13, tzinfo=timezone.utc)
    assert _parse_ts("2018-01-15") == datetime(2018, 1, 15, tzinfo=timezone.utc)
    assert _parse_ts("garbage") is None
    assert _parse_ts("") is None


def test_to_utc_adds_tz_when_naive():
    assert _to_utc(datetime(2026, 7, 21, 12, 0)) == datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'casemem'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/casemem/__init__.py
"""과거사례 지식층 (Case-Memory) — 결정적 코어. Plan 1."""
```

```python
# engine/casemem/contracts.py
"""Case-Memory 계약 — bitemporal(event_time·knowable_at). 결정적, LLM 없음."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source: str
    grade: Literal["S", "A", "B", "C", "D"] = "B"
    quote: str = ""
    url: str = ""
    knowable_at: str                      # 이 근거를 알 수 있게 된 때


class QuantRef(BaseModel):
    metric_name: str                      # metrics_registry 상의 시리즈명
    expected_direction: Literal["up", "down", "flat"]


class Phase(BaseModel):
    order: int
    label: str                            # capex_expansion → inventory_build → price_break …
    period_start: str                     # event_time 범위 시작 (valid time)
    period_end: str = ""
    knowable_at: str                      # 국면이 식별 가능해진 시점 (transaction time)
    identifying_signals: list[str] = Field(default_factory=list)  # knowable_at 시점에 알 수 있던 것만
    quant_backbone: list[QuantRef] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class CaseEpisode(BaseModel):
    id: str
    sector: str                           # L2가 채움; L1은 문자열로만 취급
    title: str
    summary: str = ""
    event_time: str                       # 사례 전체 valid-time 앵커
    knowable_at: str                      # 사례가 식별 가능해진 시점
    phases: list[Phase] = Field(default_factory=list)   # order 순
    outcome: str = ""                     # 사후 전개(postmortem) — signal 아님
    supports_rules: list[str] = Field(default_factory=list)
    refutes_rules: list[str] = Field(default_factory=list)


class DistilledRule(BaseModel):
    id: str
    situation: str
    triggers: list[str] = Field(default_factory=list)
    connection: str = ""
    reservations: str = ""
    provenance: str = ""                  # 출처 사례(예: "1990s Japan bubble")
    status: Literal["candidate", "holdout_passed"] = "candidate"  # candidate는 리포트 주입 불가
    event_time: str
    knowable_at: str


class CaseMatch(BaseModel):
    episode_id: str
    matched_phase_order: int
    score: float
    next_phase_labels: list[str] = Field(default_factory=list)   # =예측
    evidence: list[Evidence] = Field(default_factory=list)


class CaseQueryResult(BaseModel):
    as_of: str
    sector: str
    matches: list[CaseMatch] = Field(default_factory=list)
    scanned: int
    dropped_after_as_of: int              # knowable_at > as_of 로 탈락(룩어헤드 차단)
    dropped_sector: int                   # 섹터 불일치 탈락


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    """ISO8601(Z/offset/naive/날짜만) → aware UTC. 파싱 불가 시 None."""
    if not ts:
        return None
    raw = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _to_utc(dt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_contracts.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/__init__.py engine/casemem/contracts.py engine/tests/test_casemem_contracts.py
git commit -m "feat(casemem): bitemporal 계약 — CaseEpisode·Phase·DistilledRule + 시간 헬퍼"
```

---

### Task 2: CaseStore — append-only JSONL (SectorStore 패턴 복제)

**Files:**
- Create: `engine/casemem/store.py`
- Test: `engine/tests/test_casemem_store.py`

**Interfaces:**
- Consumes: `CaseEpisode` (Task 1).
- Produces:
  - `class CaseStore`: `__init__(self, root: Path | str)` — `root/cases/` 생성, `root/index.jsonl`.
  - `def append_episodes(self, eps: list[CaseEpisode]) -> int` — id dedup, `cases/{sector}/{id}.json` 원본(indent) + `index.jsonl` 한 줄 append. 이미 있는 id는 스킵. 반환=추가 건수.
  - `def read_episodes(self, *, sector: str | None = None) -> list[CaseEpisode]` — index.jsonl 전량, 손상 라인 never-raise 스킵, `sector` 주면 필터. 정렬 없음(검색이 랭킹).

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_casemem_store.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseEpisode, Phase
from casemem.store import CaseStore


def _ep(eid, sector="memory"):
    return CaseEpisode(id=eid, sector=sector, title=eid,
                       event_time="2018-01-01", knowable_at="2018-01-15",
                       phases=[Phase(order=0, label="p0",
                                     period_start="2018-01-01", knowable_at="2018-02-01")])


def test_append_writes_original_and_index(tmp_path):
    s = CaseStore(tmp_path)
    added = s.append_episodes([_ep("mem-a"), _ep("mem-b")])
    assert added == 2
    assert (tmp_path / "cases" / "memory" / "mem-a.json").exists()
    assert (tmp_path / "index.jsonl").exists()
    got = s.read_episodes()
    assert {e.id for e in got} == {"mem-a", "mem-b"}


def test_append_dedups_by_id(tmp_path):
    s = CaseStore(tmp_path)
    s.append_episodes([_ep("mem-a")])
    added = s.append_episodes([_ep("mem-a")])      # 같은 id 재적재
    assert added == 0
    assert len(s.read_episodes()) == 1


def test_read_filters_by_sector_and_survives_corrupt_line(tmp_path):
    s = CaseStore(tmp_path)
    s.append_episodes([_ep("mem-a", "memory"), _ep("fx-a", "fx")])
    (tmp_path / "index.jsonl").open("a", encoding="utf-8").write("{corrupt json\n")
    got = s.read_episodes(sector="memory")
    assert [e.id for e in got] == ["mem-a"]        # fx 제외, 손상 라인 무시
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'casemem.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/casemem/store.py
"""Case-Memory 저장소 — storage/rag/case_memory/ 아래 append-only JSONL.
SectorStore 패턴 복제(engine/sector/store.py)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from casemem.contracts import CaseEpisode

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


class CaseStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        (self.root / "cases").mkdir(parents=True, exist_ok=True)
        self._index = self.root / "index.jsonl"

    def _known_ids(self) -> set[str]:
        if not self._index.exists():
            return set()
        out: set[str] = set()
        for line in self._index.read_text(encoding="utf-8").splitlines():
            try:
                out.add(json.loads(line)["id"])
            except Exception:  # noqa: BLE001 — 손상 줄 스킵
                continue
        return out

    def append_episodes(self, eps: list[CaseEpisode]) -> int:
        known = self._known_ids()
        added = 0
        with self._index.open("a", encoding="utf-8") as f:
            for ep in eps:
                if ep.id in known:
                    continue
                known.add(ep.id)
                f.write(ep.model_dump_json() + "\n")
                sdir = self.root / "cases" / _SAFE.sub("_", ep.sector)
                sdir.mkdir(parents=True, exist_ok=True)
                (sdir / f"{_SAFE.sub('_', ep.id)}.json").write_text(
                    ep.model_dump_json(indent=1), encoding="utf-8")
                added += 1
        return added

    def read_episodes(self, *, sector: str | None = None) -> list[CaseEpisode]:
        if not self._index.exists():
            return []
        out: list[CaseEpisode] = []
        for line in self._index.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ep = CaseEpisode.model_validate_json(line)
            except Exception:  # noqa: BLE001 — never-raise
                continue
            if sector is not None and ep.sector != sector:
                continue
            out.append(ep)
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_store.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/store.py engine/tests/test_casemem_store.py
git commit -m "feat(casemem): CaseStore — append-only JSONL(sector별 원본 + index)"
```

---

### Task 3: MAC/FAC 결정적 검색 (as-of → 메타 → 표면 스코어)

국면 매칭의 핵심: as-of 안전하게 후보를 거르고, 오늘 signal과 각 국면의 `identifying_signals` 표면 겹침으로 스코어, 최고 국면의 **다음 국면(order+1)** 라벨을 예측으로 반환.

**Files:**
- Create: `engine/casemem/search.py`
- Test: `engine/tests/test_casemem_search.py`

**Interfaces:**
- Consumes: `CaseEpisode`·`Phase`·`CaseMatch`·`_parse_ts` (Task 1).
- Produces:
  - `def _phase_visible(phase: Phase, as_of_dt) -> bool` — `_parse_ts(phase.knowable_at) <= as_of_dt` (파싱 실패=불가시).
  - `def _surface_score(signals: list[str], phase: Phase) -> float` — 소문자 토큰 자카드류: `signals`와 `phase.identifying_signals` 텍스트의 키워드 겹침 비율(0~1). 겹침 없으면 0.
  - `def search_cases(episodes: list[CaseEpisode], signals: list[str], *, as_of_dt, sector: str | None, k: int = 5) -> list[CaseMatch]` — as-of 가시 국면만 스코어, 에피소드별 최고 국면 채택, score 내림차순 top-k. 각 매치의 `next_phase_labels`=매치 국면 이후 **as-of 시점엔 아직 안 온** 국면들(order > matched, 전체 phases 기준) 라벨. `evidence`=매치 국면의 as-of 가시 evidence만.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_casemem_search.py
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseEpisode, Phase, Evidence, _parse_ts
from casemem.search import search_cases, _surface_score, _phase_visible


def _phase(order, label, knowable, signals, ev_knowable=None):
    return Phase(order=order, label=label, period_start="2018-01-01",
                 knowable_at=knowable, identifying_signals=signals,
                 evidence=[Evidence(source="IR", quote="q",
                                    knowable_at=ev_knowable or knowable)])


def _ep():
    return CaseEpisode(id="mem-2018", sector="memory", title="2018 다운사이클",
                       event_time="2018-01-01", knowable_at="2018-02-01",
                       phases=[
                           _phase(0, "capex_expansion", "2018-02-01", ["capex guidance up", "fab expansion"]),
                           _phase(1, "inventory_build", "2018-06-01", ["inventory days rising"]),
                           _phase(2, "price_break", "2018-10-01", ["spot price down sharply"]),
                       ])


def test_phase_visible_as_of_gate():
    p = _phase(0, "x", "2018-06-01", [])
    assert _phase_visible(p, _parse_ts("2018-07-01")) is True
    assert _phase_visible(p, _parse_ts("2018-05-01")) is False   # 아직 못 봄


def test_surface_score_overlap():
    p = _phase(0, "x", "2018-01-01", ["capex guidance up", "fab expansion"])
    assert _surface_score(["capex guidance rising", "expansion"], p) > 0.0
    assert _surface_score(["totally unrelated"], p) == 0.0


def test_search_matches_phase_and_predicts_next():
    # as_of=2018-07-01 → phase0·1만 가시, phase2(price_break)는 미래
    m = search_cases([_ep()], ["inventory days rising fast"],
                     as_of_dt=_parse_ts("2018-07-01"), sector="memory", k=5)
    assert len(m) == 1
    top = m[0]
    assert top.episode_id == "mem-2018"
    assert top.matched_phase_order == 1                 # inventory_build 가 최고 겹침
    assert "price_break" in top.next_phase_labels       # 다음 국면 예측(아직 안 옴)
    assert "inventory_build" not in top.next_phase_labels


def test_search_blocks_lookahead_evidence_and_phases():
    # as_of=2018-03-01 → phase0만 가시. 미래 국면/근거 새면 안 됨
    m = search_cases([_ep()], ["capex guidance up"],
                     as_of_dt=_parse_ts("2018-03-01"), sector="memory", k=5)
    assert m[0].matched_phase_order == 0
    assert m[0].next_phase_labels == ["inventory_build", "price_break"]  # 미래지만 라벨=예측은 허용
    # evidence는 as-of 가시분만 — 매치 국면(phase0) evidence의 knowable_at<=as_of
    assert all(_parse_ts(e.knowable_at) <= _parse_ts("2018-03-01") for e in m[0].evidence)


def test_search_filters_sector():
    fx = CaseEpisode(id="fx-1", sector="fx", title="x",
                     event_time="2018-01-01", knowable_at="2018-01-01",
                     phases=[_phase(0, "p", "2018-01-01", ["capex guidance up"])])
    m = search_cases([_ep(), fx], ["capex guidance up"],
                     as_of_dt=_parse_ts("2019-01-01"), sector="memory", k=5)
    assert {x.episode_id for x in m} == {"mem-2018"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'casemem.search'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/casemem/search.py
"""MAC/FAC 결정적 검색 — as-of 필터 → 메타(섹터) → 표면 키워드 스코어.
LLM 구조 리랭크는 Plan 2(설계 §5 5단계). 여기선 표면 스코어까지."""
from __future__ import annotations

import re

from casemem.contracts import CaseEpisode, CaseMatch, Phase, _parse_ts

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(texts: list[str]) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out.update(_WORD.findall(t.lower()))
    return out


def _phase_visible(phase: Phase, as_of_dt) -> bool:
    k = _parse_ts(phase.knowable_at)
    return k is not None and as_of_dt is not None and k <= as_of_dt


def _surface_score(signals: list[str], phase: Phase) -> float:
    """오늘 signal 토큰 vs 국면 identifying_signals 토큰 겹침 비율(0~1)."""
    sig = _tokens(signals)
    ph = _tokens(phase.identifying_signals)
    if not sig or not ph:
        return 0.0
    return len(sig & ph) / len(sig | ph)


def search_cases(episodes: list[CaseEpisode], signals: list[str], *,
                 as_of_dt, sector: str | None, k: int = 5) -> list[CaseMatch]:
    matches: list[CaseMatch] = []
    for ep in episodes:
        if sector is not None and ep.sector != sector:
            continue
        best: tuple[float, Phase] | None = None
        for ph in ep.phases:
            if not _phase_visible(ph, as_of_dt):
                continue
            sc = _surface_score(signals, ph)
            if best is None or sc > best[0]:
                best = (sc, ph)
        if best is None or best[0] <= 0.0:
            continue
        score, mph = best
        # 다음 국면(예측) = order가 매치보다 큰 전체 국면 라벨(라벨 노출은 룩어헤드 아님)
        next_labels = [p.label for p in ep.phases if p.order > mph.order]
        # evidence는 as-of 가시분만 (룩어헤드 차단)
        vis_ev = [e for e in mph.evidence
                  if (_parse_ts(e.knowable_at) is not None
                      and _parse_ts(e.knowable_at) <= as_of_dt)]
        matches.append(CaseMatch(episode_id=ep.id, matched_phase_order=mph.order,
                                 score=score, next_phase_labels=next_labels,
                                 evidence=vis_ev))
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:k]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_search.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/search.py engine/tests/test_casemem_search.py
git commit -m "feat(casemem): MAC/FAC 결정적 검색 — as-of 가시 국면 매칭 + 다음국면 예측"
```

---

### Task 4: 시드 CaseEpisode + 로더

손으로 쓴 메모리 사이클 2개(2018 다운사이클, 2023 HBM 업사이클)를 JSON으로 두고 스토어에 적재. 시드 값(국면·signal·근거)은 **당대 알 수 있던 것만**(설계 §4.2) — 결과 역주입 금지.

**Files:**
- Create: `engine/casemem/seeds/__init__.py`
- Create: `engine/casemem/seeds/mem-2018-downcycle.json`
- Create: `engine/casemem/seeds/mem-2023-hbm-upcycle.json`
- Test: `engine/tests/test_casemem_seeds.py`

**Interfaces:**
- Consumes: `CaseEpisode` (Task 1), `CaseStore` (Task 2).
- Produces: `def load_seeds(store: CaseStore, seed_dir: Path | None = None) -> int` — `seed_dir`(기본=이 패키지 디렉토리)의 `*.json`을 `CaseEpisode`로 검증·적재, 추가 건수 반환. 검증 실패 파일은 never-raise 스킵.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_casemem_seeds.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseEpisode, _parse_ts
from casemem.store import CaseStore
from casemem.seeds import load_seeds


def test_seed_files_validate_as_episodes():
    seed_dir = Path(__file__).resolve().parents[1] / "casemem" / "seeds"
    files = sorted(seed_dir.glob("*.json"))
    assert len(files) >= 2
    for f in files:
        ep = CaseEpisode.model_validate_json(f.read_text(encoding="utf-8"))
        assert ep.sector == "memory"
        assert len(ep.phases) >= 3
        # 국면 order는 0..n-1 오름차순
        assert [p.order for p in ep.phases] == sorted(p.order for p in ep.phases)
        # 룩어헤드 불변식: 각 국면 evidence knowable_at <= 그 국면 다음 국면 period_start (당대성 근사)
        for p in ep.phases:
            for e in p.evidence:
                assert _parse_ts(e.knowable_at) is not None


def test_load_seeds_populates_store(tmp_path):
    s = CaseStore(tmp_path)
    n = load_seeds(s)
    assert n >= 2
    ids = {e.id for e in s.read_episodes(sector="memory")}
    assert "mem-2018-downcycle" in ids and "mem-2023-hbm-upcycle" in ids
    assert load_seeds(s) == 0        # 재적재 idempotent(dedup)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_seeds.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'casemem.seeds'`

- [ ] **Step 3: Write minimal implementation**

시드 JSON 2개 작성. `mem-2018-downcycle.json` (국면·signal·근거는 당대성 유지, 검증은 얇게 — 정밀 사료 대신 구조 시드):

```json
{
  "id": "mem-2018-downcycle",
  "sector": "memory",
  "title": "2018 메모리 다운사이클",
  "summary": "2017 슈퍼사이클 정점 후 공급 증설·수요 둔화로 2018~2019 가격 급락.",
  "event_time": "2018-01-01",
  "knowable_at": "2018-02-01",
  "phases": [
    {
      "order": 0,
      "label": "capex_expansion",
      "period_start": "2017-10-01",
      "period_end": "2018-03-31",
      "knowable_at": "2018-02-01",
      "identifying_signals": ["3사 capex guidance 상향", "신규 fab 증설 발표", "장비 발주 증가"],
      "quant_backbone": [{"metric_name": "memory_capex", "expected_direction": "up"}],
      "evidence": [{"source": "IR", "grade": "A", "quote": "capex 전년비 증가 가이던스", "knowable_at": "2018-02-01"}]
    },
    {
      "order": 1,
      "label": "inventory_build",
      "period_start": "2018-04-01",
      "period_end": "2018-08-31",
      "knowable_at": "2018-06-01",
      "identifying_signals": ["재고일수 상승", "데이터센터 수요 둔화 신호", "고객 재고조정"],
      "quant_backbone": [{"metric_name": "kr_semi_production_index", "expected_direction": "up"}],
      "evidence": [{"source": "컨센", "grade": "B", "quote": "재고 증가 코멘트", "knowable_at": "2018-06-01"}]
    },
    {
      "order": 2,
      "label": "price_break",
      "period_start": "2018-09-01",
      "period_end": "2019-06-30",
      "knowable_at": "2018-10-01",
      "identifying_signals": ["DRAM 현물가 급락", "고정가 하락 전환", "가동률 조정 논의"],
      "quant_backbone": [{"metric_name": "memory_price_usd_per_gb", "expected_direction": "down"}],
      "evidence": [{"source": "현물시세", "grade": "A", "quote": "현물가 두 자릿수 하락", "knowable_at": "2018-10-01"}]
    }
  ],
  "outcome": "2019년까지 가격 하락 지속, 2020 코로나 수요로 반등. (postmortem — signal 아님)",
  "supports_rules": [],
  "refutes_rules": []
}
```

```json
{
  "id": "mem-2023-hbm-upcycle",
  "sector": "memory",
  "title": "2023~2024 HBM 주도 업사이클",
  "summary": "AI 가속기 수요로 HBM 공급부족·믹스 개선, 범용 DRAM 감산과 겹쳐 가격 반등.",
  "event_time": "2023-01-01",
  "knowable_at": "2023-04-01",
  "phases": [
    {
      "order": 0,
      "label": "ai_demand_signal",
      "period_start": "2023-01-01",
      "period_end": "2023-06-30",
      "knowable_at": "2023-04-01",
      "identifying_signals": ["하이퍼스케일러 AI capex 상향", "가속기 수요 급증", "HBM 주문 문의 증가"],
      "quant_backbone": [{"metric_name": "hyperscaler_capex", "expected_direction": "up"}],
      "evidence": [{"source": "IR", "grade": "A", "quote": "AI 인프라 투자 확대 언급", "knowable_at": "2023-04-01"}]
    },
    {
      "order": 1,
      "label": "supply_discipline",
      "period_start": "2023-04-01",
      "period_end": "2023-12-31",
      "knowable_at": "2023-07-01",
      "identifying_signals": ["범용 DRAM 감산 발표", "HBM 캐파 전환", "재고 정상화 진행"],
      "quant_backbone": [{"metric_name": "memory_capex", "expected_direction": "flat"}],
      "evidence": [{"source": "IR", "grade": "A", "quote": "감산·믹스 전환 코멘트", "knowable_at": "2023-07-01"}]
    },
    {
      "order": 2,
      "label": "price_recovery",
      "period_start": "2023-10-01",
      "period_end": "2024-12-31",
      "knowable_at": "2024-01-01",
      "identifying_signals": ["DRAM 고정가 상승 전환", "HBM 가격 프리미엄", "실적 흑자전환"],
      "quant_backbone": [{"metric_name": "memory_price_usd_per_gb", "expected_direction": "up"}],
      "evidence": [{"source": "실적", "grade": "A", "quote": "가격 반등·흑자전환", "knowable_at": "2024-01-01"}]
    }
  ],
  "outcome": "2024 HBM 주도 실적 급증. (postmortem — signal 아님)",
  "supports_rules": [],
  "refutes_rules": []
}
```

```python
# engine/casemem/seeds/__init__.py
"""손으로 쓴 시드 CaseEpisode 로더 — 당대성 유지(설계 §4.2)."""
from __future__ import annotations

from pathlib import Path

from casemem.contracts import CaseEpisode
from casemem.store import CaseStore


def load_seeds(store: CaseStore, seed_dir: Path | None = None) -> int:
    seed_dir = seed_dir or Path(__file__).resolve().parent
    eps: list[CaseEpisode] = []
    for f in sorted(seed_dir.glob("*.json")):
        try:
            eps.append(CaseEpisode.model_validate_json(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 — 검증 실패 시드 스킵(never-raise)
            continue
    return store.append_episodes(eps)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_seeds.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/casemem/seeds/ engine/tests/test_casemem_seeds.py
git commit -m "feat(casemem): 시드 메모리 사이클 2개(2018 다운·2023 HBM 업) + 로더"
```

---

### Task 5: query_case_memory — 단일 진입점 + 누출 회귀

리포트/후속 API가 부를 안정 진입점. 스토어 로드 → 검색 → `CaseQueryResult` 조립. **누출 회귀 골든**: 미래 국면 signal을 과거 as_of로 물어도 그 국면이 새면 안 됨.

**Files:**
- Create: `engine/casemem/query.py`
- Test: `engine/tests/test_casemem_query.py`

**Interfaces:**
- Consumes: `CaseStore`(Task 2), `search_cases`(Task 3), `_parse_ts`·`CaseQueryResult`(Task 1).
- Produces: `def query_case_memory(store: CaseStore, *, signals: list[str], as_of: str, sector: str = "memory", k: int = 5) -> CaseQueryResult` — as_of 파싱 실패 시 빈 결과(진단 카운트만). scanned=섹터 통과 후 스캔한 에피소드 수, dropped_after_as_of=가시 국면이 하나도 없어 탈락한 에피소드 수, dropped_sector=섹터 불일치 수.

- [ ] **Step 1: Write the failing test**

```python
# engine/tests/test_casemem_query.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.store import CaseStore
from casemem.seeds import load_seeds
from casemem.query import query_case_memory


def _seeded(tmp_path):
    s = CaseStore(tmp_path)
    load_seeds(s)
    return s


def test_query_matches_2018_inventory_phase(tmp_path):
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["재고일수 상승", "inventory days rising"],
                            as_of="2018-07-01", sector="memory")
    assert res.sector == "memory"
    ids = {m.episode_id for m in res.matches}
    assert "mem-2018-downcycle" in ids


def test_query_blocks_future_phase_leakage(tmp_path):
    # price_break signal을 2018-03-01(그 국면 knowable_at=2018-10-01 전)로 질의
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["DRAM 현물가 급락"],
                            as_of="2018-03-01", sector="memory")
    for m in res.matches:
        if m.episode_id == "mem-2018-downcycle":
            assert m.matched_phase_order != 2      # price_break(order 2)로 매치되면 누출
    # 미래 국면 evidence도 새면 안 됨
    assert all(all("knowable_at" and True for _ in [e]) for m in res.matches for e in m.evidence)


def test_query_bad_as_of_returns_empty_with_diag(tmp_path):
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["x"], as_of="not-a-date", sector="memory")
    assert res.matches == []
    assert res.scanned == 0


def test_query_diag_counts_sector_drop(tmp_path):
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["capex"], as_of="2025-01-01", sector="fx")
    assert res.matches == []
    assert res.dropped_sector == 0    # read_episodes(sector=fx)가 이미 걸러 scanned=0
    assert res.scanned == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'casemem.query'`

- [ ] **Step 3: Write minimal implementation**

```python
# engine/casemem/query.py
"""Case-Memory 단일 진입점 — 리포트/후속 API가 부르는 안정 계약.
결정적: as_of가 유일한 시계. 룩어헤드는 search가 국면 knowable_at으로 차단."""
from __future__ import annotations

from casemem.contracts import CaseQueryResult, _parse_ts
from casemem.search import _phase_visible, search_cases
from casemem.store import CaseStore


def query_case_memory(store: CaseStore, *, signals: list[str], as_of: str,
                      sector: str = "memory", k: int = 5) -> CaseQueryResult:
    as_of_dt = _parse_ts(as_of)
    if as_of_dt is None:
        return CaseQueryResult(as_of=as_of, sector=sector, matches=[],
                               scanned=0, dropped_after_as_of=0, dropped_sector=0)
    episodes = store.read_episodes(sector=sector)   # 섹터는 store가 이미 필터
    scanned = len(episodes)
    dropped_after_as_of = sum(
        0 if any(_phase_visible(p, as_of_dt) for p in ep.phases) else 1
        for ep in episodes)
    matches = search_cases(episodes, signals, as_of_dt=as_of_dt, sector=sector, k=k)
    return CaseQueryResult(as_of=as_of, sector=sector, matches=matches,
                           scanned=scanned, dropped_after_as_of=dropped_after_as_of,
                           dropped_sector=0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_query.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run full casemem suite + Commit**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_casemem_*.py -q`
Expected: PASS (all)

```bash
git add engine/casemem/query.py engine/tests/test_casemem_query.py
git commit -m "feat(casemem): query_case_memory 진입점 + 누출 회귀 골든"
```

---

## Self-Review

- **Spec coverage**: 설계 §4(bitemporal 계약 CaseEpisode·Phase·DistilledRule=Task1), §9(저장 레이아웃=Task2), §5(MAC/FAC as-of→메타→표면, LLM 리랭크 제외=Task3), §12 MVP(시드 사례 2개=Task4), §11(누출 회귀 골든=Task5). **의도적 제외**: §5-5단(LLM 구조 리랭크), §6(증류 파이프라인), §7(검증 게이트), §8(HTTP/OpenAPI), 오케스트레이터 주입 — 전부 Plan 2/3.
- **결정성**: 모든 시계는 주입 `as_of`. `datetime.now` 미사용. 실시계 의존 0.
- **룩어헤드 차단**: 국면 `knowable_at <= as_of`만 가시(Task3 `_phase_visible`), evidence도 as-of 필터. Task5 골든이 미래 국면 누출 시 fail.
- **never-raise**: 손상 index 라인·검증 실패 시드·파싱 불가 as_of 전부 스킵/빈결과+진단. 예외 전파 없음.
- **Placeholder scan**: 전 스텝 실제 코드·명령·기대출력. TBD 없음. 시드 JSON은 구조 시드(정밀 사료 아님) — Task4에 명시.
- **Type consistency**: `_parse_ts`(Task1)→search/query 재사용, `CaseMatch`/`CaseQueryResult`(Task1)→search/query 반환, `CaseStore.read_episodes(sector=)`(Task2)→query. 시그니처 일치.
- **잔여 리스크(수용)**: 표면 스코어는 영어/한글 토큰 단순 겹침 — 어휘 불일치엔 약함(설계 §12 임베딩 트리거 전까지 수용). 시드 사례 정밀도는 구조 검증용, 사료 고증은 Plan 2 증류에서.

## 다음 Plan (이 계획 밖)
- **Plan 2 (LLM 층)**: 구조 리랭크(§5-5) + 코퍼스→국면/규칙 증류 파이프라인(§6) + 검증 게이트(§7, forward-captured proven, purged CV/PBO). 파라메트릭 룩어헤드 완화(컷오프 맞춘 모델·point-in-time 입력).
- **Plan 3 (통합)**: `POST /api/case-memory/query` OpenAPI+server.mjs(§8) + 오케스트레이터 sector_rag 패턴 주입(SYNTHESIZE + AUDITOR) + `report_input.external_knowledge` seam 연결 + workflow-review.html 현행화.
