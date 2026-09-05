"""CLI publication must be atomic across failed, cancelled and overlapping attempts."""
import asyncio
import json

import pytest

import sector.report_pipeline as pipeline
from sector.report_contracts import FinalOpinion, Report, ReportPipeline


def _report(seq=1, *, wiped=False):
    return Report(
        id=f"2026-09-05-{seq}", seq=seq, generatedAt="2026-09-05T06:30:00+09:00",
        title="Report", window={"from": "a", "to": "b"}, publish_status="ok",
        finalOpinion=FinalOpinion(text="hold", confidence="낮"),
        pipeline=ReportPipeline(stages=[]),
        diagnostics={"stage_errors": ["all providers failed"] if wiped else []},
    )


def _args(root):
    return ["--root", str(root), "--now", "2026-09-05T06:30:00+09:00"]


def test_failed_attempt_is_not_public_and_releases_only_its_reservation(tmp_path, monkeypatch):
    _, other_path, other_token = pipeline.alloc_report_slot(tmp_path, "2026-09-05")

    async def fail(_store, **kwargs):
        return _report(kwargs["seq"], wiped=True)

    monkeypatch.setattr(pipeline, "run_report_pipeline", fail)
    assert pipeline.main(_args(tmp_path)) == 2
    assert list((tmp_path / "reports").glob("*.json")) == []
    assert list((tmp_path / "reports").glob("*.reserve")) == [other_path.with_suffix(".reserve")]
    assert other_path.with_suffix(".reserve").read_text() == other_token


@pytest.mark.parametrize("failure", [RuntimeError("generation failed"), asyncio.CancelledError()])
def test_aborted_attempt_releases_owned_reservation(tmp_path, monkeypatch, failure):
    async def abort(_store, **kwargs):
        raise failure

    monkeypatch.setattr(pipeline, "run_report_pipeline", abort)
    with pytest.raises(type(failure)):
        pipeline.main(_args(tmp_path))
    assert list((tmp_path / "reports").glob("*.reserve")) == []


def test_overlapping_invocation_does_not_allocate_or_publish(tmp_path, monkeypatch):
    from runtime_io import try_singleton_lock

    async def generate(_store, **kwargs):
        return _report(kwargs["seq"])

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    with try_singleton_lock(tmp_path / ".report-pipeline.lock") as acquired:
        assert acquired
        assert pipeline.main(_args(tmp_path)) == 0
        assert list((tmp_path / "reports").glob("*")) == []
    assert pipeline.main(_args(tmp_path)) == 0
    assert len(list((tmp_path / "reports").glob("*.json"))) == 1


@pytest.mark.parametrize("status, expected", [
    ({}, "missing"),
    ({"rss": {"status": "ok", "at": "2026-09-04T12:00:00+00:00"}}, "stale"),
    ({"rss": {"status": "error", "at": "2026-09-04T21:29:00+00:00"}}, "failed"),
    ({"rss": {"status": "ok", "at": "2026-09-06T00:00:00+00:00"}}, "stale"),
    ({"rss": {"status": "ok", "at": "bad timestamp"}}, "stale"),
    ({"_run": {"state": "running"},
      "rss": {"status": "ok", "at": "2026-09-04T21:29:00+00:00"}}, "failed"),
    ({"rss": {"status": "ok", "at": "2026-09-04T21:29:00+00:00"}}, "fresh"),
])
def test_input_freshness_is_persisted_and_gates_ok(tmp_path, monkeypatch, status, expected):
    (tmp_path / "status.json").write_text(json.dumps(status))

    async def generate(_store, **kwargs):
        return _report(kwargs["seq"])

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    assert pipeline.main(_args(tmp_path)) == 0
    saved = json.loads((tmp_path / "reports" / "2026-09-05-1.json").read_text())
    assert saved["publish_status"] == ("ok" if expected == "fresh" else "hold")
    assert saved["diagnostics"]["collection_freshness"]["state"] == expected


def test_release_does_not_remove_replaced_reservation(tmp_path):
    _, path, token = pipeline.alloc_report_slot(tmp_path, "2026-09-05")
    path.with_suffix(".reserve").write_text("another-owner")
    pipeline.release_report_slot(path, token)
    assert path.with_suffix(".reserve").read_text() == "another-owner"


def test_failed_precollection_is_preserved_even_if_disk_status_is_fresh(tmp_path, monkeypatch):
    (tmp_path / "status.json").write_text(json.dumps({
        "rss": {"status": "ok", "at": "2026-09-04T21:29:00+00:00"}}))

    async def generate(_store, **kwargs):
        return _report(kwargs["seq"])

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    diagnostic = {"state": "failed", "collection_rc": 7}
    assert pipeline.main(_args(tmp_path) + ["--collection-freshness", json.dumps(diagnostic)]) == 0
    saved = json.loads((tmp_path / "reports" / "2026-09-05-1.json").read_text())
    assert saved["publish_status"] == "hold"
    assert saved["diagnostics"]["collection_freshness"]["precollection"] == diagnostic
