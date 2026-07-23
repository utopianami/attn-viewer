"""수집기 공용 헬퍼 — mops_tw·customs_kr·ecos에 복붙돼 있던 파싱 유틸 통합.

수집기 모듈 규약(NAME/KIND/collect)이 없으므로 registry() 명시 목록과 무관.
"""
from __future__ import annotations

import datetime as _dt


def num(raw: str | None) -> float | None:
    """천단위 콤마 허용, "-"/빈값은 None."""
    s = (raw or "").strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def months_ago(d: _dt.date, n: int) -> str:
    """d에서 n개월 전을 "YYYYMM" 문자열로."""
    y, m = d.year, d.month - n
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y}{m:02d}"
