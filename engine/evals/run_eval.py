"""평가 실행기 — golden suite + chain suite.

골든셋: `.venv/bin/python -m evals.run_eval --limit 5 --type fact_lookup`
체인:   `.venv/bin/python -m evals.run_eval --suite chain --split dev [--limit N] [--pilot]`
회귀:   `.venv/bin/python -m evals.run_eval --suite golden --check-regression`
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

from evals.metrics import keyword_check, question_metrics
from orchestrator import run_qa

_HERE = Path(__file__).parent

# ── 체인 케이스 번들 디렉토리 ──────────────────────────────────────────────────
_BUNDLES_DIR = _HERE / "bundles"
# 봉인 ledger / holdout ledger
_SEALED_LEDGER = _HERE / "sealed_ledger.jsonl"
_HOLDOUT_LEDGER = _HERE / "holdout_ledger.jsonl"

# holdout 스키마 게이트: 사건 유형 층화 4유형
_HOLDOUT_STRATA = frozenset(
    {"event_interpretation", "stock_judgment", "industry_analysis", "fact_lookup"}
)


# ─────────────────────────────────────────────────────────────────────────────
# golden suite 실행 (기존 경로 — 무변화)
# ─────────────────────────────────────────────────────────────────────────────


async def _one(row: dict) -> dict:
    layers, final = [], None
    async for ev in run_qa(row["question"], user_id=os.environ.get("EVAL_PLAYBOOK_USER", "")):
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


# ─────────────────────────────────────────────────────────────────────────────
# ledger 헬퍼
# ─────────────────────────────────────────────────────────────────────────────


def _load_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _append_ledger(path: Path, entry: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# 게이트 함수 (순수 로직은 테스트 가능하도록 분리)
# ─────────────────────────────────────────────────────────────────────────────


async def _gate_selftest(role) -> None:
    """self-test 실패 → exit 1, 채점 시작 안 함."""
    from evals.calibration import run_selftest
    from evals.chain_judge import judge_case as _jc

    async def _jfn(case_id, answer_md, rubric, bundle_text):
        return await _jc(case_id, answer_md, rubric, bundle_text, role)

    failures = await run_selftest(_jfn)
    if failures:
        print("[SELFTEST FAIL]", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)


def _load_sealed_file(version: str) -> list[dict]:
    """sealed-{version}.json 로드. 없거나 비면 exit 1."""
    p = _HERE / "fixtures" / "chain_judge" / f"sealed-{version}.json"
    if not p.exists():
        print(f"[SEALED] fixtures/chain_judge/sealed-{version}.json 없음 — "
              "봉인 파일을 생성하거나 JUDGE_PROMPT_VERSION을 올려라", file=sys.stderr)
        sys.exit(1)
    data = json.loads(p.read_text())
    if not data:
        print(f"[SEALED] sealed-{version}.json 비어 있음", file=sys.stderr)
        sys.exit(1)
    return data


def gate_sealed_check(version: str, current_hash: str,
                      current_judge_config_hash: str = "") -> str | None:
    """봉인 ledger (version, sealed_hash, judge_config_hash) 3-키 검증.

    반환:
      None   — ledger에 기록 없음 (새로 평가 필요)
      "ok"   — passed 기록 있음 (생략 가능)
      "fail" — failed 기록 있음 (exit 1)
      "hash_conflict" — 같은 version에 다른 sealed_hash (exit 1)

    judge_config_hash가 다른 과거 pass는 재사용하지 않고 None을 반환한다 — 모델·프롬프트
    설정이 바뀌면 봉인을 반드시 재실행해야 한다.
    """
    entries = _load_ledger(_SEALED_LEDGER)
    for e in entries:
        if e.get("version") != version:
            continue
        ledger_hash = e.get("hash")
        if ledger_hash != current_hash:
            return "hash_conflict"
        # judge_config_hash 불일치 → 재평가 필요 (설정이 바뀐 경우)
        if current_judge_config_hash and \
                e.get("judge_config_hash", "") != current_judge_config_hash:
            continue
        if e.get("result") == "passed":
            return "ok"
        if e.get("result") == "failed":
            return "fail"
    return None


async def _gate_sealed(role) -> tuple[str, list[dict]]:
    """봉인 게이트 통과 → (sealed_hash, sealed) 반환. 실패 시 exit 1."""
    from evals.calibration import (
        run_sealed,
        sealed_hash,
        sealed_structure_errors,
    )
    from evals.chain_judge import JUDGE_PROMPT_VERSION, judge_case as _jc
    from evals.chain_judge import judge_config_hash as _jch

    version = JUDGE_PROMPT_VERSION
    sealed = _load_sealed_file(version)

    errs = sealed_structure_errors(sealed)
    if errs:
        print("[SEALED] 구조 오류:", file=sys.stderr)
        for e in errs:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    shash = sealed_hash(sealed)
    jch = _jch(role)
    status = gate_sealed_check(version, shash, jch)

    if status == "hash_conflict":
        print(f"[SEALED] version={version}에 다른 hash가 이미 기록됨 — "
              "sealed 파일 교체로 재시도 금지. JUDGE_PROMPT_VERSION을 올려라",
              file=sys.stderr)
        sys.exit(1)
    if status == "fail":
        print(f"[SEALED] version={version} 이전 봉인 평가 failed — "
              "JUDGE_PROMPT_VERSION을 올려라", file=sys.stderr)
        sys.exit(1)
    if status == "ok":
        print(f"[SEALED] version={version} hash={shash} judge_config_hash={jch} — 이미 passed, 생략")
        return shash, sealed

    # 새로 평가
    async def _jfn(case_id, answer_md, rubric, bundle_text):
        return await _jc(case_id, answer_md, rubric, bundle_text, role)

    failures = await run_sealed(_jfn, sealed)
    result = "failed" if failures else "passed"
    _append_ledger(_SEALED_LEDGER, {
        "version": version, "hash": shash, "judge_config_hash": jch,
        "result": result,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "failures": failures,
    })
    if failures:
        print(f"[SEALED] version={version} FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)
    print(f"[SEALED] version={version} hash={shash} judge_config_hash={jch} — passed")
    return shash, sealed


def validate_holdout_schema(cases: list[dict]) -> list[str]:
    """holdout 스키마 검증 (순수 함수 — 단위 테스트 가능).

    반환: 오류 목록. 비어 있으면 통과.
    """
    errs: list[str] = []
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        errs.append(f"중복 id 존재: {len(ids) - len(set(ids))}개")
    unique_ids = list(set(ids))
    if len(unique_ids) < 10:
        errs.append(f"고유 id ≥ 10 필요 (현재 {len(unique_ids)})")
    not_proven = [c["id"] for c in cases if c.get("availability") != "proven"]
    if not_proven:
        errs.append(f"비proven 케이스 {len(not_proven)}개: {not_proven[:5]}")
    # 사건 유형 층화: event_type 필드 기준 (없으면 type 폴백)
    type_set: dict[str, int] = {}
    for c in cases:
        t = c.get("event_type") or c.get("type", "unknown")
        type_set[t] = type_set.get(t, 0) + 1
    missing_strata = _HOLDOUT_STRATA - set(type_set)
    if missing_strata:
        errs.append(f"층화 미달 유형: {sorted(missing_strata)}")
    return errs


def _gate_holdout(cases: list[dict], args: argparse.Namespace) -> None:
    """holdout 스키마 게이트. experiment 한정. 위반 시 exit 1."""
    if args.limit:
        print("[HOLDOUT] --limit은 holdout에 금지", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "pilot", False):
        print("[HOLDOUT] --pilot은 holdout에 금지", file=sys.stderr)
        sys.exit(1)
    errs = validate_holdout_schema(cases)
    if errs:
        print("[HOLDOUT] 스키마 게이트 미달:", file=sys.stderr)
        for e in errs:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)


def validate_holdout_id_set_fresh(id_set: frozenset[str]) -> list[str]:
    """holdout ledger에서 id 집합이 이미 claimed/consumed 됐는지 확인 (순수 함수).

    반환: 오류 목록. 비어 있으면 fresh.
    """
    errs: list[str] = []
    entries = _load_ledger(_HOLDOUT_LEDGER)
    for e in entries:
        prev_ids = frozenset(e.get("ids") or [])
        if prev_ids & id_set and e.get("status") in ("claimed", "consumed"):
            overlap = sorted(prev_ids & id_set)
            errs.append(
                f"id {len(overlap)}개가 이미 {e['status']} 집합과 교집합 "
                f"(experiment={e.get('experiment')}, ts={e.get('ts')}) — "
                f"부분 재사용 금지: {overlap[:5]}"
            )
    return errs


def _validate_case_manifest(case: dict, args: argparse.Namespace) -> list[str]:
    """케이스↔manifest 상호 검증 (순수 — bundle 로드 없이 구조만).

    실제 hash 검증은 EvalBundle.verify_hash()로 별도 수행.
    반환: 오류 목록.
    """
    from evals.bundle import EvalBundle, resolve_bundle_path

    errs: list[str] = []
    # bundle_path 필드가 있으면 resolver 사용(상대경로→evals 기준 절대화),
    # 없으면 _BUNDLES_DIR 기본값 (테스트가 monkeypatch하는 경로)
    bundle_path = (resolve_bundle_path(case)
                   if case.get("bundle_path")
                   else _BUNDLES_DIR / case["id"])
    if not bundle_path.exists():
        errs.append(f"{case['id']}: bundle 경로 없음: {bundle_path}")
        return errs
    try:
        eb = EvalBundle(bundle_path)
    except Exception as exc:
        errs.append(f"{case['id']}: bundle 로드 실패: {exc}")
        return errs

    manifest = eb.manifest
    if not eb.verify_hash():
        errs.append(f"{case['id']}: bundle content_hash 불일치 (변조 의심)")
    if case.get("availability") != manifest.get("availability"):
        errs.append(
            f"{case['id']}: case.availability={case.get('availability')} ≠ "
            f"manifest.availability={manifest.get('availability')}"
        )
    if case.get("as_of") != manifest.get("as_of"):
        errs.append(
            f"{case['id']}: case.as_of={case.get('as_of')} ≠ "
            f"manifest.as_of={manifest.get('as_of')}"
        )
    # proven이면 captured_at[:10] == as_of (회고 bundle proven 위장 차단)
    if manifest.get("availability") == "proven":
        captured_day = (manifest.get("captured_at") or "")[:10]
        as_of = manifest.get("as_of", "")
        if captured_day != as_of:
            errs.append(
                f"{case['id']}: proven인데 captured_at[:10]={captured_day} ≠ "
                f"as_of={as_of} (회고 bundle proven 위장 차단)"
            )
    return errs


def check_pilot_allowed(cases: list[dict], args: argparse.Namespace) -> list[str]:
    """pilot 제한 검증 (순수 함수 — 단위 테스트 가능).

    반환: 오류 목록.
    """
    errs: list[str] = []
    if getattr(args, "experiment", None):
        errs.append("--pilot은 --experiment와 조합 금지")
    if getattr(args, "split", "dev") != "dev":
        errs.append(f"--pilot은 --split dev에서만 허용 (현재 {args.split})")
    not_unproven = [c["id"] for c in cases if c.get("availability") != "unproven"]
    if not_unproven:
        errs.append(
            f"--pilot은 전 케이스 unproven일 때만 허용 — "
            f"proven 케이스 {len(not_unproven)}개: {not_unproven[:5]}"
        )
    return errs


# ─────────────────────────────────────────────────────────────────────────────
# check-regression 게이트
# ─────────────────────────────────────────────────────────────────────────────


async def _check_regression(args: argparse.Namespace) -> None:
    """golden_baseline.json 10개 케이스 재실행 후 keyword / verified 퇴행 체크.

    실행 레코드: evals/out/regression-{ts}.jsonl (케이스별 id, verified_ratio, keyword_ok, missing, must_not_hit, answer_md)
    """
    baseline_path = _HERE / "golden_baseline.json"
    if not baseline_path.exists():
        print("[REGRESSION] golden_baseline.json 없음", file=sys.stderr)
        sys.exit(1)
    baseline = json.loads(baseline_path.read_text())
    cases_baseline = baseline.get("cases", {})
    tolerance = baseline.get("tolerance", 0.15)
    golden_rows = [
        json.loads(l)
        for l in (_HERE / "golden.jsonl").read_text().splitlines()
        if l.strip()
    ]
    target_ids = set(cases_baseline)
    rows = [r for r in golden_rows if r["id"] in target_ids]
    found_ids = {r["id"] for r in rows}
    missing_ids = target_ids - found_ids
    if missing_ids:
        print(
            f"[REGRESSION] golden.jsonl에서 baseline id {len(missing_ids)}개 누락: "
            f"{sorted(missing_ids)}", file=sys.stderr
        )
        sys.exit(1)

    records = await _run_golden_rows(rows)

    # 회귀 레코드 저장 (케이스별 상세)
    out_dir = _HERE / "out"
    out_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    regression_records = []
    for rec in records:
        regression_records.append({
            'id': rec['id'],
            'verified_ratio': rec.get('verified_ratio'),
            'keyword_ok': rec.get('keyword_ok'),
            'missing': rec.get('missing', []),
            'must_not_hit': rec.get('must_not_hit', []),
            'answer_md': rec.get('answer_md', ''),
        })

    regression_path = out_dir / f'regression-{ts}.jsonl'
    with regression_path.open('w', encoding='utf-8') as f:
        for r in regression_records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    keyword_regressions = []
    verified_deltas = []
    case_missing_keywords = {}
    for rec in records:
        bid = rec["id"]
        if bid not in cases_baseline:
            continue
        b = cases_baseline[bid]
        if b.get("keyword_ok") is True and rec.get("keyword_ok") is False:
            keyword_regressions.append(bid)
            missing = rec.get('missing', [])
            if missing:
                case_missing_keywords[bid] = missing
        if b.get("verified_ratio") is not None:
            if rec.get("verified_ratio") is None:
                keyword_regressions.append(f"{bid}(verified_ratio→None)")
            else:
                verified_deltas.append(rec["verified_ratio"] - b["verified_ratio"])

    failed = False
    if keyword_regressions:
        print(f"[REGRESSION] keyword 퇴행 {len(keyword_regressions)}건: "
              f"{keyword_regressions}", file=sys.stderr)
        if case_missing_keywords:
            print(f"[REGRESSION] 케이스별 missing 키워드:", file=sys.stderr)
            for bid, missing in sorted(case_missing_keywords.items()):
                print(f"  {bid}: {missing}", file=sys.stderr)
        failed = True
    if verified_deltas:
        avg_delta = sum(verified_deltas) / len(verified_deltas)
        if avg_delta < -tolerance:
            print(
                f"[REGRESSION] verified_ratio 평균 하락 {avg_delta:.3f} > tolerance "
                f"{tolerance}", file=sys.stderr
            )
            failed = True
    if failed:
        sys.exit(1)
    print(f"[REGRESSION] PASS — {len(records)}건 확인, "
          f"keyword 퇴행 0, verified 평균 delta "
          f"{(sum(verified_deltas)/len(verified_deltas) if verified_deltas else 0):.3f}")
    print(f"[REGRESSION] 레코드 저장: {regression_path}")


async def _run_golden_rows(rows: list[dict]) -> list[dict]:
    results = []
    for row in rows:
        rec = await _one(row)
        results.append(rec)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# chain 케이스 로드
# ─────────────────────────────────────────────────────────────────────────────


_CHAIN_CASES_FILE = _HERE / "golden_chain.jsonl"


def _load_chain_cases(split: str) -> list[dict]:
    """golden_chain.jsonl 에서 케이스를 읽어 split 필터 후 반환.

    진실 원천: 케이스 row의 split 필드. split 필드가 없는 케이스는 스키마 위반 → exit 1.
    """
    if not _CHAIN_CASES_FILE.exists():
        return []
    cases = []
    for lineno, line in enumerate(_CHAIN_CASES_FILE.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"[CHAIN] golden_chain.jsonl:{lineno} JSON 파싱 실패: {exc}",
                  file=sys.stderr)
            sys.exit(1)
        if "split" not in row:
            print(
                f"[CHAIN] golden_chain.jsonl:{lineno} id={row.get('id', '?')} "
                "split 필드 없음 — 스키마 위반",
                file=sys.stderr,
            )
            sys.exit(1)
        if row["split"] != split:
            continue
        cases.append(row)
    return cases


# ─────────────────────────────────────────────────────────────────────────────
# chain suite 실행
# ─────────────────────────────────────────────────────────────────────────────


async def _run_one_chain(case: dict, role, *, arm: bool | None = None) -> dict:
    """케이스 1개 실행 — run_qa(bundle 모드) + judge_case + judge_claim_coverage.

    arm(B2 — 4부 2-arm 승계 좌석): None이면 overrides에 disable_p23을 넣지 않고
    (settings.disable_p23 기본값 경로), True/False면 명시적으로 병합한다.
    """
    from evals.bundle import EvalBundle, find_violations, resolve_bundle_path
    from evals.chain_judge import judge_case, judge_claim_coverage, judge_edge_entailment
    from evals.chain_judge import resolve_edge_evidence
    from evals.metrics import chain_axes_valid, chain_layer, grounded_edge_ratio

    # bundle_path 필드가 있으면 resolver 사용(상대경로→evals 기준 절대화),
    # 없으면 _BUNDLES_DIR 기본값
    bundle_path = (resolve_bundle_path(case)
                   if case.get("bundle_path")
                   else _BUNDLES_DIR / case["id"])
    eb = EvalBundle(bundle_path)
    bundle_text = eb.full_text()  # 위반 검사용 — 전체 본문 포함
    manifest = eb.manifest
    rubric = case.get("rubric") or {}

    overrides = {"eval_bundle": str(bundle_path)}
    if arm is not None:
        overrides["disable_p23"] = arm

    layers, final = [], None
    async for ev in run_qa(
        case["question"],
        overrides=overrides,
        user_id=os.environ.get("EVAL_PLAYBOOK_USER", ""),
    ):
        if ev.get("kind") == "layer":
            layers.append(ev)
        elif ev.get("kind") == "final":
            final = ev

    answer_md = (final or {}).get("answer", "")
    meta = (final or {}).get("meta") or {}

    # as_of 위반 (bundle URL·cite 토큰 위반 전체)
    as_of_viol, _, da_cited = find_violations(layers, answer_md, manifest, bundle_text)
    # must_not 키워드 검사 (케이스 스키마 — as_of_violations와 별도 필드)
    _, _, must_not_hit = keyword_check(answer_md, [], case.get("must_not", []))

    # 관련성 선발 컨텍스트 — head-truncate 아티팩트 해소 (judge 전용)
    judge_ctx = eb.judge_context(answer_md, rubric)

    raws_sink: list[str] = []
    judge_result = await judge_case(
        case["id"], answer_md, rubric, judge_ctx, role, raws_sink=raws_sink
    )
    claim_ratio = await judge_claim_coverage(
        case["id"], answer_md, judge_ctx, role, raws_sink=raws_sink
    )

    chain_axes: dict | None = None
    if judge_result is not None:
        chain_axes = {ax: judge_result.axes[ax].score for ax in judge_result.axes}

    chain_data = chain_layer(layers)
    entailed_ratio: float | None = None
    entailed_none_reason: str | None = None
    if chain_data is None:
        entailed_none_reason = "no_chain_layer"
    else:
        edges = chain_data.get("edges") or []
        # resolve_edge_evidence의 ValueError는 삼키지 않고 전파(r2-7 fail-hard —
        # run_chain_suite 실패로 이어진다).
        evidence_by_id = resolve_edge_evidence(edges, eb, layers)
        thesis_data = next((l.get("data") or {} for l in layers
                           if l.get("name") == "thesis"), {})
        thesis_claims = [p.get("claim") for p in (thesis_data.get("selected") or [])
                         if p.get("claim")]
        entailed_ratio = await judge_edge_entailment(
            case["id"], edges, evidence_by_id, role,
            thesis_claims=thesis_claims or None, raws_sink=raws_sink,
        )

    rec = {
        "id": case["id"],
        "split": case["split"],
        "availability": case["availability"],
        "chain_axes": chain_axes,
        "uncovered_claim_ratio": claim_ratio,
        "disable_p23": arm,
        "grounded_edge_ratio": grounded_edge_ratio(layers),
        "layers_had_chain": chain_data is not None,
        "entailed_edge_ratio": entailed_ratio,
        "judge_raws": raws_sink,
        "as_of_violations": as_of_viol,
        "da_cited": da_cited,
        "must_not_hit": must_not_hit,
        "answer_md": answer_md,
        "rubric": rubric,
        "bundle_text": bundle_text,
        **question_metrics(layers, meta),
    }
    if entailed_none_reason is not None:
        rec["entailed_none_reason"] = entailed_none_reason
    return rec


def check_entailed_gate(records: list[dict]) -> list[str]:
    """chain layer가 있는데 entailed_edge_ratio가 None인 케이스 id 목록 (순수 함수).

    3부 전환 게이트(1부 계획 1420행) — null 허용 종료(B9): run_chain_suite가
    비어있지 않으면 리포트 저장 후 exit 1."""
    return [r["id"] for r in records
            if r.get("layers_had_chain") and r.get("entailed_edge_ratio") is None]


async def _run_chain_cases(
    cases: list[dict],
    role,
    pilot: bool = False,
) -> list[dict]:
    records = []
    for case in cases:
        print(f"  [{case['id']}] running…")
        rec = await _run_one_chain(case, role)
        records.append(rec)
        ax_str = str(rec.get("chain_axes")) if not pilot else "(pilot — 비권위 채점)"
        print(f"  [{case['id']}] axes={ax_str} "
              f"uncovered={rec.get('uncovered_claim_ratio')} "
              f"violations={len(rec.get('as_of_violations', []))}")
    return records


def _save_chain_report(
    records: list[dict],
    ts: str,
    sealed_hash_val: str,
    code_sha: str,
    judge_version: str,
    pilot: bool = False,
) -> Path:
    from evals.chain_judge import AXES
    from evals.metrics import axis_mean

    prefix = "chain-pilot" if pilot else "chain"
    out_dir = _HERE / "out"
    out_dir.mkdir(exist_ok=True)

    jsonl_path = out_dir / f"report-{prefix}-{ts}.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    )

    lines = [
        f"# chain eval {ts} {'[PILOT]' if pilot else ''} — {len(records)}케이스",
        "",
        f"- code SHA: `{code_sha}`",
        f"- judge version: `{judge_version}`",
        f"- sealed_hash: `{sealed_hash_val}`",
        "",
        "## 축 평균",
    ]
    for ax in AXES:
        lines.append(f"- {ax}: {axis_mean(records, ax)}")
    uncov_vals = [r["uncovered_claim_ratio"] for r in records
                  if r.get("uncovered_claim_ratio") is not None]
    uncov_avg = round(sum(uncov_vals) / len(uncov_vals), 3) if uncov_vals else None
    lines.append(f"- uncovered_claim_ratio 평균: {uncov_avg}")

    total_viol = sum(len(r.get("as_of_violations", [])) for r in records)
    total_da_cited = sum(r.get("da_cited", 0) for r in records)
    must_not_total = sum(len(r.get("must_not_hit", [])) for r in records)
    invalid = sum(1 for r in records if r.get("chain_axes") is None)
    lines += [
        "",
        f"## 요약",
        f"- as_of 위반 합계: {total_viol}",
        f"- DA 별칭 인용 합계(da_cited): {total_da_cited}",
        f"- must_not 히트 합계: {must_not_total}",
        f"- 무효 케이스(chain_axes None): {invalid}",
        "",
        "## 케이스별 bundle content_hash",
    ]
    from evals.bundle import resolve_bundle_path
    for r in records:
        bid = r["id"]
        # resolve_bundle_path 사용 — bundle_path 필드 존중, CWD 독립
        case_stub = {"id": bid, "bundle_path": r.get("bundle_path")}
        bp = resolve_bundle_path(case_stub) / "manifest.json"
        ch = "N/A"
        if bp.exists():
            m = json.loads(bp.read_text())
            ch = m.get("content_hash", "N/A")
        lines.append(f"- {bid}: `{ch}`")

    lines += [
        "",
        "> **DA 인용(da_cited)은 frozen bundle 밖 파라메트릭 지식을 포함할 수 있으며, "
        "as_of_violation=0은 이를 부정하지 않는다. 저지 점수는 확률적 추정치다.",
    ]

    md_path = out_dir / f"report-{prefix}-{ts}.md"
    md_path.write_text("\n".join(lines))
    return jsonl_path


def _code_sha() -> str:
    """현재 run_eval.py + chain_judge.py + bundle.py SHA-256 (앞 12자).
    engine/ 작업 트리가 dirty이면 SHA에 -dirty 표기."""
    import subprocess
    h = hashlib.sha256()
    for p in [
        Path(__file__),
        Path(__file__).parent / "chain_judge.py",
        Path(__file__).parent / "bundle.py",
    ]:
        if p.exists():
            h.update(p.read_bytes())
    sha = h.hexdigest()[:12]
    try:
        repo_root = Path(__file__).parent.parent.parent  # engine/evals/ → engine/ → attn-viewer/
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "engine/"],
            capture_output=True, text=True, cwd=repo_root, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            sha += "-dirty"
    except Exception:
        pass
    return sha


async def run_chain_suite(args: argparse.Namespace) -> None:
    """--suite chain 실행기 — 게이트·채점·리포트 저장."""
    from evals.chain_judge import JUDGE_PROMPT_VERSION
    from providers import Role

    # experiment 분기 — arm 실행부 미구현 → 즉시 실패 (ledger 기록·게이트보다 먼저)
    if getattr(args, "experiment", None):
        print(
            "[CHAIN] --experiment 2-arm 실행부가 미구현입니다. "
            "(2·3부 disable_p23 토글 구현 후 활성화)",
            file=sys.stderr,
        )
        sys.exit(1)
        # stub 제거 시 이 return 위의 게이트 순서 유지 — freshness→_gate_holdout→claimed→arm 실행

    # --split holdout 단독 금지
    if getattr(args, "split", "dev") == "holdout" and not getattr(args, "experiment", None):
        print("[CHAIN] --split holdout은 --experiment와 함께만 허용 (r3-B8)", file=sys.stderr)
        sys.exit(1)

    role = Role("chain_judge")

    pilot = getattr(args, "pilot", False)
    shash = None

    # ── 게이트 1·2: pilot 모드는 채점 안 함 — self-test·sealed 스킵 ────────
    if not pilot:
        # ── 게이트 1: self-test ────────────────────────────────────────────────
        print("[GATE 1] self-test…")
        await _gate_selftest(role)
        print("[GATE 1] OK")

        # ── 게이트 2: 봉인 ────────────────────────────────────────────────────
        print("[GATE 2] sealed…")
        shash, _ = await _gate_sealed(role)
        print("[GATE 2] OK")
    else:
        print("[GATE 1·2] pilot 모드 — self-test·sealed 스킵")

    # ── 케이스 로드 ────────────────────────────────────────────────────────
    split = getattr(args, "split", "dev")
    cases = _load_chain_cases(split)
    if not cases:
        print(f"[CHAIN] golden_chain.jsonl에 split={split} 케이스 없음 — "
              "evals/build_chain_cases.py capture로 먼저 캡처하세요", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "limit", 0):
        cases = cases[: args.limit]

    # ── 게이트 5: pilot 제한 ──────────────────────────────────────────────
    if pilot:
        errs = check_pilot_allowed(cases, args)
        if errs:
            print("[GATE 5] pilot 제한 위반:", file=sys.stderr)
            for e in errs:
                print(f"  {e}", file=sys.stderr)
            sys.exit(1)

    # ── 게이트 4: 케이스↔manifest 상호 검증 (pilot 포함 항상 실행) ─────────
    print("[GATE 4] case↔manifest 검증…")
    all_errs = []
    for case in cases:
        errs = _validate_case_manifest(case, args)
        all_errs.extend(errs)
    if all_errs:
        print("[GATE 4] 상호 검증 실패:", file=sys.stderr)
        for e in all_errs:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)
    print("[GATE 4] OK")

    # ── 채점 루프 ─────────────────────────────────────────────────────────
    ts = time.strftime("%Y%m%d-%H%M%S")
    print(f"[CHAIN] {len(cases)}케이스 채점 시작 (split={split}, pilot={pilot})")
    records = await _run_chain_cases(cases, role, pilot=pilot)

    # ── 게이트 6·7 집계 ─────────────────────────────────────────────────────
    total_viol = sum(len(r.get("as_of_violations", [])) for r in records)
    must_not_total = sum(len(r.get("must_not_hit", [])) for r in records)

    # ── 리포트 저장 ───────────────────────────────────────────────────────
    code_sha = _code_sha()
    out_path = _save_chain_report(
        records, ts, shash, code_sha, JUDGE_PROMPT_VERSION, pilot=pilot
    )
    print(f"saved: {out_path}")

    # ── 게이트 7: 저지 유효율 (리포트 저장 후) ────────────────────────────
    if not pilot:
        non_null_count = sum(
            1 for r in records
            if r.get("chain_axes") and all(
                v is not None for v in r["chain_axes"].values()
            )
        )
        validity_ratio = non_null_count / len(records) if records else 0.0
        if validity_ratio < 0.9:
            print(
                f"[GATE 7] 저지 유효율 {validity_ratio:.3f} < 0.9 → exit 1",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── 게이트 6: 위반 시 exit 1 (리포트 저장 후) ──────────────────────────
    if not pilot and (total_viol > 0 or must_not_total > 0):
        print(
            f"[GATE 6] as_of 위반 {total_viol} + must_not 히트 {must_not_total} → exit 1",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── 게이트 8: entailed None (chain layer 있는데 미측정) — 3부 전환 게이트
    #    (1부 계획 1420행, B9). 리포트 저장 후 exit 1.
    if not pilot:
        entailed_none_ids = check_entailed_gate(records)
        if entailed_none_ids:
            print(
                f"[GATE 8] entailed_edge_ratio None (chain 有) {len(entailed_none_ids)}건 "
                f"→ exit 1: {entailed_none_ids}",
                file=sys.stderr,
            )
            sys.exit(1)

    print("[CHAIN] 완료")


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────


async def main() -> None:
    ap = argparse.ArgumentParser(
        description="평가 실행기 — golden suite / chain suite"
    )
    ap.add_argument("--suite", choices=["golden", "chain"], default="golden")
    ap.add_argument("--split", choices=["dev", "holdout"], default="dev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--type", default="", help="golden suite 질문 유형 필터")
    ap.add_argument("--pilot", action="store_true",
                    help="pilot 모드 — 판정·ledger 없이 입출력만 저장")
    ap.add_argument("--experiment", default="",
                    help="experiment 이름 (holdout 2-arm — 1부 미구현)")
    ap.add_argument("--check-regression", action="store_true",
                    help="golden_baseline.json 대비 회귀 검사")
    args = ap.parse_args()

    if args.suite == "chain":
        await run_chain_suite(args)
        return

    # ── golden suite (기존 경로) ─────────────────────────────────────────
    if args.check_regression:
        await _check_regression(args)
        return

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
