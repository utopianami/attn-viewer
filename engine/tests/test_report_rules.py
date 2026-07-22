import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import Anchor, EventCluster, EvidenceRef
from sector.report_rules import derive_topics, rank_playbooks


def _pb(slug, keys, topics, ctype="방향 판단", status="holdout_passed"):
    return {"slug": slug, "situation": slug, "triggers": [], "topics": topics,
            "conclusionType": ctype, "gates": [], "connection": "c",
            "status": status, "matchKeys": keys}


_ALLOWED = {"방향 판단", "종목 비교", "시점 판단", "리스크 점검"}


def test_rank_eligibility_and_order():
    pbs = [_pb("r-hbm", ["HBM 공급난"], ["메모리"]),
           _pb("r-two", ["HBM 공급난", "eSSD"], ["메모리"]),   # 2키 히트 → 더 높음
           _pb("r-topic-only", [], ["메모리"]),                # mk_hits 0 → 제외
           _pb("r-draft", ["HBM 공급난"], [], status="draft"),  # 미검증 → 제외
           _pb("r-type", ["HBM 공급난"], [], ctype="기타")]     # 타입 밖 → 제외
    text = "HBM 공급난 지속, eSSD 가격 상승, 메모리 업사이클"
    ranked = rank_playbooks(text, pbs, allowed_conclusion_types=_ALLOWED)
    assert [r["slug"] for r in ranked] == ["r-two", "r-hbm"]   # (-score, slug)
    assert ranked[0]["matched_keys"] == sorted(["HBM 공급난", "eSSD"])


def test_rank_dedups_matchkey_topic_double_count():
    # 같은 문자열이 matchKey이자 topic — 이중가산 금지(실제 스코어링 보존)
    pb = _pb("r-dup", ["HBM"], ["HBM"])
    ranked = rank_playbooks("HBM", [pb], allowed_conclusion_types=_ALLOWED)
    assert ranked and ranked[0]["score"] == 2                   # 2점(matchKey)만, 3점 아님


def test_rank_ubiquitous_name_scores_one():
    # 유비쿼터스 대형주 이름은 matchKey여도 1점 → 단독으론 score<2 미달
    pb = _pb("r-ubiq", ["삼성전자"], [])
    assert rank_playbooks("삼성전자 어때", [pb], allowed_conclusion_types=_ALLOWED) == []
    # 니치 키와 결합하면 통과
    pb2 = _pb("r-mix", ["삼성전자", "HBM4 인증"], [])
    ranked = rank_playbooks("삼성전자 HBM4 인증", [pb2], allowed_conclusion_types=_ALLOWED)
    assert ranked and ranked[0]["score"] == 3                   # 1 + 2


def test_derive_topics_includes_members_and_anchors():
    cl = EventCluster(cluster_id="c", title="MU 실적", axis="A",
                      members=[EvidenceRef(kind="news", id="n1", title="마이크론 서프라이즈")])
    a = Anchor(anchor_id="x:DRAM", metric="memory_price_usd_per_gb", entity="DRAM",
               value=3.5, as_of="2026-07")
    text = " ".join(derive_topics(cl, [a]))
    assert "마이크론" in text and "DRAM" in text and "MU 실적" in text
