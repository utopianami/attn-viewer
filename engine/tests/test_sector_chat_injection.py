"""섹터 데이터의 채팅 주입 (2026-07-13) — 관측치 typed_fact 승격 + 사이클 컨텍스트 + 조립 병합."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import DaPacket, PlanPacket, PriceMacroPacket, RaPacket, TypedFact  # noqa: E402
from sector.evidence import cycle_context, sector_typed_facts  # noqa: E402
from sector.store import SectorStore  # noqa: E402
from stages.assemble import run_assemble  # noqa: E402


def _store_with_dram(tmp_path) -> SectorStore:
    store = SectorStore(tmp_path)
    mdir = tmp_path / "metrics"
    mdir.mkdir(exist_ok=True)
    rows = [
        {"metric": "memory_price_usd_per_gb", "ts": "2026-06", "value": 10.0,
         "unit": "USD/GB", "meta": {"item": "DRAM|DDR5 (Keepa)", "category": "DRAM"}},
        {"metric": "memory_price_usd_per_gb", "ts": "2026-07", "value": 11.0,
         "unit": "USD/GB", "meta": {"item": "DRAM|DDR5 (Keepa)", "category": "DRAM"}},
        {"metric": "memory_price_usd_per_gb", "ts": "2026-07", "value": 0.1,
         "unit": "USD/GB", "meta": {"item": "NAND|cheapest", "category": "NAND"}},
    ]
    (mdir / "memory_price_usd_per_gb.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows))
    return store


def test_sector_typed_facts_dram_canonical(tmp_path):
    facts = sector_typed_facts(_store_with_dram(tmp_path))
    by_id = {f.id: f for f in facts}
    assert by_id["sector:dram_price"].value == 11.0
    assert by_id["sector:dram_price"].unit == "USD/GB"
    assert by_id["sector:dram_price_mom"].value == 10.0  # +10%
    # NAND는 섞이면 안 됨 (category 필터)
    assert all("NAND" not in f.label for f in facts)


def test_sector_typed_facts_empty_store(tmp_path):
    assert sector_typed_facts(SectorStore(tmp_path)) == []


def test_cycle_context_format():
    txt = cycle_context({"state": "up", "score": 0.42,
                         "explain": ["price: +1.00", "demand: +0.13"]})
    assert "UP" in txt and "0.42" in txt and "price: +1.00" in txt
    assert cycle_context({}) == ""


def test_assemble_merges_extra_typed_facts():
    plan = PlanPacket(tier=2, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-13")
    extra = [TypedFact(id="sector:dram_price", value=11.0, unit="USD/GB",
                       period="2026-07", label="D램 현물가", source="sector:stanford_dam")]
    table = run_assemble(plan, DaPacket(), RaPacket(), PriceMacroPacket(),
                         extra_typed_facts=extra)
    assert any(f.id == "sector:dram_price" for f in table.typed_facts)


def test_search_for_question_topic_trigger(tmp_path, monkeypatch):
    """회사명 없는 섹터 일반 질문도 토픽 키워드로 발동한다 (2026-07-13)."""
    from sector import retrieve
    monkeypatch.setattr(retrieve, "search", lambda store, **kw: ["CARD"])
    ents, cards = retrieve.search_for_question(None, "메모리 반도체 업황 지금 어디쯤이야?")
    assert ents == ["MEMORY_SECTOR"] and cards == ["CARD"]
    ents2, cards2 = retrieve.search_for_question(None, "D램 가격 요즘 어때")
    assert ents2 == ["MEMORY_SECTOR"] and cards2
    # 섹터 무관 질문은 여전히 미발동
    ents3, cards3 = retrieve.search_for_question(None, "현대차 주가 어때?")
    assert ents3 == [] and cards3 == []
