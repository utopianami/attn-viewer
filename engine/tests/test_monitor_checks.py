"""monitor.checks — 순수 점검 함수 단위 테스트 (오프라인)."""
from datetime import datetime, timedelta, timezone

from monitor.checks import (
    check_collector_status,
    check_metric_freshness,
    check_metric_sanity,
    check_report_recency,
    check_report_health,
    check_saveticker,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _by(results, check):
    got = [r for r in results if r.check == check]
    assert got, f"{check} 결과 없음: {[r.check for r in results]}"
    return got


def _iso(dt_):
    return dt_.isoformat()


# ── 안정성: 수집기 status ────────────────────────────────────────────────────

def test_collector_error_is_alert():
    status = {"rss": {"status": "error", "detail": "boom", "at": _iso(NOW)}}
    (r,) = [x for x in check_collector_status(status, NOW) if x.pipeline == "collector:rss"]
    assert r.level == "alert" and r.axis == "stability"


def test_collector_degraded_and_missing_key_are_warn():
    status = {
        "rss": {"status": "degraded", "detail": "feed_fail=trendforce", "at": _iso(NOW)},
        "ecos": {"status": "missing_key", "detail": "", "at": _iso(NOW)},
    }
    results = check_collector_status(status, NOW)
    levels = {r.pipeline: r.level for r in results}
    assert levels["collector:rss"] == "warn"
    assert levels["collector:ecos"] == "warn"


def test_collector_ok_is_ok():
    status = {"kosis": {"status": "ok", "detail": "", "at": _iso(NOW)}}
    (r,) = [x for x in check_collector_status(status, NOW) if x.pipeline == "collector:kosis"]
    assert r.level == "ok"


def test_collect_recency_alert_when_stale():
    old = NOW - timedelta(hours=9)
    status = {"kosis": {"status": "ok", "at": _iso(old)}}
    (r,) = _by(check_collector_status(status, NOW), "collect_recency")
    assert r.level == "alert"


def test_collect_recency_ok_when_fresh():
    status = {"kosis": {"status": "ok", "at": _iso(NOW - timedelta(hours=1))}}
    (r,) = _by(check_collector_status(status, NOW), "collect_recency")
    assert r.level == "ok"


def test_collect_recency_alert_when_no_status():
    (r,) = _by(check_collector_status({}, NOW), "collect_recency")
    assert r.level == "alert"


def test_collect_recency_partial_run_not_masked():
    # 한 수집기만 최근에 돌았어도(수동 only=[…]) 나머지가 낡았으면 alert
    status = {"kosis": {"status": "ok", "at": _iso(NOW)},
              "rss": {"status": "ok", "at": _iso(NOW - timedelta(hours=9))}}
    (r,) = _by(check_collector_status(status, NOW), "collect_recency")
    assert r.level == "alert" and "rss" in r.detail


def test_collect_recency_threshold_overridable():
    # 리포트 스케줄러 OFF 환경(12h 주기)에서는 임계를 넓혀 오탐 방지
    status = {"kosis": {"status": "ok", "at": _iso(NOW - timedelta(hours=9))}}
    (r,) = _by(check_collector_status(status, NOW, stale_after_s=13 * 3600),
               "collect_recency")
    assert r.level == "ok"


def test_missing_collectors_vs_registry_warns():
    status = {"kosis": {"status": "ok", "at": _iso(NOW)}}
    results = check_collector_status(status, NOW, expected={"kosis", "rss"})
    missing = [r for r in results if r.check == "collector_missing"]
    assert missing and missing[0].level == "warn" and "rss" in missing[0].detail


# ── 정합성: saveticker 커서 불변식 ───────────────────────────────────────────

def _st(**over):
    base = {"scan_hwm": 100, "observed_anchor": 100, "backlog": 0,
            "pending_len": 0, "calendar_ok": True}
    base.update(over)
    return base


def test_saveticker_ok():
    assert all(r.level == "ok" for r in check_saveticker(_st()))


def test_saveticker_hwm_over_anchor_is_alert():
    results = check_saveticker(_st(scan_hwm=101, observed_anchor=100))
    assert any(r.level == "alert" and r.axis == "consistency" for r in results)


def test_saveticker_pending_near_cap_is_warn_full_is_alert():
    assert any(r.level == "warn" for r in check_saveticker(_st(pending_len=250)))
    assert any(r.level == "alert" for r in check_saveticker(_st(pending_len=300)))


def test_saveticker_backlog_growth_warns():
    assert any(r.level == "warn" for r in check_saveticker(_st(backlog=600)))


def test_saveticker_calendar_fail_warns():
    assert any(r.level == "warn" for r in check_saveticker(_st(calendar_ok=False)))


# ── 안정성: 리포트 슬롯 ──────────────────────────────────────────────────────

TIMES = [(6, 30), (18, 30)]  # KST


def test_report_recency_ok_when_latest_covers_last_slot():
    # 마지막 슬롯: KST 08-10 18:30 = UTC 09:30. now=12:00 UTC, 리포트 10:00 UTC 생성.
    (r,) = _by([check_report_recency(_iso(NOW - timedelta(hours=2)), NOW, TIMES)],
               "report_recency")
    assert r.level == "ok"


def test_report_recency_alert_when_slot_missed():
    # 마지막 슬롯 09:30 UTC로부터 유예(기본 4h) 지난 시각, 리포트는 하루 전 것뿐.
    now = NOW + timedelta(hours=2)  # 14:00 UTC
    r = check_report_recency(_iso(NOW - timedelta(hours=26)), now, TIMES)
    assert r.level == "alert" and r.axis == "stability"


def test_report_recency_grace_before_alert():
    # 슬롯 직후(생성 중)에는 아직 alert 아님
    now = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)  # 슬롯 09:30 + 30m
    r = check_report_recency(_iso(NOW - timedelta(hours=13)), now, TIMES)
    assert r.level == "ok"


def test_report_recency_missing_report_is_alert():
    assert check_report_recency(None, NOW, TIMES).level == "alert"


# ── 정합성·안정성: 리포트 내용 ───────────────────────────────────────────────

def _report(**over):
    base = {"id": "2026-08-10-1", "publish_status": "ok", "format": "axes",
            "cards": [{"axis": "macro"}, {"axis": "memory"}, {"axis": "other"}]}
    base.update(over)
    return base


def test_report_health_ok():
    assert all(r.level == "ok" for r in check_report_health(_report(), "2026-08-10-1.json"))


def test_report_health_bad_publish_status():
    results = check_report_health(_report(publish_status="failed"), "2026-08-10-1.json")
    assert any(r.level == "alert" and r.axis == "stability" for r in results)


def test_report_health_hold_is_warn_not_alert():
    # hold는 검증 게이트의 정상 산출일 수 있음 (report_pipeline.py:403)
    results = check_report_health(_report(publish_status="hold"), "2026-08-10-1.json")
    (r,) = [x for x in results if x.check == "report_publish"]
    assert r.level == "warn"


def test_report_health_id_filename_mismatch():
    results = check_report_health(_report(id="2026-08-09-2"), "2026-08-10-1.json")
    assert any(r.level == "alert" and r.axis == "consistency" for r in results)


def test_report_health_axes_missing_cards():
    results = check_report_health(_report(cards=[{"axis": "macro"}]), "2026-08-10-1.json")
    assert any(r.level == "warn" for r in results)


# ── 정확성: 지표 신선도 ──────────────────────────────────────────────────────

def test_metric_freshness_daily_stale_warns_then_alerts():
    ages = {"macro_market": 4.0}          # 일간 지표가 4일 묵음 (기준 2일)
    results = check_metric_freshness(ages, NOW)
    assert any(r.level == "warn" and r.pipeline == "metric:macro_market" for r in results)
    results = check_metric_freshness({"macro_market": 10.0}, NOW)  # 2배 초과
    assert any(r.level == "alert" for r in results)


def test_metric_freshness_quarterly_not_flagged_at_60d():
    results = check_metric_freshness({"hyperscaler_capex": 60.0}, NOW)
    assert all(r.level == "ok" for r in results)


# ── 정확성: 값 급변·이상치 ───────────────────────────────────────────────────

def _obs(pairs, group="A"):
    return [{"ts": t, "value": v, "meta": {"name": group}} for t, v in pairs]


def test_metric_sanity_spike_warns():
    series = {"macro_market": _obs([("2026-08-08", 100.0), ("2026-08-09", 170.0)])}
    results = check_metric_sanity(series)
    assert any(r.level == "warn" and r.axis == "accuracy" for r in results)


def test_metric_sanity_groups_independently():
    # 그룹(종목)별 비교 — 서로 다른 종목 값 차이를 급변으로 오인하면 안 됨
    series = {"stock_price": _obs([("2026-08-08", 100.0), ("2026-08-09", 101.0)], "A")
              + _obs([("2026-08-08", 900.0), ("2026-08-09", 905.0)], "B")}
    assert all(r.level == "ok" for r in check_metric_sanity(series))


def test_metric_sanity_future_ts_is_alert():
    series = {"macro_market": _obs([("2027-01-01", 100.0)])}
    results = check_metric_sanity(series, now=NOW)
    assert any(r.level == "alert" and r.axis == "consistency" for r in results)


def test_metric_sanity_calendar_metrics_allow_future_ts():
    # 실적 캘린더 등 *_calendar 지표는 예정일(미래 ts)이 정상
    series = {"earnings_calendar": _obs([("2026-08-20", 1.0)])}
    assert all(r.level == "ok" for r in check_metric_sanity(series, now=NOW))


def test_metric_sanity_volatile_metrics_use_loose_threshold():
    # 토큰 소비량은 배수 변동이 정상 — 기본 임계로 오탐하면 안 됨
    series = {"openrouter_daily_tokens":
              _obs([("2026-08-08", 1.6e10), ("2026-08-09", 3.4e10)])}
    assert all(r.level == "ok" for r in check_metric_sanity(series, now=NOW))
