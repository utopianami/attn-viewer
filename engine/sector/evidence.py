"""sector card → audit 증거 변환 헬퍼 (F1)."""
from __future__ import annotations

from sector.contracts import SectorCard


def cards_to_evidence(
    cards: list[SectorCard],
) -> tuple[list[str], dict[str, str]]:
    """SectorCard 목록을 audit 증거 구조체로 변환한다.

    Returns:
        texts: run_audit의 evidence_texts에 extend할 문자열 목록.
               각 카드 → "{title} — {raw_quote} {interpreted_signal}".
        docs:  run_audit의 evidence_docs에 setdefault로 머지할 url→원문 dict.
               url이 비어 있는 카드는 건너뜀. 기존 키를 덮어쓰지 않도록
               호출측에서 setdefault를 사용해야 한다.
    """
    texts: list[str] = []
    docs: dict[str, str] = {}
    for c in cards:
        texts.append(f"{c.title} — {c.raw_quote} {c.interpreted_signal}")
        if c.url:
            docs[c.url] = f"{c.title}\n{c.raw_quote}\n{c.interpreted_signal}"
    return texts, docs


def sector_typed_facts(store) -> list:
    """섹터 관측치 → TypedFact 승격 (2026-07-13 — 채팅이 카드만 쓰고 숫자를 버리던 갭).

    안전 원칙: 시리즈 규칙이 확정된 지표만 (D램 현물가 — pick_dram_series canonical).
    나머지 지표는 cycle explain 텍스트로 합성에 전달 (라벨 불명 시계열의 오병합 방지).
    """
    from contracts import TypedFact
    from sector.cycle import pick_dram_series
    facts: list = []
    try:
        dam = [o for o in store.read_metric("memory_price_usd_per_gb")
               if o.meta.get("category") == "DRAM"]
        if dam:
            item, rows = pick_dram_series(dam)
            if rows:
                last = rows[-1]
                facts.append(TypedFact(
                    id="sector:dram_price", value=round(float(last.value), 4),
                    unit=last.unit or "USD/GB", period=last.ts,
                    label=f"D램 현물가 ({item})", source="sector:stanford_dam"))
                if len(rows) >= 2 and rows[-2].value:
                    mom = (float(last.value) / float(rows[-2].value) - 1) * 100
                    facts.append(TypedFact(
                        id="sector:dram_price_mom", value=round(mom, 2), unit="percent",
                        period=f"{rows[-2].ts}→{last.ts}",
                        label="D램 현물가 변화율", source="sector:stanford_dam"))
    except Exception:
        return facts  # never-raise — 섹터 팩트 실패가 파이프라인을 못 죽임
    return facts


def cycle_context(cycle: dict) -> str:
    """cycle.compute() 결과 → 합성·감사용 텍스트 (판정 + 수치 근거)."""
    if not cycle:
        return ""
    lines = [f"[메모리 섹터 사이클 판정] {str(cycle.get('state', '?')).upper()} "
             f"(점수 {cycle.get('score')}) — 자동 수집 지표 기반"]
    lines += [f"- {e}" for e in (cycle.get("explain") or [])[:4]]
    return "\n".join(lines)
