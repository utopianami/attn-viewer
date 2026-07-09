"""A3 — 재조사 쿼리 유사도 감지·변형 (dexter scratchpad 패턴의 코드 레벨 이식).

exact-string seen_queries는 "확인"→"최신 확인" 같은 미세 변형 공회전을 못 막는다.
토큰 Jaccard + (한국어 붙여쓰기 대비) 문자 2-gram Jaccard 중 max로 판정.
변형(variant)은 접미 수식어 순환 — 같은 검색의 반복 대신 각도를 바꾼다.
"""
from __future__ import annotations

_SUFFIXES = ["최신", "공시 기준", "발표 수치", "뉴스", "분기 실적"]


def _tokens(s: str) -> set[str]:
    return set(s.lower().split())


def _bigrams(s: str) -> set[str]:
    t = "".join(s.lower().split())
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similar(a: str, b: str, threshold: float = 0.6) -> bool:
    return max(_jaccard(_tokens(a), _tokens(b)),
               _jaccard(_bigrams(a), _bigrams(b))) >= threshold


def any_similar(q: str, seen: set[str]) -> bool:
    return any(similar(q, s) for s in seen)


def variant(q: str, tried: set[str]) -> str | None:
    """q와 유사한 시도가 이미 있을 때 각도를 바꾼 변형 반환. 소진되면 None."""
    for suf in _SUFFIXES:
        cand = f"{q} {suf}".strip()
        if cand not in tried and not any(similar(cand, s, threshold=0.8) for s in tried):
            return cand
    return None
