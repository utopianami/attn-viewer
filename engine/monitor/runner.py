"""실데이터 로드 + 전체 점검 실행 + health.json/알림 처리. CLI: python -m monitor.runner.

점검 하나가 죽어도 나머지는 진행하고, 죽은 점검 자체를 alert로 보고한다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import time
from pathlib import Path

from monitor import checks
from monitor.alert import process_alerts
from monitor.contracts import CheckResult, HealthReport
from runtime_io import atomic_write_text

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TAIL_BYTES = 256 * 1024          # 지표 jsonl은 tail만 읽는다 (openrouter 등 대형 파일)
_SANITY_ROWS = 60


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _tail_rows(path: Path) -> list[dict]:
    try:
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - _TAIL_BYTES))
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    for line in raw.splitlines()[1:] if path.stat().st_size > _TAIL_BYTES else raw.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[-_SANITY_ROWS:]


def _latest_report(reports_dir: Path) -> tuple[dict | None, str | None]:
    def sort_key(p: Path):
        stem = p.stem                          # 2026-08-10-1
        date, _, seq = stem.rpartition("-")
        return (date, int(seq) if seq.isdigit() else 0)

    files = [p for p in reports_dir.glob("*.json") if not p.stem.startswith("__")]
    if not files:
        return None, None
    latest = max(files, key=sort_key)
    return _read_json(latest), latest.name


def _metric_ages(metrics_dir: Path, now: dt.datetime) -> dict[str, float]:
    ages: dict[str, float] = {}
    for p in sorted(metrics_dir.glob("*.jsonl")):
        rows = _tail_rows(p)
        ts_vals = []
        for row in rows:
            try:
                ts_vals.append(dt.date.fromisoformat(str(row.get("ts"))[:10]))
            except ValueError:
                continue
        if ts_vals:
            ages[p.stem] = (now.date() - max(ts_vals)).days
    return ages


def run_checks(storage_root: Path | None = None, now: dt.datetime | None = None,
               times_kst: list[tuple[int, int]] | None = None,
               *, cooldown_s: float | None = None, token: str = "",
               chat_id: str = "") -> HealthReport:
    now = now or dt.datetime.now(dt.timezone.utc)
    sector = None
    stale_after_s = checks.STALE_COLLECT_S
    if storage_root is None or times_kst is None or cooldown_s is None:
        from app.settings import settings
        from sector.report_scheduler import parse_times
        storage_root = storage_root or _REPO_ROOT / "storage"
        if settings.sector_storage_dir:              # api.py와 같은 경로 규칙 (codex #4)
            sector = Path(settings.sector_storage_dir)
        times_kst = times_kst or parse_times(settings.report_times_kst)
        cooldown_s = settings.monitor_cooldown_s if cooldown_s is None else cooldown_s
        token = token or settings.telegram_bot_token
        chat_id = chat_id or settings.telegram_chat_id
        if not settings.report_scheduler_enabled:
            # 리포트 직전 보충 수집이 없으면 주기(12h)+드리프트만 남는다 (codex #1)
            stale_after_s = settings.sector_collect_interval_s * 1.25
    sector = sector or storage_root / "rag" / "memory_sector"

    results: list[CheckResult] = []

    def guarded(name: str, fn):
        try:
            got = fn()
            results.extend([got] if isinstance(got, CheckResult) else got)
        except Exception as exc:  # noqa: BLE001 — 점검 실패도 데이터로 남긴다
            logger.error("monitor: 점검 %s 실패 — %s", name, exc)
            results.append(CheckResult(check="monitor_error", pipeline=name,
                                       axis="stability", level="alert",
                                       detail=f"{type(exc).__name__}: {exc}"[:300]))

    status = _read_json(sector / "status.json")
    if status is None and (sector / "status.json").exists():
        # store가 status.json을 비원자 저장 — 순간 손상 오탐 방지 재시도 (codex #4)
        time.sleep(0.5)
        status = _read_json(sector / "status.json")
    status = status or {}
    expected = None
    try:
        from sector.runner import _registry
        expected = {m.NAME for m in _registry()}
    except Exception:  # noqa: BLE001 — 레지스트리 로드 실패는 누락 점검만 생략
        pass
    guarded("collectors", lambda: checks.check_collector_status(
        status, now, stale_after_s=stale_after_s, expected=expected))
    st_stats = (status.get("saveticker") or {}).get("stats") or {}
    if st_stats:
        guarded("saveticker", lambda: checks.check_saveticker(st_stats))

    report, filename = _latest_report(sector / "reports")
    guarded("report", lambda: checks.check_report_recency(
        (report or {}).get("generatedAt"), now, times_kst))
    if report is not None and filename is not None:
        guarded("report", lambda: checks.check_report_health(report, filename))

    metrics_dir = sector / "metrics"
    if metrics_dir.is_dir():
        ages = _metric_ages(metrics_dir, now)
        guarded("metrics", lambda: checks.check_metric_freshness(ages, now))
        series = {p.stem: _tail_rows(p) for p in sorted(metrics_dir.glob("*.jsonl"))}
        guarded("metrics", lambda: checks.check_metric_sanity(series, now=now))

    def disk_check():
        usage = shutil.disk_usage(storage_root)
        ratio = usage.used / usage.total
        level = "alert" if ratio > 0.92 else ("warn" if ratio > 0.85 else "ok")
        return CheckResult(check="disk_usage", pipeline="host", axis="stability",
                           level=level, detail=f"디스크 {ratio:.0%} 사용")
    guarded("host", disk_check)

    health = HealthReport(at=now.isoformat(), results=results,
                          worst=HealthReport.worst_of(results))
    monitor_dir = storage_root / "monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(monitor_dir / "health.json", health.model_dump_json())

    process_alerts(results, monitor_dir, now, cooldown_s=cooldown_s or 21600,
                   token=token, chat_id=chat_id)
    return health


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    health = run_checks()
    bad = [r for r in health.results if r.level != "ok"]
    print(f"worst={health.worst} checks={len(health.results)} 이상={len(bad)}")
    for r in bad:
        print(f"  [{r.level}] {r.pipeline} · {r.check}: {r.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
