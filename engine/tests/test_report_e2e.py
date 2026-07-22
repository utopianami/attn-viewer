"""골든 end-to-end — 캡처 role 출력 replay: 같은 입력+같은 role 출력 → 같은 결과.

결정성 정의(스펙 v3): 코드 파생 계산·cutoff·정렬·ID 안정 + 캡처 role 출력 replay 동일.
타이밍 필드(elapsed_ms)는 골든 동등성에서 정규화 제외."""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.contracts import RawNewsDoc, SectorCard
from sector.report_pipeline import run_report_pipeline
from sector.store import SectorStore

_NOW = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)


def _seed(tmp_path):
    s = SectorStore(tmp_path)
    s.append_cards([SectorCard(id="c1", ts="2026-07-21T15:00:00+00:00", axis="market",
                               title="美 반도체주 강세",
                               ingested_at="2026-07-21T15:05:00+00:00")])
    s.append_raw_news([
        RawNewsDoc(id="n1", title="원/달러 급등", created_at="2026-07-21T16:00:00+00:00",
                   ingested_at="2026-07-21T16:05:00+00:00"),
        RawNewsDoc(id="n2", title="연예 뉴스", created_at="2026-07-21T16:00:00+00:00",
                   ingested_at="2026-07-21T16:05:00+00:00")])
    return s


class _Replay:
    """캡처된 role 출력 — 결정성 replay의 '고정 LLM'."""

    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        name = getattr(response_format, "__name__", "")
        if name == "_RelBatch":
            return response_format(rows=[{"idx": 0, "relevant": True, "reason": "환율"},
                                         {"idx": 1, "relevant": False, "reason": "무관"}])
        if name == "_ImpBatch":
            return response_format(rows=[{"idx": i, "impact": "상", "keep": True,
                                          "reason": "임팩트"} for i in range(2)])
        if name == "_ClusterOut":
            return response_format(clusters=[{"cluster_id": "e1", "title": "환율+지수",
                                              "member_idxs": [0, 1]}])
        if name == "_ClaimsOut":
            return response_format(claims=[{
                "title": "환율發 수급 상충", "stance": "수급 확인 우선",
                "load_bearing": True, "confidence": "중",
                "evidence_ids": ["c1", "n1"], "matched_rules": []}])
        if name == "_Support":
            return response_format(supported=True, reason="ok")
        return "논증 replay"


def _run(store):
    roles = {k: _Replay() for k in
             ("filter", "importance", "cluster", "deepen", "synth", "verifier", "cross")}
    return asyncio.run(run_report_pipeline(store, now=_NOW, seq=1, roles=roles))


def _normalize(d):
    for st in d["pipeline"]["stages"]:
        if st.get("io"):
            st["io"].pop("elapsed_ms", None)
    return d


def test_replay_is_deterministic_and_viewer_shaped(tmp_path):
    s = _seed(tmp_path)
    d1 = _normalize(_run(s).model_dump())
    d2 = _normalize(_run(s).model_dump())
    assert d1 == d2                          # replay 결정성

    # 뷰어 스키마 형태
    assert [st["key"] for st in d1["pipeline"]["stages"]] == \
        ["raw", "f1", "f2", "f3", "deepen", "synth", "verify"]
    assert d1["claims"][0]["status"] == "verified"
    assert d1["claims"][0]["evidence"] == ["美 반도체주 강세", "원/달러 급등"]
    assert d1["finalOpinion"]["text"] == "수급 확인 우선"
    assert "환율發 수급 상충" in d1["overview"]
    assert d1["diagnostics"]["seams_empty"] == \
        ["price_reaction", "analyst_reports", "case_memory"]
    # f1이 무관 뉴스를 실제로 걸렀는지(드롭 사유 기록)
    f1 = next(st for st in d1["pipeline"]["stages"] if st["key"] == "f1")
    assert any(dd["reason"] == "무관" for dd in f1["io"]["dropped"])
    # 전 스테이지 items 문자열(뷰어 안전)
    assert all(isinstance(i, str)
               for st in d1["pipeline"]["stages"] for i in st.get("items", []))
