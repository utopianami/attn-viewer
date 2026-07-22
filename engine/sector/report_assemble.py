"""검증 후 결론 조립 — 결론은 verified만, 코드가 결정적으로. LLM 재합성 금지(스펙 v3).

rejected → claims[]에서 제외(뷰어가 status 무시하고 '최종 주장'으로 렌더하므로)
→ diagnostics.rejected_claims. 판정 누락 → unverified + confidence 낮 강제(codex NB6)."""
from __future__ import annotations

from datetime import timedelta, timezone

from sector.report_contracts import FinalOpinion, Report, ReportPipeline

_KST = timezone(timedelta(hours=9))
_RANK = {"낮": 0, "중": 1, "높": 2}
_INV = {v: k for k, v in _RANK.items()}


_CLAIM_CAP = 2      # 본문 주장 상한 — 소수 정예(2026-07-22 사용자: "최대 2개")


def _claim_rank(c):
    """본문 노출 우선순위: verified > load_bearing > 확신도."""
    return (0 if c.status == "verified" else 1,
            0 if c.load_bearing else 1,
            -_RANK.get(c.confidence, 0))


def assemble_report(claims, verdicts, *, stages, now, window_hours, seq, title,
                    stage_errors, seams_empty) -> Report:
    vmap = {v.claim_id: v for v in verdicts}
    for c in claims:
        v = vmap.get(c.claim_id)
        if v is not None:
            c.status = v.status
            c.confidence = v.adjusted_confidence
        else:
            # 판정 누락 → 보수적: 결론 미반영 + 합성 confidence 노출 차단(NB6)
            c.status = "unverified"
            c.confidence = "낮"
    rejected = [c for c in claims if c.status == "rejected"]
    kept = [c for c in claims if c.status != "rejected"]
    kept.sort(key=_claim_rank)
    overflow = kept[_CLAIM_CAP:]
    kept = kept[:_CLAIM_CAP]                  # 본문 상한 — 초과분은 diagnostics에 기록
    verified = [c for c in kept if c.status == "verified"]

    if verified:
        overview = " · ".join(c.title for c in verified)
        fo_text = next((c.stance for c in verified if c.stance), verified[0].title)
        conf = _INV[min(_RANK.get(c.confidence, 0) for c in verified)]
    else:
        # 결론 불변식 유지(finalOpinion=관망/낮) + 종합은 정보 보존: 미검증 관측과
        # 관찰 신호를 코드가 요약(7호 실측 — "판단 보류" 한 줄은 정보가 죽음)
        parts = ["검증 통과 주장 없음 — 방향성 판단 보류."]
        if kept:
            parts.append("미검증 관측: " + " · ".join(c.title for c in kept))
            sigs = [w for c in kept for w in c.watch_signals][:4]
            if sigs:
                parts.append("관찰 신호: " + " · ".join(sigs))
        overview = "\n".join(parts)
        fo_text, conf = "관망 — 관찰 신호 확인 우선", "낮"   # verified 0 → 낮 고정

    kst = now.astimezone(_KST)
    return Report(
        id=f"{kst.strftime('%Y-%m-%d')}-{seq}", seq=seq,
        generatedAt=kst.isoformat(), title=title,
        window={"from": (now - timedelta(hours=window_hours)).astimezone(_KST).isoformat(),
                "to": kst.isoformat()},
        overview=overview,
        finalOpinion=FinalOpinion(text=fo_text, confidence=conf),
        claims=kept,
        pipeline=ReportPipeline(stages=list(stages)),
        diagnostics={"seams_empty": list(seams_empty),
                     "stage_errors": list(stage_errors),
                     "rejected_claims": [c.title for c in rejected],
                     "overflow_claims": [c.title for c in overflow]})
