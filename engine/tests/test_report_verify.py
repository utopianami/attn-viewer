import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import Anchor, EvidenceRef, NumericFact, ReportClaim
from sector.report_verify import verify_claims

_CUT = datetime(2026, 7, 21, 21, 0, tzinfo=timezone.utc)


class _Yes:
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        return response_format(supported=True, reason="근거 충분")


class _No:
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        return response_format(supported=False, reason="반증 있음")


class _Boom:
    async def run(self, *a, **k):
        raise RuntimeError("down")


def _claim(**kw):
    base = dict(claim_id="c0", title="t", load_bearing=True,
                as_of="2026-07-21T09:00:00+00:00")
    base.update(kw)
    return ReportClaim(**base)


def _run(claims, anchors, verifier, cross):
    return asyncio.run(verify_claims(claims, anchors, cutoff=_CUT,
                                     verifier=verifier, cross=cross))


def test_lookahead_rejected_and_monthly_asof_parses():
    res = _run([_claim(as_of="2026-08-01T00:00:00+00:00"),
                _claim(claim_id="c1", as_of="2026-07")], [], _Yes(), _Yes())
    assert res.output[0].status == "rejected"                      # 미래 → 기각
    assert res.output[1].status == "verified"                      # 월 단위 파싱 OK


def test_missing_asof_on_load_bearing_is_unverified():
    res = _run([_claim(as_of="")], [], _Yes(), _Yes())
    v = res.output[0]
    assert v.status == "unverified" and any("as_of" in r for r in v.reasons)


def test_numeric_identity_mismatch_and_missing_anchor_rejected():
    a = Anchor(anchor_id="fx:krw", metric="usdkrw", value=1450.0, as_of="2026-07-21")
    good = _claim(numeric_facts=[NumericFact(anchor_id="fx:krw", value=1450.0)])
    bad = _claim(claim_id="c1", numeric_facts=[NumericFact(anchor_id="fx:krw", value=1500.0)])
    ghost = _claim(claim_id="c2", numeric_facts=[NumericFact(anchor_id="ghost", value=1.0)])
    res = _run([good, bad, ghost], [a], _Yes(), _Yes())
    assert res.output[0].status == "verified"
    assert res.output[1].status == "rejected"                      # 정체성 불일치
    assert res.output[2].status == "rejected"                      # 미존재 anchor 선언(NB3)
    assert any("불일치" in r for r in res.output[1].reasons)
    assert any("미존재" in r for r in res.output[2].reasons)


def test_a1_gets_excerpts_and_anchor_values_in_prompt():
    seen = {}

    class _Spy:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            seen.setdefault("p", prompt)
            return response_format(supported=True, reason="ok")

    ev = EvidenceRef(kind="news", id="n1", title="원/달러 급등", source="연합",
                     excerpt="서울 외환시장에서 원/달러 환율이 12원 급등 마감했다")
    a = Anchor(anchor_id="fx:krw", metric="usdkrw", value=1450.0, as_of="2026-07-21")
    c = _claim(evidence=["원/달러 급등 (연합)"], evidence_refs=[ev],
               anchor_refs=["fx:krw"])
    _run([c], [a], _Spy(), _Yes())
    assert "12원 급등 마감" in seen["p"]                           # excerpt 실전달(제목만 금지)
    assert "1450.0" in seen["p"]                                   # anchor 수치 실전달


def test_a2_refutation_downgrades_verified():
    res = _run([_claim()], [], _Yes(), _No())                       # A1 통과 → A2 반박
    v = res.output[0]
    assert v.status == "unverified" and any("반증" in r for r in v.reasons)


def test_a1_and_a2_llm_errors_fail_closed():
    res = _run([_claim()], [], _Boom(), _Yes())                     # A1 예외
    assert res.output[0].status == "unverified"
    res2 = _run([_claim()], [], _Yes(), _Boom())                    # A2 예외도 보수(NB5)
    assert res2.output[0].status == "unverified"
    assert any("A2" in r for r in res2.output[0].reasons)
