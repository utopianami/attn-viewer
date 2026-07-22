"""리포트용 다중 playbook 랭커 — match_playbook과 동일 eligibility·스코어링(_score 공유).

margin 규칙(1위-2위 ≥1)은 의도적으로 미적용: 단일 규칙 주입의 오매칭 안전장치라
다중 규칙 랭킹(top-k)엔 해당 없음. 스펙 v3 · 계획 T5."""
from __future__ import annotations

from sector.report_contracts import Anchor, EventCluster
from stages.playbook import _REQUIRED_KEYS, _score


def derive_topics(cluster: EventCluster, anchors: list[Anchor]) -> list[str]:
    """클러스터·근거·anchor에서 매칭용 신호 문자열 유도(SectorCard엔 topics 필드 없음)."""
    sig = [cluster.title, cluster.axis, *cluster.topics]
    sig += [m.title for m in cluster.members if m.title]
    for a in anchors:
        sig.append(a.metric)
        if a.entity:
            sig.append(a.entity)
    return [s for s in dict.fromkeys(sig) if s]


def rank_playbooks(signal_text: str, playbooks: list[dict], *,
                   allowed_conclusion_types: set[str], top_k: int = 5) -> list[dict]:
    scored = []
    for pb in sorted(playbooks, key=lambda p: p.get("slug", "") if isinstance(p, dict) else ""):
        if not isinstance(pb, dict) or not _REQUIRED_KEYS.issubset(pb.keys()):
            continue
        if pb.get("status") != "holdout_passed":
            continue
        if pb.get("conclusionType") not in allowed_conclusion_types:
            continue
        score, mk_hits, matched = _score(signal_text, pb)
        if score < 2 or mk_hits == 0:
            continue
        scored.append({"slug": pb["slug"], "situation": pb.get("situation", ""),
                       "connection": pb.get("connection", ""), "score": score,
                       "matched_keys": matched, "conclusionType": pb.get("conclusionType", "")})
    scored.sort(key=lambda r: (-r["score"], r["slug"]))
    seen, out = set(), []
    for r in scored:
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        out.append(r)
        if len(out) >= top_k:
            break
    return out
