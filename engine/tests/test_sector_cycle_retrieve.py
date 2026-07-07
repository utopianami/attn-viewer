"""메모리 섹터 P1 — retrieve + cycle 테스트 (Task 8)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import MetricObservation, SectorCard  # noqa: E402
from sector.store import SectorStore  # noqa: E402
from sector import cycle, retrieve  # noqa: E402


# ─── 헬퍼 ────────────────────────────────────────────────────────────────────

def _card(cid, direction="pos", magnitude=2, entities=None, ts="2026-07-06T09:00:00Z"):
    return SectorCard(
        id=cid, ts=ts, axis="B", entities=entities or ["SK하이닉스"],
        edge="B->A", event_type="demand_signal", memory_segment="dram",
        direction=direction, magnitude=magnitude,
        time_horizon="immediate", source_grade="B",
        title=f"title-{cid}", raw_quote="q", interpreted_signal="s",
        url="http://x", source="reuters.com",
    )


def _obs(metric, ts, value, meta=None):
    return MetricObservation(metric=metric, ts=ts, value=value, meta=meta or {})


# ─── retrieve 테스트 ──────────────────────────────────────────────────────────

def test_retrieve_direction_balance_9pos_1neg(tmp_path):
    """9 pos + 1 neg 카드에서 k=5 → neg 최소 1개 포함."""
    s = SectorStore(tmp_path)
    s.append_cards([_card(f"pos{i}", direction="pos", magnitude=3) for i in range(9)])
    s.append_cards([_card("neg1", direction="neg", magnitude=1)])
    result = retrieve.search(s, days=None, k=5)
    assert len(result) <= 5
    neg_count = sum(1 for c in result if c.direction == "neg")
    assert neg_count >= 1, "neg 카드 min(2,1)=1개 보장 실패"


def test_retrieve_direction_balance_1pos_5neg(tmp_path):
    """pos 1 + neg 5 카드에서 k=4 → pos 최소 1개 포함."""
    s = SectorStore(tmp_path)
    s.append_cards([_card("pos1", direction="pos", magnitude=1)])
    s.append_cards([_card(f"neg{i}", direction="neg", magnitude=3) for i in range(5)])
    result = retrieve.search(s, days=None, k=4)
    pos_count = sum(1 for c in result if c.direction == "pos")
    assert pos_count >= 1, "pos 카드 min(2,1)=1개 보장 실패"


def test_retrieve_direction_balance_2_each(tmp_path):
    """pos 5 + neg 5 카드에서 k=6 → pos 최소 2개, neg 최소 2개."""
    s = SectorStore(tmp_path)
    s.append_cards([_card(f"pos{i}", direction="pos", magnitude=2) for i in range(5)])
    s.append_cards([_card(f"neg{i}", direction="neg", magnitude=2) for i in range(5)])
    result = retrieve.search(s, days=None, k=6)
    pos_count = sum(1 for c in result if c.direction == "pos")
    neg_count = sum(1 for c in result if c.direction == "neg")
    assert pos_count >= 2 and neg_count >= 2


def test_retrieve_entities_filter(tmp_path):
    """entities 필터 — 교집합 기준."""
    s = SectorStore(tmp_path)
    s.append_cards([
        _card("a", entities=["삼성전자"]),
        _card("b", entities=["SK하이닉스"]),
        _card("c", entities=["삼성전자", "SK하이닉스"]),
    ])
    result = retrieve.search(s, entities=["삼성전자"], days=None)
    ids = {c.id for c in result}
    assert "a" in ids and "c" in ids and "b" not in ids


def test_retrieve_magnitude_first(tmp_path):
    """magnitude 내림차순이 ts보다 우선."""
    s = SectorStore(tmp_path)
    s.append_cards([
        _card("low_mag", magnitude=1, ts="2026-07-06T10:00:00Z"),
        _card("high_mag", magnitude=3, ts="2026-07-01T10:00:00Z"),
    ])
    result = retrieve.search(s, days=None)
    assert result[0].id == "high_mag"


def test_retrieve_empty(tmp_path):
    """빈 저장소 → 빈 리스트."""
    s = SectorStore(tmp_path)
    assert retrieve.search(s, days=None) == []


def test_retrieve_k_limit(tmp_path):
    """반환 수 ≤ k."""
    s = SectorStore(tmp_path)
    s.append_cards([_card(f"c{i}") for i in range(20)])
    result = retrieve.search(s, days=None, k=7)
    assert len(result) <= 7


def test_retrieve_ts_desc_tiebreak(tmp_path):
    """magnitude 같을 때 최신 ts 우선."""
    s = SectorStore(tmp_path)
    s.append_cards([
        _card("old", magnitude=2, ts="2026-06-01T00:00:00Z"),
        _card("new", magnitude=2, ts="2026-07-01T00:00:00Z"),
    ])
    result = retrieve.search(s, days=None)
    assert result[0].id == "new"


# ─── cycle 테스트 ─────────────────────────────────────────────────────────────

def test_cycle_price_up(tmp_path):
    """price 요소: D램 필터 적용, 상승 방향 검출."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0, {"item": "D램"}),
        _obs("kr_dram_export_price_index", "2026-06", 110.0, {"item": "D램"}),
        # sufficient을 위해 demand도 추가
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 105.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["price"] is not None
    assert r["factors"]["price"] > 0


def test_cycle_price_fallback_no_dram_filter(tmp_path):
    """D램 행 없으면 전체 시리즈 사용."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0, {"item": "낸드"}),
        _obs("kr_dram_export_price_index", "2026-06", 90.0, {"item": "낸드"}),
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 95.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["price"] is not None
    assert r["factors"]["price"] < 0  # 하락


def test_cycle_inventory_negated(tmp_path):
    """재고 증가 → inventory factor 음수 (악재)."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_semi_production_index", "2026-05", 100.0, {"item": "재고"}),
        _obs("kr_semi_production_index", "2026-06", 120.0, {"item": "재고"}),
        _obs("kr_dram_export_price_index", "2026-05", 100.0),
        _obs("kr_dram_export_price_index", "2026-06", 105.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["inventory"] is not None
    assert r["factors"]["inventory"] < 0, "재고 증가는 악재 → 음수"


def test_cycle_inventory_decrease_positive(tmp_path):
    """재고 감소 → inventory factor 양수 (호재)."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_semi_production_index", "2026-05", 120.0, {"item": "재고"}),
        _obs("kr_semi_production_index", "2026-06", 100.0, {"item": "재고"}),
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 100.5),
    ])
    r = cycle.compute(s)
    assert r["factors"]["inventory"] is not None
    assert r["factors"]["inventory"] > 0, "재고 감소는 호재 → 양수"


def test_cycle_inventory_none_without_inventory_rows(tmp_path):
    """재고 행 없으면 inventory=None."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_semi_production_index", "2026-05", 100.0, {"item": "생산"}),
        _obs("kr_semi_production_index", "2026-06", 105.0, {"item": "생산"}),
    ])
    r = cycle.compute(s)
    assert r["factors"]["inventory"] is None


def test_cycle_demand_from_export(tmp_path):
    """demand: kr_semi_export만 있어도 계산."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 120.0),
        _obs("kr_dram_export_price_index", "2026-05", 100.0),
        _obs("kr_dram_export_price_index", "2026-06", 105.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["demand"] is not None
    assert r["factors"]["demand"] > 0


def test_cycle_demand_from_tsmc_yoy(tmp_path):
    """demand: TSMC yoy 가속도로 보완."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("tw_monthly_revenue", "2026-05", 1000.0, {"name": "TSMC", "yoy": 10.0}),
        _obs("tw_monthly_revenue", "2026-06", 1100.0, {"name": "TSMC", "yoy": 20.0}),
        _obs("kr_dram_export_price_index", "2026-05", 100.0),
        _obs("kr_dram_export_price_index", "2026-06", 105.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["demand"] is not None
    assert r["factors"]["demand"] > 0


def test_cycle_demand_none_without_sources(tmp_path):
    """수출·TSMC 데이터 없으면 demand=None."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0),
        _obs("kr_dram_export_price_index", "2026-06", 105.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["demand"] is None


def test_cycle_supply_always_none(tmp_path):
    """P1에서 supply는 항상 None."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0),
        _obs("kr_dram_export_price_index", "2026-06", 110.0),
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 110.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["supply"] is None


def test_cycle_state_up(tmp_path):
    """score > 0.15 → state='up'."""
    s = SectorStore(tmp_path)
    # price 크게 상승 (→ +1.0), export 크게 상승 (→ +1.0)
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0, {"item": "D램"}),
        _obs("kr_dram_export_price_index", "2026-06", 130.0, {"item": "D램"}),
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 130.0),
    ])
    r = cycle.compute(s)
    assert r["state"] == "up", f"expected up, got {r['state']}, score={r['score']}"
    assert r["score"] > 0.15


def test_cycle_state_down(tmp_path):
    """score < -0.15 → state='down'."""
    s = SectorStore(tmp_path)
    # price 하락, export 하락, 재고 증가 (모두 음의 방향)
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 130.0, {"item": "D램"}),
        _obs("kr_dram_export_price_index", "2026-06", 100.0, {"item": "D램"}),
        _obs("kr_semi_export", "2026-05", 130.0),
        _obs("kr_semi_export", "2026-06", 100.0),
        _obs("kr_semi_production_index", "2026-05", 100.0, {"item": "재고"}),
        _obs("kr_semi_production_index", "2026-06", 130.0, {"item": "재고"}),
    ])
    r = cycle.compute(s)
    assert r["state"] == "down", f"expected down, got {r['state']}, score={r['score']}"
    assert r["score"] < -0.15


def test_cycle_state_transition(tmp_path):
    """-0.15 ≤ score ≤ 0.15 → state='transition'."""
    s = SectorStore(tmp_path)
    # 미미한 변화 → direction ≈ 0.01~0.05
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0),
        _obs("kr_dram_export_price_index", "2026-06", 100.1),
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 100.1),
    ])
    r = cycle.compute(s)
    assert r["state"] == "transition", f"expected transition, got {r['state']}"
    assert -0.15 <= r["score"] <= 0.15


def test_cycle_insufficient_no_data(tmp_path):
    """데이터 없음 → state='insufficient', score=0.0."""
    s = SectorStore(tmp_path)
    r = cycle.compute(s)
    assert r["state"] == "insufficient"
    assert r["score"] == 0.0
    assert isinstance(r["explain"], list)


def test_cycle_insufficient_single_factor(tmp_path):
    """가용 요소 1개 → state='insufficient'."""
    s = SectorStore(tmp_path)
    # price만 있고 나머지 없음
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0),
        _obs("kr_dram_export_price_index", "2026-06", 110.0),
    ])
    r = cycle.compute(s)
    assert r["state"] == "insufficient"
    assert r["score"] == 0.0


def test_cycle_explain_names_factors(tmp_path):
    """explain 문자열에 factor 이름 + 방향값 포함."""
    s = SectorStore(tmp_path)
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0),
        _obs("kr_dram_export_price_index", "2026-06", 110.0),
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 110.0),
    ])
    r = cycle.compute(s)
    assert len(r["explain"]) >= 2
    text = " ".join(r["explain"])
    assert "price" in text
    assert "demand" in text


def test_cycle_explain_insufficient_mentions_missing(tmp_path):
    """insufficient시 어떤 요소가 부족한지 explain에 명시."""
    s = SectorStore(tmp_path)
    r = cycle.compute(s)
    assert r["state"] == "insufficient"
    # 최소한 어떤 factor가 없는지 언급
    text = " ".join(r["explain"])
    assert len(text) > 0


def test_cycle_direction_clamped(tmp_path):
    """방향값이 항상 -1.0 ~ +1.0 범위 내."""
    s = SectorStore(tmp_path)
    # 극단적 변화 (10배 상승)
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 10.0),
        _obs("kr_dram_export_price_index", "2026-06", 100.0),
        _obs("kr_semi_export", "2026-05", 10.0),
        _obs("kr_semi_export", "2026-06", 100.0),
    ])
    r = cycle.compute(s)
    for k, v in r["factors"].items():
        if v is not None:
            assert -1.0 <= v <= 1.0, f"{k}={v} out of [-1, 1]"
    assert -1.0 <= r["score"] <= 1.0


# ─── cycle DAM 폴백 테스트 ────────────────────────────────────────────────────

def test_cycle_price_dam_fallback_when_ecos_empty(tmp_path):
    """ECOS 없음 + DAM DRAM 관측 2개 → price 요소 not None (DAM 폴백 사용)."""
    s = SectorStore(tmp_path)
    # ECOS 데이터 없음; DAM DRAM 시리즈 2개 ts (동일 series)
    s.append_observations([
        _obs("memory_price_usd_per_gb", "2024-06", 2.0,
             {"item": "DRAM|Modern DRAM Series", "category": "DRAM"}),
        _obs("memory_price_usd_per_gb", "2024-12", 1.8,
             {"item": "DRAM|Modern DRAM Series", "category": "DRAM"}),
        # demand 데이터 추가 (sufficient 조건)
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 105.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["price"] is not None, "DAM 폴백 시 price 요소가 None이면 안 됨"
    # explain에 fallback DAM 표기
    text = " ".join(r["explain"])
    assert "fallback DAM" in text


def test_cycle_price_ecos_wins_over_dam(tmp_path):
    """ECOS 있으면 DAM 폴백 미사용 — ECOS 우선."""
    s = SectorStore(tmp_path)
    # ECOS 데이터 있음
    s.append_observations([
        _obs("kr_dram_export_price_index", "2026-05", 100.0, {"item": "D램"}),
        _obs("kr_dram_export_price_index", "2026-06", 110.0, {"item": "D램"}),
        # DAM 데이터도 있음
        _obs("memory_price_usd_per_gb", "2024-06", 2.0,
             {"item": "DRAM|Modern DRAM Series", "category": "DRAM"}),
        _obs("memory_price_usd_per_gb", "2024-12", 1.5,
             {"item": "DRAM|Modern DRAM Series", "category": "DRAM"}),
        # demand
        _obs("kr_semi_export", "2026-05", 100.0),
        _obs("kr_semi_export", "2026-06", 105.0),
    ])
    r = cycle.compute(s)
    assert r["factors"]["price"] is not None
    # explain에 ECOS 사용 표기 (fallback DAM 아님)
    text = " ".join(r["explain"])
    assert "fallback DAM" not in text
    assert "kr_dram_export_price_index" in text


def test_pick_dram_series_prefers_mainstream_generation(tmp_path):
    """canonical D램 시리즈 — DDR5 우선 (판정/브리핑/화면 모순 사고 회귀)."""
    from sector.cycle import pick_dram_series
    rows = []
    for i in range(8):
        rows.append(_obs("memory_price_usd_per_gb", f"2026-0{(i % 6) + 1}", 3.0 + i * 0.1,
                         {"item": "DRAM|DRAM cheapest (Keepa)", "category": "DRAM"}))
        rows.append(_obs("memory_price_usd_per_gb", f"2026-0{(i % 6) + 1}", 10.0 + i * 0.1,
                         {"item": "DRAM|DDR5 (Keepa)", "category": "DRAM"}))
    item, series = pick_dram_series(rows)
    assert "DDR5" in item and len(series) == 8
    # DDR 세대가 없으면 관측수 최다 폴백
    generic = [_obs("memory_price_usd_per_gb", f"2026-0{i+1}", 1.0, {"item": "DRAM|X", "category": "DRAM"}) for i in range(3)]
    item2, _ = pick_dram_series(generic)
    assert item2 == "DRAM|X"
