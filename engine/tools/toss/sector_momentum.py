"""최근 거래일의 KOSPI 업종 모멘텀을 결정적으로 계산한다.

업종 분류는 Toss WTS overview의 WICS, 가격은 Toss 일봉을 우선 사용한다.
개별 종목의 Toss 차트만 실패한 경우 Yahoo 일봉으로 보완한다. 결과는 모델 추정이
아니라 종목별 종가 수익률을 업종 단위로 집계한 표본 통계다.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.price.yahoo import daily_history

from .client import TossClient
from .price import daily_candles
from .readonly import execute_wts_operation

_UNIVERSE_PATH = Path(__file__).resolve().parents[1] / "price" / "universe_kospi.json"
_PREFERRED_RE = re.compile(r"우(?:B|C)?$")
_META_TTL_S = 6 * 60 * 60
_meta_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class _ResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectorLeader(_ResultModel):
    code: str
    name: str
    return_pct: float
    source: Literal["toss_wts", "yahoo"]


class SectorMomentumRow(_ResultModel):
    rank: int = 0
    sector_code: str
    sector_name: str
    member_count: int
    median_return_pct: float
    equal_weight_return_pct: float
    market_cap_weighted_return_pct: float
    breadth_positive_pct: float
    leaders: list[SectorLeader] = Field(default_factory=list)


class SectorMomentumResult(_ResultModel):
    status: Literal["ok", "partial", "error"]
    market: Literal["KOSPI"] = "KOSPI"
    as_of: str | None = None
    lookback_sessions: int
    base_session: str | None = None
    universe_requested: int
    universe_valid: int = 0
    coverage_pct: float = 0.0
    sector_count: int = 0
    positive_sector_count: int = 0
    sectors: list[SectorMomentumRow] = Field(default_factory=list)
    excluded: dict[str, int] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    methodology: str
    error: str | None = None


def is_sector_momentum_request(text: str, market_scope: str = "kr") -> bool:
    """질문이 한국 업종/섹터의 최근 등락 비교를 요구하는지 판정한다."""
    if market_scope not in ("kr", "mixed"):
        return False
    normalized = " ".join((text or "").lower().split())
    sector_signal = any(word in normalized for word in ("섹터", "업종", "산업군"))
    move_signal = any(
        word in normalized
        for word in ("오른", "상승", "강세", "주도", "등락", "수익률", "모멘텀")
    )
    recent_signal = any(
        word in normalized for word in ("최근", "거래일", "며칠", "이번 주", "금주")
    )
    return sector_signal and move_signal and recent_signal


def parse_lookback_sessions(text: str, default: int = 3) -> int:
    """“2~3일”은 비교 구간의 상단인 3거래일로 해석한다."""
    normalized = (text or "").replace("–", "-").replace("~", "-")
    range_match = re.search(r"(\d+)\s*-\s*(\d+)\s*(?:거래)?일", normalized)
    if range_match:
        return min(max(max(map(int, range_match.groups())), 1), 20)
    single = re.search(r"최근\s*(\d+)\s*(?:거래)?일", normalized)
    if single:
        return min(max(int(single.group(1)), 1), 20)
    if "이번 주" in normalized or "금주" in normalized:
        return 5
    return min(max(default, 1), 20)


def _universe(limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    raw = json.loads(_UNIVERSE_PATH.read_text(encoding="utf-8"))
    selected: list[dict[str, Any]] = []
    excluded = {"preferred_or_spac": 0, "invalid": 0}
    for item in raw:
        code, name = str(item.get("code") or ""), str(item.get("name") or "")
        if len(code) != 6 or not code.isdigit() or not name:
            excluded["invalid"] += 1
            continue
        if _PREFERRED_RE.search(name) or "스팩" in name.upper() or "SPAC" in name.upper():
            excluded["preferred_or_spac"] += 1
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected, excluded


async def _classification(
    client: TossClient, code: str, fallback_marcap: float
) -> dict[str, Any]:
    cached = _meta_cache.get(code)
    now = time.monotonic()
    if cached and now < cached[0]:
        return cached[1]
    raw = await execute_wts_operation(
        "getWtsOverview",
        path_params={"productCode": f"A{code}"},
        client=client,
    )
    result = (raw or {}).get("result") or {}
    company = result.get("company") or {}
    wics = company.get("wics") or company.get("industry") or {}
    value = {
        "sector_code": str(wics.get("code") or ""),
        "sector_name": str(wics.get("displayName") or ""),
        "market": str((result.get("market") or {}).get("code") or ""),
        "market_cap": float(
            result.get("marketValueKrw")
            or company.get("marketValueKrw")
            or fallback_marcap
            or 0
        ),
        "name": str(company.get("name") or ""),
    }
    _meta_cache[code] = (now + _META_TTL_S, value)
    return value


def _toss_closes(candles: list[Any], cutoff: str) -> list[tuple[str, float]]:
    by_date: dict[str, float] = {}
    for candle in candles:
        date = str(candle.dt).split("T", 1)[0]
        if date <= cutoff and candle.close is not None:
            by_date[date] = float(candle.close)
    return sorted(by_date.items())


async def _stock_observation(
    client: TossClient,
    item: dict[str, Any],
    *,
    lookback: int,
    cutoff: str,
) -> tuple[dict[str, Any] | None, str]:
    code = str(item["code"])
    classification_result, candles_result = await asyncio.gather(
        _classification(client, code, float(item.get("marcap") or 0)),
        daily_candles(code, count=min(max(lookback + 8, 10), 60), client=client),
        return_exceptions=True,
    )
    if isinstance(classification_result, BaseException):
        return None, "classification_error"
    classification = classification_result
    if classification.get("market") != "KSP":
        return None, "not_kospi"
    if not classification.get("sector_name"):
        return None, "missing_sector"

    source: Literal["toss_wts", "yahoo"] = "toss_wts"
    closes: list[tuple[str, float]] = []
    if not isinstance(candles_result, BaseException):
        closes = _toss_closes(candles_result, cutoff)
    if len(closes) < lookback + 1:
        yahoo = await daily_history(code, count=lookback + 8, until=cutoff)
        if "error" not in yahoo:
            yahoo_by_date = {
                str(row["date"]): float(row["close"])
                for row in yahoo.get("candles", [])
                if row.get("close") is not None and str(row.get("date") or "") <= cutoff
            }
            closes = sorted(yahoo_by_date.items())
            source = "yahoo"
    if len(closes) < lookback + 1:
        return None, "missing_history"
    base_date, base_close = closes[-(lookback + 1)]
    as_of, latest_close = closes[-1]
    if base_close <= 0:
        return None, "invalid_price"
    return {
        "code": code,
        "name": classification.get("name") or item.get("name") or code,
        "sector_code": classification["sector_code"],
        "sector_name": classification["sector_name"],
        "market_cap": max(float(classification.get("market_cap") or 0), 0.0),
        "return_pct": (latest_close / base_close - 1.0) * 100.0,
        "base_date": base_date,
        "as_of": as_of,
        "source": source,
    }, ""


async def collect_sector_momentum(
    *,
    lookback_sessions: int = 3,
    cutoff: str | None = None,
    universe_size: int = 200,
    min_members: int = 2,
) -> SectorMomentumResult:
    """시가총액 상위 KOSPI 보통주 표본의 WICS 업종 모멘텀을 계산한다."""
    lookback = min(max(int(lookback_sessions), 1), 20)
    size = min(max(int(universe_size), 30), 300)
    min_members = min(max(int(min_members), 1), 20)
    cutoff_date = (cutoff or dt.date.today().isoformat())[:10]
    items, excluded = _universe(size)
    methodology = (
        f"시가총액 상위 KOSPI 보통주 {len(items)}개 표본; Toss WICS 분류; "
        f"최근 {lookback}거래세션 종가 수익률; 업종 중앙값 순위 "
        "(동일시점 종목만, 최소 구성종목 수 적용); Toss 일봉 우선·Yahoo 개별 폴백"
    )

    async with TossClient() as client:
        results = await asyncio.gather(
            *(
                _stock_observation(
                    client, item, lookback=lookback, cutoff=cutoff_date
                )
                for item in items
            )
        )
    observations = [row for row, _ in results if row is not None]
    for _, reason in results:
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
    if not observations:
        return SectorMomentumResult(
            status="error",
            lookback_sessions=lookback,
            universe_requested=len(items),
            excluded=excluded,
            methodology=methodology,
            error="업종 분류와 가격 이력을 함께 확보한 종목이 없습니다",
        )

    # 거래정지·업데이트 지연 종목이 이전 날짜 수익률로 섞이지 않게 최빈 최신일만 사용한다.
    as_of_counts = Counter(row["as_of"] for row in observations)
    as_of = max(as_of_counts, key=lambda day: (as_of_counts[day], day))
    aligned = [row for row in observations if row["as_of"] == as_of]
    excluded["stale_as_of"] = len(observations) - len(aligned)
    base_counts = Counter(row["base_date"] for row in aligned)
    base_session = max(base_counts, key=lambda day: (base_counts[day], day))
    same_window = [row for row in aligned if row["base_date"] == base_session]
    excluded["different_base_session"] = len(aligned) - len(same_window)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in same_window:
        grouped[(row["sector_code"], row["sector_name"])].append(row)

    sector_rows: list[SectorMomentumRow] = []
    too_small = 0
    for (sector_code, sector_name), members in grouped.items():
        if len(members) < min_members:
            too_small += len(members)
            continue
        returns = [float(member["return_pct"]) for member in members]
        total_cap = sum(float(member["market_cap"]) for member in members)
        weighted = (
            sum(
                float(member["return_pct"]) * float(member["market_cap"])
                for member in members
            ) / total_cap
            if total_cap > 0
            else statistics.fmean(returns)
        )
        leaders = sorted(members, key=lambda member: member["return_pct"], reverse=True)[:3]
        sector_rows.append(SectorMomentumRow(
            sector_code=sector_code,
            sector_name=sector_name,
            member_count=len(members),
            median_return_pct=round(statistics.median(returns), 2),
            equal_weight_return_pct=round(statistics.fmean(returns), 2),
            market_cap_weighted_return_pct=round(weighted, 2),
            breadth_positive_pct=round(
                sum(value > 0 for value in returns) / len(returns) * 100, 1
            ),
            leaders=[
                SectorLeader(
                    code=member["code"],
                    name=member["name"],
                    return_pct=round(float(member["return_pct"]), 2),
                    source=member["source"],
                )
                for member in leaders
            ],
        ))
    excluded["sector_below_min_members"] = too_small
    sector_rows.sort(
        key=lambda row: (
            row.median_return_pct,
            row.breadth_positive_pct,
            row.market_cap_weighted_return_pct,
        ),
        reverse=True,
    )
    for rank, row in enumerate(sector_rows, 1):
        row.rank = rank

    valid = len(same_window)
    coverage = round(valid / len(items) * 100, 1) if items else 0.0
    sources = sorted({row["source"] for row in same_window})
    status: Literal["ok", "partial", "error"] = "ok" if coverage >= 70 else "partial"
    return SectorMomentumResult(
        status=status,
        as_of=as_of,
        lookback_sessions=lookback,
        base_session=base_session,
        universe_requested=len(items),
        universe_valid=valid,
        coverage_pct=coverage,
        sector_count=len(sector_rows),
        positive_sector_count=sum(
            row.median_return_pct > 0 for row in sector_rows
        ),
        sectors=sector_rows,
        excluded=excluded,
        sources=sources,
        methodology=methodology,
        error=None if sector_rows else "최소 구성종목 수를 충족한 업종이 없습니다",
    )
