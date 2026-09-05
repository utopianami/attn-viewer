"""CLI publication must be atomic across failed, cancelled and overlapping attempts."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

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


@pytest.fixture
def fixed_freshness_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 4, 21, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr("sector.report_freshness.datetime", Clock)


def test_failed_attempt_is_not_public_and_releases_only_its_reservation(tmp_path, monkeypatch):
    _, other_path, other_token = pipeline.alloc_report_slot(tmp_path, "2026-09-05")

    async def fail(_store, **kwargs):
        return _report(kwargs["seq"], wiped=True)

    monkeypatch.setattr(pipeline, "run_report_pipeline", fail)
    assert pipeline.main(_args(tmp_path)) == 2
    assert list((tmp_path / "reports").glob("*.json")) == []
    assert list((tmp_path / "reports").glob("*.reserve")) == [other_path.with_suffix(".reserve")]
    assert other_path.with_suffix(".reserve").read_text() == other_token


def test_language_quality_failure_is_quarantined_instead_of_published(
        tmp_path, monkeypatch, fixed_freshness_clock):
    """두 차례 문장 검수에 실패한 편집본은 공개 reports에 쓰지 않는다."""
    (tmp_path / "status.json").write_text(json.dumps({
        "rss": {"status": "ok", "at": "2026-09-04T21:29:00+00:00"},
    }))

    async def generate(_store, **kwargs):
        report = _report(kwargs["seq"])
        report.publish_status = "hold"
        report.diagnostics["readability"] = {
            "mode": "fallback", "error": "language_quality",
        }
        return report

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)

    assert pipeline.main(_args(tmp_path)) == 0
    assert list((tmp_path / "reports").glob("*.json")) == []
    held = list((tmp_path / "rejected-reports").glob(
        "2026-09-05-1.language-quality-*.json"))
    assert len(held) == 1
    assert json.loads(held[0].read_text())["diagnostics"]["readability"] == {
        "mode": "fallback", "error": "language_quality",
    }


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
        assert pipeline.main(_args(tmp_path)) not in (0, 2)
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
def test_input_freshness_is_persisted_and_gates_ok(tmp_path, monkeypatch, fixed_freshness_clock, status, expected):
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


@pytest.mark.parametrize("operation", ["read_text", "unlink"])
@pytest.mark.parametrize("phase", ["generation", "publication", "cancellation"])
def test_cleanup_oserror_preserves_original_failure(tmp_path, monkeypatch, caplog, operation, phase):
    from pathlib import Path

    failure = asyncio.CancelledError("original cancellation") if phase == "cancellation" else RuntimeError(f"original {phase}")
    original_operation = getattr(Path, operation)
    cleanup_started = False

    def deny_cleanup(path, *args, **kwargs):
        if cleanup_started and path.suffix == ".reserve":
            raise PermissionError("reservation filesystem unavailable")
        return original_operation(path, *args, **kwargs)

    def fail_publication(*_args):
        nonlocal cleanup_started
        cleanup_started = True
        raise failure

    async def generate(_store, **kwargs):
        nonlocal cleanup_started
        if phase != "publication":
            cleanup_started = True
            raise failure
        return _report(kwargs["seq"])

    monkeypatch.setattr(Path, operation, deny_cleanup)
    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    if phase == "publication":
        monkeypatch.setattr(pipeline.os, "replace", fail_publication)
    with pytest.raises(type(failure), match=f"original {phase}") as caught:
        pipeline.main(_args(tmp_path))
    assert caught.value is failure
    assert "reservation filesystem unavailable" in caplog.text
    assert "2026-09-05-1.reserve" in caplog.text
    assert (tmp_path / "reports" / "2026-09-05-1.reserve").exists()
    assert list((tmp_path / "reports").glob("*.json")) == []


def test_failed_precollection_is_preserved_even_if_disk_status_is_fresh(tmp_path, monkeypatch, fixed_freshness_clock):
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


def test_historical_report_now_does_not_set_freshness_clock(tmp_path, monkeypatch, fixed_freshness_clock):
    (tmp_path / "status.json").write_text(json.dumps({
        "rss": {"status": "ok", "at": "2026-09-04T21:29:00+00:00"}}))

    async def generate(_store, **kwargs):
        assert kwargs["now"].isoformat() == "2026-09-04T16:00:00+00:00"
        return _report(kwargs["seq"])

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    assert pipeline.main(["--root", str(tmp_path), "--now", "2026-09-05T01:00:00+09:00"]) == 0
    saved = json.loads((tmp_path / "reports" / "2026-09-05-1.json").read_text())
    assert saved["publish_status"] == "ok"
    diagnostic = saved["diagnostics"]["collection_freshness"]
    assert diagnostic["initial_state"] == "fresh"
    assert diagnostic["checked_at"] == "2026-09-04T21:30:00+00:00"
    assert diagnostic["oldest_age_s"] == 60


@pytest.mark.parametrize("elapsed, expected", [(5340, "ok"), (5341, "hold")])
def test_publication_ages_original_inputs_despite_later_collection(tmp_path, monkeypatch, elapsed, expected):
    import sector.report_freshness as freshness

    initial = datetime(2026, 9, 4, 21, 30, tzinfo=timezone.utc)
    clock_now = initial

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock_now.astimezone(tz)

    monkeypatch.setattr(freshness, "datetime", Clock)
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps({"_run": {"id": "original", "state": "completed"},
                                     "rss": {"status": "ok", "at": "2026-09-04T21:29:00+00:00"}}))

    async def generate(_store, **kwargs):
        nonlocal clock_now
        clock_now += timedelta(seconds=elapsed)
        status_path.write_text(json.dumps({"_run": {"id": "later", "state": "completed"},
                                         "rss": {"status": "ok", "at": clock_now.isoformat()}}))
        return _report(kwargs["seq"])

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    assert pipeline.main(_args(tmp_path)) == 0
    saved = json.loads((tmp_path / "reports" / "2026-09-05-1.json").read_text())
    assert saved["publish_status"] == expected
    diagnostic = saved["diagnostics"]["collection_freshness"]
    assert diagnostic["state"] == ("fresh" if expected == "ok" else "stale")
    assert diagnostic["initial_state"] == "fresh"
    assert diagnostic["checked_at"] == initial.isoformat()
    assert diagnostic["oldest_age_s"] == 60
    assert diagnostic["run_id"] == "original"
    assert diagnostic["publication_check"] == {
        "checked_at": clock_now.isoformat(), "elapsed_since_input_check_s": elapsed,
        "oldest_age_s": 60 + elapsed, "state": diagnostic["state"]}


@pytest.mark.parametrize("stage", ["judge", "thesis_update"])
@pytest.mark.parametrize("recover", [True, False], ids=["recovered", "not-executed"])
def test_auxiliary_failure_only_clears_after_real_collection_recovery(
        tmp_path, monkeypatch, stage, recover):
    """Merged historical errors must stop gating publication only after real recovery."""
    from types import SimpleNamespace
    import sector.runner as runner
    from sector.contracts import CollectorResult, RawNewsItem
    from sector.store import SectorStore

    store = SectorStore(tmp_path)
    failing = True
    provide_news = True
    generated_ids = []

    async def collect(_store):
        items = [RawNewsItem(id="news-1", title="Market news", source="fixture")]
        return CollectorResult(name="rss", kind="news", items=items if provide_news else [])

    async def judge(_items):
        if failing and stage == "judge":
            raise RuntimeError("judge temporarily unavailable")
        return []

    async def update(_store, *, tstore):
        if failing and stage == "thesis_update":
            raise RuntimeError("thesis temporarily unavailable")
        return {}

    async def generate(_store, **kwargs):
        report = _report(kwargs["seq"])
        report.id = f"{kwargs['now'].astimezone(pipeline._KST):%Y-%m-%d}-{kwargs['seq']}"
        generated_ids.append(report.id)
        return report

    def publish():
        assert pipeline.main(["--root", str(tmp_path)]) == 0
        return json.loads((tmp_path / "reports" / f"{generated_ids[-1]}.json").read_text())

    monkeypatch.setattr(runner, "_registry", lambda: [
        SimpleNamespace(NAME="rss", KIND="news", collect=collect)])
    monkeypatch.setattr(runner.settings, "thesis_update_enabled", True)
    monkeypatch.setattr("sector.thesis_update.update_all", update)
    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)

    asyncio.run(runner.collect_all(store, judge_fn=judge))
    first_run = store.read_status()["_run"]["id"]
    assert store.read_status()[stage]["status"] == "error"
    failed_report = publish()
    assert failed_report["publish_status"] == "hold"
    assert failed_report["diagnostics"]["collection_freshness"]["failed_collectors"] == [stage]

    failing = False
    if not recover:
        provide_news = stage != "judge"
        monkeypatch.setattr(runner.settings, "thesis_update_enabled", stage != "thesis_update")
    asyncio.run(runner.collect_all(store, judge_fn=judge))
    assert store.read_status()["_run"]["id"] != first_run
    recovered_report = publish()
    assert recovered_report["publish_status"] == ("ok" if recover else "hold")
    diagnostic = recovered_report["diagnostics"]["collection_freshness"]
    assert diagnostic["state"] == ("fresh" if recover else "failed")
    assert diagnostic["failed_collectors"] == ([] if recover else [stage])


@pytest.mark.parametrize("archived", [False, True])
def test_scheduled_fire_survives_crash_at_atomic_publication(tmp_path, monkeypatch, archived):
    """The public JSON itself is the completion record, even before save returns."""
    async def generate(_store, **kwargs):
        return _report(kwargs["seq"])

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    args = _args(tmp_path) + ["--scheduled-fire", "2026-09-05T06:30:00+09:00"]
    original_replace = pipeline.os.replace

    def publish_then_crash(source, destination):
        original_replace(source, destination)
        raise RuntimeError("process lost immediately after atomic publication")

    with monkeypatch.context() as crash:
        crash.setattr(pipeline.os, "replace", publish_then_crash)
        with pytest.raises(RuntimeError, match="immediately after atomic publication"):
            pipeline.main(args)

    report_path = tmp_path / "reports" / "2026-09-05-1.json"
    saved = json.loads(report_path.read_text())
    assert saved["diagnostics"]["scheduled_fire"] == "2026-09-04T21:30:00+00:00"
    if archived:
        archive = tmp_path / "report-archive" / "2026" / "09"
        archive.mkdir(parents=True)
        report_path.rename(archive / report_path.name)

    def unexpected_allocation(*_args):
        raise AssertionError("completed scheduled fire must skip before reservation")

    monkeypatch.setattr(pipeline, "alloc_report_slot", unexpected_allocation)
    assert pipeline.main(args) == 0
    assert len(list((tmp_path / "reports").glob("*.json"))) == (0 if archived else 1)
    assert list((tmp_path / "reports").glob("*.reserve")) == []


def test_scheduled_fires_are_distinct_and_manual_runs_remain_repeatable(tmp_path, monkeypatch):
    generations = []

    async def generate(_store, **kwargs):
        generations.append(kwargs["seq"])
        return _report(kwargs["seq"])

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    for _ in range(2):
        assert pipeline.main(_args(tmp_path)) == 0
    for fire in ["2026-09-05T06:30:00+09:00", "2026-09-04T21:30:00+00:00",
                 "2026-09-05T18:30:00+09:00"]:
        assert pipeline.main(_args(tmp_path) + ["--scheduled-fire", fire]) == 0
    assert generations == [1, 2, 3, 4]
    saved = [json.loads(path.read_text()) for path in sorted((tmp_path / "reports").glob("*.json"))]
    assert [report["diagnostics"].get("scheduled_fire") for report in saved] == [
        None, None, "2026-09-04T21:30:00+00:00", "2026-09-05T09:30:00+00:00"]
