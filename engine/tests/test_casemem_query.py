import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import _parse_ts
from casemem.store import CaseStore
from casemem.seeds import load_seeds
from casemem.query import query_case_memory


def _seeded(tmp_path):
    s = CaseStore(tmp_path)
    load_seeds(s)
    return s


def test_query_matches_2018_inventory_phase(tmp_path):
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["재고일수 상승", "inventory days rising"],
                            as_of="2018-07-01", sector="memory")
    assert res.sector == "memory"
    ids = {m.episode_id for m in res.matches}
    assert "mem-2018-downcycle" in ids


def test_query_blocks_future_phase_leakage(tmp_path):
    # price_break signal을 2018-03-01(그 국면 knowable_at=2018-10-01 전)로 질의
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["DRAM 현물가 급락"],
                            as_of="2018-03-01", sector="memory")
    for m in res.matches:
        if m.episode_id == "mem-2018-downcycle":
            assert m.matched_phase_order != 2      # price_break(order 2)로 매치되면 누출
    # 미래 국면 evidence도 새면 안 됨 — 모든 매치 evidence의 knowable_at <= as_of
    as_of_dt = _parse_ts("2018-03-01")
    assert all(_parse_ts(e.knowable_at) <= as_of_dt
               for m in res.matches for e in m.evidence)


def test_query_bad_as_of_returns_empty_with_diag(tmp_path):
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["x"], as_of="not-a-date", sector="memory")
    assert res.matches == []
    assert res.scanned == 0


def test_query_diag_counts_sector_drop(tmp_path):
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["capex"], as_of="2025-01-01", sector="fx")
    assert res.matches == []
    assert res.dropped_sector == 0    # read_episodes(sector=fx)가 이미 걸러 scanned=0
    assert res.scanned == 0


def test_query_without_llm_is_deterministic(tmp_path):
    s = _seeded(tmp_path)
    res = query_case_memory(s, signals=["재고일수 상승"], as_of="2018-07-01",
                            sector="memory")
    assert res.rerank_used is False and res.rerank_failed is False
    assert all(m.reranked is False for m in res.matches)
    assert all(m.surface_score == m.score for m in res.matches)   # 블렌드 안 됨


def test_query_with_llm_reranks(tmp_path):
    s = _seeded(tmp_path)
    calls = {"n": 0}
    def fake(prompt):
        calls["n"] += 1
        return '[{"i":0,"s":1.0}]'      # 첫 후보 구조점수 최대
    res = query_case_memory(s, signals=["재고일수 상승"], as_of="2018-07-01",
                            sector="memory", llm_fn=fake)
    assert res.rerank_used is True
    assert calls["n"] == 1
    assert res.matches and res.matches[0].reranked is True


def test_query_llm_failure_sets_rerank_failed(tmp_path):
    s = _seeded(tmp_path)
    def boom(prompt): raise RuntimeError("x")
    res = query_case_memory(s, signals=["재고일수 상승"], as_of="2018-07-01",
                            sector="memory", llm_fn=boom)
    assert res.rerank_used is True and res.rerank_failed is True
    assert all(m.reranked is False for m in res.matches)          # 폴백
