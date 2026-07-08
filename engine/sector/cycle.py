"""메모리 섹터 P1 — 규칙 기반 사이클 스코어 (원칙 14)."""
from __future__ import annotations

from sector.contracts import MetricObservation
from sector.store import SectorStore


def _direction(series: list[MetricObservation]) -> float | None:
    """시리즈 마지막 2개 관측으로 방향 계산 (-1.0 ~ +1.0).

    fewer than 2 → None; a==0 → 0.0;
    else clamp((b - a) / |a| * 10, -1, 1).
    """
    if len(series) < 2:
        return None
    a_val = series[-2].value
    b_val = series[-1].value
    if a_val == 0:
        return 0.0
    raw = (b_val - a_val) / abs(a_val) * 10
    return max(-1.0, min(1.0, raw))


def _direction_yoy(series: list[MetricObservation]) -> float | None:
    """TSMC 월매출 YoY 메타 필드 기반 방향.

    meta.yoy 값의 마지막 2개를 이용: (yoy_b - yoy_a) / |yoy_a| * 10 clamped.
    """
    if len(series) < 2:
        return None
    a_yoy = series[-2].meta.get("yoy")
    b_yoy = series[-1].meta.get("yoy")
    if a_yoy is None or b_yoy is None:
        return None
    if a_yoy == 0:
        return 0.0
    raw = (b_yoy - a_yoy) / abs(a_yoy) * 10
    return max(-1.0, min(1.0, raw))


def _explain_line(factor: str, metric: str, series: list[MetricObservation],
                  direction_val: float) -> str:
    """explain 문자열 — factor + metric + ts 범위 + 방향값."""
    if len(series) >= 2:
        ts_range = f"{series[-2].ts}→{series[-1].ts}"
    elif series:
        ts_range = series[-1].ts
    else:
        ts_range = "n/a"
    return f"{factor}: {metric} {ts_range} {direction_val:+.2f}"


def pick_dram_series(rows) -> tuple[str, list]:
    """DAM DRAM 시리즈 canonical 선택 — 엔진·브리핑·화면이 전부 이 규칙 하나를 쓴다.

    주력 세대 우선(DDR5 > DDR4 > DDR3, 관측 6개 이상), 해당 없으면
    관측 수 최다 → 이름 lex 최솟값 (2026-07-07: 코드마다 다른 시리즈를 집어
    판정 +1.0 vs 화면 -5.2% 모순이 났던 사고의 재발 방지).
    """
    items: dict[str, list] = {}
    for o in rows:
        it = (o.meta.get("item") or "")
        items.setdefault(it, []).append(o)
    if not items:
        return "", []
    for gen in ("DDR5", "DDR4", "DDR3"):
        for it in sorted(items):
            if gen in it and len(items[it]) >= 6:
                return it, sorted(items[it], key=lambda o: o.ts)
    best = min(items, key=lambda i: (-len(items[i]), i))
    return best, sorted(items[best], key=lambda o: o.ts)


# ── Supply Overbuild Risk — 공급 과잉 경보 게이지 ────────────────────────────
# score 4요소가 아니라 별도 경보 (2026-07-08 합의): 공급 데이터는 분기 단위·부호가
# 애매해(단기 호재·장기 악재) 가중평균에 넣으면 판정을 오염시킴. 신호가 겹칠 때만 경보.
_CAPEX_SURGE_PCT = 10.0     # 메모리 3사 capex 평균 QoQ
_EQUIP_SURGE_PCT = 8.0      # 장비 4사 매출 평균 QoQ
_INV_REBOUND_PCT = 1.0      # 재고지수 MoM


def _latest_qoq_pct(rows: list[MetricObservation]) -> float | None:
    rows = sorted(rows, key=lambda o: o.ts)
    if len(rows) < 2 or rows[-2].value == 0:
        return None
    return (rows[-1].value / rows[-2].value - 1) * 100


def _avg_company_qoq(store: SectorStore, metric: str) -> float | None:
    by: dict[str, list[MetricObservation]] = {}
    for o in store.read_metric(metric, last_n=200):
        by.setdefault(o.meta.get("token", "?"), []).append(o)
    qoqs = [q for q in (_latest_qoq_pct(v) for v in by.values()) if q is not None]
    return round(sum(qoqs) / len(qoqs), 1) if qoqs else None


def supply_risk(store: SectorStore) -> dict:
    """공급 과잉 경보: 낮음(low)/상승(rising)/높음(high)/데이터 부족(nodata).

    신호 3개 — ① 3사 capex 급증 ② 장비 매출 급증 ③ 재고 반등.
    계산 가능한 신호가 2개 미만이면 nodata, 발동 0=low, 1=rising, 2+=high.
    """
    capex = _avg_company_qoq(store, "memory_capex")
    equip = _avg_company_qoq(store, "equip_revenue")
    inv_rows = [o for o in store.read_metric("kr_semi_production_index", last_n=100)
                if "재고" in o.meta.get("item", "")]
    inv = _latest_qoq_pct(inv_rows)
    signals = [
        {"key": "memory_capex", "name": "메모리 3사 capex QoQ", "pct": capex,
         "fired": capex is not None and capex > _CAPEX_SURGE_PCT},
        {"key": "equip_revenue", "name": "장비 4사 매출 QoQ", "pct": equip,
         "fired": equip is not None and equip > _EQUIP_SURGE_PCT},
        {"key": "inventory_rebound", "name": "재고지수 MoM",
         "pct": round(inv, 1) if inv is not None else None,
         "fired": inv is not None and inv > _INV_REBOUND_PCT},
    ]
    available = sum(1 for s in signals if s["pct"] is not None)
    fired = sum(1 for s in signals if s["fired"])
    level = ("nodata" if available < 2
             else "high" if fired >= 2 else "rising" if fired == 1 else "low")
    return {"level": level, "signals": signals, "available": available, "fired": fired}


def compute(store: SectorStore) -> dict:
    """섹터 사이클 상태 계산.

    반환: {"state", "score", "factors": {"price", "inventory", "demand", "supply"},
           "explain": [...], "factor_details": [...]}
    """
    # ── price ────────────────────────────────────────────────────────────────
    price_all = store.read_metric("kr_dram_export_price_index")
    _price_source = "ecos"
    _dam_selected_item = ""
    if price_all:
        price_dram = [o for o in price_all if "D램" in o.meta.get("item", "")]
        price_series = price_dram if price_dram else price_all
    else:
        # ECOS 시리즈가 없으면 Stanford DAM memory_price_usd_per_gb 폴백
        dam_all = store.read_metric("memory_price_usd_per_gb")
        dam_dram = [o for o in dam_all if o.meta.get("category") == "DRAM"]
        if dam_dram:
            # canonical 선택 — pick_dram_series (판정·브리핑·화면 공용 규칙)
            selected_item, _sorted_rows = pick_dram_series(dam_dram)
            price_series = _sorted_rows
            _price_source = "dam_fallback"
            _dam_selected_item = selected_item
        else:
            price_series = []
            _dam_selected_item = ""
    price = _direction(price_series)

    # ── inventory ────────────────────────────────────────────────────────────
    inv_all = store.read_metric("kr_semi_production_index")
    inv_series = [o for o in inv_all if "재고" in o.meta.get("item", "")]
    if inv_series:
        inv_raw = _direction(inv_series)
        inventory = -inv_raw if inv_raw is not None else None
    else:
        inventory = None

    # ── demand ───────────────────────────────────────────────────────────────
    export_series = store.read_metric("kr_semi_export")
    # 10일 잠정치는 월 3회(01~10/01~20/01~31) 혼재 — 같은 구간끼리만 월간 비교
    # (2026-07-07 실측 스키마: meta.item=집계구간)
    early = [o for o in export_series if o.meta.get("item") == "01~10"]
    if early:
        export_series = early
    export_dir = _direction(export_series)

    rev_all = store.read_metric("tw_monthly_revenue")
    tsmc_series = [o for o in rev_all if o.meta.get("name") == "TSMC"]
    tsmc_dir = _direction_yoy(tsmc_series)

    demand_parts = [d for d in (export_dir, tsmc_dir) if d is not None]
    demand = sum(demand_parts) / len(demand_parts) if demand_parts else None

    # ── supply (P1: 미구현) ──────────────────────────────────────────────────
    supply: float | None = None

    factors: dict[str, float | None] = {
        "price": price,
        "inventory": inventory,
        "demand": demand,
        "supply": supply,
    }

    # ── 가중평균 ──────────────────────────────────────────────────────────────
    weights = {"price": 0.35, "inventory": 0.25, "demand": 0.30, "supply": 0.10}
    available = {k: v for k, v in factors.items() if v is not None}

    if len(available) < 2:
        explain = [
            f"{k}: 데이터 없음"
            for k, v in factors.items()
            if v is None and k != "supply"  # supply는 P1 미구현이므로 별도 메시지
        ]
        if factors["supply"] is None:
            explain.append("supply: P1 미구현")
        return {
            "state": "insufficient",
            "score": 0.0,
            "factors": factors,
            "explain": explain,
            "factor_details": [],
        }

    total_w = sum(weights[k] for k in available)
    score = sum(weights[k] * v for k, v in available.items()) / total_w

    if score > 0.15:
        state = "up"
    elif score < -0.15:
        state = "down"
    else:
        state = "transition"

    # explain 문자열 생성
    explain: list[str] = []
    if price is not None:
        if _price_source == "dam_fallback":
            explain.append(_explain_line(
                f"price(fallback DAM): {_dam_selected_item}",
                "memory_price_usd_per_gb", price_series, price))
        else:
            explain.append(_explain_line("price", "kr_dram_export_price_index",
                                         price_series, price))
    if inventory is not None:
        explain.append(_explain_line("inventory", "kr_semi_production_index(재고)",
                                     inv_series, inventory))
    if demand is not None:
        parts_desc: list[str] = []
        if export_dir is not None:
            parts_desc.append(f"kr_semi_export {export_dir:+.2f}")
        if tsmc_dir is not None:
            parts_desc.append(f"TSMC_yoy {tsmc_dir:+.2f}")
        explain.append(f"demand: {' / '.join(parts_desc)} → {demand:+.2f}")

    # ── factor_details (P2 구조화 필드) ─────────────────────────────────────
    factor_details: list[dict] = []
    if price is not None:
        _price_metric = ("memory_price_usd_per_gb"
                         if _price_source == "dam_fallback"
                         else "kr_dram_export_price_index")
        factor_details.append({
            "factor": "price",
            "metric": _price_metric,
            "from_ts": price_series[-2].ts if len(price_series) >= 2 else None,
            "to_ts": price_series[-1].ts if price_series else None,
            "direction": price,
        })
    if inventory is not None:
        factor_details.append({
            "factor": "inventory",
            "metric": "kr_semi_production_index",
            "from_ts": inv_series[-2].ts if len(inv_series) >= 2 else None,
            "to_ts": inv_series[-1].ts if inv_series else None,
            "direction": inventory,
        })
    if demand is not None:
        _demand_series = export_series if export_dir is not None else tsmc_series
        _demand_metric = "kr_semi_export" if export_dir is not None else "tw_monthly_revenue"
        factor_details.append({
            "factor": "demand",
            "metric": _demand_metric,
            "from_ts": _demand_series[-2].ts if len(_demand_series) >= 2 else None,
            "to_ts": _demand_series[-1].ts if _demand_series else None,
            "direction": demand,
        })

    return {
        "state": state,
        "score": round(score, 4),
        "factors": factors,
        "explain": explain,
        "factor_details": factor_details,
    }
