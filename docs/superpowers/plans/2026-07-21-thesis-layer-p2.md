# Thesis "현재 판" 레이어 (스펙 2부) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 섹터 카드·지표에서 "현재 판"(시드 가설 8개의 상태)을 완전 자동으로 합성·유지하는 Thesis 레이어 — append-only revision, 코드 가드레일 4종, 일일 갱신 잡.

**Architecture:** `engine/sector/thesis*.py` 신설. LLM(sonnet)은 statement 텍스트·근거 후보·metric 이름만 제안하고, 코드가 인용 검증·publisher 독립성·수량 금지·관측값 역참조를 강제한다. 검증 LLM(교차 provider)이 지지성만 기각 방향으로 판정. freshness는 저장하지 않고 조회 시 파생. 갱신은 collect_all 말미 훅(never-block) + CLI.

**Tech Stack:** Python 3.12(engine/.venv), pydantic v2, 기존 Role/SectorStore. 답변 파이프라인 **무접촉**(주입은 3부).

**스펙:** docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md §2부 (codex r1~r4 왕복 반영판)

## Global Constraints

- **완전 자동·수동 검수 없음** — 모든 가드레일은 코드 검증. LLM 산출을 신뢰하는 경로 금지.
- statement supporting **2개 이상 + publisher_id 2종 이상**(전재 중복은 1주체 계수). 빈 raw_quote·D급·자동 보존 공시(`interpreted_signal`에 `"(자동 보존)"` 포함) 카드는 지지 수 제외. `interpreted_signal`은 근거 불인정 — **quote는 카드 raw_quote/title의 부분문자열** 코드 검증.
- statement 텍스트 **수량 literal 금지**(단위·%·통화 결합 수치 또는 독립 수사) — 영문자 결합 식별자(HBM3E·DDR5·H100) 허용 (r2-R1).
- **key_metrics는 LLM이 metric 이름만 제안** — 코드가 store 역참조로 observation_id·value·unit·ts·meta·source 덮어쓰기 (r2-B2).
- append-only revision (`revision_id = {id}@{valid_from}`), freshness는 **파생 상태**(저장 금지). required_inputs 불충족 시 revision 미생성(직전 유지).
- 지지성 검증 LLM은 갱신 잡과 **분리된 교차 provider** — 기각은 근거 드롭 방향만(fail-safe).
- thesis 갱신 실패는 수집을 못 막고, 수집 실패는 thesis를 못 막는다 (never-block, thesis별 격리).
- 2부 기능은 답변 경로에 주입되지 않는다(3부). 갱신 잡은 `settings.thesis_update_enabled`(기본 True) 플래그로 오프 가능 — **3부 주입은 disable_p23 토글 대상**(1부 계획 승계 제약).
- 엔진 재시작 `pm2 restart attn-engine`만. 커밋 작은따옴표. git add는 수정 파일만 명시.
- 각 Task 리뷰어 게이트 + 2부 완료 시 codex 교차 리뷰(Task 7). 모든 명령 cwd `/home/ryze_yn/attn-viewer/engine`, git은 `git -C /home/ryze_yn/attn-viewer …`.
- 병행 운영: 전향 proven 케이스 캡처(1부 README-chain.md 절차)를 2부 기간에도 지속 — 4부 holdout 10개 전제.

## File Structure

- `engine/sector/thesis_contracts.py` — ThesisRevision·Statement·Evidence pydantic + observation_id 파생 (T1)
- `engine/sector/thesis_seeds.py` — 시드 8개(selectors·priority·required_inputs) 코드 고정 (T1)
- `engine/sector/thesis_store.py` — append-only 저장·최신 조회·freshness 파생 (T2)
- `engine/sector/thesis_guard.py` — 가드레일 코드 필터 전부 (T3)
- `engine/sector/thesis_verify.py` — 지지성 검증 LLM 래퍼 (T4)
- `engine/sector/thesis_update.py` — 제안 LLM 호출 + 파이프라인 + 훅/CLI (T5)
- Modify: `engine/providers.py`(역할 2개), `engine/app/settings.py`(플래그), `engine/sector/runner.py`(훅), `engine/sector/api.py`(GET /v1/sector/theses), `engine/evals/bundle.py`(capture thesis 스냅샷) (T5·T6)
- 테스트: `engine/tests/test_thesis_{contracts,store,guard,verify,update}.py`, `test_eval_bundle.py` 추가분

---

### Task 1: 계약 + 시드

**Files:**
- Create: `engine/sector/thesis_contracts.py`, `engine/sector/thesis_seeds.py`
- Test: `engine/tests/test_thesis_contracts.py`

**Interfaces (Produces):**
- `Evidence(card_id: str, canonical_url: str, publisher_id: str, quote: str)`
- `Statement(statement_id: str, text: str, supporting: list[Evidence], contradicting: list[Evidence] = [])`
- `KeyMetric(metric: str, observation_id: str, value: float, unit: str, ts: str, meta: dict = {}, source: str = "sector_store")`
- `RequiredInput(metric: str, max_age_days: int, min_count: int = 1)`
- `ThesisRevision(id, revision_id, claim, axis, selectors: dict, priority: int, assessment: Literal["strengthening","weakening","mixed"], statements: list[Statement], key_metrics: list[KeyMetric], required_inputs: list[RequiredInput], valid_from: str, input_snapshot: dict, updated_at: str)` — pydantic strict(extra forbid)
- `observation_id(metric: str, ts: str, meta: dict) -> str` — sha256(f"{metric}|{ts}|{json.dumps(meta, sort_keys=True)}")[:16] (MetricObservation에 id 필드가 없어 결정적 파생)
- `SEED_THESES: list[dict]` — 8개: hbm-tightness / hyperscaler-capex-phase / frontier-train-to-inference / token-demand-growth / memory-price-cycle / supply-overbuild-risk / china-competition-risk / nand-decoupling. 각각 `{id, claim, axis, selectors{entities, metrics, segments, event_types}, priority, required_inputs}` — axis·metric 이름은 실존 값 사용(카드 axis 값 공간은 `engine/sector/contracts.py` SectorCard.axis, 지표 이름은 `storage/rag/memory_sector/metrics/*.jsonl` 파일명: kr_semi_export·hyperscaler_capex·memory_price_usd_per_gb·tw_monthly_revenue·openrouter_daily_tokens·token_price·memory_capex·equip_revenue 등. 구현 시 ls로 확인해 실존만 넣을 것). required_inputs 예: hbm-tightness → [{metric:"memory_price_usd_per_gb", max_age_days:45, min_count:2}], hyperscaler-capex-phase → [{metric:"hyperscaler_capex", max_age_days:120, min_count:1}] (분기 지표는 max_age 길게 — 스펙).

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_contracts.py
import pytest
from pydantic import ValidationError

from sector.thesis_contracts import (Evidence, KeyMetric, RequiredInput, Statement,
                                     ThesisRevision, observation_id)
from sector.thesis_seeds import SEED_THESES


def _rev(**kw):
    base = dict(
        id="hbm-tightness", revision_id="hbm-tightness@2026-07-21T00:00:00",
        claim="HBM 공급은 구조적으로 타이트하다", axis="A",
        selectors={"entities": ["SK하이닉스"], "metrics": ["memory_price_usd_per_gb"],
                   "segments": ["hbm"], "event_types": ["supply_signal"]},
        priority=1, assessment="strengthening",
        statements=[Statement(statement_id="s1", text="HBM 수요가 공급을 앞선다",
                              supporting=[
                                  Evidence(card_id="c-1", canonical_url="https://a.com/1",
                                           publisher_id="a.com", quote="q1"),
                                  Evidence(card_id="c-2", canonical_url="https://b.com/2",
                                           publisher_id="b.com", quote="q2")])],
        key_metrics=[KeyMetric(metric="memory_price_usd_per_gb", observation_id="x" * 16,
                               value=0.1, unit="USD/GB", ts="2026-07")],
        required_inputs=[RequiredInput(metric="memory_price_usd_per_gb", max_age_days=45)],
        valid_from="2026-07-21T00:00:00", input_snapshot={"card_ids": [], "metric_observation_ids": []},
        updated_at="2026-07-21T00:00:00")
    base.update(kw)
    return ThesisRevision(**base)


def test_revision_roundtrip_and_strict():
    r = _rev()
    assert r.revision_id.startswith(r.id + "@")
    with pytest.raises(ValidationError):
        ThesisRevision(**{**_rev().model_dump(), "freshness": "fresh"})  # 파생 상태 저장 금지


def test_observation_id_deterministic():
    a = observation_id("m", "2026-07", {"item": "x"})
    b = observation_id("m", "2026-07", {"item": "x"})
    c = observation_id("m", "2026-07", {"item": "y"})
    assert a == b and a != c and len(a) == 16


def test_seeds_shape():
    assert len(SEED_THESES) == 8
    ids = [s["id"] for s in SEED_THESES]
    assert len(set(ids)) == 8
    for s in SEED_THESES:
        assert set(s["selectors"]) == {"entities", "metrics", "segments", "event_types"}
        assert s["required_inputs"], s["id"]
        assert isinstance(s["priority"], int)
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_thesis_contracts.py -v` → ModuleNotFoundError
- [ ] **Step 3: 구현** — 위 Interfaces 그대로 (`thesis_contracts.py`는 pydantic `_Strict` 관례를 `engine/contracts/packets.py`에서 확인해 동일 패턴 사용. `thesis_seeds.py`의 claim 문구는 스펙 시드 목록 기반 1문장씩, metrics는 실존 지표 파일명 확인 후 기입).
- [ ] **Step 4: 통과 확인** — PASS 3건 + `tests/ -q` 전체(450) 회귀
- [ ] **Step 5: Commit** — `git -C /home/ryze_yn/attn-viewer add engine/sector/thesis_contracts.py engine/sector/thesis_seeds.py engine/tests/test_thesis_contracts.py` / `'feat(sector): thesis 계약·시드 8종 (2부 T1)'`

---

### Task 2: ThesisStore — append-only + freshness 파생

**Files:**
- Create: `engine/sector/thesis_store.py`
- Test: `engine/tests/test_thesis_store.py`

**Interfaces:**
- Consumes: `thesis_contracts.ThesisRevision`, `sector.store.SectorStore.read_metric`
- Produces: `ThesisStore(root)` — `.append(rev: ThesisRevision) -> None`(중복 revision_id 거부 ValueError), `.latest(thesis_id) -> ThesisRevision | None`, `.latest_all() -> dict[str, ThesisRevision]`, `.revisions(thesis_id) -> list[ThesisRevision]`(valid_from 순), `.latest_as_of(thesis_id, as_of: str) -> ThesisRevision | None`(valid_from ≤ as_of 최신 — eval 재생용)
- `freshness(rev: ThesisRevision, store: SectorStore, now: datetime | None = None) -> Literal["fresh","degraded","stale"]` — required_inputs 각각: 해당 metric의 최신 관측 ts가 max_age_days 이내 & 관측 수 ≥ min_count. 전부 충족=fresh, 일부 미충족=degraded, 전부 미충족=stale. (지표 최신성=수집기 건강성 — 스펙 r2 #2 해소 방식)
- 저장 위치: `storage/rag/memory_sector/theses.jsonl` (SectorStore.root 기준 — 생성자는 SectorStore.root와 동일 root를 받음)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_store.py
import datetime as dt

import pytest

from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_store import ThesisStore, freshness
from tests.test_thesis_contracts import _rev   # 헬퍼 재사용 (import 가능하게 helper는 모듈 레벨)


def test_append_only_and_latest(tmp_path):
    ts = ThesisStore(tmp_path)
    r1 = _rev(valid_from="2026-07-20T00:00:00", revision_id="hbm-tightness@2026-07-20T00:00:00")
    r2 = _rev(valid_from="2026-07-21T00:00:00", revision_id="hbm-tightness@2026-07-21T00:00:00")
    ts.append(r1); ts.append(r2)
    with pytest.raises(ValueError):
        ts.append(r2)                                   # 중복 revision_id 거부
    assert ts.latest("hbm-tightness").revision_id == r2.revision_id
    assert ts.latest_as_of("hbm-tightness", "2026-07-20T12:00:00").revision_id == r1.revision_id
    assert len(ts.revisions("hbm-tightness")) == 2


def test_freshness_derived(tmp_path):
    store = SectorStore(tmp_path / "sector")
    store.append_observations([MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1, unit="USD/GB")])
    rev = _rev()
    now = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)
    assert freshness(rev, store, now=now) == "fresh"
    late = dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc)   # max_age 45일 초과
    assert freshness(rev, store, now=late) == "stale"
```

- [ ] **Step 2: 실패 확인** → ModuleNotFoundError
- [ ] **Step 3: 구현** — append는 jsonl append + 기존 revision_id 셋 검사. freshness의 ts 파싱: 관측 ts는 "2026-07"(월) 또는 "2026-07-10"(일) 혼재 — 월 단위는 말일로 해석해 나이 계산(보수적). 주의: test_thesis_contracts의 `_rev`를 import하려면 그 파일에서 `_rev`가 top-level 함수여야 함(이미 그렇게 설계됨).
- [ ] **Step 4: 통과 + 전체 회귀**
- [ ] **Step 5: Commit** — `'feat(sector): ThesisStore append-only·freshness 파생 (2부 T2)'`

---

### Task 3: 가드레일 코드 필터

**Files:**
- Create: `engine/sector/thesis_guard.py`
- Test: `engine/tests/test_thesis_guard.py`

**Interfaces:**
- Consumes: `sector.contracts.SectorCard`, `thesis_contracts.*`
- Produces:
  - `publisher_id(url: str) -> str` — 등록 가능 도메인(www 제거, 첫 host 라벨이 아닌 등록 도메인: "news.a.co.kr"→"a.co.kr" 수준의 간이 규칙 — public suffix 리스트 미도입, 마지막 2~3라벨 휴리스틱(co.kr·com 등) 주석 명시)
  - `quantity_literal(text: str) -> list[str]` — 단위·%·통화 결합 수치 또는 독립 수사 검출(영문자 결합 식별자 HBM3E·DDR5 허용 — 1부 calibration의 식별자 규칙과 동일 정규식 계열)
  - `eligible_card(card: SectorCard) -> bool` — 빈 raw_quote·source_grade=="D"·`"(자동 보존)" in interpreted_signal` 제외
  - `quote_valid(card: SectorCard, quote: str) -> bool` — quote가 card.raw_quote 또는 card.title의 부분문자열
  - `dedupe_publishers(evs: list[Evidence], cards: dict[str, SectorCard]) -> int` — 유효 독립 발행 주체 수: publisher_id 집합에서 **quote 정규화(공백·문장부호 제거) 유사 — 80% 이상 겹치는 두 근거는 1주체 계수**(전재 차단, difflib.SequenceMatcher)
  - `filter_statements(stmts: list[Statement], cards: dict[str, SectorCard]) -> tuple[list[Statement], list[str]]` — statement별: ①각 supporting의 card 실존·eligible·quote_valid 검사(불합격 근거 제거) ②잔여 supporting ≥2 & dedupe_publishers ≥2 ③text 수량 literal 없음 — 하나라도 미달 statement 드롭, 사유 목록 반환
  - `resolve_key_metrics(names: list[str], store: SectorStore) -> list[KeyMetric]` — 이름별 store.read_metric 최신 관측을 **코드가** KeyMetric으로 구성(observation_id 파생 포함). 미존재 이름은 무시+로그 사유 반환은 (metrics, dropped) 튜플

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_guard.py
from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore
from sector.thesis_contracts import Evidence, Statement
from sector.thesis_guard import (dedupe_publishers, eligible_card, filter_statements,
                                 publisher_id, quantity_literal, quote_valid,
                                 resolve_key_metrics)


def _card(cid, url, quote="본문 인용문", grade="A", signal=""):
    return SectorCard(id=cid, ts="2026-07-20T00:00:00", axis="A", direction="pos",
                      magnitude=2, source_grade=grade, title=f"제목-{cid}",
                      interpreted_signal=signal, raw_quote=quote, url=url,
                      entities=["SK하이닉스"])


def test_publisher_id():
    assert publisher_id("https://news.fnnews.com/a/1") == "fnnews.com"
    assert publisher_id("https://www.a.co.kr/x") == "a.co.kr"


def test_quantity_literal():
    assert quantity_literal("수출이 34% 늘었다")            # 수치+% 금지
    assert quantity_literal("가격이 12달러다")
    assert not quantity_literal("HBM3E와 DDR5 수요가 강하다")  # 식별자 허용
    assert not quantity_literal("수요가 공급을 앞선다")


def test_eligibility_and_quote():
    assert not eligible_card(_card("c", "https://a.com", quote=""))
    assert not eligible_card(_card("c", "https://a.com", grade="D"))
    assert not eligible_card(_card("c", "https://a.com", signal="공시 원문 확인 필요 (자동 보존)"))
    c = _card("c", "https://a.com", quote="HBM 수요가 강하다는 보도")
    assert quote_valid(c, "HBM 수요가 강하다")
    assert not quote_valid(c, "없는 문장")


def test_dedupe_and_filter(tmp_path):
    cards = {"c1": _card("c1", "https://a.com/1", quote="HBM 수요가 공급을 앞선다 보도"),
             "c2": _card("c2", "https://b.com/2", quote="HBM 수요가 공급을 앞선다 보도"),  # 전재
             "c3": _card("c3", "https://c.com/3", quote="완전히 다른 근거 문장")}
    evs = [Evidence(card_id="c1", canonical_url=cards["c1"].url, publisher_id="a.com",
                    quote="HBM 수요가 공급을 앞선다"),
           Evidence(card_id="c2", canonical_url=cards["c2"].url, publisher_id="b.com",
                    quote="HBM 수요가 공급을 앞선다")]
    assert dedupe_publishers(evs, cards) == 1              # 전재 → 1주체
    st_bad = Statement(statement_id="s", text="수요가 강하다", supporting=evs)
    st_good = Statement(statement_id="s2", text="수요가 강하다", supporting=[
        evs[0], Evidence(card_id="c3", canonical_url=cards["c3"].url,
                         publisher_id="c.com", quote="완전히 다른 근거 문장")])
    kept, dropped = filter_statements([st_bad, st_good], cards)
    assert [s.statement_id for s in kept] == ["s2"]
    assert dropped                                          # 사유 기록


def test_resolve_key_metrics(tmp_path):
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="kr_semi_export", ts="2026-07", value=1.5, unit="k_usd")])
    kms, dropped = resolve_key_metrics(["kr_semi_export", "ghost_metric"], store)
    assert len(kms) == 1 and kms[0].value == 1.5 and len(kms[0].observation_id) == 16
    assert dropped == ["ghost_metric"]
```

- [ ] **Step 2: 실패 확인** / **Step 3: 구현** (수량 정규식: `(?<![A-Za-z0-9])[+-]?\d+(?:[.,]\d+)?\s*(?:%|퍼센트|달러|원|조|억|만|배|bp|포인트)|(?<![A-Za-z0-9])\d+(?:[.,]\d+)?(?![A-Za-z0-9])` 계열 — 식별자는 영문자 인접이라 제외됨. 구현 후 테스트 케이스로 조정) / **Step 4: 통과+회귀** / **Step 5: Commit** `'feat(sector): thesis 가드레일 — 인용 검증·전재 계수·수량 금지·지표 역참조 (2부 T3)'`

---

### Task 4: 지지성 검증 LLM (교차 provider)

**Files:**
- Create: `engine/sector/thesis_verify.py`
- Modify: `engine/providers.py` (ROLE_MAP `"thesis_verifier": [("openai", settings.model_gpt_mini, "low")]` — 갱신 잡(sonnet)과 분리·교차)
- Test: `engine/tests/test_thesis_verify.py`

**Interfaces:**
- Produces: `async verify_statements(stmts: list[Statement], role) -> tuple[list[Statement], list[str]]` — statement별로 각 supporting에 대해 "이 quote가 이 statement를 지지하는가" 저지(structured output `{supported: bool, why: str}`), **기각된 근거만 제거**(드롭 방향 fail-safe), 제거 후 supporting <2면 statement 드롭. LLM 실패(예외·invalid)는 해당 근거 **유지**가 아니라 **보수적으로 제거하지 않고 통과** — 아니, 스펙 fail-safe 방향: 검증 실패 시 근거를 지우면 전 statement가 소멸할 수 있으므로 **판정 불가 근거는 유지 + 사유 로그**(검증은 기각 방향만 행동). 반환 둘째는 기각/불가 사유 목록.
- 배치: statement당 1콜(supporting 묶음 판정) — 비용 절약.

- [ ] **Step 1: 실패하는 테스트** (fake role로 배선 검증)

```python
# engine/tests/test_thesis_verify.py
import asyncio

from sector.thesis_contracts import Evidence, Statement
from sector.thesis_verify import verify_statements


class _FakeRole:
    def __init__(self, verdicts):                     # quote → supported bool
        self.verdicts = verdicts
        self.model = "fake"

    async def run(self, prompt, instructions="", response_format=None, **kw):
        rows = [{"quote": q, "supported": v, "why": "t"}
                for q, v in self.verdicts.items() if q in prompt]
        return response_format.model_validate({"rows": rows})


def _st(quotes):
    sup = [Evidence(card_id=f"c{i}", canonical_url=f"https://p{i}.com/1",
                    publisher_id=f"p{i}.com", quote=q) for i, q in enumerate(quotes)]
    return Statement(statement_id="s", text="수요가 강하다", supporting=sup)


def test_rejected_evidence_dropped_and_statement_killed():
    st = _st(["지지되는 인용", "무관한 인용", "또 무관"])
    role = _FakeRole({"지지되는 인용": True, "무관한 인용": False, "또 무관": False})
    kept, reasons = asyncio.run(verify_statements([st], role))
    assert kept == []                                  # supporting 1개 남아 드롭
    assert reasons


def test_all_supported_kept():
    st = _st(["인용 A", "인용 B"])
    role = _FakeRole({"인용 A": True, "인용 B": True})
    kept, _ = asyncio.run(verify_statements([st], role))
    assert len(kept) == 1 and len(kept[0].supporting) == 2
```

- [ ] **Step 2~4: 실패 확인→구현→통과+회귀** (structured output pydantic `_VerifyOut{rows: list[{quote, supported, why}]}`; 예외 시 해당 statement 근거 전체 "판정 불가 유지" + 사유)
- [ ] **Step 5: Commit** `'feat(sector): thesis 지지성 검증 — 교차 provider·기각 방향 fail-safe (2부 T4)'`

---

### Task 5: 갱신 잡 — 제안 LLM + 파이프 + 훅/CLI

**Files:**
- Create: `engine/sector/thesis_update.py`
- Modify: `engine/providers.py` (ROLE_MAP `"thesis_updater": [("anthropic", settings.model_claude_sonnet, "low")]`), `engine/app/settings.py` (`thesis_update_enabled: bool = True`), `engine/sector/runner.py` (collect_all 말미 훅 — write_status 이후, never-block try/except)
- Test: `engine/tests/test_thesis_update.py`

**Interfaces:**
- Produces: `async update_thesis(seed: dict, store: SectorStore, tstore: ThesisStore, updater_role, verifier_role, now=None) -> ThesisRevision | None` — 파이프:
  1. required_inputs 검사(freshness 파생 로직 재사용) — 미충족 metric 있으면 **None**(미생성, 사유 로그)
  2. 입력 조립: 최근 14일 카드(seed selectors의 entities/segments/event_types로 필터, eligible_card만, 카드당 `id·title·raw_quote[:200]·url`) + seed metrics의 최근 관측 요약
  3. 제안 LLM(structured output `_ProposalOut{assessment, statements: [{text, evidence: [{card_id, quote}]}], key_metric_names: list[str]}`): **경계 프롬프트** — "근거 quote는 제공된 카드 원문에서 그대로 발췌. 수치는 statement 텍스트에 쓰지 말 것"
  4. 코드 가드레일: Evidence 구성(canonical_url·publisher_id는 카드에서 **코드가** 채움 — LLM 입력 아님) → `filter_statements` → `verify_statements`(T4) → `resolve_key_metrics`
  5. **신규 인용 근거 없음(잔여 statements 0)이면 None** — "새 인용이 없으면 갱신하지 않는다"(스펙)
  6. ThesisRevision 조립(valid_from=now ISO, input_snapshot={사용 card_ids, metric observation_ids}) → tstore.append
- `async update_all(store, tstore=None, only: list[str] | None = None) -> dict[str, str]` — 시드별 격리(예외는 사유 문자열), 반환 {thesis_id: "updated"|"skipped: <사유>"|"error: .."}
- runner 훅: `if settings.thesis_update_enabled:` try: `await update_all(store)` except 전체 무시+status 로그 1줄. CLI: `python -m sector.thesis_update [--only id]`
- 테스트는 fake 역할·tmp store로 파이프 검증(제안→가드레일 드롭→미생성 / 정상 생성 / required_inputs 미충족 skip). LLM 실호출 없음.

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_update.py
import asyncio

from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore
from sector.thesis_store import ThesisStore
from sector.thesis_update import update_thesis


class _Updater:
    model = "fake-sonnet"
    def __init__(self, proposal): self.proposal = proposal
    async def run(self, prompt, instructions="", response_format=None, **kw):
        return response_format.model_validate(self.proposal)


class _Verifier:
    model = "fake-gpt"
    async def run(self, prompt, instructions="", response_format=None, **kw):
        import json, re
        quotes = re.findall(r'"quote":\s*"([^"]+)"', prompt) or []
        return response_format.model_validate(
            {"rows": [{"quote": q, "supported": True, "why": "t"} for q in quotes]})


def _seed():
    return {"id": "hbm-tightness", "claim": "HBM 타이트", "axis": "A", "priority": 1,
            "selectors": {"entities": ["SK하이닉스"], "metrics": ["memory_price_usd_per_gb"],
                          "segments": ["hbm"], "event_types": ["supply_signal"]},
            "required_inputs": [{"metric": "memory_price_usd_per_gb",
                                 "max_age_days": 3650, "min_count": 1}]}


def _env(tmp_path):
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1, unit="USD/GB")])
    store.append_cards([
        SectorCard(id="c1", ts="2026-07-20T00:00:00", axis="A", direction="pos",
                   magnitude=2, source_grade="A", title="t1", interpreted_signal="",
                   raw_quote="HBM 수요가 공급을 앞선다는 분석", url="https://a.com/1",
                   entities=["SK하이닉스"]),
        SectorCard(id="c2", ts="2026-07-20T00:00:00", axis="A", direction="pos",
                   magnitude=2, source_grade="A", title="t2", interpreted_signal="",
                   raw_quote="고객 인증 확대 보도 별개 근거", url="https://b.com/2",
                   entities=["SK하이닉스"])])
    return store, ThesisStore(tmp_path)


def test_update_creates_revision(tmp_path):
    store, tstore = _env(tmp_path)
    prop = {"assessment": "strengthening",
            "statements": [{"text": "HBM 수요가 공급을 앞선다",
                            "evidence": [{"card_id": "c1", "quote": "HBM 수요가 공급을 앞선다"},
                                         {"card_id": "c2", "quote": "고객 인증 확대 보도"}]}],
            "key_metric_names": ["memory_price_usd_per_gb"]}
    rev = asyncio.run(update_thesis(_seed(), store, tstore, _Updater(prop), _Verifier()))
    assert rev is not None and tstore.latest("hbm-tightness") is not None
    assert rev.key_metrics[0].value == 0.1               # 역참조 값 (LLM 아님)
    assert rev.input_snapshot["card_ids"]


def test_no_valid_statements_skips(tmp_path):
    store, tstore = _env(tmp_path)
    prop = {"assessment": "mixed",
            "statements": [{"text": "수출이 34% 늘었다",      # 수량 literal → 드롭
                            "evidence": [{"card_id": "c1", "quote": "HBM 수요가"},
                                         {"card_id": "c2", "quote": "고객 인증"}]}],
            "key_metric_names": []}
    rev = asyncio.run(update_thesis(_seed(), store, tstore, _Updater(prop), _Verifier()))
    assert rev is None and tstore.latest("hbm-tightness") is None


def test_required_inputs_unmet_skips(tmp_path):
    store, tstore = _env(tmp_path)
    seed = _seed()
    seed["required_inputs"] = [{"metric": "ghost_metric", "max_age_days": 30, "min_count": 1}]
    rev = asyncio.run(update_thesis(seed, store, tstore, _Updater({}), _Verifier()))
    assert rev is None
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (runner 훅은 diff 최소 — write_status 뒤 5줄 try/except; settings 플래그 1줄)
- [ ] **Step 5: Commit** `'feat(sector): thesis 갱신 잡 — 제안·가드레일·검증 파이프, collect_all 훅+CLI (2부 T5)'`

---

### Task 6: 조회 API + bundle 스냅샷

**Files:**
- Modify: `engine/sector/api.py` (GET `/v1/sector/theses` — latest_all + 파생 freshness), `engine/evals/bundle.py` (capture_bundle: theses.jsonl 존재 시 `latest_as_of(id, as_of)` revision들을 bundle `theses.jsonl`로 복사, manifest `thesis_revisions`에 revision_id 목록), `EvalBundle.theses() -> list[dict]`
- Test: `engine/tests/test_thesis_api_bundle.py`

**Interfaces:**
- Produces: GET /v1/sector/theses → `{"theses": [{...revision..., "freshness": "fresh"}]}`; `capture_bundle(..., thesis_store: ThesisStore | None = None)` 선택 인자(기본 None — 기존 호출 무변경·하위호환, 1부 케이스 24개 bundle은 재캡처하지 않음)
- 주의: capture는 불변 원칙 유지 — thesis 스냅샷은 **새 캡처부터** 적용(전향 케이스). manifest hash에 자동 포함(파일이 hash 대상).

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_api_bundle.py
import json

from evals.bundle import EvalBundle, capture_bundle
from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_store import ThesisStore
from tests.test_thesis_contracts import _rev


def test_capture_includes_thesis_snapshot(tmp_path):
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd")])
    tstore = ThesisStore(tmp_path / "s")
    tstore.append(_rev(valid_from="2026-07-19T00:00:00",
                       revision_id="hbm-tightness@2026-07-19T00:00:00"))
    tstore.append(_rev(valid_from="2026-07-25T00:00:00",                # as_of 이후 — 제외
                       revision_id="hbm-tightness@2026-07-25T00:00:00"))
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-20",
                         availability="unproven", ra_docs=[], prices={}, macro={},
                         thesis_store=tstore)
    b = EvalBundle(out)
    ths = b.theses()
    assert [t["revision_id"] for t in ths] == ["hbm-tightness@2026-07-19T00:00:00"]
    m = json.loads((out / "manifest.json").read_text())
    assert m["thesis_revisions"] == ["hbm-tightness@2026-07-19T00:00:00"]
    assert b.verify_hash()                                  # thesis 파일도 hash 포함
```

(API 라우트 테스트는 sector/api.py의 기존 테스트 관례를 확인해 동일 방식 1건 — 관례 부재 시 함수 직접 호출 테스트.)

- [ ] **Step 2~4: 실패→구현→통과+회귀** / **Step 5: Commit** `'feat(sector): theses 조회 API + bundle thesis 스냅샷 (2부 T6)'`

---

### Task 7: 라이브 가동 + 2부 codex 리뷰

- [ ] **Step 1: 배포·첫 갱신** — `pm2 restart attn-engine` 후 CLI로 1회 실제 갱신: `.venv/bin/python -m sector.thesis_update` → 시드별 결과(updated/skipped 사유) 확인. `storage/rag/memory_sector/theses.jsonl` 생성 revision들을 눈이 아닌 **코드 점검**: statement마다 supporting≥2·publisher 2종·수량 literal 0을 재검증하는 일회성 스크립트 실행 결과 기록.
- [ ] **Step 2: GET /v1/sector/theses 스모크** — curl로 freshness 포함 응답 확인.
- [ ] **Step 3: codex 2부 리뷰** — 대상: thesis_* 5개 파일·훅·API·bundle 스냅샷·라이브 revision 산출물. 관점: 가드레일 우회 가능성(LLM 산출 신뢰 경로 잔존), append-only 위반, 답변 경로 무접촉 확인. 블로커 반영→승인까지 왕복 (docs/memory-chain-review-p2-*.md).
- [ ] **Step 4: workflow-review.html §2부 카드 추가 + 스크린샷 확인, 렛저 기록.**

---

## Self-Review 기록

- 스펙 §2부 대조: 스키마(T1)·seed 8(T1)·append-only+valid_from+input_snapshot(T1·T2)·freshness 파생(T2)·갱신 잡 sonnet 14일(T5)·가드레일 1(publisher 2종·전재 dedupe·제외 규칙, T3)·2(quote substring+지지성 검증+전재, T3·T4)·3(key_metrics 역참조, T3·T5)·4(주입/AUDIT 제외 — 3부 소관, 2부는 주입 없음 명시)·수량 literal(T3)·required_inputs 미충족 미생성(T5) — 전부 매핑.
- statements의 "지지성 검증 = 갱신 잡과 분리된 교차 provider" — thesis_verifier(gpt mini) vs thesis_updater(sonnet) (T4·T5).
- eval 재생(latest_as_of)과 bundle thesis 스냅샷(T6) — 스펙 bundle 정의의 thesis revision 항목 이행. 1부 기존 bundle 24개는 불변 유지(재캡처 없음 — 하위호환 명시).
- 타입 일관성: Statement/Evidence/KeyMetric 시그니처가 T1~T6에서 동일. `_rev` 헬퍼 공유는 T1 테스트 파일 top-level 배치로 해결.
- YAGNI: 임베딩·thesis UI·3부 주입 제외.
