"""VERIFIER 스테이지 — 하드 게이트 G1~G4 (설계 §⑥, verifier_rubric).

G2 숫자·G3 as-of·G4 지시어 = 순수 코드 게이트.
G1 근거성만 LLM 구조화 판정 — 선별(load-bearing·2차출처·tier3·DA-DA 불일치)만, 전건 강제 금지.
교차 채점: da_fable 출처 claim은 GPT가, 나머지는 Fable이 판정 (자기 채점 방지).
enforce_g2() 코드가 LLM verdict 뒤에도 최종 강제 (불변식 2).

REFLECT 발동 사유 → retry_directives: 핵심 주장 게이트 실패 / 미해소 충돌 / 커버리지 구멍.
재조사는 신규 확장 쿼리 강제 (seen_queries 캐리).
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, ConfigDict, Field

from stages.query_sim import any_similar
from contracts import (
    AtomicClaim,
    CalcResult,
    ClaimTable,
    ClaimVerdict,
    EnvelopeMeta,
    GateResult,
    PlanPacket,
    RaPacket,
    RetryDirective,
    VerdictPacket,
)
from providers import Role

# G4 — 직접 매수/매도/보유 지시 패턴 (tier 3+)
_DIRECTIVE_RE = re.compile(
    r"(매수하세요|매도하세요|사세요|파세요|팔아라|사라\b|지금 사|지금 팔|"
    r"전량 매도|전량 매수|풀매수|무조건 (사|팔))"
)
_G1_MAX_CLAIMS = 48   # 라운드당 신규 판정 상한 (비용 가드) — 초과분만 미검증 유지
_G1_SHARD = 10        # 심판 콜당 claim 수 (설계 "G1 유닛 샤딩" — 캡 병목 해소, 병렬)
_REL_TOL = 0.05  # G2: DA 숫자가 결정적 값과 5% 이내면 지지로 인정

# P2-2 (F3, FinGround): claim 타입 → 담당 게이트 라우팅.
# G2는 DA(모델 기억) 출처 한정 — 뉴스·토스 숫자는 출처가 근거라 G1 담당 (기존 규칙 유지).
# comparison: 스키마가 단일 value라 양변 재검산은 불가 — 값은 G2, 관계 서술은 G1이 판정.
# G1_STRICT(regulation): 출처 ref 없으면 LLM 불경유 즉시 unverified.
_ROUTE: dict[str, tuple[str, ...]] = {
    "numeric": ("G2",),          "price": ("G2",),
    "comparison": ("G2", "G1"),  "temporal": ("G3", "G1"),
    "regulation": ("G1_STRICT",),
    "fact": ("G1",), "definition": (), "context": (), "risk": (),
}


class _SO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _V(_SO):
    claim_id: str
    verdict: str = "uncertain"   # supported | unsupported | uncertain
    note: str = ""


class _Verdicts(_SO):
    verdicts: list[_V] = Field(default_factory=list)


_G1_INSTR = """너는 금융 QA의 근거성 검증(G1) 단계다. 각 claim이 아래 [수집 증거]로 지지되는지 판정하라.
- supported: 증거가 claim을 직접 지지
- unsupported: 증거가 claim과 모순되거나, 사실·수치인데 증거가 전혀 없음
- uncertain: 증거가 부분적이거나 애매함
증거에 없다고 전부 unsupported가 아니다 — 도메인 상식·정의는 지지로 봐도 된다.
단, 구체적 수치·사건·시세 claim은 증거 없이 supported 금지. note에 한 줄 근거."""


# 단위 3그룹: pct(%·pp·bps) / mult(배·ratio — PER·PBR류) / abs(그 외)
# "배"↔"ratio" 호환 없으면 toss 승격 PER 앵커가 DA "23배" claim과 대조 불발 (2차 리뷰 #2)
_UNIT_GROUP = {"percent": "pct", "%": "pct", "pp": "pct", "bps": "pct", "퍼센트": "pct",
               "ratio": "mult", "배": "mult", "x": "mult"}
# 한국어 배수 단위 → 원화 스케일 (claim value가 "4411 억원"처럼 단위 상대값일 때 정규화)
_KRW_SCALE = {"조": 1e12, "조원": 1e12, "억": 1e8, "억원": 1e8, "만원": 1e4, "krw": 1.0, "원": 1.0}


def _scaled(value: float, unit: str) -> float:
    return value * _KRW_SCALE.get(unit.strip().lower(), 1.0)


def _numeric_anchors(table: ClaimTable, calc_results: list[CalcResult]) -> list[tuple[float, str]]:
    """G2 대조 기준 — 결정적 출처의 (값, 단위) (calc 결과 + typed_facts + price claim)."""
    vals: list[tuple[float, str]] = []
    for r in calc_results:
        if r.ok and r.result and r.result.get("result"):
            rv = r.result["result"]
            v = rv.get("value")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append((float(v), rv.get("unit", "")))
    vals.extend((f.value, f.unit) for f in table.typed_facts)
    for c in table.claims:
        if c.source in ("calc", "price") and c.norm.value is not None:
            vals.append((c.norm.value, c.norm.unit))
    return vals


def _unit_compatible(a: str, b: str) -> bool:
    """단위 호환 — 둘 다 있으면 pct/mult/abs 그룹으로 나눠 대조 (전역 float 우연 일치 차단)."""
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return True
    return _UNIT_GROUP.get(a, "abs") == _UNIT_GROUP.get(b, "abs")


def _g2_supported(value: float, unit: str, anchors: list[tuple[float, str]]) -> bool:
    v = _scaled(value, unit)
    for a, au in anchors:
        if not _unit_compatible(unit, au):
            continue
        av = _scaled(a, au)
        base = max(abs(av), abs(v))
        if base == 0 or abs(av - v) / base <= _REL_TOL:
            return True
    return False


def _render_evidence(plan: PlanPacket, ra: RaPacket, table: ClaimTable,
                     calc_results: list[CalcResult]) -> str:
    parts = [f"[기준시점] {plan.knowledge_cutoff}"]
    if ra.x_narrative:
        parts.append("[실시간 검색 서사]\n" + ra.x_narrative[:3000])
    # curation 통과분만 — 노이즈 기사가 G1 판정을 흐리지 않게 (P1-2)
    # 보완·재조사 유닛 우선 — 라운드를 태워 가져온 신규 증거가 쿼터에 밀려
    # 자기 claim 판정에 안 쓰이는 낭비 방지 (리뷰 #2)
    pools = ra.curated_items()
    ordered = sorted(pools, key=lambda uid: 0 if uid.startswith(("supplement_", "reflect_")) else 1)
    news, bodies = [], []
    for uid in ordered:
        for n in pools[uid][:5]:
            news.append(f"- {n.title} ({n.published_at or '?'})")
            if n.content and len(bodies) < 8:
                bodies.append(f"### {n.title}\n{n.content[:700]}")
    if news:
        parts.append("[뉴스]\n" + "\n".join(news[:24]))
    if bodies:  # 본문 발췌 (P1-1) — 헤드라인만으론 수치·맥락 판정 불가
        parts.append("[뉴스 본문 발췌]\n" + "\n\n".join(bodies))
    if ra.toss_company:
        parts.append("[종목 데이터] " + ", ".join(ra.toss_company.keys()))
    det = [f"- {f.label}: {f.value} {f.unit}" for f in table.typed_facts]
    for r in calc_results:
        if r.ok and r.result and r.result.get("result"):
            rv = r.result["result"]
            det.append(f"- [계산] {r.request.metric} = {rv['value']} {rv['unit']}")
    if det:
        parts.append("[결정적 수치 (시세·계산)]\n" + "\n".join(det))
    return "\n\n".join(parts)


async def _g1_judge(role_name: str, judged_by: str, claims: list[AtomicClaim],
                    evidence: str, overrides: dict | None) -> dict[str, tuple[str, str, str]]:
    """G1 LLM 판정 1콜 (배치). 반환: claim_id → (verdict, note, judged_by)."""
    if not claims:
        return {}
    view = "\n".join(f"- id={c.id} [{c.type}] {c.text}" for c in claims)
    role = Role(role_name, overrides)
    try:
        # 증거는 cache_prefix로 — 같은 run의 샤드들이 공유 (anthropic 캐시 90% 할인)
        val: _Verdicts = await role.run(
            f"[판정할 claim 목록]\n{view}", _G1_INSTR,
            response_format=_Verdicts, effort="medium", cache_prefix=evidence,
        )
    except Exception:
        return {c.id: ("uncertain", "judge unavailable", "code") for c in claims}
    out = {}
    valid = {"supported", "unsupported", "uncertain"}
    for v in val.verdicts:
        out[v.claim_id] = (v.verdict if v.verdict in valid else "uncertain", v.note, judged_by)
    for c in claims:
        out.setdefault(c.id, ("uncertain", "no verdict returned", judged_by))
    return out


async def run_verify(plan: PlanPacket, table: ClaimTable, ra: RaPacket,
                     calc_results: list[CalcResult], *,
                     round_: int = 0, seen_queries: set[str] | None = None,
                     g1_cache: dict[str, tuple[str, str, str]] | None = None,
                     replan_available: bool = True,
                     overrides: dict | None = None) -> VerdictPacket:
    """G1~G4 집행 + REFLECT 발동 판단.

    g1_cache: 라운드 간 G1 판정 캐리오버 (claim_id → (verdict, note, judged_by)).
    supported만 재사용 — 실패/불확실 claim은 새 증거로 재판정 기회를 가진다.
    없으면(단독 호출) 매번 전체 판정 — 캡 초과 강등이 이미 검증된 claim을 덮치는
    구조적 결함의 해소 (2026-07-03 E2E: "판정 캡 초과" ×11 + verified 37→32 하락).
    """
    seen_queries = seen_queries or set()
    g1_cache = g1_cache if g1_cache is not None else {}
    tier = plan.tier
    anchors = _numeric_anchors(table, calc_results)
    disagreement_ids = {d.gpt_claim_id for d in table.da_disagreements} | \
                       {d.fable_claim_id for d in table.da_disagreements}

    # ── G1 선별 — _ROUTE 기반 + load-bearing/2차출처/DA-DA 불일치 보정 (P2-2)
    def _g1_candidate(c: AtomicClaim) -> bool:
        if c.derived or c.source in ("calc", "price", "macro"):
            return False       # derived는 증거 자격 없음(별도), 결정적 출처는 G2가 담당
        route = _ROUTE.get(c.type, ("G1",))
        if "G1_STRICT" in route:
            return bool(c.ref)  # ref 없는 regulation은 LLM 불경유 즉시 unverified (게이트 집계에서)
        if "G1" not in route:
            if c.type in ("numeric", "price"):
                # 2차출처 증거 숫자는 G2가 안 보므로(G2는 DA 전용) G1이 근거 대조
                return (c.load_bearing or c.id in disagreement_ids
                        or c.norm.source_type == "secondary")
            # definition/context/risk: DA(모델지식)는 허용 — 비후보.
            # 단 2차출처 추출물은 증거 유래라 G1 판정 필수 — 아니면 뉴스발 사건 서술이
            # 무검증 verified로 통과 (2차 리뷰 #1: 신뢰성 구멍)
            return c.norm.source_type == "secondary"
        return (c.load_bearing or c.id in disagreement_ids
                or c.norm.source_type == "secondary" or tier >= 3)

    g1_candidates = sorted([c for c in table.claims if _g1_candidate(c)],
                           key=lambda c: (not c.load_bearing, c.id))
    # 캐리오버 — 이전 라운드 supported는 재판정 없이 재사용 (캡·비용은 신규분에만)
    cached_pass = {cid for cid, v in g1_cache.items() if v[0] == "supported"}
    to_judge = [c for c in g1_candidates if c.id not in cached_pass]
    g1_pool = to_judge[:_G1_MAX_CLAIMS]
    # 캡 초과분 — 판정 없이 verified로 새면 claim flood로 게이트 우회 가능 (codex #5)
    g1_overflow_ids = {c.id for c in to_judge[_G1_MAX_CLAIMS:]}
    evidence = _render_evidence(plan, ra, table, calc_results)

    # 교차 채점 라우팅 — da_fable → GPT 심판, 나머지 → Fable 심판. 샤드 단위 병렬.
    fable_made = [c for c in g1_pool if c.source == "da_fable"]
    others = [c for c in g1_pool if c.source != "da_fable"]

    def _shards(pool: list[AtomicClaim]) -> list[list[AtomicClaim]]:
        return [pool[i:i + _G1_SHARD] for i in range(0, len(pool), _G1_SHARD)]

    g1_map: dict[str, tuple[str, str, str]] = {
        c.id: g1_cache[c.id] for c in g1_candidates if c.id in cached_pass}
    # anthropic 샤드가 2개 이상이면 첫 샤드로 캐시를 예열(write) 후 나머지 병렬(read) —
    # 전부 동시 발사하면 캐시 생성 전에 도착해 전원 miss (P: 캐시는 첫 응답 시작 후 유효)
    fable_shards = _shards(others)
    if len(fable_shards) > 1:
        g1_map.update(await _g1_judge("verifier", "fable", fable_shards[0], evidence, overrides))
        fable_shards = fable_shards[1:]
    judge_tasks = [_g1_judge("verifier", "fable", chunk, evidence, overrides)
                   for chunk in fable_shards]
    judge_tasks += [_g1_judge("verifier_cross", "gpt", chunk, evidence, overrides)
                    for chunk in _shards(fable_made)]
    for res in await asyncio.gather(*judge_tasks):
        g1_map.update(res)
    g1_cache.update(g1_map)  # 다음 라운드 캐리오버 (호출자가 dict를 관통시킴)

    # ── claim별 게이트 집계
    verdicts: list[ClaimVerdict] = []
    load_bearing_failed: list[AtomicClaim] = []
    for c in table.claims:
        gates = GateResult()
        notes: list[str] = []
        judged_by = "code"

        # G1_STRICT (P2-2) — 규제·공시 인용인데 출처 좌표가 없으면 LLM 불경유 즉시 미검증
        if c.type == "regulation" and not c.ref and not c.derived \
                and c.source not in ("calc", "price", "macro"):
            gates.g1 = "fail"
            notes.append("G1:규제·공시 인용인데 출처 없음")
        # G1
        if c.id in g1_map:
            v, note, judged_by = g1_map[c.id]
            gates.g1 = "pass" if v == "supported" else "fail"
            if note:
                notes.append(f"G1:{note}")
        # G2 — enforce_g2(): tier2+ '모델 기억' 숫자만 결정적 값 대조.
        # 뉴스·토스 출처 숫자는 출처 자체가 근거(2차) — G1(근거성) 담당이지 G2 대상 아님
        # (아니면 뉴스가 보도한 실적 수치가 전부 "미검증"으로 강등되는 오탐 — 2026-07-03 사용자 리포트)
        # comparison은 value 있는 것만 G2 (값 대조) — 정성 비교("A가 B보다 크다")는 G1 담당
        if tier >= 2 and (c.type in ("numeric", "price")
                          or (c.type == "comparison" and c.norm.value is not None)):
            if c.source in ("calc", "price", "macro"):
                gates.g2 = "pass"
            elif c.source in ("da_gpt", "da_fable"):
                if c.norm.value is None:
                    # 모델 기억 숫자인데 값 미정형 = 대조 불가 → 미검증 (codex #6)
                    gates.g2 = "fail"
                    notes.append("G2:모델 기억 수치가 미정형 — 대조 불가")
                elif _g2_supported(c.norm.value, c.norm.unit, anchors):
                    gates.g2 = "pass"
                else:
                    gates.g2 = "fail"
                    notes.append("G2:결정적 계산과 불일치/부재 — 미검증 수치")
            # ra_x/ra_web/toss_*: G2 skip — G1이 근거 대조
        # 값 없는 DA comparison — 모델 기억의 정량 비교인데 대조 불가 (미정형 numeric과 동급,
        # 2차 리뷰 #5: 안 막으면 게이트 0개 통과로 default-verified 우회)
        if tier >= 2 and c.type == "comparison" and c.norm.value is None \
                and c.source in ("da_gpt", "da_fable") and c.id not in g1_map:
            gates.g2 = "fail"
            notes.append("G2:모델 기억 비교인데 수치 미정형 — 대조 불가")
        # G3 — no-lookahead: 근거 as_of가 knowledge_cutoff보다 미래면 배제
        if c.norm.as_of:
            if c.norm.as_of > plan.knowledge_cutoff:
                gates.g3 = "fail"
                notes.append(f"G3:no-lookahead 위반 as_of={c.norm.as_of}")
            else:
                gates.g3 = "pass"
        # G4 — 지시어 (tier3+)
        if tier >= 3 and _DIRECTIVE_RE.search(c.text):
            gates.g4 = "fail"
            notes.append("G4:직접 매매 지시")

        # 최종 판정 — 결정적 게이트 통과(G2/출처)가 캡 초과보다 우선 (리뷰 #4)
        if gates.g3 == "fail" or gates.g4 == "fail":
            final = "rejected"
        elif gates.g1 == "fail" or gates.g2 == "fail":
            final = "unverified"
        elif gates.g1 == "pass" or gates.g2 == "pass" or c.source in ("calc", "price", "macro"):
            final = "verified"
        elif c.id in g1_overflow_ids:
            final = "unverified"   # G1 후보였으나 캡 초과로 미판정 — verified 승격 금지
            notes.append("G1:판정 캡 초과 — 미검증 유지")
        else:
            final = "verified" if c.norm.source_type == "primary" else "unverified" \
                if c.uncertainty == "high" else "verified"
            if final == "unverified":
                notes.append("모델 스스로 불확실(high) 표시 — 단정 금지")  # 빈 사유 방지

        if final != "verified" and c.load_bearing:
            load_bearing_failed.append(c)
        verdicts.append(ClaimVerdict(
            claim_id=c.id, gates=gates, final=final,  # type: ignore[arg-type]
            judged_by=judged_by, note="; ".join(notes)[:300],  # type: ignore[arg-type]
        ))

    # ── REFLECT 발동 판단 → retry_directives (round<2에서만)
    directives: list[RetryDirective] = []
    holes = [ce for ce in table.coverage if ce.status == "uncovered"]
    if round_ < 2:
        # 사유① 핵심 주장 게이트 실패 → [검증] 재조사
        for c in load_bearing_failed[:2]:
            q = f"{c.norm.entity} {c.norm.metric} {c.norm.period}".strip() or c.text[:60]
            q = f"{q} 확인"
            if not any_similar(q, seen_queries):
                directives.append(RetryDirective(
                    kind="research", unit_id=c.unit_id, queries=[q],
                    reason=f"[검증] load-bearing 미지지: {c.text[:80]}"))
        # 사유② 미해소 충돌
        for cf in [x for x in table.conflicts if x.resolution == "unresolved"][:1]:
            ids = set(cf.claim_ids)
            src = next((c for c in table.claims if c.id in ids), None)
            if src is not None:
                q = f"{src.norm.entity} {src.norm.metric} 최신 확인".strip()
                if not any_similar(q, seen_queries):
                    directives.append(RetryDirective(
                        kind="research", unit_id=src.unit_id, queries=[q],
                        reason=f"[검증] 미해소 충돌: {cf.claim_key}"))
        # 사유③ 커버리지 구멍 (required·obtainable)
        for ce in holes[:2]:
            q = f"{ce.slot.entity} {ce.slot.metric} {ce.slot.period}".strip()
            if q and not any_similar(q, seen_queries):
                directives.append(RetryDirective(
                    kind="research", unit_id="q0", queries=[q],
                    reason=f"[수집] 커버리지 구멍: {ce.slot.entity}/{ce.slot.metric}"))
        # 사유④ 시점/기간 해석 실패 → replan (1회 한정 — 보완검색이 round를 올려도
        # 기회가 사라지면 안 됨: round==0 가드가 replan을 영구 봉인했던 결함, 리뷰 #3)
        if replan_available and any(not fp.resolved and fp.basis == "unclear"
                                    for fp in table.fiscal_periods) and load_bearing_failed:
            directives.append(RetryDirective(
                kind="replan", unit_id="q0",
                reason="기간 해석 미확정 + 핵심 주장 실패 — PLAN 부분 재실행"))

    return VerdictPacket(
        meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref()),
        verdicts=verdicts,
        retry_directives=directives[:4],
        coverage_holes=holes,
    )
