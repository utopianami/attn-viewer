"""심화(규칙·과거사례 대조 논증, CLI) + 합성(claims만 — 결론은 report_assemble 코드가).

LLM은 ID/수치 '선언'만 하고 코드가 hydrate·검증·as_of 파생(날조 차단, 스펙 v3).
과거사례(cases)는 casemem 질의 결과(CaseMatch dump) — 실존 episode_id로만
precedent_grounded=True (Plan4-c)."""
from __future__ import annotations

import time

from pydantic import BaseModel

from sector.report_contracts import (
    Anchor, NumericFact, ReportClaim, StageIO, StageResult,
)


class _ClaimRow(BaseModel):
    title: str
    trigger: str = ""
    mechanism: str = ""
    confidence: str = "낮"
    counter: str = ""
    stance: str = ""
    load_bearing: bool = False
    evidence_ids: list[str] = []
    anchor_refs: list[str] = []
    numeric_facts: list[dict] = []      # {anchor_id, value}
    precedent: str = ""
    precedent_case_ids: list[str] = []  # casemem episode_id 선언 — 코드가 실존 검증
    matched_rules: list[str] = []


class _ClaimsOut(BaseModel):
    claims: list[_ClaimRow]


def _fmt_anchor(a: Anchor) -> str:
    d = f" (Δ{a.delta_pct:+.1f}%)" if a.delta_pct is not None else ""
    return f"{a.anchor_id}: {a.value}{a.unit}{d} @{a.as_of} [{a.source}]"


def _fmt_rule(r: dict) -> str:
    return f"{r['slug']} (score {r['score']}, 키 {r['matched_keys']}): {r['connection']}"


def _fmt_case(c: dict) -> str:
    ev = " / ".join(f"{e.get('source', '')}: {e.get('quote', '')}"
                    for e in (c.get("evidence") or [])[:3])
    nxt = ", ".join(c.get("next_phase_labels") or []) or "?"
    return (f"{c.get('episode_id')} (국면 {c.get('matched_phase_order')}, "
            f"score {c.get('score')}) → 다음 국면 예측: {nxt}"
            + (f" · 근거: {ev}" if ev else ""))


async def deepen(clusters, rules, anchors, *, role,
                 cases: list[dict] | None = None) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="deepen", label="심화 — 규칙·과거사례 대조", in_count=len(clusters))
    cases = cases or []
    try:
        parts = ["[관측 이벤트 — 근거 발췌 포함]"]
        for c in clusters:
            parts.append(f"- {c.title} ({c.axis}/{c.direction}, 출처 {len(c.members)}건)")
            for m in c.members[:4]:
                ex = f": {m.excerpt[:160]}" if m.excerpt else ""
                parts.append(f"    · [{m.id}] {m.title}{ex}")
        parts.append("\n[수치 anchor — 인용만, 산술 금지]")
        parts += [_fmt_anchor(a) for a in anchors]
        parts.append("\n[매칭 규칙 — 절차 참고용, 사실 인용 금지]")
        parts += [_fmt_rule(r) for r in rules]
        if cases:
            parts.append("\n[과거사례 — 현재 관측이 어느 국면인지 대조, 다음 국면 예측 참고]")
            parts += [_fmt_case(c) for c in cases]
        parts.append("\n나이브 단정 기각. 규칙·과거사례에 비추어 여러 관측을 연결한 논증을 서술하라.")
        text = await role.run("\n".join(parts),
                              instructions="메모리 반도체 시황 분석가.", effort="high")
        io.out_count = 1
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=str(text), io=io, error=None)
    except Exception as exc:  # noqa: BLE001
        io.note = f"심화 실패: {exc}"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output="", io=io, error=str(exc))


def _hydrate(ids: list[str], pool: dict, io: StageIO) -> list:
    out = []
    for i in ids:
        if i in pool:
            out.append(pool[i])
        else:
            io.dropped.append({"title": i, "reason": "미존재 evidence id(날조 의심)"})
    return out


async def synthesize_claims(deepen_text, clusters, anchors, rules, *, role,
                            cases: list[dict] | None = None) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="synth", label="합성 — 주장", in_count=len(clusters))
    cases = cases or []
    try:
        pool = {m.id: m for c in clusters for m in c.members}
        anchor_ids = {a.anchor_id for a in anchors}
        case_ids = {str(c.get("episode_id")) for c in cases if c.get("episode_id")}
        ev_lines = [f"- {i}: {m.title}" + (f" — {m.excerpt[:120]}" if m.excerpt else "")
                    for i, m in sorted(pool.items())]
        anchor_lines = [_fmt_anchor(a) for a in anchors]
        prompt = (f"[논증]\n{deepen_text}\n\n[근거 풀 — id: 제목/발췌]\n"
                  + "\n".join(ev_lines)
                  + "\n[anchor 풀]\n" + "\n".join(anchor_lines)
                  + f"\n[과거사례 id 풀]\n{sorted(case_ids)}\n\n"
                  "주장 카드만 생성(종합/최종의견 금지). 규칙 대조에서 나온 주장만. "
                  "evidence_ids는 그 주장을 실제로 지지하는 근거만, "
                  "anchor_refs/numeric_facts/precedent_case_ids는 반드시 위 풀의 id만. "
                  "수치를 본문(title/mechanism/stance 등)에 쓰면 반드시 numeric_facts로도 선언하라.")
        res = await role.run(prompt, instructions="주장 합성기.",
                             response_format=_ClaimsOut, effort="high")
        claims: list[ReportClaim] = []
        for i, r in enumerate(res.claims):
            refs = _hydrate(r.evidence_ids, pool, io)
            # 숫자 선언은 전부 보존 — 미존재 anchor_id도 검증(T8)이 reject하도록
            # 여기서 거르지 않는다(거르면 reject 분기가 죽음 — codex plan r2 NB3)
            nf = [NumericFact(**d) for d in r.numeric_facts
                  if isinstance(d, dict) and d.get("anchor_id") and "value" in d]
            valid_cases = []
            for cid in r.precedent_case_ids:
                if cid in case_ids:
                    valid_cases.append(cid)
                else:
                    io.dropped.append({"title": cid, "reason": "미존재 case id(날조 의심)"})
            claims.append(ReportClaim(
                claim_id=f"c{i}", title=r.title, trigger=r.trigger, mechanism=r.mechanism,
                confidence=r.confidence if r.confidence in ("낮", "중", "높") else "낮",
                counter=r.counter, stance=r.stance, load_bearing=r.load_bearing,
                evidence_refs=refs,
                evidence=[f"{e.title} ({e.source})" if e.source else e.title for e in refs],
                anchor_refs=[a for a in r.anchor_refs if a in anchor_ids],
                numeric_facts=nf,
                precedent=r.precedent,
                precedent_grounded=bool(valid_cases),      # 실존 case로만 접지(날조 금지)
                precedent_case_ids=valid_cases,
                matched_rules=r.matched_rules, status="unverified",
                as_of=max((e.ts for e in refs if e.ts), default="")))   # 코드 파생
        io.out_count = len(claims)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=claims, io=io, error=None)
    except Exception as exc:  # noqa: BLE001
        io.note = f"합성 실패: {exc}"
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=[], io=io, error=str(exc))
