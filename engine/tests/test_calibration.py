import asyncio

from evals.calibration import load_tuning_fixtures, run_selftest, TRANSFORMS, make_sealed_set, run_sealed, sealed_hash
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


# ── Task 3: 봉인 metamorphic 셋 ──────────────────────────────────────────────

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

    assert asyncio.run(run_sealed(always_one, sealed))
