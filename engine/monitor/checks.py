"""순수 점검 함수 — 입력은 plain dict/list, 파일·네트워크 접근 없음 (오프라인 테스트).

임계값은 여기 상수로 관리. 축 구분:
- stability  파이프라인이 돌고 있는가
- consistency 데이터끼리 아귀가 맞는가
- accuracy   값이 말이 되는가
"""
from __future__ import annotations

from collections import Counter
import datetime as dt

from monitor.contracts import CheckResult

_KST = dt.timezone(dt.timedelta(hours=9))

# 수집은 하루 ~4회(약 6h 간격) — 8h 넘게 조용하면 스케줄러 정지 의심
STALE_COLLECT_S = 8 * 3600
# 리포트는 슬롯 후 ~1h 내 완성이 정상, 재시도(30분×2)까지 고려한 유예
REPORT_GRACE_S = 4 * 3600

# saveticker 불변식 상수 (collectors/saveticker.py PENDING_MAX와 동기)
PENDING_MAX = 300
BACKLOG_WARN = 500

# 지표별 신선도 기준(일) — 초과 시 warn, 2배 초과 시 alert. 미등재는 DEFAULT.
METRIC_MAX_AGE_DAYS: dict[str, float] = {
    "macro_market": 2, "stock_price": 2, "token_price": 5,
    "memory_price_usd_per_gb": 7, "openrouter_daily_tokens": 5,
    "kr_semi_export": 15, "kr_semi_export_share": 15,
    "kr_semi_production_index": 45, "tw_monthly_revenue": 45,
    "hyperscaler_capex": 120, "memory_capex": 120,
    "ai_chip_revenue": 120, "equip_revenue": 120,
}
METRIC_MAX_AGE_DEFAULT = 30.0

# 값 급변 경보 임계 — 같은 그룹(종목·계열) 내 직전 대비 상대 변화.
# 분기 재무·토큰 소비량은 배수 변동이 정상이라 완화 (2026-08-10 실데이터 오탐 실측:
# META capex +59%, gpt 토큰 +113%가 전부 진짜 값이었다)
SPIKE_RATIO = 0.5
SPIKE_RATIO_OVERRIDES: dict[str, float] = {
    "openrouter_daily_tokens": 5.0, "token_price": 2.0,
    "hyperscaler_capex": 2.0, "memory_capex": 2.0,
    "ai_chip_revenue": 2.0, "equip_revenue": 2.0, "tw_monthly_revenue": 2.0,
}


def _parse_ts(raw) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    return t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t


# ── 안정성: 수집기 ───────────────────────────────────────────────────────────

def check_collector_status(status: dict, now: dt.datetime,
                           stale_after_s: float = STALE_COLLECT_S,
                           expected: set[str] | None = None) -> list[CheckResult]:
    """status.json 스냅샷 → 수집기별 상태 + 전체 수집 경과 + 레지스트리 누락.

    경과 판정은 가장 낡은 수집기 기준 — status.json은 부분 수집(only=[…])도
    병합 갱신하므로 max(at)는 한 수집기만 돌아도 전체 정상으로 가장한다(codex #2).
    """
    out: list[CheckResult] = []
    ats: dict[str, dt.datetime] = {}
    for name, entry in sorted(status.items()):
        if name.startswith("_"):
            continue
        if not isinstance(entry, dict):
            continue
        st = entry.get("status", "")
        level = {"ok": "ok", "degraded": "warn", "missing_key": "warn"}.get(st, "alert")
        out.append(CheckResult(
            check="collector_status", pipeline=f"collector:{name}",
            axis="stability", level=level,
            detail=f"status={st} {entry.get('detail', '')}".strip()))
        if (t := _parse_ts(entry.get("at"))) is not None:
            ats[name] = t
    if ats:
        oldest_name, oldest = min(ats.items(), key=lambda kv: kv[1])
        age = (now - oldest).total_seconds()
        level = "alert" if age > stale_after_s else "ok"
        detail = f"가장 낡은 수집 {oldest_name} {age / 3600:.1f}h 전"
    else:
        level, detail = "alert", "수집 기록 없음 (status.json 비었거나 손상)"
    out.append(CheckResult(check="collect_recency", pipeline="collect",
                           axis="stability", level=level, detail=detail))
    if expected:
        missing = sorted(expected - set(status))
        if missing:
            out.append(CheckResult(
                check="collector_missing", pipeline="collect", axis="stability",
                level="warn", detail=f"레지스트리에 있으나 실행 기록 없음: {missing}"))
    return out


def check_engine_health(result: dict) -> list[CheckResult]:
    """Validate a bounded local /healthz probe result."""
    level = "alert"
    detail = "invalid engine health response"
    if not isinstance(result, dict):
        detail = f"invalid probe result: {type(result).__name__}"
    elif result.get("error"):
        detail = f"probe failed: {result['error']}"
    else:
        status_code = result.get("status_code")
        payload = result.get("payload")
        if status_code == 200 and isinstance(payload, dict) and payload.get("ok") is True:
            level = "ok"
            detail = "GET /healthz returned 200 ok=true"
        else:
            detail = f"status={status_code} ok={payload.get('ok') if isinstance(payload, dict) else None}"
    return [CheckResult(
        check="engine_health",
        pipeline="engine",
        axis="stability",
        level=level,
        detail=detail,
    )]


# ── 정합성: saveticker 커서 ──────────────────────────────────────────────────

def check_saveticker(stats: dict) -> list[CheckResult]:
    """firehose 무손실 커서 불변식 — status.json의 saveticker.stats 입력."""
    def r(check, level, detail, axis="consistency"):
        return CheckResult(check=check, pipeline="collector:saveticker",
                           axis=axis, level=level, detail=detail)

    out: list[CheckResult] = []
    hwm, anchor = stats.get("scan_hwm", 0), stats.get("observed_anchor", 0)
    out.append(r("st_hwm_anchor", "alert" if hwm > anchor else "ok",
                 f"scan_hwm={hwm} observed_anchor={anchor}"))
    pend = stats.get("pending_len", 0)
    level = "alert" if pend >= PENDING_MAX else ("warn" if pend >= PENDING_MAX * 0.8 else "ok")
    out.append(r("st_pending", level, f"pending={pend}/{PENDING_MAX}"))
    backlog = stats.get("backlog", 0)
    out.append(r("st_backlog", "warn" if backlog > BACKLOG_WARN else "ok",
                 f"backlog={backlog}"))
    out.append(r("st_calendar", "ok" if stats.get("calendar_ok", True) else "warn",
                 f"calendar_ok={stats.get('calendar_ok')}", axis="stability"))
    return out


# ── 안정성: 리포트 슬롯 ──────────────────────────────────────────────────────

def _last_slot(now: dt.datetime, times_kst: list[tuple[int, int]]) -> dt.datetime:
    """now 이전 가장 최근 KST 발화 시각(UTC). report_scheduler.next_fire의 역방향."""
    now_kst = now.astimezone(_KST)
    candidates = []
    for day_offset in (0, -1):
        base = (now_kst + dt.timedelta(days=day_offset)).date()
        for hh, mm in times_kst:
            t = dt.datetime.combine(base, dt.time(hh, mm), tzinfo=_KST)
            if t <= now_kst:
                candidates.append(t)
    return max(candidates).astimezone(dt.timezone.utc)


def check_report_recency(latest_generated_at: str | None, now: dt.datetime,
                         times_kst: list[tuple[int, int]],
                         grace_s: float = REPORT_GRACE_S) -> CheckResult:
    """마지막 발화 슬롯을 커버하는 리포트가 있는가 (슬롯+유예 경과 후에만 판정)."""
    def r(level, detail):
        return CheckResult(check="report_recency", pipeline="report",
                           axis="stability", level=level, detail=detail)

    if latest_generated_at is None:
        return r("alert", "리포트 파일 없음")
    latest = _parse_ts(latest_generated_at)
    if latest is None:
        return r("alert", f"generatedAt 해석 불가: {latest_generated_at!r}")
    slot = _last_slot(now, times_kst)
    if latest >= slot:
        return r("ok", f"최신 리포트 {latest.isoformat()} ≥ 슬롯 {slot.isoformat()}")
    if (now - slot).total_seconds() <= grace_s:
        return r("ok", f"슬롯 {slot.astimezone(_KST):%H:%M KST} 생성 유예 중")
    return r("alert", f"슬롯 {slot.astimezone(_KST):%m-%d %H:%M KST} 리포트 누락 "
                      f"(최신 {latest.isoformat()})")


def check_report_health(report: dict, filename: str) -> list[CheckResult]:
    """최신 리포트 내용 자체 점검 — 발행 상태·id↔파일명·축 카드 수."""
    def r(check, level, detail, axis):
        return CheckResult(check=check, pipeline="report", axis=axis,
                           level=level, detail=detail)

    out: list[CheckResult] = []
    ps = report.get("publish_status", "")
    # hold는 검증 게이트의 정상 산출일 수 있어 warn (report_pipeline.py:403)
    level = "ok" if ps == "ok" else ("warn" if ps in ("hold", "", None) else "alert")
    out.append(r("report_publish", level, f"publish_status={ps}", "stability"))
    rid = report.get("id", "")
    out.append(r("report_id_file", "ok" if filename == f"{rid}.json" else "alert",
                 f"id={rid} file={filename}", "consistency"))
    if report.get("format") == "axes":
        cards = report.get("cards", [])
        axes = [c.get("axis") if isinstance(c, dict) else None
                for c in cards] if isinstance(cards, list) else []
        axis_model = report.get("axisModel")
        expected = ["macro", "topic1", "topic2"] if axis_model == "topics_v1" else ["macro", "memory", "other"]
        known_model = axis_model in (None, "topics_v1")
        valid_cards = (isinstance(cards, list) and len(cards) == 3
                       and all(isinstance(card, dict)
                               and isinstance(card.get("axis"), str)
                               for card in cards))
        exact = known_model and valid_cards and Counter(axes) == Counter(expected)
        detail = (f"3축 완비 ({axis_model or 'legacy'})" if exact else
                  f"축 구성 불일치: model={axis_model!r} expected={expected} actual={axes}")
        out.append(r("report_axes", "ok" if exact else "warn", detail, "consistency"))
    return out


# ── 정확성: 지표 신선도·값 검증 ──────────────────────────────────────────────

def check_metric_freshness(ages_days: dict[str, float],
                           now: dt.datetime) -> list[CheckResult]:
    """지표별 마지막 관측 경과(일) — 기준 초과 warn, 2배 초과 alert."""
    out: list[CheckResult] = []
    for name, age in sorted(ages_days.items()):
        limit = METRIC_MAX_AGE_DAYS.get(name, METRIC_MAX_AGE_DEFAULT)
        level = "alert" if age > limit * 2 else ("warn" if age > limit else "ok")
        out.append(CheckResult(check="metric_freshness", pipeline=f"metric:{name}",
                               axis="accuracy", level=level,
                               detail=f"{age:.0f}일 경과 (기준 {limit:.0f}일)"))
    return out


def check_metric_sanity(series: dict[str, list[dict]],
                        now: dt.datetime | None = None) -> list[CheckResult]:
    """관측치 값 검증 — 그룹(meta)별 직전 대비 급변, 미래 타임스탬프.

    series: {metric: [{"ts","value","meta"}...]} (append 순서 = 시간 순서 가정)
    """
    out: list[CheckResult] = []
    today = (now or dt.datetime.now(dt.timezone.utc)).date()
    for metric, rows in sorted(series.items()):
        pipeline = f"metric:{metric}"
        is_calendar = metric.endswith("_calendar")   # 예정일 지표 — 미래 ts가 정상
        groups: dict[str, list[dict]] = {}
        future = 0
        for row in rows:
            try:
                ts = dt.date.fromisoformat(str(row.get("ts"))[:10])
                if ts > today + dt.timedelta(days=1):
                    future += 1
            except ValueError:
                pass
            key = str(sorted((row.get("meta") or {}).items()))
            groups.setdefault(key, []).append(row)
        out.append(CheckResult(
            check="metric_future_ts", pipeline=pipeline, axis="consistency",
            level="alert" if future and not is_calendar else "ok",
            detail=f"미래 ts {future}건" if future else "미래 ts 없음"))
        threshold = SPIKE_RATIO_OVERRIDES.get(metric, SPIKE_RATIO)
        spikes = []
        for key, g in groups.items():
            if len(g) < 2:
                continue
            prev, last = g[-2].get("value"), g[-1].get("value")
            if not isinstance(prev, (int, float)) or not isinstance(last, (int, float)):
                continue
            if abs(prev) < 1e-9:
                continue
            ratio = abs(last - prev) / abs(prev)
            if ratio > threshold:
                spikes.append(f"{g[-1].get('meta')} {prev}→{last} ({ratio:+.0%})")
        out.append(CheckResult(
            check="metric_spike", pipeline=pipeline, axis="accuracy",
            level="warn" if spikes else "ok",
            detail="; ".join(spikes) if spikes else "급변 없음"))
    return out
