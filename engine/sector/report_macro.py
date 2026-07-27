"""거시 관측 브리프 — 리포트 프롬프트 주입용 (2026-07-24 F1/F3).

macro_market 시계열(수집기 collectors/macro.py)의 최신 관측과 일간 변화율에
중요도 게이트를 적용해 draft/compose가 쓸 블록을 만든다. 코드만(LLM 없음),
never-raise — 데이터 없으면 ("", []) 반환하고 리포트는 기존대로 진행.

중요도 게이트(사용자: "항상이 아니라 중요할 때만"): |일간 변화율|이 임계를
넘은 항목만 ⚠중요 — 프롬프트가 이 표시를 기준으로 본문 포함 여부를 정한다.
"""
from __future__ import annotations

# name(meta.name) → 중요 임계 |day_pct| (%). 구현 시 확정값(2026-07-24 계획):
# 주요 지수 ±2%, 유가 ±5%, 환율 ±1.5%, 달러인덱스 ±1%, 금리(수익률 자체 변화) ±3%.
_THRESHOLDS = {
    "나스닥": 2.0,
    "S&P500": 2.0,
    "WTI유가": 5.0,
    "원달러": 1.5,
    "엔달러": 1.5,
    "달러인덱스": 1.0,
    "미국10년금리": 3.0,
}
_DEFAULT_THRESHOLD = 2.0


def _day_pct(rows) -> float | None:
    """최신 관측의 일간 변화율 — meta.day_pct 우선, 없으면 직전 관측 대비."""
    last = rows[-1]
    dp = (last.meta or {}).get("day_pct")
    try:
        if dp is not None:
            return float(dp)
    except (TypeError, ValueError):
        pass
    if len(rows) >= 2 and rows[-2].value not in (None, 0):
        try:
            return (last.value / rows[-2].value - 1.0) * 100.0
        except (TypeError, ZeroDivisionError):
            return None
    return None


def macro_brief(store, *, cutoff=None) -> tuple[str, list[str]]:
    """(프롬프트 블록, ⚠중요 항목 이름 리스트). 관측 부재·실패 시 ("", [])."""
    try:
        rows = store.read_metric("macro_market", last_n=200)
        if cutoff is not None:                   # look-ahead 차단(SF1과 동일 규칙)
            cut = (cutoff.date().isoformat() if hasattr(cutoff, "date")
                   else str(cutoff)[:10])
            rows = [o for o in rows if o.ts[:10] <= cut]
        if not rows:
            return "", []
        groups: dict[str, list] = {}
        for o in rows:                            # read_metric은 ts 오름차순
            name = str((o.meta or {}).get("name") or (o.meta or {}).get("token") or "")
            if name:
                groups.setdefault(name, []).append(o)
        lines, hot = [], []
        # 신선성 하한(codex M3): 기준일보다 5일 넘게 낡은 관측은 제외 —
        # 오래된 급변이 매 회차 ⚠중요로 재사용되는 것을 차단
        import datetime as _dt
        ref = (cutoff.date() if hasattr(cutoff, "date") else _dt.date.today()) \
            if cutoff is not None else _dt.date.today()
        for name, rs in groups.items():
            last = rs[-1]
            if last.value is None:
                continue
            try:
                age = (ref - _dt.date.fromisoformat(last.ts[:10])).days
                if age > 5:
                    continue
            except ValueError:
                pass
            dp = _day_pct(rs)
            chg = f" (일간 {dp:+.1f}%)" if dp is not None else ""
            mark = ""
            if dp is not None and abs(dp) >= _THRESHOLDS.get(name, _DEFAULT_THRESHOLD):
                mark = " ⚠중요"
                hot.append(name)
            unit = f"{last.unit}" if last.unit else ""
            lines.append(f"- {name} {last.value:,.2f}{unit}{chg} @{last.ts}{mark}")
        if not lines:
            return "", []
        block = ("[거시 관측 — 지수·금리·환율·유가 (⚠중요 = 임계 초과 변동)]\n"
                 + "\n".join(sorted(lines)))
        return block, hot
    except Exception:  # noqa: BLE001 — 거시 브리프 실패가 리포트를 못 죽인다
        return "", []
