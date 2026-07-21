# Thesis "현재 판" 레이어 (스펙 2부) Implementation Plan (v3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

v3 — r2 잔존 5건+신규 2건 반영(방향 Literal 반환·PSL publisher·관측 source 필드·segments Literal·snapshot metric ID 검증·npm 게이트·CLI entrypoint). v2 — codex 계획 리뷰 블로커 12건 반영 (docs/memory-chain-review-p2-plan-r1_codex.md):
계약 우선(OpenAPI 선행), canonical 어휘(SK_HYNIX 등) 사용·실어휘 검증, verifier fail-closed
(이상 시 revision 전체 skip)·관련성/방향 판정·assessment 코드 집계, post-verifier 재가드,
빈 quote/URL 차단·publisher 재파생, meta_filter 그룹 역참조·registry source, 수량 acceptance
matrix, typed 계약(validator), cmd_capture 실배선·날짜 비교, 라이브 append는 codex 승인 후.

**Goal:** 카드·지표에서 시드 가설 8개의 "현재 판"을 완전 자동 합성·유지 — append-only revision, fail-closed 가드레일, 일일 갱신 잡. 답변 경로 무접촉(주입은 3부).

**Architecture:** LLM(sonnet)은 statement 텍스트·(card_id, quote) 근거 후보·metric 이름만 제안. 코드가 자격·인용·독립성·수량을 강제하고, 교차 verifier(gpt-mini)가 지지·관련성·방향을 기각 방향으로 판정 — **판정 이상(예외·누락·중복·미지 ID)은 신규 revision 전체 skip**(직전 유지 = never-block 보존). assessment는 검증된 방향 판정의 코드 집계.

**Tech Stack:** Python 3.12(engine/.venv)·pydantic v2·기존 Role/SectorStore. OpenAPI 계약 우선(AGENTS.md). Node contract 테스트(`npm run check:openapi`·`npm run test:contract`).

**스펙:** docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md §2부 + "1부 완료 스코프" 절

## Global Constraints

- **완전 자동·수동 검수 없음.** LLM 산출 신뢰 경로 금지 — Evidence의 canonical_url·publisher_id는 guard가 카드 url에서 **매번 재파생**(LLM/입력값 불신).
- statement supporting **≥2 + 독립 publisher ≥2**(전재는 quote 정규화 80% 유사 시 1주체). 부적격 카드(빈 raw_quote·D급·`"(자동 보존)" in interpreted_signal`) 제외, interpreted_signal 근거 불인정, **quote는 카드 raw_quote/title 부분문자열**(strip 후 비어있으면 무효).
- statement 텍스트 수량 literal 금지 — **acceptance matrix 고정**: 허용 {gpt-5.5, HBM3E, DDR5, H100} / 금지 {12%, 12퍼센트, $12, ₩12, USD12, 12 USD, 12달러, 12조, 3bp, 독립 숫자 "12"}.
- key_metrics: LLM은 metric **이름만** — 코드가 seed의 meta_filter 그룹 최신 관측을 역참조(observation_id 파생, source는 METRIC_REGISTRY label/desc). 
- append-only(`revision_id == f"{id}@{valid_from}"` validator 강제), freshness 파생(fresh/degraded/stale, min_count 포함, 월 단위 ts는 월말 해석+age 0 clamp, 미래·파싱 불가 ts는 해당 input **미충족** 처리 fail-closed). 단일 writer(fcntl.flock), **직전 revision과 실질 동일(statements·assessment·key_metrics values)이면 append 생략**.
- verifier는 갱신 LLM과 **분리·교차 provider**. 판정은 (statement_id, card_id) 결속, 입력 근거당 정확 1판정.
- contradicting은 2부에서 **항상 빈 배열**(proposal 스키마에 없음 — 명시적 미사용, 3부+에서 확장).
- never-block 양방향: 수집 실패↛thesis, thesis 실패↛수집(결과·status 무영향). `settings.thesis_update_enabled`(기본 True). 3부 주입은 disable_p23 토글 대상(승계 제약).
- **라이브 첫 append는 codex 2부 승인 이후**(T9) — append-only 데이터는 리뷰 전 생성 금지.
- 신규 HTTP 라우트는 **openapi.yaml 선행**(계약 우선) — `npm run check:openapi`·`npm run test:contract` 통과가 완료 조건.
- pm2 재시작만·작은따옴표 커밋·명시적 add. cwd `/home/ryze_yn/attn-viewer/engine`, git은 `git -C /home/ryze_yn/attn-viewer`.
- 병행 운영: 전향 proven 캡처 지속(1부 README-chain.md — T7 이후엔 thesis 포함 캡처).

## File Structure

- `engine/sector/thesis_contracts.py`(T1) / `thesis_seeds.py`(T1) / `thesis_store.py`(T2) / `thesis_guard.py`(T3) / `thesis_verify.py`(T4) / `thesis_update.py`(T5)
- Modify: `openapi.yaml`(T1), `engine/providers.py`(T4·T5 역할), `engine/app/settings.py`(T6), `engine/sector/runner.py`(T6), `engine/sector/api.py`(T7), `engine/evals/bundle.py`·`engine/evals/build_chain_cases.py`(T7)
- 테스트: `engine/tests/test_thesis_{contracts,store,guard,verify,update,runner_hook,api_bundle}.py`

---

### Task 1: 계약 확정 — OpenAPI + typed Thesis 계약 + canonical seeds

**Files:**
- Modify: `openapi.yaml` (신규 path `/v1/sector/theses`)
- Create: `engine/sector/thesis_contracts.py`, `engine/sector/thesis_seeds.py`
- Test: `engine/tests/test_thesis_contracts.py`

**Interfaces (Produces):**
- `Evidence(card_id: str, canonical_url: str, publisher_id: str, quote: str)` — quote·canonical_url·publisher_id는 `min_length=1` + strip validator, canonical_url은 `^https?://` validator
- `Statement(statement_id: str, text: str, supporting: list[Evidence], contradicting: list[Evidence] = [])`
- `KeyMetric(metric: str, observation_id: str, value: float, unit: str, ts: str, meta: dict = {}, source: str)`
- `RequiredInput(metric: str, max_age_days: int, min_count: int = 1, meta_filter: dict = {})`
- `Selectors(entities: list[str], metrics: list[str], segments: list[Literal["hbm","dram","nand","mixed"]], event_types: list[str])` — segments는 `SectorCard.memory_segment` Literal 값 공간 재사용 (r2-B6), typed (B8)
- `InputSnapshot(card_ids: list[str], metric_observation_ids: list[str])` — **LLM prompt에 실제 제공된 전체 ID**(채택분 아님)
- `ThesisRevision(id, revision_id, claim, axis: Axis, selectors: Selectors, priority: int, assessment: Literal["strengthening","weakening","mixed"], statements, key_metrics, required_inputs, valid_from, input_snapshot: InputSnapshot, updated_at)` — `Axis`는 `sector.contracts`의 SectorCard.axis Literal **재사용**(import), `revision_id == f"{id}@{valid_from}"` model_validator, valid_from은 `YYYY-MM-DDTHH:MM:SS` UTC 형식 validator, extra forbid
- `observation_id(metric, ts, meta) -> str` — sha256(f"{metric}|{ts}|{json.dumps(meta, sort_keys=True, ensure_ascii=False)}")[:16]
- `SEED_THESES: list[dict]` 8개 — **canonical 어휘만**: entities ⊆ ENTITY_PATTERNS canon(SAMSUNG·SK_HYNIX·MICRON·TSMC·NVIDIA·MICROSOFT 등), metrics ⊆ METRIC_REGISTRY 키(kr_semi_export·hyperscaler_capex·memory_capex·memory_price_usd_per_gb·tw_monthly_revenue·openrouter_daily_tokens·token_price·equip_revenue·ai_chip_revenue), event_types ⊆ EventType Literal 값, axis ⊆ Axis 값. memory_price 계열 required_inputs엔 `meta_filter: {"category": "DRAM"}` 식 그룹 고정 (B5)
- openapi.yaml: `GET /v1/sector/theses` — 응답 `{theses: [{...ThesisRevision 필드..., freshness: enum[fresh,degraded,stale]}]}` 스키마를 기존 sector 경로들(예: /v1/sector/status) 관례에 맞춰 추가

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_contracts.py
import pytest
from pydantic import ValidationError

from sector.contracts import EventType
from sector.entities import ENTITY_PATTERNS
from sector.metrics_registry import METRIC_REGISTRY
from sector.thesis_contracts import (Evidence, InputSnapshot, KeyMetric, RequiredInput,
                                     Selectors, Statement, ThesisRevision, observation_id)
from sector.thesis_seeds import SEED_THESES

_CANON = {c for c, _ in ENTITY_PATTERNS}


def make_rev(**kw):
    base = dict(
        id="hbm-tightness", revision_id="hbm-tightness@2026-07-21T00:00:00",
        claim="HBM 공급은 구조적으로 타이트하다", axis="A",
        selectors=Selectors(entities=["SK_HYNIX"], metrics=["memory_price_usd_per_gb"],
                            segments=["hbm"], event_types=["supply_signal"]),
        priority=1, assessment="strengthening",
        statements=[Statement(statement_id="s1", text="HBM 수요가 공급을 앞선다",
                              supporting=[
                                  Evidence(card_id="c-1", canonical_url="https://a.com/1",
                                           publisher_id="a.com", quote="q1"),
                                  Evidence(card_id="c-2", canonical_url="https://b.com/2",
                                           publisher_id="b.com", quote="q2")])],
        key_metrics=[KeyMetric(metric="memory_price_usd_per_gb", observation_id="x" * 16,
                               value=0.1, unit="USD/GB", ts="2026-07",
                               source="DRAM/NAND 소비자가 proxy")],
        required_inputs=[RequiredInput(metric="memory_price_usd_per_gb", max_age_days=45,
                                       meta_filter={"category": "DRAM"})],
        valid_from="2026-07-21T00:00:00",
        input_snapshot=InputSnapshot(card_ids=["c-1", "c-2"],
                                     metric_observation_ids=["x" * 16]),
        updated_at="2026-07-21T00:00:00")
    base.update(kw)
    return ThesisRevision(**base)


def test_revision_id_equality_enforced():
    with pytest.raises(ValidationError):
        make_rev(revision_id="hbm-tightness@2099-01-01T00:00:00")   # id@valid_from 불일치
    with pytest.raises(ValidationError):
        make_rev(valid_from="2026-07-21")                            # timestamp 형식 위반
    with pytest.raises(ValidationError):
        make_rev(axis="Z")                                           # Axis Literal 위반


def test_evidence_rejects_empty_and_bad_url():
    with pytest.raises(ValidationError):
        Evidence(card_id="c", canonical_url="https://a.com/1", publisher_id="a.com", quote="  ")
    with pytest.raises(ValidationError):
        Evidence(card_id="c", canonical_url="ftp://a.com/1", publisher_id="a.com", quote="q")
    with pytest.raises(ValidationError):
        Evidence(card_id="c", canonical_url="https://a.com/1", publisher_id="", quote="q")


def test_observation_id_deterministic():
    assert observation_id("m", "2026-07", {"a": 1}) == observation_id("m", "2026-07", {"a": 1})
    assert observation_id("m", "2026-07", {"a": 1}) != observation_id("m", "2026-07", {"a": 2})


def test_seeds_use_real_vocabulary():                # B6 — 가짜 세계 금지
    assert len(SEED_THESES) == 8
    import typing
    event_vals = set(typing.get_args(EventType))
    for s in SEED_THESES:
        sel = s["selectors"]
        assert set(sel["entities"]) <= _CANON, (s["id"], sel["entities"])
        assert set(sel["metrics"]) <= set(METRIC_REGISTRY), (s["id"], sel["metrics"])
        assert set(sel["event_types"]) <= event_vals, s["id"]
        assert set(sel["segments"]) <= {"hbm", "dram", "nand", "mixed"}, s["id"]  # r2-B6
        for ri in s["required_inputs"]:
            assert ri["metric"] in METRIC_REGISTRY, (s["id"], ri["metric"])
        make_rev(id=s["id"], revision_id=f"{s['id']}@2026-07-21T00:00:00",
                 claim=s["claim"], axis=s["axis"],
                 selectors=Selectors(**sel), priority=s["priority"],
                 required_inputs=[RequiredInput(**ri) for ri in s["required_inputs"]])
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_thesis_contracts.py -v` → ModuleNotFoundError
- [ ] **Step 3: openapi.yaml에 /v1/sector/theses 추가** — 기존 sector 경로 서술 관례(경로·스키마 구조)를 파일에서 확인 후 동일 스타일. 검증: `cd /home/ryze_yn/attn-viewer && npm run check:openapi` 통과.
- [ ] **Step 4: 구현** — 계약(위 Interfaces·validator 전부)·시드 8개(hbm-tightness/hyperscaler-capex-phase/frontier-train-to-inference/token-demand-growth/memory-price-cycle/supply-overbuild-risk/china-competition-risk/nand-decoupling — claim 1문장, canonical 어휘, memory_price 계열 meta_filter 고정, 분기성 지표 max_age 120+).
- [ ] **Step 5: 통과 + 회귀** — pytest 전체(450) + `npm run check:openapi`
- [ ] **Step 6: Commit** — `'feat(sector): thesis typed 계약·canonical 시드 8종 + OpenAPI /v1/sector/theses (2부 T1)'`

---

### Task 2: ThesisStore — append-only·freshness 파생·단일 writer

**Files:**
- Create: `engine/sector/thesis_store.py`
- Test: `engine/tests/test_thesis_store.py`

**Interfaces:**
- `ThesisStore(root)` — 파일 `<root>/theses.jsonl`. `.append(rev) -> bool`(fcntl.flock 배타 잠금; 중복 revision_id ValueError; **직전 최신과 실질 동일**(statements·assessment·key_metrics의 (metric,value) 목록 동일)이면 False 반환·미기록), `.latest(id)`, `.latest_all()`, `.revisions(id)`, `.latest_as_of(id, as_of: str)` — **as_of가 날짜(YYYY-MM-DD)면 `valid_from[:10] <= as_of`**, timestamp면 전체 비교 (B9 날짜/ts 혼용 해소)
- `freshness(rev, store, now) -> "fresh"|"degraded"|"stale"` — required_inputs별: meta_filter 매칭 관측 중 최신 ts 나이 ≤ max_age_days **and** 매칭 관측 수 ≥ min_count. ts 해석: `YYYY-MM`은 월말로, **미래 ts는 age 0 clamp가 아니라 해당 관측 무효(fail-closed)**, 파싱 불가도 무효. 전부 충족 fresh / 일부 degraded / 전무 stale.

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_store.py
import datetime as dt

import pytest

from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_store import ThesisStore, freshness
from tests.test_thesis_contracts import make_rev


def test_append_dedup_and_as_of(tmp_path):
    ts = ThesisStore(tmp_path)
    r1 = make_rev(valid_from="2026-07-20T00:00:00",
                  revision_id="hbm-tightness@2026-07-20T00:00:00")
    assert ts.append(r1) is True
    assert ts.append(make_rev(valid_from="2026-07-21T00:00:00",
                              revision_id="hbm-tightness@2026-07-21T00:00:00")) is False  # 실질 동일 → 생략
    r3 = make_rev(valid_from="2026-07-21T01:00:00",
                  revision_id="hbm-tightness@2026-07-21T01:00:00",
                  assessment="mixed")
    assert ts.append(r3) is True
    with pytest.raises(ValueError):
        ts.append(r3)                                              # 중복 revision_id
    assert ts.latest("hbm-tightness").assessment == "mixed"
    assert ts.latest_as_of("hbm-tightness", "2026-07-20").revision_id == r1.revision_id  # 날짜형
    assert ts.latest_as_of("hbm-tightness", "2026-07-21T00:30:00").revision_id == r1.revision_id


def _store_with(tmp_path, obs):
    s = SectorStore(tmp_path / "s")
    s.append_observations(obs)
    return s


def test_freshness_fresh_degraded_stale_and_min_count(tmp_path):
    now = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)
    rev = make_rev(required_inputs=[
        {"metric": "memory_price_usd_per_gb", "max_age_days": 45, "min_count": 2,
         "meta_filter": {"category": "DRAM"}},
        {"metric": "kr_semi_export", "max_age_days": 30, "min_count": 1}])
    obs_full = [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta={"category": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=0.09,
                          unit="USD/GB", meta={"category": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.2,
                          unit="USD/GB", meta={"category": "NAND"}),   # 그룹 밖 — 미계수
        MetricObservation(metric="kr_semi_export", ts="2026-07-10", value=1.0, unit="k_usd")]
    assert freshness(rev, _store_with(tmp_path, obs_full), now=now) == "fresh"
    # min_count 미달(DRAM 1건) → degraded
    assert freshness(rev, _store_with(tmp_path / "b", obs_full[1:]), now=now) == "degraded"
    # 전무 → stale
    assert freshness(rev, _store_with(tmp_path / "c", []), now=now) == "stale"
    # 미래 ts는 무효 (fail-closed)
    future = [MetricObservation(metric="kr_semi_export", ts="2027-01-01", value=1.0, unit="k_usd")]
    rev2 = make_rev(required_inputs=[{"metric": "kr_semi_export", "max_age_days": 30}])
    assert freshness(rev2, _store_with(tmp_path / "d", future), now=now) == "stale"
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (flock은 append 내부 `with open(...,"a") as f: fcntl.flock(f, LOCK_EX)`; 실질 동일 비교는 정규화 dump 비교)
- [ ] **Step 5: Commit** — `'feat(sector): ThesisStore — append-only·flock·실질동일 생략·freshness 파생 (2부 T2)'`

---

### Task 3: 구조 guard

**Files:**
- Create: `engine/sector/thesis_guard.py`
- Test: `engine/tests/test_thesis_guard.py`

**Interfaces:**
- `publisher_id(url: str) -> str` — **오프라인 PSL 기반**(`publicsuffix2` 패키지 — `engine/requirements.txt`에 추가, T3에 포함) registrable domain. **IP 주소·단일 라벨(localhost)·public-suffix-only host는 `""` 반환**(무효 — r2-B4). 빈 host → `""`
- `quantity_literal(text) -> list[str]` — acceptance matrix(Global Constraints) 충족 정규식
- `eligible_card(card) -> bool` / `quote_valid(card, quote) -> bool`(quote.strip() 비어있으면 False)
- `build_evidence(card: SectorCard, quote: str) -> Evidence | None` — **카드에서 재파생**: canonical_url=card.url(http(s) 아니면 None), publisher_id=publisher_id(card.url)(빈 값이면 None), quote_valid 실패 None (B4 — LLM/입력 publisher 불신의 단일 진입점)
- `independent_publishers(evs, cards) -> int` — quote 정규화(공백·문장부호 제거) SequenceMatcher ≥0.8 쌍은 동일 주체 병합
- `filter_statements(stmts, cards) -> tuple[list[Statement], list[str]]` — supporting 각각을 build_evidence로 재구성(실존·eligible 포함), 잔여 ≥2 & independent ≥2 & 수량 literal 0
- `resolve_key_metrics(names: list[str], seed: dict, store) -> tuple[list[KeyMetric], list[str]]` — seed required_inputs/meta_filter 그룹의 최신 관측(그룹 키는 `metrics_registry._GROUP_KEYS` 관례). **source = 관측의 `obs.source`**(r2-B5 — T1에서 `MetricObservation.source: str = ""` 필드 추가·하위호환, openapi의 해당 스키마도 갱신), 빈 값이면 `METRIC_REGISTRY[metric]["desc"]` 폴백(주석: provenance 부재 관측의 표시용). **대표 수집기 2곳(kr customs·hyperscaler capex — collectors에서 실파일 확인)이 신규 관측부터 source를 채우도록 T3에서 수정**. 미존재 이름 dropped

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_guard.py
from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore
from sector.thesis_contracts import Statement
from sector.thesis_guard import (build_evidence, eligible_card, filter_statements,
                                 independent_publishers, publisher_id, quantity_literal,
                                 quote_valid, resolve_key_metrics)


def _card(cid, url, quote="본문 인용문 원문", grade="A", signal=""):
    return SectorCard(id=cid, ts="2026-07-20T00:00:00", axis="A", direction="pos",
                      magnitude=2, source_grade=grade, title=f"제목-{cid}",
                      interpreted_signal=signal, raw_quote=quote, url=url,
                      entities=["SK_HYNIX"])


def test_publisher_id_psl():
    assert publisher_id("https://news.fnnews.com/a/1") == "fnnews.com"
    assert publisher_id("https://www.chosun.co.kr/x") == "chosun.co.kr"
    assert publisher_id("not-a-url") == ""
    assert publisher_id("https://localhost/x") == ""          # 단일 라벨 (r2-B4)
    assert publisher_id("https://127.0.0.1/x") == ""          # IP
    assert publisher_id("https://co.kr/x") == ""              # suffix-only


def test_quantity_acceptance_matrix():                       # B7 — 고정 matrix
    for allowed in ("gpt-5.5 모델", "HBM3E", "DDR5 수요", "H100 클러스터"):
        assert not quantity_literal(allowed), allowed
    for banned in ("12% 상승", "12퍼센트", "$12", "₩12", "USD12", "12 USD",
                   "12달러", "12조 규모", "3bp", "수치는 12 였다"):
        assert quantity_literal(banned), banned


def test_build_evidence_rederives_and_rejects():             # B4
    c = _card("c1", "https://news.a.com/1", quote="HBM 수요가 강하다는 보도 원문")
    ev = build_evidence(c, "HBM 수요가 강하다")
    assert ev and ev.publisher_id == "a.com" and ev.canonical_url == c.url
    assert build_evidence(c, "  ") is None                   # 빈 quote
    assert build_evidence(c, "없는 문장") is None
    assert build_evidence(_card("c2", "javascript:void(0)"), "본문") is None
    assert not eligible_card(_card("c3", "https://a.com", signal="공시 원문 확인 필요 (자동 보존)"))
    assert not eligible_card(_card("c4", "https://a.com", grade="D"))
    assert quote_valid(c, "제목-c1")                          # title도 허용


def test_independence_and_filter():
    cards = {"c1": _card("c1", "https://a.com/1", quote="HBM 수요가 공급을 크게 앞선다 분석"),
             "c2": _card("c2", "https://b.com/2", quote="HBM 수요가 공급을 크게 앞선다 분석"),
             "c3": _card("c3", "https://c.com/3", quote="고객 인증 확대라는 별개 근거")}
    st_reprint = Statement(statement_id="s1", text="수요가 공급을 앞선다", supporting=[
        build_evidence(cards["c1"], "HBM 수요가 공급을 크게 앞선다"),
        build_evidence(cards["c2"], "HBM 수요가 공급을 크게 앞선다")])
    st_ok = Statement(statement_id="s2", text="수요가 공급을 앞선다", supporting=[
        build_evidence(cards["c1"], "HBM 수요가 공급을 크게 앞선다"),
        build_evidence(cards["c3"], "고객 인증 확대라는 별개 근거")])
    assert independent_publishers(st_reprint.supporting, cards) == 1
    kept, dropped = filter_statements([st_reprint, st_ok], cards)
    assert [s.statement_id for s in kept] == ["s2"] and dropped


def test_resolve_key_metrics_group_and_source(tmp_path):     # B5
    store = SectorStore(tmp_path / "s")
    store.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.09,
                          unit="USD/GB", meta={"category": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.30,
                          unit="USD/GB", meta={"category": "NAND"})])
    seed = {"required_inputs": [{"metric": "memory_price_usd_per_gb", "max_age_days": 45,
                                 "min_count": 1, "meta_filter": {"category": "DRAM"}}]}
    kms, dropped = resolve_key_metrics(["memory_price_usd_per_gb", "ghost"], seed, store)
    assert len(kms) == 1 and kms[0].value == 0.09            # DRAM 그룹 고정 — NAND 아님
    assert kms[0].source and dropped == ["ghost"]
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** / **Step 5: Commit** `'feat(sector): thesis 구조 guard — 재파생 evidence·독립성·수량 matrix·그룹 역참조 (2부 T3)'`

---

### Task 4: fail-closed 교차 verifier

**Files:**
- Create: `engine/sector/thesis_verify.py`
- Modify: `engine/providers.py` — `"thesis_verifier": [("openai", settings.model_gpt_mini, "low")]` (`"audit"` 아래)
- Test: `engine/tests/test_thesis_verify.py`

**Interfaces:**
- `class VerificationFailed(Exception)` — 예외·invalid·판정 누락/중복/미지 (statement_id, card_id) 발생 시 (B1: 호출측이 revision 전체 skip)
- `async verify_statements(stmts, seed_claim: str, role) -> tuple[list[Statement], dict[str, bool], list[str]]`:
  - structured output `_VerifyOut{rows: [{statement_id, card_id, supported: bool, why}], relations: [{statement_id, relevant: bool, direction: Literal["supports","contradicts","neutral"]}]}` — 근거당 정확 1행·statement당 정확 1 relation을 코드 검증(불일치 → VerificationFailed)
  - supported=False 근거 제거. relevant=False statement 제거. **direction=="neutral" statement도 드롭** (r2-B2)
  - 반환: (잔여 statements, {statement_id: Literal["supports","contradicts"]}, 사유 목록) — 방향을 **Literal 그대로** 반환 (bool 붕괴 금지). **assessment 집계는 호출측 코드**: 전부 supports→strengthening, 전부 contradicts→weakening, 혼재→mixed

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_verify.py
import asyncio

import pytest

from sector.thesis_contracts import Evidence, Statement
from sector.thesis_verify import VerificationFailed, verify_statements


def _st(sid, quotes):
    sup = [Evidence(card_id=f"c{sid}{i}", canonical_url=f"https://p{i}.com/1",
                    publisher_id=f"p{i}.com", quote=q) for i, q in enumerate(quotes)]
    return Statement(statement_id=sid, text="수요가 강하다", supporting=sup)


class _Role:
    model = "fake-gpt"
    def __init__(self, rows, relations): self.rows, self.relations = rows, relations
    async def run(self, prompt, instructions="", response_format=None, **kw):
        return response_format.model_validate({"rows": self.rows, "relations": self.relations})


def test_reject_and_relevance_and_direction():
    st = _st("s1", ["인용A", "인용B", "인용C"])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "c s10".replace(" ", ""), "supported": True, "why": ""},
                       {"statement_id": "s1", "card_id": "cs11", "supported": True, "why": ""},
                       {"statement_id": "s1", "card_id": "cs12", "supported": False, "why": "무관"}],
                 relations=[{"statement_id": "s1", "relevant": True, "direction": "supports"}])
    kept, directions, reasons = asyncio.run(verify_statements([st], "HBM 타이트", role))
    assert len(kept) == 1 and len(kept[0].supporting) == 2
    assert directions == {"s1": "supports"} and reasons     # 방향 Literal 그대로 (r2-B2)


def test_missing_or_duplicate_verdict_fails_closed():       # B1
    st = _st("s1", ["인용A", "인용B"])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "cs10", "supported": True, "why": ""}],
                 relations=[{"statement_id": "s1", "relevant": True, "direction": "supports"}])
    with pytest.raises(VerificationFailed):
        asyncio.run(verify_statements([st], "claim", role))  # cs11 판정 누락


def test_irrelevant_statement_dropped():                    # B2
    st = _st("s1", ["인용A", "인용B"])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "cs10", "supported": True, "why": ""},
                       {"statement_id": "s1", "card_id": "cs11", "supported": True, "why": ""}],
                 relations=[{"statement_id": "s1", "relevant": False, "direction": "neutral"}])
    kept, directions, _ = asyncio.run(verify_statements([st], "claim", role))
    assert kept == [] and directions == {}


def test_neutral_direction_dropped():                       # r2-B2
    st = _st("s1", ["인용A", "인용B"])
    role = _Role(rows=[{"statement_id": "s1", "card_id": "cs10", "supported": True, "why": ""},
                       {"statement_id": "s1", "card_id": "cs11", "supported": True, "why": ""}],
                 relations=[{"statement_id": "s1", "relevant": True, "direction": "neutral"}])
    kept, directions, _ = asyncio.run(verify_statements([st], "claim", role))
    assert kept == [] and directions == {}                   # neutral은 저장 불가
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (LLM 예외도 VerificationFailed로 래핑) / **Step 5: Commit** `'feat(sector): thesis 교차 verifier — fail-closed·관련성·방향 판정 (2부 T4)'`

---

### Task 5: updater 파이프

**Files:**
- Create: `engine/sector/thesis_update.py`
- Modify: `engine/providers.py` — `"thesis_updater": [("anthropic", settings.model_claude_sonnet, "low")]`
- Test: `engine/tests/test_thesis_update.py`

**Interfaces:**
- `async update_thesis(seed, store, tstore, updater_role, verifier_role, now: datetime) -> ThesisRevision | None` — 파이프 (순서 계약):
  1. **required_inputs 게이트 — LLM 호출 전** (freshness 로직 재사용; fresh 아니면 None+사유)
  2. 입력 조립: `now` 기준 최근 14일 카드(selectors entities/segments/event_types 필터·eligible만), 카드당 id·title·raw_quote[:200]·url + seed metrics 요약. **제공한 전체 card_id·observation_id를 InputSnapshot으로 기록** (B8)
  3. 제안 LLM `_ProposalOut{statements: [{text, evidence: [{card_id, quote}]}], key_metric_names: list[str]}` — **assessment 없음** (B2)
  4. build_evidence로 Evidence 재구성 → `filter_statements` → `verify_statements`(VerificationFailed → None+사유) → **filter_statements 재실행** (B3 — verifier 제거 후 독립성 재검) → `resolve_key_metrics`
  5. 잔여 statements 0 → None. assessment = 방향 집계 코드
  6. ThesisRevision 조립·`tstore.append` (False면 "unchanged")
- `async update_all(store, tstore=None, only=None, role_factory=None) -> dict[str, str]` — role_factory 기본 `lambda name: Role(name)`으로 `thesis_updater`·`thesis_verifier` 생성(테스트 주입 — B11 배선 검증), 시드별 격리
- **CLI entrypoint** (r2-N2): `if __name__ == "__main__":` — argparse(`--only`), `asyncio.run(update_all(_get_store(), only=...))` 후 `{id: status}` 출력·status에 error 있으면 exit 1. 테스트: `python -m sector.thesis_update --only hbm-tightness`를 subprocess 실행이 아닌 **main() 함수 직접 호출**로 검증(모듈에 `main(argv) -> int` 분리) — updated/unchanged/skipped 문자열과 revision 존재 일치 assertion

- [ ] **Step 1: 실패하는 테스트** (spy·sentinel로 실순서 검증 — B11)

```python
# engine/tests/test_thesis_update.py
import asyncio
import datetime as dt

from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore
from sector.thesis_store import ThesisStore
from sector.thesis_update import update_all, update_thesis

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)


def _seed():
    return {"id": "hbm-tightness", "claim": "HBM 타이트", "axis": "A", "priority": 1,
            "selectors": {"entities": ["SK_HYNIX"], "metrics": ["memory_price_usd_per_gb"],
                          "segments": ["hbm"], "event_types": ["supply_signal"]},
            "required_inputs": [{"metric": "memory_price_usd_per_gb", "max_age_days": 3650,
                                 "min_count": 1, "meta_filter": {"category": "DRAM"}}]}


def _env(tmp_path):
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1, unit="USD/GB",
        meta={"category": "DRAM"})])
    store.append_cards([
        SectorCard(id="c1", ts="2026-07-20T00:00:00", axis="A", direction="pos",
                   magnitude=2, source_grade="A", title="t1", interpreted_signal="",
                   raw_quote="HBM 수요가 공급을 앞선다는 분석 기사", url="https://a.com/1",
                   entities=["SK_HYNIX"]),
        SectorCard(id="c2", ts="2026-07-20T00:00:00", axis="A", direction="pos",
                   magnitude=2, source_grade="A", title="t2", interpreted_signal="",
                   raw_quote="고객 인증 확대 보도라는 별개 근거", url="https://b.com/2",
                   entities=["SK_HYNIX"])])
    return store, ThesisStore(tmp_path)


class _Updater:
    model = "fake-sonnet"
    def __init__(self, proposal): self.proposal, self.calls = proposal, 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        return response_format.model_validate(self.proposal)


class _Verifier:
    model = "fake-gpt"
    def __init__(self): self.calls = 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        import re
        pairs = re.findall(r'"statement_id":\s*"(s\d+)".*?"card_id":\s*"(c\d+)"', prompt, re.S) or []
        # 프롬프트에서 (sid, card) 전부에 supported=True — 구현이 넣는 형식에 맞춰 조정 가능
        sids = set(re.findall(r'"statement_id":\s*"(s\d+)"', prompt))
        cids = re.findall(r'"card_id":\s*"(c\d+)"', prompt)
        rows = [{"statement_id": s, "card_id": c, "supported": True, "why": ""}
                for s in sids for c in set(cids)]
        rels = [{"statement_id": s, "relevant": True, "direction": "supports"} for s in sids]
        return response_format.model_validate({"rows": rows, "relations": rels})


_GOOD = {"statements": [{"text": "HBM 수요가 공급을 앞선다",
                         "evidence": [{"card_id": "c1", "quote": "HBM 수요가 공급을 앞선다"},
                                      {"card_id": "c2", "quote": "고객 인증 확대 보도"}]}],
         "key_metric_names": ["memory_price_usd_per_gb"]}


def test_full_pipe_creates_revision_with_verifier_called(tmp_path):
    store, tstore = _env(tmp_path)
    up, ver = _Updater(_GOOD), _Verifier()
    rev = asyncio.run(update_thesis(_seed(), store, tstore, up, ver, now=NOW))
    assert rev is not None and ver.calls >= 1               # B11 — verifier 실호출
    assert rev.assessment == "strengthening"                 # 방향 코드 집계
    assert rev.key_metrics[0].value == 0.1
    assert set(rev.input_snapshot.card_ids) == {"c1", "c2"}  # 제공 전체 (정확 집합)
    from sector.thesis_contracts import observation_id as _oid
    assert set(rev.input_snapshot.metric_observation_ids) == {
        _oid("memory_price_usd_per_gb", "2026-07", {"category": "DRAM"})}  # r2-B8


def test_required_gate_blocks_before_llm(tmp_path):          # B11 — sentinel
    store, tstore = _env(tmp_path)
    seed = _seed(); seed["required_inputs"][0]["metric"] = "kr_semi_export"  # 관측 없음
    class _Boom:
        model = "boom"
        async def run(self, *a, **k): raise AssertionError("LLM called before gate")
    rev = asyncio.run(update_thesis(seed, store, tstore, _Boom(), _Boom(), now=NOW))
    assert rev is None


def test_update_all_wires_roles_and_isolates(tmp_path):      # B11 — 배선·격리
    store, _ = _env(tmp_path)
    created = []
    def factory(name):
        created.append(name)
        return _Updater(_GOOD) if name == "thesis_updater" else _Verifier()
    res = asyncio.run(update_all(store, tstore=ThesisStore(tmp_path),
                                 only=["hbm-tightness"], role_factory=factory))
    assert set(created) == {"thesis_updater", "thesis_verifier"}
    assert res["hbm-tightness"] == "updated"
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (verifier 프롬프트에 (statement_id, card_id, quote) 목록을 JSON으로 넣는 형식을 fake와 일치시켜라 — fake가 프롬프트 파싱에 실패하면 형식을 fake 기준으로 맞춘다) / **Step 5: Commit** `'feat(sector): thesis updater 파이프 — pre-LLM 게이트·재가드·방향 집계·role 배선 (2부 T5)'`

---

### Task 6: runner 훅 + 플래그 (never-block 양방향)

**Files:**
- Modify: `engine/app/settings.py` (`thesis_update_enabled: bool = True`), `engine/sector/runner.py` (write_status **이후** 훅)
- Test: `engine/tests/test_thesis_runner_hook.py`

훅 코드 (collect_all 말미, `store.write_status(results)` 다음):

```python
    if getattr(settings, "thesis_update_enabled", True):
        try:
            from sector.thesis_update import update_all
            await update_all(store)
        except Exception as exc:  # noqa: BLE001 — thesis 실패가 수집 결과를 못 건드림
            results.append(CollectorResult(name="thesis_update", kind="metric",
                                           status="error", detail=str(exc)[:200]))
    return results
```

- [ ] **Step 1: 실패하는 테스트** — monkeypatch로 update_all을 ①정상 ②예외 ③플래그 off 3케이스: collect_all 반환·write_status가 영향받지 않고, 예외 시 results에 error 항목 추가, off 시 미호출(spy). 수집기 전멸(빈 registry monkeypatch)에도 update_all 호출됨.
- [ ] **Step 2~4: 실패→구현→통과+회귀** / **Step 5: Commit** `'feat(sector): collect_all thesis 훅 — never-block 양방향·플래그 (2부 T6)'`

---

### Task 7: cmd_capture 실배선 + API route

**Files:**
- Modify: `engine/evals/bundle.py` (`capture_bundle(..., thesis_store=None)` + `EvalBundle.theses()`), `engine/evals/build_chain_cases.py` (cmd_capture가 **자동으로** store root의 ThesisStore 사용 — theses.jsonl 존재 시 포함, `--no-thesis` 옵트아웃), `engine/sector/api.py` (GET /v1/sector/theses — T1 계약 구현, latest_all+freshness)
- Test: `engine/tests/test_thesis_api_bundle.py`

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_api_bundle.py
import json

from evals.bundle import EvalBundle, capture_bundle
from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_store import ThesisStore
from tests.test_thesis_contracts import make_rev


def test_capture_snapshot_date_boundary_and_backcompat(tmp_path):
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd")])
    tstore = ThesisStore(tmp_path / "s")                     # store root 동일 위치 (B9)
    tstore.append(make_rev(valid_from="2026-07-20T09:00:00",
                           revision_id="hbm-tightness@2026-07-20T09:00:00"))
    tstore.append(make_rev(valid_from="2026-07-21T09:00:00", assessment="mixed",
                           revision_id="hbm-tightness@2026-07-21T09:00:00"))
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-20",
                         availability="unproven", ra_docs=[], prices={}, macro={},
                         thesis_store=tstore)
    b = EvalBundle(out)
    assert [t["revision_id"] for t in b.theses()] == \
        ["hbm-tightness@2026-07-20T09:00:00"]                # 당일 09시 revision 포함 (날짜 비교)
    m = json.loads((out / "manifest.json").read_text())
    assert m["thesis_revisions"] == ["hbm-tightness@2026-07-20T09:00:00"]
    assert b.verify_hash()
    # 하위호환: thesis 없는 기존 bundle
    out2 = capture_bundle(store, tmp_path / "b2", as_of="2026-07-20",
                          availability="unproven", ra_docs=[], prices={}, macro={})
    assert EvalBundle(out2).theses() == []


def test_cmd_capture_auto_wires_thesis(tmp_path, monkeypatch):   # B9 — 운영 경로
    import evals.build_chain_cases as bcc
    store = SectorStore(tmp_path / "s")
    store.append_observations([MetricObservation(
        metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd")])
    ThesisStore(tmp_path / "s").append(make_rev(
        valid_from="2026-07-19T00:00:00",
        revision_id="hbm-tightness@2026-07-19T00:00:00"))
    monkeypatch.setattr(bcc, "_get_store", lambda: store)
    monkeypatch.setattr(bcc, "_HERE", tmp_path)              # bundles 출력 위치
    import argparse, json as _json
    ra = tmp_path / "ra.json"; ra.write_text("[]")
    pj = tmp_path / "p.json"; pj.write_text('{"quotes": []}')
    mj = tmp_path / "m.json"; mj.write_text("{}")
    args = argparse.Namespace(case="cj-t", as_of="2026-07-20", availability="unproven",
                              ra_docs=str(ra), prices=str(pj), macro=str(mj),
                              auto_live=False, allow_empty_ra="", no_thesis=False)
    bcc.cmd_capture(args)
    b = EvalBundle(tmp_path / "bundles" / "cj-t")
    assert len(b.theses()) == 1
```

(API route: sector/api.py 기존 라우트 테스트 관례 확인 후 1건 — latest_all 비어있으면 `{"theses": []}`, revision 있으면 freshness 필드 포함. `npm run test:contract` 통과 확인 스텝 포함.)

- [ ] **Step 2~4: 실패→구현→통과** + `cd /home/ryze_yn/attn-viewer && npm run check:openapi && npm run test:contract` / **Step 5: Commit** `'feat(sector): theses API 구현 + capture thesis 자동 배선·날짜 경계 (2부 T7)'`

---

### Task 8: 전체 회귀

- [ ] `.venv/bin/python -m pytest tests/ -q` (450+신규 전부) / `cd /home/ryze_yn/attn-viewer && npm run check:openapi && npm run test:contract && npm test` — **fallback·`|| true` 금지, exit code가 게이트** (r2-N1). 전부 green을 보고서에 기록. 실패 시 해당 태스크로 회귀.

### Task 9: codex 2부 리뷰 → 승인 후 배포·첫 live append

- [ ] **Step 1: codex 리뷰** — thesis_* 6파일·훅·API·bundle 배선. 관점: 가드레일 우회·fail-closed 완전성·append-only·무접촉. 블로커 반영→승인 왕복 (docs/memory-chain-review-p2-*.md).
- [ ] **Step 2 (승인 후에만):** `pm2 restart attn-engine` → `.venv/bin/python -m sector.thesis_update` 첫 실행 → 산출 revision **코드 재감사 스크립트**(statement별 supporting≥2·독립≥2·수량 0·quote 실존 재검증) 결과 기록 → GET /v1/sector/theses 스모크.
- [ ] **Step 3:** workflow-review.html §2 카드 추가+스크린샷, 렛저 기록. (B12 — 순서 고정)

---

## Self-Review 기록 (v2)

- B1 verifier fail-closed(T4 VerificationFailed·정확 1판정) / B2 관련성·방향 판정+assessment 코드 집계(T4·T5) / B3 post-verifier 재filter(T5 파이프 4) / B4 build_evidence 재파생·빈값 거부(T1 validator+T3) / B5 meta_filter 그룹·registry source·튜플 시그니처(T1·T3) / B6 canonical 어휘·실어휘 검증 테스트(T1) / B7 acceptance matrix(T3) / B8 typed 계약·equality validator·snapshot 전체 집합(T1·T5) / B9 cmd_capture 자동 배선·날짜 경계·하위호환(T7) / B10 OpenAPI 선행+contract 테스트(T1·T7·T8) / B11 spy·sentinel·factory·양방향 never-block·degraded/min_count(T2·T5·T6) / B12 라이브 append는 codex 승인 후(T9)
- 권고 반영: 월말 해석 명시+미래 fail-closed(T2), contradicting 미사용 명시(전역 제약), flock+실질 동일 생략(T2), 무접촉 문구는 "2부 주입 없음·P3 게이트"로 한정(전역 제약)
