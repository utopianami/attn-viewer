import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import ClaimVerdict, EvidenceRef, ReportClaim
from sector.report_assemble import assemble_report

_NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _mk(cid, title, **kw):
    return ReportClaim(claim_id=cid, title=title, **kw)


def test_three_way_split_and_verified_only_conclusion():
    claims = [_mk("c0", "검증됨", stance="수급 확인 우선"),
              _mk("c1", "미검증"), _mk("c2", "기각됨")]
    verdicts = [ClaimVerdict(claim_id="c0", status="verified", adjusted_confidence="중"),
                ClaimVerdict(claim_id="c1", status="unverified", adjusted_confidence="낮"),
                ClaimVerdict(claim_id="c2", status="rejected", adjusted_confidence="낮")]
    r = assemble_report(claims, verdicts, stages=[], now=_NOW, window_hours=12,
                        seq=2, title="t", stage_errors=[], seams_empty=["case_memory"])
    assert {c.title for c in r.claims} == {"검증됨", "미검증"}      # rejected 제외
    assert r.diagnostics["rejected_claims"] == ["기각됨"]
    assert "검증됨" in r.overview and "미검증" not in r.overview     # 결론=verified만
    assert r.title == "검증됨"                                       # 제목=최상위 verified 헤드라인
    assert r.finalOpinion.text == "수급 확인 우선"
    assert r.finalOpinion.confidence == "중"


def test_no_verdict_claim_forced_low_and_out_of_conclusion():
    # 판정 누락 claim이 합성의 "높"을 그대로 노출하면 안 됨(codex NB6 — 뷰어가 직접 렌더)
    claims = [_mk("c0", "판정누락", confidence="높")]
    r = assemble_report(claims, [], stages=[], now=_NOW, window_hours=12,
                        seq=1, title="t", stage_errors=[], seams_empty=[])
    assert r.claims[0].status == "unverified"
    assert r.claims[0].confidence == "낮"                            # 강제 하향
    # 종합엔 '미검증 관측' 라벨로 정보 보존, 결론(finalOpinion)엔 미반영(정책 v2)
    assert "미검증 관측" in r.overview and "판정누락" in r.overview
    assert r.title == "판정누락 (미검증)"                            # 헤드라인에도 미검증 표시
    assert r.finalOpinion.confidence == "낮"                         # verified 0 → 낮 고정
    assert "관망" in r.finalOpinion.text


def test_window_hours_and_diagnostics_fields():
    r = assemble_report([], [], stages=[], now=_NOW, window_hours=6,
                        seq=1, title="t", stage_errors=["f1: llm down"], seams_empty=["x"])
    assert r.window["from"].startswith("2026-07-21T15:00")           # KST 21:00−6h
    assert r.diagnostics["stage_errors"] == ["f1: llm down"]
    assert r.diagnostics["seams_empty"] == ["x"]
    assert r.id == "2026-07-21-1"                                    # KST 날짜
    assert r.title == "t — 생성 실패 (파이프라인 오류)"              # 전멸 시 제목이 실패 명시
    assert "파이프라인 오류 1건" in r.overview


def test_rejected_only_visible_in_title_and_overview():
    # -5호 실측: 주장 0 + 빈 종합으로 저장돼 목록에서 정체불명 — 기각/실패가 보여야 함
    claims = [_mk("c0", "기각된 주장")]
    verdicts = [ClaimVerdict(claim_id="c0", status="rejected", adjusted_confidence="낮")]
    r = assemble_report(claims, verdicts, stages=[], now=_NOW, window_hours=12,
                        seq=1, title="베이스", stage_errors=[], seams_empty=[])
    assert r.title == "베이스 — 전 주장 반증 기각, 관망"
    assert "기각 주장: 기각된 주장" in r.overview


def test_claim_evidence_stays_display_strings_in_dump():
    ev = EvidenceRef(kind="news", id="n1", title="SOX +1.8%", ts="2026-07-21T09:00:00+00:00",
                     source="reuters")
    claims = [_mk("c0", "c", evidence=["SOX +1.8% (reuters)"], evidence_refs=[ev])]
    verdicts = [ClaimVerdict(claim_id="c0", status="verified", adjusted_confidence="중")]
    r = assemble_report(claims, verdicts, stages=[], now=_NOW, window_hours=12,
                        seq=1, title="t", stage_errors=[], seams_empty=[])
    dumped = r.model_dump()["claims"][0]
    assert dumped["evidence"] == ["SOX +1.8% (reuters)"]   # 문자열 — 뷰어 [object Object] 방지
    assert dumped["evidence_refs"][0]["id"] == "n1"        # typed는 additive


def test_claim_cap_keeps_top_priority():
    claims = ([_mk(f"v{i}", f"검증{i}", load_bearing=True) for i in range(3)]
              + [_mk(f"u{i}", f"미검증{i}") for i in range(8)])
    verdicts = ([ClaimVerdict(claim_id=f"v{i}", status="verified", adjusted_confidence="중")
                 for i in range(3)]
                + [ClaimVerdict(claim_id=f"u{i}", status="unverified", adjusted_confidence="낮")
                   for i in range(8)])
    r = assemble_report(claims, verdicts, stages=[], now=_NOW, window_hours=12,
                        seq=1, title="t", stage_errors=[], seams_empty=[])
    assert len(r.claims) == 2                                # 상한(사용자: 최대 2개)
    assert [c.claim_id for c in r.claims] == ["v0", "v1"]    # verified 우선
    assert len(r.diagnostics["overflow_claims"]) == 9        # 초과분 투명 기록


def test_deepen_failure_marks_degraded_mode():
    # 사실성 감사 6.1: 심화 실패 리포트가 표시 없이 발행되면 안 됨
    r = assemble_report([], [], stages=[], now=_NOW, window_hours=12,
                        seq=1, title="t",
                        stage_errors=["deepen: 스테이지 타임아웃(2400s)", "f1: down"],
                        seams_empty=[])
    assert r.overview.startswith("⚠ 강등 모드: deepen")
    assert r.diagnostics["degraded"] == ["deepen"]
