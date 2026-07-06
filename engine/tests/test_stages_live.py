"""M5 스테이지별 개별 라이브 테스트 — 전용 입력으로 하나씩 검증 (2026-07-03).

각 스테이지를 격리 실행: 전용 크래프트 입력 → 실행 → 계약·행동 assert.
사용: .venv/bin/python tests/test_stages_live.py [stage]
  stage ∈ ra | calc | verify | risk | audit | reflect | all
비용: 전체 ~$0.3 (grok 검색 1콜 포함). CI 아님 — 수동/야간용.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import (  # noqa: E402
    AtomicClaim,
    CalcRequest,
    ClaimNorm,
    DaPacket,
    NeededEvidence,
    PlanPacket,
    PriceMacroPacket,
    RaPacket,
    SubQuestion,
    TypedFact,
    UnitAnswer,
)
from stages.assemble import run_assemble  # noqa: E402


def make_plan(**kw) -> PlanPacket:
    base = dict(
        tier=2, original_question="SK하이닉스 올해 수익률과 HBM 점유율은?",
        standalone_question="SK하이닉스 올해 수익률과 HBM 점유율",
        knowledge_cutoff="2026-07-03",
        sub_questions=[SubQuestion(id="q1", text="SK하이닉스 HBM 점유율",
                                   search_queries=["SK하이닉스 HBM 점유율 2026"])],
        search_queries=["SK하이닉스 주가 2026"],
        needed_evidence=[
            NeededEvidence(entity="SK하이닉스", metric="수익률", source_type="price"),
            NeededEvidence(entity="기관 리밸런싱", metric="방식과 일정", source_type="web"),
        ],
        metrics=["기간 수익률"],
    )
    base.update(kw)
    return PlanPacket(**base)


def make_pm() -> PriceMacroPacket:
    return PriceMacroPacket(typed_facts=[
        TypedFact(id="price:SK하이닉스", value=2282000, unit="KRW", label="SK하이닉스 현재가",
                  source="yahoo:000660.KS"),
        TypedFact(id="ret:SK하이닉스", value=298.4, unit="percent", period="since 2026-01-02",
                  label="SK하이닉스 기간수익률", source="yahoo:000660.KS"),
    ], macro={"KOSPI": {"last": 7851.02, "day_pct": 2.65}})


async def t_ra():
    """RA-외부: web_knowledge 발동(web 슬롯) + 유닛별 x_search + claim 추출 + trend 합성."""
    from stages.ra_external import run_ra_external
    plan = make_plan()
    ra = await run_ra_external(plan)
    print(f"  collector_status={ra.collector_status}")
    print(f"  x_narrative={len(ra.x_narrative)}자, x_search units={list(ra.x_search.keys())}")
    print(f"  web_knowledge units={list(ra.web_knowledge.keys())} (web 슬롯 발동 확인)")
    print(f"  claims={len(ra.claims)} (추출), trend={len(ra.toss_trend.trends) if ra.toss_trend else 0}")
    assert ra.status in ("ok", "degraded"), ra.status
    assert "web_knowledge" in ra.collector_status, "web 슬롯이 있는데 web_knowledge 미발동"
    assert ra.claims, "claim 추출 0건"
    derived = [c for c in ra.claims if c.derived]
    print(f"  derived(trend) claims={len(derived)} — 전부 근거 뉴스 id 보유: "
          f"{all(c.ref for c in derived)}")
    print("PASS ra")
    return ra


async def t_calc():
    """CALC: 실 GPT 프로그램 작성 → finance_math 결정적 실행."""
    from stages.calc import run_calc
    plan = make_plan(metrics=["연초 대비 수익률(%)", "현재가 대비 250만원 괴리율(%)"])
    pm = make_pm()
    da = DaPacket(unit_answers=[])
    table = run_assemble(plan, da, RaPacket(), pm)
    table.calc_requests = [
        CalcRequest(metric="연초 대비 수익률(%)", typed_fact_ids=[f.id for f in pm.typed_facts]),
        CalcRequest(metric="현재가 대비 250만원 괴리율(%)", typed_fact_ids=[f.id for f in pm.typed_facts]),
    ]
    results, claims, missing = await run_calc(plan, table)
    print(f"  missing_inputs={missing}")
    for r in results:
        print(f"  [{('OK' if r.ok else 'SKIP/FAIL')}] {r.request.metric} → "
              f"{(r.result or {}).get('result') or (r.result or {}).get('errors')}")
    assert results, "결과 없음"
    ok_results = [r for r in results if r.ok]
    for r in ok_results:
        assert r.result["checks"]["units_consistent"], "단위 검증 실패"
    assert claims and all(c.source == "calc" for c in claims)
    print(f"  calc claims={[(c.text) for c in claims]}")
    print("PASS calc")


async def t_verify():
    """VERIFIER: 실 G1 심판 (교차 채점) + 코드 게이트 통합."""
    from stages.verify import run_verify
    plan = make_plan(tier=3)
    pm = make_pm()
    # 크래프트 입력: 지지될 claim(수익률 298), 조작 claim(수익률 500), fable claim(교차 채점 확인)
    good = AtomicClaim(id="da_gpt:q0:c0", text="SK하이닉스는 올해 약 298% 상승했다", type="numeric",
                       source="da_gpt", unit_id="q0", load_bearing=True,
                       norm=ClaimNorm(entity="SK하이닉스", metric="수익률", value=298.0, unit="percent"))
    bad = AtomicClaim(id="da_gpt:q0:c1", text="SK하이닉스는 올해 500% 상승했다", type="numeric",
                      source="da_gpt", unit_id="q0", load_bearing=True,
                      norm=ClaimNorm(entity="SK하이닉스", metric="수익률", value=500.0, unit="percent"))
    fable_c = AtomicClaim(id="da_fable:q0:c0", text="SK하이닉스는 HBM 시장 1위다", type="fact",
                          source="da_fable", unit_id="q0", load_bearing=True,
                          norm=ClaimNorm(entity="SK하이닉스", metric="HBM 점유율 순위"))
    da = DaPacket(unit_answers=[
        UnitAnswer(unit_id="q0", model="da_gpt", answer_text="a", claims=[good, bad]),
        UnitAnswer(unit_id="q0", model="da_fable", answer_text="b", claims=[fable_c]),
    ])
    ra = RaPacket(x_narrative="SK하이닉스는 2026년 HBM 시장 점유율 1위(약 55%)를 유지하고 있으며 "
                              "올해 주가는 약 298% 상승했다. (출처: https://example.com/1)")
    table = run_assemble(plan, da, ra, pm)
    v = await run_verify(plan, table, ra, [], round_=0, seen_queries=set())
    vmap = {x.claim_id: x for x in v.verdicts}
    print(f"  good: {vmap['da_gpt:q0:c0'].final} (g2={vmap['da_gpt:q0:c0'].gates.g2})")
    print(f"  bad(500%): {vmap['da_gpt:q0:c1'].final} (g2={vmap['da_gpt:q0:c1'].gates.g2})")
    print(f"  fable claim 심판: judged_by={vmap['da_fable:q0:c0'].judged_by} (gpt여야 함 — 교차 채점)")
    assert vmap["da_gpt:q0:c0"].gates.g2 == "pass"
    assert vmap["da_gpt:q0:c1"].gates.g2 == "fail" and vmap["da_gpt:q0:c1"].final != "verified"
    assert vmap["da_fable:q0:c0"].judged_by == "gpt", "교차 채점 라우팅 실패"
    print("PASS verify")


async def t_risk():
    """RISK: tier3 bear case — supporting_claim_ids 코드 라벨링."""
    from stages.risk import run_risk
    plan = make_plan(tier=3)
    pm = make_pm()
    ra = RaPacket(claims=[
        AtomicClaim(id="ra_x:c0", text="마이크론이 HBM4 양산을 앞당겨 경쟁이 심화되고 있다",
                    type="fact", source="ra_x",
                    norm=ClaimNorm(entity="마이크론", metric="HBM4 양산", as_of="2026-07-01")),
    ])
    table = run_assemble(plan, DaPacket(unit_answers=[]), ra, pm)
    risk = await run_risk(plan, table)
    assert risk.applicable and risk.bear_cases, "tier3인데 bear case 없음"
    for b in risk.bear_cases:
        print(f"  ({b.label}) {b.text[:80]} ids={b.supporting_claim_ids}")
        if b.supporting_claim_ids:
            assert b.label == "grounded"
        else:
            assert b.label == "scenario"
    print(f"  wrong_if: {risk.wrong_if[:80]}")
    # tier2 → passthrough
    r2 = await run_risk(make_plan(tier=2), table)
    assert not r2.applicable
    print("PASS risk (tier2 passthrough 포함)")


async def t_audit():
    """AUDIT: 실 mini 신규 엔티티 + 코드 숫자 대조/완곡화."""
    from stages.audit import run_audit
    plan = make_plan()
    pm = make_pm()
    table = run_assemble(plan, DaPacket(unit_answers=[]), RaPacket(), pm)
    answer = ("SK하이닉스는 올해 298.4% 상승했고 현재가 2,282,000원, 228만원 수준이다. "
              "코스피는 7,851.02로 +2.65% 올랐다. 한편 큐리오시티캐피털은 지분 7.7%를 매집했다. "
              "지금 무조건 사세요.")
    report, patched = await run_audit(answer, table, [])
    print(f"  숫자 {report.numeric_supported}/{report.numeric_total} 지지")
    for i in report.issues:
        print(f"  [{i.kind}] {i.detail or i.sentence[:60]}")
    assert report.numeric_supported >= 3, "지지 숫자(298.4/2282000/2.65) 미매칭"
    assert any(i.kind == "numeric_unsupported" and "7.7" in i.sentence for i in report.issues)
    assert report.directive_hits and "사세요" not in patched
    assert any(i.kind == "new_fact" for i in report.issues), "신규 엔티티(큐리오시티캐피털) 미탐"
    print("PASS audit")


async def t_reflect():
    """REFLECT 부품: run_ra_research — 신규 쿼리 검색 + seen_urls 제외."""
    from stages.ra_external import run_ra_research
    found, claims = await run_ra_research(
        ["SK하이닉스 HBM4 양산 일정"], seen_urls=set())
    n_docs = sum(len(v) for v in found.values())
    print(f"  신규 문서={n_docs}, 추출 claims={len(claims)}")
    assert n_docs > 0, "재조사 검색 실패"
    # 같은 쿼리 + 전부 seen 처리 → 신규 0건이어야 (unobtainable 판정 경로)
    all_urls = {n.url for v in found.values() for n in v if n.url}
    found2, _ = await run_ra_research(["SK하이닉스 HBM4 양산 일정"], seen_urls=all_urls)
    n2 = sum(len(v) for v in found2.values())
    print(f"  seen 처리 후 신규={n2} (0에 가까워야)")
    print("PASS reflect")


async def t_p1():
    """P1: 실 RA 수집 → curation·본문 fetch 검증 → 실출력으로 answerability 판정.

    메모리 규칙: 수제 입력이 아니라 '직전 스테이지 실출력'을 통과시켜 계약 실효성 확인.
    """
    from stages.answerability import run_answerability
    from stages.ra_external import run_ra_external
    plan = make_plan()
    ra = await run_ra_external(plan)

    # curation — 선별 결과가 실제 풀의 id를 가리키는지
    pool_ids = {n.id for items in list(ra.x_search.values()) + list(ra.web_knowledge.values())
                for n in items}
    cur_ids = {i for ids in ra.curated.values() for i in ids}
    print(f"  pool={len(pool_ids)}건 → curated={ {k: len(v) for k, v in ra.curated.items()} }")
    assert cur_ids <= pool_ids, f"curated에 풀 밖 id: {cur_ids - pool_ids}"
    assert all(len(v) <= 5 for v in ra.curated.values()), "유닛당 상한 5 위반"

    # 본문 fetch — curation 통과분 중 content 채워진 수
    kept = [n for items in ra.curated_items().values() for n in items]
    with_body = [n for n in kept if len(n.content) >= 300]
    print(f"  curation 통과 {len(kept)}건 중 본문 확보 {len(with_body)}건")
    if kept and not with_body:
        print("  (경고) 본문 0건 — 사이트 차단 가능성, 제목/요약 동작은 유지됨")

    # answerability — 실 RA 출력 + 시세로 조립한 표를 판정
    pm = make_pm()
    table = run_assemble(plan, DaPacket(unit_answers=[]), ra, pm)
    ans = await run_answerability(plan, table, ra)
    print(f"  unit_verdicts={ans.unit_verdicts}")
    for s in ans.supplements:
        print(f"  보완: [{s.unit_id}] {s.question} → {s.search_queries}")
    assert set(ans.unit_verdicts.values()) <= {"answerable", "partial", "unanswerable"}
    for s in ans.supplements:
        assert s.question.strip() and s.question != plan.standalone_question, \
            "보완질문이 원질문 재서술"
    print(f"  queries()={ans.queries()[:4]}")
    print("PASS p1")


async def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    tests = {"ra": t_ra, "calc": t_calc, "verify": t_verify, "risk": t_risk,
             "audit": t_audit, "reflect": t_reflect, "p1": t_p1}
    if which == "all":
        for name, fn in tests.items():
            print(f"\n=== {name} ===")
            await fn()
        print("\n전체 스테이지 라이브 테스트 통과")
    else:
        await tests[which]()


if __name__ == "__main__":
    asyncio.run(main())
