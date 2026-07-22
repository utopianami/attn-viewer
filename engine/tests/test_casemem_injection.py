"""Plan 4-b — casemem 오케스트레이터 주입: 플래그 기본 OFF·합성 렌더."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import DaPacket, EnvelopeMeta, PlanPacket
from profiles import PROFILES
from stages.synthesize import _render_context


def test_casemem_on_for_judgment_profiles_only():
    # 2026-07-22 Playwright 스크린샷 검증 후 판단형 프로필 활성화 —
    # fact_lookup 경량 경로만 OFF 유지(핸드오프 §주의의 게이트 통과)
    assert PROFILES["fact_lookup"].casemem_enabled is False
    for name in ("full", "event_interpretation", "stock_judgment",
                 "industry_analysis", "strategy_portfolio"):
        assert PROFILES[name].casemem_enabled is True, name


def _plan():
    return PlanPacket(meta=EnvelopeMeta(), tier=2, original_question="q",
                      standalone_question="q", knowledge_cutoff="2026-07-22")


def _da():
    return DaPacket(meta=EnvelopeMeta())


def test_render_context_includes_cases_when_given():
    cases = [{"episode_id": "mem-2018-downcycle", "matched_phase_order": 2,
              "score": 0.83, "next_phase_labels": ["가격 하락 가속"],
              "evidence": [{"source": "kosis", "quote": "재고지수 급증"}]}]
    ctx = _render_context(_plan(), _da(), None, None, None, None, [], None,
                          case_matches=cases)
    assert "[과거사례 대조]" in ctx
    assert "mem-2018-downcycle" in ctx and "가격 하락 가속" in ctx
    assert "재고지수 급증" in ctx
    assert "단정" in ctx                        # 경계 문구(사실 인용 금지)


def test_render_context_omits_cases_when_none():
    ctx = _render_context(_plan(), _da(), None, None, None, None, [], None,
                          case_matches=None)
    assert "[과거사례 대조]" not in ctx
