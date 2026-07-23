"""공유 기간 파싱 — freshness·guard가 함께 쓰는 단일 소스 (2부 T9 블로커 3).

`thesis_store.py`의 freshness 판정과 `thesis_guard.py`의 최신 관측 선택이
동일한 "미래·파싱불가 관측은 무효" 규칙을 따라야 한다 — 두 곳에 같은 로직을
복붙하면 한쪽만 고쳐지는 drift가 생기므로 이 모듈 하나로 합친다.
"""
from __future__ import annotations

import datetime as _dt
from calendar import monthrange


def parse_period(ts: str) -> tuple[_dt.datetime, _dt.datetime] | None:
    """ts를 (기간 시작, 기간 끝)으로 파싱한다.

    'YYYY-MM'은 그 달 전체(1일 00:00 ~ 말일 23:59:59)로, 그 외 날짜/타임스탬프는
    정확한 순간(시작==끝)으로 다룬다. naive는 UTC로 간주. 파싱 불가면 None.
    """
    ts = (ts or "").strip()
    try:
        if len(ts) == 7 and ts[4] == "-":
            year, month = int(ts[:4]), int(ts[5:7])
            start = _dt.datetime(year, month, 1, tzinfo=_dt.timezone.utc)
            last_day = monthrange(year, month)[1]
            end = _dt.datetime(year, month, last_day, 23, 59, 59,
                               tzinfo=_dt.timezone.utc)
            return start, end
        parsed = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_dt.timezone.utc)
        return parsed, parsed
    except (ValueError, TypeError):
        return None
