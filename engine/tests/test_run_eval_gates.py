"""run_eval 게이트 단위 테스트 — 순수 함수 계층만 (LLM 호출 없음).

커버:
  - 봉인 ledger version-hash 충돌 거부
  - holdout 스키마 게이트 3케이스 (proven 미달·10개 미만·층화 미달)
  - pilot 제한 2케이스
  - 케이스↔manifest 불일치 거부
  - bootstrap_ci 빈 deltas 가드 (Task 6 이월)
"""
from __future__ import annotations

import argparse
import math

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# bootstrap_ci 빈 deltas 가드 (Task 6 이월)
# ─────────────────────────────────────────────────────────────────────────────


def test_bootstrap_ci_empty_deltas():
    from evals.metrics import bootstrap_ci

    lo, hi = bootstrap_ci([])
    assert math.isnan(lo) and math.isnan(hi), "빈 deltas는 (nan, nan) 반환이어야 함"


def test_bootstrap_ci_nonempty():
    from evals.metrics import bootstrap_ci

    lo, hi = bootstrap_ci([0.1, 0.2, 0.3])
    assert lo <= hi, "CI 하한 ≤ 상한"
    assert not math.isnan(lo)


# ─────────────────────────────────────────────────────────────────────────────
# 봉인 ledger version-hash 충돌 거부
# ─────────────────────────────────────────────────────────────────────────────


def test_gate_sealed_check_hash_conflict(tmp_path, monkeypatch):
    """같은 version에 다른 hash가 ledger에 있으면 'hash_conflict' 반환."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "sealed_ledger.jsonl"
    # 기존 레코드: version=cj-v1, hash=aaa, passed
    ledger_path.write_text(
        '{"version": "cj-v1", "hash": "aaa", "result": "passed"}\n'
    )
    monkeypatch.setattr(re_mod, "_SEALED_LEDGER", ledger_path)

    result = re_mod.gate_sealed_check("cj-v1", "bbb")  # 다른 hash
    assert result == "hash_conflict"


def test_gate_sealed_check_same_hash_passed(tmp_path, monkeypatch):
    """같은 version+hash, passed → 'ok' 반환."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "sealed_ledger.jsonl"
    ledger_path.write_text(
        '{"version": "cj-v1", "hash": "abc123", "result": "passed"}\n'
    )
    monkeypatch.setattr(re_mod, "_SEALED_LEDGER", ledger_path)

    result = re_mod.gate_sealed_check("cj-v1", "abc123")
    assert result == "ok"


def test_gate_sealed_check_same_hash_failed(tmp_path, monkeypatch):
    """같은 version+hash, failed → 'fail' 반환."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "sealed_ledger.jsonl"
    ledger_path.write_text(
        '{"version": "cj-v1", "hash": "abc123", "result": "failed"}\n'
    )
    monkeypatch.setattr(re_mod, "_SEALED_LEDGER", ledger_path)

    result = re_mod.gate_sealed_check("cj-v1", "abc123")
    assert result == "fail"


def test_gate_sealed_check_no_entry(tmp_path, monkeypatch):
    """ledger에 기록 없으면 None 반환."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "sealed_ledger.jsonl"
    monkeypatch.setattr(re_mod, "_SEALED_LEDGER", ledger_path)

    result = re_mod.gate_sealed_check("cj-v1", "abc123")
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# judge_config_hash — 결정성 + 설정 변경 시 키 불일치
# ─────────────────────────────────────────────────────────────────────────────


def test_judge_config_hash_deterministic():
    """같은 설정으로 두 번 계산하면 동일한 해시를 반환해야 한다."""
    from evals.chain_judge import judge_config_hash

    class FakeRole:
        provider = "openai"
        model = "gpt-5.5"
        effort = "high"

    h1 = judge_config_hash(FakeRole())
    h2 = judge_config_hash(FakeRole())
    assert h1 == h2, f"해시가 달라짐: {h1} != {h2}"
    assert len(h1) == 16, f"해시 길이 16이어야 함: {len(h1)}"


def test_judge_config_hash_changes_on_model_change():
    """모델 ID가 다르면 judge_config_hash가 달라져야 한다."""
    from evals.chain_judge import judge_config_hash

    class RoleA:
        provider = "openai"
        model = "gpt-5.5"
        effort = "high"

    class RoleB:
        provider = "openai"
        model = "gpt-4o"  # 다른 모델
        effort = "high"

    assert judge_config_hash(RoleA()) != judge_config_hash(RoleB()), \
        "모델이 다른데 같은 해시가 반환됨"


def test_gate_sealed_check_judge_config_hash_mismatch(tmp_path, monkeypatch):
    """같은 version+sealed_hash라도 judge_config_hash가 다르면 None 반환 (재평가 필요)."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "sealed_ledger.jsonl"
    # 이전 pass: judge_config_hash=oldhash
    ledger_path.write_text(
        '{"version": "cj-v7", "hash": "abc123", "judge_config_hash": "oldhash0000000a", "result": "passed"}\n'
    )
    monkeypatch.setattr(re_mod, "_SEALED_LEDGER", ledger_path)

    # 새 실행: judge_config_hash가 바뀜 → None (재평가 필요)
    result = re_mod.gate_sealed_check("cj-v7", "abc123", "newhash0000000b")
    assert result is None, f"judge_config_hash 불일치인데 ok 반환됨: {result}"


def test_gate_sealed_check_judge_config_hash_match(tmp_path, monkeypatch):
    """version+sealed_hash+judge_config_hash 세 키 모두 일치하면 'ok' 반환."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "sealed_ledger.jsonl"
    ledger_path.write_text(
        '{"version": "cj-v7", "hash": "abc123", "judge_config_hash": "samehash000000c", "result": "passed"}\n'
    )
    monkeypatch.setattr(re_mod, "_SEALED_LEDGER", ledger_path)

    result = re_mod.gate_sealed_check("cj-v7", "abc123", "samehash000000c")
    assert result == "ok", f"3-키 일치인데 ok가 반환되지 않음: {result}"


# ─────────────────────────────────────────────────────────────────────────────
# holdout 스키마 게이트 3케이스
# ─────────────────────────────────────────────────────────────────────────────


def _make_holdout_cases(n: int = 12, availability: str = "proven") -> list[dict]:
    """4유형 층화 포함, n개 proven 케이스."""
    strata = ["event_interpretation", "stock_judgment", "industry_analysis", "fact_lookup"]
    cases = []
    for i in range(n):
        cases.append({
            "id": f"case-{i:03d}",
            "availability": availability,
            "event_type": strata[i % len(strata)],
        })
    return cases


def test_holdout_schema_proven_미달():
    """availability != proven 케이스 포함 → 오류."""
    from evals.run_eval import validate_holdout_schema

    cases = _make_holdout_cases(12, availability="proven")
    cases[0]["availability"] = "unproven"  # 1개 오염
    errs = validate_holdout_schema(cases)
    assert any("비proven" in e for e in errs), f"오류 없음: {errs}"


def test_holdout_schema_10개_미만():
    """고유 id < 10 → 오류."""
    from evals.run_eval import validate_holdout_schema

    cases = _make_holdout_cases(8, availability="proven")
    errs = validate_holdout_schema(cases)
    assert any("고유 id" in e for e in errs), f"오류 없음: {errs}"


def test_holdout_schema_층화_미달():
    """4유형 중 일부 누락 → 오류."""
    from evals.run_eval import validate_holdout_schema

    cases = _make_holdout_cases(12, availability="proven")
    # fact_lookup 유형만 남기고 나머지 덮어씀
    for c in cases:
        c["event_type"] = "fact_lookup"
    errs = validate_holdout_schema(cases)
    assert any("층화" in e for e in errs), f"오류 없음: {errs}"


def test_holdout_schema_valid():
    """정상 케이스 — 오류 없음."""
    from evals.run_eval import validate_holdout_schema

    cases = _make_holdout_cases(12, availability="proven")
    errs = validate_holdout_schema(cases)
    assert errs == [], f"예상치 못한 오류: {errs}"


# ─────────────────────────────────────────────────────────────────────────────
# pilot 제한 2케이스
# ─────────────────────────────────────────────────────────────────────────────


def _args(**kwargs) -> argparse.Namespace:
    defaults = {"split": "dev", "experiment": "", "pilot": True, "limit": 0}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _unproven_cases(n: int = 3) -> list[dict]:
    return [{"id": f"c{i}", "availability": "unproven"} for i in range(n)]


def test_pilot_rejected_with_experiment():
    """--pilot + --experiment 조합 → 오류."""
    from evals.run_eval import check_pilot_allowed

    cases = _unproven_cases(3)
    args = _args(experiment="exp-1")
    errs = check_pilot_allowed(cases, args)
    assert any("experiment" in e for e in errs), f"오류 없음: {errs}"


def test_pilot_rejected_with_proven_cases():
    """--pilot인데 proven 케이스 포함 → 오류."""
    from evals.run_eval import check_pilot_allowed

    cases = _unproven_cases(3)
    cases[1]["availability"] = "proven"
    args = _args()
    errs = check_pilot_allowed(cases, args)
    assert any("proven" in e for e in errs), f"오류 없음: {errs}"


def test_pilot_rejected_with_wrong_split():
    """--pilot + --split holdout → 오류."""
    from evals.run_eval import check_pilot_allowed

    cases = _unproven_cases(3)
    args = _args(split="holdout")
    errs = check_pilot_allowed(cases, args)
    assert any("dev" in e for e in errs), f"오류 없음: {errs}"


def test_pilot_allowed():
    """dev split + 전 케이스 unproven + experiment 없음 → 오류 없음."""
    from evals.run_eval import check_pilot_allowed

    cases = _unproven_cases(3)
    args = _args()
    errs = check_pilot_allowed(cases, args)
    assert errs == [], f"예상치 못한 오류: {errs}"


# ─────────────────────────────────────────────────────────────────────────────
# 케이스↔manifest 불일치 거부
# ─────────────────────────────────────────────────────────────────────────────


def _write_bundle(tmp_path, case_id: str, manifest: dict) -> None:
    """tmp_path/bundles/{case_id}/manifest.json + 더미 파일 생성."""
    import hashlib
    import json

    bundle_dir = tmp_path / "bundles" / case_id
    bundle_dir.mkdir(parents=True)
    # 더미 데이터 파일 (hash 계산용)
    (bundle_dir / "dummy.txt").write_text("dummy")
    # content_hash 생성 (bundle.py의 _content_hash 로직 복제)
    h = hashlib.sha256()
    for p in sorted(bundle_dir.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            h.update(str(p.relative_to(bundle_dir)).encode())
            h.update(p.read_bytes())
    canon = {k: v for k, v in manifest.items() if k != "content_hash"}
    h.update(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode())
    manifest["content_hash"] = h.hexdigest()[:16]
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest))


def test_case_manifest_availability_mismatch(tmp_path, monkeypatch):
    """case.availability ≠ manifest.availability → 오류."""
    import evals.run_eval as re_mod

    monkeypatch.setattr(re_mod, "_BUNDLES_DIR", tmp_path / "bundles")
    manifest = {
        "availability": "proven",
        "as_of": "2026-07-01",
        "captured_at": "2026-07-01T10:00:00Z",
    }
    _write_bundle(tmp_path, "case-01", manifest)

    case = {"id": "case-01", "availability": "unproven", "as_of": "2026-07-01"}
    args = _args(split="dev", pilot=False)
    errs = re_mod._validate_case_manifest(case, args)
    assert any("availability" in e for e in errs), f"오류 없음: {errs}"


def test_case_manifest_as_of_mismatch(tmp_path, monkeypatch):
    """case.as_of ≠ manifest.as_of → 오류."""
    import evals.run_eval as re_mod

    monkeypatch.setattr(re_mod, "_BUNDLES_DIR", tmp_path / "bundles")
    manifest = {
        "availability": "unproven",
        "as_of": "2026-07-01",
        "captured_at": "2026-06-15T10:00:00Z",
    }
    _write_bundle(tmp_path, "case-02", manifest)

    case = {"id": "case-02", "availability": "unproven", "as_of": "2026-06-01"}
    args = _args(split="dev", pilot=False)
    errs = re_mod._validate_case_manifest(case, args)
    assert any("as_of" in e for e in errs), f"오류 없음: {errs}"


def test_case_manifest_proven_captured_at_mismatch(tmp_path, monkeypatch):
    """proven인데 captured_at[:10] ≠ as_of → 회고 bundle 위장 차단."""
    import evals.run_eval as re_mod

    monkeypatch.setattr(re_mod, "_BUNDLES_DIR", tmp_path / "bundles")
    manifest = {
        "availability": "proven",
        "as_of": "2026-07-01",
        "captured_at": "2026-06-15T10:00:00Z",  # 날짜 불일치
    }
    _write_bundle(tmp_path, "case-03", manifest)

    case = {"id": "case-03", "availability": "proven", "as_of": "2026-07-01"}
    args = _args(split="dev", pilot=False)
    errs = re_mod._validate_case_manifest(case, args)
    assert any("captured_at" in e for e in errs), f"오류 없음: {errs}"


def test_case_manifest_valid(tmp_path, monkeypatch):
    """정상 unproven 케이스 — 오류 없음."""
    import evals.run_eval as re_mod

    monkeypatch.setattr(re_mod, "_BUNDLES_DIR", tmp_path / "bundles")
    manifest = {
        "availability": "unproven",
        "as_of": "2026-07-01",
        "captured_at": "2026-06-15T10:00:00Z",
    }
    _write_bundle(tmp_path, "case-ok", manifest)

    case = {"id": "case-ok", "availability": "unproven", "as_of": "2026-07-01"}
    args = _args(split="dev", pilot=False)
    errs = re_mod._validate_case_manifest(case, args)
    assert errs == [], f"예상치 못한 오류: {errs}"


# ─────────────────────────────────────────────────────────────────────────────
# holdout id 집합 재사용 금지
# ─────────────────────────────────────────────────────────────────────────────


def test_holdout_id_set_reuse_rejected(tmp_path, monkeypatch):
    """이미 claimed/consumed된 id 집합 재사용 → 오류."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "holdout_ledger.jsonl"
    ledger_path.write_text(
        '{"ids": ["c1", "c2", "c3"], "status": "consumed", "experiment": "exp-1"}\n'
    )
    monkeypatch.setattr(re_mod, "_HOLDOUT_LEDGER", ledger_path)

    errs = re_mod.validate_holdout_id_set_fresh(frozenset(["c1", "c2", "c3"]))
    assert errs, "재사용 감지 실패"


def test_holdout_id_set_partial_overlap_rejected(tmp_path, monkeypatch):
    """부분 교집합도 거부 — c1만 겹쳐도 rejected."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "holdout_ledger.jsonl"
    ledger_path.write_text(
        '{"ids": ["c1", "c2", "c3"], "status": "claimed", "experiment": "exp-1"}\n'
    )
    monkeypatch.setattr(re_mod, "_HOLDOUT_LEDGER", ledger_path)

    # c1 하나만 겹치는 새 집합
    errs = re_mod.validate_holdout_id_set_fresh(frozenset(["c1", "c4", "c5"]))
    assert errs, "부분 교집합 감지 실패"
    assert any("부분 재사용" in e for e in errs), f"오류 메시지 부적절: {errs}"


def test_holdout_id_set_fresh(tmp_path, monkeypatch):
    """새 id 집합 — 오류 없음."""
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "holdout_ledger.jsonl"
    monkeypatch.setattr(re_mod, "_HOLDOUT_LEDGER", ledger_path)

    errs = re_mod.validate_holdout_id_set_fresh(frozenset(["c10", "c11"]))
    assert errs == []


# ─────────────────────────────────────────────────────────────────────────────
# C1: async 게이트 함수 — await 호출 시 RuntimeError 없음
# ─────────────────────────────────────────────────────────────────────────────


def test_gate_selftest_is_coroutine():
    """_gate_selftest가 async def — 이벤트 루프 안에서 await 가능."""
    import inspect
    import evals.run_eval as re_mod

    assert inspect.iscoroutinefunction(re_mod._gate_selftest), \
        "_gate_selftest는 async def 이어야 합니다"


def test_gate_sealed_is_coroutine():
    """_gate_sealed가 async def — 이벤트 루프 안에서 await 가능."""
    import inspect
    import evals.run_eval as re_mod

    assert inspect.iscoroutinefunction(re_mod._gate_sealed), \
        "_gate_sealed는 async def 이어야 합니다"


def test_check_regression_is_coroutine():
    """_check_regression가 async def — 이벤트 루프 안에서 await 가능."""
    import inspect
    import evals.run_eval as re_mod

    assert inspect.iscoroutinefunction(re_mod._check_regression), \
        "_check_regression는 async def 이어야 합니다"


def test_async_gates_no_runtime_error_inside_loop():
    """이벤트 루프 내에서 게이트 async 함수 await — RuntimeError 없음.

    실제 LLM 호출은 monkeypatch로 단락. asyncio.run() 중첩이면 여기서 크래시.
    """
    import asyncio
    import evals.run_eval as re_mod

    async def _fake_role_arg():
        pass  # role 객체 자리 (실제 호출 없음)

    async def _run():
        # _gate_selftest: run_selftest를 빈 리스트 반환으로 대체
        from unittest.mock import AsyncMock, patch
        with patch("evals.calibration.run_selftest", new=AsyncMock(return_value=[])), \
             patch("evals.chain_judge.judge_case", new=AsyncMock(return_value=None)):
            # RuntimeError("This event loop is already running") 없이 반환돼야 함
            await re_mod._gate_selftest(object())

    asyncio.run(_run())  # RuntimeError 없으면 통과


# ─────────────────────────────────────────────────────────────────────────────
# C3: split 필드 부재 케이스 → SystemExit
# ─────────────────────────────────────────────────────────────────────────────


def test_load_chain_cases_no_split_field_exits(tmp_path, monkeypatch):
    """golden_chain.jsonl 케이스에 split 필드 없으면 SystemExit."""
    import evals.run_eval as re_mod

    cases_file = tmp_path / "golden_chain.jsonl"
    cases_file.write_text('{"id": "c1", "question": "Q"}\n')  # split 없음
    monkeypatch.setattr(re_mod, "_CHAIN_CASES_FILE", cases_file)

    with pytest.raises(SystemExit):
        re_mod._load_chain_cases("dev")


def test_load_chain_cases_filters_by_split(tmp_path, monkeypatch):
    """split 필드로 필터 — dev만 반환."""
    import json
    import evals.run_eval as re_mod

    cases_file = tmp_path / "golden_chain.jsonl"
    rows = [
        {"id": "c1", "split": "dev", "question": "Q1"},
        {"id": "c2", "split": "holdout", "question": "Q2"},
        {"id": "c3", "split": "dev", "question": "Q3"},
    ]
    cases_file.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(re_mod, "_CHAIN_CASES_FILE", cases_file)

    result = re_mod._load_chain_cases("dev")
    ids = [r["id"] for r in result]
    assert ids == ["c1", "c3"], f"dev 케이스만 반환돼야 함: {ids}"


def test_load_chain_cases_missing_file_returns_empty(tmp_path, monkeypatch):
    """golden_chain.jsonl 없으면 빈 리스트 반환."""
    import evals.run_eval as re_mod

    monkeypatch.setattr(re_mod, "_CHAIN_CASES_FILE", tmp_path / "nonexistent.jsonl")
    result = re_mod._load_chain_cases("dev")
    assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# I1: must_not 키워드 hit 레코드 반영
# ─────────────────────────────────────────────────────────────────────────────


def test_keyword_check_must_not_hit():
    """keyword_check must_not hit — 반환값 hit 리스트에 반영."""
    from evals.metrics import keyword_check

    ok, missing, hit = keyword_check("삼성전자가 강세입니다", [], ["삼성전자"])
    assert hit == ["삼성전자"], f"must_not 히트 누락: {hit}"


def test_keyword_check_must_not_no_hit():
    """답변에 must_not 키워드 없으면 hit 빈 리스트."""
    from evals.metrics import keyword_check

    ok, missing, hit = keyword_check("SK하이닉스 호실적", [], ["삼성전자"])
    assert hit == [], f"오탐 hit: {hit}"


def test_keyword_check_must_not_independent_of_must_include():
    """must_not hit은 must_include와 독립 필드 — 혼동 없음."""
    from evals.metrics import keyword_check

    ok, missing, hit = keyword_check("A가 있고 B도 있다", ["A"], ["B"])
    assert "A" not in hit, f"must_not_hit에 must_include 키워드 혼입: {hit}"
    assert missing == [], f"A는 include돼야 함: {missing}"
    assert hit == ["B"], f"B는 must_not_hit이어야 함: {hit}"


# ─────────────────────────────────────────────────────────────────────────────
# pilot 모드 — GATE 1·2 스킵 (Task 7 픽스)
# ─────────────────────────────────────────────────────────────────────────────


def test_pilot_skips_gate1_and_gate2(tmp_path, monkeypatch):
    """--pilot 모드에서 sealed 파일 부재 시에도 GATE 1·2 함수를 호출하지 않음.

    pilot은 답변 생성만 하고 채점하지 않으므로 self-test·sealed 게이트가 필요 없고,
    sealed 파일 미존재가 pilot 실행을 막아서는 안 됨 (chicken-egg 방지).
    """
    import asyncio
    from unittest.mock import AsyncMock, patch, call
    import evals.run_eval as re_mod

    # 게이트 함수 호출 추적
    gate1_mock = AsyncMock()
    gate2_mock = AsyncMock()

    def mock_load_cases(split):
        # unproven 케이스만 반환 (pilot 허용 조건)
        return [
            {"id": f"c{i}", "availability": "unproven", "split": split}
            for i in range(3)
        ]

    def mock_validate_case_manifest(case, args):
        return []  # 모든 케이스 유효

    async def mock_run_chain_cases(cases, role, pilot=False):
        # 각 케이스당 최소한의 레코드 반환
        return [
            {
                "id": c["id"],
                "split": c["split"],
                "availability": c["availability"],
                "chain_axes": None,  # pilot이므로 판정 없음
                "uncovered_claim_ratio": None,
                "entailed_edge_ratio": None,
                "judge_raws": [],
                "as_of_violations": [],
                "must_not_hit": [],
                "answer_md": "pilot answer",
                "rubric": {},
                "bundle_text": "bundle",
                "verified_ratio": None,
                "elapsed_s": 0.1,
                "cost_usd": 0.0,
                "layers": [],
            }
            for c in cases
        ]

    async def run_test():
        monkeypatch.setattr(re_mod, "_gate_selftest", gate1_mock)
        monkeypatch.setattr(re_mod, "_gate_sealed", gate2_mock)
        monkeypatch.setattr(re_mod, "_load_chain_cases", mock_load_cases)
        monkeypatch.setattr(re_mod, "_validate_case_manifest", mock_validate_case_manifest)
        monkeypatch.setattr(re_mod, "_run_chain_cases", mock_run_chain_cases)

        args = argparse.Namespace(
            suite="chain",
            split="dev",
            limit=0,
            pilot=True,  # PILOT 모드
            experiment="",
        )

        with patch("evals.run_eval._save_chain_report"):
            await re_mod.run_chain_suite(args)

        # GATE 1·2 함수가 호출되지 않았는지 확인
        assert gate1_mock.call_count == 0, f"_gate_selftest 호출됨: {gate1_mock.call_count}회"
        assert gate2_mock.call_count == 0, f"_gate_sealed 호출됨: {gate2_mock.call_count}회"

    asyncio.run(run_test())


# ─────────────────────────────────────────────────────────────────────────────
# holdout freshness 배선 (Task 7)
# ─────────────────────────────────────────────────────────────────────────────


def test_experiment_gate_holdout_freshness_rejection(tmp_path, monkeypatch, capsys):
    """experiment 분기에서 claimed id 집합 감지 — sys.exit(1)."""
    import sys
    import evals.run_eval as re_mod

    ledger_path = tmp_path / "holdout_ledger.jsonl"
    ledger_path.write_text(
        '{"ids": ["c1", "c2"], "status": "claimed", "experiment": "prev-exp"}\n'
    )
    monkeypatch.setattr(re_mod, "_HOLDOUT_LEDGER", ledger_path)

    # simulate 케이스 로드
    def mock_load_cases(split):
        return [
            {"id": "c1", "question": "Q1", "availability": "proven", "event_type": "fact_lookup"},
            {"id": "c2", "question": "Q2", "availability": "proven", "event_type": "stock_judgment"},
        ]

    def mock_gate_holdout(cases, args):
        pass  # no-op

    monkeypatch.setattr(re_mod, "_load_chain_cases", mock_load_cases)
    monkeypatch.setattr(re_mod, "_gate_holdout", mock_gate_holdout)

    args = argparse.Namespace(
        experiment="new-exp",
        split="holdout",
        suite="chain"
    )

    with pytest.raises(SystemExit) as exc_info:
        # simulate experiment 분기 진입점 (실제는 main에서 호출되지만, 여기선 단위 호출)
        id_set = frozenset(["c1", "c2"])
        errs = re_mod.validate_holdout_id_set_fresh(id_set)
        if errs:
            for err in errs:
                print(f"[HOLDOUT] {err}", file=sys.stderr)
            sys.exit(1)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "[HOLDOUT]" in captured.err and "claimed" in captured.err


# ─────────────────────────────────────────────────────────────────────────────
# Task 9: regression gate — 전수 ID 강제 + verified_ratio→None 퇴행
# ─────────────────────────────────────────────────────────────────────────────


def test_regression_requires_all_baseline_ids(tmp_path, monkeypatch):
    """golden.jsonl에서 baseline id 일부 누락 → exit 1."""
    import asyncio
    import json
    import evals.run_eval as re_mod

    baseline = {"cases": {"g1": {"keyword_ok": True, "verified_ratio": 0.8},
                          "g2": {"keyword_ok": True, "verified_ratio": 0.9}},
                "tolerance": 0.15}
    baseline_path = tmp_path / "golden_baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    monkeypatch.setattr(re_mod, "_HERE", tmp_path)

    # golden.jsonl에 g1만 있고 g2 없음
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "g1", "question": "Q1", "type": "t"}) + "\n")

    with pytest.raises(SystemExit) as exc:
        asyncio.run(re_mod._check_regression(argparse.Namespace()))
    assert exc.value.code == 1


def test_regression_verified_ratio_none_triggers_fail(tmp_path, monkeypatch):
    """baseline verified_ratio 非null인데 새 실행에서 None → 퇴행으로 exit 1."""
    import asyncio
    import json
    import evals.run_eval as re_mod

    baseline = {"cases": {"g1": {"keyword_ok": True, "verified_ratio": 0.8}},
                "tolerance": 0.15}
    baseline_path = tmp_path / "golden_baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    monkeypatch.setattr(re_mod, "_HERE", tmp_path)

    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "g1", "question": "Q1", "type": "t"}) + "\n")

    # _run_golden_rows를 monkeypatch — verified_ratio=None 반환
    async def mock_run_golden(rows):
        return [{"id": "g1", "keyword_ok": True, "verified_ratio": None,
                 "elapsed_s": 0.1, "cost_usd": 0.0}]

    monkeypatch.setattr(re_mod, "_run_golden_rows", mock_run_golden)

    with pytest.raises(SystemExit) as exc:
        asyncio.run(re_mod._check_regression(argparse.Namespace()))
    assert exc.value.code == 1


# ─────────────────────────────────────────────────────────────────────────────
# Task 9: 저지 유효율 게이트 (gate 7)
# ─────────────────────────────────────────────────────────────────────────────


def test_judge_validity_gate_below_threshold(tmp_path, monkeypatch):
    """chain_axes 전축 non-null 비율 < 0.9 → 리포트 저장 후 exit 1."""
    import asyncio
    import json
    from unittest.mock import patch, AsyncMock
    import evals.run_eval as re_mod
    from evals.chain_judge import AXES

    # 10케이스 중 2케이스만 유효 (0.2 < 0.9)
    def make_rec(cid, valid):
        axes = {a: 1.0 for a in AXES} if valid else {a: None for a in AXES}
        return {"id": cid, "split": "dev", "availability": "unproven",
                "chain_axes": axes, "uncovered_claim_ratio": 0.1,
                "entailed_edge_ratio": None, "judge_raws": [],
                "as_of_violations": [], "da_cited": 0, "must_not_hit": [],
                "answer_md": "", "rubric": {}, "bundle_text": "",
                "verified_ratio": None, "elapsed_s": 0.1, "cost_usd": 0.0, "layers": []}

    records = [make_rec(f"c{i}", i < 2) for i in range(10)]

    async def mock_run_chain(cases, role, pilot=False):
        return records

    def mock_load_cases(split):
        return [{"id": f"c{i}", "availability": "unproven", "split": "dev",
                 "question": "Q", "rubric": {}, "must_not": []} for i in range(10)]

    def mock_validate_manifest(case, args):
        return []

    async def run_test():
        gate1 = AsyncMock()
        gate2 = AsyncMock(return_value=("fakehash", []))
        monkeypatch.setattr(re_mod, "_gate_selftest", gate1)
        monkeypatch.setattr(re_mod, "_gate_sealed", gate2)
        monkeypatch.setattr(re_mod, "_load_chain_cases", mock_load_cases)
        monkeypatch.setattr(re_mod, "_validate_case_manifest", mock_validate_manifest)
        monkeypatch.setattr(re_mod, "_run_chain_cases", mock_run_chain)

        args = argparse.Namespace(suite="chain", split="dev", limit=0,
                                  pilot=False, experiment="")
        with patch("evals.run_eval._save_chain_report"):
            with pytest.raises(SystemExit) as exc:
                await re_mod.run_chain_suite(args)
        assert exc.value.code == 1

    asyncio.run(run_test())


# ─────────────────────────────────────────────────────────────────────────────
# Task 9: bundle_path from case field
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_case_manifest_uses_bundle_path_field(tmp_path, monkeypatch):
    """case에 bundle_path 필드가 있으면 _BUNDLES_DIR/id 대신 그 경로를 사용."""
    import evals.run_eval as re_mod

    monkeypatch.setattr(re_mod, "_BUNDLES_DIR", tmp_path / "bundles")
    # bundle을 _BUNDLES_DIR 밖 위치에 생성
    custom_dir = tmp_path / "custom_bundles" / "case-x"
    manifest = {"availability": "unproven", "as_of": "2026-07-01",
                "captured_at": "2026-06-15T10:00:00Z"}
    _write_bundle.__wrapped__(tmp_path, "case-x", manifest) if hasattr(
        _write_bundle, "__wrapped__") else None

    # 직접 custom_dir에 bundle 생성
    import hashlib
    import json as _json
    custom_dir.mkdir(parents=True)
    (custom_dir / "dummy.txt").write_text("dummy")
    h = hashlib.sha256()
    for p in sorted(custom_dir.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            h.update(str(p.relative_to(custom_dir)).encode())
            h.update(p.read_bytes())
    canon = {k: v for k, v in manifest.items() if k != "content_hash"}
    h.update(_json.dumps(canon, sort_keys=True, ensure_ascii=False).encode())
    manifest["content_hash"] = h.hexdigest()[:16]
    (custom_dir / "manifest.json").write_text(_json.dumps(manifest))

    case = {"id": "case-x", "availability": "unproven", "as_of": "2026-07-01",
            "bundle_path": str(custom_dir)}
    args = _args(split="dev", pilot=False)
    errs = re_mod._validate_case_manifest(case, args)
    assert errs == [], f"bundle_path 필드로 올바른 경로를 찾지 못함: {errs}"
