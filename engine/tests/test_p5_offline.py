"""P5 인용 entailment 오프라인 테스트 — 쌍 추출 · 판정 반영 · provenance (mini 스텁).

① _citation_pairs: 근거 원문 있는 URL만, 문장 경계 추출
② contradict → [인용 불일치] 인라인 + citation_mismatch 이슈 + severe
③ provenance_soundness = entail 비율
④ evidence_docs 없으면 provenance=None (기존 동작 불변)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import ClaimTable  # noqa: E402
import stages.audit as audit_mod  # noqa: E402

_ANSWER = (
    "카카오 1분기 매출은 1조9421억원이다 ([이투데이](https://a.com/1)).\n"
    "카카오는 2분기에 영업이익 3조원을 달성했다 ([한국경제](https://b.com/2)).\n"
    "출처 모르는 링크 문장이다 ([기타](https://no-doc.com/x))."
)
_DOCS = {
    "https://a.com/1": "카카오 실적 발표 — 1분기 매출 1조9421억원, 영업이익 2114억원",
    "https://b.com/2": "카카오 2분기 실적은 아직 미발표이며 컨센서스는 영업이익 2500억원 수준",
}


def test_citation_pairs():
    pairs = audit_mod._citation_pairs(_ANSWER, _DOCS)
    assert len(pairs) == 2, pairs  # no-doc.com은 원문 없어 제외
    assert "1조9421억원" in pairs[0][0] and "매출 1조9421억원" in pairs[0][1]


def test_entailment_applied():
    async def _fake_run(self, prompt, instr="", *, response_format=None, **kw):
        if response_format is audit_mod._Entails:
            return audit_mod._Entails(judgements=[
                audit_mod._Entail(idx=0, verdict="entail"),
                audit_mod._Entail(idx=1, verdict="contradict", reason="2분기 미발표"),
            ])
        raise RuntimeError("skip other mini")  # ③ 신규엔티티는 skip 경로

    orig = audit_mod.Role.run
    audit_mod.Role.run = _fake_run
    try:
        report, patched = asyncio.run(audit_mod.run_audit(
            _ANSWER, ClaimTable(), [],
            evidence_texts=list(_DOCS.values()), evidence_docs=_DOCS))
        assert report.provenance_soundness == 0.5, report.provenance_soundness
        mism = [i for i in report.issues if i.kind == "citation_mismatch"]
        assert len(mism) == 1 and "모순" in mism[0].detail, mism
        assert "[인용 불일치]" in patched
        assert report.severe, "contradict인데 severe=False"
    finally:
        audit_mod.Role.run = orig


def test_no_docs_no_provenance():
    async def _no_llm(self, *a, **k):
        raise RuntimeError("offline")
    orig = audit_mod.Role.run
    audit_mod.Role.run = _no_llm
    try:
        report, _ = asyncio.run(audit_mod.run_audit("숫자 없는 답변.", ClaimTable(), []))
        assert report.provenance_soundness is None
    finally:
        audit_mod.Role.run = orig


if __name__ == "__main__":
    test_citation_pairs()
    test_entailment_applied()
    test_no_docs_no_provenance()
    print("p5 offline: all passed")
