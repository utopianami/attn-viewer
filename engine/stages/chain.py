"""ChainPacket 합성 스테이지 — 사건→메커니즘→edge 인과 사슬 (3부 T5, VERIFY 이전).

LLM은 사건·메커니즘·edge·인용 ID를 "제안"할 뿐이다 — 신뢰하지 않는다. 코드가
전량 재검증한다: 미등록 edge 드롭 → 인용 ID 실존 대조(미실존 드롭) → supporting·
metric이 모두 비면 observed→inference 강등 → thesis_relation의 미주입 revision
드롭 → edge_id는 드롭이 끝난 뒤 코드가 e0, e1, ... 순번을 부여한다.

never-raise 계약: LLM 호출 실패("llm_error")·후속 처리 실패("invalid_output")·
전 edge 드롭("all_edges_dropped")은 (None, 사유)로 무음 없이 표식한다(B5).
REFLECT 라운드 재생성은 하지 않는다 — 체인은 사건-기제 서술이고 재조사는 근거
보강이라(판정 3), meta.round는 재생성 없이 "생성 시점 round_"을 그대로 기록한다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from contracts import (
    CHAIN_EDGES,
    ChainEdge,
    ChainPacket,
    ClaimTable,
    EnvelopeMeta,
    PlanPacket,
    RaPacket,
    ThesisRelation,
)
from providers import Role
from stages.thesis_context import ThesisPick

# ---- LLM 제안 구조화 출력 (검증은 전부 코드 — 이 스키마를 신뢰하지 않는다) --------


class _ChainOutEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge: str
    kind: Literal["observed", "inference"]
    supporting_card_ids: list[str] = []
    metric_fact_ids: list[str] = []
    contradicting_card_ids: list[str] = []


class _ChainOutRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thesis_revision_id: str
    relation: Literal["supports", "contradicts"]


class _ChainOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: str
    mechanism: str
    verdict: str = ""
    edges: list[_ChainOutEdge] = []
    thesis_relation: list[_ChainOutRelation] = []


_INSTR = (
    "너는 금융/반도체 섹터의 사건→메커니즘→인과 edge를 제안하는 애널리스트다. "
    "edge는 반드시 아래 열거된 CHAIN_EDGES 중 하나를 그대로 써라(새 조합을 지어내지 "
    "마라). kind는 'observed'(제공된 카드·지표로 직접 관찰됨) 또는 'inference'"
    "(관찰 근거 없이 추론)만 쓴다. supporting_card_ids·contradicting_card_ids는 "
    "제공된 섹터 카드 id만, metric_fact_ids는 제공된 typed_facts id만 인용하라 — "
    "없는 id를 지어내면 코드가 드롭한다. thesis_relation은 제공된 thesis의 "
    "revision_id만 참조하라."
)


def _build_prompt(plan: PlanPacket, table: ClaimTable, sector_cards: list,
                   ra: RaPacket, thesis_picks: list[ThesisPick]) -> str:
    lines = [f"[질문] {plan.standalone_question or plan.original_question}"]

    lines.append("[claims]")
    for c in table.claims:
        lines.append(f"- {c.id} ({c.source}): {c.text}")

    lines.append("[sector_cards]")
    for card in sector_cards:
        lines.append(f"- {card.id}: {card.title} | {card.interpreted_signal}")

    lines.append("[typed_facts]")
    for f in table.typed_facts:
        lines.append(f"- {f.id}: {f.label}")

    lines.append("[thesis]")
    for p in thesis_picks:
        lines.append(f"- {p.rev.revision_id}: {p.rev.claim}")

    lines.append("[CHAIN_EDGES] " + ", ".join(CHAIN_EDGES))
    lines.append(
        "[kind 정의] observed=제공된 카드·지표로 직접 관찰됨 / "
        "inference=관찰 근거 없이 추론"
    )
    return "\n".join(lines)


def typed_fact_snapshot(table: ClaimTable) -> dict[str, dict]:
    """체인 생성 시점 전체 TypedFact 스냅샷 (r2-7 — eval resolver의 정확 역참조원).

    r3-4: dict 조립의 조용한 덮어쓰기 금지 — 중복 fact id는 상류 fact 조립
    버그이자 resolver 유일 해소 전제의 붕괴라, 방출 시점에 ValueError로 드러낸다
    (never-raise 계약의 명시적 예외 — 측정 무결성).
    """
    ids = [f.id for f in table.typed_facts]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate typed_fact id(s): {dupes}")
    return {
        f.id: {"label": f.label, "value": f.value, "unit": f.unit,
               "source": f.source, "metric": f.metric, "period": f.period}
        for f in table.typed_facts
    }


async def run_chain(plan: PlanPacket, table: ClaimTable, sector_cards: list,
                    ra: RaPacket, thesis_picks: list[ThesisPick], *,
                    round_: int = 0, role=None,
                    overrides: dict | None = None) -> tuple[ChainPacket | None, str]:
    """ChainPacket 합성 — 반환 2번째 원소가 강등 사유 ("" = 정상)."""

    try:
        chain_role = role or Role("chain_synth", overrides)
        prompt = _build_prompt(plan, table, sector_cards, ra, thesis_picks)
        out: _ChainOut = await chain_role.run(
            prompt, instructions=_INSTR, response_format=_ChainOut)
    except Exception:  # noqa: BLE001 — never-raise, LLM 호출단 실패
        return None, "llm_error"

    try:
        card_ids = {c.id for c in sector_cards}
        news_ids = {n.id for items in ra.curated_items().values() for n in items}
        citation_ids = card_ids | news_ids
        fact_ids = {f.id for f in table.typed_facts}
        thesis_ids = {p.rev.revision_id for p in thesis_picks}

        chain_edges: list[ChainEdge] = []
        for e in out.edges:
            if e.edge not in CHAIN_EDGES:
                continue  # 미등록 edge 드롭 (곱집합 금지, B4)
            supporting = [cid for cid in e.supporting_card_ids if cid in citation_ids]
            contradicting = [cid for cid in e.contradicting_card_ids if cid in citation_ids]
            metrics = [fid for fid in e.metric_fact_ids if fid in fact_ids]
            kind = e.kind if (supporting or metrics) else "inference"
            chain_edges.append(ChainEdge(
                edge_id=f"e{len(chain_edges)}", edge=e.edge, kind=kind,
                supporting_card_ids=supporting, metric_fact_ids=metrics,
                contradicting_card_ids=contradicting))

        if not chain_edges:
            return None, "all_edges_dropped"

        relations = [
            ThesisRelation(thesis_revision_id=r.thesis_revision_id, relation=r.relation)
            for r in out.thesis_relation if r.thesis_revision_id in thesis_ids
        ]

        packet = ChainPacket(
            meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref()),
            event=out.event, mechanism=out.mechanism, verdict=out.verdict,
            edges=chain_edges, thesis_relation=relations)
        return packet, ""
    except Exception:  # noqa: BLE001 — never-raise, 후속 처리단 실패
        return None, "invalid_output"
