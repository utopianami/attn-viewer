"""Publication preserves failed input provenance while aging the original snapshot."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from sector.report_freshness import collection_freshness, publication_freshness
from sector.store import SectorStore


@pytest.mark.parametrize("status, expected", [
    ({}, "missing"),
    ({"rss": {"status": "error", "at": "2026-09-04T21:29:00+00:00"}}, "failed"),
    ({"rss": {"status": "ok", "at": "2026-09-04T19:00:00+00:00"}}, "stale"),
    ({"rss": {"status": "ok", "at": "2026-09-04T22:00:00+00:00"}}, "stale"),
    ({"rss": {"status": "ok", "at": "invalid"}}, "stale"),
])
def test_publication_cannot_promote_initial_failure_or_rewrite_diagnostics(tmp_path, status, expected):
    now = datetime(2026, 9, 4, 21, 30, tzinfo=timezone.utc)
    (tmp_path / "status.json").write_text(json.dumps(status))
    snapshot = collection_freshness(SectorStore(tmp_path), now=now)
    original = deepcopy(snapshot)
    result = publication_freshness(snapshot, now=now + timedelta(minutes=45))
    assert result["state"] == expected
    assert result["initial_state"] == expected
    assert result["publication_check"]["state"] == expected
    assert result["publication_check"]["elapsed_since_input_check_s"] == 2700
    assert snapshot == original
    for key, value in original.items():
        assert result[key] == value


def test_publication_preserves_precollection_failure_after_inputs_age(tmp_path):
    now = datetime(2026, 9, 4, 21, 30, tzinfo=timezone.utc)
    (tmp_path / "status.json").write_text(json.dumps({
        "rss": {"status": "ok", "at": "2026-09-04T21:29:00+00:00"}}))
    snapshot = collection_freshness(SectorStore(tmp_path), now=now)
    snapshot.update(state="failed", precollection={"state": "failed", "collection_rc": 7})
    result = publication_freshness(snapshot, now=now + timedelta(hours=2))
    assert result["state"] == "failed"
    assert result["precollection"] == {"state": "failed", "collection_rc": 7}
    assert result["publication_check"]["oldest_age_s"] == 7260


def test_partial_degraded_collector_with_usable_output_does_not_block_publication(tmp_path):
    """One optional upstream can fail while the collector still supplies current data."""
    now = datetime(2026, 9, 5, 6, 30, tzinfo=timezone.utc)
    (tmp_path / "status.json").write_text(json.dumps({
        "rss": {
            "status": "ok", "at": "2026-09-05T06:29:00+00:00",
            "items": 3, "observations": 0,
        },
        "sdk_downloads": {
            "status": "degraded", "at": "2026-09-05T06:29:00+00:00",
            "items": 0, "observations": 2,
            "detail": "PyPI 429; npm succeeded",
        },
    }))

    snapshot = collection_freshness(SectorStore(tmp_path), now=now)

    assert snapshot["state"] == "fresh"
    assert snapshot["failed_collectors"] == []
    assert snapshot["degraded_collectors"] == ["sdk_downloads"]


def test_degraded_collector_without_output_still_blocks_publication(tmp_path):
    now = datetime(2026, 9, 5, 6, 30, tzinfo=timezone.utc)
    (tmp_path / "status.json").write_text(json.dumps({
        "sdk_downloads": {
            "status": "degraded", "at": "2026-09-05T06:29:00+00:00",
            "items": 0, "observations": 0,
        },
    }))

    snapshot = collection_freshness(SectorStore(tmp_path), now=now)

    assert snapshot["state"] == "failed"
    assert snapshot["failed_collectors"] == ["sdk_downloads"]
    assert snapshot["degraded_collectors"] == []


def test_successful_empty_collection_is_fresh_but_error_with_output_still_blocks(tmp_path):
    """An empty successful poll means no new event; status, not volume, proves success."""
    now = datetime(2026, 9, 5, 6, 30, tzinfo=timezone.utc)
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps({
        "rss": {
            "status": "ok", "at": "2026-09-05T06:29:00+00:00",
            "items": 0, "observations": 0,
        },
    }))
    assert collection_freshness(SectorStore(tmp_path), now=now)["state"] == "fresh"

    status_path.write_text(json.dumps({
        "rss": {
            "status": "error", "at": "2026-09-05T06:29:00+00:00",
            "items": 1, "observations": 0,
        },
    }))
    snapshot = collection_freshness(SectorStore(tmp_path), now=now)
    assert snapshot["state"] == "failed"
    assert snapshot["failed_collectors"] == ["rss"]
