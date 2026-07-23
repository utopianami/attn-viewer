# ChainPacket 체인 합성 + SYNTHESIZE 주입 (스펙 3부) Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

v2 — codex r1 블로커 9건 전면 반영: B1(전역 SCHEMA_VERSION 무변경·CHAIN_SCHEMA_VERSION 분리·off-arm 바이트 동일성 golden 하네스) · B2(effective_disable_p23 = run override > settings, 1회 결정 관통·eval arm 파라미터) · B3(memory_sector_active — plan_query 성공 결정적 게이트, sector_rag_enabled 아님) · B4(canonical CHAIN_EDGES 레지스트리 — judge 방출·ChainEdge validator 공용 + build_rule_plan 결정적 event-type 추출) · B5(SYNTHESIZE에 event/mechanism/verdict/thesis_relation/contradicting 렌더·RISK에 verified claim 원문·run_chain 강등 사유 가시화) · B6(소스별 날짜 필드 fail-closed grounding·시나리오 validator에 chain_verdicts·tier≥3 명시) · B7(keyword 교량 기각 — canonical metric ID 관통, 정확 키/label/유일 최장 alias, 0·복수 매칭 → anchor 사용 거부) · B8(게이트 평가 PLAN 이후 이동·sector_metric_notes 순서·selector.series+혼합단위 거부·생산자 태스크 신설+마이그레이션 명시) · B9(grounded 분모=실제 edge 집합·초과/중복=오류·judge row 정합 대조·구조화 resolver·thesis 컨텍스트·entailed None fail-hard). 판정 3건(G2 keyword 기각 / 시나리오 강화 수용 / EnvelopeMeta 실제 round 기록)·권고 6건 전부 반영. 태스크 9→11개 재번호(T1 identity 하네스·T9 생산자 신설).

v1 — 2부 SHIPPED(main=57cf3f 계열) 기반. 답변 파이프라인에 3부 전체를 disable_p23 단일 토글 뒤에 넣는 초안.

**Goal:** 답변 파이프라인에 ① thesis "배경 판" 절 주입(결정적 선택·fresh/degraded만) ② ChainPacket 체인 합성(VERIFY 이전·코드 실존 검증) ③ VERIFY chain_verdicts 산출 + RISK 소비 ④ SYNTHESIZE 긍정/부정 시나리오 계약(코드 후검증·1회 재합성) ⑤ 플레이북 구조 게이트(all-or-none, 소비+생산) — 전부 `effective_disable_p23=True`면 통째로 꺼져 기존 경로와 **바이트 동일**(golden 하네스로 증명).

**Architecture:** 선택·검증·게이트는 전부 코드(LLM 신뢰 없음): thesis 선택은 `build_rule_plan` 스코어링(결정적), ChainPacket 인용 ID는 실존 검증·미실존 드롭·빈 supporting 강등, chain_verdicts는 VERIFY의 코드 재검증(존재+소스별 날짜 fail-closed), 시나리오 계약은 마크다운 구조 마커+grounded edge의 코드 후검증, 게이트 값은 store 관측 역참조(series·meta·unit 전체 코드 검증). LLM은 chain 제안(sonnet)과 시나리오 서술만 한다. 숫자는 전부 TypedFact 경로(주입 절엔 수치 없음).

**Tech Stack:** Python 3.12(engine/.venv)·pydantic v2·기존 Role/SectorStore/ThesisStore. 생산자는 Node(lib/playbooks.mjs — `npm test` 게이트). 신규 HTTP 라우트 없음(openapi 무변경).

**스펙:** docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md §3부 + §2부 가드레일 5 + "1부 완료 스코프"의 4부 승계 게이트 + 전역 제약

## v2 조정 — 컨트롤러 판정과 실코드가 충돌한 지점 (코드 우선)

1. **build_rule_plan event-type 추출은 opt-in 파라미터** (B4 문면과 다름): `plan.event_types`는 라이브 검색 스코어·필터에 직접 쓰인다(`sector/retrieve.py:126·179·189`). 무조건 채우면 토글 밖에서 검색 결과가 바뀌어 B1(off-arm 바이트 동일)과 충돌. 해소: `extract_event_types(question)`을 공개 결정적 함수로 추가하고 `build_rule_plan(question, include_event_types=False)` 기본 off — thesis 스코어링 경로만 `True`로 호출. 스코어 식의 event_types 항은 실제 추출로 라이브가 되고(B4 취지 충족), 검색 경로는 무변경.
2. **orchestrator `run_verify` 호출은 2곳** (orchestrator.py:496·568) — v1의 "3곳" 정정 (권고 4). `_g2_supported` 호출부도 **1곳**(verify.py:340) — v1의 "2곳" 정정.
3. **플레이북 실측**: 제외 파일(clusters/holdout/holdout-report) 제외 JSON **24개**, `holdout_passed` 4개, 구조 필드 가진 gate **0개** (리뷰의 26개와 집계 범위 차이 — 결론 동일: 소비자만 추가하면 영구 무동작 → T9 생산자 태스크 + 마이그레이션 명시).
4. **judge.py CHAIN_EDGES 결속은 수집기 경로**: `judge_items`는 답변 파이프라인(run_qa) 밖의 수집 잡 — off-arm 바이트 동일 계약(run_qa의 프롬프트·layer·final)에 저촉되지 않음. 카드 `edge` 정규화는 신규 판정분부터 적용.
5. **metric fact `period`는 범위형 가능**: `sector:dram_price_mom`의 period는 `"2026-06→2026-07"`. grounding의 날짜 대조는 `period.split("→")[-1]`을 `sector.period.parse_period`로 해석 — 파싱 불가·빈 값은 fail-closed(not grounded).
6. **바이트 동일성 계약의 정의**: off-arm에서 (a) 전 LLM 프롬프트(role별 instructions+prompt), (b) 방출 layer 스트림, (c) FinalAnswer dump가 3부 이전과 동일. 전부 수동 dict 조립이라 TypedFact/VerdictPacket/DraftAnswer의 기본값 신규 필드(모델 내부 직렬화에 새 키)는 이 계약 무저촉 — golden 하네스가 (a)(b)(c)를 대조.

## 스펙-코드 불일치 (실코드 대조 — v2 확정 해소)

1. **TypedFact schema_version**: TypedFact엔 자체 버전 없음, 패킷들이 전역 `SCHEMA_VERSION=1`(packets.py:18) 공유. **해소(B1):** 전역은 **무변경(=1)**. 신규 ChainPacket만 자체 `CHAIN_SCHEMA_VERSION=1` 스탬프. TypedFact 신규 필드 `metric`·`observation_id`는 기본값 추가(구 직렬화 하위호환 테스트). `period`는 이미 존재.
2. **edge 값 공간**: judge.py에 edge 열거 없음(자유 문자열, 기본 `"B->A"`; 축 집합 `_VALID_AXIS`만 존재, judge.py:25). **해소(B4):** 축 곱집합이 아니라 **명시 열거 `CHAIN_EDGES`** — judge.py `_INSTR`의 실제 인과 사슬(C0→C→B→[GPU/ASIC=A_prime]→A, 보조 A_prime/E/P/market→A)에서 도출한 8개 유향 edge. contracts/packets.py에 정의(단일 진실원), sector/judge.py가 import해 `_validate_row`에서 미등록 edge를 축 기반 결정적 폴백으로 정규화, ChainEdge validator는 멤버십 검사. 드리프트 가드: `nodes(CHAIN_EDGES) == judge._VALID_AXIS`.
3. **rule_plan의 event_types**: `build_rule_plan`(sector/queryplan.py:83)은 event_types 미기입. **해소(B4+v2 조정 1):** `extract_event_types` 키워드 규칙(실존 `EventType` Literal 위) 신설, thesis 스코어링 경로 opt-in — 스코어 항이 실추출로 라이브.
4. **"2부 주입 경로+3부 전체 무효"**: 2부는 답변 경로 무접촉 배송 — disable_p23 하나가 배경 판 주입과 3부 신규 경로 전체를 관장(`thesis_update_enabled`는 갱신 잡 전용 별개).
5. **EnvelopeMeta·VerdictPacket**: 스펙 명칭 그대로 실존(packets.py:49·377). ChainPacket.meta는 **필수 필드**로, 실제 생성 시점의 `EnvelopeMeta(round=round_, plan_ref=plan.plan_ref())` 기록 — ANSWERABILITY 보충검색이 첫 VERIFY 전에 round\_를 올릴 수 있으므로 round 0 고정 금지 (판정 3 수용).

## Global Constraints

- **effective_disable_p23 — run당 1회 결정, 전 경로 관통 (B2)**: `run_qa` 진입부에서 `effective_disable_p23 = bool((overrides or {}).get("disable_p23", settings.disable_p23))` — run override가 환경설정보다 우선(1부 계획 1385~1391행의 단일 명령 2-arm 계약: off-arm=`overrides["disable_p23"]=True`). import-time 싱글턴 직접 참조 금지 — 모든 P3 분기(thesis·chain·chain_verdicts·G2 metric identity·RISK 체인 입력·시나리오·구조 게이트)는 이 지역 변수만 본다. `settings.disable_p23: bool = False`(기본 ON)는 env `DISABLE_P23` 폴백.
- **memory_sector_active — 결정적 섹터 질문 게이트 (B3)**: `profile.sector_rag_enabled`는 비메모리 산업·전략 질문에서도 True(profiles.py:41~55) — 게이트 부적격. 대신 기존 sector_rag 블록의 `plan_query`(내부 `is_sector_question` 키워드 게이트, queryplan.py:46) 성공 여부로 `memory_sector_active = outcome is not None`을 만들고 thesis·chain·시나리오를 전부 그 뒤에 묶는다. 비메모리 full-profile 통합 테스트 포함(T10).
- **off-arm 바이트 동일 (B1)**: `effective_disable_p23=True`면 프롬프트·layer 스트림·FinalAnswer가 3부 이전과 동일 — T1의 golden 하네스(pre-P3 HEAD에서 캡처한 fixture)와의 등치 테스트가 전 태스크의 상시 회귀 게이트. metric-tagged G2·시나리오·게이트 전부 포함해 신규 동작은 토글 안쪽에만.
- **stale thesis 주입 금지** — fresh + degraded(라벨 병기)만. 선택된 `revision_id`를 thesis layer에 기록.
- **AUDIT evidence_texts에 thesis 주입 절 불포함** — `_audit_evidence()` 헬퍼 추출로 시그니처 수준 보장.
- **숫자 불변식**: thesis 유래 숫자는 TypedFact 경로만. 배경 판 절엔 수치 미포함 — 렌더 시점 `thesis_guard.quantity_literal` 코드 검증, 위반 statement 드롭. revision_id·타임스탬프도 절 본문 미포함.
- **임의 ID로 grounded 채우기 불가**: ChainPacket 인용 ID는 (섹터 카드 ∪ curated NewsItem ∪ typed_facts) 실존 집합 대조 — 미실존 드롭, supporting·metric 인용이 다 비면 `observed`→`inference` 강등. VERIFY가 독립 재검증 + **소스별 날짜 필드 fail-closed**(카드 `ts`·NewsItem `published_at`·metric fact `period` — 빈 값·파싱 불가·cutoff 초과 전부 not grounded, B6).
- **LLM 유사 지표 대입 금지**: 구조 게이트 값은 코드가 store에서 조회·집계.
- **all-or-none 게이트**: 구조 필드가 일부만 있으면 그 gate의 구조 판정 전체 무시 + 로그(문자열 gate로만 동작).
- **답변 경로 기존 동작 무영향**: 신규 경로는 전부 never-raise — 단 실패는 **삼키지 않고 degraded 표식으로 가시화**(B5: `run_chain`은 `(packet|None, 강등사유)` 튜플 반환, 호출부가 기록).
- **pm2 재시작만**(`pm2 restart attn-engine`), 커밋 작은따옴표·**명시적 git add**(공유 체크아웃 — `git -C /home/ryze_yn/attn-viewer add <파일들>` 나열). 커밋 전 브랜치 확인(main).
- 신규 HTTP 라우트 없음 — openapi 무변경. `npm test`·`npm run check:openapi`는 회귀 게이트(T9·T10), **fallback·`|| true` 금지, exit code가 게이트**.
- 프론트(public/index.html) 미변경 — 신규 layer name은 `CHAT_LAYER_TITLE` 미등록으로 필터. workflow-review 현행화는 T11 컨트롤러.
- cwd `/home/ryze_yn/attn-viewer/engine`, 테스트 `.venv/bin/python -m pytest tests/... -q`.

## File Structure

- Create: `engine/tests/p23_harness.py`+`engine/tests/fixtures/p23_off_golden.json`(T1), `engine/stages/thesis_context.py`(T3·T4), `engine/stages/chain.py`(T5), `engine/tests/fixtures/playbook_structured_gate.json`(T8)
- Modify: `engine/contracts/packets.py`·`engine/contracts/__init__.py`·`engine/app/settings.py`·`engine/sector/judge.py`·`engine/sector/queryplan.py`(T2), `engine/stages/synthesize.py`(T4·T7), `engine/orchestrator.py`(T4~T8), `engine/providers.py`(T5), `engine/stages/verify.py`·`engine/sector/evidence.py`·`engine/stages/risk.py`(T6), `engine/stages/playbook.py`(T8), `lib/playbooks.mjs`·`lib/playbooks.test.mjs`(T9), `engine/evals/chain_judge.py`·`engine/evals/metrics.py`·`engine/evals/run_eval.py`(T10)
- 테스트: `engine/tests/test_p23_off_identity.py`, `test_chain_contracts.py`, `test_thesis_select.py`, `test_thesis_inject.py`, `test_chain_stage.py`, `test_chain_verify_risk.py`, `test_scenario_contract.py`, `test_playbook_gates.py`, `test_chain_eval_wiring.py`, `test_p23_integration.py`

---

### Task 1: off-arm 바이트 동일성 하네스 + golden 캡처 (pre-P3 HEAD — 코드 변경 전 필수 선행)

**Files:**
- Create: `engine/tests/p23_harness.py`, `engine/tests/fixtures/p23_off_golden.json`, `engine/tests/test_p23_off_identity.py`

**Interfaces:**
- `p23_harness.run_pipeline(question: str, *, overrides_extra: dict | None = None, tmp_path) -> dict` — 결정적 오프라인 run_qa 실행기:
  1. 고정 시드 SectorStore(카드 3장·`memory_price_usd_per_gb` 관측 2건, ts 고정) → `evals.bundle.capture_bundle(store, out, as_of="2026-07-10", availability="unproven", ra_docs=[고정 1건], prices={"quotes": [...]}, macro={})`
  2. `providers.Role` monkeypatch — role name별 canned 구조화/텍스트 출력(triage=deep/stock_judgment/high, plan=tier3·cutoff는 bundle as_of로 덮임, da/extract/answerability/verifier/risk/synthesizer/audit 전부 고정). 모든 콜의 `(role_name, instructions, prompt)`를 순서대로 기록
  3. `casemem.async_query.query_case_memory_async` monkeypatch — 고정 빈 매치(라이브 store 비결정성 차단)
  4. `run_qa(question, overrides={"eval_bundle": str(bundle), **(overrides_extra or {})}, user_id="")` 수집 → `{"prompts": [...], "layers": [...], "final": {...}}` 반환. 정규화: `elapsed_s`·`cost`·`planner_ms` 키 제거(값 비결정)
- `__main__` 캡처 모드: `.venv/bin/python -m tests.p23_harness --capture` → `tests/fixtures/p23_off_golden.json` 기록 (질문: `"SK하이닉스 HBM 현물가 흐름 어때?"`)
- `test_p23_off_identity.py::test_off_arm_byte_identical_to_pre_p3_golden` — `run_pipeline(q, overrides_extra={"disable_p23": True})` 결과 == golden fixture (json 등치). **pre-P3 코드는 미지 override 키를 무시하므로 캡처 시점(코드 변경 전)에도 green** — 이후 전 태스크에서 상시 회귀로 유지

- [ ] **Step 1: 하네스+테스트 작성 → 캡처 실행** — 캡처는 반드시 **P3 프로덕션 코드 변경 전** HEAD에서. `--capture` 후 test green 확인
- [ ] **Step 2: 재실행 결정성 확인** — 캡처 2회 diff 0 (비결정 키 정규화 검증)
- [ ] **Step 3: Commit** — `'test(chain): 3부 off-arm 바이트 동일성 하네스 + pre-P3 golden 캡처 (3부 T1, r1-B1)'`

---

### Task 2: 계약 — ChainPacket·CHAIN_EDGES·PlaybookGate + TypedFact 확장 + disable_p23 + judge 결속 + event-type 추출

**Files:**
- Modify: `engine/contracts/packets.py`, `engine/contracts/__init__.py`, `engine/app/settings.py`, `engine/sector/judge.py`, `engine/sector/queryplan.py`
- Test: `engine/tests/test_chain_contracts.py`

**Interfaces (Produces — 신규 모델은 전부 `_Strict` 상속, packets.py 내):**
- `SCHEMA_VERSION = 1` **무변경** (B1). `CHAIN_SCHEMA_VERSION = 1` 신설 — ChainPacket 전용
- `CHAIN_EDGES = ("C0->C", "C->B", "B->A_prime", "B->A", "A_prime->A", "E->A", "P->A", "market->A")` — judge.py `_INSTR` 인과 사슬의 명시 열거(곱집합 금지, B4). 노드 집합 == `judge._VALID_AXIS` 드리프트 가드 테스트. contracts→sector 방향 import 없음(sector가 contracts를 import — evidence.py 선례)
- `sector/judge.py`: `from contracts.packets import CHAIN_EDGES` + `_DEFAULT_EDGE = {"A": "B->A", "A_prime": "A_prime->A", "B": "B->A", "C": "C->B", "C0": "C0->C", "E": "E->A", "P": "P->A", "market": "market->A"}`; `_validate_row`에 `if row.edge not in CHAIN_EDGES: row.edge = _DEFAULT_EDGE[row.axis]` (axis는 직전에 검증됨 — 방출 edge가 레지스트리 밖일 수 없음, B4 "judge와 ChainEdge가 실제로 함께 사용")
- `sector/queryplan.py`: `_EVENT_TYPE_TERMS: dict[str, tuple[str, ...]]` — 실존 `EventType` Literal(sector/contracts.py:9) 9종 전부에 한국어 키워드: `demand_signal=("수요","발주","주문")`, `supply_signal=("공급","증설","감산","수율")`, `price_signal=("가격","현물가","고정가","인상","인하")`, `earnings=("실적","영업이익","컨콜")`, `filing=("공시",)`, `policy=("관세","수출통제","제재","보조금","규제")`, `speaker=("발언","ceo")`, `product_policy=("신제품","출시","로드맵")`, `market_reaction=("급등","급락")`; `extract_event_types(question: str) -> list[str]`(매칭 event_type, 정의 순서, [:4]); `build_rule_plan(question, include_event_types: bool = False)` — True일 때만 `event_types=extract_event_types(question)` (v2 조정 1 — 검색 경로 무변경)
- `TypedFact` += `metric: str = ""`(METRIC_REGISTRY 키), `observation_id: str = ""` (기존 생성부 무변경 — 기본값)
- `ThesisRelation(thesis_revision_id: str, relation: Literal["supports", "contradicts"])`
- `ChainEdge(edge_id: str, edge: str, kind: Literal["observed", "inference"], supporting_card_ids: list[str] = Field(default_factory=list), metric_fact_ids: list[str] = Field(default_factory=list), contradicting_card_ids: list[str] = Field(default_factory=list))` — `edge`는 `edge in CHAIN_EDGES` field_validator (멤버십 — 패턴 아님)
- `ChainPacket(schema_version: int = CHAIN_SCHEMA_VERSION, meta: EnvelopeMeta, event: str, mechanism: str, edges: list[ChainEdge] = Field(default_factory=list), thesis_relation: list[ThesisRelation] = Field(default_factory=list), verdict: str = "")` — **meta 필수(기본값 없음)**: 생성 시점 round·plan_ref 강제 (판정 3)
- `ChainEdgeVerdict(edge_id: str, grounded: bool, note: str = "")`
- `VerdictPacket` += `chain_verdicts: list[ChainEdgeVerdict] = Field(default_factory=list)`
- `PlaybookGateSelector(series: str | None = None, meta_filter: dict = Field(default_factory=dict))`
- `PlaybookGateCheck(order: int, check: str, metric_id: str, selector: PlaybookGateSelector = Field(default_factory=PlaybookGateSelector), aggregation: Literal["last", "mean_window", "yoy"], window_days: int = 0, comparator: Literal[">=", "<=", ">", "<", "=="], threshold: float, unit: str, max_age_days: int)` — `threshold` 유한성 validator(`math.isfinite`, 권고 6)
- `PlaybookGateOutcome(order: int, metric_id: str, value: float | None = None, verdict: Literal["pass", "fail", "unavailable"], evidence_observation_id: str = "", unavailable_reason: Literal["", "no_metric", "unit_mismatch", "stale_data"] = "")` — model_validator: `verdict=="unavailable" ⇔ unavailable_reason != "" ∧ value is None`, `verdict∈{pass,fail} ⇒ value is not None ∧ unavailable_reason == ""` (권고 6)
- `DraftAnswer` += `scenario_flags: list[str] = Field(default_factory=list)`
- `LAYER_NAMES` += `"thesis"`, `"chain"`
- `engine/app/settings.py` += `disable_p23: bool = False` (주석: 3부 답변 경로 주입 전체 off — 4부 2-arm 승계. run override가 우선, `thesis_update_enabled`와 별개)
- `contracts/__init__.py` export: CHAIN_EDGES, CHAIN_SCHEMA_VERSION, ChainEdge, ChainEdgeVerdict, ChainPacket, PlaybookGateCheck, PlaybookGateOutcome, PlaybookGateSelector, ThesisRelation (+`__all__`)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_contracts.py
import pytest
from pydantic import ValidationError

from app.settings import Settings
from contracts import (CHAIN_EDGES, CHAIN_SCHEMA_VERSION, LAYER_NAMES, SCHEMA_VERSION,
                       ChainEdge, ChainEdgeVerdict, ChainPacket, DraftAnswer,
                       EnvelopeMeta, PlanRef, PlaybookGateCheck, PlaybookGateOutcome,
                       TypedFact, VerdictPacket)


def test_global_schema_version_untouched_and_backcompat():
    assert SCHEMA_VERSION == 1                     # B1 — 전역 무변경
    assert CHAIN_SCHEMA_VERSION == 1
    old = VerdictPacket.model_validate({"schema_version": 1})   # 구 직렬화본
    assert old.chain_verdicts == []                             # 신규 필드 기본값


def test_typed_fact_metric_identity_fields():
    f = TypedFact(id="thesis:hbm-tightness:memory_price_usd_per_gb", value=0.1,
                  unit="USD/GB", metric="memory_price_usd_per_gb",
                  observation_id="a" * 16, period="2026-07")
    assert f.metric == "memory_price_usd_per_gb" and f.observation_id == "a" * 16
    assert TypedFact(id="x", value=1.0, unit="KRW").metric == ""  # 기존 생성부 무변경


def test_chain_edges_registry_nodes_match_judge_axes():
    from sector.judge import _VALID_AXIS
    nodes = {n for e in CHAIN_EDGES for n in e.split("->")}
    assert nodes == _VALID_AXIS                    # 드리프트 가드 (단일 진실원)
    assert "B->A" in CHAIN_EDGES and "A_prime->A" in CHAIN_EDGES and "C0->C" in CHAIN_EDGES
    assert "A->A" not in CHAIN_EDGES and "market->C" not in CHAIN_EDGES  # 곱집합 금지 (r1-B4)


def test_judge_emission_normalized_into_registry():
    from sector.judge import _DEFAULT_EDGE, _JudgeRow, _validate_row
    assert set(_DEFAULT_EDGE.values()) <= set(CHAIN_EDGES)
    row = _validate_row(_JudgeRow(idx=0, relevant=True, axis="A_prime",
                                  edge="A_prime → A"))          # 자유 문자열
    assert row.edge == "A_prime->A"                # 축 기반 결정적 폴백
    row2 = _validate_row(_JudgeRow(idx=0, relevant=True, axis="B", edge="B->A"))
    assert row2.edge == "B->A"                     # 실존 edge 보존


def test_extract_event_types_deterministic_and_opt_in():
    from sector.judge import _VALID_EVENT_TYPE
    from sector.queryplan import build_rule_plan, extract_event_types
    got = extract_event_types("SK하이닉스 HBM 증설로 공급 과잉 안 와?")
    assert "supply_signal" in got and set(got) <= _VALID_EVENT_TYPE
    assert extract_event_types("오늘 날씨 어때?") == []
    # 기본 off — 검색 경로(retrieve.py:126 event_type 스코어) 무변경 (v2 조정 1)
    assert build_rule_plan("HBM 증설 어때?").event_types == []
    rp = build_rule_plan("HBM 증설 어때?", include_event_types=True)
    assert "supply_signal" in rp.event_types       # thesis 스코어링 전용 opt-in


def test_chain_edge_value_space_and_kind():
    ChainEdge(edge_id="e0", edge="B->A", kind="observed", supporting_card_ids=["c1"])
    ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference")
    with pytest.raises(ValidationError):
        ChainEdge(edge_id="e2", edge="A->A", kind="observed")   # 미등록 edge
    with pytest.raises(ValidationError):
        ChainEdge(edge_id="e3", edge="B->A", kind="guessed")    # kind Literal


def test_chain_packet_meta_records_real_round_and_plan_ref():
    meta = EnvelopeMeta(round=1, plan_ref=PlanRef(tier=3, knowledge_cutoff="2026-07-21"))
    cp = ChainPacket(meta=meta, event="HBM 증설 발표", mechanism="공급 확대 기대",
                     edges=[ChainEdge(edge_id="e0", edge="A_prime->A", kind="inference")],
                     thesis_relation=[{"thesis_revision_id":
                                       "hbm-tightness@2026-07-21T00:00:00",
                                       "relation": "supports"}])
    assert cp.schema_version == CHAIN_SCHEMA_VERSION
    assert cp.meta.round == 1 and cp.meta.plan_ref.tier == 3   # 실제 라운드 (판정 3)
    with pytest.raises(ValidationError):
        ChainPacket(event="x", mechanism="y")       # meta 필수 — 기본 빈 meta 금지
    with pytest.raises(ValidationError):
        ChainPacket(meta=meta, event="x", mechanism="y",
                    thesis_relation=[{"thesis_revision_id": "t@1", "relation": "maybe"}])
    v = VerdictPacket(chain_verdicts=[ChainEdgeVerdict(edge_id="e0", grounded=False,
                                                       note="근거 없음")])
    assert v.chain_verdicts[0].grounded is False


def test_playbook_gate_contracts_and_validators():
    chk = PlaybookGateCheck(order=1, check="D램 가격 수준",
                            metric_id="memory_price_usd_per_gb",
                            selector={"meta_filter": {"category": "DRAM"}},
                            aggregation="last", comparator=">=", threshold=0.05,
                            unit="USD/GB", max_age_days=45)
    assert chk.window_days == 0 and chk.selector.series is None
    with pytest.raises(ValidationError):
        PlaybookGateCheck(order=1, check="x", metric_id="m", aggregation="median",
                          comparator=">=", threshold=1.0, unit="u", max_age_days=1)
    with pytest.raises(ValidationError):            # threshold 유한성 (권고 6)
        PlaybookGateCheck(order=1, check="x", metric_id="m", aggregation="last",
                          comparator=">=", threshold=float("nan"), unit="u",
                          max_age_days=1)
    out = PlaybookGateOutcome(order=1, metric_id="memory_price_usd_per_gb",
                              verdict="unavailable", unavailable_reason="no_metric")
    assert out.value is None
    with pytest.raises(ValidationError):            # verdict/reason 정합 (권고 6)
        PlaybookGateOutcome(order=1, metric_id="m", verdict="unavailable")
    with pytest.raises(ValidationError):
        PlaybookGateOutcome(order=1, metric_id="m", verdict="pass", value=None)


def test_layer_names_settings_default_and_scenario_flags():
    assert "thesis" in LAYER_NAMES and "chain" in LAYER_NAMES
    # env 오염 무관 — 인스턴스가 아니라 모델 필드 기본값 검사 (권고 3:
    # `DISABLE_P23=true pytest`에서도 통과해야 함)
    assert Settings.model_fields["disable_p23"].default is False
    assert Settings(disable_p23=True).disable_p23 is True
    assert DraftAnswer(answer_markdown="x").scenario_flags == []
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_chain_contracts.py -v` → ImportError (CHAIN_EDGES 등 미존재)
- [ ] **Step 3: 구현** — 위 Interfaces 전부. judge/queryplan 변경 후 기존 `test_sector_judge.py`·섹터 검색 테스트 무변경 통과 확인(edge 정규화는 미등록 값만 건드림·event_types는 opt-in)
- [ ] **Step 4: 통과 + 회귀** — 신규 green + `.venv/bin/python -m pytest tests/ -q` 전체 green + **T1 identity 테스트 green**
- [ ] **Step 5: Commit** — `'feat(chain): 3부 typed 계약 — CHAIN_EDGES 레지스트리·ChainPacket(CHAIN_SCHEMA_VERSION)·PlaybookGate validator·event-type 추출·disable_p23 (3부 T2)'`

---

### Task 3: thesis 선택기 — 결정적 rule_plan 스코어링

**Files:**
- Create: `engine/stages/thesis_context.py`
- Test: `engine/tests/test_thesis_select.py`

**Interfaces:**
- `@dataclass ThesisPick(rev: ThesisRevision, freshness: str, score: int)`
- `score_thesis(rp: SectorQueryPlan, rev: ThesisRevision) -> int` — `len(set(rp.entities) & set(rev.selectors.entities)) * 2 + len(set(rp.metrics) & set(rev.selectors.metrics)) * 1 + len(set(rp.event_types) & set(rev.selectors.event_types)) * 1` (스펙 식 — event_types 항은 T2 `extract_event_types`로 **라이브**, B4)
- `select_from_revisions(rp, revs: list[ThesisRevision], store, now: datetime) -> list[ThesisPick]` — 0점 제외 → `sector.thesis_store.freshness(rev, store, now)` → stale 제외 → 정렬 `(-score, priority, rev.id)` → 상위 1~3개
- `select_theses(question: str, tstore: ThesisStore, store, now) -> list[ThesisPick]` — `build_rule_plan(question, include_event_types=True)` + `tstore.latest_all()` 위임 (라이브 경로). eval bundle 경로는 orchestrator가 `EvalBundle.theses()` → `ThesisRevision.model_validate` 후 select_from_revisions 직접 호출 (T4)

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


def test_score_weights_deterministic_with_real_event_extraction():
    # 인위적 SectorQueryPlan이 아니라 실제 추출 경로 (r1-B4): make_rev의
    # selectors.event_types == ["supply_signal"] — "증설"이 supply_signal로 추출됨
    rp = build_rule_plan("SK하이닉스 HBM 증설에도 현물가 오를까?",
                         include_event_types=True)
    assert "SK_HYNIX" in rp.entities and "memory_price_usd_per_gb" in rp.metrics
    assert "supply_signal" in rp.event_types
    assert score_thesis(rp, make_rev()) == 4          # 1×2 + 1×1 + 1×1 — 3항 전부 라이브
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
    assert picks[0].rev.revision_id == "hbm-tightness@2026-07-21T00:00:00"


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
    picks = select_theses("SK하이닉스 HBM 현물가 흐름 어때?", ts, store, NOW)
    assert [p.rev.id for p in picks] == ["hbm-tightness"]
    assert select_theses("오늘 날씨 어때?", ts, store, NOW) == []   # 0점 전원 제외
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (freshness는 `sector.thesis_store.freshness` 재사용 — 재구현 금지. T1 identity green 유지)
- [ ] **Step 5: Commit** — `'feat(chain): thesis 결정적 선택기 — rule_plan 스코어링(3항 라이브)·0점/stale 제외·top3 (3부 T3)'`

---

### Task 4: 배경 판 주입 — 렌더·TypedFact 승격·effective_disable_p23/memory_sector_active 배선·AUDIT 격리

**Files:**
- Modify: `engine/stages/thesis_context.py`, `engine/stages/synthesize.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_thesis_inject.py`

**Interfaces:**
- `render_thesis_section(picks: list[ThesisPick]) -> str` — 빈 picks → `""`. 형식:
  - 헤더 `[배경 판 — 섹터 현재 가설 (자동 합성·경향 참고)]` + 경계 문구: "아래는 축적 근거로 자동 유지되는 '배경 가설'이다. 사실 근거로 단정 인용하지 말고 해석의 배경으로만 써라. 이 절의 가설 관련 수치는 [결정적 수치] 절의 값만 인용하라."
  - 가설당: `- ({assessment}{", 입력 일부 노후" if degraded}) {claim}: {statement texts "; " 연결}` — revision_id·타임스탬프·key_metrics 값은 절에 미포함
  - 렌더 직전 코드 검증: `thesis_guard.quantity_literal(text)`에 잡히는 statement/claim 라인 드롭
- `thesis_typed_facts(picks) -> list[TypedFact]` — key_metrics → `TypedFact(id=f"thesis:{rev.id}:{km.metric}", value=km.value, unit=km.unit, period=km.ts, label=f"{rev.id} 관련 지표 {km.metric}", source=km.source, metric=km.metric, observation_id=km.observation_id)`. id 중복은 상위 pick first-wins
- `stages/synthesize.py`: `_render_context(..., thesis_section: str = "")`·`run_synthesize(..., thesis_section: str = "")` — 비면 기존 출력과 바이트 동일. 위치: `[메모리 섹터 근거]` 뒤·`[과거사례 대조]` 앞
- `orchestrator.py`:
  - **run_qa 진입부** (meter 설정 직후): `from app.settings import settings` 후 `effective_disable_p23 = bool((overrides or {}).get("disable_p23", settings.disable_p23))` — **B2: run당 1회 결정.** 이후 어떤 P3 분기도 `settings.disable_p23` 직접 참조 금지 (overrides는 line 191에서 `role_overrides`로 재대입되므로 반드시 재대입 전 원본에서 읽는다)
  - sector_rag 블록: `memory_sector_active = False` 초기화, `outcome = await plan_query(...)` 직후 `memory_sector_active = outcome is not None` — **B3: 결정적 섹터 질문 게이트** (`plan_query` 내부 `is_sector_question`이 게이트, LLM 실패 시 규칙 폴백도 outcome 반환 — 게이트 판정은 결정적)
  - `_audit_evidence(ra, sector_cycle_text, sector_metric_notes, sector_cards, case_matches) -> tuple[list[str], dict[str, str]]` — 기존 ⑧ AUDITOR evidence 조립 블록(orchestrator.py:604~630) 그대로 추출(동작 불변). thesis 파라미터 없음
  - casemem 블록 뒤(run_assemble 전):

```python
    thesis_picks, thesis_section = [], ""
    if not effective_disable_p23 and memory_sector_active:
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
                _th_rule(plan.standalone_question or question,
                         include_event_types=True), _th_revs, _th_store, _th_now)
            if thesis_picks:
                thesis_section = render_thesis_section(thesis_picks)
                sector_facts = list(sector_facts) + thesis_typed_facts(thesis_picks)
                yield _layer("thesis", {
                    "selected": [{"revision_id": p.rev.revision_id,
                                  "claim": p.rev.claim,          # eval judge 컨텍스트용 (r1-B9)
                                  "score": p.score, "freshness": p.freshness}
                                 for p in thesis_picks],
                    "typed_facts": [{"id": f.id, "label": f.label, "value": f.value,
                                     "unit": f.unit, "period": f.period}
                                    for f in thesis_typed_facts(thesis_picks)]})
        except Exception:  # noqa: BLE001 — never-raise, 무주입 폴백 (표식은 남김)
            degraded.append("thesis")
            thesis_picks, thesis_section = [], ""
```

  - run_synthesize 호출에 `thesis_section=thesis_section` 전달, ⑧ evidence 조립을 `_audit_evidence(...)` 호출로 치환
- eval bundle 모드: `EvalBundle.theses()`(bundle.py:167)가 as_of 경계 선택본 — 라이브 store 오염 없음

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


def test_effective_toggle_resolved_from_run_overrides():
    # B2 — orchestrator 소스에 결정 시점이 하나뿐인지 (run override > settings)
    import inspect as _i
    import orchestrator
    src = _i.getsource(orchestrator.run_qa)
    assert 'get("disable_p23", settings.disable_p23)' in src
    assert src.count("effective_disable_p23 =") == 1    # run당 1회 결정
```

- [ ] **Step 2~3: 실패 확인 → 구현** (⑧ 블록 추출은 diff 최소 — 추출 전후 기존 audit 테스트 green)
- [ ] **Step 4: 통과 + 회귀** — 전체 pytest + **T1 identity green** (off-arm에선 thesis 블록 자체가 스킵 — 프롬프트·layer 불변)
- [ ] **Step 5: Commit** — `'feat(chain): thesis 배경 판 주입 — effective_disable_p23 1회 결정·memory_sector_active 게이트·수량 0 검증·AUDIT 격리 (3부 T4)'`

---

### Task 5: ChainPacket 생성 (VERIFY 이전) — 코드 실존 검증·강등 사유 가시화

**Files:**
- Create: `engine/stages/chain.py`
- Modify: `engine/providers.py` (`"chain_synth": [("anthropic", settings.model_claude_sonnet, "low")]` — `"thesis_updater"`(providers.py:42) 아래), `engine/orchestrator.py`
- Test: `engine/tests/test_chain_stage.py`

**Interfaces:**
- structured output `_ChainOut{event, mechanism, verdict, edges: [{edge, kind, supporting_card_ids, metric_fact_ids, contradicting_card_ids}], thesis_relation: [{thesis_revision_id, relation}]}` (LLM 제안일 뿐 — 검증은 코드)
- `async run_chain(plan: PlanPacket, table: ClaimTable, sector_cards: list, ra: RaPacket, thesis_picks: list, *, round_: int = 0, role=None, overrides=None) -> tuple[ChainPacket | None, str]` — **반환 2번째 원소 = 강등 사유** (`""`=정상, `"llm_error"`, `"invalid_output"`, `"all_edges_dropped"` — B5: 예외 삼킴 뒤 무표식 금지):
  1. 입력 조립: claim 목록(id·text·source), 섹터 카드(id·title·interpreted_signal), typed_facts(id·label), thesis(revision_id·claim), **CHAIN_EDGES 열거**·kind 정의를 프롬프트에
  2. LLM 1콜 (`role or Role("chain_synth", overrides)`, effort low)
  3. 코드 검증 (LLM 불신): `edge not in CHAIN_EDGES` → 드롭 / 인용 ID 실존 대조(supporting·contradicting ⊆ {sector_cards id} ∪ {`ra.curated_items()` 전 유닛 NewsItem id}, metric_fact_ids ⊆ {table.typed_facts id}) — 미실존 드롭 / supporting과 metric이 모두 비면 `observed`→`inference` 강등 / thesis_relation revision_id ∉ {p.rev.revision_id} → 드롭 / `edge_id` 코드 순번 부여(`e0`, `e1`, …)
  4. `meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref())` — **실제 생성 라운드** (판정 3)
  5. 내부 예외 → `(None, "llm_error")` 등 — never-raise + 사유
- orchestrator: ANSWERABILITY 뒤·첫 `run_verify`(orchestrator.py:496) 직전 —

```python
    chain = None
    if not effective_disable_p23 and memory_sector_active and table.claims:
        from stages.chain import run_chain
        chain, chain_note = await run_chain(plan, table, sector_cards, ra,
                                            thesis_picks, round_=round_,
                                            overrides=overrides)
        if chain_note:
            degraded.append(f"chain:{chain_note}")   # B5 — 강등 표식 가시화
        if chain is not None:
            yield _layer("chain", chain.model_dump(mode="json"))
```

  (REFLECT 라운드 재생성 없음 — 판정 3 수용: 체인은 사건-기제 서술, 재조사는 근거 보강. 라운드 0이 아니라 **생성 시점 round\_**를 meta에 기록)

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
        {"edge": "A->A", "kind": "observed", "supporting_card_ids": ["card-1"],
         "metric_fact_ids": [], "contradicting_card_ids": []}],
    "thesis_relation": [
        {"thesis_revision_id": "hbm-tightness@2026-07-21T00:00:00",
         "relation": "supports"},
        {"thesis_revision_id": "ghost@2026-01-01T00:00:00", "relation": "contradicts"}]}


def test_code_validation_drops_demotes_assigns_ids_and_meta():
    picks = [ThesisPick(rev=make_rev(), freshness="fresh", score=3)]
    cp, note = asyncio.run(run_chain(_plan(), _table(), [_card("card-1")], RaPacket(),
                                     picks, round_=1, role=_Role(_PROPOSAL)))
    assert note == "" and cp is not None
    assert cp.meta.round == 1 and cp.meta.plan_ref.tier == 3   # 실제 생성 라운드 (판정 3)
    assert [e.edge_id for e in cp.edges] == ["e0", "e1"]
    e0, e1 = cp.edges
    assert e0.supporting_card_ids == ["card-1"]          # ghost 드롭
    assert e0.metric_fact_ids == ["sector:dram_price"]   # no-such-fact 드롭
    assert e0.contradicting_card_ids == []               # ghost2 드롭
    assert e0.kind == "observed"
    assert e1.kind == "inference"                        # 빈 supporting → 강등
    assert len(cp.edges) == 2                            # A->A 레지스트리 밖 → 드롭
    assert [t.thesis_revision_id for t in cp.thesis_relation] == \
        ["hbm-tightness@2026-07-21T00:00:00"]            # 미주입 revision 드롭


def test_never_raise_returns_reason_marker():
    class _Boom:
        model = "boom"
        async def run(self, *a, **k): raise RuntimeError("down")
    cp, note = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [],
                                     role=_Boom()))
    assert cp is None and note == "llm_error"            # B5 — 무음 None 금지


def test_all_edges_dropped_is_visible():
    bad = dict(_PROPOSAL, edges=[{"edge": "A->A", "kind": "observed",
                                  "supporting_card_ids": [], "metric_fact_ids": [],
                                  "contradicting_card_ids": []}])
    cp, note = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [],
                                     role=_Role(bad)))
    assert cp is None and note == "all_edges_dropped"
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (T1 identity green — off-arm은 chain 블록 스킵)
- [ ] **Step 5: Commit** — `'feat(chain): ChainPacket 합성 스테이지 — CHAIN_EDGES 검증·미실존 드롭·observed 강등·meta 실라운드·강등 사유 가시화 (3부 T5)'`

---

### Task 6: VERIFY chain_verdicts(소스별 날짜 fail-closed) + G2 canonical metric ID + RISK 실소비

**Files:**
- Modify: `engine/stages/verify.py`, `engine/sector/evidence.py`, `engine/stages/risk.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_chain_verify_risk.py`

**Interfaces:**
- `run_verify(..., overrides=None, metric_identity: bool = False, chain: ChainPacket | None = None, sector_cards: list | None = None)` — 기존 keyword 뒤 추가. `chain` 있으면 `chain_verdicts` 채움 (코드 판정 — 생성부 불신 독립 재검증):
  - edge별 `grounded=True` 조건 전부 충족: ① 인용 ID(supporting·contradicting ⊆ sector_cards∪ra NewsItem ids, metric_fact_ids ⊆ table.typed_facts ids) 전원 실존 ② supporting 또는 metric **비어있지 않음** ③ 인용 전원 **as-of clean — 소스별 날짜 필드 fail-closed** (B6): 카드=`c.ts`(`^\d{4}-\d{2}-\d{2}` 불일치·빈 값 → fail, `ts[:10] <= plan.knowledge_cutoff`), NewsItem=`n.published_at`(동일 규칙 — `ts` 아님), metric fact=`f.period`(`period.split("→")[-1]`을 `sector.period.parse_period`로 해석 — None → fail, 시작일 ≤ cutoff). 미충족 시 grounded=False + note 사유
  - grounded 정의: kind와 독립(판정 3 수용) — inference도 실존·as-of-clean 인용이 있으면 grounded 가능
- **G2 canonical metric ID 관통 (B7 — keyword 교량 기각)**:
  - `_numeric_anchors(...) -> list[tuple[float, str, str]]` — `(value, unit, metric_id)`. typed_facts는 `f.metric` 그대로(섹터·thesis 유래는 생성 시점에 ID 보유 — NL 매핑 불필요), calc/price/macro 유래는 `""`
  - `_claim_metric_id(norm_metric: str) -> str` — claim 자유 문장 → 레지스트리 ID: ① 정확 키 일치 ② 정확 label 일치(소문자) ③ **유일 최장 alias**(`METRIC_REGISTRY[*]["keywords"]` 중 claim 문자열에 포함되는 최장 alias가 정확히 한 metric 소유일 때만). 0개 또는 복수 매칭 → `""` (fail-closed)
  - `_g2_supported(value, unit, anchors, claim_metric_id: str = "") -> bool` — anchor `metric_id==""` → 기존 판정 그대로(미태그: 기존 G2 회귀 0). anchor `metric_id!=""` → `claim_metric_id == anchor_metric_id`일 때만 대조 자격 — claim ID가 비면 태그 anchor 전부 사용 불가 (교차 지표 동수치 앵커링 차단: `memory_price_usd_per_gb`의 keywords `"가격"`이 `"토큰 가격"` claim과 오매칭되던 r1-B7 사례가 최장 alias 규칙으로 `token_price`에 귀속)
  - 호출부(verify.py:340, 1곳): `metric_identity`가 True일 때만 `claim_metric_id=_claim_metric_id(c.norm.metric)` 전달, False면 `""` 고정 — **G2 변경도 토글 안쪽** (B1)
- `sector/evidence.py sector_typed_facts`: 생성 TypedFact 2건에 `metric="memory_price_usd_per_gb"`, `observation_id=observation_id(metric, last.ts, last.meta)`(`sector.thesis_contracts.observation_id`) 기입 — 데이터 태그일 뿐 off-arm 판정 무영향(위 `metric_identity` 게이트)
- `run_risk(..., force: bool = False, chain: ChainPacket | None = None, verdict: VerdictPacket | None = None)` — chain 있으면 프롬프트에 **② 절 추가** (B5: 수 요약 아님):
  - `[검증 통과 주장]` — verdict에서 `final=="verified"`인 claim의 **원문 텍스트** 목록(각 160자·최대 20줄)
  - `[인과 체인 판정]` — edge별 `- {edge_id} {edge} ({kind}, {'근거확인' if grounded else '미확인'}): {event} — {mechanism}` (verdict.chain_verdicts 대조)
  - chain None → 기존 프롬프트 그대로 (off-path)
- orchestrator: `run_verify` **2곳**(orchestrator.py:496·568)에 `metric_identity=not effective_disable_p23, chain=chain, sector_cards=sector_cards` 추가, `run_risk`에 `chain=chain, verdict=verdict` 추가. verify layer data에 `"chain_verdicts": [...]` 포함(chain 없으면 키 생략 — off-path 동일)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_verify_risk.py
import asyncio

from contracts import (AtomicClaim, ChainEdge, ChainPacket, ClaimTable, EnvelopeMeta,
                       NewsItem, PlanPacket, RaPacket, TypedFact)
from stages.risk import run_risk
from stages.verify import _claim_metric_id, _g2_supported, run_verify
from tests.test_chain_stage import _card, _plan

_META = EnvelopeMeta()


def _table():
    return ClaimTable(
        claims=[AtomicClaim(id="cl-1", text="HBM 수요가 견조하다", type="context",
                            source="da_gpt")],
        typed_facts=[
            TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB",
                      period="2026-07", metric="memory_price_usd_per_gb"),
            TypedFact(id="sector:dram_price_mom", value=11.1, unit="percent",
                      period="2026-06→2026-07", metric="memory_price_usd_per_gb"),
            TypedFact(id="bad-period", value=1.0, unit="USD/GB", period="")])


def _chain():
    return ChainPacket(meta=_META, event="e", mechanism="m", edges=[
        ChainEdge(edge_id="e0", edge="B->A", kind="observed",
                  supporting_card_ids=["card-1"]),
        ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference"),
        ChainEdge(edge_id="e2", edge="C->B", kind="observed",
                  supporting_card_ids=["card-future"]),
        ChainEdge(edge_id="e3", edge="B->A", kind="observed",
                  metric_fact_ids=["no-such-fact"]),
        ChainEdge(edge_id="e4", edge="B->A", kind="observed",
                  supporting_card_ids=["news-1"]),
        ChainEdge(edge_id="e5", edge="B->A", kind="inference",
                  metric_fact_ids=["sector:dram_price_mom"]),
        ChainEdge(edge_id="e6", edge="B->A", kind="observed",
                  metric_fact_ids=["bad-period"])])


def _ra_with_news(published_at):
    return RaPacket(x_search={"q0": [NewsItem(id="news-1", title="t",
                                              published_at=published_at)]})


def test_chain_verdicts_source_typed_dates_fail_closed():
    cards = [_card("card-1")]
    future = _card("card-future"); future.ts = "2026-07-25T00:00:00"  # cutoff 이후
    verdict = asyncio.run(run_verify(
        _plan(), _table(), _ra_with_news(""), [],
        chain=_chain(), sector_cards=cards + [future]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e0"].grounded is True
    assert by_id["e1"].grounded is False        # 인용 전무
    assert by_id["e2"].grounded is False and "as_of" in by_id["e2"].note  # 미래 카드
    assert by_id["e3"].grounded is False        # 미실존 fact
    assert by_id["e4"].grounded is False        # NewsItem published_at 빈 값 → fail-closed
    assert by_id["e5"].grounded is True         # 범위형 period "→" 해석 (v2 조정 5)
    assert by_id["e6"].grounded is False        # period 빈 값 → fail-closed


def test_news_published_at_clean_passes():
    verdict = asyncio.run(run_verify(
        _plan(), _table(), _ra_with_news("2026-07-19T09:00:00"), [],
        chain=_chain(), sector_cards=[_card("card-1")]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e4"].grounded is True         # published_at 실존·cutoff 이내


def test_chain_none_keeps_packet_shape():
    verdict = asyncio.run(run_verify(_plan(), _table(), RaPacket(), []))
    assert verdict.chain_verdicts == []          # off-path 무영향


def test_claim_metric_id_exact_unique_longest_alias():
    assert _claim_metric_id("memory_price_usd_per_gb") == "memory_price_usd_per_gb"
    assert _claim_metric_id("D램 현물가") == "memory_price_usd_per_gb"  # 유일 alias "현물가"
    # "토큰 가격"은 token_price alias(최장) — memory의 "가격"보다 김 → 교차 오귀속 차단 (r1-B7)
    assert _claim_metric_id("토큰 가격") == "token_price"
    assert _claim_metric_id("영업이익률") == ""    # 무매칭 → fail-closed
    assert _claim_metric_id("") == ""


def test_g2_metric_identity_blocks_cross_metric_anchor():
    tagged = [(5.0, "percent", "memory_price_usd_per_gb")]
    assert _g2_supported(5.0, "percent", tagged,
                         claim_metric_id="memory_price_usd_per_gb")
    assert not _g2_supported(5.0, "percent", tagged, claim_metric_id="token_price")
    assert not _g2_supported(5.0, "percent", tagged, claim_metric_id="")  # fail-closed
    untagged = [(5.0, "percent", "")]
    assert _g2_supported(5.0, "percent", untagged, claim_metric_id="")    # 기존 동작


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


def test_risk_consumes_verified_texts_and_chain_verdicts(monkeypatch):
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
    assert "[검증 통과 주장]" in captured["prompt"]
    assert "HBM 수요가 견조하다" in captured["prompt"]   # 원문 텍스트 — 수 요약 아님 (r1-B5)
    captured.clear()
    asyncio.run(run_risk(_plan(), _table()))     # off-path
    assert "[인과 체인 판정]" not in captured["prompt"]
    assert "[검증 통과 주장]" not in captured["prompt"]
```

  (주의: `_table()`의 claim은 `type="context"`·`source="da_gpt"`·secondary 아님 → G1 후보 0 = LLM 무호출 — verify 오프라인 관례. context claim은 게이트 전무 통과로 `final="verified"` — RISK 원문 테스트가 이를 이용)

- [ ] **Step 2~4: 실패→구현→통과+회귀** — 기존 G2 테스트 전량 green(미태그 anchor·`metric_identity=False` 기본값 무변경 확인) + **T1 identity green** (off-arm: metric_identity=False·chain=None → 기존 판정·프롬프트 동일)
- [ ] **Step 5: Commit** — `'feat(chain): VERIFY chain_verdicts 소스별 날짜 fail-closed·G2 canonical metric ID 관통·RISK verified 원문+체인 소비 (3부 T6)'`

---

### Task 7: SYNTHESIZE 시나리오 계약 — grounded edge 요구·코드 후검증·1회 재합성

**Files:**
- Modify: `engine/stages/synthesize.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_scenario_contract.py`

**Interfaces:**
- `_SCENARIO_INSTR`(상수) — `_INSTR`에 조건부 append: "답변 말미에 `## 긍정 시나리오`와 `## 부정 시나리오` 절을 각각 두라. 각 절은 4줄 필수: `- 체인:`([인과 체인] 절의 edge_id 인용 — 근거확인된 edge 포함), `- 지표:`([결정적 수치] 절 항목 인용, 없으면 정확히 '지표 없음'), `- 유효 조건:`, `- 기각 조건:`. 숫자는 [결정적 수치] 절의 값 외에 쓰지 마라."
- `_render_context(..., chain: ChainPacket | None = None, chain_verdicts: list | None = None)` — chain 있으면 `[인과 체인]` 절 렌더 (B5 — **event/mechanism/verdict/thesis_relation/contradicting 포함, 길이 상한**): 헤더 줄 `사건: {event[:200]} / 기제: {mechanism[:300]} / 판정: {verdict[:200]}`, edge별 `- {edge_id} {edge} ({kind}/{'근거확인' if grounded else '미확인'}): 인용 {supporting_card_ids + metric_fact_ids}{' / 반증 카드 ' + contradicting_card_ids if any}`, thesis_relation별 `- (테제) {thesis_revision_id} {relation}`
- `validate_scenarios(answer_md: str, chain: ChainPacket, typed_facts: list[TypedFact], chain_verdicts: list[ChainEdgeVerdict]) -> list[str]` — 코드 후검증 (빈 리스트 = 통과, B6·판정 2 강화판):
  - **정확한 H2 절 경계**: `## 긍정 시나리오`·`## 부정 시나리오` 각 절 = 해당 헤더부터 다음 `## ` 또는 EOF까지 — 마커 검사는 절 내부 한정
  - 각 절에 `- 체인:`·`- 지표:`·`- 유효 조건:`·`- 기각 조건:` 라인 존재 + **콜론 뒤 payload 비어있지 않음**
  - `- 체인:` 라인의 `\be\d+\b` **정확 토큰**이 chain 실존 edge_id ⊆ ∧ ≥1, 그리고 인용 edge 중 **≥1이 chain_verdicts에서 grounded=True** (ungrounded-only 체인 불인정)
  - typed_facts 비어있지 않으면 `- 지표:`가 fact의 label 또는 id를 ≥1 포함, 비어있으면 payload가 정확히 `지표 없음`
- `run_synthesize(..., chain=None, chain_verdicts=None, scenario_required: bool = False)` — scenario_required ∧ chain 존재: 1차 합성 → validate → 미충족 시 1회 재합성(컨텍스트에 `[재합성 — 시나리오 계약 미충족]\n` + 사유) → 재실패 시 `DraftAnswer.scenario_flags = issues` (답변 유지)
- orchestrator: `run_synthesize(..., thesis_section=thesis_section, chain=chain, chain_verdicts=verdict.chain_verdicts, scenario_required=(plan.tier >= 3 and chain is not None and risk.applicable))` — **`plan.tier >= 3` 명시** (B6: routing.py:17 `risk_forced`는 tier2에서도 applicable 가능 — force_on 프로필·requires_countercase). scenario_flags 발생 시 `degraded.append("scenario_contract")` — FinalAnswer.degraded로 관찰(eval이 잡음)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_scenario_contract.py
import asyncio

from contracts import (ChainEdge, ChainEdgeVerdict, ChainPacket, ClaimTable, DaPacket,
                       EnvelopeMeta, PlanPacket, TypedFact, UnitAnswer)
from stages.synthesize import run_synthesize, validate_scenarios

_CHAIN = ChainPacket(meta=EnvelopeMeta(), event="HBM 증설 보도",
                     mechanism="공급 확대 기대", edges=[
    ChainEdge(edge_id="e0", edge="B->A", kind="observed",
              supporting_card_ids=["card-1"]),
    ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference")])
_VERDICTS = [ChainEdgeVerdict(edge_id="e0", grounded=True),
             ChainEdgeVerdict(edge_id="e1", grounded=False)]
_FACTS = [TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB",
                    label="D램 현물가 (ddr5_16gb)")]

# 권고 2 반영: 근거 없는 수량("2건 이상") 제거 — 숫자 불변식과 충돌 금지
_GOOD = """결론.

## 긍정 시나리오
- 체인: e0 (B->A) 경로 유지
- 지표: D램 현물가 (ddr5_16gb) 상승 지속
- 유효 조건: 하이퍼스케일러 발주 유지 보도 확인
- 기각 조건: 발주 축소 보도

## 부정 시나리오
- 체인: e0 역전 — 발주 둔화
- 지표: D램 현물가 (ddr5_16gb) 하락 전환
- 유효 조건: 재고 경고 보도 누적
- 기각 조건: 가격 반등
"""


def test_validate_good_and_missing_section():
    assert validate_scenarios(_GOOD, _CHAIN, _FACTS, _VERDICTS) == []
    bad = _GOOD.split("## 부정 시나리오")[0]
    assert any("부정 시나리오" in i
               for i in validate_scenarios(bad, _CHAIN, _FACTS, _VERDICTS))


def test_validate_rejects_fake_edge_ungrounded_and_empty_payload():
    fake = _GOOD.replace("체인: e0", "체인: e9")
    assert any("체인" in i for i in validate_scenarios(fake, _CHAIN, _FACTS, _VERDICTS))
    ungrounded = _GOOD.replace("체인: e0 (B->A) 경로 유지", "체인: e1 경유") \
                      .replace("체인: e0 역전 — 발주 둔화", "체인: e1 역전")
    # grounded=True edge 0개 인용 → 불인정 (r1-B6)
    assert any("체인" in i
               for i in validate_scenarios(ungrounded, _CHAIN, _FACTS, _VERDICTS))
    empty = _GOOD.replace("- 유효 조건: 하이퍼스케일러 발주 유지 보도 확인", "- 유효 조건:")
    assert any("유효 조건" in i
               for i in validate_scenarios(empty, _CHAIN, _FACTS, _VERDICTS))


def test_validate_metric_contract():
    no_metric = _GOOD.replace("D램 현물가 (ddr5_16gb)", "임의 지표")
    assert any("지표" in i
               for i in validate_scenarios(no_metric, _CHAIN, _FACTS, _VERDICTS))
    # facts 없음 → '지표 없음'만 허용 (권고 2 — 계약 정합 fixture)
    ok = _GOOD.replace("- 지표: D램 현물가 (ddr5_16gb) 상승 지속", "- 지표: 지표 없음") \
              .replace("- 지표: D램 현물가 (ddr5_16gb) 하락 전환", "- 지표: 지표 없음")
    assert validate_scenarios(ok, _CHAIN, [], _VERDICTS) == []
    assert any("지표" in i for i in validate_scenarios(_GOOD, _CHAIN, [], _VERDICTS))


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
    draft = asyncio.run(run_synthesize(plan, da, chain=_CHAIN,
                                       chain_verdicts=_VERDICTS,
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
            calls.append((ctx, instr))
            return _GOOD
    monkeypatch.setattr("stages.synthesize.Role", _FakeRole)
    plan, da = _plan_da()
    draft = asyncio.run(run_synthesize(
        plan, da, claim_table=ClaimTable(typed_facts=_FACTS),   # 권고 2 — facts 실존과 정합
        chain=_CHAIN, chain_verdicts=_VERDICTS, scenario_required=True))
    assert len(calls) == 1 and draft.scenario_flags == []
    ctx, instr = calls[0]
    assert "## 긍정 시나리오" in instr                   # 계약 지시
    assert "[인과 체인]" in ctx and "공급 확대 기대" in ctx  # mechanism 렌더 (r1-B5)
    calls.clear()
    asyncio.run(run_synthesize(plan, da))                # off-path
    assert len(calls) == 1
    assert "## 긍정 시나리오" not in calls[0][1] and "[인과 체인]" not in calls[0][0]
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (validate의 지표 대조는 run_synthesize에 전달된 claim_table.typed_facts 기준 — 없으면 빈 목록. T1 identity green)
- [ ] **Step 5: Commit** — `'feat(chain): SYNTHESIZE 시나리오 계약 — H2 절 경계·grounded edge 요구·비어있지 않은 payload·tier3 명시·1회 재합성 (3부 T7)'`

---

### Task 8: 플레이북 구조 게이트 소비자 — PLAN 이후 평가·series/unit 코드 검증·all-or-none

**Files:**
- Modify: `engine/stages/playbook.py`, `engine/orchestrator.py`
- Create: `engine/tests/fixtures/playbook_structured_gate.json` (실존 holdout_passed 플레이북 1건을 손 마이그레이션 — 라이브 경로 fixture, B8)
- Test: `engine/tests/test_playbook_gates.py`

**Interfaces (stages/playbook.py):**
- `_STRUCT_KEYS = ("metric_id", "aggregation", "comparator", "threshold", "unit", "max_age_days")` (selector·window_days는 선택)
- `parse_gate_checks(pb: dict) -> tuple[list[PlaybookGateCheck], list[str]]` — gate별: _STRUCT_KEYS 전무 → 문자열 gate(무로그 — 하위 호환) / 전부 존재+validate 통과 → 채택 / 일부만 또는 validate 실패 → 구조 판정 전체 무시 + 로그. `aggregation ∈ ("mean_window","yoy")`인데 `window_days <= 0` → 불완전
- `evaluate_gate(check, store, now: datetime) -> PlaybookGateOutcome` — 전부 코드:
  - `check.metric_id not in METRIC_REGISTRY` 또는 필터 후 관측 0건 → `unavailable/no_metric`
  - **관측 필터 (B8 — selector 전체 참여)**: `meta_filter.items() ⊆ o.meta.items()` **그리고** `selector.series`가 있으면 `metrics_registry._group_key(o.meta) == selector.series` (하드 필터 — 이종 시리즈 혼입 차단)
  - **혼합 단위 거부 (B8)**: 필터 후 관측들의 비어있지 않은 unit이 2종 이상 → `unavailable/unit_mismatch` (혼합 평균 금지). 단일 unit != check.unit ∧ `aggregation != "yoy"` → `unit_mismatch`; yoy는 산출 단위 percent 고정 — check.unit != "percent"면 `unit_mismatch`
  - `sector.period.parse_period`로 ts 해석 — 미래·파싱불가 관측 무효(fail-closed), 최신 유효 관측 나이 > max_age_days → `unavailable/stale_data`
  - aggregation: `last` / `mean_window`(now−window_days 내 평균) / `yoy`((최신/1년 전 최근접 − 1)×100, 부재 → stale_data)
  - comparator 적용 → `pass|fail`, `evidence_observation_id = observation_id(metric, ts, meta)` (최신 관측)
- `evaluate_playbook_gates(pb, store, now) -> tuple[list[PlaybookGateOutcome], list[str]]`
- **orchestrator — 평가 배치 이동 (B8)**: ⓪′(PLAN 전, orchestrator.py:200~208)이 아니라 **casemem 블록 뒤·ASSEMBLE 전** — `plan.knowledge_cutoff` 실존(eval 경로는 line 231에서 이미 manifest `as_of`로 덮여 있어 **단일 식으로 양경로 충족**), `sector_metric_notes`도 line 320에서 이미 초기화됨(**init 순서 결함 해소** — 앞에서 append 시 소실되던 문제):

```python
    if playbook and not effective_disable_p23:
        try:
            from stages.playbook import evaluate_playbook_gates, parse_gate_checks
            _gate_store = eval_bundle.store() if eval_bundle else None
            if _gate_store is None:
                from sector.api import _get_store as _pb_get
                _gate_store = _pb_get()
            import datetime as _pb_dt
            _gate_now = _pb_dt.datetime.fromisoformat(
                plan.knowledge_cutoff + "T23:59:59+00:00")
            gate_outcomes, gate_logs = evaluate_playbook_gates(playbook, _gate_store,
                                                               _gate_now)
            for o in gate_outcomes:
                if o.verdict in ("pass", "fail") and o.value is not None:
                    chk = next(c for c in parse_gate_checks(playbook)[0]
                               if c.order == o.order)
                    sector_metric_notes.append(
                        f"[플레이북 게이트] {chk.check}: {o.metric_id}={o.value} "
                        f"{chk.unit} ({o.verdict}, 관측 {o.evidence_observation_id[:8]})")
            yield _layer("playbook", {
                "matched": playbook["slug"],
                "gate_outcomes": [o.model_dump() for o in gate_outcomes],
                "gate_logs": gate_logs})
        except Exception:  # noqa: BLE001
            degraded.append("playbook_gates")
```

  (unavailable은 notes 미기재 — 수치 없음, layer에만. 값의 답변 진입은 `sector_metric_notes` → 합성 `[결정적 수치]` 절 경로만, synthesize.py:136~137)
- 기존 `format_gates`·`format_connection`·`_valid_playbook`·문자열 gate 경로 무변경. **마이그레이션 명시 (B8 — 무동작 은폐 금지)**: 현 저장소 24개 플레이북은 전부 문자열 게이트 유지 — 구조 게이트는 T9 생산자로 **신규 합성분부터** 활성. 라이브 경로 검증은 손 마이그레이션 fixture 1건으로

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_playbook_gates.py
import datetime as dt
import json
from pathlib import Path

from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_contracts import observation_id
from stages.playbook import (_valid_playbook, evaluate_gate, evaluate_playbook_gates,
                             parse_gate_checks)

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
    assert evaluate_gate(chk, _store(tmp_path / "a", []),
                         NOW).unavailable_reason == "no_metric"
    bad_unit = _store(tmp_path / "b", [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="KRW/GB", meta={"category": "DRAM"})])
    assert evaluate_gate(chk, bad_unit, NOW).unavailable_reason == "unit_mismatch"
    old = _store(tmp_path / "c", [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2025-01", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    assert evaluate_gate(chk, old, NOW).unavailable_reason == "stale_data"


def test_selector_series_filters_and_mixed_units_refused(tmp_path):
    # B8 — series가 평가 알고리즘에 실참여 + 이종 단위 혼합 평균 차단
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta={"category": "DRAM", "item": "ddr5_16gb"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=90.0,
                          unit="KRW/GB", meta={"category": "DRAM", "item": "ddr4_8gb"})])
    sel = dict(_STRUCT, selector={"series": "ddr5_16gb",
                                  "meta_filter": {"category": "DRAM"}})
    (chk,), _ = parse_gate_checks(_pb([sel]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and out.value == 0.1        # _group_key 하드 필터
    (chk2,), _ = parse_gate_checks(_pb([_STRUCT]))            # series 없음 → 혼재
    assert evaluate_gate(chk2, store, NOW).unavailable_reason == "unit_mismatch"


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


def test_hand_migrated_fixture_valid_and_adopted(tmp_path):
    # B8 — 실존 holdout_passed 플레이북 1건의 손 마이그레이션본 (라이브 경로 fixture)
    pb = json.loads((Path(__file__).parent / "fixtures"
                     / "playbook_structured_gate.json").read_text())
    assert _valid_playbook(pb) and pb["status"] == "holdout_passed"
    checks, logs = parse_gate_checks(pb)
    assert len(checks) >= 1 and logs == []
    store = _store(tmp_path, [MetricObservation(
        metric=checks[0].metric_id, ts="2026-07", value=0.1,
        unit=checks[0].unit, meta=dict(checks[0].selector.meta_filter))])
    outs, logs2 = evaluate_playbook_gates(pb, store, NOW)
    assert any(o.verdict in ("pass", "fail") for o in outs) and logs2 == []


def test_evaluate_playbook_gates_wraps(tmp_path):
    store = _store(tmp_path, [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    outs, logs = evaluate_playbook_gates(
        _pb([_STRUCT, {"order": 9, "check": "문자열만", "operationalization": "o"}]),
        store, NOW)
    assert len(outs) == 1 and outs[0].verdict == "pass" and logs == []
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (기존 test_playbook_match.py 무변경 통과 = 문자열 하위 호환 증거. T1 identity green — off-arm은 게이트 블록 스킵, ⓪′ 매칭·기존 playbook layer 무변경)
- [ ] **Step 5: Commit** — `'feat(chain): 플레이북 구조 게이트 소비 — PLAN 이후 평가·series/meta/unit 코드 검증·혼합 단위 거부·all-or-none (3부 T8)'`

---

### Task 9: 플레이북 구조 게이트 생산자 — lib/playbooks.mjs 합성 계약 확장 (B8)

**Files:**
- Modify: `lib/playbooks.mjs`, `lib/playbooks.test.mjs`

**Interfaces:**
- `ENGINE_METRIC_IDS`(상수) — `engine/sector/metrics_registry.py`의 키 목록 미러(주석에 동기 규칙 명시 — 드리프트 시 엔진이 `no_metric`으로 fail-closed하므로 안전 방향)
- `buildPlaybookPrompt`(playbooks.mjs:146) 게이트 규칙에 추가: "게이트에 **구체 수치 기준**이 카드에 실재할 때만 선택 필드를 채워라: `metric_id`(다음 목록에서만: {ENGINE_METRIC_IDS}), `selector`({series, meta_filter}), `aggregation`(last|mean_window|yoy), `window_days`, `comparator`(>=|<=|>|<|==), `threshold`(숫자), `unit`, `max_age_days`. 카드에 근거 없는 값을 지어내지 마라 — 없으면 필드 자체를 생략(문자열 게이트로 동작)."
- `validatePlaybook`(playbooks.mjs:116) 확장 — 생산자 측 all-or-none: gate에 구조 필드가 **일부만** 있거나 `metric_id ∉ ENGINE_METRIC_IDS` 또는 `threshold` 비유한수면 구조 필드 전부 strip + dropped 사유(`구조 필드 불완전 — 문자열 게이트로 강등`). 완전하면 보존. 기존 evidence/operationalization 검증 무변경 (하위 호환 — 구 플레이북 JSON 그대로 통과)
- **마이그레이션 문서화**: 기존 24개 플레이북은 재합성 전까지 문자열 게이트 — 구조 게이트는 신규 `synthesizePlaybook` 산출분부터 활성 (moduledoc 주석 + 이 계획 명기. "이미 켜졌다" 류 보고 금지)

- [ ] **Step 1: 실패하는 테스트** (lib/playbooks.test.mjs에 추가 — 기존 테스트 스타일 준수)

```js
// lib/playbooks.test.mjs 에 추가
test("buildPlaybookPrompt는 구조 게이트 필드 지시와 metric 메뉴를 포함한다", () => {
  const prompt = buildPlaybookPrompt({ slug: "s", situation: "x", cardIds: [] }, []);
  assert.match(prompt, /metric_id/);
  assert.match(prompt, /memory_price_usd_per_gb/);   // ENGINE_METRIC_IDS 메뉴
  assert.match(prompt, /max_age_days/);
});

test("validatePlaybook은 완전한 구조 게이트를 보존하고 불완전분은 strip한다", () => {
  const base = { order: 1, check: "c", operationalization: "o", evidence: ["k1"] };
  const full = { ...base, metric_id: "memory_price_usd_per_gb",
    selector: { meta_filter: { category: "DRAM" } }, aggregation: "last",
    comparator: ">=", threshold: 0.05, unit: "USD/GB", max_age_days: 45 };
  const partial = { ...base, order: 2, metric_id: "memory_price_usd_per_gb" };
  const badId = { ...full, order: 3, metric_id: "no_such_metric" };
  const { playbook, dropped } = validatePlaybook(
    { gates: [full, partial, badId] }, new Set(["k1"]));
  assert.equal(playbook.gates[0].metric_id, "memory_price_usd_per_gb"); // 완전 → 보존
  assert.equal(playbook.gates[1].metric_id, undefined);   // 일부만 → strip (all-or-none)
  assert.equal(playbook.gates[2].metric_id, undefined);   // 미등록 id → strip
  assert.ok(dropped.some((d) => d.includes("구조 필드")));
});
```

- [ ] **Step 2~3: 실패 확인 → 구현** — `npm test` 실패 → 구현 → green
- [ ] **Step 4: 회귀** — `cd /home/ryze_yn/attn-viewer && npm test && npm run check:openapi` (exit code 게이트) — 기존 플레이북 하위 호환 확인
- [ ] **Step 5: Commit** — `'feat(playbook): 구조 게이트 생산자 계약 — 합성 프롬프트 metric 메뉴·validatePlaybook all-or-none strip·기존 24개 문자열 유지 명시 (3부 T9)'`

---

### Task 10: eval 배선(정확 분모·구조화 resolver·fail-hard) + 통합 테스트 + 전체 회귀

**Files:**
- Modify: `engine/evals/chain_judge.py` (`judge_edge_entailment`·`resolve_edge_evidence`), `engine/evals/metrics.py` (`chain_layer`·`grounded_edge_ratio`), `engine/evals/run_eval.py` (`_run_one_chain` — arm 파라미터·chain 소비·`entailed_edge_ratio` 실측, run_eval.py:479~545)
- Test: `engine/tests/test_chain_eval_wiring.py`, `engine/tests/test_p23_integration.py`

**Interfaces:**
- `evals/metrics.py`:
  - `chain_layer(layers) -> dict | None` — `name == "chain"` layer의 data
  - `grounded_edge_ratio(layers) -> float | None` — **분모 = chain layer의 실제 edge 집합** (B9). verify layer(최신 round) `chain_verdicts` 대조: 누락 verdict → False 계수, **verdict의 edge_id가 chain에 없거나 중복 → `ValueError`** (측정 무결성 — 은폐 금지). chain 부재·edges 빈 목록 → None
- `evals/chain_judge.py`:
  - `resolve_edge_evidence(edges: list[dict], bundle, layers) -> dict[str, str]` — **구조화 ID 역참조** (B9): 카드 id → `bundle.store().read_cards()` title+raw_quote / NewsItem id → `bundle.ra_news_items()` title+snippet / metric fact id → sector_rag layer `sector_typed_facts` + thesis layer `typed_facts`(T4에서 방출)의 id·label·value·unit. 미해석 id는 `"(미해석 인용)"` 마킹 — 자유 문자열 검색 금지
  - `async judge_edge_entailment(case_id, edges: list[dict], evidence_by_id: dict[str, str], role, *, thesis_claims: list[str] | None = None, raws_sink=None) -> float | None` — 구조화 판정 `_EdgeOut{rows: [{edge_id, entailed: bool, reason}]}`. 프롬프트: edge별 인용 근거 원문(resolver 결과) + **thesis_claims 포함**(캡처 시 — B9). **반환 rows 정합 대조 (B9)**: `{row.edge_id} != {edge.edge_id}` 집합 불일치·중복·미지 id → invalid → 1회 재시도 → None. 반환 = entailed / **전체 edge**. edges 빈 목록 → None
- `run_eval._run_one_chain(case, role, *, arm: bool | None = None) -> dict` (B2 — 4부 2-arm 승계 좌석): `overrides={"eval_bundle": str(bundle_path)}` + (`arm is not None`이면 `{"disable_p23": arm}` 병합). rec에 `"disable_p23": arm`, `"grounded_edge_ratio"`, `"layers_had_chain": chain_layer(layers) is not None` 추가, `entailed_edge_ratio`는 chain layer 있을 때 `judge_edge_entailment(...)` 실측(resolver+thesis 포함), 없으면 None + `"entailed_none_reason": "no_chain_layer"`
- `check_entailed_gate(records) -> list[str]`(순수 함수) — **chain layer가 있는데 `entailed_edge_ratio is None`인 케이스 id 목록** — run_chain_suite가 비어있지 않으면 리포트 저장 후 **exit 1** (1부 계획 1420행의 3부 전환 게이트 — null 허용 종료, B9)
- ChainPacket layer는 run_qa가 방출(T5) — eval은 layers 경유 소비. find_violations는 chain layer에 url 없음 → 무영향

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_eval_wiring.py
import asyncio

import pytest

from evals.chain_judge import judge_edge_entailment
from evals.metrics import chain_layer, grounded_edge_ratio


def _layers(verdicts):
    return [
        {"kind": "layer", "name": "chain", "round": 0, "data": {
            "event": "e", "mechanism": "m", "verdict": "",
            "edges": [{"edge_id": "e0", "edge": "B->A", "kind": "observed",
                       "supporting_card_ids": ["card-1"], "metric_fact_ids": [],
                       "contradicting_card_ids": []},
                      {"edge_id": "e1", "edge": "A_prime->A", "kind": "inference",
                       "supporting_card_ids": [], "metric_fact_ids": [],
                       "contradicting_card_ids": []}],
            "thesis_relation": []}},
        {"kind": "layer", "name": "verify", "round": 0, "data": {
            "counts": {"verified": 1, "unverified": 0, "rejected": 0},
            "chain_verdicts": verdicts}},
    ]


def test_grounded_ratio_denominator_is_chain_edge_set():
    # e1 verdict 누락 → False 계수 (분모 = 실제 edge 집합, r1-B9)
    layers = _layers([{"edge_id": "e0", "grounded": True, "note": ""}])
    assert chain_layer(layers)["edges"][0]["edge_id"] == "e0"
    assert grounded_edge_ratio(layers) == 0.5
    assert chain_layer([]) is None and grounded_edge_ratio([]) is None


def test_grounded_ratio_extra_or_duplicate_verdict_is_error():
    with pytest.raises(ValueError):                     # 미지 edge verdict (r1-B9)
        grounded_edge_ratio(_layers([{"edge_id": "e9", "grounded": True, "note": ""}]))
    with pytest.raises(ValueError):                     # 중복 verdict
        grounded_edge_ratio(_layers([{"edge_id": "e0", "grounded": True, "note": ""},
                                     {"edge_id": "e0", "grounded": False, "note": ""}]))


class _Role:
    model = "fake"
    def __init__(self, rows): self.rows, self.calls = rows, 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        return response_format.model_validate({"rows": self.rows})


_EDGES = _layers([])[0]["data"]["edges"]
_EV = {"card-1": "card-1: HBM 증설 본문"}


def test_judge_edge_entailment_ratio_over_all_edges_with_context():
    role = _Role([{"edge_id": "e0", "entailed": True, "reason": ""},
                  {"edge_id": "e1", "entailed": False, "reason": "근거 없음"}])
    ratio = asyncio.run(judge_edge_entailment(
        "cj-t", _EDGES, _EV, role, thesis_claims=["HBM 공급은 구조적으로 타이트하다"]))
    assert ratio == 0.5                                   # 분모 = 전체 edge
    assert asyncio.run(judge_edge_entailment("cj-t", [], _EV, role)) is None


def test_judge_edge_entailment_row_mismatch_returns_none():
    # 누락·중복·미지 edge_id 전부 invalid — 1회 재시도 후 None (r1-B9)
    missing = _Role([{"edge_id": "e0", "entailed": True, "reason": ""}])
    assert asyncio.run(judge_edge_entailment("cj-t", _EDGES, _EV, missing)) is None
    assert missing.calls == 2                             # 정확 1회 재시도
    unknown = _Role([{"edge_id": "e0", "entailed": True, "reason": ""},
                     {"edge_id": "e9", "entailed": True, "reason": ""}])
    assert asyncio.run(judge_edge_entailment("cj-t", _EDGES, _EV, unknown)) is None


def test_entailed_gate_pure_fn():
    from evals.run_eval import check_entailed_gate
    with_chain = {"id": "c1", "layers_had_chain": True, "entailed_edge_ratio": None}
    ok = {"id": "c2", "layers_had_chain": True, "entailed_edge_ratio": 0.8}
    no_chain = {"id": "c3", "layers_had_chain": False, "entailed_edge_ratio": None}
    assert check_entailed_gate([with_chain, ok, no_chain]) == ["c1"]  # 1부 1420행 게이트
```

```python
# engine/tests/test_p23_integration.py — B3 비메모리 + on-arm 통합 (하네스 재사용)
from tests.p23_harness import run_pipeline


def test_non_memory_full_profile_no_thesis_no_chain(tmp_path):
    # full 프로필(sector_rag_enabled=True)이지만 is_sector_question=False —
    # 게이트가 프로필이 아니라 memory_sector_active임을 증명 (r1-B3)
    out = run_pipeline("코스피 은행 배당주 지금 어때?", tmp_path=tmp_path)
    names = [l["name"] for l in out["layers"]]
    assert "thesis" not in names and "chain" not in names
    assert not any("chain" in d for d in out["final"]["degraded"])


def test_on_arm_sector_question_emits_thesis_and_chain(tmp_path):
    out = run_pipeline("SK하이닉스 HBM 현물가 흐름 어때?", tmp_path=tmp_path)
    names = [l["name"] for l in out["layers"]]
    assert "chain" in names                       # 토글 기본 ON — 3부 경로 가동
    verify = [l for l in out["layers"] if l["name"] == "verify"][-1]
    assert "chain_verdicts" in verify["data"]


def test_off_arm_override_suppresses_everything(tmp_path):
    out = run_pipeline("SK하이닉스 HBM 현물가 흐름 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": True})
    names = [l["name"] for l in out["layers"]]
    assert "thesis" not in names and "chain" not in names   # B2 — run override arm
```

  (하네스 canned role에 `chain_synth` 추가 — 실존 카드 id 인용 proposal. T1 golden은 off-arm이라 무영향)

- [ ] **Step 2~4: 실패→구현→통과**
- [ ] **Step 5: 전체 회귀** — `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/ -q` 전부 green + `DISABLE_P23=true .venv/bin/python -m pytest tests/ -q` green(권고 3의 env 내성 포함) + `cd /home/ryze_yn/attn-viewer && npm run check:openapi && npm test` — **fallback·`|| true` 금지, exit code가 게이트**. 타 세션 유래 기존 실패는 파일 소관 확인 후 명시 격리
- [ ] **Step 6: Commit** — `'feat(chain): eval 배선 — grounded 분모 정확화·row 정합 대조·구조화 resolver·thesis 컨텍스트·entailed None fail-hard·arm 파라미터 (3부 T10)'`

---

### Task 11: codex 리뷰 → 승인 후 배포 → 라이브 스모크

- [ ] **Step 1: codex 리뷰** — 신규 4파일 + 수정 13파일 diff. 관점: ① off-arm 바이트 동일(golden 하네스 방식 포함) ② effective_disable_p23 단일 결정·관통 ③ memory_sector_active 게이트 ④ CHAIN_EDGES 단일 진실원(judge/validator 공용) ⑤ grounding fail-closed(소스별 날짜) ⑥ G2 metric ID fail-closed ⑦ 게이트 배치·series·생산자 계약 ⑧ eval 분모·정합·fail-hard ⑨ 숫자 불변식·AUDIT 격리. 블로커 반영→승인 왕복(docs/memory-chain-review-p3-*.md). **리뷰 반영 전 다음 단계 금지.**
- [ ] **Step 2 (승인 후에만): 배포** — 커밋 완료·브랜치 확인 후 `pm2 restart attn-engine`. 신규 패키지 0 확인.
- [ ] **Step 3: 라이브 스모크** — 실질문 1건("SK하이닉스 지금 사도 될까?")을 기본(ON)으로 실행 → thesis·chain layer, 배경 판 절·시나리오 절·chain_verdicts 실물 확인 + 답변 수량 literal 출처 육안 점검. 이어 동일 질문을 오프라인 orchestrator 직호출 스크립트에서 `overrides={"disable_p23": True}`로(PM2 환경 변경 금지 — B2 방식 그대로) → thesis/chain layer 0건·기존 형태 답변. 두 실행의 layer 목록 diff를 보고에 기록.
- [ ] **Step 4: 렛저 기록** — `.superpowers/sdd/progress.md` 갱신. **workflow-review.html 현행화+스크린샷은 컨트롤러가 같은 세션 마지막에.**

---

## Self-Review 기록 (v2)

- **B1**: 전역 SCHEMA_VERSION=1 무변경(T2 테스트로 고정) / CHAIN_SCHEMA_VERSION 분리 / G2 metric identity·시나리오·게이트 전부 effective 토글 안쪽(`metric_identity` 파라미터 포함) / T1 golden 하네스가 pre-P3 캡처본과 off-arm의 프롬프트·layer·final 등치를 전 태스크 상시 검증
- **B2**: `effective_disable_p23` run_qa 진입부 1회 결정(overrides 재대입 전 원본에서) — 소스 수준 테스트(T4)로 결정 지점 단일성 고정, `_run_one_chain(arm=...)` 좌석(T10)으로 1부 1385~1391 2-arm 계약 승계
- **B3**: `memory_sector_active = plan_query 성공`(is_sector_question 결정적 게이트) — 비메모리 full-profile 통합 테스트(T10)
- **B4**: CHAIN_EDGES 명시 열거 8개(judge \_INSTR 인과 사슬 도출) — judge `_validate_row` 정규화 + ChainEdge 멤버십 validator + 노드=\_VALID_AXIS 드리프트 가드. event_types는 `extract_event_types` 실추출(스코어 3항 전부 라이브, 인위 SectorQueryPlan 테스트 제거) — 단 opt-in(v2 조정 1: 검색 경로 보호)
- **B5**: T7 렌더에 event/mechanism/verdict/thesis_relation/contradicting(길이 상한) / RISK에 verified claim **원문** + chain_verdicts / run_chain `(packet, 사유)` 튜플 — 호출부가 `chain:{사유}` degraded 기록
- **B6**: 소스별 날짜 필드(카드 ts·NewsItem published_at·fact period) 전부 fail-closed / validator에 chain_verdicts 전달·grounded≥1 요구·H2 절 경계·비어있지 않은 payload·정확 edge 토큰 / `scenario_required = plan.tier >= 3 and chain and risk.applicable`
- **B7**: keyword 교량 폐기 — 생성 시점 canonical metric ID(섹터·thesis fact) + claim측 정확 키/label/유일 최장 alias, 0·복수 → anchor 사용 거부. 미태그 anchor 기존 동작(회귀 0)
- **B8**: 평가를 casemem 뒤로 이동(plan.knowledge_cutoff 단일 식이 eval as_of까지 커버 — line 231 선덮임) / sector_metric_notes init(line 320) 이후 append / selector.series `_group_key` 하드 필터 + 혼합 단위 거부 / T9 생산자 태스크 신설 + "기존 24개는 문자열 유지, 신규 합성분부터" 명시 + 손 마이그레이션 fixture 라이브 경로 테스트
- **B9**: grounded 분모=실제 edge 집합·누락 False·초과/중복 ValueError / judge row 정합(누락·중복·미지 → None) / 구조화 resolver(카드·NewsItem·metric fact ID 역참조) / thesis claim judge 컨텍스트 포함 / `check_entailed_gate` — chain 존재 시 None은 exit 1(1부 1420)
- **판정 3건**: G2 keyword 기각 수용(B7) / 시나리오 강화 수용(B6) / EnvelopeMeta 실제 round\_·plan_ref 기록(meta 필수 필드화, round 0 고정 폐기)
- **권고 6건**: 실존 식별자만(CHAIN_EDGES가 이제 A_prime->A·C->B의 정본) / \_GOOD 수량 제거·facts 정합 / settings는 model_fields 기본값 검사 / run_verify 2곳 정정 / ChainPacket.meta 실값 테스트 / Field(default_factory)·threshold 유한성·Outcome 정합 validator
- 성공 기준 계측: 주입 수량 literal 0(T4), grounded_edge_ratio(T10), entailed_edge_ratio(T10 실측), stale/degraded 사용률(thesis layer freshness)
- 커밋 11개 전부 명시적 add·작은따옴표, 라이브 영향 코드는 T11 승인 후 배포
