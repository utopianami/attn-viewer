import datetime as dt

import pytest

from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_store import ThesisStore, freshness
from tests.test_thesis_contracts import make_rev


def test_append_dedup_and_as_of(tmp_path):
    ts = ThesisStore(tmp_path)
    r1 = make_rev(valid_from="2026-07-20T00:00:00",
                  revision_id="hbm-tightness@2026-07-20T00:00:00")
    assert ts.append(r1) is True
    assert ts.append(make_rev(valid_from="2026-07-21T00:00:00",
                              revision_id="hbm-tightness@2026-07-21T00:00:00")) is False  # 실질 동일 → 생략
    r3 = make_rev(valid_from="2026-07-21T01:00:00",
                  revision_id="hbm-tightness@2026-07-21T01:00:00",
                  assessment="mixed")
    assert ts.append(r3) is True
    with pytest.raises(ValueError):
        ts.append(r3)                                              # 중복 revision_id
    assert ts.latest("hbm-tightness").assessment == "mixed"
    assert ts.latest_as_of("hbm-tightness", "2026-07-20").revision_id == r1.revision_id  # 날짜형
    assert ts.latest_as_of("hbm-tightness", "2026-07-21T00:30:00").revision_id == r1.revision_id


def _store_with(tmp_path, obs):
    s = SectorStore(tmp_path / "s")
    s.append_observations(obs)
    return s


def test_freshness_fresh_degraded_stale_and_min_count(tmp_path):
    now = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)
    rev = make_rev(required_inputs=[
        {"metric": "memory_price_usd_per_gb", "max_age_days": 45, "min_count": 2,
         "meta_filter": {"category": "DRAM"}},
        {"metric": "kr_semi_export", "max_age_days": 30, "min_count": 1}])
    obs_full = [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta={"category": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=0.09,
                          unit="USD/GB", meta={"category": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.2,
                          unit="USD/GB", meta={"category": "NAND"}),   # 그룹 밖 — 미계수
        MetricObservation(metric="kr_semi_export", ts="2026-07-10", value=1.0, unit="k_usd")]
    assert freshness(rev, _store_with(tmp_path, obs_full), now=now) == "fresh"
    # min_count 미달(DRAM 1건) → degraded
    assert freshness(rev, _store_with(tmp_path / "b", obs_full[1:]), now=now) == "degraded"
    # 전무 → stale
    assert freshness(rev, _store_with(tmp_path / "c", []), now=now) == "stale"
    # 미래 ts는 무효 (fail-closed)
    future = [MetricObservation(metric="kr_semi_export", ts="2027-01-01", value=1.0, unit="k_usd")]
    rev2 = make_rev(required_inputs=[{"metric": "kr_semi_export", "max_age_days": 30}])
    assert freshness(rev2, _store_with(tmp_path / "d", future), now=now) == "stale"
