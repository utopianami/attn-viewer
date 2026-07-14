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
    # PB triggers=["감산","재고"] → 2*2=4점, topics=["DRAM","HBM"] 제외(trigger와 겹치지 않으나 질문에 DRAM도 있음)
    # 질문: "DRAM 감산이 사이클에 미치는 영향은?" → triggers: 감산(+2), topics: DRAM(+1), HBM 없음 → 총 3점
    # score=3 >= 2, 후보 1개이므로 second_score=0, margin=3 >= 1 → 매칭
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
    # PB: triggers=["감산","재고"](+2each), topics=["DRAM","HBM"](+1each if not in triggers)
    # 질문에 "DRAM 감산과 재고를 보면?" → PB: 감산+2, 재고+2, DRAM+1=5점
    # other: triggers=[], topics=["DRAM"] → DRAM+1=1점 → score<2 → None 후보에서 탈락
    # PB score=5 >= 2, second_score=0 (other 탈락), margin=5 >= 1 → 매칭
    other = {**PB, "slug": "other", "triggers": [], "topics": ["DRAM"]}
    got = match_playbook("DRAM 감산과 재고를 보면?", "industry_analysis", [other, PB])
    assert got["slug"] == "memory-cycle-direction"

def test_single_generic_topic_hit_returns_none():
    """topic 1개만 히트 → score=1 < 2 → None (안전 기본값)."""
    simple = {**PB, "slug": "simple", "triggers": [], "topics": ["DRAM"]}
    assert match_playbook("DRAM 지금 업사이클이야?", "industry_analysis", [simple]) is None

def test_trigger_hit_beats_topic_only():
    """trigger 히트 플레이북이 topic만 히트 플레이북을 이겨야 함."""
    topic_only = {**PB, "slug": "topic-only", "triggers": [], "topics": ["DRAM"]}
    trigger_hit = {**PB, "slug": "trigger-hit", "triggers": ["감산"], "topics": []}
    # 질문에 "DRAM 감산" → topic_only: DRAM+1=1점(score<2, 탈락), trigger_hit: 감산+2=2점 → 매칭
    got = match_playbook("DRAM 감산", "industry_analysis", [topic_only, trigger_hit])
    assert got["slug"] == "trigger-hit"

def test_equal_scores_returns_none():
    """두 후보 동점 → margin 0 < 1 → None."""
    pb_a = {**PB, "slug": "aaa", "triggers": ["감산"], "topics": []}
    pb_b = {**PB, "slug": "bbb", "triggers": ["재고"], "topics": []}
    # 질문: "감산과 재고" → 각각 2점씩 동점 → margin=0 < 1 → None
    assert match_playbook("감산과 재고", "industry_analysis", [pb_a, pb_b]) is None

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


def test_valid_playbook_rejects_wrong_types():
    """타입 검증: str 필드가 str이 아니거나 triggers/topics가 list of str이 아니면 거부."""
    # slug가 int
    assert _valid_playbook({**PB, "slug": 123}) is False
    # triggers가 None
    assert _valid_playbook({**PB, "triggers": None}) is False
    # topics가 list of int
    assert _valid_playbook({**PB, "topics": [1, 2]}) is False
    # gates가 빈 리스트
    assert _valid_playbook({**PB, "gates": []}) is False
    # gate.order가 str
    bad_gate = {"order": "1", "check": "체크", "operationalization": "기준"}
    assert _valid_playbook({**PB, "gates": [bad_gate]}) is False
    # gate.operationalization이 None (str이어야 함)
    none_op_gate = {"order": 1, "check": "체크", "operationalization": None}
    assert _valid_playbook({**PB, "gates": [none_op_gate]}) is False


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


def test_match_playbook_triggers_none_skipped():
    """triggers=None 플레이북은 스킵(match_playbook 방어 처리), 정상 항목은 매칭."""
    pb_none_triggers = {**PB, "slug": "bad-triggers", "triggers": None}
    # triggers=None → (pb.get("triggers") or []) → [] → 점수 0, topics만
    # PB score >= 2, pb_none_triggers score 낮으므로 PB가 매칭
    got = match_playbook("DRAM 감산이 사이클에 미치는 영향은?", "industry_analysis",
                          [pb_none_triggers, PB])
    assert got["slug"] == "memory-cycle-direction"


def test_match_playbook_all_malformed_returns_none():
    """손상 항목만 있으면 None 반환 (크래시 없음)."""
    malformed_list = ["bad", None, {"slug": "missing-fields"}]
    result = match_playbook("DRAM 감산", "industry_analysis", malformed_list)
    assert result is None


# ── Finding 3 (구 tie-break): 동점 → margin 미달 → None ────────────────────────
# 새 스코어링에서 동점은 margin=0 < 1 이므로 None을 반환한다.
# slug 사전순 정렬은 내부적으로 유지되지만 동점 결과는 None이다.

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


def test_tiebreak_equal_score_returns_none():
    """두 플레이북 동점(margin=0) → None (안전 기본값)."""
    # "DRAM 감산": PB_AAA 감산+2=2점, PB_ZZZ 감산+2=2점 → margin=0 → None
    assert match_playbook("DRAM 감산", "industry_analysis", [PB_ZZZ, PB_AAA]) is None
    assert match_playbook("DRAM 감산", "industry_analysis", [PB_AAA, PB_ZZZ]) is None


def test_clear_winner_by_score():
    """명확한 승자가 있을 때 (margin >= 1) slug 순서와 무관하게 점수 높은 쪽 선택."""
    # PB_AAA: triggers=["감산"], topics=["DRAM"] → "DRAM 감산 재고" → 감산+2, DRAM+1 = 3점
    # PB_ZZZ: triggers=["감산"] → 감산+2 = 2점 → margin=1 → PB_AAA 선택
    pb_aaa_extra = {**PB_AAA, "topics": ["DRAM"]}
    pb_zzz_no_topic = {**PB_ZZZ, "topics": []}
    got = match_playbook("DRAM 감산 재고", "industry_analysis", [pb_zzz_no_topic, pb_aaa_extra])
    assert got["slug"] == "aaa-first"
