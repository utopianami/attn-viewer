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


def _run(claims, anchors, verifier, cross, clusters=None):
    return asyncio.run(verify_claims(claims, anchors, clusters or [], cutoff=_CUT,
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


# ── code review r1 exploit 회귀 (정책 v2: 하드차단→A1 경고 전달+확신도 상한) ──
def test_unmatched_number_reaches_a1_with_warning_and_caps_confidence():
    # exploit "99% 상승": 코드가 미확인 수치를 A1 프롬프트에 경고로 전달,
    # A1이 기각하면 unverified. (4호 실측: 하드차단은 시나리오 산술까지 전부 보류시킴)
    seen = {}

    class _SpyNo:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            seen["p"] = prompt
            return response_format(supported=False, reason="근거 없는 수치 단정")

    c = _claim(stance="근거 없이 99% 상승하므로 전량 매수")
    res = _run([c], [], _SpyNo(), _Yes())
    assert res.output[0].status == "unverified"
    assert "출처 미확인 수치" in seen["p"] and "99" in seen["p"]   # 경고 실전달
    # A1이 속아 지지해도 확신도는 중 상한 + 사유 기록
    c2 = _claim(stance="근거 없이 99% 상승하므로 전량 매수", confidence="높")
    res2 = _run([c2], [], _Yes(), _Yes())
    v2 = res2.output[0]
    assert v2.status == "verified" and v2.adjusted_confidence != "높"
    assert any("출처 미확인" in r for r in v2.reasons)


def test_evidence_quoted_number_passes_sweep_but_legal_section_ignored():
    ev = EvidenceRef(kind="news", id="n1", title="수출 기사",
                     excerpt="7월 반도체 수출이 8.2% 증가했다")
    ok = _claim(mechanism="수출 8.2% 증가가 수요 개선을 시사", evidence_refs=[ev])
    res = _run([ok], [], _Yes(), _Yes())
    assert res.output[0].status == "verified"       # 근거 발췌 실존 → 출처 귀속 인용

    legal = _claim(claim_id="c1", mechanism="무역법 301조 조사 리스크")
    res2 = _run([legal], [], _Yes(), _Yes())
    assert res2.output[0].status == "verified"      # "301조"는 법조문 — 수치 아님(오탐 방지)

    fake = _claim(claim_id="c2", mechanism="이익이 18.18조원 늘 것", evidence_refs=[ev])
    res3 = _run([fake], [], _No(), _Yes())
    assert res3.output[0].status == "unverified"    # 발췌에 없는 수치 → A1 경고 → 기각


def test_declared_or_anchor_number_passes_sweep():
    a = Anchor(anchor_id="fx:krw", metric="usdkrw", value=1450.0, as_of="2026-07-21",
               delta_pct=2.5)
    c = _claim(mechanism="원/달러 1450원, 변동 2.5%",
               numeric_facts=[NumericFact(anchor_id="fx:krw", value=1450.0)])
    res = _run([c], [a], _Yes(), _Yes())
    assert res.output[0].status == "verified"       # 1450=선언, 2.5%=anchor delta


def test_delta_fact_field_compared_to_delta():
    a = Anchor(anchor_id="px:DRAM", metric="p", value=3.5, delta_pct=16.7, as_of="2026-07")
    ok = _claim(numeric_facts=[NumericFact(anchor_id="px:DRAM", value=16.7,
                                           field="delta_pct")])
    bad = _claim(claim_id="c1",
                 numeric_facts=[NumericFact(anchor_id="px:DRAM", value=99.0,
                                            field="delta_pct")])
    res = _run([ok, bad], [a], _Yes(), _Yes())
    assert res.output[0].status == "verified"
    assert res.output[1].status == "rejected"


def test_a1_audits_stance_and_a2_sees_full_bundle():
    seen = {}

    class _SpyA1:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            seen["a1"] = prompt
            return response_format(supported=True, reason="ok")

    class _SpyA2:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            seen["a2"] = prompt
            return response_format(supported=True, reason="ok")

    from sector.report_contracts import EventCluster
    hidden = EvidenceRef(kind="news", id="h1", title="반증 기사",
                         excerpt="사실은 반대 방향이라는 근거")
    clusters = [EventCluster(cluster_id="e1", title="이벤트", members=[hidden])]
    c = _claim(stance="수급 확인 우선", counter="환율 되돌림")
    _run([c], [], _SpyA1(), _SpyA2(), clusters=clusters)
    assert "수급 확인 우선" in seen["a1"]           # 스탠스가 감사 대상(B1)
    assert "지식 컷오프" in seen["a1"]
    assert "반증 기사" in seen["a2"]                # 합성이 안 고른 재료도 A2에(B4)
