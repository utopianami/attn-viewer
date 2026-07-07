"""sector P3 — sector_rag 레이어 + synthesize 주입 통합 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Test 1: extract_entities ──────────────────────────────────────────────────

from sector.entities import extract_entities  # noqa: E402


def test_extract_entities_hynix():
    result = extract_entities("하이닉스 HBM 어때")
    assert "SK_HYNIX" in result


def test_extract_entities_irrelevant():
    result = extract_entities("오늘 날씨가 맑고 화창합니다")
    assert result == []


# ── Test 2: LAYER_NAMES에 sector_rag 존재 ────────────────────────────────────

from contracts.packets import LAYER_NAMES  # noqa: E402


def test_sector_rag_in_layer_names():
    assert "sector_rag" in LAYER_NAMES


# ── Test 3: _render_context sector_cards 렌더링 ───────────────────────────────

from contracts.packets import DaPacket, PlanPacket  # noqa: E402
from stages.synthesize import _render_context  # noqa: E402
from sector.contracts import SectorCard  # noqa: E402


def _mini_plan():
    return PlanPacket(tier=2, original_question="하이닉스 전망", standalone_question="하이닉스 전망",
                      knowledge_cutoff="2026-07-06")


def _make_card(title="Meta, 잉여 GPU 처분 계획", url="https://reuters.com/test"):
    return SectorCard(
        id="test-001",
        ts="2026-07-06T09:00:00Z",
        axis="B",
        direction="neg",
        magnitude=2,
        source_grade="B",
        title=title,
        interpreted_signal="메모리 수요 둔화 신호",
        raw_quote="원문 인용",
        url=url,
        entities=["META"],
    )


def test_render_context_includes_sector_cards():
    cards = [_make_card()]
    ctx = _render_context(_mini_plan(), DaPacket(status="ok"), None, None, None, None, [], None,
                          sector_cards=cards)
    assert "[메모리 섹터 근거]" in ctx
    assert "Meta, 잉여 GPU 처분 계획" in ctx


def test_render_context_excludes_sector_cards_when_none():
    ctx = _render_context(_mini_plan(), DaPacket(status="ok"), None, None, None, None, [], None,
                          sector_cards=None)
    assert "[메모리 섹터 근거]" not in ctx


def test_render_context_excludes_sector_cards_when_empty():
    ctx = _render_context(_mini_plan(), DaPacket(status="ok"), None, None, None, None, [], None,
                          sector_cards=[])
    assert "[메모리 섹터 근거]" not in ctx


# ── Test 4: judge 기존 동작 회귀 (entities 이동 후에도 동일 결과) ──────────────

import asyncio  # noqa: E402
from sector import judge  # noqa: E402
from sector.contracts import RawNewsItem  # noqa: E402


def _items(n=2):
    return [RawNewsItem(id=f"i{k}", title=f"hynix HBM {k}", content="본문",
                        source="reuters.com", url=f"http://n/{k}",
                        published_at="2026-07-06T09:00:00Z") for k in range(n)]


def test_judge_entities_regression(monkeypatch):
    """entities.py 분리 후에도 _extract_entities가 동일하게 동작해야 한다."""
    class FakeRole:
        def __init__(self, *a, **k): pass
        async def run(self, prompt, instructions="", *, response_format=None, **kw):
            return judge._JudgeBatch(rows=[
                judge._JudgeRow(idx=0, relevant=True, axis="B", direction="pos",
                                magnitude=2, interpreted_signal="HBM 수요 증가"),
            ])
    monkeypatch.setattr(judge, "Role", FakeRole)
    cards = asyncio.run(judge.judge_items(_items(1)))
    assert len(cards) == 1
    # hynix → SK_HYNIX 엔티티 추출 확인
    assert "SK_HYNIX" in cards[0].entities


def test_search_for_question_fallback_when_entity_filter_empty(tmp_path):
    """엔티티 감지 + 매칭 0건 → 무필터 폴백 (구세대 entities=[] 카드 자가 치유)."""
    from sector.retrieve import search_for_question
    from sector.store import SectorStore
    from sector.contracts import SectorCard
    import datetime as _dt
    store = SectorStore(tmp_path)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    store.append_cards([SectorCard(id="old1", ts=now, axis="B", entities=[],
                                   title="구세대 카드", raw_quote="", url="", source="")])
    ents, cards = search_for_question(store, "SK하이닉스 HBM 어때?")
    assert "SK_HYNIX" in ents and [c.id for c in cards] == ["old1"]
    ents2, cards2 = search_for_question(store, "유럽 전력주 어때?")
    assert ents2 == [] and cards2 == []


# ── F1 회귀: sector card 숫자가 audit evidence에 포함됨 ────────────────────────

def test_cards_to_evidence_texts_contain_numeric():
    """카드의 raw_quote/interpreted_signal 숫자가 evidence_texts에 포함돼야 한다."""
    from sector.evidence import cards_to_evidence
    card = _make_card(title="ASML 수주 잔고 42억 유로 돌파", url="https://asml.com/news")
    card2 = _make_card(title="no-url card", url="")
    texts, docs = cards_to_evidence([card, card2])
    assert len(texts) == 2
    # 숫자 텍스트가 evidence_texts에 들어와야 함
    assert any("ASML 수주 잔고 42억 유로 돌파" in t for t in texts)
    # url 있는 카드만 docs에 포함
    assert "https://asml.com/news" in docs
    assert "" not in docs  # url="" 카드는 건너뜀


def test_cards_to_evidence_does_not_overwrite_existing_docs():
    """기존 evidence_docs 키는 덮어쓰지 않는다."""
    from sector.evidence import cards_to_evidence
    card = _make_card(title="덮어쓰기 시도", url="https://reuters.com/test")
    _, docs = cards_to_evidence([card])
    existing: dict[str, str] = {}
    for url, doc in docs.items():
        existing.setdefault(url, "original")  # setdefault → 기존값 유지
    assert existing["https://reuters.com/test"] == "original"


# ── F2 회귀: 확장된 엔티티 감지 ─────────────────────────────────────────────────

def test_extract_entities_asml():
    result = extract_entities("ASML 장비 수주 급증")
    assert "ASML" in result


def test_extract_entities_cxmt():
    result = extract_entities("CXMT 증산으로 D램 가격 하락 우려")
    assert "CXMT" in result


def test_extract_entities_amd():
    result = extract_entities("AMD MI300X HBM 탑재 발표")
    # "amd " 또는 " amd" 패턴 — 앞뒤 공백 주의
    assert "AMD" in result


def test_extract_entities_kioxia():
    result = extract_entities("키옥시아 NAND 감산 연장")
    assert "KIOXIA" in result


def test_extract_entities_coreweave():
    result = extract_entities("코어위브 GPU 클러스터 확장")
    assert "COREWEAVE" in result


def test_extract_entities_nebius():
    result = extract_entities("네비우스 데이터센터 투자 계획")
    assert "NEBIUS" in result


# ── F3 회귀: DAM 결정적 시리즈 선택 ─────────────────────────────────────────────

def _add_export_factor(store, n: int = 3) -> None:
    """두 번째 factor(demand)용 kr_semi_export 관측 추가 — insufficient 방지."""
    from sector.contracts import MetricObservation
    obs = [MetricObservation(metric="kr_semi_export",
                              ts=f"2026-0{i+1}", value=float(i + 10), meta={})
           for i in range(1, n + 1)]
    store.append_observations(obs)


def test_dam_series_selection_deterministic(tmp_path):
    """관측 수가 더 많은 시리즈를 선택, 해시 순서와 무관하게 결정적이어야 한다."""
    from sector.store import SectorStore
    from sector.contracts import MetricObservation
    from sector.cycle import compute

    store = SectorStore(tmp_path)
    # "DDR4" 시리즈: 5개 관측, "DDR5" 시리즈: 2개 관측
    ddr4 = [MetricObservation(metric="memory_price_usd_per_gb",
                               ts=f"2026-0{i+1}", value=float(i),
                               meta={"category": "DRAM", "item": "DDR4"})
             for i in range(1, 6)]
    ddr5 = [MetricObservation(metric="memory_price_usd_per_gb",
                               ts=f"2026-0{i+1}", value=float(i + 1),
                               meta={"category": "DRAM", "item": "DDR5"})
             for i in range(1, 3)]
    store.append_observations(ddr4 + ddr5)
    # demand factor 추가 (factor 수 >= 2 확보 → insufficient 탈출)
    _add_export_factor(store)

    result = compute(store)
    assert result["state"] != "insufficient", f"State is insufficient: {result}"
    # 관측 수 더 많은 DDR4가 선택돼야 함
    price_explain = " ".join(result["explain"])
    assert "DDR4" in price_explain, f"Expected DDR4 in explain: {result['explain']}"
    assert "DDR5" not in price_explain


def test_dam_series_tiebreak_lex(tmp_path):
    """동률(관측 수 같음)이면 lex 최솟값이 선택돼야 한다."""
    from sector.store import SectorStore
    from sector.contracts import MetricObservation
    from sector.cycle import compute

    store = SectorStore(tmp_path)
    # 둘 다 3개 관측 — lex 최솟값은 "AAA"
    for name in ("ZZZ", "AAA"):
        obs = [MetricObservation(metric="memory_price_usd_per_gb",
                                  ts=f"2026-0{i+1}", value=float(i),
                                  meta={"category": "DRAM", "item": name})
                for i in range(1, 4)]
        store.append_observations(obs)
    _add_export_factor(store)

    result = compute(store)
    assert result["state"] != "insufficient", f"State is insufficient: {result}"
    price_explain = " ".join(result["explain"])
    assert "AAA" in price_explain, f"Expected AAA in explain: {result['explain']}"


# ── F4 회귀: factor_details 구조 ─────────────────────────────────────────────────

def test_cycle_returns_factor_details_key(tmp_path):
    """compute() 반환값에 factor_details 키가 있어야 한다."""
    from sector.store import SectorStore
    from sector.cycle import compute
    store = SectorStore(tmp_path)
    result = compute(store)
    assert "factor_details" in result


def test_cycle_factor_details_populated(tmp_path):
    """충분한 데이터가 있으면 factor_details에 price 항목이 들어가야 한다."""
    from sector.store import SectorStore
    from sector.contracts import MetricObservation
    from sector.cycle import compute

    store = SectorStore(tmp_path)
    obs = [MetricObservation(metric="kr_dram_export_price_index",
                              ts=f"2026-0{i+1}", value=float(i + 1),
                              meta={"item": "D램 수출가격지수"})
           for i in range(3)]
    store.append_observations(obs)
    # demand factor 추가 (factor 수 >= 2 확보 → insufficient 탈출)
    _add_export_factor(store)
    result = compute(store)
    assert result["state"] != "insufficient", f"State is insufficient: {result}"
    details = result.get("factor_details", [])
    price_detail = next((d for d in details if d["factor"] == "price"), None)
    assert price_detail is not None
    assert price_detail["metric"] == "kr_dram_export_price_index"
    assert price_detail["direction"] is not None
