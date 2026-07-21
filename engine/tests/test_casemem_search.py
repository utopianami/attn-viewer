import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.contracts import CaseEpisode, Phase, Evidence, _parse_ts
from casemem.search import search_cases, _surface_score, _phase_visible


def _phase(order, label, knowable, signals, ev_knowable=None):
    return Phase(order=order, label=label, period_start="2018-01-01",
                 knowable_at=knowable, identifying_signals=signals,
                 evidence=[Evidence(source="IR", quote="q",
                                    knowable_at=ev_knowable or knowable)])


def _ep():
    return CaseEpisode(id="mem-2018", sector="memory", title="2018 다운사이클",
                       event_time="2018-01-01", knowable_at="2018-02-01",
                       phases=[
                           _phase(0, "capex_expansion", "2018-02-01", ["capex guidance up", "fab expansion"]),
                           _phase(1, "inventory_build", "2018-06-01", ["inventory days rising"]),
                           _phase(2, "price_break", "2018-10-01", ["spot price down sharply"]),
                       ])


def test_phase_visible_as_of_gate():
    p = _phase(0, "x", "2018-06-01", [])
    assert _phase_visible(p, _parse_ts("2018-07-01")) is True
    assert _phase_visible(p, _parse_ts("2018-05-01")) is False   # 아직 못 봄


def test_surface_score_overlap():
    p = _phase(0, "x", "2018-01-01", ["capex guidance up", "fab expansion"])
    assert _surface_score(["capex guidance rising", "expansion"], p) > 0.0
    assert _surface_score(["totally unrelated"], p) == 0.0


def test_search_matches_phase_and_predicts_next():
    # as_of=2018-07-01 → phase0·1만 가시, phase2(price_break)는 미래
    m = search_cases([_ep()], ["inventory days rising fast"],
                     as_of_dt=_parse_ts("2018-07-01"), sector="memory", k=5)
    assert len(m) == 1
    top = m[0]
    assert top.episode_id == "mem-2018"
    assert top.matched_phase_order == 1                 # inventory_build 가 최고 겹침
    assert "price_break" in top.next_phase_labels       # 다음 국면 예측(아직 안 옴)
    assert "inventory_build" not in top.next_phase_labels


def test_search_blocks_lookahead_evidence_and_phases():
    # as_of=2018-03-01 → phase0만 가시. 미래 국면/근거 새면 안 됨
    m = search_cases([_ep()], ["capex guidance up"],
                     as_of_dt=_parse_ts("2018-03-01"), sector="memory", k=5)
    assert m[0].matched_phase_order == 0
    assert m[0].next_phase_labels == ["inventory_build", "price_break"]  # 미래지만 라벨=예측은 허용
    # evidence는 as-of 가시분만 — 매치 국면(phase0) evidence의 knowable_at<=as_of
    assert all(_parse_ts(e.knowable_at) <= _parse_ts("2018-03-01") for e in m[0].evidence)


def test_search_filters_sector():
    fx = CaseEpisode(id="fx-1", sector="fx", title="x",
                     event_time="2018-01-01", knowable_at="2018-01-01",
                     phases=[_phase(0, "p", "2018-01-01", ["capex guidance up"])])
    m = search_cases([_ep(), fx], ["capex guidance up"],
                     as_of_dt=_parse_ts("2019-01-01"), sector="memory", k=5)
    assert {x.episode_id for x in m} == {"mem-2018"}
