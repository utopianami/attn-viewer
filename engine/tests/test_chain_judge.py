# engine/tests/test_chain_judge.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from evals.chain_judge import AXES, ChainAxisScore, ChainJudgeResult, judge_case, merge_repeats


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


def test_raws_sink_captures_invalid_path(monkeypatch):
    """I-2: judge_case가 None을 반환하는 invalid 경로에서 sink가 채워지는지 확인."""
    # _judge_once가 항상 None을 반환하도록 monkeypatch
    monkeypatch.setattr(
        "evals.chain_judge._judge_once",
        AsyncMock(return_value=None),
    )
    sink: list[str] = []
    result = asyncio.run(
        judge_case("cj-test", "answer", {}, "bundle", object(), raws_sink=sink)
    )
    assert result is None                               # invalid → None 반환 불변
    assert len(sink) >= 1                              # sink에 최소 1건 기록
    assert all(s == "invalid" for s in sink)           # None 경로 → "invalid" 마커
