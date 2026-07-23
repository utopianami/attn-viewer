"""casemem 평가 골드셋 러너 — 국면매칭 실측(서베이 P1: LLM 리랭커를 믿지 말고 골드셋으로).

메트릭: hit@1 / hit@3 / MRR / 국면 정확도 / 룩어헤드 위반(forbid는 하드 게이트).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.seeds import load_seeds
from casemem.store import CaseStore
from evals.casemem_eval import GOLDSET_PATH, evaluate_rows, load_goldset


@pytest.fixture()
def store(tmp_path):
    cs = CaseStore(tmp_path)
    load_seeds(cs)
    return cs


def test_hit_and_phase_match(store):
    # 2018-10 시점: "기록 실적 + 재고조정 시작" → 슈퍼사이클 크래시 p2가 1위여야
    rows = [{
        "qid": "t1", "sector": "memory", "as_of": "2018-10-01",
        "signals": ["기록적 실적 발표", "고객 재고조정 시작 언급", "NAND 가격 하락"],
        "expect_top": "mem-2016-2019-supercycle-crash", "expect_phase": 2,
    }]
    summary, results = evaluate_rows(store, rows, k=5)
    assert summary["n"] == 1
    assert summary["hit@1"] == 1.0
    assert summary["hit@3"] == 1.0
    assert summary["mrr"] == 1.0
    assert summary["phase_acc"] == 1.0
    assert summary["forbid_violations"] == 0
    assert results[0]["rank"] == 1


def test_miss_scores_zero(store):
    rows = [{
        "qid": "t2", "sector": "memory", "as_of": "2018-10-01",
        "signals": ["기록적 실적", "재고조정"],
        "expect_top": "mem-2007-2009-gfc-downcycle",   # 오답을 기대 → miss
    }]
    summary, results = evaluate_rows(store, rows, k=5)
    assert summary["hit@1"] == 0.0
    # MRR: 기대 사례가 top-k 어딘가에 있으면 1/rank, 없으면 0 — 1.0은 아님
    assert summary["mrr"] < 1.0


def test_forbid_detects_lookahead(store):
    # as_of 2016-01: 슈퍼사이클 크래시(첫 knowable 2017-03)는 절대 나오면 안 됨
    rows = [{
        "qid": "t3", "sector": "memory", "as_of": "2016-01-01",
        "signals": ["재고 저수준", "가격 반등", "수요 강세"],
        "forbid": ["mem-2016-2019-supercycle-crash"],
    }]
    summary, _ = evaluate_rows(store, rows, k=5)
    assert summary["forbid_violations"] == 0    # as-of 차단이 지켜지면 0

    # 검증기 자체가 위반을 잡아내는지: as_of를 미래로 옮기면 위반으로 집계돼야
    rows[0]["as_of"] = "2019-01-01"
    rows[0]["signals"] = ["기록적 실적 발표", "고객 재고조정 시작 언급"]
    summary2, _ = evaluate_rows(store, rows, k=5)
    assert summary2["forbid_violations"] == 1


def test_expect_only_rows_dont_count_forbid(store):
    # expect 없는 순수 룩어헤드 프로브는 hit 분모에서 제외
    rows = [{
        "qid": "t4", "sector": "memory", "as_of": "2016-01-01",
        "signals": ["아무 신호"],
        "forbid": ["mem-2016-2019-supercycle-crash"],
    }]
    summary, _ = evaluate_rows(store, rows, k=5)
    assert summary["n"] == 1
    assert summary["n_expect"] == 0             # hit@k/MRR 분모 0 → 값 None
    assert summary["hit@1"] is None


def test_goldset_file_loads_and_is_wellformed():
    rows = load_goldset(GOLDSET_PATH)
    assert len(rows) >= 20
    qids = [r["qid"] for r in rows]
    assert len(qids) == len(set(qids))          # qid 유일
    for r in rows:
        assert r["as_of"] and r["signals"]
        assert r.get("expect_top") or r.get("forbid"), r["qid"]
