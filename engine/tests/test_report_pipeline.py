import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from sector.contracts import SectorCard
from sector.report_contracts import FinalOpinion, Report, ReportPipeline
from sector.report_pipeline import alloc_report_slot, run_report_pipeline, save_report
from sector.store import SectorStore


def _rep(rid, seq):
    return Report(id=rid, seq=seq, generatedAt="x", title="t",
                  window={"from": "a", "to": "b"},
                  finalOpinion=FinalOpinion(text="hold", confidence="낮"),
                  pipeline=ReportPipeline(stages=[]), diagnostics={})


def test_alloc_reserves_and_increments(tmp_path):
    s1, p1, t1 = alloc_report_slot(tmp_path, "2026-07-21")
    s2, p2, t2 = alloc_report_slot(tmp_path, "2026-07-21")
    assert (s1, s2) == (1, 2) and p1 != p2 and t1 != t2
    assert p1.exists() and p1.parent.name == "reports"       # flat 예약(토큰) 파일


def test_save_requires_authentic_reservation(tmp_path):
    seq, path, token = alloc_report_slot(tmp_path, "2026-07-21")
    out = save_report(_rep("2026-07-21-1", seq), path, token)
    assert json.loads(out.read_text())["finalOpinion"]["confidence"] == "낮"
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

    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        name = getattr(response_format, "__name__", "")
        if name == "_RelBatch":
            return response_format(rows=[])
        if name == "_ImpBatch":
            return response_format(rows=[{"idx": 0, "impact": "상", "keep": True,
                                          "reason": "임팩트"}])
        if name == "_ClusterOut":
            return response_format(clusters=[{"cluster_id": "e1", "title": "SOX 강세",
                                              "member_idxs": [0]}])
        if name == "_ClaimsOut":
            return response_format(claims=[{
                "title": "지수 훈풍", "stance": "보유", "load_bearing": True,
                "confidence": "중", "evidence_ids": ["c1"], "matched_rules": []}])
        if name == "_Support":
            return response_format(supported=True, reason="ok")
        return "논증"                                        # deepen 텍스트(비구조화)


def _roles():
    r = _FakeRoles()
    return {k: r for k in
            ("filter", "importance", "cluster", "deepen", "synth", "verifier", "cross")}


def test_pipeline_end_to_end_with_fake_roles(tmp_path):
    s = SectorStore(tmp_path)
    now = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)
    s.append_cards([SectorCard(id="c1", ts="2026-07-21T15:00:00+00:00", axis="A",
                               title="SOX 강세", ingested_at="2026-07-21T15:05:00+00:00")])
    rep = asyncio.run(run_report_pipeline(s, now=now, seq=1, roles=_roles()))
    assert rep.id == "2026-07-22-1"                            # KST(21:00Z=익일 06:00 KST)
    assert [st.key for st in rep.pipeline.stages] == \
        ["raw", "f1", "f2", "f3", "deepen", "synth", "verify"]
    assert rep.claims and rep.claims[0].status == "verified"
    assert "지수 훈풍" in rep.overview
    assert all(isinstance(i, str) for st in rep.pipeline.stages for i in st.items)
    assert rep.diagnostics["seams_empty"] == \
        ["price_reaction", "analyst_reports", "case_memory"]


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
    rep = asyncio.run(run_report_pipeline(s, now=now, seq=1, roles=_roles(),
                                          case_store=cs))
    assert "case_memory" not in rep.diagnostics["seams_empty"]
    assert "case_memory_matches" in rep.diagnostics           # 관측성 카운트
