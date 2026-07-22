import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import Anchor, EventCluster, EvidenceRef
from sector.report_synthesis import deepen, synthesize_claims


class _CliText:
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        assert "r-fx" in prompt and "usdkrw:krw" in prompt      # rules·anchors 실사용 확인
        return "논증 텍스트"


def test_deepen_includes_rules_and_anchors_in_prompt():
    cl = [EventCluster(cluster_id="c1", title="FX")]
    rules = [{"slug": "r-fx", "situation": "원화 급락", "connection": "환율→실적/수급 양가",
              "score": 4, "matched_keys": ["원/달러"], "conclusionType": "방향 판단"}]
    anchors = [Anchor(anchor_id="usdkrw:krw", metric="usdkrw", value=1450.0,
                      as_of="2026-07-21")]
    res = asyncio.run(deepen(cl, rules, anchors, role=_CliText()))
    assert res.output == "논증 텍스트" and res.error is None


def test_deepen_includes_case_memory_when_given():
    class _Spy:
        async def run(self, prompt, instructions="", *, response_format=None, effort=None):
            assert "mem-2018-downcycle" in prompt              # 과거사례 실주입
            assert "다음 국면" in prompt
            return "논증"

    cases = [{"episode_id": "mem-2018-downcycle", "matched_phase_order": 2,
              "score": 0.8, "next_phase_labels": ["가격 하락 가속"],
              "evidence": [{"source": "kosis", "quote": "재고 급증",
                            "knowable_at": "2018-07-01"}]}]
    res = asyncio.run(deepen([EventCluster(cluster_id="c", title="t")], [], [],
                             cases=cases, role=_Spy()))
    assert res.error is None


class _CliClaims:
    async def run(self, prompt, instructions="", *, response_format=None, effort=None):
        return response_format(claims=[{
            "title": "환율發 수급 상충", "trigger": "원/달러 급등",
            "mechanism": "원화약세→실적↑ but 외국인 수급 양가", "confidence": "낮",
            "counter": "환율 되돌림 시 소멸", "stance": "수급 확인 우선",
            "load_bearing": True,
            "evidence_ids": ["n1", "made-up"],                 # 날조 1건 → drop
            "anchor_refs": ["usdkrw:krw", "ghost"],            # 실존만 유지
            "numeric_facts": [{"anchor_id": "usdkrw:krw", "value": 1450.0}],
            "precedent": "2018 다운사이클 유사 국면",
            "precedent_case_ids": ["mem-2018-downcycle", "fake-case"],
            "matched_rules": ["r-fx"]}])


def _fixture():
    ev = EvidenceRef(kind="news", id="n1", title="원/달러 급등", source="연합",
                     ts="2026-07-21T09:00:00+00:00")
    cl = [EventCluster(cluster_id="c1", title="FX", members=[ev])]
    anchors = [Anchor(anchor_id="usdkrw:krw", metric="usdkrw", value=1450.0,
                      as_of="2026-07-21")]
    cases = [{"episode_id": "mem-2018-downcycle", "matched_phase_order": 2,
              "score": 0.8, "next_phase_labels": [], "evidence": []}]
    return cl, anchors, cases


def test_synthesize_hydrates_ids_and_derives_as_of():
    cl, anchors, cases = _fixture()
    res = asyncio.run(synthesize_claims("논증", cl, anchors, [], cases=cases,
                                        role=_CliClaims()))
    c = res.output[0]
    assert c.claim_id == "c0" and c.status == "unverified"
    assert [e.id for e in c.evidence_refs] == ["n1"]            # 날조 drop
    assert c.evidence == ["원/달러 급등 (연합)"]                 # 표시 문자열
    assert c.anchor_refs == ["usdkrw:krw"]                      # 실존만
    assert c.numeric_facts[0].value == 1450.0
    assert c.as_of == "2026-07-21T09:00:00+00:00"               # 코드 파생(max member ts)
    assert any("made-up" in str(d) for d in res.io.dropped)


def test_synthesize_grounds_precedent_only_on_real_cases():
    cl, anchors, cases = _fixture()
    res = asyncio.run(synthesize_claims("논증", cl, anchors, [], cases=cases,
                                        role=_CliClaims()))
    c = res.output[0]
    assert c.precedent_grounded is True                         # 실존 episode_id 확인됨
    assert c.matched_rules == ["r-fx"]
    assert any("fake-case" in str(d) for d in res.io.dropped)   # 날조 case drop

    # 케이스 풀이 비면 접지 불가 — precedent_grounded=False 유지(날조 금지)
    res2 = asyncio.run(synthesize_claims("논증", cl, anchors, [], cases=[],
                                         role=_CliClaims()))
    assert res2.output[0].precedent_grounded is False
