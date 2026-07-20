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
