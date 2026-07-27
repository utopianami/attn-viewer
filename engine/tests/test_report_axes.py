"""v2 3축 카드 흐름 회귀 — 07-27 저녁 회차 타임아웃 사후 수정.

핵심 계약:
1. 시나리오 스테이지 타임아웃도 1회 재시도 — 재시도 성공 시 error 카드가 아니다.
2. 축 프롬프트의 앵커 라인은 비교 종류(MoM/QoQ/YoY)를 명시(_fmt_anchor 재사용).
3. 축 role.run 호출은 CLI 다리 데드라인(timeout=)을 전달한다.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sector.report_contracts import Anchor
from sector import report_axes


def _anchor():
    return Anchor(anchor_id="capex_hynix", metric="capex", value=-35.8, unit="%",
                  delta_pct=-35.8, as_of="2026-07-20", source="Yahoo Finance",
                  prev_period="2025Q4", prev_value=100.0, comparison_kind="QoQ")


def _clusters():
    return [SimpleNamespace(title="SOX 강세", axis="A", members=[])]


class _Role:
    """스테이지명별 스크립트 fake — run(**kw)로 timeout 전달을 함께 검증."""

    def __init__(self, name, log):
        self.name, self.log = name, log

    async def run(self, prompt, instructions="", *, response_format=None,
                  effort=None, timeout=None):
        self.log.append((self.name, timeout, prompt))
        n = getattr(response_format, "__name__", "")
        if n == "_AxisPlanOut":
            return response_format(axes=[
                {"axis": a, "focus": "F +1.0%", "event_titles": ["SOX 강세"]}
                for a in ("macro", "memory", "other")])
        if n == "_PhenomenonOut":
            return response_format(title="헤드라인 +1.0%",
                                   phenomenon_md="- 불릿\n\n해석.",
                                   watch_signals=["신호"])
        if n == "_ScenariosOut":
            if self.name == "scen_memory":        # 1차: 타임아웃 시뮬레이션
                await asyncio.sleep(0.5)
            return response_format(scenarios=[
                {"polarity": "positive", "thesis": "A면 좋다",
                 "beneficiaries": [{"name": "전력", "kind": "sector",
                                    "direction": "indirect", "polarity": "benefit",
                                    "rationale": "전이"}]},
                {"polarity": "negative", "thesis": "B면 나쁘다", "beneficiaries": []}])
        raise AssertionError(f"unexpected format {n}")


def _run_flow(monkeypatch):
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []
    cards, errors = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _Role(st, log), model="m",
        eff=None, live_research=False))
    return cards, errors, log


def test_scenario_timeout_retried_and_card_survives(monkeypatch):
    cards, errors, log = _run_flow(monkeypatch)
    assert [c.axis for c in cards] == ["macro", "memory", "other"]
    mem = cards[1]
    assert not mem.error                          # 재시도가 살렸다 — error 카드 아님
    assert {s.polarity for s in mem.scenarios} == {"positive", "negative"}
    assert any("scen_memory: 타임아웃 — 재시도" in e for e in errors)
    assert any(name == "scen_memory_retry" for name, _, _ in log)


def test_anchor_lines_carry_comparison_kind(monkeypatch):
    _, _, log = _run_flow(monkeypatch)
    for name in ("axis_split", "pheno_macro", "scen_macro"):
        prompt = next(p for n, _, p in log if n == name)
        assert "QoQ" in prompt and "직전 2025Q4=100.0" in prompt, name


def test_cli_leg_deadline_passed(monkeypatch):
    _, _, log = _run_flow(monkeypatch)
    t = {n: to for n, to, _ in log}
    assert t["axis_split"] == report_axes._SPLIT_CLI_S
    assert t["pheno_macro"] == report_axes._PHENO_CLI_S
    assert t["scen_macro"] == report_axes._SCEN_CLI_S
