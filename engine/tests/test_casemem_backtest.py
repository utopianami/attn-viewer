"""규칙 백테스트 v2 — 2단계 판정·마스킹·커버리지 강제·출처 제외 (§7 + codex 리뷰 반영).

가드레일 검증: 인용 실재 국면 역산(주장 불신) · 커버리지 미달=승격 불가 ·
환각/불량 인용 폐기 · 마지막 국면 트리거 unclear · 출처 사례 지지 제외 · fail-closed.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from casemem.backtest_rules import (
    MaskedCases,
    _OutOut,
    _OutVerdict,
    _TrigOut,
    _TrigVerdict,
    aggregate,
    backtest_rule,
    decide_status,
    source_episode_ids,
)
from casemem.seeds import load_seeds
from casemem.store import CaseStore


@pytest.fixture()
def masked(tmp_path):
    cs = CaseStore(tmp_path)
    load_seeds(cs)
    return MaskedCases(cs, sectors=("memory",))


def _key_of(masked, ep_id):
    return next(k for k, v in masked.key_to_id.items() if v == ep_id)


def _full_coverage(masked, overrides):
    """전 사례 false 기본 + overrides로 덮은 A단계 응답(커버리지 충족)."""
    out = []
    for k in sorted(masked.phases):
        out.append(overrides.get(k) or _TrigVerdict(episode_key=k, triggered=False))
    return out


class _FakeRole:
    def __init__(self, trig, outc=None):
        self._trig, self._outc = trig, outc or []
        self.calls = []

    async def run(self, prompt, instructions="", *, response_format=None,
                  effort=None, cache_prefix=None):
        self.calls.append(instructions[:20])
        if response_format is _TrigOut:
            return _TrigOut(verdicts=self._trig)
        return _OutOut(verdicts=self._outc)


def _rule():
    return {"id": "r1", "situation": "재고조정 시작", "triggers": ["재고조정"],
            "connection": "수요 붕괴로 이어진다", "status": "candidate"}


SUPER = "mem-2016-2019-supercycle-crash"


def test_masking_hides_ids_titles_labels(masked):
    d = masked.all_digest()
    assert "mem-2016-2019" not in d          # 사례 id 마스킹
    assert "supercycle" not in d and "crash" not in d   # 사후 라벨 마스킹
    assert "2018-09" not in d                # 날짜 마스킹
    assert "재고조정" in d                    # 신호 원문은 유지


def test_two_stage_support_flow(masked):
    k = _key_of(masked, SUPER)
    # 실제 p2 신호 원문 조각 — locate_quote가 국면 2를 역산해야
    quote = "재고조정(inventory adjustments)이 시작됐다는 첫 언급"
    trig = _full_coverage(masked, {k: _TrigVerdict(episode_key=k, triggered=True,
                                                   quote=quote)})
    # B단계: 이후 국면(3·4)의 실제 신호를 인용해 followed
    out_quote = "공급사가 '고객 수요 약화'를 공식 인정하고 근시일 가시성 제한 언급"
    role = _FakeRole(trig, [_OutVerdict(episode_key=k, outcome="followed",
                                        quote=out_quote)])
    r = asyncio.run(backtest_rule(_rule(), masked, role))
    assert r["ok"] and r["coverage_ok"]
    assert r["verdicts"] == [{"episode_id": SUPER, "trigger_phase": 2,
                              "outcome": "followed", "quote": out_quote,
                              "is_source": False}]


def test_incomplete_coverage_blocks_promotion(masked):
    k = _key_of(masked, SUPER)
    quote = "재고조정(inventory adjustments)이 시작됐다는 첫 언급"
    # 한 사례 누락된 응답 → coverage_ok=False → 승격 불가
    trig = _full_coverage(masked, {k: _TrigVerdict(episode_key=k, triggered=True,
                                                   quote=quote)})[:-1]
    r = asyncio.run(backtest_rule(_rule(), masked, _FakeRole(trig)))
    assert r["coverage_ok"] is False
    assert decide_status(aggregate(r)) == "candidate"


def test_hallucinated_trigger_quote_breaks_trust(masked):
    k = _key_of(masked, SUPER)
    trig = _full_coverage(masked, {k: _TrigVerdict(episode_key=k, triggered=True,
                                                   quote="다이제스트에 없는 환각 문장")})
    r = asyncio.run(backtest_rule(_rule(), masked, _FakeRole(trig)))
    assert r["verdicts"] == []               # 환각 인용 → 트리거 불인정
    assert r["coverage_ok"] is False         # 판정 신뢰 상실 → 승격 불가


def test_short_or_crossphase_outcome_quote_stays_unclear(masked):
    k = _key_of(masked, SUPER)
    trig_quote = "재고조정(inventory adjustments)이 시작됐다는 첫 언급"     # p2
    past_quote = "클라우드 고객 매출이 전년 대비 4배 이상 급증"              # p1 — 이후 아님
    trig = _full_coverage(masked, {k: _TrigVerdict(episode_key=k, triggered=True,
                                                   quote=trig_quote)})
    role = _FakeRole(trig, [_OutVerdict(episode_key=k, outcome="followed",
                                        quote=past_quote)])
    r = asyncio.run(backtest_rule(_rule(), masked, role))
    assert r["verdicts"][0]["outcome"] == "unclear"   # 이전 국면 인용 → 불인정(보수)

    role2 = _FakeRole(trig, [_OutVerdict(episode_key=k, outcome="followed",
                                         quote="약화")])   # 10자 미만
    r2 = asyncio.run(backtest_rule(_rule(), masked, role2))
    assert r2["verdicts"][0]["outcome"] == "unclear"


def test_last_phase_trigger_unclear_and_no_stage_b_call(masked):
    k = _key_of(masked, SUPER)
    last_quote = "고객 재고는 정상화 진행 중이나 생산자(공급사) 재고는 여전히 과다한 비대칭 국면"  # p4(마지막)
    trig = _full_coverage(masked, {k: _TrigVerdict(episode_key=k, triggered=True,
                                                   quote=last_quote)})
    role = _FakeRole(trig)
    r = asyncio.run(backtest_rule(_rule(), masked, role))
    assert r["verdicts"][0]["outcome"] == "unclear"
    assert len(role.calls) == 1              # B단계 호출 자체가 없어야


def test_source_exclusion_and_policy(masked):
    # provenance 명시 id 파싱
    rule = dict(_rule(), provenance=f"cross-case: {SUPER}, mem-2014-2016-pc-downcycle")
    srcs = source_episode_ids(rule, masked, {})
    assert srcs == {SUPER, "mem-2014-2016-pc-downcycle"}
    # evidence 인용 겹침 파생
    rule2 = dict(_rule(), evidence=[{"quote": "unique overlap fragment here"}])
    srcs2 = source_episode_ids(rule2, masked,
                               {"mem-x": "…unique overlap fragment here…"})
    assert srcs2 == {"mem-x"}
    # 정책: 출처 지지는 승격에 못 씀, 반증은 출처여도 유효
    t = {"coverage_ok": True, "supports": 3, "out_supports": 1,
         "contradicts": 0, "unclear": 0, "fired": 3}
    assert decide_status(t) == "candidate"                    # 독립 지지 1뿐
    t["out_supports"] = 2
    assert decide_status(t) == "historically_supported"
    t2 = {"coverage_ok": True, "supports": 0, "out_supports": 0,
          "contradicts": 2, "unclear": 0, "fired": 2}
    assert decide_status(t2) == "historically_contradicted"
    t2["coverage_ok"] = False
    assert decide_status(t2) == "candidate"                   # 커버리지 없인 아무 승격 불가


def test_fail_closed_on_role_error(masked):
    class _Boom:
        async def run(self, *a, **k):
            raise RuntimeError("down")

    r = asyncio.run(backtest_rule(_rule(), masked, _Boom()))
    assert r["ok"] is False
    assert decide_status(aggregate(r)) == "candidate"
