import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import MetricObservation
from sector.report_anchors import build_anchors
from sector.store import SectorStore


def _obs(ts, value, ing="2026-06-01T00:00:00+00:00"):
    # ingested_at 명시 — store.append가 실시계를 찍으면 과거 now 주입 시
    # ingested 게이트에 전량 걸리므로 기본값을 과거로 고정
    return MetricObservation(metric="memory_price_usd_per_gb", ts=ts, value=value,
                             unit="$/GB", meta={"item": "DRAM"}, ingested_at=ing)


def test_delta_code_computed_and_day_precision_cutoff(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([_obs("2026-06", 3.0), _obs("2026-07", 3.5),
                           _obs("2026-07-31", 9.9)])       # 일 단위 미래 → 컷
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    anchors = build_anchors(s, now=now, metrics=["memory_price_usd_per_gb"])
    a = anchors[0]
    assert a.value == 3.5                                   # 7/31 관측이 아님(ts[:7] 비교 버그 방지)
    assert round(a.delta_pct, 1) == 16.7
    assert a.anchor_id == "memory_price_usd_per_gb:DRAM"


def test_future_ingested_observation_excluded(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([_obs("2026-07", 3.5, ing="2026-07-01T00:00:00+00:00"),
                           _obs("2026-07-02", 8.8, ing="2026-07-20T00:00:00+00:00")])
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    anchors = build_anchors(s, now=now, metrics=["memory_price_usd_per_gb"])
    assert anchors and anchors[0].value == 3.5              # 7/20 수집분 look-ahead 차단


def test_allowlist_reexport_alive():
    from sector.report_input import _REPORT_METRICS
    from sector.report_metrics_allowlist import REPORT_METRICS
    assert _REPORT_METRICS is REPORT_METRICS


def test_never_raise_on_missing_metric(tmp_path):
    s = SectorStore(tmp_path)
    assert build_anchors(s, now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                         metrics=["ghost_metric"]) == []


def test_stale_series_excluded_from_anchors(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("2024-06", 1.5), _obs("2024-07", 1.53),           # 낡은 시리즈(2년 전)
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=8.4,
                          unit="$/GB", meta={"item": "DDR4"},
                          ingested_at="2026-07-01T00:00:00+00:00"),
    ])
    now = datetime(2026, 7, 22, tzinfo=timezone.utc)
    anchors = build_anchors(s, now=now, metrics=["memory_price_usd_per_gb"])
    assert [a.value for a in anchors] == [8.4]                  # 1.53(2024) 제외


def test_comparison_kind_and_prev_fields_code_computed(tmp_path):
    # 사실성 감사 4.1/4.2: Δ%의 비교 종류를 코드가 명시 — LLM의 QoQ/YoY 추측 차단
    s = SectorStore(tmp_path)
    s.append_observations([_obs("2026-04", 3.0), _obs("2026-07", 3.6)])
    a = build_anchors(s, now=datetime(2026, 7, 15, tzinfo=timezone.utc),
                      metrics=["memory_price_usd_per_gb"])[0]
    assert a.comparison_kind == "QoQ"                       # 3개월 차 → QoQ
    assert a.prev_period == "2026-04" and a.prev_value == 3.0
    assert round(a.delta_pct, 0) == 20


def test_comparison_kind_yoy_and_mom(tmp_path):
    s = SectorStore(tmp_path)
    s.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2025-07", value=2.0,
                          unit="$/GB", meta={"item": "A"},
                          ingested_at="2026-06-01T00:00:00+00:00"),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=3.0,
                          unit="$/GB", meta={"item": "A"},
                          ingested_at="2026-06-01T00:00:00+00:00"),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=2.0,
                          unit="$/GB", meta={"item": "B"},
                          ingested_at="2026-06-01T00:00:00+00:00"),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=3.0,
                          unit="$/GB", meta={"item": "B"},
                          ingested_at="2026-06-01T00:00:00+00:00")])
    anchors = build_anchors(s, now=datetime(2026, 7, 15, tzinfo=timezone.utc),
                            metrics=["memory_price_usd_per_gb"])
    kinds = {a.entity: a.comparison_kind for a in anchors}
    assert kinds == {"A": "YoY", "B": "MoM"}


def test_customs_full_month_labels_merge_into_one_series(tmp_path):
    # 사실성 감사 4.4: '01~30'/'01~31' 라벨 분리로 5월을 건너뛴 +40.3% 재발 방지
    s = SectorStore(tmp_path)
    rows = [("2026-04", "01~30", 32039455.0), ("2026-05", "01~31", 37285085.0),
            ("2026-06", "01~30", 44947188.0)]
    s.append_observations([
        MetricObservation(metric="kr_semi_export", ts=ts, value=v, unit="k_usd",
                          meta={"item": item}, ingested_at="2026-07-01T00:00:00+00:00")
        for ts, item, v in rows])
    anchors = build_anchors(s, now=datetime(2026, 7, 15, tzinfo=timezone.utc),
                            metrics=["kr_semi_export"])
    fm = [a for a in anchors if a.entity == "full_month"]
    assert len(fm) == 1
    a = fm[0]
    assert a.prev_period == "2026-05"                       # 5월을 건너뛰지 않음
    assert round(a.delta_pct, 1) == 20.6                    # 연속 월간(5→6월), +40.3% 아님
    assert a.comparison_kind == "MoM"
