from stages.playbook import match_playbook, format_gates

PB = {
    "slug": "memory-cycle-direction", "situation": "메모리 사이클 방향 판단",
    "triggers": ["감산", "재고"], "topics": ["DRAM", "HBM"], "conclusionType": "방향 판단",
    "gates": [{"order": 1, "check": "재고 주수 확인", "why": None,
               "kill": "재고 20주 이상이면 기각", "operationalization": "8주 미만", "evidence": ["a1"]}],
    "connection": "재고·가격 방향 일치 시 결론", "reservations": None,
    "status": "holdout_passed",
}

def test_match_topic_hit_and_type_map():
    got = match_playbook("DRAM 감산이 사이클에 미치는 영향은?", "industry_analysis", [PB])
    assert got["slug"] == "memory-cycle-direction"

def test_no_match_on_fact_lookup():
    assert match_playbook("DRAM 감산 발표일이 언제야?", "fact_lookup", [PB]) is None

def test_no_match_without_keyword():
    assert match_playbook("현대차 실적 어때?", "stock_judgment", [PB]) is None

def test_draft_never_matches():
    draft = {**PB, "status": "draft"}
    assert match_playbook("DRAM 감산 영향?", "industry_analysis", [draft]) is None

def test_top1_by_keyword_score():
    other = {**PB, "slug": "other", "triggers": [], "topics": ["DRAM"]}
    got = match_playbook("DRAM 감산과 재고를 보면?", "industry_analysis", [other, PB])
    assert got["slug"] == "memory-cycle-direction"  # 히트 3(감산·재고·DRAM) > 1(DRAM)

def test_format_gates_marks_procedure_only():
    text = format_gates(PB)
    assert "재고 주수 확인" in text
    assert "킬" in text
    assert "사실" in text  # 절차로만 쓰라는 경계 문구
