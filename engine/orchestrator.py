"""QA 파이프라인 오케스트레이터 — 설계 §1.1 v1 그래프 완전판 (2026-07-03).

TRIAGE → PLAN → (tier4 차단) → [DA·RA·PRICE 병렬] → ASSEMBLER → CALC → VERIFIER
 ↺ REFLECT (배타 라우팅: 발동 시 재조사 후 재조립·재검증, 최대 2라운드)
 → RISK(tier3) → SYNTHESIZER → AUDITOR → FINALIZER

불변식:
1. 브랜치는 raise하지 않고 항상 패킷 반환 (never-raise, 오케스트레이터가 격리)
2. 모든 숫자는 CALC/시세(결정적)에서만 — enforce_g2 코드 게이트 + AUDITOR 이중 안전망
REFLECT 규칙: 신규 확장 쿼리 강제(seen_queries), 신규 문서 0건 → unobtainable 종료,
replan은 그래프 전이가 아니라 서브루틴(1회 한정, tier·차단 판정은 라운드1 값 고정).
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from contracts import (
    DaPacket,
    EnvelopeMeta,
    FinalAnswer,
    PlanPacket,
    PlanSummary,
    PriceMacroPacket,
    RaPacket,
)
from providers import CostMeter, current_meter
from stages.answerability import run_answerability
from stages.assemble import run_assemble
from stages.audit import run_audit
from stages.calc import run_calc
from stages.da import run_da
from stages.followup import run_followup, run_smalltalk
from stages.plan import run_plan
from stages.price_macro import run_price_macro
from stages.news_summary import run_news_summary
from stages.ra_external import run_ra_external, run_ra_research
from stages.risk import run_risk
from stages.synthesize import run_synthesize
from stages.triage import run_triage
from stages.verify import run_verify

_MAX_ROUNDS = 2  # REFLECT 상한 (초기 라운드 제외 최대 2회 재조사)


def _layer(name: str, data: dict, round_: int = 0) -> dict:
    return {"kind": "layer", "name": name, "round": round_, "data": data}


def _blocked_answer(plan: PlanPacket) -> str:
    return (
        "요청하신 주문·매매 실행은 이 시스템이 수행할 수 없습니다.\n\n"
        "대신 판단 재료가 필요하시면 이렇게 물어보세요 — "
        f"“{plan.tickers[0].name if plan.tickers else '해당 종목'} 지금 사도 될까?” 처럼요. "
        "근거·리스크·반대 시나리오를 정리해 드립니다."
    )


async def _safe(coro, fallback):
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        fallback.error = str(exc)[:400]
        return fallback


def _plan_layer_data(plan: PlanPacket) -> dict:
    return {
        "tier": plan.tier,
        "standalone_question": plan.standalone_question,
        "knowledge_cutoff": plan.knowledge_cutoff,
        "news_mode": plan.news_mode,
        "richness": {"grade": plan.richness.grade if plan.richness else "B"},
        "tickers": [{"name": t.name, "symbol": t.yahoo_symbol} for t in plan.tickers],
        "sub_questions": [{"id": s.id, "text": s.text, "depends_on": s.depends_on} for s in plan.sub_questions],
        "contrast_questions": plan.contrast_questions,
        "needed_evidence": [{"entity": n.entity, "metric": n.metric, "source_type": n.source_type} for n in plan.needed_evidence],
        "metrics": plan.metrics,
        "g0_notes": plan.g0_notes,
    }


def _claims_layer_data(table) -> dict:
    return {
        "count": len(table.claims),
        "claims": [{"text": c.text, "source": c.source, "provenance": c.provenance,
                    "uncertainty": c.uncertainty, "load_bearing": c.load_bearing}
                   for c in table.claims[:25]],
        "conflicts": [{"key": cf.claim_key, "resolution": cf.resolution} for cf in table.conflicts],
        "da_disagreements": len(table.da_disagreements),
        "coverage": [{"slot": f"{ce.slot.entity}/{ce.slot.metric}", "status": ce.status}
                     for ce in table.coverage],
        "richness": table.richness.model_dump() if table.richness else None,
    }


def _ra_x_layer_data(ra: RaPacket) -> dict:
    """ra_x 레이어 — 사용자에게는 큐레이션 통과분만 (raw 노출 금지, 2026-07-06)."""
    items = []
    for pool_items in ra.curated_items().values():
        for n in pool_items[:6]:
            items.append({"title": n.title, "url": n.url, "published_at": n.published_at})
    return {"narrative": ra.x_narrative, "items": items[:12]}


def _verify_layer_data(verdict) -> dict:
    counts = {"verified": 0, "unverified": 0, "rejected": 0}
    for v in verdict.verdicts:
        counts[v.final] = counts.get(v.final, 0) + 1
    return {
        "counts": counts,
        "failed": [{"claim_id": v.claim_id, "final": v.final, "note": v.note}
                   for v in verdict.verdicts if v.final != "verified"][:12],
        "retry_directives": [{"kind": d.kind, "reason": d.reason, "queries": d.queries}
                             for d in verdict.retry_directives],
        "coverage_holes": len(verdict.coverage_holes),
    }


async def run_qa(question: str, history: list | None = None,
                 overrides: dict | None = None) -> AsyncIterator[dict]:
    """QA 파이프라인. layer dict들을 yield하고 마지막에 {"kind":"final",...}."""
    started = time.monotonic()
    models_used: set[str] = set()
    degraded: list[str] = []
    meter = CostMeter()
    current_meter.set(meter)

    # ── ⓪ TRIAGE — 입구 라우팅 (deep / followup / smalltalk, /deep 강제)
    triage, question = await run_triage(question, history, overrides)
    yield _layer("triage", {"route": triage.route, "needs_fresh_data": triage.needs_fresh_data,
                            "reason": triage.reason})

    if triage.route == "smalltalk":
        answer = await run_smalltalk(question, history, overrides)
        yield {"kind": "final", "answer": answer, "meta": FinalAnswer(
            answer_markdown=answer, models_used=["gpt-5.4-mini"],
            cost=meter.summary(),
            elapsed_s=round(time.monotonic() - started, 2)).model_dump(mode="json")}
        return
    if triage.route == "followup" and not triage.needs_fresh_data:
        answer = await run_followup(question, history, overrides)
        yield {"kind": "final", "answer": answer, "meta": FinalAnswer(
            answer_markdown=answer, models_used=["opus-4.8"],
            cost=meter.summary(),
            elapsed_s=round(time.monotonic() - started, 2)).model_dump(mode="json")}
        return

    # ── ① PLAN
    plan = await run_plan(question, history, overrides)
    models_used.update({"opus-4.8", "gpt-5.4-mini"})
    yield _layer("plan", _plan_layer_data(plan))

    # tier 4 차단 (배타 라우팅 — 라운드1 판정 고정)
    if plan.tier == 4:
        blocked = _blocked_answer(plan)
        yield {"kind": "final", "answer": blocked, "meta": FinalAnswer(
            answer_markdown=blocked, models_used=list(models_used),
            plan_summary=PlanSummary(tier=4, knowledge_cutoff=plan.knowledge_cutoff, tickers=plan.tickers),
            cost=meter.summary(),
            elapsed_s=round(time.monotonic() - started, 2)).model_dump(mode="json")}
        return

    # ── ② DISPATCH — 3브랜치 무조건 fan-out
    da_fb = DaPacket(meta=EnvelopeMeta(plan_ref=plan.plan_ref()), status="error")
    ra_fb = RaPacket(meta=EnvelopeMeta(plan_ref=plan.plan_ref()), status="error")
    pm_fb = PriceMacroPacket(meta=EnvelopeMeta(plan_ref=plan.plan_ref()), status="error")

    da, ra, pm = await asyncio.gather(
        _safe(run_da(plan, overrides), da_fb),
        _safe(run_ra_external(plan, overrides), ra_fb),
        _safe(run_price_macro(plan), pm_fb),
    )
    models_used.update({"gpt-5.5", "opus-4.8"})

    # 브랜치 layer 방출
    yield _layer("da_blind", {
        "unit_answers": [{"unit_id": u.unit_id, "model": u.model, "answer_text": u.answer_text}
                         for u in da.unit_answers],
        "status": da.status,
    })
    if da.status != "ok":
        degraded.append("da")

    if ra.x_narrative or ra.x_search:
        yield _layer("ra_x", _ra_x_layer_data(ra))

    # NEWS_SUMMARY (sonnet) — 실패해도 비차단 (degrade)
    news_sum = None
    try:
        news_sum = await run_news_summary(plan, ra, overrides)
        if news_sum and news_sum.lines:
            yield _layer("news_summary", {
                "lines": [{"text": l.text, "url": l.url} for l in news_sum.lines],
                "as_of": news_sum.as_of,
            })
            models_used.add("sonnet-4.6")
    except Exception:  # noqa: BLE001
        degraded.append("news_summary")

    if ra.web_knowledge:
        yield _layer("ra_web", {"items": [
            {"title": n.title, "url": n.url}
            for items in ra.web_knowledge.values() for n in items[:4]][:10]})
    if ra.toss_trend and ra.toss_trend.articles:
        yield _layer("toss_trend", {"trends": ra.toss_trend.trends})
    if ra.toss_company:
        yield _layer("toss_company", {"codes": list(ra.toss_company.keys()),
                                      "detail": ra.toss_company})
    if ra.status in ("degraded", "error"):
        degraded.append("ra_external")

    if pm.quotes:
        yield _layer("price", {"quotes": pm.quotes})
    if pm.macro:
        yield _layer("macro", pm.macro)
    if pm.status not in ("ok",):
        degraded.append("price_macro")

    # ── ③④⑤⑥ ASSEMBLE → CALC → VERIFY ↺ REFLECT (최대 2라운드)
    seen_queries: set[str] = set(plan.search_queries)
    for sq in plan.sub_questions:
        seen_queries.update(sq.search_queries)
    seen_urls: set[str] = set()
    for items in list(ra.x_search.values()) + list(ra.web_knowledge.values()):
        seen_urls.update(n.url for n in items if n.url)
    extra_claims: list = []
    calc_results: list = []
    replan_used = False
    round_ = 0

    table = run_assemble(plan, da, ra, pm, round_=round_)
    yield _layer("claims", _claims_layer_data(table), round_)

    # CALC — 라운드 0에서 1회 (시세 typed_facts는 라운드 간 불변)
    calc_missing: list = []
    try:
        calc_results, calc_claims, calc_missing = await run_calc(plan, table, overrides)
        extra_claims.extend(calc_claims)
        if calc_results:
            yield _layer("calc", {"results": [
                {"metric": r.request.metric, "ok": r.ok,
                 "value": (r.result or {}).get("result"),
                 "errors": (r.result or {}).get("errors", [])} for r in calc_results]})
        if calc_claims:
            table = run_assemble(plan, da, ra, pm, extra_claims=extra_claims, round_=round_)
    except Exception as exc:  # noqa: BLE001
        degraded.append("calc")
        yield _layer("calc", {"results": [], "error": str(exc)[:200]})

    # ── ③′ ANSWERABILITY (P1-3/P1-4) — 게이트 실패 전에 "증거로 답 되는가" 선판정,
    #    부족분은 표적 보완질문으로 1회 선제 재검색 (REFLECT와 총 라운드 상한 2 공유)
    answerability_data = None
    try:
        ans = await run_answerability(plan, table, ra, overrides,
                                      calc_missing=calc_missing)
        answerability_data = {
            "unit_verdicts": ans.unit_verdicts,
            "supplements": [{"unit_id": s.unit_id, "question": s.question,
                             "queries": s.search_queries} for s in ans.supplements],
        }
        supp_queries = [q for q in ans.queries() if q not in seen_queries][:4]
        if supp_queries and round_ < _MAX_ROUNDS:
            found, new_claims = await run_ra_research(
                supp_queries, seen_urls=seen_urls, overrides=overrides, tag="supp")
            # 성공 후에만 seen 마킹 — 검색이 죽었는데 쿼리를 소진 처리하면
            # 이후 REFLECT의 동일 쿼리가 영구 필터링됨 (리뷰 #8)
            seen_queries.update(supp_queries)
            if found:
                round_ += 1
                for items in found.values():
                    seen_urls.update(n.url for n in items if n.url)
                    ra.x_search.setdefault(f"supplement_r{round_}", []).extend(items)
                extra_claims.extend(new_claims)
                table = run_assemble(plan, da, ra, pm, extra_claims=extra_claims, round_=round_)
                yield _layer("claims", _claims_layer_data(table), round_)
            else:
                answerability_data["research"] = "보완 검색 신규 문서 0건"
    except Exception:  # noqa: BLE001 — 선판정 실패가 파이프라인을 죽이면 안 됨
        pass

    g1_cache: dict = {}  # G1 판정 캐리오버 — supported 재사용, 캡·비용은 라운드 신규분에만
    verdict = await run_verify(plan, table, ra, calc_results,
                               round_=round_, seen_queries=seen_queries,
                               g1_cache=g1_cache, replan_available=not replan_used,
                               overrides=overrides)
    vdata = _verify_layer_data(verdict)
    if answerability_data:
        vdata["answerability"] = answerability_data
    yield _layer("verify", vdata, round_)

    # ↺ REFLECT — 배타 라우팅: 발동 시 재조사→재조립→재검증만 (라운드1 답 조기 방출 없음)
    while verdict.retry_directives and round_ < _MAX_ROUNDS:
        attempt = round_ + 1  # 신규 문서를 실제로 얻어야 라운드로 확정 (codex #8)
        research_queries: list[str] = []
        for d in verdict.retry_directives:
            if d.kind == "replan" and not replan_used:
                # replan 서브루틴 — 1회 한정, tier·차단 판정은 라운드1 값 고정
                replan_used = True
                try:
                    replanned = await run_plan(
                        f"{question}\n[재계획 사유] {d.reason}", history, overrides)
                    plan.fiscal_periods = replanned.fiscal_periods
                    plan.metrics = list({*plan.metrics, *replanned.metrics})
                    for q in replanned.search_queries:
                        if q not in seen_queries:
                            research_queries.append(q)
                except Exception:
                    pass
                continue
            for q in d.queries:
                if q not in seen_queries:
                    research_queries.append(q)
        research_queries = list(dict.fromkeys(research_queries))[:4]
        if not research_queries:
            break  # 신규 확장 쿼리 없음 — 공회전 금지

        try:
            found, new_claims = await run_ra_research(
                research_queries, seen_urls=seen_urls, overrides=overrides,
                tag=f"r{attempt}_")
            seen_queries.update(research_queries)  # 성공 후 마킹 (리뷰 #8)
        except Exception:  # noqa: BLE001 — 재조사 실패가 파이프라인을 죽이면 안 됨 (codex #9)
            found, new_claims = {}, []
        if not found:
            # 신규 문서 0건 → unobtainable 마킹 후 즉시 종료 (라운드 미소비 — meta.rounds 미증가)
            for ce in table.coverage:
                if ce.status == "uncovered":
                    ce.status = "unobtainable"
            # coverage 변경을 화면에도 반영 + verify 데이터에 병합 방출 — 별도 reflect 레이어가
            # 같은 (name, round)로 실측 verdict 표시를 지우는 문제 해소 (리뷰 #1, #10)
            yield _layer("claims", _claims_layer_data(table), round_)
            yield _layer("verify", {**_verify_layer_data(verdict),
                                    "reflect": "재조사 신규 문서 0건 — 정직한 빈칸 처리",
                                    "queries": research_queries}, round_)
            break
        round_ = attempt
        for items in found.values():
            seen_urls.update(n.url for n in items if n.url)
            ra.x_search.setdefault(f"reflect_r{round_}", []).extend(items)
        extra_claims.extend(new_claims)

        table = run_assemble(plan, da, ra, pm, extra_claims=extra_claims, round_=round_)
        yield _layer("claims", _claims_layer_data(table), round_)
        verdict = await run_verify(plan, table, ra, calc_results,
                                   round_=round_, seen_queries=seen_queries,
                                   g1_cache=g1_cache, replan_available=not replan_used,
                                   overrides=overrides)
        yield _layer("verify", _verify_layer_data(verdict), round_)

    # ── ⑥′ RISK (tier 3만 — 내부 passthrough)
    risk = await run_risk(plan, table, round_=round_, overrides=overrides)
    if risk.applicable:
        yield _layer("risk", {
            "bear_cases": [{"text": b.text, "label": b.label} for b in risk.bear_cases],
            "wrong_if": risk.wrong_if,
        }, round_)

    # ── ⑦ SYNTHESIZE (실패해도 final은 반드시 방출)
    try:
        draft = await run_synthesize(
            plan, da, ra=ra, price=pm.model_dump(), claim_table=table,
            verdict=verdict, calc_results=calc_results, risk=risk,
            news_summary=news_sum, overrides=overrides)
        answer_md = draft.answer_markdown
    except Exception:  # noqa: BLE001
        degraded.append("synthesize")
        fallback = "\n\n".join(f"**{u.unit_id}**: {u.answer_text}" for u in da.unit_answers[:3])
        answer_md = ("합성 단계에서 오류가 발생해 수집된 독립 답변만 제공합니다.\n\n"
                     + (fallback or "답변 생성에 실패했습니다."))
    models_used.add("opus-4.8")

    # ── ⑧ AUDITOR — 최종 텍스트 게이트 (숫자 대조·지시어 완곡화·신규 사실)
    try:
        # 근거 원문 (본문·요약·서사) — 근거에 실재하는 숫자·엔티티의 오탐 방지
        # evidence_docs (url→원문) — ④ 인용 entailment 판정용 (P5)
        evidence_texts = [ra.x_narrative]
        evidence_docs: dict[str, str] = {}
        for items in ra.curated_items().values():
            for n in items[:5]:
                # 전문 포함 — 숫자 앵커는 regex 추출이라 길이 비용 없음 (truncation이 오탐 유발)
                evidence_texts.append(f"{n.source_name} {n.title} {n.summary} {n.content}")
                # 본문 확보분만 — 헤드라인 200자에 대고 판정하면 정당한 인용이
                # neutral로 쏟아져 인용일치율이 무의미해짐 (2차 리뷰 #4)
                if n.url and len(n.content) >= 300:
                    evidence_docs.setdefault(n.url, f"{n.title}\n{n.summary}\n{n.content}")
        audit_report, answer_md = await run_audit(answer_md, table, calc_results,
                                                  verdict=verdict,
                                                  evidence_texts=evidence_texts,
                                                  evidence_docs=evidence_docs,
                                                  overrides=overrides)
        yield _layer("audit", {
            "numeric_total": audit_report.numeric_total,
            "numeric_supported": audit_report.numeric_supported,
            "directive_hits": audit_report.directive_hits,
            "issues": [{"kind": i.kind, "sentence": i.sentence[:120], "detail": i.detail}
                       for i in audit_report.issues][:10],
            "severe": audit_report.severe,
            "skipped": audit_report.skipped,
            "provenance_soundness": audit_report.provenance_soundness,
        }, round_)
    except Exception:  # noqa: BLE001
        from contracts import AuditReport
        audit_report = AuditReport(skipped=True)
        degraded.append("audit")

    # ── ⑨ FINALIZER
    final = FinalAnswer(
        answer_markdown=answer_md,
        degraded=degraded,
        audit=audit_report,
        models_used=sorted(models_used),
        rounds=round_,
        plan_summary=PlanSummary(
            tier=plan.tier, knowledge_cutoff=plan.knowledge_cutoff,
            tickers=plan.tickers, fiscal_periods=plan.fiscal_periods,
        ),
        cost=meter.summary(),
        elapsed_s=round(time.monotonic() - started, 2),
    )
    yield {"kind": "final", "answer": answer_md, "meta": final.model_dump(mode="json")}
