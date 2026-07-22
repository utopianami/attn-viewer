"""Plan 4-b — casemem 오케스트레이터 주입: 플래그 기본 OFF·합성 렌더."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import DaPacket, EnvelopeMeta, PlanPacket
from profiles import PROFILES
from stages.synthesize import _render_context


def test_all_profiles_default_casemem_off():
    # 유저 리포트 출력을 바꾸는 변경 — 스크린샷 검증 전 전 프로필 OFF(핸드오프 §주의)
    assert all(p.casemem_enabled is False for p in PROFILES.values())


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
