"""C1 평가 하네스 — 코드 지표 (골든셋 실행 결과 → 레코드).

LLM 심판이 아니라 코드 지표가 본체 (스펙 §2 C1 — 동의 편향 회피):
verified_ratio(마지막 verify 라운드) · numeric_supported_ratio · provenance ·
rounds · cost · elapsed · keyword_check(골든셋 must_include/must_not).
"""
from __future__ import annotations

from typing import Any


def question_metrics(layers: list[dict], final_meta: dict) -> dict[str, Any]:
    """한 질문의 layer 스트림 + final meta → 지표 레코드."""
    verify_last: dict | None = None
    profile = None
    qtype = None
    playbook_matched: str | None = None
    for l in layers:
        if l.get("name") == "verify":
            verify_last = l.get("data") or {}
        elif l.get("name") == "triage":
            profile = (l.get("data") or {}).get("profile")
            qtype = (l.get("data") or {}).get("question_type")
        elif l.get("name") == "playbook":
            playbook_matched = ((l.get("data") or {}).get("matched")) or None
    verified_ratio = None
    if verify_last:
        counts = verify_last.get("counts") or {}
        total = sum(counts.values())
        if total:
            verified_ratio = round(counts.get("verified", 0) / total, 3)
    audit = final_meta.get("audit") or {}
    nt, ns = audit.get("numeric_total", 0), audit.get("numeric_supported", 0)
    return {
        "profile": profile,
        "question_type": qtype,
        "playbook_matched": playbook_matched,
        "verified_ratio": verified_ratio,
        "numeric_supported_ratio": round(ns / nt, 3) if nt else None,
        "provenance_soundness": audit.get("provenance_soundness"),
        "severe": audit.get("severe", False),
        "rounds": final_meta.get("rounds", 0),
        "elapsed_s": final_meta.get("elapsed_s", 0.0),
        "cost_usd": (final_meta.get("cost") or {}).get("total_usd", 0.0),
        "degraded": final_meta.get("degraded", []),
    }


def keyword_check(answer_md: str, must_include: list[str],
                  must_not: list[str]) -> tuple[bool, list[str], list[str]]:
    """골든셋 키워드 검사. 반환: (통과, 누락된 must_include, 걸린 must_not)."""
    missing = [k for k in must_include if k not in answer_md]
    hit = [k for k in must_not if k in answer_md]
    return (not missing and not hit), missing, hit
