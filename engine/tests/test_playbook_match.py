from stages.playbook import match_playbook, format_gates, load_playbooks, _valid_playbook

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


# ── Finding 1: load-validation — 손상 항목 스킵 ──────────────────────────────

def test_valid_playbook_accepts_well_formed():
    assert _valid_playbook(PB) is True


def test_valid_playbook_rejects_non_dict():
    assert _valid_playbook("not-a-dict") is False
    assert _valid_playbook(None) is False
    assert _valid_playbook([PB]) is False


def test_valid_playbook_rejects_missing_required_field():
    # slug 누락
    pb_no_slug = {k: v for k, v in PB.items() if k != "slug"}
    assert _valid_playbook(pb_no_slug) is False
    # gates 누락
    pb_no_gates = {k: v for k, v in PB.items() if k != "gates"}
    assert _valid_playbook(pb_no_gates) is False


def test_valid_playbook_rejects_malformed_gate():
    # gate에서 operationalization 누락
    bad_gate = {"order": 1, "check": "체크"}  # operationalization 없음
    pb_bad_gate = {**PB, "gates": [bad_gate]}
    assert _valid_playbook(pb_bad_gate) is False


def test_match_playbook_ignores_non_dict_and_missing_fields():
    """match_playbook에 직접 손상 항목 주입 시 크래시 없이 무시."""
    malformed_list = [
        "not-a-dict",          # 문자열
        42,                    # 정수
        None,                  # None
        {"slug": "no-gates"},  # 필수 필드 누락
        PB,                    # 정상 항목
    ]
    got = match_playbook("DRAM 감산이 사이클에 미치는 영향은?", "industry_analysis", malformed_list)
    assert got is not None
    assert got["slug"] == "memory-cycle-direction"


def test_match_playbook_all_malformed_returns_none():
    """손상 항목만 있으면 None 반환 (크래시 없음)."""
    malformed_list = ["bad", None, {"slug": "missing-fields"}]
    result = match_playbook("DRAM 감산", "industry_analysis", malformed_list)
    assert result is None


# ── Finding 3: 동점 tie-break — slug 사전순 결정적 ─────────────────────────────

# 두 플레이북이 동점(키워드 히트 수 동일)인 경우 slug 오름차순 앞쪽이 선택돼야 함.
PB_AAA = {
    **PB,
    "slug": "aaa-first",
    "triggers": ["감산"],
    "topics": ["DRAM"],
}
PB_ZZZ = {
    **PB,
    "slug": "zzz-last",
    "triggers": ["감산"],
    "topics": ["DRAM"],
}


def test_tiebreak_slug_order_forward():
    """입력 순서 [zzz, aaa] → aaa 선택."""
    got = match_playbook("DRAM 감산", "industry_analysis", [PB_ZZZ, PB_AAA])
    assert got["slug"] == "aaa-first"


def test_tiebreak_slug_order_reverse():
    """입력 순서 [aaa, zzz] → aaa 선택."""
    got = match_playbook("DRAM 감산", "industry_analysis", [PB_AAA, PB_ZZZ])
    assert got["slug"] == "aaa-first"
