"""종합 브리핑 — 수집 지표를 인과 사슬로 읽어 3~4줄 요약 (P2, 2026-07-07).

단순 나열이 아니라 "AI 수요 → capex → 메모리"를 엮는 서사.
지표에서 팩트를 규칙으로 추출(재현 가능) → sonnet이 문장화. LLM 실패 시 규칙 문장 폴백.
"""
from __future__ import annotations

import re

from sector.cycle import compute as cycle_compute
from sector.store import SectorStore

# ── HBM Tightness — 현물시장이 없어 뉴스 카드 키워드로 합성 (브리프 §파생) ────
_HBM_TIGHT_PAT = re.compile(
    r"sold.?out|완판|공급\s?계약|장기\s?계약|고객\s?인증|qualification|cowos|병목|"
    r"capacity constrained|타이트|shortage|공급\s?부족|물량\s?부족", re.I)
_HBM_LOOSE_PAT = re.compile(
    r"증설|캐파\s?(확대|확장|증가)|capacity (expansion|increase|ramp)|공급\s?확대|"
    r"과잉|oversupply|시장\s?진입|양산\s?돌입", re.I)


def hbm_tightness(store: SectorStore, quanta_mom: float | None = None,
                  days: int = 30) -> dict:
    """HBM 타이트 게이지: tight/easing/mixed/nodata.

    최근 카드 중 HBM 관련만 — 타이트 키워드(완판·계약·인증·CoWoS 병목) vs
    완화 키워드(증설·과잉·신규 진입)를 임팩트(magnitude) 가중 합산.
    AI 서버 프록시(콴타 월매출) 둔화는 완화 쪽 신호.
    """
    tight = loose = 0.0
    ev_tight: list[str] = []
    ev_loose: list[str] = []
    for c in store.read_cards(days=days, limit=500):
        txt = f"{c.title} {c.raw_quote[:300]} {c.interpreted_signal}"
        if c.memory_segment != "hbm" and "HBM" not in txt.upper():
            continue
        if _HBM_LOOSE_PAT.search(txt):
            loose += c.magnitude
            ev_loose.append(c.title[:60])
        elif _HBM_TIGHT_PAT.search(txt):
            tight += c.magnitude
            ev_tight.append(c.title[:60])
    signals = len(ev_tight) + len(ev_loose)
    if quanta_mom is not None and quanta_mom < -1:
        loose += 2.0
        ev_loose.append(f"AI서버 조립(콴타) 월매출 {quanta_mom:+.1f}% — 수요 프록시 둔화")
        signals += 1
    if signals == 0:
        level, label = "nodata", "데이터 부족"
    elif tight >= loose * 1.5 and tight > 0:
        level, label = "tight", "타이트"
    elif loose >= tight * 1.5 and loose > 0:
        level, label = "easing", "완화 중"
    else:
        level, label = "mixed", "혼재"
    return {"level": level, "label": label, "tight_score": tight, "loose_score": loose,
            "evidence_tight": ev_tight[:5], "evidence_loose": ev_loose[:5]}


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
    # 대만 월매출 — YoY는 붐에서 항상 높아 참고용, 판단은 MoM(모멘텀) (yvon 원칙)
    tw_rows = store.read_metric("tw_monthly_revenue", last_n=60)
    def _tw(nm, key):
        r = [o.meta.get(key) for o in tw_rows
             if (o.meta or {}).get("name") == nm and o.meta.get(key) is not None]
        return round(r[-1], 1) if r else None
    tsmc = [o.meta.get("yoy") for o in tw_rows
            if (o.meta or {}).get("name") == "TSMC" and o.meta.get("yoy") is not None]
    # 빅테크 capex — 4사 모두 보고한 분기만 합산 (결산 시차로 일부만 나온 분기 제외)
    cap_rows = store.read_metric("hyperscaler_capex", last_n=200)
    by_q: dict[str, dict] = {}
    for o in cap_rows:
        by_q.setdefault(o.ts, {})[o.meta.get("token")] = o.value
    full = sorted(q for q, d in by_q.items() if len(d) >= 4)
    capex_last = round(sum(by_q[full[-1]].values()), 1) if full else None
    capex_qoq = None
    if len(full) >= 2:
        a2, b2 = sum(by_q[full[-2]].values()), sum(by_q[full[-1]].values())
        if a2:
            capex_qoq = round((b2 / a2 - 1) * 100, 1)

    return {
        "cycle": cyc,
        "token_growth_pct": tok,
        "dram_price_change_pct": _pct_change(dram),
        "dram_series": dram_item.split("|")[-1] if dram_item else None,
        "semi_export_change_pct": _pct_change(exp),
        "inventory_change_pct": _pct_change(inv),
        "tsmc_yoy": round(tsmc[-1], 1) if tsmc else None,
        "tsmc_mom": _tw("TSMC", "mom"),
        "quanta_mom": _tw("Quanta", "mom"),
        "capex_total_b": capex_last, "capex_qoq_pct": capex_qoq,
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


def _band(v: float | None, width: float) -> int | None:
    """±width 데드밴드 — 노이즈에 방향 경보 남발 방지. None=데이터 없음."""
    if v is None:
        return None
    if v > width:
        return 1
    if v < -width:
        return -1
    return 0


def build_assessment(facts: dict, store: SectorStore, stock30: dict | None = None) -> dict:
    """규칙 기반 산업 판단 (브리프 2026-07-08 스펙) — 재현 가능, LLM 아님.

    반환: headline / good·bad·unknown / quadrants(수요·가격·재고·공급) /
          chain(4단계) + break_point(끊긴 곳).
    """
    cyc = facts["cycle"]
    exp, dram, inv = facts["semi_export_change_pct"], facts["dram_price_change_pct"], facts["inventory_change_pct"]
    tok, ts_mom, qt_mom = facts["token_growth_pct"], facts["tsmc_mom"], facts["quanta_mom"]
    dram_series = facts.get("dram_series") or "D램"

    # ── 4분면 (상태: good/bad/mixed/nodata) ────────────────────────────────
    def quad(key, name, val, width, metric, fmt, good_c, bad_c, mixed_c):
        b = _band(val, width)
        if val is None:
            return {"key": key, "name": name, "status": "nodata", "metric": metric,
                    "value_label": "—", "comment": ""}
        status = {1: "good", -1: "bad", 0: "mixed"}[b]
        return {"key": key, "name": name, "status": status, "metric": metric,
                "value_label": fmt, "comment": {1: good_c, -1: bad_c, 0: mixed_c}[b]}

    q_demand = quad("demand", "수요", exp, 3, "반도체 수출 (월초 10일 페이스)",
                    f"전월 대비 {exp:+.1f}%" if exp is not None else "—",
                    "수출 페이스 개선 — 삼전·하이닉스 매출 선행 신호 양호.",
                    "수출 페이스 둔화 — 실수요 약화 신호.",
                    "수출 페이스 보합 — 방향 대기.")
    q_price = quad("price", "가격", dram, 2, f"D램 가격 ({dram_series}, $/GB)",
                   f"한 달 새 {dram:+.1f}%" if dram is not None else "—",
                   "메모리 가격 상승 — 마진 개선 방향.",
                   "메모리 가격 하락 — 마진 압박.",
                   "가격 보합.")
    inv_signal = -inv if inv is not None else None   # 재고 감소가 좋음
    q_inv = quad("inventory", "재고", inv_signal, 1, "반도체 재고지수 (통계청)",
                 f"전월 대비 {inv:+.1f}%" if inv is not None else "—",
                 "재고 감소 — 공급과잉 압력 완화.",
                 "재고가 빠르게 쌓이는 중 — 공급과잉 경계.",
                 f"재고 소폭 {'증가' if (inv or 0) > 0 else '변동'} — 위험 수준 아니나 방향 주시.")
    # 공급 = 과잉 경보 게이지 (score 요소가 아니라 별도 경보 — 2026-07-08 합의)
    try:
        from sector.cycle import supply_risk
        srisk = supply_risk(store)
    except Exception:  # noqa: BLE001
        srisk = {"level": "nodata", "signals": [], "available": 0, "fired": 0}
    if srisk["level"] == "nodata":
        q_supply = {"key": "supply", "name": "공급", "status": "nodata",
                    "metric": "3사 capex · 장비 매출 · 재고 (과잉 경보)",
                    "value_label": "데이터 축적 중",
                    "comment": "업사이클 판단의 가장 큰 공백 — 과열 여부 판단 불가."}
    else:
        cap_sig = next((s for s in srisk["signals"] if s["key"] == "memory_capex"), {})
        lv = srisk["level"]
        status = {"low": "good", "rising": "mixed", "high": "bad"}[lv]
        label = {"low": "과잉 위험 낮음", "rising": "과잉 위험 상승", "high": "과잉 위험 높음"}[lv]
        if cap_sig.get("pct") is not None:
            label += f" · 3사 capex {cap_sig['pct']:+.1f}% QoQ"
        q_supply = {"key": "supply", "name": "공급", "status": status,
                    "metric": "과잉 경보 (3사 capex · 장비 매출 · 재고 조합)",
                    "value_label": label,
                    "comment": {"low": "증설 절제 — 업사이클의 질 양호.",
                                "rising": "증설 신호 1개 발동 — 과잉 타이머 주의.",
                                "high": "증설 신호 중첩 — 2~4분기 뒤 공급과잉 위험."}[lv]}
    quadrants = [q_demand, q_price, q_inv, q_supply]

    # ── 사슬 4단계 + 끊긴 곳 ────────────────────────────────────────────────
    server_mom = None
    parts = [v for v in (ts_mom, qt_mom) if v is not None]
    if parts:
        server_mom = round(sum(parts) / len(parts), 1)
    stock_pct = (stock30 or {}).get("avg30")
    chain = [
        {"key": "ai", "name": "AI 수요", "pct": tok, "band": _band(tok, 1),
         "label": "토큰 사용량 주간"},
        {"key": "server", "name": "서버·투자", "pct": server_mom, "band": _band(server_mom, 1),
         "label": "TSMC·콴타 월매출 전월비",
         "sub": (f"빅테크 4사 capex {facts['capex_total_b']:.0f}B/분기 ({facts['capex_qoq_pct']:+.1f}% QoQ)"
                 if facts.get("capex_total_b") is not None and facts.get("capex_qoq_pct") is not None else None)},
        {"key": "physical", "name": "메모리 실물", "pct": exp, "band": _band(exp, 3),
         "label": "반도체 수출 월간"},
        {"key": "stock", "name": "주가", "pct": stock_pct, "band": _band(stock_pct, 3),
         "label": "삼전·하이닉스 30일"},
    ]
    bands = {c["key"]: c["band"] for c in chain}
    break_point = None
    if bands["server"] == -1 and bands["physical"] == 1:
        break_point = ("서버·투자 단계 약함 — AI서버 조립(콴타) 모멘텀이 꺾였는데 실물 지표는 아직 강함. "
                       "시차인지 둔화의 시작인지, 다음 달 대만 월매출이 판가름.")
    elif bands["ai"] == -1 and (bands["server"] or 0) >= 0:
        break_point = "AI 수요 단계 둔화 — 상류가 꺾였고 아직 하류에 반영 전. 1~2분기 시차 주의."
    elif bands["physical"] == -1 and bands["stock"] == 1:
        break_point = "실물 약화에도 주가 강세 — 선반영 과열 가능성."
    elif bands["stock"] == -1 and bands["physical"] == 1:
        break_point = "실물 강세인데 주가 조정 — 과민반응이거나 시장이 먼저 아는 것."

    # ── 파생 인사이트 — Cycle Quality · Market Divergence (브리프 §파생) ────
    qs = {q["key"]: q["status"] for q in quadrants}
    if (qs["demand"] == "good" and qs["price"] == "good"
            and qs["inventory"] == "good" and qs["supply"] != "bad"):
        cycle_quality = {"grade": "strong", "label": "강함",
                         "reason": "수요·가격·재고 동반 개선 + 증설 절제 신호."}
    elif ((qs["demand"] == "good" or qs["price"] == "good")
          and (qs["inventory"] == "bad" or qs["supply"] == "bad")):
        cycle_quality = {"grade": "fragile", "label": "취약",
                         "reason": "수요·가격은 좋지만 재고/공급이 반대 방향 — 반등의 질 의심."}
    else:
        cycle_quality = {"grade": "mixed", "label": "혼재",
                         "reason": "4분면 신호가 엇갈림."}

    pb, sb = bands["physical"], bands["stock"]
    if pb is None or sb is None:
        market_divergence = {"state": "nodata", "label": "데이터 부족"}
    elif pb >= 1 and sb <= -1:
        market_divergence = {"state": "stock_lagging", "label": "주가 과민 (또는 시장이 먼저 아는 것)"}
    elif pb <= -1 and sb >= 1:
        market_divergence = {"state": "stock_ahead", "label": "주가 선반영 — 과열 주의"}
    else:
        market_divergence = {"state": "aligned", "label": "지표와 일치"}

    # ── 좋은/나쁜/모르는 것 ─────────────────────────────────────────────────
    good, bad = [], []
    if _band(exp, 3) == 1:
        good.append(f"반도체 수출 {exp:+.1f}% (월초 페이스)")
    elif _band(exp, 3) == -1:
        bad.append(f"반도체 수출 {exp:+.1f}%")
    if _band(dram, 2) == 1:
        good.append(f"D램 가격 {dram:+.1f}% ({dram_series})")
    elif _band(dram, 2) == -1:
        bad.append(f"D램 가격 {dram:+.1f}%")
    if inv is not None:
        (good if inv < -1 else bad if inv > 1 else bad).append(
            f"재고지수 {inv:+.1f}%" + ("" if abs(inv) > 1 else " (소폭 증가 — 주시)"))
    if qt_mom is not None and qt_mom < -1:
        bad.append(f"AI서버 조립(콴타) 월매출 {qt_mom:+.1f}%")
    if tok is not None and _band(tok, 1) == 1:
        good.append(f"AI 토큰 수요 주간 {tok:+.1f}%")
    cq = facts.get("capex_qoq_pct")
    if cq is not None and cq > 3:
        good.append(f"빅테크 capex {cq:+.1f}% (분기)")
    elif cq is not None and cq < -3:
        bad.append(f"빅테크 capex {cq:+.1f}% (분기)")
    # 최근 대형 악재 뉴스 1건
    try:
        neg_cards = [c for c in store.read_cards(days=7)
                     if c.direction == "neg" and c.magnitude >= 2]
        if neg_cards:
            bad.append(f"악재 뉴스: {neg_cards[0].title[:36]}…")
    except Exception:  # noqa: BLE001
        pass
    unknown = ["HBM 계약가격·출하량 — 유료 트래커 영역"]
    if srisk["level"] == "nodata":
        unknown.insert(0, "공급 측 (3사 capex · 장비 매출) — 데이터 축적 중")
    else:
        unknown.append("HBM 증설 캐파 정량 — 뉴스 기반만 (capex·장비 매출로 프록시)")
    try:
        st = store.read_status()
        if (st.get("ecos") or {}).get("status") == "missing_key":
            unknown.append("D램 공식 수출물가지수 (한국은행 키 미발급 — 소매가로 대체 중)")
    except Exception:  # noqa: BLE001
        pass

    # ── 결론 한 줄 ──────────────────────────────────────────────────────────
    state_ko = {"up": "업사이클", "down": "다운사이클", "transition": "전환 구간",
                "insufficient": "판정 보류(데이터 축적 중)"}.get(cyc.get("state"), "판정 불가")
    head = state_ko
    if good:
        head += " — " + " · ".join(g.split(" (")[0] for g in good[:2]) + " 강세"
    if break_point:
        head += ". 단, " + break_point.split(" — ")[0]
    elif srisk["level"] == "high":
        head += ". 단, 공급 증설 경보"
    elif q_supply["status"] == "nodata":
        head += ". 공급 데이터 공백은 유의"

    try:
        hbm = hbm_tightness(store, quanta_mom=qt_mom)
    except Exception:  # noqa: BLE001
        hbm = {"level": "nodata", "label": "데이터 부족",
               "tight_score": 0, "loose_score": 0,
               "evidence_tight": [], "evidence_loose": []}

    return {"headline": head, "state": cyc.get("state"), "score": cyc.get("score"),
            "good": good, "bad": bad, "unknown": unknown,
            "quadrants": quadrants, "chain": chain, "break_point": break_point,
            "supply_risk": srisk, "cycle_quality": cycle_quality,
            "market_divergence": market_divergence, "hbm_tightness": hbm}


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
    # 주가 30일 수익률 (사슬 4단계·괴리 판정용) — 실패해도 판단은 진행
    stock30 = None
    try:
        from sector.prices import price_series
        pr = await price_series(days=35)
        rets = []
        for sr in pr.get("series", []):
            if sr.get("token") in ("005930.KS", "000660.KS") and sr.get("points"):
                pts = sr["points"]
                if len(pts) >= 2 and pts[0][1]:
                    rets.append((pts[-1][1] / pts[0][1] - 1) * 100)
        if rets:
            stock30 = {"avg30": round(sum(rets) / len(rets), 1)}
    except Exception:  # noqa: BLE001
        stock30 = None
    assessment = build_assessment(facts, store, stock30)
    text = fallback
    try:
        from providers import Role
        text = (await Role("news_summary", overrides=overrides).run(
            prompt, instructions="간결한 한국어. 불릿 없이 흐르는 문장.")).strip() or fallback
    except Exception:  # noqa: BLE001 — LLM 실패 시 규칙 문장
        text = fallback
    return {"text": text, "facts": facts, "assessment": assessment}
