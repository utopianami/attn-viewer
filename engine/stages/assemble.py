"""ASSEMBLER 스테이지 — 통합 claim table (설계 §④, 순수 코드·LLM 없음).

1. 전 브랜치 claim 수집 (DA + RA + PRICE) → claim_key 정규화 → dedup(provenance 병합)
2. DA-DA 규칙: 이중 블라인드 불일치 = 채택 없음 + 둘 다 unverified + 집중검증 승격 / 일치 = corroborated
3. 충돌표: 같은 claim_key에 값이 다른 claim → 해소 우선순위 CALC > 1차소스 > 최신성 > DA
4. coverage: needed_evidence 슬롯 ↔ claim 코드 매칭 (커버리지 1차 판정 = 코드 — Claude 다운이어도 REFLECT 사유 유지)
5. calc_requests: plan.metrics → CALC 준비
6. richness 확정 재산출 (실수집량 기반 — 유명도 프록시 퇴화 방지)
7. fiscal late-binding, load_bearing 마킹
"""

from __future__ import annotations

from contracts import (
    AtomicClaim,
    CalcRequest,
    ClaimNorm,
    ClaimTable,
    Conflict,
    CoverageEntry,
    DaDisagreement,
    DaPacket,
    EnvelopeMeta,
    EvidenceRichness,
    PlanPacket,
    PriceMacroPacket,
    RaPacket,
    TypedFact,
    normalize_claim_key,
)

_REL_TOL = 0.01  # 값 차이 1% 이내 = 같은 값 (거짓 충돌 방지)

# metric 동의어 정규화 — 안 하면 "수익률" vs "기간수익률"이 딴 key가 되어 충돌 미탐 (rubric §3a)
_METRIC_SYNONYMS = {
    "기간수익률": "수익률", "기간 수익률": "수익률", "상승률": "수익률",
    "등락률": "수익률", "주가상승률": "수익률", "주가 상승률": "수익률", "ytd 수익률": "수익률",
    "주가": "현재가", "종가": "현재가", "현재 주가": "현재가",
}


def _norm_metric(m: str) -> str:
    key = " ".join(m.strip().lower().split())
    return _METRIC_SYNONYMS.get(key, key)


def _conflict_group_key(c) -> str:
    """충돌 그룹핑 키 — entity + 정규화 metric (period는 호환성 검사로 별도)."""
    ent = " ".join(c.norm.entity.strip().lower().split())
    return f"{ent}|{_norm_metric(c.norm.metric)}"


_PERIOD_BOUND_RE = None  # lazy — 아래에서 컴파일


def _periods_compatible(a: str, b: str) -> bool:
    """기간 호환 판정 — Q1 vs Q2는 딴 값이 정상(충돌 아님).

    한쪽이 빈 경우: 상대가 분기/연도 한정(2026Q1 등) 회계치면 비호환(거짓충돌 방지, codex #10),
    시세성(since/현재)이면 호환(와일드카드 — DA의 무기간 수익률 주장을 결정적 수익률과 대조).
    """
    global _PERIOD_BOUND_RE
    import re as _re
    if _PERIOD_BOUND_RE is None:
        _PERIOD_BOUND_RE = _re.compile(r"(q[1-4]|[1-4]분기|fy ?20\d\d|20\d\d년|반기|연간)")
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return True
    if a and b:
        return False
    filled = a or b
    return not _PERIOD_BOUND_RE.search(filled)


def _tokens(s: str) -> set[str]:
    return {t for t in s.lower().replace("/", " ").split() if len(t) > 1}


def _values_conflict(a: AtomicClaim, b: AtomicClaim) -> bool:
    va, vb = a.norm.value, b.norm.value
    if va is None or vb is None:
        return False
    if not _periods_compatible(a.norm.period, b.norm.period):
        return False  # 다른 기간의 다른 값 = 정상 (가짜충돌 방지)
    if va == vb:
        return False
    base = max(abs(va), abs(vb))
    return base > 0 and abs(va - vb) / base > _REL_TOL


def _source_rank(c: AtomicClaim) -> int:
    """충돌 해소 우선순위: CALC(0) > 1차소스(1) > 최신성/2차(2) > DA(3)."""
    if c.source == "calc" or c.source == "price":
        return 0
    if c.norm.source_type == "primary" or c.source in ("toss_company", "macro"):
        return 1
    if c.source in ("ra_x", "ra_web", "toss_trend"):
        return 2
    return 3  # da_gpt / da_fable


def _price_claims(pm: PriceMacroPacket) -> list[AtomicClaim]:
    """결정적 시세 수집 → price claim (CALC급 권위 — 야후 실측)."""
    out = []
    for f in pm.typed_facts:
        metric = "기간수익률" if f.id.startswith("ret:") else "현재가"
        entity = f.id.split(":", 1)[1] if ":" in f.id else f.id
        out.append(AtomicClaim(
            id=f"price:{f.id}", text=f"{f.label} = {f.value} {f.unit}",
            type="price", source="price", unit_id="q0", uncertainty="low",
            norm=ClaimNorm(entity=entity, metric=metric, period=f.period, unit=f.unit,
                           value=f.value, source_type="primary", as_of=""),
            ref=f.source,
        ))
    return out


def run_assemble(plan: PlanPacket, da: DaPacket, ra: RaPacket, pm: PriceMacroPacket,
                 extra_claims: list[AtomicClaim] | None = None,
                 round_: int = 0) -> ClaimTable:
    """통합 claim table 조립 — 순수 코드. extra_claims = CALC 결과·REFLECT 재조사분."""
    # ── 1. 수집 + 정규화 — 권위 높은 출처 먼저 (dedup 시 대표 claim이 권위 출처가 되도록)
    pool: list[AtomicClaim] = []
    for ua in da.unit_answers:
        pool.extend(ua.claims)
    pool.extend(ra.claims)
    pool.extend(_price_claims(pm))
    pool.extend(extra_claims or [])
    pool.sort(key=_source_rank)

    for c in pool:
        if (c.norm.entity or c.norm.metric) and not c.claim_key:
            c.claim_key = normalize_claim_key(c.norm.entity, c.norm.metric, c.norm.period)

    # ── 2. dedup — 같은 정규화 key + 값 동일(또는 값 없음) → provenance 병합
    claims: list[AtomicClaim] = []
    by_key: dict[str, list[AtomicClaim]] = {}
    seen_exact: dict[tuple, AtomicClaim] = {}
    for c in pool:
        has_key = bool(c.norm.entity or c.norm.metric)
        gkey = _conflict_group_key(c) if has_key else c.id
        exact = (gkey, c.norm.period.strip().lower(),
                 round(c.norm.value, 6) if c.norm.value is not None else None)
        if exact in seen_exact and has_key:
            kept = seen_exact[exact]
            if c.source not in kept.provenance:
                kept.provenance.append(c.source)
            continue
        seen_exact[exact] = c
        claims.append(c)
        if has_key:
            by_key.setdefault(gkey, []).append(c)

    # ── 3. DA-DA 규칙 (q0 이중 블라인드)
    disagreements: list[DaDisagreement] = []
    for key, group in by_key.items():
        gpt = [c for c in group if c.source == "da_gpt" and c.unit_id == "q0"]
        fable = [c for c in group if c.source == "da_fable" and c.unit_id == "q0"]
        for g in gpt:
            for f in fable:
                if _values_conflict(g, f):
                    disagreements.append(DaDisagreement(
                        claim_key=key, gpt_claim_id=g.id, fable_claim_id=f.id))
                    g.uncertainty = f.uncertainty = "high"
                    g.load_bearing = f.load_bearing = True  # 집중 검증 승격
                elif g.norm.value is not None and f.norm.value is not None:
                    # 일치 = corroborated (provenance에 상호 기록만 — 채택 아님)
                    if f.source not in g.provenance:
                        g.provenance.append(f.source)

    # ── 4. 충돌표 + 해소
    conflicts: list[Conflict] = []
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        conflicting = []
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if _values_conflict(a, b):
                    conflicting = group
                    break
            if conflicting:
                break
        if not conflicting:
            continue
        ranked = sorted(conflicting, key=_source_rank)
        best_rank = _source_rank(ranked[0])
        if best_rank == 0:
            resolution = "calc"
        elif best_rank == 1:
            resolution = "primary"
        else:
            # 최신성: as_of 있는 것 중 가장 늦은 것
            dated = [c for c in conflicting if c.norm.as_of]
            if dated:
                ranked = sorted(dated, key=lambda c: c.norm.as_of, reverse=True)
                resolution = "freshness"
            else:
                resolution = "unresolved"  # 병기 대상
        conflicts.append(Conflict(
            claim_key=key, claim_ids=[c.id for c in conflicting],
            resolution=resolution,  # type: ignore[arg-type]
            chosen_claim_id=ranked[0].id if resolution != "unresolved" else None,
        ))
        # 패배 claim 강등 (해소된 경우)
        if resolution != "unresolved":
            for c in conflicting:
                if c.id != ranked[0].id:
                    c.uncertainty = "high"

    # ── 5. coverage — needed_evidence 슬롯 코드 매칭
    coverage: list[CoverageEntry] = []
    for slot in plan.needed_evidence:
        if slot.obtainability == "unavailable":
            coverage.append(CoverageEntry(slot=slot, status="unobtainable"))
            continue
        slot_toks = _tokens(f"{slot.entity} {slot.metric}")
        metric_toks = _tokens(slot.metric)
        matched = []
        for c in claims:
            c_toks = _tokens(f"{c.norm.entity} {c.norm.metric} {c.text[:80]}")
            overlap = slot_toks & c_toks
            # metric 토큰 최소 1개 필수 — entity만 겹쳐서 covered 되는 오탐 방지 (codex #12)
            if len(overlap) >= min(2, len(slot_toks)) and (not metric_toks or metric_toks & c_toks):
                matched.append(c.id)
        if matched:
            coverage.append(CoverageEntry(slot=slot, status="covered", matched_claim_ids=matched[:6]))
        elif not slot.required:
            coverage.append(CoverageEntry(slot=slot, status="ambiguous"))
        else:
            coverage.append(CoverageEntry(slot=slot, status="uncovered"))

    # ── 6. load_bearing 마킹 — required 슬롯에 매칭됐거나 q0 numeric
    covered_ids = {cid for ce in coverage if ce.slot.required for cid in ce.matched_claim_ids}
    for c in claims:
        if c.id in covered_ids or (c.unit_id == "q0" and c.type in ("numeric", "price")):
            c.load_bearing = True

    # ── 6b. 토스 재무 → typed_facts 승격 (P3-2) — G2 앵커·CALC 입력 자격
    typed_facts = list(pm.typed_facts)
    code_names = {t.code: t.name for t in plan.tickers if t.code}
    for code, bundle in (ra.toss_company or {}).items():
        per = bundle.get("info_per") if isinstance(bundle, dict) else None
        if isinstance(per, (int, float)) and not isinstance(per, bool) and per > 0:
            typed_facts.append(TypedFact(
                id=f"toss:{code}:per", value=float(per), unit="ratio",
                label=f"{code_names.get(code, code)} PER", source=f"toss:{code}"))

    # ── 7. calc_requests — plan.metrics 기반 (typed_facts 있어야 실행 가능)
    calc_requests = []
    if typed_facts:
        for m in plan.metrics[:4]:
            calc_requests.append(CalcRequest(
                metric=m, typed_fact_ids=[f.id for f in typed_facts]))

    # ── 8. richness 확정 재산출 (실수집 기반)
    n_claims = len(claims)
    n_sources = len({c.source for c in claims})
    n_news = sum(len(v) for v in ra.x_search.values()) + sum(len(v) for v in ra.web_knowledge.values())
    if n_claims >= 12 and n_sources >= 4 and n_news >= 6:
        grade = "A"
    elif n_claims >= 5 and n_sources >= 2:
        grade = "B"
    else:
        grade = "C"
    richness = EvidenceRichness(grade=grade, prelim=False,  # type: ignore[arg-type]
                                reason=f"claims={n_claims} sources={n_sources} news={n_news}")

    # ── 9. fiscal late-binding (v1 단순화: calendar 확정치 있으면 resolved)
    fiscal = []
    for fp in plan.fiscal_periods:
        if not fp.resolved and fp.calendar_period:
            fp = fp.model_copy(update={"resolved": True, "basis": "calendar"})
        fiscal.append(fp)

    return ClaimTable(
        meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref()),
        claims=claims,
        conflicts=conflicts,
        da_disagreements=disagreements,
        coverage=coverage,
        calc_requests=calc_requests,
        typed_facts=typed_facts,
        richness=richness,
        fiscal_periods=fiscal,
        global_context={"macro": pm.macro},
    )
