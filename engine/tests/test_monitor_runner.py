"""monitor.runner — fixture 디렉터리 통합 테스트 (오프라인)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitor.runner import run_checks

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _fixture_root(tmp_path: Path) -> Path:
    """storage/ 유사 트리 — sector 스토어 + 리포트 + 모니터 상태 디렉터리."""
    root = tmp_path / "storage"
    sector = root / "rag" / "memory_sector"
    _write(sector / "status.json", {
        "kosis": {"status": "ok", "detail": "", "at": (NOW - timedelta(hours=1)).isoformat()},
        "rss": {"status": "error", "detail": "boom",
                "at": (NOW - timedelta(hours=1)).isoformat()},
    })
    _write(sector / "reports" / "2026-08-10-1.json", {
        "id": "2026-08-10-1", "publish_status": "ok", "format": "axes",
        "generatedAt": (NOW - timedelta(hours=2)).isoformat(),
        "cards": [{"axis": "macro"}, {"axis": "memory"}, {"axis": "other"}],
    })
    m = sector / "metrics" / "macro_market.jsonl"
    m.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"metric": "macro_market", "ts": "2026-08-09", "value": 100.0,
             "meta": {"name": "nasdaq"}},
            {"metric": "macro_market", "ts": "2026-08-10", "value": 101.0,
             "meta": {"name": "nasdaq"}}]
    m.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return root


def test_run_checks_collects_alerts_and_writes_health(tmp_path):
    root = _fixture_root(tmp_path)
    report = run_checks(storage_root=root, now=NOW, times_kst=[(6, 30), (18, 30)])
    assert report.worst == "alert"                       # rss error
    pipelines = {r.pipeline for r in report.results}
    assert "collector:rss" in pipelines and "report" in pipelines
    health = json.loads((root / "monitor" / "health.json").read_text(encoding="utf-8"))
    assert health["worst"] == "alert"


def test_run_checks_never_raises_on_broken_inputs(tmp_path):
    root = tmp_path / "storage"
    sector = root / "rag" / "memory_sector"
    sector.mkdir(parents=True)
    (sector / "status.json").write_text("{잘못된 json", encoding="utf-8")
    report = run_checks(storage_root=root, now=NOW, times_kst=[(6, 30), (18, 30)])
    assert report.worst == "alert"                       # status 없음 → collect_recency alert


def test_alert_state_and_jsonl_written(tmp_path):
    root = _fixture_root(tmp_path)
    run_checks(storage_root=root, now=NOW, times_kst=[(6, 30), (18, 30)])
    alerts = (root / "monitor" / "alerts.jsonl").read_text(encoding="utf-8").strip()
    assert alerts, "alerts.jsonl 비어 있음"
    assert (root / "monitor" / "state.json").exists()
    # 같은 실행 반복 — 쿨다운 내 재발송 억제로 alerts.jsonl 줄 수 불변
    n1 = len(alerts.splitlines())
    run_checks(storage_root=root, now=NOW + timedelta(minutes=30),
               times_kst=[(6, 30), (18, 30)])
    n2 = len((root / "monitor" / "alerts.jsonl").read_text(encoding="utf-8")
             .strip().splitlines())
    assert n2 == n1


def test_engine_probe_timeout_is_alert(tmp_path):
    root = _fixture_root(tmp_path)
    report = run_checks(
        storage_root=root,
        now=NOW,
        times_kst=[(6, 30), (18, 30)],
        engine_probe=lambda: {"error": "timeout"},
    )
    assert any(
        result.pipeline == "engine" and result.level == "alert"
        for result in report.results
    )
