"""시황 리포트 스케줄러 — KST 고정 시각 하루 2회 (Phase 3, 기본 OFF).

파이프라인은 in-process가 아니라 서브프로세스로 돌린다:
- CLI claude 콜·스테이지 타임아웃 가드까지 수동 실행(`python -m sector.report_pipeline`)과
  동일 경로를 타야 실측이 그대로 적용된다.
- 엔진 이벤트루프를 15분짜리 동기 파이프라인이 점유하지 않는다.
stdout/stderr는 DEVNULL — 산출물은 storage에 영속되고, 죽은 소비자 파이프에
블록되는 사고(2026-07-22 실측)를 원천 차단한다.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from app.settings import settings

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
_ENGINE_DIR = Path(__file__).resolve().parents[1]
# 스테이지별 가드(30~40분)가 1차 방어 — 이건 좀비 방지 최후 보루
_HARD_TIMEOUT_S = 3 * 60 * 60
# 인프라 전멸(exit 2 — 2026-07-23 04:39 DNS 다운 실측) 시 재시도. 30분×2회면
# 발화 간격(12h) 안에 넉넉히 수렴하고, 지속 장애면 슬롯을 포기하고 다음 발화로.
_RETRY_DELAY_S = 30 * 60
_MAX_ATTEMPTS = 3

_retry_sleep = asyncio.sleep  # 테스트 치환점


def parse_times(raw: str) -> list[tuple[int, int]]:
    """"04:39,16:39" → [(4, 39), (16, 39)]. 형식 오류는 기동 시점에 바로 터뜨린다."""
    out: list[tuple[int, int]] = []
    for part in raw.split(","):
        hh, mm = part.strip().split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(f"잘못된 시각: {part!r}")
        out.append((h, m))
    if not out:
        raise ValueError("REPORT_TIMES_KST가 비었습니다")
    return sorted(set(out))


def next_fire(now: dt.datetime, times: list[tuple[int, int]]) -> dt.datetime:
    """now(aware) 이후 가장 가까운 KST 발화 시각을 UTC로 반환."""
    now_kst = now.astimezone(KST)
    candidates = []
    for day_offset in (0, 1):
        base = (now_kst + dt.timedelta(days=day_offset)).date()
        for hh, mm in times:
            t = dt.datetime.combine(base, dt.time(hh, mm), tzinfo=KST)
            if t > now_kst:
                candidates.append(t)
    return min(candidates).astimezone(dt.timezone.utc)


async def _spawn_once() -> int | None:
    """파이프라인 1회 실행 — 종료코드 반환(하드 타임아웃이면 None)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "sector.report_pipeline", "--case-memory",
        cwd=str(_ENGINE_DIR),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return await asyncio.wait_for(proc.wait(), timeout=_HARD_TIMEOUT_S)
    except asyncio.TimeoutError:
        # SIGTERM 먼저 — 파이프라인이 취소 정리로 CLI 자식 프로세스그룹까지 죽인다
        # (SIGKILL만 하면 별도 세션인 claude 자식이 고아로 남음 — codex P4 B2)
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        logger.error("report scheduler: 하드 타임아웃(%ds) — 프로세스 종료", _HARD_TIMEOUT_S)
        return None


async def _run_once() -> None:
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        rc = await _spawn_once()
        if rc == 0:
            logger.info("report scheduler: 파이프라인 완료 (시도 %d)", attempt)
            return
        logger.error("report scheduler: 파이프라인 실패 rc=%s (시도 %d/%d)",
                     rc, attempt, _MAX_ATTEMPTS)
        if attempt < _MAX_ATTEMPTS:
            await _retry_sleep(_RETRY_DELAY_S)
    logger.error("report scheduler: %d회 모두 실패 — 이번 슬롯 포기", _MAX_ATTEMPTS)


async def _loop() -> None:
    times = parse_times(settings.report_times_kst)
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        target = next_fire(now, times)
        wait_s = (target - now).total_seconds()
        logger.info("report scheduler: 다음 실행 %s (%.0f초 대기)",
                    target.astimezone(KST).strftime("%m-%d %H:%M KST"), wait_s)
        await asyncio.sleep(wait_s)
        try:
            await _run_once()
        except Exception as exc:  # noqa: BLE001 — never-raise, 다음 발화는 계속
            logger.error("report scheduler: 실행 실패 — %s", exc)


async def start(app) -> asyncio.Task | None:
    if not settings.report_scheduler_enabled:
        logger.info("report scheduler: 비활성화(기본 OFF) — "
                    "cd engine && .venv/bin/python -m sector.report_pipeline --case-memory")
        return None
    parse_times(settings.report_times_kst)  # 설정 오류는 기동 시 즉시 노출
    task = asyncio.create_task(_loop())
    app.state.report_task = task
    logger.info("report scheduler: 시작 (KST %s)", settings.report_times_kst)
    return task
