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


def test_multi_series_ambiguous_without_selector_but_explicit_series_passes(tmp_path):
    # 3부 T11 블로커3(a) — selector.series 미지정 + 같은 단위의 서로 다른 시리즈
    # (DDR4/DDR5)가 참여 집합에 섞이면 각자 자체 YoY 쌍이 없는데도 뒤섞여 계산되던
    # 결함(codex 최종 리뷰: 100%, pass가 나온 재현). series 미지정이면 fail-closed
    # (ambiguous_series), 명시하면 자기 시리즈만으로 정상 판정.
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2025-07", value=5.0,
                          unit="USD/GB", meta={"category": "DRAM", "item": "ddr4_8gb"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=8.0,
                          unit="USD/GB", meta={"category": "DRAM", "item": "ddr4_8gb"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2025-07", value=6.0,
                          unit="USD/GB", meta={"category": "DRAM", "item": "ddr5_16gb"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=10.0,
                          unit="USD/GB", meta={"category": "DRAM", "item": "ddr5_16gb"})])
    yoy = dict(_STRUCT, aggregation="yoy", window_days=400, unit="percent",
              comparator=">=", threshold=50.0, max_age_days=400)
    (chk,), _ = parse_gate_checks(_pb([yoy]))
    assert evaluate_gate(chk, store, NOW).unavailable_reason == "ambiguous_series"
    sel = dict(yoy, selector={"series": "ddr5_16gb", "meta_filter": {"category": "DRAM"}})
    (chk2,), _ = parse_gate_checks(_pb([sel]))
    out = evaluate_gate(chk2, store, NOW)
    assert out.verdict == "pass" and abs(out.value - 66.67) < 0.1  # (10/6-1)*100


def test_mean_window_includes_current_period_start_convention(tmp_path):
    # 3부 T11 블로커3(b) — codex 최종 리뷰 재현: 6월=100, 7월=0, cutoff 2026-07-21.
    # latest/freshness·valid 참여 자격은 기간 시작일(start<=now) 관례라 진행 중인
    # 7월도 이미 "참여" 자격이 있는데, mean_window만 `end<=now`로 추가 배제해
    # 100(6월 단독)이 나오던 결함. 참여 자격을 기간 시작일로 통일하면 (100+0)/2=50.
    meta = {"category": "DRAM"}
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=100.0,
                          unit="USD/GB", meta=meta),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.0,
                          unit="USD/GB", meta=meta)])
    mw = dict(_STRUCT, aggregation="mean_window", window_days=60,
             comparator=">=", threshold=75.0)
    (chk,), _ = parse_gate_checks(_pb([mw]))
    out = evaluate_gate(chk, store, NOW)
    assert out.value == 50.0 and out.verdict == "fail"


def test_duplicate_order_among_structured_gates_drops_all(tmp_path):
    # 3부 T11 블로커3(c) — 중복 order를 허용하면 orchestrator의 order 룩업이
    # 항상 첫 check에 붙어 두 번째 게이트 판정이 첫 번째 이름·단위로 잘못
    # 라벨링된다(codex 최종 리뷰 재현: search_interest_kr 결과가 첫 번째 가격
    # 게이트 이름·USD/GB 단위로 주입됨). all-or-none — 같은 order를 공유하는
    # 구조 게이트는 전부 구조 해석에서 드롭(문자열 게이트로만 유지, 로그는 남김).
    second = dict(_STRUCT, metric_id="search_interest_kr", unit="index")  # order=1 중복
    checks, logs = parse_gate_checks(_pb([_STRUCT, second]))
    assert checks == []
    assert any("중복 order" in m for m in logs)


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
