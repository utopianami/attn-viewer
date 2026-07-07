"""sector card → audit 증거 변환 헬퍼 (F1)."""
from __future__ import annotations

from sector.contracts import SectorCard


def cards_to_evidence(
    cards: list[SectorCard],
) -> tuple[list[str], dict[str, str]]:
    """SectorCard 목록을 audit 증거 구조체로 변환한다.

    Returns:
        texts: run_audit의 evidence_texts에 extend할 문자열 목록.
               각 카드 → "{title} — {raw_quote} {interpreted_signal}".
        docs:  run_audit의 evidence_docs에 setdefault로 머지할 url→원문 dict.
               url이 비어 있는 카드는 건너뜀. 기존 키를 덮어쓰지 않도록
               호출측에서 setdefault를 사용해야 한다.
    """
    texts: list[str] = []
    docs: dict[str, str] = {}
    for c in cards:
        texts.append(f"{c.title} — {c.raw_quote} {c.interpreted_signal}")
        if c.url:
            docs[c.url] = f"{c.title}\n{c.raw_quote}\n{c.interpreted_signal}"
    return texts, docs
