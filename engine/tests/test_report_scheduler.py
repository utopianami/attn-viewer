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
