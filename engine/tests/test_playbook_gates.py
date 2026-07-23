# engine/tests/test_playbook_gates.py
import datetime as dt
import json
from pathlib import Path

from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_contracts import observation_id
from stages.playbook import (_valid_playbook, evaluate_gate, evaluate_playbook_gates,
                             parse_gate_checks)

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)

_STRUCT = {"order": 1, "check": "D램 가격 수준", "operationalization": "현물가 확인",
           "metric_id": "memory_price_usd_per_gb",
           "selector": {"meta_filter": {"category": "DRAM"}},
           "aggregation": "last", "comparator": ">=", "threshold": 0.05,
           "unit": "USD/GB", "max_age_days": 45}


def _pb(gates):
    return {"slug": "s", "situation": "x", "triggers": [], "topics": [],
            "conclusionType": "방향 판단", "gates": gates, "connection": "c",
            "status": "holdout_passed"}


def test_parse_all_or_none():
    checks, logs = parse_gate_checks(_pb([_STRUCT]))
    assert len(checks) == 1 and logs == []
    partial = {"order": 2, "check": "y", "operationalization": "z",
               "metric_id": "memory_price_usd_per_gb"}          # 일부만 — 전체 무시
    checks, logs = parse_gate_checks(_pb([partial]))
    assert checks == [] and len(logs) == 1
    legacy = {"order": 3, "check": "y", "operationalization": "z"}  # 문자열 gate
    checks, logs = parse_gate_checks(_pb([legacy]))
    assert checks == [] and logs == []                          # 하위 호환 — 무로그
    mw = dict(_STRUCT, aggregation="mean_window")               # window_days 없음
    checks, logs = parse_gate_checks(_pb([mw]))
    assert checks == [] and len(logs) == 1


def _store(tmp_path, obs):
    s = SectorStore(tmp_path / "s")
    s.append_observations(obs)
    return s


def test_evaluate_pass_with_evidence_observation(tmp_path):
    meta = {"category": "DRAM"}
    store = _store(tmp_path, [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta=meta)])
    (chk,), _ = parse_gate_checks(_pb([_STRUCT]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and out.value == 0.1
    assert out.evidence_observation_id == observation_id(
        "memory_price_usd_per_gb", "2026-07", meta)


def test_evaluate_unavailable_reasons(tmp_path):
    (chk,), _ = parse_gate_checks(_pb([_STRUCT]))
    assert evaluate_gate(chk, _store(tmp_path / "a", []),
                         NOW).unavailable_reason == "no_metric"
    bad_unit = _store(tmp_path / "b", [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="KRW/GB", meta={"category": "DRAM"})])
    assert evaluate_gate(chk, bad_unit, NOW).unavailable_reason == "unit_mismatch"
    old = _store(tmp_path / "c", [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2025-01", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    assert evaluate_gate(chk, old, NOW).unavailable_reason == "stale_data"


def test_selector_series_filters_and_mixed_units_refused(tmp_path):
    # B8 — series가 평가 알고리즘에 실참여 + 이종 단위 혼합 평균 차단
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta={"category": "DRAM", "item": "ddr5_16gb"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=90.0,
                          unit="KRW/GB", meta={"category": "DRAM", "item": "ddr4_8gb"})])
    sel = dict(_STRUCT, selector={"series": "ddr5_16gb",
                                  "meta_filter": {"category": "DRAM"}})
    (chk,), _ = parse_gate_checks(_pb([sel]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and out.value == 0.1        # _group_key 하드 필터
    (chk2,), _ = parse_gate_checks(_pb([_STRUCT]))            # series 없음 → 혼재
    assert evaluate_gate(chk2, store, NOW).unavailable_reason == "unit_mismatch"


def test_evaluate_yoy_percent_unit(tmp_path):
    meta = {"category": "DRAM"}
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2025-07", value=0.08,
                          unit="USD/GB", meta=meta),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    yoy = dict(_STRUCT, aggregation="yoy", window_days=400, unit="percent",
               comparator=">=", threshold=10.0, max_age_days=45)
    (chk,), _ = parse_gate_checks(_pb([yoy]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and abs(out.value - 25.0) < 0.01
    wrong = dict(yoy, unit="USD/GB")
    (chk2,), _ = parse_gate_checks(_pb([wrong]))
    assert evaluate_gate(chk2, store, NOW).unavailable_reason == "unit_mismatch"


def test_yoy_baseline_outside_fixed_window_is_stale(tmp_path):
    # r2-6 — 기준점 ±45일 고정 창: 6개월 전 값이 "1년 전 최근접"으로 선택되면 안 됨
    meta = {"category": "DRAM"}
    yoy = dict(_STRUCT, aggregation="yoy", window_days=400, unit="percent",
               comparator=">=", threshold=10.0, max_age_days=45)
    (chk,), _ = parse_gate_checks(_pb([yoy]))
    near = _store(tmp_path / "near", [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2025-08", value=0.08,
                          unit="USD/GB", meta=meta),   # −365일에서 31일 — 창 안
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    assert evaluate_gate(chk, near, NOW).verdict in ("pass", "fail")
    far = _store(tmp_path / "far", [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-01", value=0.08,
                          unit="USD/GB", meta=meta),   # 약 6개월 전 — 창 밖
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    assert evaluate_gate(chk, far, NOW).unavailable_reason == "stale_data"


def test_empty_unit_and_nonfinite_observations_do_not_participate(tmp_path):
    # r2-6 — 빈 unit 관측을 check.unit으로 해석 금지·NaN 불참 → 참여 0 = unit_mismatch
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.2,
                          unit="", meta={"category": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07",
                          value=float("nan"), unit="USD/GB",
                          meta={"category": "DRAM"})])
    (chk,), _ = parse_gate_checks(_pb([_STRUCT]))
    assert evaluate_gate(chk, store, NOW).unavailable_reason == "unit_mismatch"


def test_registry_unitless_metrics_have_canonical_unit():
    from sector.metrics_registry import METRIC_REGISTRY
    assert METRIC_REGISTRY["search_interest_kr"]["unit"] == "index"   # r2-6 마이그레이션
    assert METRIC_REGISTRY["app_rank"]["unit"] == "rank"


def test_hand_migrated_fixture_valid_and_adopted(tmp_path):
    # B8 — 실존 holdout_passed 플레이북 1건의 손 마이그레이션본 (라이브 경로 fixture)
    pb = json.loads((Path(__file__).parent / "fixtures"
                     / "playbook_structured_gate.json").read_text())
    assert _valid_playbook(pb) and pb["status"] == "holdout_passed"
    checks, logs = parse_gate_checks(pb)
    assert len(checks) >= 1 and logs == []
    store = _store(tmp_path, [MetricObservation(
        metric=checks[0].metric_id, ts="2026-07", value=0.1,
        unit=checks[0].unit, meta=dict(checks[0].selector.meta_filter))])
    outs, logs2 = evaluate_playbook_gates(pb, store, NOW)
    assert any(o.verdict in ("pass", "fail") for o in outs) and logs2 == []


def test_evaluate_playbook_gates_wraps(tmp_path):
    store = _store(tmp_path, [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    outs, logs = evaluate_playbook_gates(
        _pb([_STRUCT, {"order": 9, "check": "문자열만", "operationalization": "o"}]),
        store, NOW)
    assert len(outs) == 1 and outs[0].verdict == "pass" and logs == []
