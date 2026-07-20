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


def gate_sealed_check(version: str, current_hash: str) -> str | None:
    """봉인 ledger version-hash 검증.

    반환:
      None   — ledger에 기록 없음 (새로 평가 필요)
      "ok"   — passed 기록 있음 (생략 가능)
      "fail" — failed 기록 있음 (exit 1)
      "hash_conflict" — 같은 version에 다른 hash (exit 1)
    """
    entries = _load_ledger(_SEALED_LEDGER)
    for e in entries:
        if e.get("version") != version:
            continue
        ledger_hash = e.get("hash")
        if ledger_hash != current_hash:
            return "hash_conflict"
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

    version = JUDGE_PROMPT_VERSION
    sealed = _load_sealed_file(version)

    errs = sealed_structure_errors(sealed)
    if errs:
        print("[SEALED] 구조 오류:", file=sys.stderr)
        for e in errs:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    shash = sealed_hash(sealed)
    status = gate_sealed_check(version, shash)

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
        print(f"[SEALED] version={version} hash={shash} — 이미 passed, 생략")
        return shash, sealed

    # 새로 평가
    async def _jfn(case_id, answer_md, rubric, bundle_text):
        return await _jc(case_id, answer_md, rubric, bundle_text, role)

    failures = await run_sealed(_jfn, sealed)
    result = "failed" if failures else "passed"
    _append_ledger(_SEALED_LEDGER, {
        "version": version, "hash": shash, "result": result,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "failures": failures,
    })
    if failures:
        print(f"[SEALED] version={version} FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)
    print(f"[SEALED] version={version} hash={shash} — passed")
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
        if prev_ids == id_set and e.get("status") in ("claimed", "consumed"):
            errs.append(
                f"id 집합이 이미 {e['status']} (experiment={e.get('experiment')}, "
                f"ts={e.get('ts')}) — 재사용 금지"
            )
    return errs


def _validate_case_manifest(case: dict, args: argparse.Namespace) -> list[str]:
    """케이스↔manifest 상호 검증 (순수 — bundle 로드 없이 구조만).

    실제 hash 검증은 EvalBundle.verify_hash()로 별도 수행.
    반환: 오류 목록.
    """
    from evals.bundle import EvalBundle

    errs: list[str] = []
    bundle_path = _BUNDLES_DIR / case["id"]
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
    """golden_baseline.json 10개 케이스 재실행 후 keyword / verified 퇴행 체크."""
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
    if not rows:
        print("[REGRESSION] golden.jsonl에서 baseline id 없음", file=sys.stderr)
        sys.exit(1)

    records = await _run_golden_rows(rows)

    keyword_regressions = []
    verified_deltas = []
    for rec in records:
        bid = rec["id"]
        if bid not in cases_baseline:
            continue
        b = cases_baseline[bid]
        if b.get("keyword_ok") is True and rec.get("keyword_ok") is False:
            keyword_regressions.append(bid)
        if b.get("verified_ratio") is not None and rec.get("verified_ratio") is not None:
            verified_deltas.append(rec["verified_ratio"] - b["verified_ratio"])

    failed = False
    if keyword_regressions:
        print(f"[REGRESSION] keyword 퇴행 {len(keyword_regressions)}건: "
              f"{keyword_regressions}", file=sys.stderr)
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


async def _run_one_chain(case: dict, role) -> dict:
    """케이스 1개 실행 — run_qa(bundle 모드) + judge_case + judge_claim_coverage."""
    from evals.bundle import EvalBundle, find_violations
    from evals.chain_judge import judge_case, judge_claim_coverage
    from evals.metrics import chain_axes_valid

    bundle_path = _BUNDLES_DIR / case["id"]
    eb = EvalBundle(bundle_path)
    bundle_text = eb.bundle_text()
    manifest = eb.manifest
    rubric = case.get("rubric") or {}

    layers, final = [], None
    async for ev in run_qa(
        case["question"],
        overrides={"eval_bundle": str(bundle_path)},
        user_id=os.environ.get("EVAL_PLAYBOOK_USER", ""),
    ):
        if ev.get("kind") == "layer":
            layers.append(ev)
        elif ev.get("kind") == "final":
            final = ev

    answer_md = (final or {}).get("answer", "")
    meta = (final or {}).get("meta") or {}

    # as_of 위반 (bundle URL·cite 토큰 위반 전체)
    as_of_viol = find_violations(layers, answer_md, manifest)
    # must_not 키워드 검사 (케이스 스키마 — as_of_violations와 별도 필드)
    _, _, must_not_hit = keyword_check(answer_md, [], case.get("must_not", []))

    raws_sink: list[str] = []
    judge_result = await judge_case(
        case["id"], answer_md, rubric, bundle_text, role, raws_sink=raws_sink
    )
    claim_ratio = await judge_claim_coverage(
        case["id"], answer_md, bundle_text, role, raws_sink=raws_sink
    )

    chain_axes: dict | None = None
    if judge_result is not None:
        chain_axes = {ax: judge_result.axes[ax].score for ax in judge_result.axes}

    rec = {
        "id": case["id"],
        "split": case["split"],
        "availability": case["availability"],
        "chain_axes": chain_axes,
        "uncovered_claim_ratio": claim_ratio,
        "entailed_edge_ratio": None,  # 3부부터 (ChainPacket 미구현)
        "judge_raws": raws_sink,
        "as_of_violations": as_of_viol,
        "must_not_hit": must_not_hit,
        "answer_md": answer_md,
        "rubric": rubric,
        "bundle_text": bundle_text,
        **question_metrics(layers, meta),
    }
    return rec


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
        ax_str = str(rec.get("chain_axes")) if not pilot else "(pilot — 판정 없음)"
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
    must_not_total = sum(len(r.get("must_not_hit", [])) for r in records)
    invalid = sum(1 for r in records if r.get("chain_axes") is None)
    lines += [
        "",
        f"## 요약",
        f"- as_of 위반 합계: {total_viol}",
        f"- must_not 히트 합계: {must_not_total}",
        f"- 무효 케이스(chain_axes None): {invalid}",
        "",
        "## 케이스별 bundle content_hash",
    ]
    for r in records:
        bid = r["id"]
        bp = _BUNDLES_DIR / bid / "manifest.json"
        ch = "N/A"
        if bp.exists():
            m = json.loads(bp.read_text())
            ch = m.get("content_hash", "N/A")
        lines.append(f"- {bid}: `{ch}`")

    lines += [
        "",
        "> **DA 파라메트릭 잔여 위험**: 저지 점수는 확률적 추정치이며 실측 확률이 아닙니다. "
        "bootstrap CI는 표본 재표집 분산을 나타내며 모델 사전 분포·프롬프트 민감도 불확실성은 포함하지 않습니다.",
    ]

    md_path = out_dir / f"report-{prefix}-{ts}.md"
    md_path.write_text("\n".join(lines))
    return jsonl_path


def _code_sha() -> str:
    """현재 run_eval.py + chain_judge.py SHA-256 (앞 12자)."""
    h = hashlib.sha256()
    for p in [Path(__file__), Path(__file__).parent / "chain_judge.py"]:
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


async def run_chain_suite(args: argparse.Namespace) -> None:
    """--suite chain 실행기 — 게이트·채점·리포트 저장."""
    from evals.chain_judge import JUDGE_PROMPT_VERSION
    from providers import Role

    # experiment 분기 — 1부에서는 불가 (게이트·claimed ledger는 먼저 실행)
    if getattr(args, "experiment", None):
        # 케이스 로드 (게이트·ledger 기록을 위해 먼저 수행)
        _exp_split = getattr(args, "split", "dev")
        _exp_cases = _load_chain_cases(_exp_split)
        # holdout 게이트 (답변 생성 전)
        _gate_holdout(_exp_cases, args)
        # claimed ledger 기록 (답변 생성 전 — 2부에서 arm 채울 때 이미 무장 상태)
        _append_ledger(_HOLDOUT_LEDGER, {
            "ids": [c["id"] for c in _exp_cases],
            "status": "claimed",
            "experiment": args.experiment,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        print(
            "[CHAIN] --experiment는 2·3부 disable_p23 토글 대상이 미구현인 1부 시점에서 "
            "실행할 수 없습니다. dev split에서 베이스라인을 먼저 측정하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    # --split holdout 단독 금지
    if getattr(args, "split", "dev") == "holdout" and not getattr(args, "experiment", None):
        print("[CHAIN] --split holdout은 --experiment와 함께만 허용 (r3-B8)", file=sys.stderr)
        sys.exit(1)

    role = Role("chain_judge")

    # ── 게이트 1: self-test ────────────────────────────────────────────────
    print("[GATE 1] self-test…")
    await _gate_selftest(role)
    print("[GATE 1] OK")

    # ── 게이트 2: 봉인 ────────────────────────────────────────────────────
    print("[GATE 2] sealed…")
    shash, _ = await _gate_sealed(role)
    print("[GATE 2] OK")

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
    pilot = getattr(args, "pilot", False)
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

    # ── 게이트 6: 위반 시 exit 1 ──────────────────────────────────────────
    total_viol = sum(len(r.get("as_of_violations", [])) for r in records)
    must_not_total = sum(len(r.get("must_not_hit", [])) for r in records)

    # ── 리포트 저장 ───────────────────────────────────────────────────────
    code_sha = _code_sha()
    out_path = _save_chain_report(
        records, ts, shash, code_sha, JUDGE_PROMPT_VERSION, pilot=pilot
    )
    print(f"saved: {out_path}")

    # 위반 gate (리포트 저장 후)
    if not pilot and (total_viol > 0 or must_not_total > 0):
        print(
            f"[GATE 6] as_of 위반 {total_viol} + must_not 히트 {must_not_total} → exit 1",
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
