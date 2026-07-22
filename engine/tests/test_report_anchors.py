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
