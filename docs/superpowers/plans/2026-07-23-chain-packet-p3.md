# ChainPacket 체인 합성 + SYNTHESIZE 주입 (스펙 3부) Implementation Plan (v1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

v1 — 2부 SHIPPED(main=57dcf3f) 기반. 답변 파이프라인에 3부 전체(thesis 배경 판 주입 + ChainPacket + chain_verdicts + 시나리오 계약 + 구조 게이트)를 **`settings.disable_p23` 단일 토글**(기본 False=ON) 뒤에 넣는다 — 4부 2-arm experiment 승계 제약(스펙 "4부 승계 필수 게이트" 4: 단일 명령 disable_p23 off/on).

**Goal:** 답변 파이프라인에 ① thesis "배경 판" 절 주입(결정적 선택·fresh/degraded만) ② ChainPacket 체인 합성(VERIFY 이전·코드 실존 검증) ③ VERIFY chain_verdicts 산출 + RISK 소비 ④ SYNTHESIZE 긍정/부정 시나리오 계약(코드 후검증·1회 재합성) ⑤ 플레이북 구조 게이트(all-or-none) — 전부 disable_p23=True면 통째로 꺼져 기존 경로와 **바이트 동일**.

**Architecture:** 선택·검증·게이트는 전부 코드(LLM 신뢰 없음): thesis 선택은 `build_rule_plan` 스코어링(결정적), ChainPacket 인용 ID는 실존 검증·미실존 드롭·빈 supporting 강등, chain_verdicts는 VERIFY의 코드 재검증(존재+as_of), 시나리오 계약은 마크다운 구조 마커의 정규식 후검증, 게이트 값은 store 관측 역참조. LLM은 chain 제안(sonnet)과 시나리오 서술만 한다. 숫자는 전부 TypedFact 경로(주입 절엔 수치 없음).

**Tech Stack:** Python 3.12(engine/.venv)·pydantic v2·기존 Role/SectorStore/ThesisStore. 신규 HTTP 라우트 없음(openapi 무변경 — npm 게이트는 회귀 확인용).

**스펙:** docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md §3부 + §2부 가드레일 5 + "1부 완료 스코프"의 4부 승계 게이트 + 전역 제약

## 스펙-코드 불일치 (실코드 대조 결과 — codex 판정 요청)

1. **TypedFact schema_version**: 스펙은 "TypedFact 확장(schema_version 증가)"이라 하나 TypedFact엔 자체 schema_version이 없다 — 패킷들이 모듈 상수 `SCHEMA_VERSION`(현재 1, engine/contracts/packets.py:18)을 공유 스탬프. **해소:** `SCHEMA_VERSION` 1→2 전역 증가 + 신규 필드 전부 기본값(구 직렬화본 `schema_version:1` 로드 하위호환을 테스트로 고정). 또한 스펙의 `period` 필드는 TypedFact에 **이미 존재** — 실추가는 `metric`·`observation_id` 2개.
2. **edge 값 공간**: 스펙 "judge.py 인과 그래프 edge 값 공간" — judge.py에 edge 열거는 없다(자유 문자열, 기본 `"B->A"`; 축 집합 `_VALID_AXIS = {A, A_prime, B, C, C0, E, P, market}`만 존재, judge.py:25). **해소:** packets에 `CHAIN_AXES` 상수 + `"{src}->{dst}"` (src,dst ∈ CHAIN_AXES) validator, `set(CHAIN_AXES) == judge._VALID_AXIS` 드리프트 가드 테스트(contracts→sector 런타임 import 없이 단일 진실원 유지).
3. **rule_plan의 event_types**: `build_rule_plan`(sector/queryplan.py:83)은 event_types를 채우지 않는다 — 스코어 식의 event_types×1 항은 현 코드에선 항상 0 기여. **해소:** 식은 스펙대로 구현·테스트(rule_plan 확장 시 자동 활성), 결정성 무영향임을 명기.
4. **"2부 주입 경로+3부 전체 무효"**: 2부는 답변 경로 무접촉으로 배송됨(주입 자체가 3부에서 처음 생김) — disable_p23 하나가 배경 판 주입과 3부 신규 경로 전체를 관장한다(스펙 의도 그대로, 별도 2부 토글 없음. `thesis_update_enabled`는 갱신 잡 전용으로 별개).
5. **EnvelopeMeta·VerdictPacket**: 스펙 명칭 그대로 실존(contracts/packets.py:49·377) — 불일치 없음, 확인 기록.

## Global Constraints

- **disable_p23 단일 토글** (`engine/app/settings.py`, 기본 False=주입 ON): True면 thesis 배경 판 주입 + ChainPacket + chain_verdicts + RISK 체인 입력 + 시나리오 계약 + 구조 게이트 **전부 무효** — 신규 layer 미방출, 프롬프트·패킷이 3부 이전과 **바이트 동일 경로**(off-path 스냅샷 테스트로 고정). 4부 2-arm은 이 플래그 하나로 스위칭.
- **stale thesis 주입 금지** — fresh + degraded(라벨 병기)만. 선택된 `revision_id`를 thesis layer에 기록.
- **AUDIT evidence_texts에 thesis 주입 절 불포함** — 감사 증거 조립을 `_audit_evidence()` 헬퍼로 추출해 시그니처 수준에서 보장(thesis 입력 자체가 없음).
- **숫자 불변식**: thesis 유래 숫자는 TypedFact 경로만(`thesis_typed_facts` → `[결정적 수치]` 절). 배경 판 절엔 수치 미포함 — 렌더 시점에 `thesis_guard.quantity_literal`로 코드 검증, 위반 statement 드롭(성공 기준 "주입 텍스트 수량 literal = 0"의 주입 시점 차단). revision_id·타임스탬프도 절 본문에 넣지 않는다(숫자 검출 오탐 방지 — layer에만 기록).
- **임의 ID로 grounded 채우기 불가**: ChainPacket 인용 ID는 (섹터 카드 ∪ curated NewsItem ∪ typed_facts) 실존 집합 대조 — 미실존 드롭, supporting·metric 인용이 다 비면 `observed`→`inference` 강등. VERIFY가 독립 재검증(생성부 불신).
- **LLM 유사 지표 대입 금지**: 구조 게이트 값은 코드가 store에서 조회·집계 — LLM은 게이트 판정 경로에 없음.
- **all-or-none 게이트**: 구조 필드가 일부만 있으면 그 gate의 구조 판정 전체 무시 + 로그(문자열 gate로만 동작 — 하위 호환).
- **답변 경로 기존 동작 무영향**: 토글 off 시 기존 프롬프트/패킷 그대로. 신규 경로는 전부 never-raise(실패 → degraded 항목 + 무주입 폴백).
- **pm2 재시작만**(`pm2 restart attn-engine`), 커밋 작은따옴표·**명시적 git add**(공유 체크아웃 — 병행 세션 파일 오염 금지, `git -C /home/ryze_yn/attn-viewer add <파일들>` 나열). 커밋 전 브랜치 확인(main).
- 신규 HTTP 라우트 없음 — openapi 무변경. `npm test`·`npm run check:openapi`는 회귀 게이트(T8), **fallback·`|| true` 금지, exit code가 게이트**.
- 프론트(public/index.html)는 미변경 — 신규 layer name은 `CHAT_LAYER_TITLE` 미등록으로 필터되어 UI 무영향(표시 추가·workflow-review 현행화는 T9 컨트롤러).
- cwd `/home/ryze_yn/attn-viewer/engine`, 테스트 `.venv/bin/python -m pytest tests/... -q`.

## File Structure

- Create: `engine/stages/thesis_context.py`(T2·T3), `engine/stages/chain.py`(T4)
- Modify: `engine/contracts/packets.py`·`engine/contracts/__init__.py`(T1), `engine/app/settings.py`(T1), `engine/stages/synthesize.py`(T3·T6), `engine/orchestrator.py`(T3~T7), `engine/providers.py`(T4), `engine/stages/verify.py`(T5), `engine/sector/evidence.py`(T5), `engine/stages/risk.py`(T5), `engine/stages/playbook.py`(T7), `engine/evals/chain_judge.py`·`engine/evals/metrics.py`·`engine/evals/run_eval.py`(T8)
- 테스트: `engine/tests/test_chain_contracts.py`, `test_thesis_select.py`, `test_thesis_inject.py`, `test_chain_stage.py`, `test_chain_verify_risk.py`, `test_scenario_contract.py`, `test_playbook_gates.py`, `test_chain_eval_wiring.py`

---

### Task 1: 계약 — ChainPacket·ChainEdgeVerdict·PlaybookGate 계약 + TypedFact 확장 + disable_p23

**Files:**
- Modify: `engine/contracts/packets.py`, `engine/contracts/__init__.py`, `engine/app/settings.py`
- Test: `engine/tests/test_chain_contracts.py`

**Interfaces (Produces — 전부 `_Strict`(extra forbid) 상속, packets.py 내):**
- `SCHEMA_VERSION = 2` (1→2 — 불일치 1 해소. 구 직렬화본 로드 하위호환 테스트)
- `CHAIN_AXES = ("A", "A_prime", "B", "C", "C0", "E", "P", "market")` — judge._VALID_AXIS와 동등성 테스트로 결속 (불일치 2)
- `TypedFact` += `metric: str = ""`(섹터 지표 식별자 — METRIC_REGISTRY 키), `observation_id: str = ""` (기존 생성부 무변경 — 기본값)
- `ThesisRelation(thesis_revision_id: str, relation: Literal["supports", "contradicts"])`
- `ChainEdge(edge_id: str, edge: str, kind: Literal["observed", "inference"], supporting_card_ids: list[str] = [], metric_fact_ids: list[str] = [], contradicting_card_ids: list[str] = [])` — `edge`는 `^{axis}->{axis}$` field_validator (axis ∈ CHAIN_AXES)
- `ChainPacket(schema_version: int = SCHEMA_VERSION, meta: EnvelopeMeta, event: str, mechanism: str, edges: list[ChainEdge] = [], thesis_relation: list[ThesisRelation] = [], verdict: str = "")`
- `ChainEdgeVerdict(edge_id: str, grounded: bool, note: str = "")`
- `VerdictPacket` += `chain_verdicts: list[ChainEdgeVerdict] = Field(default_factory=list)`
- `PlaybookGateSelector(series: str | None = None, meta_filter: dict = {})`
- `PlaybookGateCheck(order: int, check: str, metric_id: str, selector: PlaybookGateSelector = ..., aggregation: Literal["last", "mean_window", "yoy"], window_days: int = 0, comparator: Literal[">=", "<=", ">", "<", "=="], threshold: float, unit: str, max_age_days: int)`
- `PlaybookGateOutcome(order: int, metric_id: str, value: float | None = None, verdict: Literal["pass", "fail", "unavailable"], evidence_observation_id: str = "", unavailable_reason: Literal["", "no_metric", "unit_mismatch", "stale_data"] = "")`
- `DraftAnswer` += `scenario_flags: list[str] = Field(default_factory=list)` (T6 재실패 플래그)
- `LAYER_NAMES` += `"thesis"`, `"chain"` (프론트는 미등록 name 필터 — 무영향)
- `engine/app/settings.py` += `disable_p23: bool = False` (주석: 3부 답변 경로 주입 전체 off — 4부 2-arm 승계 제약. `thesis_update_enabled`와 별개)
- `contracts/__init__.py` export: ChainEdge, ChainEdgeVerdict, ChainPacket, PlaybookGateCheck, PlaybookGateOutcome, PlaybookGateSelector, ThesisRelation (+`__all__`)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_contracts.py
import pytest
from pydantic import ValidationError

from app.settings import Settings
from contracts import (LAYER_NAMES, SCHEMA_VERSION, ChainEdge, ChainEdgeVerdict,
                       ChainPacket, DraftAnswer, PlaybookGateCheck,
                       PlaybookGateOutcome, TypedFact, VerdictPacket)


def test_schema_version_bumped_and_backcompat():
    assert SCHEMA_VERSION == 2
    old = VerdictPacket.model_validate({"schema_version": 1})   # 구 직렬화본
    assert old.chain_verdicts == []                             # 신규 필드 기본값


def test_typed_fact_metric_identity_fields():
    f = TypedFact(id="thesis:hbm-tightness:memory_price_usd_per_gb", value=0.1,
                  unit="USD/GB", metric="memory_price_usd_per_gb",
                  observation_id="a" * 16, period="2026-07")
    assert f.metric == "memory_price_usd_per_gb" and f.observation_id == "a" * 16
    assert TypedFact(id="x", value=1.0, unit="KRW").metric == ""  # 기존 생성부 무변경


def test_chain_edge_value_space_follows_judge_axes():
    from contracts.packets import CHAIN_AXES
    from sector.judge import _VALID_AXIS
    assert set(CHAIN_AXES) == _VALID_AXIS           # 단일 진실원 드리프트 가드
    ChainEdge(edge_id="e0", edge="B->A", kind="observed", supporting_card_ids=["c1"])
    ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference")
    with pytest.raises(ValidationError):
        ChainEdge(edge_id="e2", edge="Z->A", kind="observed")   # 미지 축
    with pytest.raises(ValidationError):
        ChainEdge(edge_id="e3", edge="B->A", kind="guessed")    # kind Literal


def test_chain_packet_and_edge_verdicts():
    cp = ChainPacket(
        event="HBM 증설 발표", mechanism="공급 확대 기대", verdict="공급 완화 방향",
        edges=[ChainEdge(edge_id="e0", edge="A_prime->A", kind="inference")],
        thesis_relation=[{"thesis_revision_id": "hbm-tightness@2026-07-21T00:00:00",
                          "relation": "supports"}])
    assert cp.schema_version == SCHEMA_VERSION
    with pytest.raises(ValidationError):
        ChainPacket(event="x", mechanism="y",
                    thesis_relation=[{"thesis_revision_id": "t@1", "relation": "maybe"}])
    v = VerdictPacket(chain_verdicts=[ChainEdgeVerdict(edge_id="e0", grounded=False,
                                                       note="근거 없음")])
    assert v.chain_verdicts[0].grounded is False


def test_playbook_gate_contracts():
    chk = PlaybookGateCheck(order=1, check="D램 가격 수준",
                            metric_id="memory_price_usd_per_gb",
                            selector={"meta_filter": {"category": "DRAM"}},
                            aggregation="last", comparator=">=", threshold=0.05,
                            unit="USD/GB", max_age_days=45)
    assert chk.window_days == 0 and chk.selector.series is None
    with pytest.raises(ValidationError):
        PlaybookGateCheck(order=1, check="x", metric_id="m", aggregation="median",
                          comparator=">=", threshold=1.0, unit="u", max_age_days=1)
    out = PlaybookGateOutcome(order=1, metric_id="memory_price_usd_per_gb",
                              verdict="unavailable", unavailable_reason="no_metric")
    assert out.value is None and out.evidence_observation_id == ""


def test_layer_names_flag_and_scenario_flags():
    assert "thesis" in LAYER_NAMES and "chain" in LAYER_NAMES
    assert Settings().disable_p23 is False          # 기본 = 주입 ON
    assert Settings(disable_p23=True).disable_p23 is True
    assert DraftAnswer(answer_markdown="x").scenario_flags == []
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_chain_contracts.py -v` → ImportError (ChainPacket 등 미존재)
- [ ] **Step 3: 구현** — 위 Interfaces 전부. SCHEMA_VERSION 증가가 기존 테스트(스냅샷·직렬화 비교류)를 깨는지 전체 회귀로 확인 — 깨지면 해당 테스트의 기대값 갱신(스키마 진화 의도 반영, 동작 변화 아님을 커밋 메시지에 명기).
- [ ] **Step 4: 통과 + 회귀** — `tests/test_chain_contracts.py` green + `.venv/bin/python -m pytest tests/ -q` 전체 green
- [ ] **Step 5: Commit** — `'feat(chain): 3부 typed 계약 — ChainPacket·ChainEdgeVerdict·PlaybookGate·TypedFact metric 확장·disable_p23 (3부 T1)'`

---

### Task 2: thesis 선택기 — 결정적 rule_plan 스코어링

**Files:**
- Create: `engine/stages/thesis_context.py`
- Test: `engine/tests/test_thesis_select.py`

**Interfaces:**
- `@dataclass ThesisPick(rev: ThesisRevision, freshness: str, score: int)`
- `score_thesis(rp: SectorQueryPlan, rev: ThesisRevision) -> int` — `len(set(rp.entities) & set(rev.selectors.entities)) * 2 + len(set(rp.metrics) & set(rev.selectors.metrics)) * 1 + len(set(rp.event_types) & set(rev.selectors.event_types)) * 1` (스펙 식 그대로 — 불일치 3: rule_plan은 현재 event_types 미기입이라 그 항은 0 기여)
- `select_from_revisions(rp: SectorQueryPlan, revs: list[ThesisRevision], store, now: datetime) -> list[ThesisPick]` — **0점 제외** → freshness 계산(`sector.thesis_store.freshness`) → **stale 제외** → 정렬 `(-score, priority, rev.id)`(동률은 priority 오름차순 — 시드 priority는 낮을수록 상위, 최종 동률은 id 사전순으로 결정적) → **상위 1~3개**
- `select_theses(question: str, tstore: ThesisStore, store, now) -> list[ThesisPick]` — `build_rule_plan(question)` + `tstore.latest_all()`로 select_from_revisions 위임 (라이브 경로). eval bundle 경로는 orchestrator가 `EvalBundle.theses()` dict → `ThesisRevision.model_validate` 후 select_from_revisions 직접 호출 (T3)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_select.py
import datetime as dt

from sector.contracts import MetricObservation
from sector.queryplan import SectorQueryPlan, build_rule_plan
from sector.store import SectorStore
from sector.thesis_contracts import RequiredInput, Selectors
from sector.thesis_store import ThesisStore
from stages.thesis_context import score_thesis, select_from_revisions, select_theses
from tests.test_thesis_contracts import make_rev

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)


def _store(tmp_path):
    s = SectorStore(tmp_path / "s")
    s.append_observations([MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    return s


def test_score_weights_deterministic():
    rp = SectorQueryPlan(entities=["SK_HYNIX"], metrics=["memory_price_usd_per_gb"],
                         event_types=["supply_signal"])
    assert score_thesis(rp, make_rev()) == 4          # 1×2 + 1×1 + 1×1
    assert score_thesis(SectorQueryPlan(), make_rev()) == 0
    assert score_thesis(SectorQueryPlan(entities=["MICRON"]), make_rev()) == 0


def test_select_excludes_zero_and_stale_ranks_by_priority(tmp_path):
    store = _store(tmp_path)
    rp = SectorQueryPlan(entities=["SK_HYNIX"], metrics=["memory_price_usd_per_gb"])
    r_hit = make_rev()                                 # score 3, fresh
    r_hit2 = make_rev(id="memory-price-cycle", priority=2,
                      revision_id="memory-price-cycle@2026-07-21T00:00:00")  # 동점 — priority 뒤
    r_zero = make_rev(id="nand-decoupling",
                      revision_id="nand-decoupling@2026-07-21T00:00:00",
                      selectors=Selectors(entities=["KIOXIA"], metrics=[],
                                          segments=["nand"], event_types=[]))
    r_stale = make_rev(id="china-competition-risk",
                       revision_id="china-competition-risk@2026-07-21T00:00:00",
                       required_inputs=[RequiredInput(metric="kr_semi_export",
                                                      max_age_days=30)])  # 관측 없음 → stale
    picks = select_from_revisions(rp, [r_stale, r_hit2, r_zero, r_hit], store, NOW)
    assert [p.rev.id for p in picks] == ["hbm-tightness", "memory-price-cycle"]
    assert picks[0].freshness == "fresh" and picks[0].score == 3
    assert picks[0].rev.revision_id == "hbm-tightness@2026-07-21T00:00:00"  # revision 단위 기록


def test_select_caps_top3(tmp_path):
    store = _store(tmp_path)
    rp = SectorQueryPlan(entities=["SK_HYNIX"])
    revs = [make_rev(id=f"t{i}", revision_id=f"t{i}@2026-07-21T00:00:00", priority=i)
            for i in range(5)]
    assert len(select_from_revisions(rp, revs, store, NOW)) == 3


def test_select_theses_uses_rule_plan_not_llm(tmp_path):
    store = _store(tmp_path)
    ts = ThesisStore(tmp_path / "s")
    ts.append(make_rev())
    q = "SK하이닉스 HBM 현물가 흐름 어때?"
    rp = build_rule_plan(q)
    assert "SK_HYNIX" in rp.entities and "memory_price_usd_per_gb" in rp.metrics
    picks = select_theses(q, ts, store, NOW)
    assert [p.rev.id for p in picks] == ["hbm-tightness"]
    assert select_theses("오늘 날씨 어때?", ts, store, NOW) == []   # 0점 전원 제외
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (freshness는 `sector.thesis_store.freshness` 재사용 — 재구현 금지)
- [ ] **Step 5: Commit** — `'feat(chain): thesis 결정적 선택기 — rule_plan 스코어링·0점/stale 제외·top3 (3부 T2)'`

---

### Task 3: 배경 판 주입 — 렌더·TypedFact 승격·orchestrator/synthesize 배선·AUDIT 격리

**Files:**
- Modify: `engine/stages/thesis_context.py`, `engine/stages/synthesize.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_thesis_inject.py`

**Interfaces:**
- `render_thesis_section(picks: list[ThesisPick]) -> str` — 빈 picks → `""`. 형식:
  - 헤더 `[배경 판 — 섹터 현재 가설 (자동 합성·경향 참고)]` + **경계 문구**: "아래는 축적 근거로 자동 유지되는 '배경 가설'이다. 사실 근거로 단정 인용하지 말고 해석의 배경으로만 써라. 이 절의 가설 관련 수치는 [결정적 수치] 절의 값만 인용하라."
  - 가설당: `- ({assessment}{", 입력 일부 노후" if degraded}) {claim}: {statement texts "; " 연결}` — **revision_id·타임스탬프·key_metrics 값은 절에 미포함**(layer에만 — 숫자 불변식·수량 검출 오탐 방지)
  - 렌더 직전 **코드 검증**: `thesis_guard.quantity_literal(text)`가 잡히는 statement/claim 라인은 드롭(2부 가드가 이미 차단하지만 주입 시점 이중 차단 — 성공 기준 "주입 텍스트 수량 literal = 0")
- `thesis_typed_facts(picks) -> list[TypedFact]` — key_metrics → `TypedFact(id=f"thesis:{rev.id}:{km.metric}", value=km.value, unit=km.unit, period=km.ts, label=f"{rev.id} 관련 지표 {km.metric}", source=km.source, metric=km.metric, observation_id=km.observation_id)`. id 중복은 상위 pick first-wins
- `stages/synthesize.py`: `_render_context(..., thesis_section: str = "")`·`run_synthesize(..., thesis_section: str = "")` — thesis_section이 비면 **기존 출력과 바이트 동일**. 위치: `[메모리 섹터 근거]` 블록 뒤·`[과거사례 대조]` 앞
- `orchestrator.py`:
  - `_audit_evidence(ra, sector_cycle_text, sector_metric_notes, sector_cards, case_matches) -> tuple[list[str], dict[str, str]]` — 기존 ⑧ AUDITOR의 evidence_texts/evidence_docs 조립 블록(orchestrator.py:604~630)을 그대로 추출(동작 불변). **thesis 파라미터 없음** — AUDIT 불포함의 구조 보장
  - sector_rag 블록 뒤(run_assemble 전): `from app.settings import settings` 후

```python
    thesis_picks, thesis_section = [], ""
    if not settings.disable_p23 and profile.sector_rag_enabled:
        try:
            import datetime as _th_dt
            from sector.thesis_contracts import ThesisRevision as _ThRev
            from sector.thesis_store import ThesisStore as _ThStore
            from sector.queryplan import build_rule_plan as _th_rule
            from stages.thesis_context import (render_thesis_section,
                                               select_from_revisions, thesis_typed_facts)
            if eval_bundle:
                _th_store = eval_bundle.store()
                _th_revs = [_ThRev.model_validate(t) for t in eval_bundle.theses()]
                _th_now = _th_dt.datetime.fromisoformat(
                    eval_bundle.manifest["as_of"]).replace(tzinfo=_th_dt.timezone.utc)
            else:
                from sector.api import _get_store as _th_get
                _th_store = _th_get()
                _th_revs = _ThStore(_th_store.root).latest_all()
                _th_now = _th_dt.datetime.now(_th_dt.timezone.utc)
            thesis_picks = select_from_revisions(
                _th_rule(plan.standalone_question or question), _th_revs,
                _th_store, _th_now)
            if thesis_picks:
                thesis_section = render_thesis_section(thesis_picks)
                sector_facts = list(sector_facts) + thesis_typed_facts(thesis_picks)
                yield _layer("thesis", {
                    "selected": [{"revision_id": p.rev.revision_id, "score": p.score,
                                  "freshness": p.freshness} for p in thesis_picks]})
        except Exception:  # noqa: BLE001 — never-raise, 무주입 폴백
            degraded.append("thesis")
            thesis_picks, thesis_section = [], ""
```

  - run_synthesize 호출에 `thesis_section=thesis_section` 전달, ⑧의 evidence 조립을 `_audit_evidence(...)` 호출로 치환(thesis 미전달)
- eval bundle 모드: `EvalBundle.theses()`가 as_of 경계 선택본(2부 T7) — 라이브 store 오염 없음

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_inject.py
import inspect

from contracts import DaPacket, PlanPacket, UnitAnswer
from sector.thesis_contracts import Evidence, Statement
from sector.thesis_guard import quantity_literal
from stages.synthesize import _render_context
from stages.thesis_context import ThesisPick, render_thesis_section, thesis_typed_facts
from tests.test_thesis_contracts import make_rev


def _pick(freshness="fresh", **kw):
    return ThesisPick(rev=make_rev(**kw), freshness=freshness, score=3)


def _st(text):
    sup = [Evidence(card_id=f"c{i}", canonical_url=f"https://p{i}.com/1",
                    publisher_id=f"p{i}.com", quote="q") for i in (1, 2)]
    return Statement(statement_id="s1", text=text, supporting=sup)


def test_render_boundary_label_and_no_numbers():
    sec = render_thesis_section([_pick()])
    assert "[배경 판" in sec and "사실 근거로 단정 인용하지" in sec
    assert "HBM 수요가 공급을 앞선다" in sec            # make_rev statement text
    assert quantity_literal(sec) == []                  # 수량 literal 0 (코드 검증)
    assert "0.1" not in sec and "revision_id" not in sec and "2026-07-21" not in sec
    assert render_thesis_section([]) == ""


def test_render_degraded_label_and_bad_statement_dropped():
    sec = render_thesis_section([
        _pick(freshness="degraded",
              statements=[_st("HBM 수요가 공급을 앞선다"), _st("가격 12% 급등")])])
    assert "입력 일부 노후" in sec
    assert "12%" not in sec                             # 주입 시점 이중 차단


def test_thesis_typed_facts_carry_metric_identity():
    facts = thesis_typed_facts([_pick()])
    assert facts[0].id == "thesis:hbm-tightness:memory_price_usd_per_gb"
    assert facts[0].metric == "memory_price_usd_per_gb"
    assert facts[0].observation_id == "x" * 16          # make_rev key_metrics 그대로
    assert facts[0].value == 0.1 and facts[0].period == "2026-07"


def _ctx(**kw):
    plan = PlanPacket(tier=2, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")
    da = DaPacket(unit_answers=[UnitAnswer(unit_id="q0", model="da_gpt",
                                           answer_text="a")])
    return _render_context(plan, da, None, None, None, None, [], None, **kw)


def test_synthesize_off_path_byte_identical():
    base = _ctx()
    assert _ctx(thesis_section="") == base              # off 경로 바이트 동일
    with_t = _ctx(thesis_section="[배경 판 — 섹터 현재 가설 (자동 합성·경향 참고)]\n- x")
    assert "[배경 판" in with_t and "[배경 판" not in base


def test_audit_evidence_helper_excludes_thesis_by_signature():
    from orchestrator import _audit_evidence
    params = inspect.signature(_audit_evidence).parameters
    assert "thesis_section" not in params and "thesis_picks" not in params
    from contracts import RaPacket
    texts, docs = _audit_evidence(RaPacket(), "", [], [], [])
    assert isinstance(texts, list) and isinstance(docs, dict)
```

- [ ] **Step 2~3: 실패 확인 → 구현** (orchestrator ⑧ 블록 추출은 diff 최소 — 동작 불변 확인: 추출 전후 기존 audit 테스트 green)
- [ ] **Step 4: 통과 + 회귀** — 전체 pytest. 특히 기존 synthesize·audit·p2/p3 offline 테스트 무변경 통과 (off-path 보장)
- [ ] **Step 5: Commit** — `'feat(chain): thesis 배경 판 주입 — 경계 문구·degraded 라벨·수량 0 검증·TypedFact 승격·AUDIT 격리 (3부 T3)'`

---

### Task 4: ChainPacket 생성 (VERIFY 이전) — 코드 실존 검증

**Files:**
- Create: `engine/stages/chain.py`
- Modify: `engine/providers.py` (`"chain_synth": [("anthropic", settings.model_claude_sonnet, "low")]` — `"thesis_updater"` 아래), `engine/orchestrator.py`
- Test: `engine/tests/test_chain_stage.py`

**Interfaces:**
- structured output `_ChainOut{event, mechanism, verdict, edges: [{edge, kind, supporting_card_ids, metric_fact_ids, contradicting_card_ids}], thesis_relation: [{thesis_revision_id, relation}]}` (전 필드 str/list — LLM 제안일 뿐, 검증은 코드)
- `async run_chain(plan: PlanPacket, table: ClaimTable, sector_cards: list, ra: RaPacket, thesis_picks: list, *, role=None, overrides=None) -> ChainPacket | None`:
  1. 입력 조립: claim 목록(id·text·source), 섹터 카드(id·title·interpreted_signal), typed_facts(id·label), thesis(revision_id·claim), CHAIN_AXES 어휘·kind 정의를 프롬프트에
  2. LLM 1콜 (`role or Role("chain_synth", overrides)`, effort low)
  3. **코드 검증** (LLM 불신):
     - `edge` 문자열이 ChainEdge validator 불통과 → 해당 edge 드롭
     - 인용 ID 실존 대조: `supporting_card_ids`·`contradicting_card_ids` ⊆ {sector_cards id} ∪ {curated NewsItem id}(`ra.curated_items()` 전 유닛 합집합), `metric_fact_ids` ⊆ {table.typed_facts id} — **미실존 드롭**
     - 드롭 후 supporting_card_ids와 metric_fact_ids가 **모두 비면** `observed`→`inference` 강등
     - `thesis_relation`의 revision_id ∉ {p.rev.revision_id} → 드롭
     - `edge_id`는 코드가 순번 부여(`e0`, `e1`, …)
  4. 예외·전 edge 드롭 → `None` (never-raise; 호출측 degraded)
- orchestrator: CALC·ANSWERABILITY 뒤·첫 run_verify 직전 —

```python
    chain = None
    if not settings.disable_p23 and profile.sector_rag_enabled and table.claims:
        try:
            from stages.chain import run_chain
            chain = await run_chain(plan, table, sector_cards, ra, thesis_picks,
                                    overrides=overrides)
        except Exception:  # noqa: BLE001
            degraded.append("chain")
    if chain is not None:
        yield _layer("chain", chain.model_dump(mode="json"))
```

  (REFLECT 라운드에서 재생성하지 않음 — 라운드 0 체인을 이후 verify 호출에 그대로 전달. 근거: 체인은 사건-기제 서술이고 재조사는 근거 보강이라 구조가 안 변함 + 비용/결정성. codex 판정 요청 항목)

**게이트 판단 근거(마킹):** `profile.sector_rag_enabled` 결속 — edge 어휘가 메모리 섹터 인과 사슬(CHAIN_AXES)이라 비섹터 경량 프로필(fact_lookup)에선 무의미·비용 낭비. full/판단형 프로필은 전부 활성.

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_stage.py
import asyncio

from contracts import AtomicClaim, ClaimTable, PlanPacket, RaPacket, TypedFact
from sector.contracts import SectorCard
from stages.chain import run_chain
from stages.thesis_context import ThesisPick
from tests.test_thesis_contracts import make_rev


def _plan():
    return PlanPacket(tier=3, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")


def _card(cid):
    return SectorCard(id=cid, ts="2026-07-20T00:00:00", axis="A", direction="pos",
                      magnitude=2, source_grade="A", title=f"t-{cid}",
                      interpreted_signal="sig", raw_quote="본문", url="https://a.com/1",
                      entities=["SK_HYNIX"])


def _table():
    return ClaimTable(
        claims=[AtomicClaim(id="cl-1", text="HBM 수요 강세", type="fact", source="da_gpt")],
        typed_facts=[TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB")])


class _Role:
    model = "fake-sonnet"
    def __init__(self, out): self.out, self.calls = out, 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        return response_format.model_validate(self.out)


_PROPOSAL = {
    "event": "HBM 증설 보도", "mechanism": "공급 확대 기대", "verdict": "혼조",
    "edges": [
        {"edge": "B->A", "kind": "observed",
         "supporting_card_ids": ["card-1", "ghost"],
         "metric_fact_ids": ["sector:dram_price", "no-such-fact"],
         "contradicting_card_ids": ["ghost2"]},
        {"edge": "C->B", "kind": "observed", "supporting_card_ids": ["ghost"],
         "metric_fact_ids": [], "contradicting_card_ids": []},
        {"edge": "Z->A", "kind": "observed", "supporting_card_ids": ["card-1"],
         "metric_fact_ids": [], "contradicting_card_ids": []}],
    "thesis_relation": [
        {"thesis_revision_id": "hbm-tightness@2026-07-21T00:00:00",
         "relation": "supports"},
        {"thesis_revision_id": "ghost@2026-01-01T00:00:00", "relation": "contradicts"}]}


def test_code_validation_drops_demotes_and_assigns_ids():
    picks = [ThesisPick(rev=make_rev(), freshness="fresh", score=3)]
    cp = asyncio.run(run_chain(_plan(), _table(), [_card("card-1")], RaPacket(),
                               picks, role=_Role(_PROPOSAL)))
    assert cp is not None and [e.edge_id for e in cp.edges] == ["e0", "e1"]
    e0, e1 = cp.edges
    assert e0.supporting_card_ids == ["card-1"]          # ghost 드롭
    assert e0.metric_fact_ids == ["sector:dram_price"]   # no-such-fact 드롭
    assert e0.contradicting_card_ids == []               # ghost2 드롭
    assert e0.kind == "observed"
    assert e1.kind == "inference"                        # 빈 supporting → 강등
    assert len(cp.edges) == 2                            # Z->A 값공간 위반 드롭
    assert [t.thesis_revision_id for t in cp.thesis_relation] == \
        ["hbm-tightness@2026-07-21T00:00:00"]            # 미주입 revision 드롭


def test_never_raise_returns_none():
    class _Boom:
        model = "boom"
        async def run(self, *a, **k): raise RuntimeError("down")
    cp = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [], role=_Boom()))
    assert cp is None
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** / **Step 5: Commit** — `'feat(chain): ChainPacket 합성 스테이지 — 실존 검증·미실존 드롭·observed 강등·thesis_relation 결속 (3부 T4)'`

---

### Task 5: VERIFY chain_verdicts + G2 metric 식별자 + RISK 소비

**Files:**
- Modify: `engine/stages/verify.py`, `engine/sector/evidence.py`, `engine/stages/risk.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_chain_verify_risk.py`

**Interfaces:**
- `run_verify(..., chain: ChainPacket | None = None, sector_cards: list | None = None)` — 기존 파라미터 뒤 keyword 추가. `chain`이 있으면 VerdictPacket에 `chain_verdicts` 채움 (**코드 판정 — 생성부 불신 독립 재검증**):
  - edge별 `grounded = True` 조건 전부 충족: ① 인용 ID(supporting_card_ids ⊆ sector_cards∪ra ids, metric_fact_ids ⊆ table.typed_facts ids) 전원 실존 ② supporting_card_ids 또는 metric_fact_ids **비어있지 않음** ③ 인용 카드 전원 `ts[:10] <= plan.knowledge_cutoff` (as_of 클린). 미충족 시 grounded=False + note 사유
  - **grounded 정의(마킹):** kind와 독립 — 스펙 "grounded_edge_ratio = 실존 검증된 근거 ID 보유 edge 비율" 직역. inference라도 유효 metric 인용이 있으면 grounded 가능. codex 판정 요청 항목
- **G2 metric 식별자 일치** (스펙 r2 #3): `_numeric_anchors` 반환을 `(value, unit, metric)` 3-튜플로, `_g2_supported(value, unit, anchors, claim_metric: str = "")` —
  - anchor의 metric이 빈 문자열(미태그: yahoo·toss·calc 유래) → 기존 동작 그대로
  - metric 태그 anchor는 `claim_metric`(claim.norm.metric, lower)이 `METRIC_REGISTRY[metric]["keywords"]` 중 하나를 포함하거나 label 부분일치할 때만 대조 자격 — 아니면 그 anchor는 **그 claim에 사용 불가** (우연 동수치 타 지표 앵커링 차단, fail-closed: claim_metric 비어있으면 태그 anchor 사용 불가)
  - **판단 근거(마킹):** registry 키(영문 식별자)와 claim.norm.metric(자유 한국어)은 직접 동일성 비교 불가 — registry `keywords`가 유일한 결정적 교량. 미태그 anchor 무변경으로 기존 G2 회귀 0
- `sector/evidence.py sector_typed_facts`: 생성하는 TypedFact 2건에 `metric="memory_price_usd_per_gb"`, `observation_id=observation_id(metric, ts, meta)`(`sector.thesis_contracts.observation_id`) 기입 — "섹터 유래 fact 확장" 스펙 항목
- `run_risk(..., chain: ChainPacket | None = None, verdict: VerdictPacket | None = None)` — chain이 있으면 프롬프트에 `[인과 체인 판정]` 절 추가: edge별 `- {edge_id} {edge} ({kind}, {'근거확인' if grounded else '미확인'})` + verified claim 수 요약. disable 시 파라미터 None → 기존 프롬프트 그대로
- orchestrator: 모든 `run_verify(...)` 호출(3곳)에 `chain=chain, sector_cards=sector_cards` 추가, `run_risk(...)`에 `chain=chain, verdict=verdict` 추가. verify layer data에 `"chain_verdicts": [{"edge_id", "grounded", "note"}...]` 포함(`_verify_layer_data` 확장 — chain 없으면 키 생략, off-path 동일)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_verify_risk.py
import asyncio

import pytest

from contracts import (AtomicClaim, ChainEdge, ChainPacket, ClaimTable, PlanPacket,
                       RaPacket, TypedFact)
from stages.risk import run_risk
from stages.verify import _g2_supported, run_verify
from tests.test_chain_stage import _card, _plan


def _table():
    return ClaimTable(
        claims=[AtomicClaim(id="cl-1", text="배경 서술", type="context", source="da_gpt")],
        typed_facts=[TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB")])


def _chain():
    return ChainPacket(event="e", mechanism="m", edges=[
        ChainEdge(edge_id="e0", edge="B->A", kind="observed",
                  supporting_card_ids=["card-1"]),
        ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference"),
        ChainEdge(edge_id="e2", edge="C->B", kind="observed",
                  supporting_card_ids=["card-future"]),
        ChainEdge(edge_id="e3", edge="B->A", kind="observed",
                  metric_fact_ids=["no-such-fact"], supporting_card_ids=[])])


def test_chain_verdicts_code_regrounding():
    cards = [_card("card-1")]
    future = _card("card-future"); future.ts = "2026-07-25T00:00:00"  # cutoff 이후
    verdict = asyncio.run(run_verify(_plan(), _table(), RaPacket(), [],
                                     chain=_chain(), sector_cards=cards + [future]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e0"].grounded is True
    assert by_id["e1"].grounded is False        # 인용 전무
    assert by_id["e2"].grounded is False and "as_of" in by_id["e2"].note  # 미래 카드
    assert by_id["e3"].grounded is False        # 미실존 fact 인용


def test_chain_none_keeps_packet_shape():
    verdict = asyncio.run(run_verify(_plan(), _table(), RaPacket(), []))
    assert verdict.chain_verdicts == []          # off-path 무영향


def test_g2_metric_identity_blocks_cross_metric_anchor():
    tagged = [(5.0, "percent", "memory_price_usd_per_gb")]
    assert _g2_supported(5.0, "percent", tagged, claim_metric="D램 현물가")   # keyword "현물가"
    assert not _g2_supported(5.0, "percent", tagged, claim_metric="영업이익률")
    assert not _g2_supported(5.0, "percent", tagged, claim_metric="")        # fail-closed
    untagged = [(5.0, "percent", "")]
    assert _g2_supported(5.0, "percent", untagged, claim_metric="영업이익률")  # 기존 동작


def test_sector_typed_facts_now_carry_metric(tmp_path):
    from sector.contracts import MetricObservation
    from sector.evidence import sector_typed_facts
    from sector.store import SectorStore
    from sector.thesis_contracts import observation_id
    s = SectorStore(tmp_path / "s")
    meta = {"category": "DRAM", "item": "ddr5_16gb"}
    s.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=0.09,
                          unit="USD/GB", meta=meta),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    facts = sector_typed_facts(s)
    price = next(f for f in facts if f.id == "sector:dram_price")
    assert price.metric == "memory_price_usd_per_gb"
    assert price.observation_id == observation_id("memory_price_usd_per_gb",
                                                  "2026-07", meta)


def test_risk_consumes_chain_verdicts(monkeypatch):
    captured = {}
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, prompt, instr, response_format=None, **kw):
            captured["prompt"] = prompt
            return response_format.model_validate({"bear_cases": [], "wrong_if": ""})
    monkeypatch.setattr("stages.risk.Role", _FakeRole)
    verdict = asyncio.run(run_verify(_plan(), _table(), RaPacket(), [],
                                     chain=_chain(), sector_cards=[_card("card-1")]))
    asyncio.run(run_risk(_plan(), _table(), chain=_chain(), verdict=verdict))
    assert "[인과 체인 판정]" in captured["prompt"] and "e0" in captured["prompt"]
    captured.clear()
    asyncio.run(run_risk(_plan(), _table()))     # off-path
    assert "[인과 체인 판정]" not in captured["prompt"]
```

  (주의: `_table()`의 claim은 `type="context"`·`source="da_gpt"`·secondary 아님 → G1 후보 0 = LLM 무호출 — verify를 오프라인으로 돌리는 기존 테스트 관례. 구현 중 후보 규칙이 걸리면 fixture가 아니라 후보 판정을 재확인할 것.)

- [ ] **Step 2~4: 실패→구현→통과+회귀** — `_g2_supported` 호출부(run_verify 내 2곳)에 `claim_metric=c.norm.metric` 전달. 기존 G2 테스트 전량 green(미태그 anchor 무변경 확인).
- [ ] **Step 5: Commit** — `'feat(chain): VERIFY chain_verdicts 코드 재검증·G2 metric 식별자 대조·RISK 체인 소비 (3부 T5)'`

---

### Task 6: SYNTHESIZE 시나리오 계약 — 코드 후검증·1회 재합성·재실패 플래그

**Files:**
- Modify: `engine/stages/synthesize.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_scenario_contract.py`

**Interfaces:**
- `_SCENARIO_INSTR`(상수) — `_INSTR`에 조건부 append: "답변 말미에 `## 긍정 시나리오`와 `## 부정 시나리오` 절을 각각 두라. 각 절은 다음 4줄을 반드시 포함: `- 체인:` (근거 사슬 — [인과 체인] 절의 edge_id 인용), `- 지표:` ([결정적 수치] 절 항목 인용, 결정적 수치가 없으면 '지표 없음'), `- 유효 조건:` (이 시나리오가 유효하려면 관찰돼야 할 것), `- 기각 조건:` (이 시나리오를 기각할 관찰)."
- `_render_context`에 `chain: ChainPacket | None = None, chain_verdicts: list | None = None` — chain 있으면 `[인과 체인]` 절 렌더: `- {edge_id} {edge} ({kind}/{'근거확인' if grounded else '미확인'}): 인용 {supporting_card_ids + metric_fact_ids}`
- `validate_scenarios(answer_md: str, chain: ChainPacket, typed_facts: list[TypedFact]) -> list[str]` — 코드 후검증 (빈 리스트 = 통과):
  - `## 긍정 시나리오`·`## 부정 시나리오` 절 존재
  - 각 절에 `- 체인:`·`- 지표:`·`- 유효 조건:`·`- 기각 조건:` 라인 존재
  - `- 체인:` 라인이 chain의 실존 edge_id를 ≥1 인용 (임의 id 불인정)
  - typed_facts 비어있지 않으면 `- 지표:` 라인이 typed_fact의 label 또는 id를 ≥1 포함, 비어있으면 "지표 없음" 허용
- `run_synthesize(..., chain: ChainPacket | None = None, chain_verdicts=None, scenario_required: bool = False)` — scenario_required이고 chain 존재 시: 1차 합성 → validate → 미충족이면 **1회 재합성**(컨텍스트에 `[재합성 — 시나리오 계약 미충족]\n` + 사유 목록 append) → 재실패 시 `DraftAnswer.scenario_flags = issues` (답변은 유지 — 플래그만)
- orchestrator: `run_synthesize(..., chain=chain, chain_verdicts=verdict.chain_verdicts, scenario_required=(chain is not None and risk.applicable))` — **판단 근거(마킹):** 시나리오 계약은 판단형(tier3/risk 적용) 답변의 계약 — fact_lookup에 긍정/부정 시나리오를 강제하면 없는 판단을 지어내게 함. scenario_flags 발생 시 `degraded.append("scenario_contract")` + synthesize 뒤 `yield _layer("chain", {... "scenario_flags": draft.scenario_flags})`가 아니라 audit layer 방출 전에 별도 항목 없이 FinalAnswer.degraded로 노출(layer 추가 없이 관찰 가능 — eval은 degraded로 잡음)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_scenario_contract.py
import asyncio

from contracts import (ChainEdge, ChainPacket, DaPacket, PlanPacket, TypedFact,
                       UnitAnswer)
from stages.synthesize import run_synthesize, validate_scenarios

_CHAIN = ChainPacket(event="e", mechanism="m", edges=[
    ChainEdge(edge_id="e0", edge="B->A", kind="observed",
              supporting_card_ids=["card-1"])])
_FACTS = [TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB",
                    label="D램 현물가 (ddr5_16gb)")]

_GOOD = """결론.

## 긍정 시나리오
- 체인: e0 (B->A) 경로가 유지된다
- 지표: D램 현물가 (ddr5_16gb) 상승 지속
- 유효 조건: 하이퍼스케일러 발주 유지
- 기각 조건: 발주 축소 보도

## 부정 시나리오
- 체인: e0 역전 — 발주 둔화
- 지표: D램 현물가 (ddr5_16gb) 하락 전환
- 유효 조건: 재고 경고 2건 이상
- 기각 조건: 가격 반등
"""


def test_validate_good_and_missing_section():
    assert validate_scenarios(_GOOD, _CHAIN, _FACTS) == []
    bad = _GOOD.split("## 부정 시나리오")[0]
    assert any("부정 시나리오" in i for i in validate_scenarios(bad, _CHAIN, _FACTS))


def test_validate_rejects_fake_edge_and_missing_metric():
    fake = _GOOD.replace("체인: e0", "체인: e9")
    assert any("체인" in i for i in validate_scenarios(fake, _CHAIN, _FACTS))
    no_metric = _GOOD.replace("D램 현물가 (ddr5_16gb)", "임의 지표")
    assert any("지표" in i for i in validate_scenarios(no_metric, _CHAIN, _FACTS))
    # 결정적 수치가 아예 없으면 '지표 없음' 허용
    ok = _GOOD.replace("D램 현물가 (ddr5_16gb) 상승 지속", "지표 없음") \
              .replace("D램 현물가 (ddr5_16gb) 하락 전환", "지표 없음")
    assert validate_scenarios(ok, _CHAIN, []) == []


def _plan_da():
    plan = PlanPacket(tier=3, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")
    da = DaPacket(unit_answers=[UnitAnswer(unit_id="q0", model="da_gpt",
                                           answer_text="a")])
    return plan, da


def test_resynthesis_once_then_flag(monkeypatch):
    answers = ["시나리오 절 없는 답", "여전히 없는 답"]
    prompts = []
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, ctx, instr, **kw):
            prompts.append(ctx)
            return answers[len(prompts) - 1]
    monkeypatch.setattr("stages.synthesize.Role", _FakeRole)
    plan, da = _plan_da()
    # extra_typed_facts 없는 최소 호출 — claim_table 없음 → typed_facts는 빈 취급
    draft = asyncio.run(run_synthesize(plan, da, chain=_CHAIN,
                                       scenario_required=True))
    assert len(prompts) == 2                             # 정확 1회 재합성
    assert "시나리오 계약 미충족" in prompts[1]
    assert draft.scenario_flags                          # 재실패 플래그
    assert draft.answer_markdown == "여전히 없는 답"


def test_success_and_off_path_single_call(monkeypatch):
    calls = []
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, ctx, instr, **kw):
            calls.append(instr)
            return _GOOD
    monkeypatch.setattr("stages.synthesize.Role", _FakeRole)
    plan, da = _plan_da()
    draft = asyncio.run(run_synthesize(plan, da, chain=_CHAIN,
                                       scenario_required=True))
    assert len(calls) == 1 and draft.scenario_flags == []
    assert "## 긍정 시나리오" in calls[0]                # 계약 지시 포함
    calls.clear()
    asyncio.run(run_synthesize(plan, da))                # off-path
    assert len(calls) == 1 and "## 긍정 시나리오" not in calls[0]
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (validate의 지표 대조는 chain 인용 metric_fact와 run_synthesize에 전달된 claim_table.typed_facts 합집합 기준 — claim_table 없으면 빈 목록)
- [ ] **Step 5: Commit** — `'feat(chain): SYNTHESIZE 시나리오 계약 — 구조 마커 후검증·1회 재합성·재실패 플래그 (3부 T6)'`

---

### Task 7: 플레이북 구조 게이트 — all-or-none·코드 판정·문자열 하위 호환

**Files:**
- Modify: `engine/stages/playbook.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_playbook_gates.py`

**Interfaces (stages/playbook.py):**
- `_STRUCT_KEYS = ("metric_id", "aggregation", "comparator", "threshold", "unit", "max_age_days")` (selector·window_days는 선택)
- `parse_gate_checks(pb: dict) -> tuple[list[PlaybookGateCheck], list[str]]` — gate dict별: _STRUCT_KEYS 전무 → 문자열 gate(스킵, 로그 없음 — 하위 호환). 전부 존재+PlaybookGateCheck validate 통과 → 채택. **일부만 존재 또는 validate 실패 → 그 gate 구조 판정 전체 무시 + 로그 문자열**("gate {order}: 구조 필드 불완전 — 문자열 gate로만 동작"). `aggregation in ("mean_window", "yoy")`인데 `window_days <= 0`이면 불완전 취급
- `evaluate_gate(check: PlaybookGateCheck, store, now: datetime) -> PlaybookGateOutcome` — 전부 코드:
  - `check.metric_id not in METRIC_REGISTRY` 또는 관측 0건(meta_filter 적용 후) → `unavailable/no_metric`
  - 관측 unit(비어있지 않은 최신 관측 기준) != check.unit이고 `aggregation != "yoy"` → `unavailable/unit_mismatch`; **yoy는 산출 단위가 percent로 고정 — check.unit != "percent"면 unit_mismatch** (판단 근거: 비율 지표에 원단위 임계는 범주 오류)
  - `sector.period.parse_period`로 ts 해석 — 미래·파싱불가 관측 무효(2부 freshness와 동일 fail-closed), 최신 유효 관측 나이 > max_age_days → `unavailable/stale_data`
  - aggregation: `last`=최신값 / `mean_window`=now-window_days 내 평균 / `yoy`=(최신값/1년 전 최근접값 - 1)×100, 1년 전 값 부재 → stale_data
  - comparator 적용 → `pass|fail`, `evidence_observation_id = sector.thesis_contracts.observation_id(metric, ts, meta)` (최신 관측 기준)
- `evaluate_playbook_gates(pb, store, now) -> tuple[list[PlaybookGateOutcome], list[str]]` — parse + 채택 gate만 평가
- orchestrator: playbook 매칭 직후(⓪′ 블록 내), `playbook and not settings.disable_p23`이면 `_store = eval_bundle.store() if eval_bundle else sector.api._get_store()`로 평가, 결과를 playbook layer data에 `"gate_outcomes": [...]`·`"gate_logs": [...]` 추가. **값의 답변 진입은 [결정적 수치] 경로만**: outcome이 있으면 `- [플레이북 게이트] {check}: {metric_id}={value} {unit} ({verdict}, 관측 {evidence_observation_id[:8]})` 라인을 `sector_metric_notes`에 append(주: sector_metric_notes는 합성 det 절에 그대로 들어감 — synthesize.py:137). unavailable은 notes 미기재(수치 없음), layer에만
- 기존 `format_gates`·`format_connection`·`_valid_playbook`·문자열 gate 경로 무변경

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_playbook_gates.py
import datetime as dt

from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_contracts import observation_id
from stages.playbook import evaluate_gate, evaluate_playbook_gates, parse_gate_checks

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)

_STRUCT = {"order": 1, "check": "D램 가격 수준", "operationalization": "현물가 확인",
           "metric_id": "memory_price_usd_per_gb",
           "selector": {"meta_filter": {"category": "DRAM"}},
           "aggregation": "last", "comparator": ">=", "threshold": 0.05,
           "unit": "USD/GB", "max_age_days": 45}


def _pb(gates):
    return {"slug": "s", "situation": "x", "triggers": [], "topics": [],
            "conclusionType": "방향 판단", "gates": gates, "connection": "c",
            "status": "holdout_passed"}


def test_parse_all_or_none():
    checks, logs = parse_gate_checks(_pb([_STRUCT]))
    assert len(checks) == 1 and logs == []
    partial = {"order": 2, "check": "y", "operationalization": "z",
               "metric_id": "memory_price_usd_per_gb"}          # 일부만 — 전체 무시
    checks, logs = parse_gate_checks(_pb([partial]))
    assert checks == [] and len(logs) == 1
    legacy = {"order": 3, "check": "y", "operationalization": "z"}  # 문자열 gate
    checks, logs = parse_gate_checks(_pb([legacy]))
    assert checks == [] and logs == []                          # 하위 호환 — 무로그
    mw = dict(_STRUCT, aggregation="mean_window")               # window_days 없음
    checks, logs = parse_gate_checks(_pb([mw]))
    assert checks == [] and len(logs) == 1


def _store(tmp_path, obs):
    s = SectorStore(tmp_path / "s")
    s.append_observations(obs)
    return s


def test_evaluate_pass_with_evidence_observation(tmp_path):
    meta = {"category": "DRAM"}
    store = _store(tmp_path, [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta=meta)])
    (chk,), _ = parse_gate_checks(_pb([_STRUCT]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and out.value == 0.1
    assert out.evidence_observation_id == observation_id(
        "memory_price_usd_per_gb", "2026-07", meta)


def test_evaluate_unavailable_reasons(tmp_path):
    (chk,), _ = parse_gate_checks(_pb([_STRUCT]))
    assert evaluate_gate(chk, _store(tmp_path / "a", []), NOW).unavailable_reason == "no_metric"
    bad_unit = _store(tmp_path / "b", [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="KRW/GB", meta={"category": "DRAM"})])
    assert evaluate_gate(chk, bad_unit, NOW).unavailable_reason == "unit_mismatch"
    old = _store(tmp_path / "c", [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2025-01", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    assert evaluate_gate(chk, old, NOW).unavailable_reason == "stale_data"


def test_evaluate_yoy_percent_unit(tmp_path):
    meta = {"category": "DRAM"}
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2025-07", value=0.08,
                          unit="USD/GB", meta=meta),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    yoy = dict(_STRUCT, aggregation="yoy", window_days=400, unit="percent",
               comparator=">=", threshold=10.0, max_age_days=45)
    (chk,), _ = parse_gate_checks(_pb([yoy]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and abs(out.value - 25.0) < 0.01
    wrong = dict(yoy, unit="USD/GB")
    (chk2,), _ = parse_gate_checks(_pb([wrong]))
    assert evaluate_gate(chk2, store, NOW).unavailable_reason == "unit_mismatch"


def test_evaluate_playbook_gates_wraps(tmp_path):
    store = _store(tmp_path, [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    outs, logs = evaluate_playbook_gates(
        _pb([_STRUCT, {"order": 9, "check": "문자열만", "operationalization": "o"}]),
        store, NOW)
    assert len(outs) == 1 and outs[0].verdict == "pass" and logs == []
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (기존 test_playbook_match.py 무변경 통과 = 문자열 하위 호환 증거)
- [ ] **Step 5: Commit** — `'feat(chain): 플레이북 구조 게이트 — all-or-none 파싱·코드 조회 판정·evidence 관측 결속 (3부 T7)'`

---

### Task 8: bundle/eval 배선 + 전체 회귀

**Files:**
- Modify: `engine/evals/chain_judge.py` (`judge_edge_entailment`), `engine/evals/metrics.py` (`grounded_edge_ratio`), `engine/evals/run_eval.py` (`_run_one_chain` — chain layer 소비, `entailed_edge_ratio` 실측정으로 교체 run_eval.py:535)
- Test: `engine/tests/test_chain_eval_wiring.py`

**Interfaces:**
- `evals/metrics.py`: `chain_layer(layers: list[dict]) -> dict | None` — `name == "chain"`인 layer의 data(ChainPacket dump). `grounded_edge_ratio(layers) -> float | None` — verify layer(최신 round)의 `chain_verdicts`에서 grounded 비율, chain 부재 시 None (성공 기준 "grounded_edge_ratio ≥ 0.7" 계측 지점)
- `evals/chain_judge.py`: `async judge_edge_entailment(case_id, edges: list[dict], bundle_text, role, raws_sink=None) -> float | None` — edge별 구조화 판정 `_EdgeOut{rows: [{edge_id, entailed: bool, reason}]}` — "인용된 근거(카드 ID의 본문)가 이 edge 주장(edge·kind)을 지지하는가". 프롬프트에 edge당 인용 card 본문 스니펫(bundle에서 역참조) 제공. 반환 = entailed / 전체 edge (스펙 r2-B7: 분모는 전체). invalid 1회 재시도 후 None. edges 빈 목록 → None
- `run_eval._run_one_chain`: layers에서 `chain_layer`·`grounded_edge_ratio` 추출, `entailed_edge_ratio = await judge_edge_entailment(...)` (chain layer 있을 때만 — 없으면 None 유지), rec에 `"grounded_edge_ratio"` 필드 추가
- ChainPacket layer는 run_qa가 이미 방출(T4) — eval 레코드의 `layers` 경유로 bundle 캡처 대체(별도 파일 저장 없음. 스펙 1부 edge entailment가 소비하는 실체는 layer의 packet dump). find_violations는 chain layer의 url 미포함으로 무영향

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_eval_wiring.py
import asyncio

from evals.chain_judge import judge_edge_entailment
from evals.metrics import chain_layer, grounded_edge_ratio


def _layers():
    return [
        {"kind": "layer", "name": "chain", "round": 0, "data": {
            "event": "e", "mechanism": "m", "verdict": "",
            "edges": [{"edge_id": "e0", "edge": "B->A", "kind": "observed",
                       "supporting_card_ids": ["card-1"], "metric_fact_ids": [],
                       "contradicting_card_ids": []}],
            "thesis_relation": []}},
        {"kind": "layer", "name": "verify", "round": 0, "data": {
            "counts": {"verified": 1, "unverified": 0, "rejected": 0},
            "chain_verdicts": [{"edge_id": "e0", "grounded": True, "note": ""},
                               {"edge_id": "e1", "grounded": False, "note": "인용 전무"}]}},
    ]


def test_chain_layer_and_grounded_ratio():
    layers = _layers()
    assert chain_layer(layers)["edges"][0]["edge_id"] == "e0"
    assert grounded_edge_ratio(layers) == 0.5
    assert chain_layer([]) is None and grounded_edge_ratio([]) is None


class _Role:
    model = "fake"
    def __init__(self, rows): self.rows = rows
    async def run(self, prompt, instructions="", response_format=None, **kw):
        return response_format.model_validate({"rows": self.rows})


def test_judge_edge_entailment_ratio_over_all_edges():
    edges = _layers()[0]["data"]["edges"] + [
        {"edge_id": "e1", "edge": "C->B", "kind": "inference",
         "supporting_card_ids": [], "metric_fact_ids": [],
         "contradicting_card_ids": []}]
    role = _Role([{"edge_id": "e0", "entailed": True, "reason": ""},
                  {"edge_id": "e1", "entailed": False, "reason": "근거 없음"}])
    ratio = asyncio.run(judge_edge_entailment("cj-t", edges, "card-1: 본문", role))
    assert ratio == 0.5                                   # 분모 = 전체 edge (r2-B7)
    assert asyncio.run(judge_edge_entailment("cj-t", [], "", role)) is None


def test_judge_edge_entailment_invalid_returns_none():
    class _Bad:
        model = "fake"
        async def run(self, *a, **k): raise RuntimeError("invalid")
    assert asyncio.run(judge_edge_entailment(
        "cj-t", _layers()[0]["data"]["edges"], "", _Bad())) is None
```

- [ ] **Step 2~4: 실패→구현→통과**
- [ ] **Step 5: 전체 회귀** — `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/ -q`(648+신규 전부) 그리고 `cd /home/ryze_yn/attn-viewer && npm run check:openapi && npm test` — **fallback·`|| true` 금지, exit code가 게이트**. 전부 green을 보고에 기록(타 세션 유래 기존 실패는 파일 소관 확인 후 명시 격리). **disable_p23 오프 경로 확인**: `DISABLE_P23=true .venv/bin/python -m pytest tests/ -q`도 green(신규 테스트는 플래그 무관 유닛 — orchestrator 경유 테스트만 스킵 마킹 없이 통과해야 함)
- [ ] **Step 6: Commit** — `'feat(chain): eval 배선 — chain layer 소비·entailed_edge_ratio 실측·grounded_edge_ratio 계측 (3부 T8)'`

---

### Task 9: codex 리뷰 → 승인 후 배포 → 라이브 스모크

- [ ] **Step 1: codex 리뷰** — 신규 2파일 + 수정 10파일 diff. 관점: ①disable_p23 off 시 바이트 동일 경로 ②실존 검증 우회(임의 ID grounded) ③숫자 불변식(배경 판 절 수치 0·게이트 값 경로) ④AUDIT 격리 ⑤all-or-none ⑥스펙-코드 불일치 5건과 마킹된 판단 4건(REFLECT 체인 재생성 안 함 / grounded kind 무관 / G2 keyword 교량 / 시나리오 tier3 한정)의 판정. 블로커 반영→승인 왕복(docs/memory-chain-review-p3-*.md). **리뷰 반영 전 다음 단계 금지.**
- [ ] **Step 2 (승인 후에만): 배포** — 커밋 완료 확인 후 `pm2 restart attn-engine`. PM2 venv 의존성 변화 없음(신규 패키지 0) 확인.
- [ ] **Step 3: 라이브 스모크** — 실질문 1건(예: "SK하이닉스 지금 사도 될까?")을 disable_p23 **off(기본)** 로 실행 → thesis·chain layer 방출, 배경 판 절·시나리오 절·chain_verdicts 실물 확인 + 답변 내 수량 literal이 배경 판 유래인지 육안 점검. 이어 `DISABLE_P23=true`로 동일 질문(오프라인 orchestrator 직호출 스크립트 — PM2 환경 변경 금지) → thesis/chain layer 0건·기존 형태 답변 확인. 두 실행의 layer 목록 diff를 보고에 기록.
- [ ] **Step 4: 렛저 기록** — `.superpowers/sdd/progress.md` 프로젝트 항목 갱신. **workflow-review.html 현행화+스크린샷은 컨트롤러가 같은 세션 마지막에**(다른 세션 충돌 방지 관례).

---

## Self-Review 기록 (v1)

- 스펙 §3부 전 항목 매핑: 결정적 선택(T2 — rule_plan·0점 제외·동률 priority·top1~3·revision_id 기록) / ChainPacket VERIFY 이전·EnvelopeMeta·실존 검증·강등·thesis_relation(T4) / chain_verdicts VERIFY 산출·RISK·SYNTHESIZE·eval 소비(T5·T6·T8) / TypedFact metric·observation_id·G2 식별자 일치(T1·T5) / 시나리오 계약·1회 재합성·재실패 플래그(T6) / PlaybookGateCheck·Outcome all-or-none·문자열 하위 호환·LLM 대입 금지(T7) / 배경 판 절만·fresh+degraded·stale 금지·AUDIT 불포함·경계 문구·숫자 불변식(T3) / disable_p23 승계(T1 + 전 태스크 게이트)
- 성공 기준 계측 지점: 주입 수량 literal 0(T3 렌더 검증), grounded_edge_ratio(T8 metrics), entailed_edge_ratio(T8 judge), stale/degraded 사용률(thesis layer freshness 필드 — 리포트는 4부)
- off-path 바이트 동일: T3(_render_context 스냅샷)·T5(chain=None)·T6(scenario off 단일 콜)·T7(문자열 gate 무로그) 테스트로 각 지점 고정
- 마킹된 스펙 해석 4건 + 불일치 5건은 T9 codex가 판정 — 자의 확정 아님
- 커밋 9개 전부 명시적 add·작은따옴표, 라이브 영향 코드는 T9 승인 후 배포
