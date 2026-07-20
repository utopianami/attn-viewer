import asyncio

from evals.calibration import (load_tuning_fixtures, run_selftest, TRANSFORMS,
                               make_sealed_set, run_sealed, sealed_hash,
                               sealed_structure_errors, counter_leak_terms)
from evals.chain_judge import AXES, ChainAxisScore, ChainJudgeResult


def _mk(case_id, scores):
    axes = {a: ChainAxisScore(score=scores.get(a, 1.0), reason="") for a in AXES}
    return ChainJudgeResult(case_id=case_id, axes=axes, raws=["{}"],
                            judge_model="fake", judge_prompt_version="cj-v1")


def test_fixtures_load_shape_and_synth_format():
    fx = load_tuning_fixtures()
    assert len(fx) == 7
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


# ── Task 3: 봉인 metamorphic 셋 ──────────────────────────────────────────────

def _base():
    # counter-leak 없는 깨끗한 strip_countercase 산출물 보장 (위험·반대 절에만 반대 신호 어휘)
    return {"id": "b1",
            "answer_md": ("## 결론\n긍정적이다.\n\n"
                          "HBM 수요가 강하다 [근거:c-1].\n"
                          "수출 YoY +34%가 이를 뒷받침한다 [근거:m-1].\n\n"
                          "## 위험·반대 시나리오\nCAPEX 하향 시 부정적 [근거:c-2]."),
            "rubric": {"mechanism": "m", "state_link": "s", "verdict": "v",
                       "evidence": ["HBM", "수출"], "countercase": "c"},
            "bundle_text": "c-1: HBM 수요 보도. m-1: 수출 YoY +34%. c-2: CAPEX 하향."}


def _base2():
    # counter-leak 없는 깨끗한 strip_countercase 산출물 보장
    return {"id": "b2",
            "answer_md": ("## 결론\n부정적이지 않다.\n\n"
                          "DRAM 가격이 강하다 [근거:d-1].\n"
                          "영업이익 QoQ +18%가 이를 뒷받침한다 [근거:e-1].\n\n"
                          "## 위험·반대 시나리오\n재고 증가 시 약하다 [근거:d-2]."),
            "rubric": {"mechanism": "m2", "state_link": "s2", "verdict": "v2",
                       "evidence": ["DRAM", "영업이익"], "countercase": "c2"},
            "bundle_text": "d-1: DRAM 가격 보도. e-1: 영업이익 QoQ +18%. d-2: 재고 증가."}


def test_transforms_flip_and_tamper():
    """cj-v7: TRANSFORMS 4종 — flip_verdict·strip_countercase·tamper_numbers·identity."""
    b = _base()
    md, rubric = b["answer_md"], b["rubric"]
    assert "부정적이다" in TRANSFORMS["flip_verdict"](md, rubric)       # 방향 반전 (스펙)
    assert "+34%" not in TRANSFORMS["tamper_numbers"](md, rubric)       # 수치 변조 (스펙)
    assert "## 위험·반대 시나리오" not in TRANSFORMS["strip_countercase"](md, rubric)
    assert TRANSFORMS["identity"](md, rubric) == md                     # 동일 반환
    # strip_evidence는 cj-v7에서 TRANSFORMS에 없음
    assert "strip_evidence" not in TRANSFORMS, "cj-v7: strip_evidence는 봉인 변형에서 제거됨"


def test_counter_leak_terms_detection():
    """strip_countercase 산출물에 반대 신호 어휘가 있으면 검출."""
    md_with_leak = "HBM 수요가 강하다. 다만 하락 리스크가 존재한다."
    md_clean = "HBM 수요가 강하다. 전반적으로 긍정적이다."
    found = counter_leak_terms(md_with_leak)
    assert found, f"반대 신호 어휘가 검출되지 않음: {found}"
    assert any(t in found for t in ["하락", "리스크"]), f"예상 어휘 누락: {found}"
    assert counter_leak_terms(md_clean) == [], f"클린 텍스트에서 오탐: {counter_leak_terms(md_clean)}"


def test_make_sealed_set_counter_leak_raises():
    """본문(위험·반대 절 밖)에 반대 신호 어휘가 남으면 make_sealed_set에서 ValueError."""
    import pytest
    leak_base = {"id": "leak1",
                 "answer_md": ("## 결론\n긍정적이다. 단 하락 우려가 있다.\n\n"
                               "수출 YoY +34% [근거:m-1].\n\n"
                               "## 위험·반대 시나리오\nCAPEX 하향 [근거:c-2]."),
                 "rubric": {"evidence": ["수출"], "countercase": "c"},
                 "bundle_text": "m-1: 수출 YoY +34%. c-2: CAPEX."}
    with pytest.raises(ValueError, match="counter-leak 어휘"):
        make_sealed_set([leak_base], version="test")


def test_sealed_set_shape_and_hash_stability():
    """cj-v7: base 1개 × 변형 4종 = 4항목. 해시 안정성 확인."""
    s1 = make_sealed_set([_base()], version="cj-v7")
    s2 = make_sealed_set([_base()], version="cj-v7")
    assert len(s1) == 4 and sealed_hash(s1) == sealed_hash(s2)


def test_sealed_structure_gate():
    """cj-v7: 4항목 셋(base 1개)은 sealed_structure_errors가 에러를 반환해야 한다."""
    sealed = make_sealed_set([_base()], version="cj-v7")
    assert len(sealed) == 4
    errs = sealed_structure_errors(sealed)
    assert errs, "구조 게이트가 4항목 셋(base 1개)을 통과시켜서는 안 됨"


def test_sealed_structure_gate_8_items():
    """cj-v7: base 2개 × 변형 4종 = 정확히 8항목 → 구조 게이트 통과."""
    sealed = make_sealed_set([_base(), _base2()], version="cj-v7")
    assert len(sealed) == 8, f"8항목이어야 함 (현재 {len(sealed)})"
    errs = sealed_structure_errors(sealed)
    assert errs == [], f"8항목 셋은 구조 게이트를 통과해야 함: {errs}"


def test_run_sealed_catches_insensitive_judge():
    """always-one 저지가 기대 관계 실패(score 비교)를 반환하는지 확인.
    cj-v7: base 2개 × 변형 4종 = 8개 셋으로 구조 게이트 통과 후 저지 평가 루프 진입.
    """
    sealed = make_sealed_set([_base(), _base2()], version="cj-v7")
    assert len(sealed) == 8, "base 2개로 8개 sealed 셋 생성 필요"

    async def always_one(cid, ans, rub, btxt):
        axes = {a: ChainAxisScore(score=1.0, reason="") for a in AXES}
        return ChainJudgeResult(case_id=cid, axes=axes, raws=["{}"],
                                judge_model="fake", judge_prompt_version="cj-v7")

    failures = asyncio.run(run_sealed(always_one, sealed))
    assert failures, "always-one 저지는 반드시 실패를 반환해야 함"
    # 구조 오류 문구가 아니라 관계 실패 문구가 포함되어야 함
    relation_failures = [f for f in failures
                         if "expected 0 got" in f or "expected <" in f]
    assert relation_failures, (
        f"관계 실패 문구('expected 0 got' 또는 'expected <')가 없음. "
        f"실제 failures: {failures}"
    )
