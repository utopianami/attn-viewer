"""report 전용 검증 — 코드 게이트(시점·숫자 정체성) 먼저, 그 후 A1 재감사·A2 반박.

fail-closed: LLM 실패(A1·A2 모두)·근거 불충분이면 unverified(codex NB5).
A1엔 evidence excerpt·anchor 수치를 실전달(제목만 금지 — codex NB4).
숫자는 anchor 정체성(anchor_id) 대조 — 미존재 anchor 선언도 rejected(NB3). 스펙 v3."""
from __future__ import annotations

import time
from datetime import datetime

from pydantic import BaseModel

from sector.report_contracts import ClaimVerdict, StageIO, StageResult
from sector.report_input import _parse_ts

_REL_TOL = 0.001


class _Support(BaseModel):
    supported: bool = False
    reason: str = ""


def _parse_asof(s: str):
    if len(s) == 7:                      # "YYYY-MM" → 월초(보수적)
        s = s + "-01T00:00:00+00:00"
    return _parse_ts(s)


def _evidence_block(c, anchors: dict) -> str:
    """A1/A2 프롬프트용 근거 번들 — excerpt 포함(제목만 금지, codex NB4)."""
    lines = [f"[주장] {c.title}", f"[촉발] {c.trigger}", f"[논증] {c.mechanism}", "[근거]"]
    for e in c.evidence_refs:
        line = f"- {e.title}"
        if e.source:
            line += f" ({e.source})"
        if e.excerpt:
            line += f": {e.excerpt}"
        lines.append(line)
    for s in c.evidence:                 # refs 없이 문자열만 있는 경우 보강
        if not any(s.startswith(f"- {r.title}") for r in c.evidence_refs):
            lines.append(f"- {s}")
    lines.append("[수치]")
    for ar in c.anchor_refs:
        a = anchors.get(ar)
        if a:
            lines.append(f"- {a.anchor_id} = {a.value}{a.unit} @{a.as_of}")
    return "\n".join(lines)


async def verify_claims(claims, anchors, *, cutoff: datetime, verifier, cross) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="verify", label="검증 — 시점/숫자/A1/A2", in_count=len(claims))
    amap = {a.anchor_id: a for a in anchors}
    verdicts: list[ClaimVerdict] = []

    for c in claims:
        reasons: list[str] = []
        # 1) 시점(코드)
        dt = _parse_asof(c.as_of) if c.as_of else None
        if c.as_of and dt is not None and dt > cutoff:
            verdicts.append(ClaimVerdict(claim_id=c.claim_id, status="rejected",
                                         reasons=[f"시점 위반: as_of {c.as_of} > cutoff"],
                                         adjusted_confidence="낮"))
            continue
        if c.load_bearing and (not c.as_of or dt is None):
            reasons.append("as_of 없음/불파싱 — 시점 게이트 미통과(보수)")
        # 2) 숫자 정체성(코드) — 미존재 anchor 선언도 기각(NB3)
        numeric_bad = False
        for nf in c.numeric_facts:
            a = amap.get(nf.anchor_id)
            if a is None:
                reasons.append(f"숫자 anchor 미존재: {nf.anchor_id}")
                numeric_bad = True
            elif abs(nf.value - a.value) / max(abs(a.value), 1e-9) > _REL_TOL:
                reasons.append(f"숫자 불일치: {nf.anchor_id} 주장 {nf.value} ≠ anchor {a.value}")
                numeric_bad = True
        if numeric_bad:
            verdicts.append(ClaimVerdict(claim_id=c.claim_id, status="rejected",
                                         reasons=reasons, adjusted_confidence="낮"))
            continue
        # 3) A1 재감사(load-bearing만, excerpt·수치 실전달)
        status, conf = c.status, c.confidence
        if c.load_bearing and not reasons:
            try:
                r = await verifier.run(
                    "중립 재판정: 아래 주장이 제시 근거·수치로 지지되는가.\n\n"
                    + _evidence_block(c, amap),
                    response_format=_Support, effort="medium")
                if r.supported:
                    status = "verified"
                else:
                    reasons.append(f"A1 근거부족: {r.reason}")
                    status, conf = "unverified", "낮"
            except Exception as exc:  # noqa: BLE001 — fail-closed
                reasons.append(f"A1 실패(보수): {exc}")
                status, conf = "unverified", "낮"
        elif reasons:
            status, conf = "unverified", "낮"
        # 4) A2 반박(verified만) — 예외도 fail-closed(NB5)
        if status == "verified":
            try:
                r2 = await cross.run(
                    "다음 주장을 반박할 근거를 찾아라. 발견 시 supported=false.\n\n"
                    + _evidence_block(c, amap),
                    response_format=_Support, effort="medium")
                if not r2.supported:
                    reasons.append(f"A2 반증: {r2.reason}")
                    status, conf = "unverified", "낮"
            except Exception as exc:  # noqa: BLE001 — fail-closed(반박 미수행=미검증)
                reasons.append(f"A2 실패(보수): {exc}")
                status, conf = "unverified", "낮"
        verdicts.append(ClaimVerdict(claim_id=c.claim_id, status=status,
                                     reasons=reasons, adjusted_confidence=conf))

    io.out_count = len(verdicts)
    io.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return StageResult(output=verdicts, io=io, error=None)
