"""report 전용 검증 — 코드 게이트(시점·숫자) 먼저, 그 후 A1 재감사·A2 반박.

code review r1 반영:
- B1: stance·counter·precedent까지 감사 블록에 포함(무감사 텍스트의 결론 승격 차단).
- B2: LLM이 numeric_facts 선언을 빠뜨려도 본문 수치를 코드가 스윕해 미선언·미대조
  수치는 unverified(%·통화·단위 수치 대상, 연도·제품명은 제외). delta_pct 선언 지원.
- B4: A2는 합성이 고른 근거가 아니라 **전체 클러스터 번들**을 보고 반박 + cutoff 명시.
fail-closed: LLM 실패·근거 불충분·미선언 수치 → unverified. 스펙 v3."""
from __future__ import annotations

import re
import time
from datetime import datetime

from pydantic import BaseModel

from sector.report_contracts import ClaimVerdict, StageIO, StageResult
from sector.report_input import _parse_ts

_REL_TOL = 0.001
_SWEEP_TOL = 0.005          # 본문 수치 스윕은 표기 반올림 감안 약간 관대
# 검증 대상 수치: %·통화·물량 단위가 붙은 것만 (연도·HBM4·DDR5 같은 제품명 제외)
# 화폐는 조원·억원 복합 단위만(bare 조/억은 법조문 "301조" 등 오탐 — 라이브 실측)
_NUM_UNIT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(%|퍼센트|달러|조\s?원|억\s?원|원|\$|B\b|GB\b)")


class _Support(BaseModel):
    supported: bool = False
    reason: str = ""


def _parse_asof(s: str):
    if len(s) == 7:                      # "YYYY-MM" → 월초(보수적)
        s = s + "-01T00:00:00+00:00"
    return _parse_ts(s)


def _swept_numbers(c) -> list[float]:
    """본문(제목·촉발·논증·스탠스·반론·과거사례)에서 단위 붙은 수치 추출."""
    text = " ".join([c.title, c.trigger, c.mechanism, c.stance, c.counter, c.precedent])
    return [float(m.group(1).replace(",", "")) for m in _NUM_UNIT.finditer(text)]


def _evidence_numbers(c) -> list[float]:
    """claim의 근거 발췌·제목에 실존하는 수치 — 출처 귀속 인용은 스윕 통과.

    발췌에 없는 수치만 날조 후보(라이브 실측: 뉴스 인용 수치가 전부 걸리면
    리포트가 항상 판단 보류가 됨 — 근거 실존 수치는 통과가 목적에 부합)."""
    text = " ".join([f"{e.title} {e.excerpt}" for e in c.evidence_refs])
    return [float(m.group(1).replace(",", "")) for m in _NUM_UNIT.finditer(text)]


def _matches_any(x: float, pool: list[float], tol: float) -> bool:
    return any(abs(x - p) <= max(abs(p), 1.0) * tol for p in pool)


def _evidence_block(c, anchors: dict, cutoff: datetime) -> str:
    """A1/A2 프롬프트용 — 주장 전 텍스트(스탠스·반론·과거사례 포함, B1) + 근거 발췌."""
    lines = [f"[지식 컷오프] {cutoff.isoformat()} — 이 시점 이후의 지식 사용 금지",
             f"[주장] {c.title}", f"[촉발] {c.trigger}", f"[논증] {c.mechanism}",
             f"[스탠스] {c.stance}", f"[반론] {c.counter}"]
    if c.precedent:
        lines.append(f"[과거사례 서술] {c.precedent} "
                     f"(접지 id: {c.precedent_case_ids or '없음'})")
    lines.append("[근거]")
    seen_titles = set()
    for e in c.evidence_refs:
        line = f"- {e.title}"
        if e.source:
            line += f" ({e.source})"
        if e.excerpt:
            line += f": {e.excerpt}"
        lines.append(line)
        seen_titles.add(e.title)
    for s in c.evidence:                 # refs 없이 문자열만 있는 경우 보강(중복 제거)
        if not any(t and t in s for t in seen_titles):
            lines.append(f"- {s}")
    lines.append("[수치]")
    for ar in c.anchor_refs:
        a = anchors.get(ar)
        if a:
            d = f", Δ{a.delta_pct:+.1f}%" if a.delta_pct is not None else ""
            lines.append(f"- {a.anchor_id} = {a.value}{a.unit}{d} @{a.as_of}")
    return "\n".join(lines)


def _bundle_block(clusters, cap: int = 40) -> str:
    """A2용 전체 클러스터 번들(B4) — 합성이 뺀 반증 재료까지 보이게."""
    lines = ["[전체 관측 번들 — 합성이 선택하지 않은 재료 포함]"]
    n = 0
    for cl in clusters:
        lines.append(f"- {cl.title}")
        for m in cl.members:
            if n >= cap:
                lines.append(f"  … (캡 {cap}건 초과 생략)")
                return "\n".join(lines)
            ex = f": {m.excerpt[:140]}" if m.excerpt else ""
            lines.append(f"    · {m.title}{ex}")
            n += 1
    return "\n".join(lines)


async def verify_claims(claims, anchors, clusters, *, cutoff: datetime,
                        verifier, cross) -> StageResult:
    t0 = time.monotonic()
    io = StageIO(key="verify", label="검증 — 시점/숫자/A1/A2", in_count=len(claims))
    amap = {a.anchor_id: a for a in anchors}
    anchor_pool = [a.value for a in anchors] + \
                  [a.delta_pct for a in anchors if a.delta_pct is not None]
    bundle = _bundle_block(clusters)
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
        # 2a) 숫자 정체성(코드) — 선언분 대조, 미존재 anchor·field 불일치 기각
        numeric_bad = False
        declared_vals: list[float] = []
        for nf in c.numeric_facts:
            a = amap.get(nf.anchor_id)
            if a is None:
                reasons.append(f"숫자 anchor 미존재: {nf.anchor_id}")
                numeric_bad = True
                continue
            target = a.delta_pct if nf.field == "delta_pct" else a.value
            if target is None:
                reasons.append(f"숫자 대조 불가: {nf.anchor_id}.{nf.field} 없음")
                numeric_bad = True
            elif abs(nf.value - target) / max(abs(target), 1e-9) > _REL_TOL:
                reasons.append(f"숫자 불일치: {nf.anchor_id}.{nf.field} "
                               f"주장 {nf.value} ≠ anchor {target}")
                numeric_bad = True
            else:
                declared_vals.append(nf.value)
        if numeric_bad:
            verdicts.append(ClaimVerdict(claim_id=c.claim_id, status="rejected",
                                         reasons=reasons, adjusted_confidence="낮"))
            continue
        # 2b) 본문 수치 스윕(코드, B2) — anchor·선언·근거 발췌 어디에도 없는
        # 단위 수치는 날조 후보로 미검증 처리(발췌 실존 = 출처 귀속 인용)
        sourced = declared_vals + anchor_pool + _evidence_numbers(c)
        for x in _swept_numbers(c):
            if not _matches_any(x, sourced, _SWEEP_TOL):
                reasons.append(f"미선언 수치 {x} — anchor/선언/근거 발췌에 없음(보수)")
        # 3) A1 재감사(load-bearing만, 전 텍스트·발췌·수치 실전달)
        status, conf = c.status, c.confidence
        if c.load_bearing and not reasons:
            try:
                r = await verifier.run(
                    "중립 재판정: 아래 주장(스탠스·반론 포함)이 제시 근거·수치로 "
                    "지지되는가. 근거 없는 단정·과장 스탠스면 supported=false.\n\n"
                    + _evidence_block(c, amap, cutoff),
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
        # 4) A2 반박(verified만) — 전체 번들 + cutoff, 예외 fail-closed
        if status == "verified":
            try:
                r2 = await cross.run(
                    "다음 주장을 반박할 근거를 찾아라(합성이 누락한 반증 포함). "
                    "발견 시 supported=false.\n\n"
                    + _evidence_block(c, amap, cutoff) + "\n\n" + bundle,
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
