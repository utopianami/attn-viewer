# engine/tests/test_chain_verify_risk.py
import asyncio

from contracts import (AtomicClaim, ChainEdge, ChainPacket, ClaimTable, ClaimVerdict,
                       EnvelopeMeta, NewsItem, PlanPacket, RaPacket, TypedFact,
                       VerdictPacket)
from stages.risk import run_risk
from stages.verify import _claim_metric_id, _g2_supported, run_verify
from tests.test_chain_stage import _card, _plan

_META = EnvelopeMeta()


def _table():
    return ClaimTable(
        claims=[AtomicClaim(id="cl-1", text="HBM 수요가 견조하다", type="context",
                            source="da_gpt")],
        typed_facts=[
            TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB",
                      period="2026-07", metric="memory_price_usd_per_gb"),
            TypedFact(id="sector:dram_price_mom", value=11.1, unit="percent",
                      period="2026-06→2026-07", metric="memory_price_usd_per_gb"),
            TypedFact(id="bad-period", value=1.0, unit="USD/GB", period="")])


def _chain():
    # event·mechanism은 식별 가능한 자유문 — RISK 프롬프트 부재 assertion용 (r3-3)
    return ChainPacket(meta=_META, event="증설 루머 이벤트 서술",
                       mechanism="공급 확대 기제 서술", edges=[
        ChainEdge(edge_id="e0", edge="B->A", kind="observed",
                  supporting_card_ids=["card-1"]),
        ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference"),
        ChainEdge(edge_id="e2", edge="C->B", kind="observed",
                  supporting_card_ids=["card-future"]),
        ChainEdge(edge_id="e3", edge="B->A", kind="observed",
                  metric_fact_ids=["no-such-fact"]),
        ChainEdge(edge_id="e4", edge="B->A", kind="observed",
                  supporting_card_ids=["news-1"]),
        ChainEdge(edge_id="e5", edge="B->A", kind="inference",
                  metric_fact_ids=["sector:dram_price_mom"]),
        ChainEdge(edge_id="e6", edge="B->A", kind="observed",
                  metric_fact_ids=["bad-period"]),
        ChainEdge(edge_id="e7", edge="C->B", kind="observed",
                  supporting_card_ids=["card-impossible"]),
        ChainEdge(edge_id="e8", edge="B->A", kind="observed",
                  supporting_card_ids=[""])])


def _ra_with_news(published_at):
    return RaPacket(x_search={"q0": [
        NewsItem(id="news-1", title="t", published_at=published_at),
        NewsItem(title="무ID 항목", published_at="2026-07-19T00:00:00")]})  # id="" 기본값


def test_chain_verdicts_source_typed_dates_fail_closed():
    cards = [_card("card-1")]
    future = _card("card-future"); future.ts = "2026-07-25T00:00:00"  # cutoff 이후
    impossible = _card("card-impossible")
    impossible.ts = "2026-02-30T00:00:00"       # 불가능 날짜 — 정규식은 통과했었음 (r2-4)
    verdict = asyncio.run(run_verify(
        _plan(), _table(), _ra_with_news(""), [],
        chain=_chain(), sector_cards=cards + [future, impossible]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e0"].grounded is True
    assert by_id["e1"].grounded is False        # 인용 전무
    assert by_id["e2"].grounded is False and "as_of" in by_id["e2"].note  # 미래 카드
    assert by_id["e3"].grounded is False        # 미실존 fact
    assert by_id["e4"].grounded is False        # NewsItem published_at 빈 값 → fail-closed
    assert by_id["e5"].grounded is True         # 범위형 period "→" 해석 (v2 조정 5)
    assert by_id["e6"].grounded is False        # period 빈 값 → fail-closed
    assert by_id["e7"].grounded is False        # 2026-02-30 — fromisoformat 거부 (r2-4)
    assert by_id["e8"].grounded is False        # 빈 인용 ID — id="" NewsItem 실존해도 불인정


def test_cutoff_unparsable_fails_closed():
    plan = _plan(); plan.knowledge_cutoff = "26-07-21"     # 미파싱 cutoff (r2-4)
    verdict = asyncio.run(run_verify(
        plan, _table(), _ra_with_news("2026-07-19T09:00:00"), [],
        chain=_chain(), sector_cards=[_card("card-1")]))
    assert verdict.chain_verdicts and all(not v.grounded
                                          for v in verdict.chain_verdicts)


def test_duplicate_id_across_sources_not_uniquely_resolved():
    # "card-1"이 카드와 NewsItem 양쪽에 실존 → 유일 해소 실패 → 불인정 (r2-4)
    ra = RaPacket(x_search={"q0": [NewsItem(id="card-1", title="충돌",
                                            published_at="2026-07-19T00:00:00")]})
    verdict = asyncio.run(run_verify(_plan(), _table(), ra, [],
                                     chain=_chain(), sector_cards=[_card("card-1")]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e0"].grounded is False


def test_card_fact_id_collision_not_uniquely_resolved():
    # 3부 T11 블로커1 — 카드·뉴스 인덱스와 fact 인덱스를 독립적으로만 유일성
    # 검사하면 같은 id가 카드에도 fact에도 있을 때 양쪽에서 각각 "유일"로 보여
    # 곱수집이 생기던 결함(codex 최종 리뷰). 전 소스 통합 카운트로 잡아야 한다.
    dup_table = ClaimTable(typed_facts=[
        TypedFact(id="card-1", value=1.0, unit="USD/GB", period="2026-07")])
    chain = ChainPacket(meta=_META, event="e", mechanism="m", edges=[
        ChainEdge(edge_id="e0", edge="B->A", kind="observed",
                  supporting_card_ids=["card-1"])])
    verdict = asyncio.run(run_verify(_plan(), dup_table, RaPacket(), [],
                                     chain=chain, sector_cards=[_card("card-1")]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e0"].grounded is False


def test_same_source_duplicate_news_not_uniquely_resolved():
    # 같은 id의 뉴스 항목이 2개 존재 → 유일 해소 실패 → 불인정 (codex 최종 리뷰 블로커1)
    ra = RaPacket(x_search={"q0": [
        NewsItem(id="dup-news", title="a", published_at="2026-07-19T00:00:00"),
        NewsItem(id="dup-news", title="b", published_at="2026-07-19T00:00:00")]})
    chain = ChainPacket(meta=_META, event="e", mechanism="m", edges=[
        ChainEdge(edge_id="e0", edge="B->A", kind="observed",
                  supporting_card_ids=["dup-news"])])
    verdict = asyncio.run(run_verify(_plan(), _table(), ra, [],
                                     chain=chain, sector_cards=[]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e0"].grounded is False


def test_news_published_at_clean_passes():
    verdict = asyncio.run(run_verify(
        _plan(), _table(), _ra_with_news("2026-07-19T09:00:00"), [],
        chain=_chain(), sector_cards=[_card("card-1")]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e4"].grounded is True         # published_at 실존·cutoff 이내


def test_chain_none_keeps_packet_shape():
    verdict = asyncio.run(run_verify(_plan(), _table(), RaPacket(), []))
    assert verdict.chain_verdicts == []          # off-path 무영향


def test_claim_metric_id_exact_unique_longest_alias():
    assert _claim_metric_id("memory_price_usd_per_gb") == "memory_price_usd_per_gb"
    assert _claim_metric_id("D램 현물가") == "memory_price_usd_per_gb"  # 유일 alias "현물가"
    # "토큰 가격"은 token_price alias(최장) — memory의 "가격"보다 김 → 교차 오귀속 차단 (r1-B7)
    assert _claim_metric_id("토큰 가격") == "token_price"
    assert _claim_metric_id("영업이익률") == ""    # 무매칭 → fail-closed
    assert _claim_metric_id("") == ""


def test_g2_metric_identity_strict_no_untagged_bypass():
    tagged = [(5.0, "percent", "memory_price_usd_per_gb")]
    assert _g2_supported(5.0, "percent", tagged,
                         claim_metric_id="memory_price_usd_per_gb",
                         metric_identity=True)
    assert not _g2_supported(5.0, "percent", tagged, claim_metric_id="token_price",
                             metric_identity=True)
    # r2-5 회귀: 불일치 tagged anchor + 동일값·동단위 untagged anchor 조합 — 우회 불가
    mixed = [(5.0, "percent", "token_price"), (5.0, "percent", "")]
    assert not _g2_supported(5.0, "percent", mixed,
                             claim_metric_id="memory_price_usd_per_gb",
                             metric_identity=True)
    assert not _g2_supported(5.0, "percent", tagged, claim_metric_id="",
                             metric_identity=True)  # 태그 anchor 부적격
    untagged = [(5.0, "percent", "")]
    assert _g2_supported(5.0, "percent", untagged, claim_metric_id="",
                         metric_identity=True)    # 스코프 밖 — 기존 동작


def test_g2_off_arm_ignores_tags_pre_p3_equivalence():
    tagged = [(0.1, "USD/GB", "memory_price_usd_per_gb")]
    # off-arm: 태그는 데이터일 뿐 — 값/단위 일치면 기존 그대로 통과 (B1 등치)
    assert _g2_supported(0.1, "USD/GB", tagged, claim_metric_id="",
                         metric_identity=False)
    # on-arm 미해소 claim: 태그 anchor 부적격 (기존 엄격 규칙 유지)
    assert not _g2_supported(0.1, "USD/GB", tagged, claim_metric_id="",
                             metric_identity=True)


def test_sector_typed_facts_now_carry_metric(tmp_path):
    from sector.contracts import MetricObservation
    from sector.evidence import sector_typed_facts
    from sector.store import SectorStore
    from sector.thesis_contracts import observation_id
    s = SectorStore(tmp_path / "s")
    meta = {"category": "DRAM", "item": "ddr5_16gb"}
    s.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=0.09,
                          unit="USD/GB", meta=meta),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    facts = sector_typed_facts(s)
    price = next(f for f in facts if f.id == "sector:dram_price")
    assert price.metric == "memory_price_usd_per_gb"
    assert price.observation_id == observation_id("memory_price_usd_per_gb",
                                                  "2026-07", meta)


def test_risk_on_arm_verified_only_input_and_ids(monkeypatch):
    captured = {}
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, prompt, instr, response_format=None, **kw):
            captured["prompt"] = prompt
            return response_format.model_validate({"bear_cases": [
                {"text": "b", "supporting_claim_ids": ["cl-bad"]}], "wrong_if": ""})
    monkeypatch.setattr("stages.risk.Role", _FakeRole)
    table = ClaimTable(claims=[
        AtomicClaim(id="cl-1", text="HBM 수요가 견조하다", type="context",
                    source="da_gpt"),
        AtomicClaim(id="cl-bad", text="점유율 90% 확보 루머", type="fact",
                    source="da_gpt")])
    verdict = VerdictPacket(verdicts=[
        ClaimVerdict(claim_id="cl-1", final="verified"),
        ClaimVerdict(claim_id="cl-bad", final="unverified")])
    risk = asyncio.run(run_risk(_plan(), table, chain=_chain(), verdict=verdict))
    assert "HBM 수요가 견조하다" in captured["prompt"]     # verified 원문 (r1-B5)
    assert "점유율 90% 확보 루머" not in captured["prompt"]  # r2-3 — 미검증 텍스트 전면 부재
    assert "[인과 체인 판정]" in captured["prompt"] and "e0" in captured["prompt"]
    # r3-3 — 체인 자유문(event·mechanism)은 RISK 프롬프트에 재주입되지 않는다
    assert "증설 루머 이벤트 서술" not in captured["prompt"]
    assert "공급 확대 기제 서술" not in captured["prompt"]
    assert risk.bear_cases[0].label == "scenario"          # 미검증 ID supporting 거부
    assert risk.bear_cases[0].supporting_claim_ids == []   # valid_ids ⊆ verified (r2-3)
    captured.clear()
    asyncio.run(run_risk(_plan(), table))                  # off-path — 기존 계약 그대로
    assert "점유율 90% 확보 루머" in captured["prompt"]     # 전 claim 목록 유지 (등치)
    assert "[인과 체인 판정]" not in captured["prompt"]
