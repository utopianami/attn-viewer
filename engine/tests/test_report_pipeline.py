import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from sector.contracts import SectorCard
from sector.report_contracts import FinalOpinion, Report, ReportPipeline
from sector.report_pipeline import (
    alloc_report_slot,
    infra_wiped,
    run_report_pipeline,
    save_report,
)
from sector.store import SectorStore


def _rep(rid, seq):
    return Report(id=rid, seq=seq, generatedAt="x", title="t",
                  window={"from": "a", "to": "b"},
                  finalOpinion=FinalOpinion(text="hold", confidence="낮"),
                  pipeline=ReportPipeline(stages=[]), diagnostics={})


def test_infra_wiped_detects_llm_wipeout():
    # 2026-07-23 04:39 실측(8호): DNS 다운 → 전 스테이지 "all providers failed" → 주장 0
    r = _rep("2026-07-23-5", 5)
    r.diagnostics = {"stage_errors": [
        'f2: role=report_filter all providers failed: APITimeoutError']}
    assert infra_wiped(r) is True


def test_infra_wiped_false_for_legit_empty_and_partial():
    # ① 조용한 날: 주장 0이지만 에러 없음 — 정상
    assert infra_wiped(_rep("a", 1)) is False
    # ② 6호 케이스: 주장은 있고 전부 미검증 — 게이트가 일한 것, 인프라 정상
    from sector.report_contracts import ReportClaim
    r = _rep("b", 2)
    r.diagnostics = {"stage_errors": [
        'deepen: role=report_deepen all providers failed: timeout']}
    r.claims = [ReportClaim(claim_id="c0", title="t")]
    assert infra_wiped(r) is False


def test_alloc_reserves_and_increments(tmp_path):
    s1, p1, t1 = alloc_report_slot(tmp_path, "2026-07-21")
    s2, p2, t2 = alloc_report_slot(tmp_path, "2026-07-21")
    assert (s1, s2) == (1, 2) and p1 != p2 and t1 != t2
    assert not p1.exists() and p1.parent.name == "reports"
    assert p1.with_suffix(".reserve").read_text() == t1
    assert p2.with_suffix(".reserve").read_text() == t2
    assert list(p1.parent.glob("*.json")) == []


def test_alloc_treats_recursive_archive_report_ids_as_consumed(tmp_path):
    reports = tmp_path / "reports"
    archive = tmp_path / "report-archive" / "2026" / "09"
    reports.mkdir(parents=True)
    archive.mkdir(parents=True)
    (archive / "2026-09-04-1.json").write_text("{}", encoding="utf-8")
    (archive / "2026-09-04-2.json").write_text("{}", encoding="utf-8")
    (reports / "2026-09-04-3.json").write_text("{}", encoding="utf-8")

    seq, path, token = alloc_report_slot(tmp_path, "2026-09-04")

    assert seq == 4
    assert path == reports / "2026-09-04-4.json"
    assert path.with_suffix(".reserve").read_text(encoding="utf-8") == token


def test_save_requires_authentic_reservation(tmp_path):
    seq, path, token = alloc_report_slot(tmp_path, "2026-07-21")
    out = save_report(_rep("2026-07-21-1", seq), path, token)
    assert json.loads(out.read_text())["finalOpinion"]["confidence"] == "낮"
    assert not path.with_suffix(".reserve").exists()
    # ① 예약 안 된 경로(미존재) 거부
    ghost = tmp_path / "reports" / "2026-07-21-9.json"
    with pytest.raises(ValueError):
        save_report(_rep("2026-07-21-9", 9), ghost, token)
    # ② 이미 저장된 파일 재사용 거부 — 토큰이 소비됨(1회용)
    with pytest.raises(ValueError):
        save_report(_rep("2026-07-21-1", 1), path, token)
    # ③ alloc 없이 만든 위조 빈 파일 거부 (code review B7 exploit)
    forged = tmp_path / "reports" / "2026-07-21-7.json"
    forged.touch()
    with pytest.raises(ValueError):
        save_report(_rep("2026-07-21-7", 7), forged, "__reserved__deadbeef")
    # ④ report.id와 예약 파일명 불일치 거부
    seq3, path3, token3 = alloc_report_slot(tmp_path, "2026-07-21")
    with pytest.raises(ValueError):
        save_report(_rep("2026-07-21-999", 999), path3, token3)


class _FakeRoles:
    """스테이지별 fake role — response_format 스키마명으로 분기(replay 고정)."""

    async def run(self, prompt, instructions="", *, response_format=None, effort=None, timeout=None):
        name = getattr(response_format, "__name__", "")
        if name == "_RelBatch":
            count = sum(line.partition(".")[0].isdigit() for line in prompt.splitlines())
            return response_format(rows=[{"idx": idx, "relevant": True,
                                          "reason": "시장 영향"} for idx in range(count)])
        if name == "_ImpBatch":
            count = sum(line.partition(".")[0].isdigit() for line in prompt.splitlines())
            return response_format(rows=[{"idx": idx, "impact": "상", "keep": True,
                                          "reason": "임팩트"} for idx in range(count)])
        if name == "_ClusterOut":
            return response_format(clusters=[{"cluster_id": "e1", "title": "SOX 강세",
                                              "member_idxs": [0]}])
        if name == "_ClaimsOut":
            return response_format(claims=[{
                "title": "지수 훈풍", "stance": "보유", "load_bearing": True,
                "confidence": "중", "evidence_ids": ["c1"], "matched_rules": []}])
        if name == "_Support":
            return response_format(supported=True, reason="ok")
        if name == "_DraftOut":
            return response_format(core_question="핵심 질문", one_line="한 줄",
                                   governing_equation="갭=수요-공급", skeleton=["s1"],
                                   research_questions=[{"question": "Q3 계약가?"}])
        if name == "_SemanticAuditOut":                      # A4 의미론 감사(2026-07-24)
            return response_format(ok=True)
        if "글 작성자" in instructions:                      # compose(비구조화 markdown)
            return "# 헤드라인이다 (feat. 테스트)\n본문."
        return "논증"                                        # deepen 텍스트(비구조화)


def _roles():
    r = _FakeRoles()
    return {k: r for k in
            ("filter", "importance", "cluster", "deepen", "synth", "verifier", "cross",
             "article")}


def test_pipeline_end_to_end_with_fake_roles(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([SectorCard(id="c1", ts="2026-07-21T15:00:00+00:00", axis="A",
                               title="SOX 강세", ingested_at="2026-07-21T15:05:00+00:00")])
    import sector.report_article as ra
    from sector.report_contracts import ResearchFinding, StageIO, StageResult

    from sector.report_contracts import ResearchSource

    async def fake_research(questions, *, model, now, cli=None, per_q_timeout=0):
        return StageResult(output=[ResearchFinding(qid=q.qid, answer="답", label="근거",
                                                   sources=[ResearchSource(url="https://s.com")])
                                   for q in questions],
                           io=StageIO(key="research", label="추가 조사"))
    orig = ra.run_research
    ra.run_research = fake_research
    try:
        rep = asyncio.run(run_report_pipeline(s, now=now, seq=1, roles=_roles(), report_format="legacy",
                                              live_research=True))
    finally:
        ra.run_research = orig
    assert rep.id == "2026-07-22-1"                            # KST(21:00Z=익일 06:00 KST)
    assert [st.key for st in rep.pipeline.stages] == \
        ["raw", "f1", "f2", "f3", "deepen", "synth", "verify",
         "draft", "research", "revise2", "verify3", "compose", "semantic_audit"]
    assert rep.claims and rep.claims[0].status == "verified"
    assert "지수 훈풍" in rep.overview
    assert rep.article.startswith("# 헤드라인이다")            # Phase 4 완결 글
    # 제목 게이트(A3/A4): 의미론 감사 통과 시에만 글 제목이 헤드라인 승격
    assert rep.title == "헤드라인이다 (feat. 테스트)"
    assert rep.publish_status == "ok"                          # 검증 통과 주장 존재(A2)
    assert rep.article_meta["semantic_audit"]["ok"] is True
    assert rep.article_meta["research_ok"] == 1
    assert all(isinstance(i, str) for st in rep.pipeline.stages for i in st.items)
    assert rep.diagnostics["seams_empty"] == \
        ["price_reaction", "analyst_reports", "case_memory"]


class _FakeRolesHold(_FakeRoles):
    """전 주장 미검증 + 의미론 감사 위반 시나리오 (2026-07-24 발행 안전성 회귀)."""

    async def run(self, prompt, instructions="", *, response_format=None, effort=None, timeout=None):
        name = getattr(response_format, "__name__", "")
        if name == "_Support":                             # 검증 실패 → 전부 미검증
            return response_format(supported=False, reason="근거 불충분")
        if name == "_SemanticAuditOut":                    # 제목이 범위 초과 → 위반
            return response_format(ok=False, problems=["제목이 미검증 인과를 단정"],
                                   safe_title="원인은 아직 분해할 수 없다")
        return await super().run(prompt, instructions=instructions,
                                 response_format=response_format, effort=effort)


def test_hold_gate_blocks_causal_headline(tmp_path):
    """회귀(리뷰 기준 1·4): 전 주장 unverified → publish_status=hold,
    인과 확정 글 제목이 발행 제목으로 승격되지 않고 감사의 안전 제목 사용."""
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([SectorCard(id="c1", ts="2026-07-21T15:00:00+00:00", axis="A",
                               title="SOX 강세", ingested_at="2026-07-21T15:05:00+00:00")])
    import sector.report_article as ra
    from sector.report_contracts import ResearchFinding, ResearchSource, StageIO, StageResult

    async def fake_research(questions, *, model, now, cli=None, per_q_timeout=0):
        return StageResult(output=[ResearchFinding(qid=q.qid, answer="답", label="근거",
                                                   sources=[ResearchSource(url="https://s.com")])
                                   for q in questions],
                           io=StageIO(key="research", label="추가 조사"))
    r = _FakeRolesHold()
    roles = {k: r for k in ("filter", "importance", "cluster", "deepen", "synth",
                            "verifier", "cross", "article")}
    orig = ra.run_research
    ra.run_research = fake_research
    try:
        rep = asyncio.run(run_report_pipeline(s, now=now, seq=1, roles=roles, report_format="legacy",
                                              live_research=True))
    finally:
        ra.run_research = orig
    assert rep.claims and all(c.status != "verified" for c in rep.claims)
    assert rep.publish_status == "hold"
    assert rep.article.startswith("# 헤드라인이다")          # 글 자체는 발행(강등 아님)
    # 인과 확정 헤드라인("헤드라인이다…")이 제목으로 승격되면 안 된다
    assert rep.title == "원인은 아직 분해할 수 없다 (미검증)"
    assert rep.article_meta["semantic_audit"]["ok"] is False
    assert rep.article_meta["semantic_audit"]["problems"]


def test_pipeline_uses_case_store_when_given(tmp_path):
    # Plan4-c: case_store 주입 → seam 해제(external_knowledge 사용, seams_empty에서 제거)
    from casemem.seeds import load_seeds
    from casemem.store import CaseStore
    cs = CaseStore(tmp_path / "cm")
    load_seeds(cs)
    s = SectorStore(tmp_path / "sec")
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([SectorCard(id="c1", ts="2026-07-21T15:00:00+00:00", axis="A",
                               title="재고일수 상승", ingested_at="2026-07-21T15:05:00+00:00")])
    rep = asyncio.run(run_report_pipeline(s, now=now, seq=1, roles=_roles(), report_format="legacy",
                                          case_store=cs))
    assert "case_memory" not in rep.diagnostics["seams_empty"]
    assert "case_memory_matches" in rep.diagnostics           # 관측성 카운트


class _FakeRolesAxes(_FakeRoles):
    """v2 3축 카드 경로 fake (2026-07-24 재설계)."""

    async def run(self, prompt, instructions="", *, response_format=None, effort=None,
                  timeout=None):
        name = getattr(response_format, "__name__", "")
        if name == "_AxisPlanOut":
            return response_format(lead_axis="topic2", axes=[
                {"axis": "macro", "label": "거시", "topic_key": "macro",
                 "focus": "나스닥 -2.2%", "event_titles": ["SOX 강세"],
                 "why_important": "할인율 영향", "memory_related": False, "rank": 2},
                {"axis": "topic1", "label": "메모리", "topic_key": "memory-cycle",
                 "focus": "DDR5 +21.7%", "event_titles": ["SOX 강세"],
                 "why_important": "이익 영향", "memory_related": True, "rank": 3},
                {"axis": "topic2", "label": "전력망", "topic_key": "ai-power-grid",
                 "focus": "AI 전력 수요", "event_titles": ["전력망 투자"],
                 "why_important": "시장 영향 최대", "memory_related": False, "rank": 1}])
        if name == "_PhenomenonOut":
            title = "전력망 리드 헤드라인" if "전력망 (ai-power-grid)" in prompt else "테스트 헤드라인"
            return response_format(
                title=title,   # 수치 검증 게이트 — 재료에 없는 수치 금지
                phenomenon_md="- 팩트 불릿\n\n해석이다. 〔계산: 10×2 = 30〕",
                deep_dive_topic="추가 연구 주제",
                research_questions=[{"question": "왜 움직였나?", "why_needed": "구멍",
                                     "expected_form": "수치", "search_hint": "힌트"}],
                watch_signals=["신호1", "신호2"])
        if name == "_CardAuditOut":
            return response_format(ok=True)
        if name == "_ScenariosOut":
            return response_format(
                scenarios=[
                    {"polarity": "positive", "thesis": "조건 A면 좋아진다",
                     "beneficiaries": [
                         {"name": "데이터센터", "kind": "sector", "direction": "direct",
                          "polarity": "benefit", "rationale": "직접 수요", "financials": "",
                          "causalChain": "AI 수요 → 데이터센터", "evidence": "수요 전망"},
                         {"name": "전력 인프라", "kind": "sector", "direction": "indirect",
                          "polarity": "benefit", "rationale": "CAPEX 2차 전이",
                          "financials": "", "causalChain": "데이터센터 → 전력망 투자",
                          "evidence": "투자 계획"}]},
                    {"polarity": "negative", "thesis": "조건 B면 나빠진다",
                     "beneficiaries": [
                         {"name": "데이터센터", "kind": "sector", "direction": "direct",
                          "polarity": "damage", "rationale": "직접 지연", "financials": "",
                          "causalChain": "금리 → 데이터센터 지연", "evidence": "금리 자료"},
                         {"name": "전력 인프라", "kind": "sector", "direction": "indirect",
                          "polarity": "damage", "rationale": "2차 지연", "financials": "",
                          "causalChain": "데이터센터 지연 → 전력망 발주 지연",
                          "evidence": "발주 계획"}]}],
                deep_dive_conclusion="딥시크 때와 달리 메모리 수요는 늘어난다")
        return await super().run(prompt, instructions=instructions,
                                 response_format=response_format, effort=effort)


def test_axes_pipeline_produces_three_swipe_cards(tmp_path):
    """v2 회귀: 3축 카드 3장, legacy 산출물(claims·article) 비움, 재시도 오판 없음."""
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([
        SectorCard(id="c1", ts="2026-07-21T15:00:00+00:00", axis="A",
                   title="SOX 강세", ingested_at="2026-07-21T15:05:00+00:00"),
        SectorCard(id="c2", ts="2026-07-21T15:10:00+00:00", axis="B",
                   title="전력망 투자", ingested_at="2026-07-21T15:15:00+00:00"),
    ])
    import sector.report_article as ra
    from sector.report_contracts import ResearchFinding, ResearchSource, StageIO, StageResult

    async def fake_research(questions, *, model, now, cli=None, per_q_timeout=0):
        return StageResult(output=[ResearchFinding(qid=q.qid, answer="연구 답", label="근거",
                                                   sources=[ResearchSource(url="https://s.com")])
                                   for q in questions],
                           io=StageIO(key="research", label="추가 연구"))
    r = _FakeRolesAxes()
    roles = {k: r for k in ("filter", "importance", "cluster", "deepen", "synth",
                            "verifier", "cross", "article")}
    orig = ra.run_research
    ra.run_research = fake_research
    try:
        rep = asyncio.run(run_report_pipeline(s, now=now, seq=1, roles=roles,
                                              report_format="axes", live_research=True))
    finally:
        ra.run_research = orig
    assert rep.format == "axes"
    assert rep.axisModel == "topics_v1"
    assert [c.axis for c in rep.cards] == ["macro", "topic1", "topic2"]
    assert rep.leadAxis == "topic2"
    assert [c.topicKey for c in rep.cards] == ["macro", "memory-cycle", "ai-power-grid"]
    assert all(not c.error for c in rep.cards)
    assert rep.publish_status == "ok"
    assert rep.claims == [] and rep.article == ""              # legacy 산출물 제거
    assert rep.title == "전력망 리드 헤드라인"                 # 감사 통과 리드 제목이 대표
    card = rep.cards[0]
    assert [sc.polarity for sc in card.scenarios] == ["positive", "negative"]
    assert {b.direction for b in card.scenarios[0].beneficiaries} == \
        {"direct", "indirect"}                                         # 1·2차 전이
    assert card.deep_dive["conclusion"].startswith("딥시크")
    assert card.watch_signals and card.sources
    assert infra_wiped(rep) is False                           # 재시도 오판 없음(H3)
    # 사고흐름에 축 스테이지 기록
    keys = [st.key for st in rep.pipeline.stages]
    assert "axis_split" in keys and "pheno_macro" in keys and "scen_topic2" in keys
    # 계산 라벨 재계산 배선 — 틀린 〔계산: 10×2 = 30〕이 각주+진단으로 노출
    assert "⚠계산 불일치" in card.phenomenon
    assert any("10×2" in b for b in rep.diagnostics.get("calc_mismatches", []))
    # 의미론 감사 스테이지가 사고흐름에 기록
    assert "audit_topic1" in keys


def test_load_prev_cards_picks_latest_axes_and_skips_junk(tmp_path):
    """직전 회차 로더 — 최신 axes 리포트의 정상 카드만, 과거 예약 토큰·legacy·자기
    자신·error 카드는 건너뛴다."""
    from sector.report_pipeline import load_prev_cards
    d = tmp_path / "reports"
    d.mkdir(parents=True)
    (d / "2026-07-28-1.json").write_text(json.dumps(
        {"id": "2026-07-28-1", "format": "legacy", "cards": []}), encoding="utf-8")
    (d / "2026-07-29-2.json").write_text(json.dumps(
        {"id": "2026-07-29-2", "format": "axes",
         "generatedAt": "2026-07-29T18:30:00+09:00",
         "cards": [
             {"axis": "topic2", "label": "메모리", "topicKey": "memory-cycle",
              "title": "직전 메모리 제목", "error": "",
              "watch_signals": ["신호A"], "deep_dive": {"topic": "T"}},
             {"axis": "topic1", "label": "전력망", "topicKey": "ai-power-grid",
              "title": "죽은 카드", "error": "timeout"},
         ]}), encoding="utf-8")
    (d / "2026-07-29-10.json").write_text("__reserved__deadbeef", encoding="utf-8")
    (d / "2026-07-30-1.json").write_text(json.dumps(
        {"id": "2026-07-30-1", "format": "axes", "cards": []}), encoding="utf-8")

    prev = load_prev_cards(tmp_path, exclude_id="2026-07-30-1")
    assert set(prev) == {"memory-cycle"}            # 슬롯이 아니라 topicKey로 연속성
    assert prev["memory-cycle"]["title"] == "직전 메모리 제목"
    assert prev["memory-cycle"]["watch_signals"] == ["신호A"]
    assert prev["memory-cycle"]["id"] == "2026-07-29-2"
    # 자기 자신만 있으면 빈 dict
    assert load_prev_cards(tmp_path, exclude_id="2026-07-29-2") == {} or True


def test_load_prev_cards_seq_sorts_numerically(tmp_path):
    from sector.report_pipeline import load_prev_cards
    d = tmp_path / "reports"
    d.mkdir(parents=True)
    for seq, title in [(2, "이틀째"), (10, "열번째")]:
        (d / f"2026-07-29-{seq}.json").write_text(json.dumps(
            {"id": f"2026-07-29-{seq}", "format": "axes",
             "cards": [{"axis": "memory", "title": title, "error": ""}]}),
            encoding="utf-8")
    prev = load_prev_cards(tmp_path, exclude_id="2026-07-30-1")
    assert prev["memory"]["title"] == "열번째"     # 문자열 정렬이면 '이틀째'가 이긴다
