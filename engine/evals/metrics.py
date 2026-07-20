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


# ---------------------------------------------------------------------------
# Chain-judgment 지표 (순수 함수 — LLM 의존 없음)
# ---------------------------------------------------------------------------
import random as _random

_CHAIN_AXES = ("mechanism", "state_link", "verdict", "evidence", "countercase")


def chain_axes_valid(rec: dict) -> bool:
    """chain_axes 키셋이 _CHAIN_AXES와 정확히 일치하고 전값 non-null인지 검증 (B8)."""
    ax = rec.get("chain_axes")
    return (isinstance(ax, dict) and set(ax) == set(_CHAIN_AXES)
            and all(v is not None for v in ax.values()))


def paired_valid(base: list[dict], cand: list[dict]) -> tuple[list[tuple], float]:
    """분모 = id 합집합 — 한쪽 누락도 무효 계수 (B8: 선택적 소실 은폐 차단)."""
    bmap, cmap = {r["id"]: r for r in base}, {r["id"]: r for r in cand}
    ids = sorted(set(bmap) | set(cmap))
    pairs = [(bmap[i], cmap[i]) for i in ids
             if i in bmap and i in cmap
             and chain_axes_valid(bmap[i]) and chain_axes_valid(cmap[i])]
    return pairs, (len(pairs) / len(ids) if ids else 0.0)


def bootstrap_ci(deltas: list[float], n: int = 10000,
                 seed: int = 42) -> tuple[float, float]:
    """Bootstrap 95% CI (percentile method)."""
    rng = _random.Random(seed)
    means = sorted(sum(rng.choices(deltas, k=len(deltas))) / len(deltas)
                   for _ in range(n))
    return means[int(n * 0.025)], means[int(n * 0.975)]


def axis_mean(records: list[dict], axis: str) -> float | None:
    """주어진 축의 평균값 — chain_axes 없거나 해당 축 None인 레코드는 제외."""
    vals = [r["chain_axes"][axis] for r in records
            if (r.get("chain_axes") or {}).get(axis) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None
