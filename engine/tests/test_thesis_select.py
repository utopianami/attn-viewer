import datetime as dt

from sector.contracts import MetricObservation
from sector.queryplan import SectorQueryPlan, build_rule_plan
from sector.store import SectorStore
from sector.thesis_contracts import RequiredInput, Selectors
from sector.thesis_store import ThesisStore
from stages.thesis_context import score_thesis, select_from_revisions, select_theses
from tests.test_thesis_contracts import make_rev

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)


def _store(tmp_path):
    s = SectorStore(tmp_path / "s")
    s.append_observations([MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    return s


def test_score_weights_deterministic_with_real_event_extraction():
    # 인위적 SectorQueryPlan이 아니라 실제 추출 경로 (r1-B4): make_rev의
    # selectors.event_types == ["supply_signal"] — "증설"이 supply_signal로 추출됨
    rp = build_rule_plan("SK하이닉스 HBM 증설에도 현물가 오를까?",
                         include_event_types=True)
    assert "SK_HYNIX" in rp.entities and "memory_price_usd_per_gb" in rp.metrics
    assert "supply_signal" in rp.event_types
    assert score_thesis(rp, make_rev()) == 4          # 1×2 + 1×1 + 1×1 — 3항 전부 라이브
    assert score_thesis(SectorQueryPlan(), make_rev()) == 0
    assert score_thesis(SectorQueryPlan(entities=["MICRON"]), make_rev()) == 0


def test_select_excludes_zero_and_stale_ranks_by_priority(tmp_path):
    store = _store(tmp_path)
    rp = SectorQueryPlan(entities=["SK_HYNIX"], metrics=["memory_price_usd_per_gb"])
    r_hit = make_rev()                                 # score 3, fresh
    r_hit2 = make_rev(id="memory-price-cycle", priority=2,
                      revision_id="memory-price-cycle@2026-07-21T00:00:00")  # 동점 — priority 뒤
    r_zero = make_rev(id="nand-decoupling",
                      revision_id="nand-decoupling@2026-07-21T00:00:00",
                      selectors=Selectors(entities=["KIOXIA"], metrics=[],
                                          segments=["nand"], event_types=[]))
    r_stale = make_rev(id="china-competition-risk",
                       revision_id="china-competition-risk@2026-07-21T00:00:00",
                       required_inputs=[RequiredInput(metric="kr_semi_export",
                                                      max_age_days=30)])  # 관측 없음 → stale
    picks = select_from_revisions(rp, [r_stale, r_hit2, r_zero, r_hit], store, NOW)
    assert [p.rev.id for p in picks] == ["hbm-tightness", "memory-price-cycle"]
    assert picks[0].freshness == "fresh" and picks[0].score == 3
    assert picks[0].rev.revision_id == "hbm-tightness@2026-07-21T00:00:00"


def test_select_caps_top3(tmp_path):
    store = _store(tmp_path)
    rp = SectorQueryPlan(entities=["SK_HYNIX"])
    revs = [make_rev(id=f"t{i}", revision_id=f"t{i}@2026-07-21T00:00:00", priority=i)
            for i in range(5)]
    assert len(select_from_revisions(rp, revs, store, NOW)) == 3


def test_select_theses_uses_rule_plan_not_llm(tmp_path):
    store = _store(tmp_path)
    ts = ThesisStore(tmp_path / "s")
    ts.append(make_rev())
    picks = select_theses("SK하이닉스 HBM 현물가 흐름 어때?", ts, store, NOW)
    assert [p.rev.id for p in picks] == ["hbm-tightness"]
    assert select_theses("오늘 날씨 어때?", ts, store, NOW) == []   # 0점 전원 제외
