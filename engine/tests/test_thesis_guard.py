# engine/tests/test_thesis_guard.py
from sector.contracts import MetricObservation, SectorCard
from sector.store import SectorStore
from sector.thesis_contracts import Statement
from sector.thesis_guard import (build_evidence, eligible_card, filter_statements,
                                 independent_publishers, publisher_id, quantity_literal,
                                 quote_valid, resolve_key_metrics)


def _card(cid, url, quote="본문 인용문 원문", grade="A", signal=""):
    return SectorCard(id=cid, ts="2026-07-20T00:00:00", axis="A", direction="pos",
                      magnitude=2, source_grade=grade, title=f"제목-{cid}",
                      interpreted_signal=signal, raw_quote=quote, url=url,
                      entities=["SK_HYNIX"])


def test_publisher_id_psl():
    assert publisher_id("https://news.fnnews.com/a/1") == "fnnews.com"
    assert publisher_id("https://www.chosun.co.kr/x") == "chosun.co.kr"
    assert publisher_id("not-a-url") == ""
    assert publisher_id("https://localhost/x") == ""          # 단일 라벨 (r2-B4)
    assert publisher_id("https://127.0.0.1/x") == ""          # IP
    assert publisher_id("https://co.kr/x") == ""              # suffix-only


def test_quantity_acceptance_matrix():                       # B7 — 고정 matrix
    for allowed in ("gpt-5.5 모델", "HBM3E", "DDR5 수요", "H100 클러스터"):
        assert not quantity_literal(allowed), allowed
    for banned in ("12% 상승", "12퍼센트", "$12", "₩12", "USD12", "12 USD",
                   "12달러", "12조 규모", "3bp", "수치는 12 였다"):
        assert quantity_literal(banned), banned


def test_build_evidence_rederives_and_rejects():             # B4
    c = _card("c1", "https://news.a.com/1", quote="HBM 수요가 강하다는 보도 원문")
    ev = build_evidence(c, "HBM 수요가 강하다")
    assert ev and ev.publisher_id == "a.com" and ev.canonical_url == c.url
    assert build_evidence(c, "  ") is None                   # 빈 quote
    assert build_evidence(c, "없는 문장") is None
    assert build_evidence(_card("c2", "javascript:void(0)"), "본문") is None
    assert not eligible_card(_card("c3", "https://a.com", signal="공시 원문 확인 필요 (자동 보존)"))
    assert not eligible_card(_card("c4", "https://a.com", grade="D"))
    assert quote_valid(c, "제목-c1")                          # title도 허용


def test_independence_and_filter():
    cards = {"c1": _card("c1", "https://a.com/1", quote="HBM 수요가 공급을 크게 앞선다 분석"),
             "c2": _card("c2", "https://b.com/2", quote="HBM 수요가 공급을 크게 앞선다 분석"),
             "c3": _card("c3", "https://c.com/3", quote="고객 인증 확대라는 별개 근거")}
    st_reprint = Statement(statement_id="s1", text="수요가 공급을 앞선다", supporting=[
        build_evidence(cards["c1"], "HBM 수요가 공급을 크게 앞선다"),
        build_evidence(cards["c2"], "HBM 수요가 공급을 크게 앞선다")])
    st_ok = Statement(statement_id="s2", text="수요가 공급을 앞선다", supporting=[
        build_evidence(cards["c1"], "HBM 수요가 공급을 크게 앞선다"),
        build_evidence(cards["c3"], "고객 인증 확대라는 별개 근거")])
    assert independent_publishers(st_reprint.supporting, cards) == 1
    kept, dropped = filter_statements([st_reprint, st_ok], cards)
    assert [s.statement_id for s in kept] == ["s2"] and dropped


def test_resolve_key_metrics_group_and_source(tmp_path):     # B5
    store = SectorStore(tmp_path / "s")
    store.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.09,
                          unit="USD/GB", meta={"category": "DRAM"}, source="Keepa 소비자가"),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.30,
                          unit="USD/GB", meta={"category": "NAND"})])
    seed = {"required_inputs": [{"metric": "memory_price_usd_per_gb", "max_age_days": 45,
                                 "min_count": 1, "meta_filter": {"category": "DRAM"}}]}
    kms, dropped = resolve_key_metrics(["memory_price_usd_per_gb", "ghost"], seed, store)
    assert len(kms) == 1 and kms[0].value == 0.09            # DRAM 그룹 고정 — NAND 아님
    assert kms[0].source == "Keepa 소비자가"                   # obs.source 정확 복사 (r3-B5)
    assert dropped == ["ghost"]
    # source 미기록 관측 → registry desc 폴백
    store.append_observations([MetricObservation(
        metric="kr_semi_export", ts="2026-07-10", value=1.0, unit="k_usd")])
    seed2 = {"required_inputs": [{"metric": "kr_semi_export", "max_age_days": 45,
                                  "min_count": 1}]}
    kms2, _ = resolve_key_metrics(["kr_semi_export"], seed2, store)
    assert "수출" in kms2[0].source                            # 폴백 표시 (registry desc)


def test_resolve_key_metrics_ambiguous_group_fail_closed(tmp_path):
    store = SectorStore(tmp_path / "s")
    store.append_observations([
        MetricObservation(metric="hyperscaler_capex", ts="2026-03-31", value=1.0,
                          unit="usd_b", meta={"token": "MSFT", "item": "MSFT"}),
        MetricObservation(metric="hyperscaler_capex", ts="2026-06-30", value=2.0,
                          unit="usd_b", meta={"token": "META", "item": "META"})])
    seed = {"required_inputs": [{"metric": "hyperscaler_capex", "max_age_days": 120}]}
    kms, dropped = resolve_key_metrics(["hyperscaler_capex"], seed, store)
    assert kms == [] and "hyperscaler_capex" in dropped        # 다중 그룹·필터 없음 → fail-closed
    seed2 = {"required_inputs": [{"metric": "hyperscaler_capex", "max_age_days": 120,
                                  "meta_filter": {"token": "MSFT"}}]}
    kms2, dropped2 = resolve_key_metrics(["hyperscaler_capex"], seed2, store)
    assert len(kms2) == 1 and kms2[0].value == 1.0 and dropped2 == []  # 그룹 고정 → 해소


def test_resolve_key_metrics_duplicate_metric_first_wins(tmp_path):  # 2부 T5 보정
    """같은 metric이 required_inputs에 두 번(HBM/DRAM) 나오면 첫 항목 필터가 이긴다."""
    store = SectorStore(tmp_path / "s")
    store.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=1.0,
                          unit="USD/GB", meta={"category": "HBM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.09,
                          unit="USD/GB", meta={"category": "DRAM"})])
    seed = {"required_inputs": [
        {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
         "meta_filter": {"category": "HBM"}},
        {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
         "meta_filter": {"category": "DRAM"}},
    ]}
    kms, dropped = resolve_key_metrics(["memory_price_usd_per_gb"], seed, store)
    assert len(kms) == 1 and kms[0].value == 1.0 and kms[0].meta["category"] == "HBM"
    assert dropped == []
