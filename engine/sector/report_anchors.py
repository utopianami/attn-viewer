"""코드가 계산하는 typed 수치 anchor — 검증(numeric_facts 정체성 대조)의 기준.

cutoff는 일 단위 정밀("YYYY-MM"은 월초로 정규화), ingested_at look-ahead 게이트,
전량 읽기(last_n 슬라이스가 미래 행으로 히스토리를 밀어내는 버그 차단). 스펙 v3."""
from __future__ import annotations

from datetime import datetime, timezone

from sector.metrics_registry import METRIC_REGISTRY
from sector.report_contracts import Anchor
from sector.report_input import _parse_ts
from sector.report_metrics_allowlist import REPORT_METRICS


def _ts_date(ts: str) -> str:
    """'YYYY-MM' → 'YYYY-MM-01', 'YYYY-MM-DD' 그대로. 그 외 ''(제외)."""
    if len(ts) == 7:
        return ts + "-01"
    if len(ts) == 10:
        return ts
    return ""


_FULL_MONTH = __import__("re").compile(r"^01~(2[89]|3[01])$")


def _group_key(meta: dict) -> str:
    for k in ("item", "model", "code", "token", "provider", "app", "country", "title"):
        if meta.get(k):
            v = str(meta[k])
            # 관세청 월말 라벨('01~30'/'01~31')이 월 길이에 따라 시리즈를 갈라
            # 5월을 건너뛴 +40.3%가 나온 확정 오류(감사 4.4) — 한 시리즈로 정규화
            if _FULL_MONTH.match(v):
                return "full_month"
            return v
    return ""


def _comparison_kind(prev_ts: str, cur_ts: str) -> str:
    """두 기간 문자열의 차이로 비교 종류를 코드가 판정 — LLM 추측 금지(감사 P0-5)."""
    try:
        if len(prev_ts) >= 10 and len(cur_ts) >= 10 and prev_ts[:7] == cur_ts[:7]:
            days = (datetime.fromisoformat(cur_ts[:10]) - datetime.fromisoformat(prev_ts[:10])).days
            return "DoD" if days == 1 else f"{days}D"
        months = ((int(cur_ts[:4]) - int(prev_ts[:4])) * 12
                  + int(cur_ts[5:7]) - int(prev_ts[5:7]))
        return {1: "MoM", 3: "QoQ", 12: "YoY"}.get(months, f"{months}M")
    except (ValueError, IndexError):
        return ""


_TOP_K = 8          # metric당 anchor 상한 — 최신순(토큰 모델 180개 프롬프트 점령 방지, F10)
_STALE_DAYS = 365   # 최신 관측이 이보다 낡은 시리즈는 anchor 제외
                    # (실측 2026-07-22: McCallum DRAM historical 2024-07이 1.53$/GB로
                    #  현행 Keepa 8.4$/GB 옆에 등재 — 낡은 시리즈가 프롬프트·수치풀 오염)


def build_anchors(store, *, now: datetime, metrics: list[str] | None = None) -> list[Anchor]:
    names = metrics if metrics is not None else REPORT_METRICS
    cutoff = now.astimezone(timezone.utc).date().isoformat()
    stale_floor = (now.astimezone(timezone.utc).date()
                   - __import__("datetime").timedelta(days=_STALE_DAYS)).isoformat()
    out: list[Anchor] = []
    for m in names:
        info = METRIC_REGISTRY.get(m, {})
        try:
            rows = store.read_metric(m, last_n=100_000)     # 전량 → 히스토리 안 밀림
        except Exception:  # noqa: BLE001 — never-raise
            continue
        ok = []
        for o in rows:
            d = _ts_date(o.ts)
            if not d or d > cutoff:                          # 일 단위 정밀 컷
                continue
            ing = _parse_ts(getattr(o, "ingested_at", "") or "")
            if ing is not None and ing > now:                # 수집시각 look-ahead 차단
                continue
            ok.append(o)
        groups: dict[str, list] = {}
        for o in ok:
            groups.setdefault(_group_key(o.meta), []).append(o)
        ranked = sorted(groups.items(),
                        key=lambda kv: _ts_date(max(kv[1], key=lambda o: _ts_date(o.ts)).ts),
                        reverse=True)[:_TOP_K]   # metric당 최신 상위만(F10)
        for gk, series in ranked:
            series.sort(key=lambda o: _ts_date(o.ts))
            latest = series[-1]
            if _ts_date(latest.ts) < stale_floor:
                continue                        # 낡은 시리즈 — anchor 승격 금지
            delta, prev_p, prev_v, kind = None, "", None, ""
            if len(series) >= 2 and series[-2].value:
                prev = series[-2]
                delta = (latest.value - prev.value) / abs(prev.value) * 100.0
                prev_p, prev_v = prev.ts, prev.value
                kind = _comparison_kind(prev.ts, latest.ts)
            src = info.get("origin") or info.get("label", m)
            if "프록시" in str(info.get("label", "")):
                # 프록시 지표는 정체 경고를 앵커에도 실어 프롬프트까지 전달(감사 5.1~5.3)
                src = f"{info['label']} — {src}"
            out.append(Anchor(anchor_id=f"{m}:{gk}", metric=m, entity=gk,
                              period=latest.ts, value=latest.value, unit=latest.unit,
                              delta_pct=delta, as_of=latest.ts, source=src,
                              prev_period=prev_p, prev_value=prev_v,
                              comparison_kind=kind))
    return out
