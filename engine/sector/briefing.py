"""종합 브리핑 — 수집 지표를 인과 사슬로 읽어 3~4줄 요약 (P2, 2026-07-07).

단순 나열이 아니라 "AI 수요 → capex → 메모리"를 엮는 서사.
지표에서 팩트를 규칙으로 추출(재현 가능) → sonnet이 문장화. LLM 실패 시 규칙 문장 폴백.
"""
from __future__ import annotations

from sector.cycle import compute as cycle_compute
from sector.store import SectorStore


def _pct_change(series: list[float]) -> float | None:
    """최근값 vs 직전값 변화율(%). 2개 미만이면 None."""
    if len(series) < 2 or series[-2] == 0:
        return None
    return round((series[-1] / series[-2] - 1) * 100, 1)


def _token_growth(store: SectorStore) -> float | None:
    """전세계 토큰 사용량 — 최근 7일 평균 vs 직전 7일 평균 성장률(%)."""
    rows = store.read_metric("openrouter_daily_tokens", last_n=2000)
    by_day: dict[str, float] = {}
    for o in rows:
        by_day[o.ts] = by_day.get(o.ts, 0.0) + o.value
    days = sorted(by_day)
    if len(days) < 14:
        return None
    recent = sum(by_day[d] for d in days[-7:]) / 7
    prior = sum(by_day[d] for d in days[-14:-7]) / 7
    if prior == 0:
        return None
    return round((recent / prior - 1) * 100, 1)


def gather_facts(store: SectorStore) -> dict:
    cyc = cycle_compute(store)
    tok = _token_growth(store)
    # D램 가격 방향 — cycle과 동일한 canonical 시리즈 규칙 (모순 방지)
    from sector.cycle import pick_dram_series
    dram_rows = [o for o in store.read_metric("memory_price_usd_per_gb", last_n=400)
                 if (o.meta or {}).get("category") == "DRAM"]
    dram_item, dram_sorted = pick_dram_series(dram_rows)
    dram = [o.value for o in dram_sorted]
    # 반도체 수출 01~10 월간 변화
    exp = [o.value for o in store.read_metric("kr_semi_export", last_n=60)
           if (o.meta or {}).get("item") == "01~10"]
    # 재고지수
    inv = [o.value for o in store.read_metric("kr_semi_production_index", last_n=100)
           if "재고" in (o.meta or {}).get("item", "")]
    # TSMC 월매출 YoY — value는 매출 절대값(천TWD)이므로 meta.yoy를 써야 함 (스크린샷 검증 발견)
    tsmc = [o.meta.get("yoy") for o in store.read_metric("tw_monthly_revenue", last_n=60)
            if (o.meta or {}).get("name") == "TSMC" and o.meta.get("yoy") is not None]
    return {
        "cycle": cyc,
        "token_growth_pct": tok,
        "dram_price_change_pct": _pct_change(dram),
        "dram_series": dram_item.split("|")[-1] if dram_item else None,
        "semi_export_change_pct": _pct_change(exp),
        "inventory_change_pct": _pct_change(inv),
        "tsmc_yoy": round(tsmc[-1], 1) if tsmc else None,
    }


def _rule_text(f: dict) -> str:
    cyc = f["cycle"]
    label = {"up": "업사이클", "down": "다운사이클", "transition": "전환 구간",
             "insufficient": "판정 데이터 축적 중"}.get(cyc.get("state"), "판정 불가")
    bits = [f"메모리 사이클은 현재 {label}"]
    if cyc.get("state") != "insufficient":
        bits[0] += f" (score {cyc.get('score', 0):.2f})"
    if f["token_growth_pct"] is not None:
        d = "증가" if f["token_growth_pct"] >= 0 else "감소"
        bits.append(f"AI 토큰 수요는 주간 {abs(f['token_growth_pct'])}% {d}")
    if f["dram_price_change_pct"] is not None:
        d = "상승" if f["dram_price_change_pct"] >= 0 else "하락"
        bits.append(f"D램 가격 {d}")
    if f["semi_export_change_pct"] is not None:
        bits.append(f"반도체 수출(월초) {f['semi_export_change_pct']:+.1f}%")
    if f["inventory_change_pct"] is not None:
        d = "재고 증가(주의)" if f["inventory_change_pct"] > 0 else "재고 감소(긍정)"
        bits.append(d)
    return " · ".join(bits) + "."


async def build_briefing(store: SectorStore, overrides: dict | None = None) -> dict:
    facts = gather_facts(store)
    fallback = _rule_text(facts)
    prompt = (
        "너는 메모리 반도체 애널리스트다. 아래 지표를 근거로, AI 수요가 메모리로 이어지는 "
        "인과 사슬(AI 토큰 수요 → 하이퍼스케일러 capex → 메모리 가격·수출·재고)을 짚어 "
        "투자자용 종합 브리핑을 3~4문장으로 써라. 숫자를 인용하되 과장 없이, "
        "'그래서 지금 사이클 어디인가'가 드러나게. 지표:\n"
        f"- 메모리 사이클 판정: {facts['cycle'].get('state')} (score {facts['cycle'].get('score')})\n"
        f"- 전세계 AI 토큰 수요 주간 성장률: {facts['token_growth_pct']}%\n"
        f"- D램 가격 변화: {facts['dram_price_change_pct']}%\n"
        f"- 반도체 수출(월초 10일) 변화: {facts['semi_export_change_pct']}%\n"
        f"- 반도체 재고지수 변화: {facts['inventory_change_pct']}%\n"
        f"- TSMC 월매출 YoY: {facts['tsmc_yoy']}%\n"
    )
    text = fallback
    try:
        from providers import Role
        text = (await Role("news_summary", overrides=overrides).run(
            prompt, instructions="간결한 한국어. 불릿 없이 흐르는 문장.")).strip() or fallback
    except Exception:  # noqa: BLE001 — LLM 실패 시 규칙 문장
        text = fallback
    return {"text": text, "facts": facts}
