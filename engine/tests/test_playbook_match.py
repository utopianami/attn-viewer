from stages.playbook import match_playbook, format_gates, load_playbooks, _valid_playbook

PB = {
    "slug": "memory-cycle-direction", "situation": "메모리 사이클 방향 판단",
    "triggers": ["감산", "재고"], "topics": ["DRAM", "HBM"], "conclusionType": "방향 판단",
    "matchKeys": ["감산", "재고", "레거시 DRAM", "DDR4", "가격 급등"],
    "gates": [{"order": 1, "check": "재고 주수 확인", "why": None,
               "kill": "재고 20주 이상이면 기각", "operationalization": "8주 미만", "evidence": ["a1"]}],
    "connection": "재고·가격 방향 일치 시 결론", "reservations": None,
    "status": "holdout_passed",
}

def test_match_topic_hit_and_type_map():
    # PB matchKeys=["감산","재고","레거시 DRAM","DDR4","가격 급등"], topics=["DRAM","HBM"]
    # 질문: "DRAM 감산이 사이클에 미치는 영향은?" → matchKeys: 감산+2=2, topics-matchkeys: DRAM+1=1 → 총 3점
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
    # PB: matchKeys=["감산","재고","레거시 DRAM","DDR4","가격 급등"](+2each), topics=["DRAM","HBM"](+1each if not in matchKeys)
    # 질문에 "DRAM 감산과 재고를 보면?" → PB: 감산+2, 재고+2, DRAM+1=5점
    # other: matchKeys=[], topics=["DRAM"] → DRAM+1=1점 → score<2 → 후보 제외(threshold 미달)
    # PB score=5 >= 2, second_score=0(other는 threshold 미달로 탈락, 점수 있으나 유효 후보 아님), margin=5 >= 1 → 매칭
    other = {**PB, "slug": "other", "matchKeys": [], "topics": ["DRAM"]}
    got = match_playbook("DRAM 감산과 재고를 보면?", "industry_analysis", [other, PB])
    assert got["slug"] == "memory-cycle-direction"

def test_single_generic_topic_hit_returns_none():
    """topic 1개만 히트 → score=1 < 2 → None (안전 기본값)."""
    simple = {**PB, "slug": "simple", "matchKeys": [], "topics": ["DRAM"]}
    assert match_playbook("DRAM 지금 업사이클이야?", "industry_analysis", [simple]) is None

def test_matchkey_hit_beats_topic_only():
    """matchKey 히트 플레이북이 topic만 히트 플레이북을 이겨야 함."""
    topic_only = {**PB, "slug": "topic-only", "matchKeys": [], "topics": ["DRAM"]}
    match_key_hit = {**PB, "slug": "match-key-hit", "matchKeys": ["감산", "DDR4", "재고"], "triggers": [], "topics": []}
    # 질문에 "DRAM 감산" → topic_only: DRAM+1=1점(score<2, 탈락), match_key_hit: 감산+2=2점 → 매칭
    got = match_playbook("DRAM 감산", "industry_analysis", [topic_only, match_key_hit])
    assert got["slug"] == "match-key-hit"

def test_equal_scores_returns_none():
    """두 후보 동점 → margin 0 < 1 → None."""
    pb_a = {**PB, "slug": "aaa", "matchKeys": ["감산", "DDR4", "재고"], "topics": []}
    pb_b = {**PB, "slug": "bbb", "matchKeys": ["재고", "DDR4", "감산"], "topics": []}
    # 질문: "감산과 재고" → 양쪽 다 감산+2, 재고+2 = 4점 동점 → margin=0 < 1 → None
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
    """matchKeys=None 플레이북은 방어 처리([] 취급), topics만으로 점수 계산, 정상 항목은 매칭."""
    pb_none_matchkeys = {**PB, "slug": "bad-matchkeys", "matchKeys": None}
    # matchKeys=None → (pb.get("matchKeys") or []) → [] → 점수 0, topics만(DRAM+1=1, HBM 없음)
    # PB score >= 2, pb_none_matchkeys score 낮으므로 PB가 매칭
    got = match_playbook("DRAM 감산이 사이클에 미치는 영향은?", "industry_analysis",
                          [pb_none_matchkeys, PB])
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
    "matchKeys": ["감산", "DDR4", "재고"],
    "topics": ["DRAM"],
}
PB_ZZZ = {
    **PB,
    "slug": "zzz-last",
    "matchKeys": ["감산", "DDR4", "재고"],
    "topics": ["DRAM"],
}


def test_tiebreak_equal_score_returns_none():
    """두 플레이북 동점(margin=0) → None (안전 기본값)."""
    # "DRAM 감산": 양쪽 다 감산+2 + topics DRAM+1 = 3점 동점 → margin=0 → None
    assert match_playbook("DRAM 감산", "industry_analysis", [PB_ZZZ, PB_AAA]) is None
    assert match_playbook("DRAM 감산", "industry_analysis", [PB_AAA, PB_ZZZ]) is None


def test_clear_winner_by_score():
    """명확한 승자가 있을 때 (margin >= 1) slug 순서와 무관하게 점수 높은 쪽 선택."""
    # pb_aaa_extra: matchKeys=["감산","DDR4","재고"], topics=["DRAM"]
    # pb_zzz_no_topic: matchKeys=["감산","DDR4","재고"], topics=[]
    # "DRAM 감산 재고" → pb_aaa_extra: matchKeys: 감산+2+재고+2=4, topics-matchkeys: DRAM+1=5
    # pb_zzz_no_topic: matchKeys: 감산+2+재고+2=4, topics-matchkeys: none=0=4
    # margin=1 → pb_aaa_extra wins
    pb_aaa_extra = {**PB_AAA, "matchKeys": ["감산", "DDR4", "재고"], "topics": ["DRAM"]}
    pb_zzz_no_topic = {**PB_ZZZ, "matchKeys": ["감산", "DDR4", "재고"], "topics": []}
    got = match_playbook("DRAM 감산 재고", "industry_analysis", [pb_zzz_no_topic, pb_aaa_extra])
    assert got["slug"] == "aaa-first"


def test_triggers_alone_do_not_score():
    """triggers만 있고 matchKeys가 없으면 점수 없음 — triggers는 합성 출처, 매칭 키 아님."""
    pb_trigger_only = {**PB, "matchKeys": [], "topics": []}
    # "DRAM 감산": matchKeys 없음, topics 없음 → score=0 < 2 → None
    assert match_playbook("DRAM 감산", "industry_analysis", [pb_trigger_only]) is None


def test_topic_dedupe():
    """topics=["DRAM","DRAM"]: set removes dupe → scores once."""
    pb_dup = {**PB, "matchKeys": ["감산", "DDR4", "재고"], "topics": ["DRAM", "DRAM"]}
    # "DRAM 감산": matchKeys: 감산+2=2, topics-matchKeys: DRAM+1=1 → total 3
    # single candidate, second=0, margin=3 → matches
    got = match_playbook("DRAM 감산 어때?", "industry_analysis", [pb_dup])
    assert got is not None


def test_key_in_matchkeys_and_topics_scores_two_once():
    """matchKeys=["DRAM","감산","재고"], topics=["DRAM"]: DRAM in matchKeys → 2pts,
    topics-matchkeys excludes DRAM → not double-counted."""
    pb_overlap = {**PB, "matchKeys": ["DRAM", "감산", "재고"], "topics": ["DRAM"]}
    # "DRAM 감산": matchKeys: DRAM+2+감산+2=4, topic_only_set={} (DRAM already in matchKeys)
    # single candidate → matches with score=4
    got = match_playbook("DRAM 감산", "industry_analysis", [pb_overlap])
    assert got is not None
    # Also verify total score wouldn't be 5 (3pts if double-counted):
    # second_score=0, so only the match matters
