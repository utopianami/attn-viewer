"""수집기 — macro (지표: macro_market, 거시 시장 스냅샷).

나스닥·S&P·미10y·달러인덱스·원/달러·엔/달러·WTI — 시황 리포트의 거시 축
(2026-07-24 사용자: "나스닥 전체가 폭락했는데 12시간 요약에 그 내용이 없는 게
말이 안 된다" + 엔 관련 지표 명시 요청). tools.price.yahoo.quote 재사용
(원칙: 시세는 야후 종가만). 메모리 가격 축 심화는 범위 외.
"""
from __future__ import annotations

import datetime as _dt

import httpx

from sector.contracts import CollectorResult, MetricObservation
from sector.store import SectorStore
from tools.price.yahoo import quote

NAME = "macro"
KIND = "metric"

# token → (사람이 읽는 이름, 단위) (meta.name이 시계열 그룹 키 — 섞이면 허위 변화율.
# 단위 명기: yahoo 통화코드를 unit으로 쓰면 금리·지수가 무단위/USD로 왜곡 — codex M2)
_TICKERS = {
    "^IXIC": ("나스닥", "pt"),
    "^GSPC": ("S&P500", "pt"),
    "^TNX": ("미국10년금리", "%"),
    "DX-Y.NYB": ("달러인덱스", "pt"),
    "KRW=X": ("원달러", "원"),
    "JPY=X": ("엔달러", "엔"),
    "CL=F": ("WTI유가", "USD"),
}


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    rows = await quote(list(_TICKERS), client=client)
    today = _dt.date.today().isoformat()
    obs: list[MetricObservation] = []
    errors: list[str] = []
    for row in rows:
        token = row.get("token")
        if row.get("error"):
            errors.append(f"{token}: {row['error']}")
            continue
        try:
            try:
                value = float(row["cur"])
            except (KeyError, TypeError, ValueError):
                value = float(row["last"])
            name, unit = _TICKERS.get(token, (token, ""))
            # ts는 시세 기준일(as_of) — 수집일로 찍으면 휴장일 과거 종가가 오늘
            # 값으로 위장(codex H6)
            as_of = str(row.get("as_of") or "")[:10] or today
            obs.append(MetricObservation(
                metric="macro_market", ts=as_of, value=value, unit=unit,
                meta={"name": name, "token": token,
                      "day_pct": row.get("day_pct")}))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{token}: {e}")
    # 커버리지 하한(codex M3): 지수·유가 등 절반 이상 실패면 degraded — 조용한 누락 방지
    status = "degraded" if len(obs) < (len(_TICKERS) + 1) // 2 else "ok"
    detail = f"errors: {'; '.join(errors)}"[:300] if errors else ""
    return CollectorResult(name=NAME, kind=KIND, observations=obs, status=status, detail=detail)
