"""테제(Thesis) 교차 verifier — fail-closed (2부 T4).

updater와 다른 provider(gpt-mini, ROLE_MAP["thesis_verifier"])로 statement를
재판정한다. LLM 예외·비정형 출력·판정 누락/중복/미지 ID는 전부
`VerificationFailed`로 fail-closed — 판정 불능이면 절대 통과시키지 않는다
(호출측이 revision 전체를 skip하는 게 계약, B1).

관련성 없음(relevant=False) 또는 방향 중립(direction=="neutral")인
statement는 드롭한다(r2-B2 — neutral은 저장 불가). assessment
(strengthening/weakening/mixed) 집계는 호출측(T5)의 몫이며, 이 모듈은
statement별 방향을 Literal 그대로 반환한다(bool로 붕괴시키지 않는다).
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from sector.thesis_contracts import Statement


class VerificationFailed(Exception):
    """판정 불능(LLM 예외·비정형 출력·행 누락/중복/미지 ID) — 호출측이 revision 전체 skip."""


class _VerifyRow(BaseModel):
    statement_id: str
    card_id: str
    supported: bool
    why: str = ""


class _VerifyRelation(BaseModel):
    statement_id: str
    relevant: bool
    direction: Literal["supports", "contradicts", "neutral"]


class _VerifyOut(BaseModel):
    rows: list[_VerifyRow]
    relations: list[_VerifyRelation]


_INSTRUCTIONS = (
    "너는 금융/반도체 섹터 테제(가설) 근거를 기각 방향으로 재검증하는 "
    "교차 심사자다. 판단이 애매하면 반드시 기각(supported=false, "
    "relevant=false 또는 direction=neutral) 쪽으로 판정하라 — 확신이 "
    "없으면 통과시키지 않는다. 모든 입력 근거·statement에 대해 빠짐없이 "
    "정확히 1개씩 판정을 반환하라(누락·중복 금지)."
)


def _build_prompt(seed_claim: str, stmts: list[Statement]) -> str:
    """검증 대상을 사람이 읽기 쉬운 텍스트 + JSON evidence 목록으로 함께 낸다.

    JSON 부분의 (statement_id, card_id, quote) 키는 verifier 응답이 참조할 정확한
    판정 단위(_VerifyRow/_VerifyRelation)와 1:1로 대응시키기 위한 형식 — 2부 T5
    fake verifier가 이 JSON 키를 정규식으로 파싱해 판정 행을 만든다(계약).
    """
    lines = [f"[핵심 주장(seed claim)] {seed_claim}", "", "[검증 대상 statement 목록]"]
    for st in stmts:
        lines.append(f"- statement_id={st.statement_id}")
        lines.append(f"  text: {st.text}")
        evidence_rows = [
            {"statement_id": st.statement_id, "card_id": ev.card_id, "quote": ev.quote}
            for ev in st.supporting
        ]
        lines.append("  evidence: " + json.dumps(evidence_rows, ensure_ascii=False))
    lines.append("")
    lines.append(
        "각 statement의 각 근거(card_id)마다 rows에 정확히 1행씩: "
        "그 근거가 statement.text를 실제로 뒷받침하는지(supported), 아니면 "
        "무관/과장/추론 비약인지(supported=false, why에 사유). "
        "각 statement마다 relations에 정확히 1행씩: 이 statement가 "
        "[핵심 주장]과 관련 있는지(relevant), 관련 있다면 핵심 주장을 "
        "강화(supports)/약화(contradicts)하는지, 방향이 불명확하거나 "
        "무관하면 direction=neutral."
    )
    return "\n".join(lines)


def _validate_exactness(
    out: _VerifyOut, expected_pairs: set[tuple[str, str]], expected_sids: set[str]
) -> tuple[dict[tuple[str, str], _VerifyRow], dict[str, _VerifyRelation]]:
    row_by_pair: dict[tuple[str, str], _VerifyRow] = {}
    for row in out.rows:
        key = (row.statement_id, row.card_id)
        if key in row_by_pair:
            raise VerificationFailed(f"중복 판정 행: {key}")
        if key not in expected_pairs:
            raise VerificationFailed(f"미지의 (statement_id, card_id) 판정 행: {key}")
        row_by_pair[key] = row
    if row_by_pair.keys() != expected_pairs:
        missing = expected_pairs - row_by_pair.keys()
        raise VerificationFailed(f"판정 누락 행: {missing}")

    relation_by_sid: dict[str, _VerifyRelation] = {}
    for rel in out.relations:
        if rel.statement_id in relation_by_sid:
            raise VerificationFailed(f"중복 relation: {rel.statement_id}")
        if rel.statement_id not in expected_sids:
            raise VerificationFailed(f"미지의 statement_id relation: {rel.statement_id}")
        relation_by_sid[rel.statement_id] = rel
    if relation_by_sid.keys() != expected_sids:
        missing = expected_sids - relation_by_sid.keys()
        raise VerificationFailed(f"relation 누락: {missing}")

    return row_by_pair, relation_by_sid


async def verify_statements(
    stmts: list[Statement], seed_claim: str, role
) -> tuple[list[Statement], dict[str, Literal["supports", "contradicts"]], list[str]]:
    """statement별 근거 기각·관련성·방향을 교차 provider로 재판정한다.

    반환: (잔여 statements, {statement_id: "supports"|"contradicts"}(잔여분만),
    제거 사유 목록). 실패(LLM 예외·비정형 출력·행 불일치)는 전부
    VerificationFailed로 fail-closed — 호출측이 revision 전체를 skip한다.
    """
    if not stmts:
        return [], {}, []

    expected_pairs = {(st.statement_id, ev.card_id) for st in stmts for ev in st.supporting}
    expected_sids = {st.statement_id for st in stmts}
    prompt = _build_prompt(seed_claim, stmts)

    try:
        out = await role.run(prompt, instructions=_INSTRUCTIONS, response_format=_VerifyOut)
        row_by_pair, relation_by_sid = _validate_exactness(out, expected_pairs, expected_sids)
    except VerificationFailed:
        raise
    except Exception as exc:  # noqa: BLE001 — fail-closed: 판정 불능이면 절대 통과 안 시킴
        raise VerificationFailed(f"검증 실패(판정 불능, fail-closed): {exc}") from exc

    kept: list[Statement] = []
    directions: dict[str, Literal["supports", "contradicts"]] = {}
    reasons: list[str] = []

    for st in stmts:
        rel = relation_by_sid[st.statement_id]
        if not rel.relevant:
            reasons.append(f"{st.statement_id}: 핵심 주장과 무관 판정으로 제외")
            continue
        if rel.direction == "neutral":
            reasons.append(f"{st.statement_id}: 방향 중립(neutral) 판정 — 저장 불가로 제외")
            continue
        new_supporting = []
        for ev in st.supporting:
            row = row_by_pair[(st.statement_id, ev.card_id)]
            if row.supported:
                new_supporting.append(ev)
            else:
                reasons.append(f"{st.statement_id}: 근거 {ev.card_id} 기각 — {row.why}")
        kept.append(st.model_copy(update={"supporting": new_supporting}))
        directions[st.statement_id] = rel.direction

    return kept, directions, reasons
