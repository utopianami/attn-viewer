"""Phase 3 — 시황 리포트 스케줄러: 발화 시각 계산·설정 파싱·인프라 실패 재시도."""
import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sector.report_scheduler as rs
from sector.report_scheduler import KST, next_fire, parse_times

UTC = dt.timezone.utc
_REAL_FRESHNESS_GUARD = rs._ensure_fresh_data


def test_parse_times_default_and_dedup():
    assert parse_times("04:39,16:39") == [(4, 39), (16, 39)]
    assert parse_times("16:39, 04:39,16:39") == [(4, 39), (16, 39)]


def test_parse_times_rejects_bad_values():
    with pytest.raises(ValueError):
        parse_times("25:00")
    with pytest.raises(ValueError):
        parse_times("")


def _kst(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi, tzinfo=KST)


def test_next_fire_same_day():
    now = _kst(2026, 7, 22, 10, 0)
    assert next_fire(now, [(4, 39), (16, 39)]).astimezone(KST) == _kst(2026, 7, 22, 16, 39)


def test_next_fire_rolls_to_next_day():
    now = _kst(2026, 7, 22, 23, 0)
    assert next_fire(now, [(4, 39), (16, 39)]).astimezone(KST) == _kst(2026, 7, 23, 4, 39)


def test_next_fire_exact_boundary_moves_forward():
    # 발화 시각 정각에 재계산해도 같은 시각을 다시 잡지 않는다 (t > now 엄격 비교)
    now = _kst(2026, 7, 22, 16, 39)
    assert next_fire(now, [(4, 39), (16, 39)]).astimezone(KST) == _kst(2026, 7, 23, 4, 39)


def test_next_fire_accepts_utc_input():
    # KST 04:39 = UTC 전일 19:39 — 어떤 타임존 aware 입력이든 동일 발화점
    now_utc = dt.datetime(2026, 7, 22, 18, 0, tzinfo=UTC)  # KST 23:00
    fire = next_fire(now_utc, [(4, 39), (16, 39)])
    assert fire == dt.datetime(2026, 7, 22, 19, 39, tzinfo=UTC)


# ── 인프라 실패 재시도 (2026-07-23 실측: DNS 8h 다운 → 빈 리포트가 exit 0 "완료") ──

class _FakeProc:
    def __init__(self, rc):
        self._rc = rc

    async def wait(self):
        return self._rc

    def kill(self):
        pass


def _patch_spawn(monkeypatch, rcs: list[int]):
    """create_subprocess_exec가 rcs 순서대로 종료코드를 내도록 치환. 호출 횟수 기록."""
    # 실운영 로그 격리 — 미패치 시 테스트마다 storage/logs/report-pipeline.log에
    # 빈 "===== run" 헤더가 쌓여 실행 이력 진단을 오염(08-10 실측: 하루 8건).
    import os
    monkeypatch.setattr(rs, "_open_run_log", lambda: open(os.devnull, "ab"))

    # 신선도 가드 격리 — 미패치 시 마지막 수집이 1h 넘게 묵은 시점에 돌면
    # 실네트워크 collect_all(최대 1800s)로 행(08-10 실측, 시간 의존 플레이크).
    # 가드 자체는 전용 테스트(_patch_freshness 계열)가 따로 검증한다.
    async def _fresh_noop():
        pass

    monkeypatch.setattr(rs, "_ensure_fresh_data", _fresh_noop)
    calls = []

    async def fake_spawn(*a, **kw):
        calls.append(a)
        return _FakeProc(rcs[min(len(calls) - 1, len(rcs) - 1)])

    monkeypatch.setattr(rs.asyncio, "create_subprocess_exec", fake_spawn)
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(rs, "_retry_sleep", fake_sleep)
    return calls, sleeps


def test_run_once_success_no_retry(monkeypatch):
    calls, sleeps = _patch_spawn(monkeypatch, [0])
    asyncio.run(rs._run_once())
    assert len(calls) == 1
    assert sleeps == []


def test_run_once_retries_on_nonzero_then_succeeds(monkeypatch):
    calls, sleeps = _patch_spawn(monkeypatch, [2, 0])
    asyncio.run(rs._run_once())
    assert len(calls) == 2
    assert sleeps == [rs._RETRY_DELAY_S]


def test_run_once_gives_up_after_max_attempts(monkeypatch):
    calls, sleeps = _patch_spawn(monkeypatch, [2, 2, 2, 2, 2])
    asyncio.run(rs._run_once())
    assert len(calls) == rs._MAX_ATTEMPTS
    assert len(sleeps) == rs._MAX_ATTEMPTS - 1


# ── 리포트 직전 신선도 가드 (2026-07-31) ─────────────────────────────────────
# 07-31 06:30 실측: 수집이 엔진 시작 앵커 12h 주기라 리포트 시각과 비정합 —
# 8.5h 묵은 뉴스로 발행, 아마존 실적 포함 453건(SaveTicker hwm 이후) 통누락.

def _patch_freshness(monkeypatch, *, last_at, collect_calls, result=0, run_state=None):
    class _Store:
        def read_status(self):
            data = {"rss": {"status": "ok", "at": last_at}} if last_at else {}
            if run_state:
                data["_run"] = {"state": run_state}
            return data

    async def fake_collect(*, timeout_s):
        collect_calls.append(1)
        return result

    monkeypatch.setattr("sector.api._get_store", lambda: _Store())
    monkeypatch.setattr("sector.api._last_collected", lambda s: last_at)
    monkeypatch.setattr("sector.scheduler.run_collection_subprocess", fake_collect)


def test_fresh_data_skips_collect(monkeypatch):
    calls = []
    now = dt.datetime.now(dt.timezone.utc)
    _patch_freshness(monkeypatch, last_at=(now - dt.timedelta(minutes=10)).isoformat(),
                     collect_calls=calls)
    asyncio.run(rs._ensure_fresh_data())
    assert calls == []


def test_fresh_data_joins_collection_already_in_progress(monkeypatch):
    calls = []
    now = dt.datetime.now(dt.timezone.utc)
    _patch_freshness(
        monkeypatch,
        last_at=(now - dt.timedelta(minutes=10)).isoformat(),
        collect_calls=calls,
        run_state="running",
    )
    asyncio.run(rs._ensure_fresh_data())
    assert calls == [1]


def test_stale_data_collects_before_report(monkeypatch):
    calls = []
    now = dt.datetime.now(dt.timezone.utc)
    _patch_freshness(monkeypatch, last_at=(now - dt.timedelta(hours=8)).isoformat(),
                     collect_calls=calls)
    asyncio.run(rs._ensure_fresh_data())
    assert calls == [1]


def test_missing_status_collects(monkeypatch):
    calls = []
    _patch_freshness(monkeypatch, last_at=None, collect_calls=calls)
    asyncio.run(rs._ensure_fresh_data())
    assert calls == [1]


def test_collect_failure_never_blocks_report(monkeypatch):
    async def boom(*, timeout_s):
        raise RuntimeError("collector down")
    monkeypatch.setattr("sector.api._get_store", lambda: object())
    monkeypatch.setattr("sector.api._last_collected", lambda s: None)
    monkeypatch.setattr("sector.scheduler.run_collection_subprocess", boom)
    asyncio.run(rs._ensure_fresh_data())      # 예외가 새면 리포트가 죽는다


def test_run_once_runs_freshness_guard_first(monkeypatch):
    order = []

    async def fake_fresh():
        order.append("fresh")

    async def fake_spawn(freshness=None, *, scheduled_fire=None):
        order.append("spawn")
        return 0
    monkeypatch.setattr(rs, "_ensure_fresh_data", fake_fresh)
    monkeypatch.setattr(rs, "_spawn_once", fake_spawn)
    asyncio.run(rs._run_once())
    assert order == ["fresh", "spawn"]


def test_failed_collection_diagnostics_reach_pipeline_subprocess(monkeypatch):
    calls, _ = _patch_spawn(monkeypatch, [0])
    _patch_freshness(monkeypatch, last_at=None, collect_calls=[], result=7)
    # Restore the real guard after the spawn fixture isolated it.
    monkeypatch.setattr(rs, "_ensure_fresh_data", _REAL_FRESHNESS_GUARD)
    asyncio.run(rs._run_once())
    import json
    argv = calls[0]
    assert "--collection-freshness" in argv
    diagnostic = json.loads(argv[argv.index("--collection-freshness") + 1])
    assert diagnostic["state"] == "failed"
    assert diagnostic["collection_rc"] == 7


def test_success_exit_with_stale_status_is_not_considered_fresh(monkeypatch):
    _patch_freshness(monkeypatch, last_at="2026-01-01T00:00:00+00:00",
                     collect_calls=[], result=0)
    diagnostic = asyncio.run(rs._ensure_fresh_data())
    assert diagnostic["state"] == "stale"
    assert diagnostic["collection_rc"] == 0


def test_default_report_schedule_fires_at_required_kst_times(monkeypatch):
    from app.settings import Settings
    monkeypatch.delenv("REPORT_TIMES_KST", raising=False)
    times = parse_times(Settings(_env_file=None).report_times_kst)
    assert next_fire(_kst(2026, 9, 5, 6, 0), times).astimezone(KST) == _kst(2026, 9, 5, 6, 30)
    assert next_fire(_kst(2026, 9, 5, 6, 30), times).astimezone(KST) == _kst(2026, 9, 5, 18, 30)


def test_pipeline_reads_the_same_configured_store_as_precollection(monkeypatch, tmp_path):
    calls, _ = _patch_spawn(monkeypatch, [0])
    monkeypatch.setattr(rs.settings, "sector_storage_dir", str(tmp_path))
    asyncio.run(rs._run_once())
    argv = calls[0]
    assert "--root" in argv
    assert argv[argv.index("--root") + 1] == str(tmp_path)


def test_retry_skips_publication_completed_by_another_run_during_backoff(tmp_path, monkeypatch):
    """A fails, B publishes during A's backoff, A retries: only B may publish."""
    import json
    import sector.report_pipeline as pipeline
    from sector.report_contracts import FinalOpinion, Report, ReportPipeline

    _patch_spawn(monkeypatch, [0])  # Isolate precollection, sleep and production logs.
    monkeypatch.setattr(rs.settings, "sector_storage_dir", str(tmp_path))
    monkeypatch.setattr(rs.settings, "report_times_kst", "06:30,18:30")
    clock_now = _kst(2026, 9, 5, 6, 30)
    later = _kst(2026, 9, 5, 18, 45)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return clock_now.astimezone(tz)

    monkeypatch.setattr(rs.dt, "datetime", Clock)
    generations = []
    attempts = []

    async def generate(_store, **kwargs):
        generations.append(kwargs["seq"])
        return Report(id=f"2026-09-05-{kwargs['seq']}", seq=kwargs["seq"],
                      generatedAt="2026-09-05T06:30:00+09:00", title="Report",
                      window={"from": "a", "to": "b"},
                      finalOpinion=FinalOpinion(text="hold", confidence="낮"),
                      pipeline=ReportPipeline(stages=[]), diagnostics={
                          "stage_errors": ["all providers failed"] if len(generations) == 1 else []})

    async def spawn(*argv, **_kwargs):
        # Run the real CLI publication path, replacing only the process/LLM boundary.
        cli_args = [arg for arg in argv[3:] if arg != "--case-memory"]
        rc = await asyncio.to_thread(pipeline.main,
                                     [*cli_args, "--now", "2026-09-05T06:30:00+09:00"])
        attempts.append((argv, rc))
        return _FakeProc(rc)

    async def backoff(_seconds):
        nonlocal clock_now
        assert attempts[-1][1] == 2
        assert list((tmp_path / "reports").glob("*.json")) == []
        await rs._run_once()  # B publishes while A has released its attempt lock.
        assert len(list((tmp_path / "reports").glob("*.json"))) == 1
        clock_now = later  # A must retain the original fire even across another slot.

    monkeypatch.setattr(pipeline, "run_report_pipeline", generate)
    monkeypatch.setattr(rs.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(rs, "_retry_sleep", backoff)
    asyncio.run(rs._run_once())

    public = list((tmp_path / "reports").glob("*.json"))
    assert len(public) == 1
    assert generations == [1, 1]  # Failed attempt + B; A's retry never generates.
    assert [rc for _, rc in attempts] == [2, 0, 0]
    key = "2026-09-04T21:30:00+00:00"
    assert json.loads(public[0].read_text())["diagnostics"]["scheduled_fire"] == key
    assert [argv[argv.index("--scheduled-fire") + 1] for argv, _ in attempts] == [key] * 3
    assert list((tmp_path / "reports").glob("*.reserve")) == []


def test_explicit_scheduled_fire_is_normalized_and_shared_across_runs(monkeypatch):
    calls, _ = _patch_spawn(monkeypatch, [0])
    asyncio.run(rs._run_once(scheduled_fire=_kst(2026, 9, 5, 6, 30)))
    asyncio.run(rs._run_once(scheduled_fire=dt.datetime(2026, 9, 4, 21, 30, tzinfo=UTC)))
    assert [argv[argv.index("--scheduled-fire") + 1] for argv in calls] == [
        "2026-09-04T21:30:00+00:00", "2026-09-04T21:30:00+00:00"]


def test_loop_preserves_planned_fire_after_delayed_wakeup(monkeypatch):
    target = _kst(2026, 9, 5, 6, 30)
    received = []
    monkeypatch.setattr(rs, "next_fire", lambda *_: target)

    async def sleep(_seconds):
        pass

    async def run(*args, **kwargs):
        received.append(kwargs.get("scheduled_fire"))
        raise asyncio.CancelledError()

    monkeypatch.setattr(rs.asyncio, "sleep", sleep)
    monkeypatch.setattr(rs, "_run_once", run)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(rs._loop())
    assert received == [target]


@pytest.mark.parametrize("hour, minute, expected", [
    (6, 29, "2026-09-04T09:30:00+00:00"),
    (6, 30, "2026-09-04T21:30:00+00:00"),
    (18, 31, "2026-09-05T09:30:00+00:00"),
])
def test_run_without_explicit_fire_uses_latest_configured_slot(monkeypatch, hour, minute, expected):
    calls, _ = _patch_spawn(monkeypatch, [0])
    now = _kst(2026, 9, 5, hour, minute)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(rs.dt, "datetime", Clock)
    monkeypatch.setattr(rs.settings, "report_times_kst", "06:30,18:30")
    asyncio.run(rs._run_once())
    argv = calls[0]
    assert "--scheduled-fire" in argv
    assert argv[argv.index("--scheduled-fire") + 1] == expected
