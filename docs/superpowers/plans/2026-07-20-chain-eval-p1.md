# chain_judgment eval (스펙 1부) Implementation Plan (v4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

v2 — codex 계획 r1 블로커 12건 반영. v3 — r2 잔존 10건+신규 3건 반영
(docs/memory-chain-review-p1-plan-r2_codex.md): manifest 포함 hash·재귀 URL+근거 토큰
위반 검출·auto-live 캡처·실계약 fixture·봉인 version-hash 1:1 바인딩·pilot 제한·
원자적 experiment·holdout 스키마 게이트·per-case 회귀 코호트.

**Goal:** 사건 기반 chain_judgment eval(frozen bundle + 교차 저지 + calibration)을 구축하고 베이스라인을 측정한다.

**Architecture:** 케이스별 frozen bundle로 파이프라인을 돌리고(라이브 검색 차단 + knowledge_cutoff 강제) gpt-5.5 저지가 루브릭 5축 + 주장 커버리지를 채점한다. 저지는 봉인 metamorphic 셋을 버전당 1회·첫 시도 통과해야 유효. 배포 판정은 proven 전향 케이스만.

**Tech Stack:** Python 3.12 (engine/.venv), pytest, pydantic v2, 기존 Role/CostMeter.

**스펙:** `docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md` (v5) §1부

## Global Constraints

- 저지는 **gpt-5.5 단독** (ROLE_MAP `chain_judge`, anthropic 폴백 금지).
- 봉인 셋: 버전당 1회 평가·첫 시도 통과 필수 — ledger로 강제 (Task 7).
- invalid/타임아웃: 1회 재시도 후 `None` (0점 금지). 축 점수는 [0,1] 밖이면 invalid.
- 회고 케이스 = `unproven` = dev 전용. `--split holdout`은 proven 전용 + ledger 기록.
- bundle: 날짜 불명 문서 fail-closed, content hash 검증, 기존 디렉토리 덮어쓰기 거부.
- `as_of_violation` > 0 또는 must_not hit → **실행기 비정상 종료** (exit 1).
- eval 순차 실행. 기존 golden 경로 불변 + 회귀 비교(Task 7 `--check-regression`).
- 모든 셸 명령 cwd = `/home/ryze_yn/attn-viewer/engine`. git은 항상
  `git -C /home/ryze_yn/attn-viewer …` (pathspec은 `engine/…` 그대로).
- 커밋 메시지 작은따옴표. 엔진 재시작 `pm2 restart attn-engine`만.
- entailed_edge_ratio는 ChainPacket(3부) 전 산출 불가 — 레코드에
  `entailed_edge_ratio: null` + 사유 명기 (스펙 게이트는 3부 후보 평가부터 적용).
- DA의 파라메트릭 지식은 차단 불가 — plan.knowledge_cutoff 강제(지시 수준)로 완화하고
  리포트에 잔여 위험 명시 (스펙 "잔여 위험 명시" 조항).

## File Structure

- `engine/sector/contracts.py`·`store.py` — `ingested_at` (Task 0 수정)
- `engine/evals/bundle.py` — EvalBundle·capture·hash·violation (Task 0/4)
- `engine/evals/build_chain_cases.py` — list/capture/validate CLI (Task 0/8)
- `engine/evals/chain_judge.py` (Task 1) / fixtures + `calibration.py` (Task 2·3)
- `engine/orchestrator.py`, `stages/ra_external.py`, `stages/price_macro.py`,
  `sector/retrieve.py` — bundle 모드 (Task 5)
- `engine/evals/metrics.py` (Task 6) / `run_eval.py` (Task 7)
- `engine/evals/golden_chain.jsonl` + `bundles/` + ledgers (Task 8)
- 테스트: `engine/tests/test_{chain_judge,calibration,eval_bundle,bundle_mode,chain_metrics}.py`

---

### Task 0: ingested_at 스탬프 + 전향 캡처 즉시 가동

**Files:**
- Modify: `engine/sector/contracts.py` (SectorCard·MetricObservation에 필드 추가)
- Modify: `engine/sector/store.py:36` (append_cards), `:81` (append_observations)
- Create: `engine/evals/bundle.py` (capture 부분 — Task 4에서 확장)
- Create: `engine/evals/build_chain_cases.py` (capture 서브커맨드 먼저)
- Create: `engine/evals/golden_baseline.json`
- Test: `engine/tests/test_eval_bundle.py` (capture 부분)

**Interfaces:**
- Produces: `SectorCard.ingested_at: str = ""`, `MetricObservation.ingested_at: str = ""` (기본 "" — 기존 데이터 하위 호환), store가 append 시 UTC ISO 스탬프
- Produces: `capture_bundle(store, out_dir, *, as_of, availability, ra_docs, prices, macro) -> Path` — **out_dir 존재 시 FileExistsError**, proven이면 `as_of == 오늘(UTC)` 강제
- Produces: CLI `python -m evals.build_chain_cases capture --case cj-XX --as-of D --availability proven|unproven --ra-docs F --prices F --macro F` (`F`는 JSON 파일 — 빈 배열/객체도 **명시 파일로** 전달, 인자 생략 불가)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_eval_bundle.py
import json
import time

import pytest

from evals.bundle import capture_bundle
from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore


def _card(cid: str, ts: str) -> SectorCard:
    # direction 허용값은 sector/contracts.py:22 — pos|neg|neutral|mixed
    return SectorCard(id=cid, ts=ts, axis="A", direction="pos", magnitude=2,
                      source_grade="A", title=f"t-{cid}", interpreted_signal="",
                      raw_quote=f"q-{cid}", url=f"https://a.example/{cid}",
                      entities=["SK하이닉스"])


def _seed(tmp_path, n_cards: int = 3) -> SectorStore:
    store = SectorStore(tmp_path / "sector")
    store.append_cards([_card(f"c-{i}", f"2026-07-{i+1:02d}T00:00:00") for i in range(n_cards)])
    store.append_observations([
        MetricObservation(metric="kr_semi_export", ts="2026-07-01", value=1.0, unit="k_usd"),
        MetricObservation(metric="kr_semi_export", ts="2026-07-15", value=2.0, unit="k_usd")])
    return store


def test_store_stamps_ingested_at(tmp_path):
    store = _seed(tmp_path)
    cards = store.read_cards(days=None, limit=100_000)
    assert all(c.ingested_at for c in cards)          # append가 스탬프
    obs = store.read_metric("kr_semi_export")
    assert all(o.ingested_at for o in obs)


def test_capture_refuses_overwrite_and_bad_proven(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b1", as_of="2026-07-02",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    with pytest.raises(FileExistsError):
        capture_bundle(store, tmp_path / "b1", as_of="2026-07-02",
                       availability="unproven", ra_docs=[], prices={}, macro={})
    with pytest.raises(ValueError):                    # 과거 as_of에 proven 금지
        capture_bundle(store, tmp_path / "b2", as_of="2026-07-02",
                       availability="proven", ra_docs=[], prices={}, macro={})
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with pytest.raises(ValueError):                    # r3-B4: 빈 채널 proven은 사유 없인 거부
        capture_bundle(store, tmp_path / "b3", as_of=today,
                       availability="proven", ra_docs=[], prices={}, macro={})
    capture_bundle(store, tmp_path / "b4", as_of=today, availability="proven",
                   ra_docs=[], prices={"quotes": [{"token": "005930.KS", "last": 1.0}]},
                   macro={"kospi": 1.0},
                   empty_reasons={"ra": "회고성 사건 — RA 미수집"})       # 사유 있으면 OK


def test_capture_filters_full_store_not_limit500(tmp_path):
    store = SectorStore(tmp_path / "sector")
    # 600건 적재 — 기본 limit=500 함정 검증 (store.py:53)
    store.append_cards([_card(f"c-{i}", "2026-07-01T00:00:00") for i in range(600)])
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-02",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["card_ids"]) == 600


def test_capture_fail_closed_and_manifest(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(
        store, tmp_path / "b", as_of="2026-07-10", availability="unproven",
        ra_docs=[{"id": "n1", "title": "t", "url": "https://n.example/x",
                  "published_at": "2026-07-09", "snippet": "s"},
                 {"id": "n2", "title": "t", "url": "https://n.example/undated",
                  "snippet": "s"}],
        prices={"quotes": [], "macro": {}}, macro={})
    m = json.loads((out / "manifest.json").read_text())
    assert m["dropped_undated_docs"] == 1
    assert "https://n.example/x" in m["urls"]
    assert "https://n.example/undated" not in m["urls"]
    assert m["content_hash"]                           # hash 존재
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_eval_bundle.py -v`
Expected: FAIL (`ingested_at` 필드 없음 / `evals.bundle` 없음)

- [ ] **Step 3: 구현**

`sector/contracts.py` — SectorCard와 MetricObservation 각각에 필드 1줄 추가:

```python
    ingested_at: str = ""   # 적재 시각 UTC ISO — eval bundle 가용성 증명 (스펙 r3-B4)
```

`sector/store.py` — `append_cards` 루프에서 저장 직전(중복 체크 통과 후). **실제 루프
변수는 `c`(store.py:40), `o`(store.py:96)다 (r2-N1):**

```python
            if not c.ingested_at:
                c.ingested_at = _dt.datetime.now(_dt.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S")
```

`append_observations`에도 동일 패턴 (`o.ingested_at`).

`evals/bundle.py` (capture 부분 — violation 검출은 Task 4):

```python
# engine/evals/bundle.py
"""frozen evidence bundle (스펙 1부). capture는 불변 — 덮어쓰기 거부 + content hash."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def _content_hash(root: Path, manifest: dict) -> str:
    """상대경로+파일 내용 + content_hash 제외 manifest 정규형을 함께 해시 (r2-B3 —
    manifest의 as_of/availability/urls 변조도 hash로 잡는다)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    canon = {k: v for k, v in manifest.items() if k != "content_hash"}
    h.update(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def capture_bundle(store, out_dir: Path | str, *, as_of: str, availability: str,
                   ra_docs: list[dict], prices: dict, macro: dict,
                   empty_reasons: dict[str, str] | None = None) -> Path:
    """proven 불변식은 이 함수가 강제한다 (r3-B4 — CLI·운영 문구가 아니라 코드):
    proven인데 채널이 비면 empty_reasons에 채널별 사유 필수, 없으면 ValueError."""
    out = Path(out_dir)
    empty_reasons = empty_reasons or {}
    if out.exists():
        raise FileExistsError(f"bundle exists — 불변성 위반 금지: {out}")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if availability == "proven":
        if as_of != today:
            raise ValueError(f"proven은 as_of=captured_at({today})만 허용 (스펙 r4-B4)")
        for ch, empty in (("ra", not ra_docs), ("quotes", not prices.get("quotes")),
                          ("macro", not macro)):
            if empty and ch not in empty_reasons:
                raise ValueError(f"proven인데 {ch} 채널이 비어 있음 — 사유 필수 (r3-B4)")
    (out / "metrics").mkdir(parents=True)
    cards = [c for c in store.read_cards(days=None, limit=100_000)
             if c.ts[:10] <= as_of]                     # limit=500 함정 회피 (B4)
    (out / "cards.jsonl").write_text("\n".join(c.model_dump_json() for c in cards))
    metric_names = sorted(p.stem for p in (Path(store.root) / "metrics").glob("*.jsonl"))
    for m in metric_names:
        rows = [o for o in store.read_metric(m, last_n=100_000) if o.ts[:10] <= as_of]
        (out / "metrics" / f"{m}.jsonl").write_text(
            "\n".join(o.model_dump_json() for o in rows))
    dated = [d for d in ra_docs
             if (d.get("published_at") or "")[:10] and d["published_at"][:10] <= as_of]
    (out / "ra_docs.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in dated))
    (out / "prices.json").write_text(json.dumps(prices, ensure_ascii=False))
    (out / "macro.json").write_text(json.dumps(macro, ensure_ascii=False))
    manifest = {"as_of": as_of, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                             time.gmtime()),
                "availability": availability, "card_ids": [c.id for c in cards],
                "urls": sorted({c.url for c in cards if c.url}
                               | {d["url"] for d in dated if d.get("url")}),
                "metric_names": metric_names, "thesis_revisions": [],  # 2부에서 채움
                "news_ids": [d["id"] for d in dated if d.get("id")],
                "quote_symbols": [q.get("token") for q in prices.get("quotes", [])
                                  if q.get("token")],
                "macro_keys": sorted(macro.keys()),
                "empty_channel_reasons": empty_reasons,   # proven 검증용 (r3-B4)
                "dropped_undated_docs": len(ra_docs) - len(dated)}
    manifest["content_hash"] = _content_hash(out, manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return out
```

`evals/build_chain_cases.py` — capture 서브커맨드 (`--ra-docs/--prices/--macro`는 필수
파일 인자 — 빈 컬렉션도 명시 파일로):

```python
# engine/evals/build_chain_cases.py
"""chain eval 케이스 도구 — capture(전향 즉시 가동)/list/validate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.bundle import capture_bundle
from sector.api import _get_store

_HERE = Path(__file__).parent


def cmd_capture(args) -> None:
    out = capture_bundle(
        _get_store(), _HERE / "bundles" / args.case,
        as_of=args.as_of, availability=args.availability,
        ra_docs=json.loads(Path(args.ra_docs).read_text()),
        prices=json.loads(Path(args.prices).read_text()),
        macro=json.loads(Path(args.macro).read_text()))
    print(f"captured: {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("capture")
    p.add_argument("--case", required=True)
    p.add_argument("--as-of", dest="as_of", required=True)
    p.add_argument("--availability", required=True, choices=["proven", "unproven"])
    p.add_argument("--ra-docs", dest="ra_docs", default="")
    p.add_argument("--prices", default="")
    p.add_argument("--macro", default="")
    p.add_argument("--auto-live", action="store_true",
                   help="quotes·macro를 yahoo/collect_macro로 자동 수집 (proven 필수)")
    p.add_argument("--allow-empty-ra", default="",
                   help="RA 빈 채널 사유 — capture_bundle empty_reasons['ra']로 전달")
    args = ap.parse_args()
    {"capture": cmd_capture}[args.cmd](args)
    # cmd_capture 배선: --auto-live면 quotes/macro 자동 수집 결과를 prices·macro로,
    # --allow-empty-ra면 empty_reasons={"ra": 사유}. proven인데 --auto-live도
    # --prices/--macro 파일도 없으면 capture_bundle이 ValueError로 거부 (r3-B4)


if __name__ == "__main__":
    main()
```

`evals/golden_baseline.json` — 기존 golden 회귀 기준. **per-case 코호트** (r2-B12):
`engine/evals/out/report-20260714-211007.jsonl`에서 10개 케이스의 id·verified_ratio·
keyword_ok를 추출해 저장:

```json
{"report": "report-20260714-211007", "tolerance": 0.15,
 "cases": {"sj-01": {"verified_ratio": 0.85, "keyword_ok": true},
           "...": "jsonl에서 실값 추출 — 10개 전부"}}
```

(작성 시 jsonl을 읽어 실값으로 채운다 — 예시값 복사 금지.)

- [ ] **Step 4: 통과 확인 + 배포(스탬프 가동)**

Run: `.venv/bin/python -m pytest tests/test_eval_bundle.py tests/ -v`
Expected: 신규 4건 PASS + 기존 전부 PASS
Run: `pm2 restart attn-engine` — 이후 수집분부터 ingested_at 스탬프 시작 (전향 캡처 전제)

- [ ] **Step 5: 전향 케이스 축적 시작 (운영 절차 문서화 포함)**

오늘부터 유의미한 사건(수집 카드 magnitude 3, 또는 실적·발표일)마다 **auto-live 캡처**
(r2-B4 — proven bundle에 실제 증거 자동 수집, 빈 채널은 사유 필수):

```bash
.venv/bin/python -m evals.build_chain_cases capture --case cj-p$(date -u +%m%d) \
  --as-of $(date -u +%F) --availability proven --auto-live \
  --allow-empty-ra '전향 회고 시점 RA 미수집 — 섹터 카드로 충분'
```

`--auto-live`: quotes는 `tools.price.yahoo.quote()`로 기본 티커셋(005930.KS·000660.KS·
MU·NVDA·^KS11·KRW=X)을, macro는 `stages.price_macro`의 macro 수집 함수를 그대로 호출해
채운다 (결정적, LLM 없음). RA 문서는 `--ra-docs` 파일 또는 `--allow-empty-ra "<사유>"`
중 하나 필수 — 사유는 manifest에 기록. `--auto-live` 없이 proven 캡처는 거부(exit 1).
절차를 `engine/evals/README-chain.md`에 기록 (holdout 10개 확보가 4부 배포 전제).

- [ ] **Step 6: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/sector/contracts.py engine/sector/store.py engine/evals/bundle.py engine/evals/build_chain_cases.py engine/evals/golden_baseline.json engine/tests/test_eval_bundle.py engine/evals/README-chain.md
git -C /home/ryze_yn/attn-viewer commit -m 'feat(eval): ingested_at 스탬프 + 불변 bundle capture + 전향 케이스 가동 (1부 Task 0)'
```

---

### Task 1: chain_judge — 저지 계약·반복 채점

**Files:**
- Create: `engine/evals/chain_judge.py`
- Modify: `engine/providers.py` (ROLE_MAP `"audit"` 아래 1줄)
- Test: `engine/tests/test_chain_judge.py`

**Interfaces:**
- Produces: `AXES`, `ChainAxisScore(score: float|None ∈[0,1], reason, matched, missing)`
  (범위 밖 → ValidationError → invalid 처리), `ChainJudgeResult(case_id, axes, raws: list[str], judge_model, judge_prompt_version)`, `merge_repeats(a, b, tie)`, `judge_case(case_id, answer_md, rubric, bundle_text, role) -> ChainJudgeResult|None`, `judge_claim_coverage(case_id, answer_md, bundle_text, role) -> float|None` (uncovered_claim_ratio), `JUDGE_PROMPT_VERSION="cj-v1"`
- verdict 축 정의(중요 — 봉인 flip_verdict의 전제): "방향 판단을 명시하고 **그 판단이 제시된 근거와 정합**하는가" — 근거와 모순된 결론은 0.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_chain_judge.py
import pytest
from pydantic import ValidationError

from evals.chain_judge import AXES, ChainAxisScore, ChainJudgeResult, merge_repeats


def _res(scores: dict) -> ChainJudgeResult:
    axes = {a: ChainAxisScore(score=scores.get(a), reason="r") for a in AXES}
    return ChainJudgeResult(case_id="cj-01", axes=axes, raws=["{}"],
                            judge_model="gpt-5.5", judge_prompt_version="cj-v1")


def test_axis_score_range_enforced():
    with pytest.raises(ValidationError):
        ChainAxisScore(score=2.0, reason="")          # B9: [0,1] 강제
    with pytest.raises(ValidationError):
        ChainAxisScore(score=-0.1, reason="")


def test_merge_repeats_agree_and_majority():
    a = _res({ax: 1.0 for ax in AXES})
    b = _res({**{ax: 1.0 for ax in AXES}, "mechanism": 0.0})
    tie = _res({**{ax: 1.0 for ax in AXES}, "mechanism": 0.0})
    m = merge_repeats(a, b, tie=tie)
    assert m.axes["mechanism"].score == 0.0            # 다수결 b+tie
    assert m.axes["state_link"].score == 1.0


def test_merge_repeats_null_or_no_majority_invalidates():
    a = _res({**{ax: 1.0 for ax in AXES}, "evidence": 0.2})
    b = _res({**{ax: 1.0 for ax in AXES}, "evidence": 0.8})
    tie = _res({**{ax: 1.0 for ax in AXES}, "evidence": 0.5})  # 3자 전부 다름
    m = merge_repeats(a, b, tie=tie)
    assert m.axes["evidence"].score is None
    m2 = merge_repeats(_res({ax: None for ax in AXES}), a, tie=None)
    assert all(m2.axes[ax].score is None for ax in AXES)


def test_result_keeps_all_raws():                      # 권고1: 감사 가능성
    r = _res({ax: 1.0 for ax in AXES})
    assert isinstance(r.raws, list)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_chain_judge.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 구현**

```python
# engine/evals/chain_judge.py
"""chain_judgment 저지 — gpt-5.5 교차 채점 (스펙 1부).

verdict 축 = 방향 명시 + 근거 정합 (모순 결론 0점 — 봉인 flip_verdict 전제).
claim coverage = 답변의 사실·인과 주장 중 bundle 근거 없는 비율 (r3-B7).
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

AXES = ("mechanism", "state_link", "verdict", "evidence", "countercase")
JUDGE_PROMPT_VERSION = "cj-v1"

_INSTR = """너는 금융 QA 답변의 근거 체인 채점자다. 제공된 evidence bundle 안의 근거만
실재로 인정하라 — bundle에 없는 인용·수치에 기댄 주장은 해당 축 0점.
축 정의:
- mechanism(0/1): 사건을 메커니즘으로 분해했는가 (예: 추론 개선 vs 학습 효율)
- state_link(0/1): 현재 판(자금 사용처·CAPEX 국면·공급사 포지션)과 연결했는가
- verdict(0/1): 방향 판단을 명시했고, 그 판단이 제시된 근거와 정합하는가
  (근거와 모순된 결론은 0)
- evidence(0~1): 루브릭 evidence 목록 중 답변에 bundle 근거와 함께 등장한 비율
  — matched/missing을 정확히 나눠라
- countercase(0/1): 반대 방향 시나리오가 실근거와 함께 있는가
유창함·문체는 채점 대상이 아니다."""

_COVERAGE_INSTR = """답변에서 사실·인과 주장을 전부 추출하고(결론·시나리오 포함),
각 주장이 evidence bundle의 근거로 뒷받침되는지 판정하라. 주장 누락 없이 전수 추출이
원칙이다 — 지원되는 주장만 골라내면 안 된다."""


class ChainAxisScore(BaseModel):
    score: float | None = Field(default=None, ge=0.0, le=1.0)   # B9: 범위 강제
    reason: str = ""
    matched: list[str] = []
    missing: list[str] = []


class ChainJudgeResult(BaseModel):
    case_id: str
    axes: dict[str, ChainAxisScore]
    raws: list[str]                                    # 반복 원시 응답 전량 (권고1)
    judge_model: str
    judge_prompt_version: str


class _JudgeOut(BaseModel):
    mechanism: ChainAxisScore
    state_link: ChainAxisScore
    verdict: ChainAxisScore
    evidence: ChainAxisScore
    countercase: ChainAxisScore


class _Claim(BaseModel):
    text: str
    supported: bool
    why: str = ""


class _CoverageOut(BaseModel):
    claims: list[_Claim]


def _valid(r) -> bool:
    return r is not None and all(r.axes[a].score is not None for a in AXES)


def merge_repeats(a: ChainJudgeResult, b: ChainJudgeResult,
                  tie: ChainJudgeResult | None) -> ChainJudgeResult:
    axes: dict[str, ChainAxisScore] = {}
    for ax in AXES:
        sa, sb = a.axes[ax].score, b.axes[ax].score
        if sa is None or sb is None:
            axes[ax] = ChainAxisScore(score=None, reason="repeat null")
        elif sa == sb:
            axes[ax] = a.axes[ax]
        elif tie is not None and tie.axes[ax].score is not None:
            st = tie.axes[ax].score
            if st == sa:
                axes[ax] = a.axes[ax]
            elif st == sb:
                axes[ax] = b.axes[ax]
            else:
                axes[ax] = ChainAxisScore(score=None, reason="no majority")
        else:
            axes[ax] = ChainAxisScore(score=None, reason="mismatch, no tiebreak")
    raws = a.raws + b.raws + (tie.raws if tie else [])
    return ChainJudgeResult(case_id=a.case_id, axes=axes, raws=raws,
                            judge_model=a.judge_model,
                            judge_prompt_version=a.judge_prompt_version)


async def _judge_once(case_id, answer_md, rubric, bundle_text, role):
    prompt = (f"[루브릭]\n{json.dumps(rubric, ensure_ascii=False)}\n\n"
              f"[답변]\n{answer_md}\n\n각 축을 채점하라.")
    for _ in range(2):                                 # invalid/timeout 1회 재시도
        try:
            out = await role.run(prompt, instructions=_INSTR,
                                 response_format=_JudgeOut,
                                 cache_prefix=f"[evidence bundle]\n{bundle_text}")
            data = out if isinstance(out, _JudgeOut) else _JudgeOut.model_validate(out)
            return ChainJudgeResult(
                case_id=case_id, axes={a: getattr(data, a) for a in AXES},
                raws=[data.model_dump_json()], judge_model=role.model,
                judge_prompt_version=JUDGE_PROMPT_VERSION)
        except Exception:  # noqa: BLE001
            continue
    return None


async def judge_case(case_id, answer_md, rubric, bundle_text, role):
    r1 = await _judge_once(case_id, answer_md, rubric, bundle_text, role)
    r2 = await _judge_once(case_id, answer_md, rubric, bundle_text, role)
    if not _valid(r1) or not _valid(r2):
        return None
    if all(r1.axes[a].score == r2.axes[a].score for a in AXES):
        return merge_repeats(r1, r2, tie=None)
    r3 = await _judge_once(case_id, answer_md, rubric, bundle_text, role)
    merged = merge_repeats(r1, r2, tie=r3 if _valid(r3) else None)
    return merged if _valid(merged) else None


async def judge_claim_coverage(case_id, answer_md, bundle_text, role) -> float | None:
    """uncovered_claim_ratio — 전수 주장 추출 후 미지원 비율 (r3-B7)."""
    for _ in range(2):
        try:
            out = await role.run(f"[답변]\n{answer_md}", instructions=_COVERAGE_INSTR,
                                 response_format=_CoverageOut,
                                 cache_prefix=f"[evidence bundle]\n{bundle_text}")
            data = out if isinstance(out, _CoverageOut) else _CoverageOut.model_validate(out)
            if not data.claims:
                return None                            # 주장 0개 = invalid (조작 의심)
            bad = sum(1 for c in data.claims if not c.supported)
            return round(bad / len(data.claims), 3)
        except Exception:  # noqa: BLE001
            continue
    return None
```

`providers.py` ROLE_MAP `"audit"` 항목 아래:

```python
    "chain_judge": [("openai", settings.model_gpt, "medium")],  # 교차 저지 — anthropic 폴백 금지(self-preference)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_chain_judge.py -v`
Expected: PASS 4건

- [ ] **Step 5: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/evals/chain_judge.py engine/providers.py engine/tests/test_chain_judge.py
git -C /home/ryze_yn/attn-viewer commit -m 'feat(eval): chain_judge — 범위 강제·반복 다수결·주장 커버리지 패스'
```

---

### Task 2: 튜닝 fixture 5개 + self-test

**Files:**
- Create: `engine/evals/fixtures/chain_judge/tuning/*.json` (5개)
- Create: `engine/evals/calibration.py`
- Test: `engine/tests/test_calibration.py`

**Interfaces:**
- Produces: `load_tuning_fixtures() -> list[dict]`, `run_selftest(judge_fn) -> list[str]`
- fixture의 answer_md는 **실제 합성 형식** 사용 — 반대 근거 절 제목은 synthesize 지시의
  `## 위험·반대 시나리오` (engine/stages/synthesize.py:30 — B7 정규식 정합)

fixture 5종: `01_missing_mechanism`(메커니즘 없이 결론), `02_fabricated_citation`(bundle에 없는 `[근거:ghost]` 수치 — evidence에 해당 항목 missing 기대), `03_future_info`(bundle 밖 사건 근거 — 그 주장에 기댄 축 0), `04_no_countercase`(`## 위험·반대 시나리오` 절 부재 — countercase 0), `05_clean`(전 축 1). 형식:

```json
{
  "id": "04_no_countercase",
  "answer_md": "## 결론\n부정적이다. HBM 수요 둔화가 확인됐다 [근거:c-1].\n\n메커니즘: CAPEX 축소 → HBM 주문 감소 [근거:c-1]. 현재 하이퍼스케일러 CAPEX는 둔화 국면이다 [근거:c-2].",
  "rubric": {"mechanism": "CAPEX→HBM 경로 분해", "state_link": "CAPEX 국면 연결",
             "verdict": "방향 판단+근거 정합", "evidence": ["CAPEX", "HBM"],
             "countercase": "반대 시나리오 유무"},
  "bundle_text": "c-1: HBM 주문 축소 보도. c-2: CAPEX 가이던스 하향.",
  "expected": {"countercase": 0, "verdict": 1}
}
```

(`expected`는 확실한 축만 — 부분 명세.)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_calibration.py
import asyncio

from evals.calibration import load_tuning_fixtures, run_selftest
from evals.chain_judge import AXES, ChainAxisScore, ChainJudgeResult


def _mk(case_id, scores):
    axes = {a: ChainAxisScore(score=scores.get(a, 1.0), reason="") for a in AXES}
    return ChainJudgeResult(case_id=case_id, axes=axes, raws=["{}"],
                            judge_model="fake", judge_prompt_version="cj-v1")


def test_fixtures_load_shape_and_synth_format():
    fx = load_tuning_fixtures()
    assert len(fx) == 5
    assert any("## 위험·반대 시나리오" in f["answer_md"] for f in fx)  # 실형식 사용


def test_selftest_oracle_passes_always_one_fails():
    fx = load_tuning_fixtures()
    oracle = {f["id"]: f["expected"] for f in fx}

    async def good(cid, ans, rub, btxt):
        return _mk(cid, {k: float(v) for k, v in oracle[cid].items()})

    async def lazy(cid, ans, rub, btxt):
        return _mk(cid, {})

    assert asyncio.run(run_selftest(good)) == []
    assert asyncio.run(run_selftest(lazy)) != []
```

- [ ] **Step 2: 실패 확인** — Run 위 pytest, Expected: ModuleNotFoundError

- [ ] **Step 3: fixture 5개 작성 + 구현**

```python
# engine/evals/calibration.py
"""저지 calibration — 튜닝 fixture(공개) / 봉인 metamorphic 셋(버전당 1회) 분리 (r3-B8)."""
from __future__ import annotations

import json
from pathlib import Path

_FIX = Path(__file__).parent / "fixtures" / "chain_judge"


def load_tuning_fixtures() -> list[dict]:
    return [json.loads(p.read_text())
            for p in sorted((_FIX / "tuning").glob("*.json"))]


async def run_selftest(judge_fn) -> list[str]:
    failures: list[str] = []
    for f in load_tuning_fixtures():
        res = await judge_fn(f["id"], f["answer_md"], f["rubric"], f["bundle_text"])
        if res is None:
            failures.append(f"{f['id']}: judge invalid")
            continue
        for ax, want in f["expected"].items():
            got = res.axes[ax].score
            ok = got is not None and (got == float(want) if want in (0, 1)
                                      else abs(got - want) < 0.26)
            if not ok:
                failures.append(f"{f['id']}: {ax} expected {want} got {got}")
    return failures
```

- [ ] **Step 4: 통과 확인** — PASS 2건
- [ ] **Step 5: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/evals/fixtures engine/evals/calibration.py engine/tests/test_calibration.py
git -C /home/ryze_yn/attn-viewer commit -m 'feat(eval): 튜닝 fixture 5종(실제 합성 형식) + self-test'
```

---

### Task 3: 봉인 metamorphic 셋 — 스펙 변형 4종

**Files:**
- Modify: `engine/evals/calibration.py`
- Test: `engine/tests/test_calibration.py` (추가)

**Interfaces:**
- Produces: `TRANSFORMS` = `flip_verdict` / `strip_countercase` / `ghost_citations` / `tamper_numbers` / `identity` (스펙 94행의 4종 + 대조군 — B7), `make_sealed_set(base_records, version) -> list[dict]`, `sealed_hash(sealed) -> str`, `run_sealed(judge_fn, sealed) -> list[str]`
- 기대 관계: flip_verdict→verdict `zero`(근거-결론 모순 — Task 1 verdict 정의가 전제), strip_countercase→countercase `zero`, ghost_citations→evidence `lower`, tamper_numbers→evidence `lower`(수치가 bundle과 불일치 → 해당 evidence 항목 miss), identity→verdict `same`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from evals.calibration import TRANSFORMS, make_sealed_set, run_sealed, sealed_hash
from evals.chain_judge import AXES, ChainAxisScore, ChainJudgeResult


def _base():
    return {"id": "b1",
            "answer_md": ("## 결론\n긍정적이다. HBM 수요가 강하다 [근거:c-1]. "
                          "수출 YoY +34%가 이를 뒷받침한다 [근거:m-1].\n\n"
                          "## 위험·반대 시나리오\nCAPEX 하향 시 부정적 [근거:c-2]."),
            "rubric": {"mechanism": "m", "state_link": "s", "verdict": "v",
                       "evidence": ["HBM", "수출"], "countercase": "c"},
            "bundle_text": "c-1: HBM 수요 보도. m-1: 수출 YoY +34%. c-2: CAPEX 하향."}


def test_transforms_flip_and_tamper():
    md = _base()["answer_md"]
    assert "부정적이다" in TRANSFORMS["flip_verdict"](md)      # 방향 반전 (스펙)
    assert "+34%" not in TRANSFORMS["tamper_numbers"](md)      # 수치 변조 (스펙)
    assert "## 위험·반대 시나리오" not in TRANSFORMS["strip_countercase"](md)
    assert "[근거:ghost-999]" in TRANSFORMS["ghost_citations"](md)


def test_sealed_set_shape_and_hash_stability():
    s1 = make_sealed_set([_base()], version="cj-v1")
    s2 = make_sealed_set([_base()], version="cj-v1")
    assert len(s1) == 5 and sealed_hash(s1) == sealed_hash(s2)


def test_run_sealed_catches_insensitive_judge():
    sealed = make_sealed_set([_base()], version="cj-v1")

    async def always_one(cid, ans, rub, btxt):
        axes = {a: ChainAxisScore(score=1.0, reason="") for a in AXES}
        return ChainJudgeResult(case_id=cid, axes=axes, raws=["{}"],
                                judge_model="fake", judge_prompt_version="cj-v1")

    import asyncio
    assert asyncio.run(run_sealed(always_one, sealed))
```

- [ ] **Step 2: 실패 확인** — ImportError 예상

- [ ] **Step 3: 구현** (`calibration.py`에 append)

```python
import hashlib
import re

_FLIPS = [("긍정적", "부정적"), ("부정적", "긍정적"), ("위협적이지 않다", "위협적이다"),
          ("위협적이다", "위협적이지 않다"), ("강하다", "약하다"), ("약하다", "강하다")]


def _flip_verdict(md: str) -> str:
    head, _, rest = md.partition("\n\n")               # 결론 절만 반전
    for a, b in _FLIPS:
        if a in head:
            return head.replace(a, b, 1) + "\n\n" + rest
    return "## 결론\n앞선 근거와 반대로 판단한다.\n\n" + rest


def _strip_countercase(md: str) -> str:
    return re.sub(r"## 위험·반대 시나리오.*", "", md, flags=re.S).strip()


def _ghost_citations(md: str) -> str:
    return re.sub(r"\[근거:[^\]]+\]", "[근거:ghost-999]", md)


def _tamper_numbers(md: str) -> str:
    """인용 span([근거:...]) 보호 후 본문 수치만 변조 (r2-B7 — 인용 ID 손상 금지)."""
    parts = re.split(r"(\[근거:[^\]]+\])", md)
    out = []
    for p in parts:
        if p.startswith("[근거:"):
            out.append(p)
        else:
            out.append(re.sub(r"[+-]?\d+(?:\.\d+)?%?",
                              lambda m: "97.3%" if "%" in m.group() else "973", p))
    return "".join(out)


TRANSFORMS = {"flip_verdict": _flip_verdict, "strip_countercase": _strip_countercase,
              "ghost_citations": _ghost_citations, "tamper_numbers": _tamper_numbers,
              "identity": lambda md: md}

_EXPECT = {"flip_verdict": ("verdict", "zero"),
           "strip_countercase": ("countercase", "zero"),
           "ghost_citations": ("evidence", "lower"),
           "tamper_numbers": ("evidence", "lower"),
           "identity": ("verdict", "same")}


def make_sealed_set(base_records: list[dict], version: str) -> list[dict]:
    """생성 시 검증 (r2-B7): base가 변형 대상(수치·countercase 절·인용)을 실제로
    포함하고 변형이 텍스트를 실제로 바꿨는지 강제 — 아니면 ValueError (다른 base 답변
    을 고르라는 뜻)."""
    sealed = []
    for rec in base_records:
        md = rec["answer_md"]
        if "## 위험·반대 시나리오" not in md:
            raise ValueError(f"{rec['id']}: countercase 절 없음 — sealed base 부적합")
        if not re.search(r"\[근거:[^\]]+\]", md):
            raise ValueError(f"{rec['id']}: 인용 없음 — sealed base 부적합")
        stripped_cites = re.sub(r"\[근거:[^\]]+\]", "", md)
        if not re.search(r"\d", stripped_cites):
            raise ValueError(f"{rec['id']}: 본문 수치 없음 — sealed base 부적합")
        for name, fn in TRANSFORMS.items():
            out_md = fn(md)
            if name != "identity" and out_md == md:
                raise ValueError(f"{rec['id']}::{name}: 변형이 텍스트를 못 바꿈")
            ax, rel = _EXPECT[name]
            sealed.append({"id": f"{rec['id']}::{name}", "base_id": rec["id"],
                           "transform": name, "answer_md": out_md,
                           "base_answer_md": md, "rubric": rec["rubric"],
                           "bundle_text": rec["bundle_text"], "version": version,
                           "expectation": {"axis": ax, "relation": rel}})
    return sealed


def sealed_hash(sealed: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sealed, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def sealed_structure_errors(sealed: list[dict]) -> list[str]:
    """구조 게이트 (r3-B6): 서로 다른 base 2개 × 변형 5종 = 정확히 10개."""
    errs = []
    bases = {s["base_id"] for s in sealed}
    if len(sealed) != 10:
        errs.append(f"sealed 셋은 정확히 10개여야 함 (현재 {len(sealed)})")
    if len(bases) != 2:
        errs.append(f"서로 다른 base 2개 필요 (현재 {len(bases)})")
    for b in bases:
        got = {s["transform"] for s in sealed if s["base_id"] == b}
        if got != set(TRANSFORMS):
            errs.append(f"base {b}: 변형 누락 {set(TRANSFORMS) - got}")
    return errs


async def run_sealed(judge_fn, sealed: list[dict]) -> list[str]:
    failures = sealed_structure_errors(sealed)
    if failures:
        return failures
    base_cache: dict = {}
    for s in sealed:
        if s["base_id"] not in base_cache:
            base_cache[s["base_id"]] = await judge_fn(
                s["base_id"], s["base_answer_md"], s["rubric"], s["bundle_text"])
        base, var = base_cache[s["base_id"]], await judge_fn(
            s["id"], s["answer_md"], s["rubric"], s["bundle_text"])
        # r3-B7: base 전제조건 — verdict·countercase=1, evidence>0. 항상-0 저지처럼
        # 방향에 무감한 저지는 여기서 걸린다 (변형 기대만으론 통과 가능했음).
        if base is not None and s["transform"] == "identity":
            if base.axes["verdict"].score != 1.0 or base.axes["countercase"].score != 1.0 \
                    or not (base.axes["evidence"].score or 0) > 0:
                failures.append(f"{s['base_id']}: base 전제조건 미달 "
                                f"(verdict/countercase=1·evidence>0 필요)")
        if base is None or var is None:
            failures.append(f"{s['id']}: judge invalid")
            continue
        ax, rel = s["expectation"]["axis"], s["expectation"]["relation"]
        b, v = base.axes[ax].score, var.axes[ax].score
        if b is None or v is None:
            failures.append(f"{s['id']}: null score")
        elif rel == "zero" and v != 0.0:
            failures.append(f"{s['id']}: {ax} expected 0 got {v}")
        elif rel == "lower" and not (v < b):
            failures.append(f"{s['id']}: {ax} expected < {b} got {v}")
        elif rel == "same" and v != b:
            failures.append(f"{s['id']}: {ax} expected {b} got {v}")
    return failures
```

- [ ] **Step 4: 통과 확인** — PASS (calibration 5건)
- [ ] **Step 5: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/evals/calibration.py engine/tests/test_calibration.py
git -C /home/ryze_yn/attn-viewer commit -m 'feat(eval): 봉인 셋 — 스펙 변형 4종(방향반전·삭제·유령인용·수치변조)+hash'
```

---

### Task 4: EvalBundle 읽기 + violation 검출 (실제 레이어 구조)

**Files:**
- Modify: `engine/evals/bundle.py`
- Test: `engine/tests/test_eval_bundle.py` (추가)

**Interfaces:**
- Produces: `EvalBundle(root)` — `.manifest`, `.verify_hash() -> bool`, `.store() -> BundleSectorStore(read_cards(days,axis,entity,limit)/read_metric/get_state)`, `.ra_news_items() -> list[dict]` (NewsItem dump 그대로), `.prices() -> dict` (`{"quotes": [...], "macro": {...}}`), `.bundle_text(max_chars)` — **카드 + 지표 최근값 + 가격/매크로 요약 포함** (B3)
- Produces: `find_violations(layers, answer_md, manifest) -> list[str]` — 검사 대상:
  ①`ra_x` 레이어 `data["items"][*]["url"]` (orchestrator.py:105 실구조),
  ②`sector_rag` 레이어 `data["cards"][*]["url"]`,
  ③**answer_md 본문의 URL** (정규식) — 전부 manifest.urls 대조 (B1)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from evals.bundle import EvalBundle, find_violations


def test_bundle_text_includes_metrics_and_prices(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b", as_of="2026-07-10",
                         availability="unproven", ra_docs=[],
                         prices={"quotes": [{"symbol": "005930.KS", "close": 254500}],
                                 "macro": {}},
                         macro={"kospi": 3300})
    b = EvalBundle(out)
    assert b.verify_hash()
    txt = b.bundle_text()
    assert "kr_semi_export" in txt and "005930.KS" in txt   # B3: 지표·가격 포함


def test_find_violations_real_layer_shapes_and_answer(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b2", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    m = EvalBundle(out).manifest
    layers = [
        {"name": "ra_x", "data": {"items": [{"url": "https://leak.example/a"}]}},
        {"name": "sector_rag", "data": {"cards": [{"url": "https://a.example/c-0"}]}},
    ]
    answer = "결론이다. 자세한 근거는 https://leak.example/b 참고."
    v = find_violations(layers, answer, m)
    assert "https://leak.example/a" in v and "https://leak.example/b" in v
    assert "https://a.example/c-0" not in v                 # bundle 내 카드 URL은 허용


def test_bundle_store_read_cards_signature(tmp_path):
    store = _seed(tmp_path)
    out = capture_bundle(store, tmp_path / "b3", as_of="2026-07-10",
                         availability="unproven", ra_docs=[], prices={}, macro={})
    bs = EvalBundle(out).store()
    assert bs.read_cards(days=14, axis="A", entity=None, limit=500)  # 시그니처 호환
    assert bs.read_metric("kr_semi_export", last_n=90)
```

- [ ] **Step 2: 실패 확인** — ImportError(EvalBundle) 예상

- [ ] **Step 3: 구현** (`bundle.py`에 append)

```python
import re as _re

from sector.contracts import MetricObservation, SectorCard

_URL_RE = _re.compile(r"https?://[^\s\)\]>\"']+")


class BundleSectorStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._cards = [SectorCard.model_validate_json(l)
                       for l in (self.root / "cards.jsonl").read_text().splitlines()
                       if l.strip()]

    def read_cards(self, *, days: int | None = 14, axis: str | None = None,
                   entity: str | None = None, limit: int = 500) -> list[SectorCard]:
        out = self._cards                               # 이미 as_of로 잘림 — days 무시
        if axis:
            out = [c for c in out if c.axis == axis]
        if entity:
            out = [c for c in out if entity in (c.entities or [])]
        return out[:limit]

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

    def verify_hash(self) -> bool:
        return _content_hash(self.root, self.manifest) == self.manifest.get("content_hash")

    def snapshot(self) -> dict:
        """price_macro 주입용 단일 스냅샷 — prices와 macro를 함께 (r2-B3)."""
        p = self.prices()
        return {"quotes": p.get("quotes", []), "macro": self.macro()}

    def store(self) -> BundleSectorStore:
        return BundleSectorStore(self.root)

    def ra_news_items(self) -> list[dict]:
        p = self.root / "ra_docs.jsonl"
        return ([json.loads(l) for l in p.read_text().splitlines() if l.strip()]
                if p.exists() else [])

    def prices(self) -> dict:
        return json.loads((self.root / "prices.json").read_text())

    def macro(self) -> dict:
        return json.loads((self.root / "macro.json").read_text())

    def bundle_text(self, max_chars: int = 14000) -> str:
        st = self.store()
        parts = [f"{c.id}: {c.title} — {c.raw_quote[:150]}"
                 for c in st.read_cards(days=None, limit=100_000)]
        for m in self.manifest.get("metric_names", []):
            rows = st.read_metric(m, last_n=6)
            if rows:
                parts.append(f"{m}: " + ", ".join(f"{o.ts}={o.value}{o.unit}"
                                                  for o in rows))
        for q in (self.prices().get("quotes") or []):
            parts.append(f"price:{json.dumps(q, ensure_ascii=False)[:150]}")
        if self.macro():
            parts.append(f"macro:{json.dumps(self.macro(), ensure_ascii=False)[:300]}")
        parts += [f"doc:{d.get('url', '')}: {str(d.get('snippet') or d.get('title', ''))[:150]}"
                  for d in self.ra_news_items()]
        return "\n".join(parts)[:max_chars]


_CITE_RE = _re.compile(r"\[근거:([^\]\s,]+)")


def _allowed_cite_tokens(manifest: dict) -> set[str]:
    """무조건 허용 태그 없음 (r3-B1) — 전부 manifest provenance에서 파생:
    카드 ID + NewsItem ID + 정확 URL + 도메인/1레벨 라벨 + 조건부 채널 태그
    (yahoo는 quote_symbols 있을 때만, macro는 macro_keys 있을 때만) + calc
    (bundle 모드에선 CALC 입력이 bundle 사실뿐이므로 bundle 유래)."""
    toks = (set(manifest.get("card_ids", []))
            | set(manifest.get("news_ids", []))
            | set(manifest.get("urls", []))
            | {"calc"})
    for u in manifest.get("urls", []):
        host = _re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
        toks.add(host)
        toks.add(host.split(".")[0])                   # fnnews.com → fnnews
    if manifest.get("quote_symbols"):
        toks.add("yahoo")
        toks.update(manifest["quote_symbols"])
    if manifest.get("macro_keys"):
        toks.add("macro")
    return toks


def find_violations(layers: list[dict], answer_md: str, manifest: dict) -> list[str]:
    """전 레이어 재귀 URL 수집 + 답변 URL + [근거:토큰] 검사 (r2-B1).

    레이어 이름을 열거하지 않는다 — 어떤 증거 레이어(ra_x·ra_web·news_summary·
    sector_rag·이후 추가분)든 dict/list를 재귀로 걸어 'url' 키를 전부 수집."""
    allowed = set(manifest.get("urls", []))
    allowed_toks = _allowed_cite_tokens(manifest)
    found: list[str] = []

    def _check(u):
        if isinstance(u, str) and u.startswith("http") and u not in allowed \
                and u not in found:
            found.append(u)

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "url":
                    _check(v)
                else:
                    _walk(v)
        elif isinstance(node, list):
            for it in node:
                _walk(it)

    for l in layers:
        _walk(l.get("data") or {})
    for u in _URL_RE.findall(answer_md or ""):
        _check(u.rstrip(".,"))
    for tok in _CITE_RE.findall(answer_md or ""):      # bundle 밖 근거 ID/태그 (B1)
        if tok not in allowed_toks and f"cite:{tok}" not in found:
            found.append(f"cite:{tok}")
    return found
```

- [ ] **Step 4: 통과 확인** — test_eval_bundle 전체 PASS
- [ ] **Step 5: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/evals/bundle.py engine/tests/test_eval_bundle.py
git -C /home/ryze_yn/attn-viewer commit -m 'feat(eval): EvalBundle — hash 검증·실레이어 위반 검출·지표 포함 bundle_text'
```

---

### Task 5: 파이프라인 bundle 모드 (실계약 + cutoff 강제 + 네트워크 가드)

**Files:**
- Modify: `engine/stages/price_macro.py:12` — 본문에서 packet 조립부를 `_assemble(plan, quotes, macro, extra_series)` 헬퍼로 추출 후 `snapshot` 분기 추가
- Modify: `engine/stages/ra_external.py:421` — `bundle_items` 분기
- Modify: `engine/sector/retrieve.py:134` — `search_with_plan(..., ref_now: str | None = None)` (기본 None=utcnow — B2 랭킹 시계)
- Modify: `engine/orchestrator.py` — bundle 로드·cutoff 강제·분기 전달·보충검색 차단
- Test: `engine/tests/test_bundle_mode.py`

**Interfaces:**
- `run_price_macro(plan, snapshot: dict | None = None)`: snapshot=`{"quotes": [...raw rows...], "macro": {...}}` → **라이브 fetch 없이** `_assemble` 직행 (typed_facts·claims 파생은 기존 조립 코드 그대로 재사용 — G2 경로 유지)
- `run_ra_external(plan, overrides, *, bundle_items: list[dict] | None = None)`:
  bundle_items = NewsItem dump 목록 → `NewsItem.model_validate`로 복원해
  `RaPacket(web_knowledge={"q0": items}, collector_status={...정상 표기...})` 구성,
  라이브 수집기(네이버·구글RSS·toss·x_search) 전부 미호출
- orchestrator 계약 (`overrides["eval_bundle"]`):
  1. PLAN 직후 `plan.knowledge_cutoff = manifest["as_of"]` **코드 덮어쓰기** (B2)
  2. DISPATCH: `bundle_items=`·`snapshot=` 전달
  3. sector 블록: `_store = bundle.store()`, `search_with_plan(..., ref_now=manifest["as_of"])`
  4. REFLECT 보충 검색 2곳(orchestrator.py:372 부근 `run_ra_research` 호출):
     `if eval_bundle: found, new_claims = [], []` — 기존 "신규 0건 종료" 규칙 활용
- 기본값 경로(=None) 동작 불변.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_bundle_mode.py
import asyncio

import pytest

from contracts.packets import PlanPacket
from stages.price_macro import run_price_macro
from stages.ra_external import run_ra_external


def _plan() -> PlanPacket:
    return PlanPacket(tier=2, original_question="하이닉스 전망",
                      standalone_question="하이닉스 전망",
                      knowledge_cutoff="2026-07-10")


def test_price_macro_snapshot_no_network(monkeypatch):
    import stages.price_macro as pm

    def _boom(*a, **k):
        raise AssertionError("live fetch called in snapshot mode")

    # 라이브 fetch 경로 전부 봉인 — snapshot 분기가 호출하면 즉시 실패
    for name in dir(pm):
        if name.startswith("_fetch") or name in ("collect_macro",):
            monkeypatch.setattr(pm, name, _boom, raising=False)
    # r2-B5: 실제 quote() 반환 스키마(token·last — yahoo.py:79, price_macro.py:33)만 사용
    snap = {"quotes": [{"token": "005930.KS", "last": 254500.0, "currency": "KRW"}],
            "macro": {}}
    pkt = asyncio.run(run_price_macro(_plan(), snapshot=snap))
    assert pkt.quotes and pkt.quotes[0]["token"] == "005930.KS"
    assert pkt.macro == {}
    # 구현 착수 시 yahoo.quote() 실반환 키를 확인해 위 fixture 키를 맞춘다 — 계약과
    # 다른 키로 테스트를 통과시키는 것 금지 (실행 가능한 그대로의 스키마만)


def test_ra_external_bundle_items_no_live(monkeypatch):
    import stages.ra_external as ra

    def _boom(*a, **k):
        raise AssertionError("live search called in bundle mode")

    for name in ("run_x_search", "run_web_knowledge", "run_toss_trend",
                 "run_toss_company"):
        monkeypatch.setattr(ra, name, _boom, raising=False)
    # r2-B5: NewsItem은 extra-forbid — 반드시 실계약으로 생성 후 model_dump()
    from contracts.packets import NewsItem
    item = NewsItem(id="n1", title="t", url="https://a.example/1",
                    published_at="2026-07-09", summary="s")   # 필수 필드는 packets.py:226 확인
    pkt = asyncio.run(run_ra_external(_plan(), None, bundle_items=[item.model_dump()]))
    got = [n for lst in pkt.web_knowledge.values() for n in lst]
    assert [n.url for n in got] == ["https://a.example/1"]
```

주의: `NewsItem` 실필드(engine/contracts/packets.py:226)에 맞게 items dict 키를 조정한다
— 필수 필드가 더 있으면 **테스트 fixture를 계약에 맞춘다** (계약 변경 금지). monkeypatch
대상 함수명이 다르면 ra_external.py에서 라이브 수집 진입 함수를 확인해 그 이름으로 봉인
— "이름이 없어서 봉인 실패"는 허용되지 않는다 (raising=False 남용 금지: 최소 2개는
`raising=True`로 실존 확인).

- [ ] **Step 2: 실패 확인** — TypeError (인자 없음) 예상

- [ ] **Step 3: 구현** — 위 Interfaces 계약대로. price_macro는 기존 본문을
  `_assemble`로 추출하는 리팩터가 선행 (라이브 경로 결과가 리팩터 전후 동일함을
  기존 테스트로 확인). orchestrator diff 요지:

```python
    # run_qa 초입 (PLAN 이후 최초 사용 전)
    eval_bundle = None
    if overrides and overrides.get("eval_bundle"):
        from evals.bundle import EvalBundle
        eval_bundle = EvalBundle(overrides["eval_bundle"])
        if not eval_bundle.verify_hash():
            raise RuntimeError("eval bundle hash 불일치 — 오염 의심 (B3)")

    # PLAN 직후 (plan 변수 확보된 지점)
    if eval_bundle:
        plan.knowledge_cutoff = eval_bundle.manifest["as_of"]   # B2

    # DISPATCH (L218-220)
        _safe(run_ra_external(plan, overrides,
                              bundle_items=eval_bundle.ra_news_items()
                              if eval_bundle else None), ...),
        _safe(run_price_macro(plan,
                              snapshot=eval_bundle.snapshot() if eval_bundle else None), ...)
    # snapshot()은 quotes+macro 통합 (r2-B3) — macro.json이 파이프라인에 실제 전달됨

    # sector 블록 (L267·L270)
        _store = eval_bundle.store() if eval_bundle else _get_store()
        sector_cards = search_with_plan(_store, qp, k=12,
                                        hard_entities=outcome.rule_plan.entities,
                                        ref_now=eval_bundle.manifest["as_of"]
                                        if eval_bundle else None)

    # 보충검색 2곳 (L372 부근, L436 부근)
        if eval_bundle:
            found, new_claims = [], []
        else:
            found, new_claims = await run_ra_research(...)
```

`retrieve.py`: `search_with_plan(store, plan, *, k=12, hard_entities=None, ref_now=None)`
— `now = (_dt.datetime.fromisoformat(ref_now).replace(tzinfo=_dt.timezone.utc)
if ref_now else _dt.datetime.now(_dt.timezone.utc))` (L144 대체).

- [ ] **Step 4: 통과 + 회귀 확인**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 전부 PASS (기존 포함 — 기본값 경로 무변화 증명)

- [ ] **Step 5: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/orchestrator.py engine/stages/ra_external.py engine/stages/price_macro.py engine/sector/retrieve.py engine/tests/test_bundle_mode.py
git -C /home/ryze_yn/attn-viewer commit -m 'feat(engine): bundle 모드 — cutoff·랭킹 시계 고정, 라이브 경로 봉인 테스트'
```

---

### Task 6: 지표 — paired-validity(합집합 분모)·bootstrap CI·축 검증

**Files:**
- Modify: `engine/evals/metrics.py`
- Test: `engine/tests/test_chain_metrics.py`

**Interfaces:**
- Produces: `chain_axes_valid(rec) -> bool` (axes 키셋 == AXES **정확히** + 전값 non-null — B8), `paired_valid(base, cand) -> (pairs, ratio)` — **분모 = id 합집합** (한쪽에만 있는 케이스도 무효로 계수), `bootstrap_ci(deltas, n=10000, seed=42)`, `axis_mean(records, axis)`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# engine/tests/test_chain_metrics.py
from evals.chain_metrics_helpers import noop  # 없음 — 아래 실제 import로 교체
```

실제 테스트:

```python
from evals.metrics import axis_mean, bootstrap_ci, chain_axes_valid, paired_valid

_FULL = {"mechanism": 1.0, "state_link": 1.0, "verdict": 1.0,
         "evidence": 1.0, "countercase": 1.0}


def _rec(cid, axes):
    return {"id": cid, "chain_axes": axes}


def test_chain_axes_valid_requires_exact_keyset():
    assert chain_axes_valid(_rec("a", dict(_FULL)))
    assert not chain_axes_valid(_rec("a", {"mechanism": 1.0}))          # 부분 dict 거부 (B8)
    assert not chain_axes_valid(_rec("a", {**_FULL, "extra": 1.0}))
    assert not chain_axes_valid(_rec("a", {**_FULL, "verdict": None}))


def test_paired_valid_union_denominator():
    base = [_rec("a", dict(_FULL)), _rec("b", dict(_FULL))]
    cand = [_rec("a", dict(_FULL)), _rec("c", dict(_FULL))]   # b 누락, c는 base에 없음
    pairs, ratio = paired_valid(base, cand)
    assert [p[0]["id"] for p in pairs] == ["a"]
    assert round(ratio, 3) == round(1 / 3, 3)                  # 분모 = {a,b,c}


def test_bootstrap_ci():
    lo, hi = bootstrap_ci([1.0] * 10, seed=42)
    assert lo > 0
    lo2, hi2 = bootstrap_ci([1.0, -1.0] * 5, seed=42)
    assert lo2 <= 0 <= hi2


def test_axis_mean_ignores_invalid():
    rows = [_rec("a", dict(_FULL)), _rec("b", {**_FULL, "mechanism": None})]
    assert axis_mean(rows, "mechanism") == 1.0
```

- [ ] **Step 2: 실패 확인** — ImportError
- [ ] **Step 3: 구현** (`metrics.py` append)

```python
import random as _random

_CHAIN_AXES = ("mechanism", "state_link", "verdict", "evidence", "countercase")


def chain_axes_valid(rec: dict) -> bool:
    ax = rec.get("chain_axes")
    return (isinstance(ax, dict) and set(ax) == set(_CHAIN_AXES)
            and all(v is not None for v in ax.values()))


def paired_valid(base: list[dict], cand: list[dict]) -> tuple[list[tuple], float]:
    """분모 = id 합집합 — 한쪽 누락도 무효 계수 (B8: 선택적 소실 은폐 차단)."""
    bmap, cmap = {r["id"]: r for r in base}, {r["id"]: r for r in cand}
    ids = sorted(set(bmap) | set(cmap))
    pairs = [(bmap[i], cmap[i]) for i in ids
             if i in bmap and i in cmap
             and chain_axes_valid(bmap[i]) and chain_axes_valid(cmap[i])]
    return pairs, (len(pairs) / len(ids) if ids else 0.0)


def bootstrap_ci(deltas: list[float], n: int = 10000,
                 seed: int = 42) -> tuple[float, float]:
    rng = _random.Random(seed)
    means = sorted(sum(rng.choices(deltas, k=len(deltas))) / len(deltas)
                   for _ in range(n))
    return means[int(n * 0.025)], means[int(n * 0.975)]


def axis_mean(records: list[dict], axis: str) -> float | None:
    vals = [r["chain_axes"][axis] for r in records
            if (r.get("chain_axes") or {}).get(axis) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None
```

- [ ] **Step 4: 통과 확인** — PASS 4건
- [ ] **Step 5: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/evals/metrics.py engine/tests/test_chain_metrics.py
git -C /home/ryze_yn/attn-viewer commit -m 'feat(eval): 합집합 분모 paired-validity·축 키셋 검증·bootstrap CI'
```

---

### Task 7: run_eval — `--suite chain`·봉인 게이트·--compare·회귀 체크

**Files:**
- Modify: `engine/evals/run_eval.py`
- Test: 게이트 로직은 Task 1~6 단위 테스트가 커버. 실행기 자체는 Task 8 파일럿으로 검증.

**Interfaces (CLI):**
- `--suite chain [--split dev] [--limit N] [--pilot]` — **holdout은 experiment로만
  실행 가능** (r3-B8): `--split holdout` 단독은 exit 1.
- `--suite chain --experiment NAME --split holdout` — **단일 명령 2-arm 원자 실행**
  (r3-B8): ①실행 전 holdout id 집합을 ledger에 `claimed`로 기록 → ②**off-arm**
  (baseline: `overrides["disable_p23"]=True` — 2·3부 기능 토글 오프) 전 케이스 실행·채점
  → ③**on-arm** (candidate: 토글 온) 실행·채점 → ④paired 판정 → ⑤ledger `consumed`
  갱신. 같은 코드·같은 bundle에서 두 arm이 나오므로 baseline 아티팩트 주입 불가.
  전제: 2·3부의 모든 신기능은 `disable_p23` override로 완전 비활성화 가능해야 한다
  (**2·3부 계획의 전역 제약으로 승계**). 1부 시점(2·3부 미구현)에는 experiment 실행
  자체가 불가(토글할 대상 없음) — 베이스라인은 dev에서만 측정.
- `--suite golden --check-regression` (B12 — 아래 코호트 계약)
- 게이트 (전부 코드 강제):
  1. self-test 실패 → exit 1, 채점 시작 안 함
  2. **봉인 게이트 (B6·r2):** `fixtures/chain_judge/sealed-{JUDGE_PROMPT_VERSION}.json`
     로드(없거나 비면 exit 1). `evals/sealed_ledger.jsonl`(append-only)은 **version당
     hash 1개만 허용** — 같은 version에 다른 hash가 오면 exit 1 ("sealed 파일 교체로
     재시도 금지 — JUDGE_PROMPT_VERSION을 올려라"). 기록 없으면 지금 평가·append,
     `failed`면 exit 1, `passed`면 생략.
  3. **holdout 스키마 게이트 (r2-N3):** experiment 한정. `--limit`·`--pilot` 금지,
     케이스 **고유 id ≥ 10**, 전부 `availability=="proven"`, 사건 유형 층화(4유형 각 ≥1)
     확인 — 하나라도 미달 exit 1. **id 집합은 첫 답변 생성 전에 `claimed` 기록**
     (r3-B8), 완료 시 `consumed` — claimed/consumed 이력에 있는 집합 재사용 exit 1.
  4. **케이스↔manifest 상호 검증 (r2-B10·r3):** 케이스마다 실행 전
     `EvalBundle.verify_hash()` + `case.availability == manifest.availability` +
     `case.as_of == manifest.as_of` + `row.split == args.split` +
     (proven이면 `manifest.captured_at[:10] == manifest.as_of` — 회고 bundle을 proven
     으로 위장하는 것 차단) — 실패 exit 1. hash가 manifest를 포함하므로 변조도 잡힌다.
  5. **pilot 제한 (r2-N2):** `--pilot`은 `--split dev` + 전 케이스 unproven일 때만 허용,
     `--experiment`와 조합 금지 — 위반 exit 1. pilot 레코드에도 `rubric`·`bundle_text`
     포함 (봉인 생성 입력 — r2-B6).
  6. 실행 후 `as_of_violations` 합 > 0 또는 must_not hit → 리포트 저장 후 **exit 1**
- 레코드 필드: `id, split, availability, chain_axes, uncovered_claim_ratio,
  entailed_edge_ratio: None`(사유 "ChainPacket 미구현 — 3부부터"), `judge_raws`,
  `as_of_violations, must_not_hit, answer_md, rubric, bundle_text` + question_metrics
- experiment 판정 (전부 미달 시 **exit 1** — r2-B8·B9):
  `paired_valid` ratio ≥ 0.9 AND mechanism·state_link 각각 (bootstrap CI 하한 > 0 AND
  delta ≥ +0.3) AND candidate uncovered_claim_ratio 평균 ≤ 0.2
- **3부 전환 게이트 (r2-B9):** ChainPacket 도입 커밋 이후 `entailed_edge_ratio: None`은
  실행기에서 exit 1 — 전환 시점은 3부 계획에 명시하고 이 계획의 null 허용은 그때 종료.
- `--check-regression` (r2-B12): `golden_baseline.json`은 report-20260714-211007.jsonl의
  **10개 케이스 id별 {verified_ratio, keyword_ok}**를 저장. 검사는 동일 id 10문항을
  재실행해 ①keyword_ok가 true→false로 퇴행한 케이스 존재 또는 ②verified_ratio 평균이
  tolerance(0.15) 초과 하락이면 exit 1.
- 리포트: 축 평균, uncovered_claim_ratio 평균, 위반 합계, 무효 케이스, code SHA,
  judge 버전, sealed_hash, 케이스별 bundle content_hash, DA 파라메트릭 잔여 위험 문구

- [ ] **Step 1: 구현** — `run_chain_suite(args)` (Interfaces 계약 그대로; 채점 루프는
  케이스마다 `judge_case` + `judge_claim_coverage` 순차 호출, `find_violations(layers,
  answer, manifest)` 사용. 코드 구조는 v1 계획의 `run_chain_suite`를 위 게이트들로 확장 —
  각 게이트는 함수로 분리: `_gate_selftest`, `_gate_sealed`, `_gate_holdout`,
  `_check_regression`)

- [ ] **Step 2: 기존 suite 회귀 확인**

Run: `.venv/bin/python -m pytest tests/ -v && .venv/bin/python -m evals.run_eval --limit 1`
Expected: PASS + golden 1문항 정상 (기존 경로 무변화)

- [ ] **Step 3: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/evals/run_eval.py
git -C /home/ryze_yn/attn-viewer commit -m 'feat(eval): --suite chain — 봉인 ledger 게이트·holdout 1회 강제·--compare·위반 시 실패'
```

---

### Task 8: 케이스 24개 — capture 선행 → rubric 작성 → 검증 → 베이스라인

순서가 계약이다 (권고2): **capture → hash/manifest 확인 → bundle에서 evidence 선택 →
validate → 파일럿 → 봉인 생성·통과 → authoritative 베이스라인.**

**Files:**
- Modify: `engine/evals/build_chain_cases.py` (list·validate 서브커맨드 추가)
- Create: `engine/evals/golden_chain.jsonl`, `engine/evals/bundles/cj-01..24/`,
  `engine/evals/fixtures/chain_judge/sealed-cj-v1.json`

- [ ] **Step 1: `list`·`validate` 서브커맨드 추가**

`list`: `store.read_cards(days=None, limit=100_000)`에서 `--since` 이후 magnitude≥2를
날짜순 출력 (v1 계획의 cmd_list에 limit 인자만 수정).
`validate`: golden_chain.jsonl 전 케이스에 대해 —

```python
def cmd_validate(args) -> None:
    from evals.bundle import EvalBundle
    rows = [json.loads(l) for l in (_HERE / "golden_chain.jsonl").read_text().splitlines()
            if l.strip()]
    errs: list[str] = []
    for r in rows:
        b = EvalBundle(_HERE / r["bundle_path"])
        if not b.verify_hash():
            errs.append(f"{r['id']}: bundle hash 불일치")
        if r["availability"] != b.manifest["availability"]:
            errs.append(f"{r['id']}: availability 불일치 (case vs manifest)")   # B10
        if r["split"] == "holdout" and r["availability"] != "proven":
            errs.append(f"{r['id']}: holdout은 proven만")                        # B10
        if r["as_of"] != b.manifest["as_of"]:
            errs.append(f"{r['id']}: as_of 불일치")
        btxt = b.bundle_text(max_chars=200_000)
        for ev in r["rubric"]["evidence"]:
            if ev not in btxt:
                errs.append(f"{r['id']}: rubric evidence '{ev}'가 bundle에 없음")
        if not b.manifest["card_ids"]:
            errs.append(f"{r['id']}: 빈 bundle")
    if errs:
        raise SystemExit("\n".join(errs))
    print(f"OK: {len(rows)} cases")
```

- [ ] **Step 2: bundle 24개 캡처** — `list` 출력에서 사건 선정(층화: 실적/모델·제품/
  CAPEX·수급/정책·규제 각 ≥4, 긍정·부정 반반). 케이스별 as_of=사건 다음 날.
  가격 스냅샷은 `engine/tools/price/yahoo.py:71`의 `until` 지원 quote로 관련 티커
  (005930.KS·000660.KS·MU·NVDA·^KS11 등) as_of 시점 값을 받아 prices.json 구성 —
  보조 스크립트 한 줄 실행 예시를 README-chain.md에 기록. RA 문서는 회고 케이스에서
  빈 배열 허용(명시 파일). 캡처 후 각 manifest의 `card_ids` 비어 있지 않은지 즉시 확인.

- [ ] **Step 3: golden_chain.jsonl 작성** — 24케이스 전부 `split: "dev"`,
  `availability: "unproven"` (holdout은 전향 축적분으로만 — Task 0 Step 5 가동 중).
  **rubric.evidence는 해당 bundle의 `bundle_text` 출력에서 골라 적는다** (기억 금지).
  작성 후:

Run: `.venv/bin/python -m evals.build_chain_cases validate`
Expected: `OK: 24 cases`

- [ ] **Step 4: 파일럿 → 봉인 생성·통과 → 베이스라인**

```bash
# (a) 파일럿 3문항 — 봉인 셋이 아직 없으므로 이 실행은 exit 1이어야 정상.
#     따라서 먼저 파일럿용 비권위 실행으로 답변만 뽑는다: --limit 3에 --pilot 플래그
#     (판정·ledger 기록 없이 answer_md만 저장 — run_eval에 함께 구현되어 있음)
.venv/bin/python -m evals.run_eval --suite chain --split dev --limit 3 --pilot
# (b) 봉인 셋 생성 — answer_md만 파일럿에서, rubric·bundle_text는 원본에서 직접 (r2-B6)
.venv/bin/python - <<'EOF'
import json, pathlib
from evals.bundle import EvalBundle
from evals.calibration import make_sealed_set, sealed_hash
here = pathlib.Path("evals")
cases = {r["id"]: r for l in open(here / "golden_chain.jsonl") if (r := json.loads(l))}
recs = [json.loads(l) for l in open(sorted((here / "out").glob("chain-pilot-*.jsonl"))[-1])]
base = []
for r in recs:
    if len(base) >= 2:
        break
    case = cases[r["id"]]
    b = EvalBundle(here / case["bundle_path"])
    try:                                    # make_sealed_set이 base 적합성 검증 (r2-B7)
        make_sealed_set([{"id": r["id"], "answer_md": r["answer_md"],
                          "rubric": case["rubric"], "bundle_text": b.bundle_text()}],
                        version="cj-v1")
        base.append({"id": r["id"], "answer_md": r["answer_md"],
                     "rubric": case["rubric"], "bundle_text": b.bundle_text()})
    except ValueError as e:
        print("skip:", e)                   # 부적합 답변은 다음 후보로
assert len(base) == 2, f"적합 base 2개 필요 — 현재 {len(base)} (r3-B6): 파일럿 케이스 추가 실행"
sealed = make_sealed_set(base, version="cj-v1")
from evals.calibration import sealed_structure_errors
errs = sealed_structure_errors(sealed)
assert not errs, errs
out = here / "fixtures/chain_judge/sealed-cj-v1.json"
out.write_text(json.dumps(sealed, ensure_ascii=False, indent=1))
print("sealed:", sealed_hash(sealed), len(sealed))
EOF
# (c) authoritative 베이스라인 — 봉인 게이트가 첫 실행에서 평가·기록됨 (첫 시도 통과 필수)
.venv/bin/python -m evals.run_eval --suite chain --split dev
```

Expected: self-test 통과 → 봉인 첫 시도 통과(ledger `passed`) → dev 21문항(파일럿 3 제외
아님 — 전체 24 재실행) 채점, `as_of_violation 합계: 0`, 무효 케이스 ≤ 2, 리포트에 축 평균 +
uncovered_claim_ratio. 봉인 실패 시: 튜닝 fixture로 프롬프트 수정 → `JUDGE_PROMPT_VERSION`
증가 → 새 봉인 셋 → 재시도 (ledger가 이력 보존).

- [ ] **Step 5: Commit**

```bash
git -C /home/ryze_yn/attn-viewer add engine/evals/build_chain_cases.py engine/evals/golden_chain.jsonl engine/evals/bundles engine/evals/fixtures/chain_judge engine/evals/sealed_ledger.jsonl engine/evals/out/chain-*.jsonl engine/evals/out/chain-*.md engine/evals/README-chain.md
git -C /home/ryze_yn/attn-viewer commit -m 'feat(eval): chain 케이스 24 + bundle 캡처 + 봉인 통과 + dev 베이스라인'
```

---

### Task 9: golden 회귀 + codex 구현 리뷰

- [ ] **Step 1: golden 회귀 체크 (동일 코호트 10문항 — r2-B12)**

```bash
.venv/bin/python -m evals.run_eval --suite golden --check-regression
```

(`--check-regression`이 golden_baseline.json의 케이스 id 10개를 스스로 선택해 재실행 —
`--limit` 불필요.) Expected: keyword 퇴행 케이스 0 + verified 평균 하락 ≤ 0.15.
초과 시 exit 1 — bundle 모드 수정이 라이브 경로를 건드렸다는 뜻이므로 Task 5부터 조사.

- [ ] **Step 2: codex 리뷰** — `codex exec --sandbox read-only -C /home/ryze_yn/attn-viewer -o <scratchpad>/codex-p1-impl-review.md "스펙 1부 구현 리뷰: engine/evals/*, orchestrator·스테이지 bundle 모드, 베이스라인 리포트. 관점: as_of 누출 잔존 / 게이트 우회 가능성 / golden 회귀 / 스펙-구현 불일치. 블로커·권고 + 파일·라인."` → 블로커 반영 → 승인까지 왕복 (docs/memory-chain-review-p1-impl-*.md)
- [ ] **Step 3: 승인 후 베이스라인 수치를 유저에게 보고. 2부는 그 다음.**

---

## Self-Review 기록 (v4 — r3 잔존 6건 반영)

- B1: 무조건 허용 내부 태그 제거 — manifest에 news_ids·quote_symbols·macro_keys 등록,
  yahoo/macro 태그는 해당 채널 데이터 있을 때만 허용, 정확 URL·NewsItem ID 포함 (T4)
- B4: proven 불변식을 capture_bundle 코드로 강제 — 빈 채널은 empty_reasons 사유 필수,
  빈 proven 성공 테스트를 실패 테스트로 교체 (T0)
- B6: sealed_structure_errors — base 2 × 변형 5 = 정확 10개 게이트(실행기·생성기 양쪽),
  생성 스크립트 assert (T3·T7·T8)
- B7: run_sealed에 base 전제조건(verdict·countercase=1, evidence>0) — 항상-0 무감각
  저지 차단 (T3)
- B8: holdout 단독 실행 금지, experiment = 단일 명령 2-arm(disable_p23 토글 off/on)
  원자 실행, 첫 답변 전 claimed 기록. 2·3부 기능의 토글 가능성을 2·3부 계획 전역
  제약으로 승계 (T7)
- B10: row.split==args.split + proven이면 captured_at[:10]==as_of 검증 추가 (T7)

## Self-Review 기록 (v3 — r2 반영)

- B1: find_violations를 레이어 이름 열거가 아닌 **재귀 walk**로 전 증거 레이어 커버 +
  `[근거:토큰]` 검사(카드 ID·언론 도메인 태그·내부 태그 화이트리스트) (T4)
- B3: content_hash에 manifest 정규형 포함, `snapshot()`으로 quotes+macro 통합 주입 (T0·T4·T5)
- B4: proven 캡처는 `--auto-live` 필수(quotes·macro 자동 수집), 빈 RA는 사유 필수 (T0)
- B5: fixture를 실계약(quote token/last, NewsItem 생성 후 model_dump)으로 교체 (T5)
- B6: sealed ledger version당 hash 1개 — 파일 교체 재시도 차단. 봉인 생성기는 rubric·
  bundle_text를 원본(케이스+bundle)에서 직접 (T7·T8)
- B7: tamper가 인용 span 보호, make_sealed_set이 base 적합성(수치·countercase·인용 존재,
  변형 유효)을 생성 시 강제 (T3)
- B8: --compare 폐지 → 원자적 `--experiment` (candidate 실행+paired 비교+holdout 1회 소비),
  판정 미달 exit 1 (T7)
- B9: holdout experiment에서 uncovered_claim_ratio ≤ 0.2 게이트화 + 3부 전환 게이트
  (ChainPacket 이후 null 금지) 명시 (T7)
- B10: runner가 케이스마다 hash-bound manifest와 split·availability·as_of 상호 검증 (T7)
- B12: per-case 코호트(10문항 id별 verified·keyword) + 양축 퇴행 시 exit 1 (T0·T7·T9)
- N1: store 루프 변수 c/o 정정 (T0) / N2: --pilot dev+unproven 한정, experiment 조합 금지
  (T7) / N3: holdout 스키마 게이트(고유 proven ≥10 + 층화) (T7)

## Self-Review 기록 (v2)

- B1: find_violations가 실레이어(ra_x.items·sector_rag.cards)+답변 본문 검사, 위반 시 exit 1 (T4·T7)
- B2: knowledge_cutoff 덮어쓰기 + retrieve ref_now (T5)
- B3: macro 포함·content_hash·덮어쓰기 거부·bundle_text에 지표·가격 (T0·T4)
- B4: limit=100_000 명시 + 600건 테스트, capture CLI 인자 필수화 (T0)
- B5: PlanPacket 필수 필드(original_question·knowledge_cutoff)·direction="pos"·raw dict quotes·NewsItem 복원·(found,new_claims) 실변수 반영 (T0·T5)
- B6: 봉인 게이트를 실행기에 통합, ledger로 1회·첫 시도 강제, 빈 셋 거부 (T3·T7)
- B7: 스펙 변형 4종(flip_verdict·strip_countercase·ghost·tamper_numbers), verdict 축 재정의로 flip 판정 가능, 실제 합성 절 제목 사용 (T1·T2·T3)
- B8: 합집합 분모·축 키셋 검증·--compare 구현·holdout ledger·proven 강제·--limit 금지 (T6·T7)
- B9: uncovered_claim_ratio 구현, 점수 [0,1] 강제, entailed_edge_ratio는 null+사유(3부부터 — ChainPacket 부재로 물리적으로 산출 불가) (T1·T7)
- B10: proven은 as_of=오늘 강제, validate가 case↔manifest 교차 검증 (T0·T8)
- B11: Task 0에서 ingested_at+전향 캡처 즉시 가동 — holdout 10개는 2·3부 기간 축적(스펙 v5 그대로), 1부 완료 조건은 dev 베이스라인 (holdout은 4부 배포 판정용)
- B12: golden_baseline.json + --check-regression exit 1, git -C 경로 수정 전면 적용
- 권고1: raws 전량 보존 (T1) / 권고2: capture→rubric→validate 순서 (T8)
