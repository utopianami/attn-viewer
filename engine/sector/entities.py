"""메모리 섹터 엔티티 패턴 — judge에서 분리, 공유 모듈 (P3 Task 2).

extract_entities(text) 공개 함수는 str을 직접 받아 표준화된 엔티티 목록을 반환한다.
"""
from __future__ import annotations

ENTITY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("SAMSUNG", ("삼성전자", "samsung electronics", "삼전")),
    ("SK_HYNIX", ("하이닉스", "hynix")),
    ("MICRON", ("마이크론", "micron")),
    ("TSMC", ("tsmc", "台積電", "티에스엠씨")),
    ("NVIDIA", ("엔비디아", "nvidia")),
    ("MICROSOFT", ("마이크로소프트", "microsoft", "azure")),
    ("GOOGLE", ("구글", "google", "alphabet", "gemini", "제미나이")),
    ("AMAZON", ("아마존", "amazon", "aws")),
    ("META", ("메타 ", "meta platforms", " meta", "저커버그")),
    ("APPLE", ("애플", "apple")),
    ("ORACLE", ("오라클", "oracle")),
    ("OPENAI", ("openai", "오픈ai", "chatgpt", "챗gpt", "챗지피티", "샘 올트먼")),
    ("ANTHROPIC", ("anthropic", "앤트로픽", "claude", "클로드")),
]


def extract_entities(text: str) -> list[str]:
    """주어진 텍스트에서 메모리 섹터 관련 엔티티를 추출한다.

    Args:
        text: 검색할 문자열 (소문자 변환 후 패턴 매칭).

    Returns:
        매칭된 표준 엔티티 이름 목록.
    """
    lower = text.lower()
    return [canon for canon, pats in ENTITY_PATTERNS if any(p in lower for p in pats)]
