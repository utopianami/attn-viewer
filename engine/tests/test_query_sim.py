"""A3 — 유사 쿼리 감지·변형 (exact-string dedup의 공회전 방지 강화)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stages.query_sim import any_similar, similar, variant  # noqa: E402


def test_exact_and_near_duplicate():
    assert similar("삼성전자 영업이익 확인", "삼성전자 영업이익 확인")
    assert similar("삼성전자 영업이익 확인", "삼성전자 영업이익 최신 확인")  # 1토큰 차이
    assert not similar("삼성전자 영업이익", "SK하이닉스 HBM 점유율")


def test_korean_no_space_bigram():
    """토큰이 안 갈리는 붙여쓰기 — 2-gram 폴백으로 잡는다."""
    assert similar("삼성전자영업이익", "삼성전자 영업이익")


def test_any_similar():
    seen = {"삼성전자 영업이익 확인", "코스피 전망"}
    assert any_similar("삼성전자 영업이익 최신 확인", seen)
    assert not any_similar("현대차 전기차 판매량", seen)


def test_variant_produces_new_query():
    tried = {"삼성전자 영업이익 확인"}
    v = variant("삼성전자 영업이익 확인", tried)
    assert v is not None
    assert v not in tried
    assert v != "삼성전자 영업이익 확인"


def test_variant_exhausted_returns_none():
    q = "삼성전자 영업이익 확인"
    tried = {q}
    seen = set(tried)
    for _ in range(6):
        v = variant(q, seen)
        if v is None:
            break
        seen.add(v)
    assert variant(q, seen) is None
