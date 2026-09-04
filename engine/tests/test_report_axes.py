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
                {"axis": "macro", "label": "거시", "topic_key": "macro",
                 "focus": "F +1.0%", "event_titles": ["SOX 강세"],
                 "why_important": "할인율", "rank": 2},
                {"axis": "topic1", "label": "메모리", "topic_key": "memory-cycle",
                 "focus": "F +1.0%", "event_titles": ["SOX 강세"],
                 "why_important": "이익 전이", "memory_related": True, "rank": 1},
                {"axis": "topic2", "label": "시장 수급", "topic_key": "market-flow",
                 "focus": "F +1.0%", "event_titles": ["SOX 강세"],
                 "why_important": "수급 전이", "rank": 3}], lead_axis="topic1")
        if n == "_PhenomenonOut":
            return response_format(title="헤드라인 -35.8%",
                                   phenomenon_md="- 불릿\n\n해석.",
                                   watch_signals=["신호"])
        if n == "_ScenariosOut":
            if self.name == "scen_topic1":        # 1차: 타임아웃 시뮬레이션
                await asyncio.sleep(0.5)
            return response_format(scenarios=[
                {"polarity": "positive", "thesis": "A면 좋다",
                 "beneficiaries": [
                     {"name": "전력", "kind": "sector", "direction": "direct",
                      "polarity": "benefit", "rationale": "직접 전이", "financials": "",
                      "causalChain": "수요 → 전력", "evidence": "수요 자료"},
                     {"name": "산업재", "kind": "sector", "direction": "indirect",
                      "polarity": "benefit", "rationale": "간접 전이", "financials": "",
                      "causalChain": "전력 → 설비", "evidence": "설비 자료"}]},
                {"polarity": "negative", "thesis": "B면 나쁘다",
                 "beneficiaries": [
                     {"name": "전력", "kind": "sector", "direction": "direct",
                      "polarity": "damage", "rationale": "직접 전이", "financials": "",
                      "causalChain": "금리 → 발주", "evidence": "금리 자료"},
                     {"name": "산업재", "kind": "sector", "direction": "indirect",
                      "polarity": "damage", "rationale": "간접 전이", "financials": "",
                      "causalChain": "발주 → 가동률", "evidence": "가동률 자료"}]}])
        if n == "_CardAuditOut":
            return response_format(ok=True)
        raise AssertionError(f"unexpected format {n}")


def _run_flow(monkeypatch):
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []
    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _Role(st, log), model="m",
        eff=None, live_research=False))
    return cards, errors, log


def test_scenario_timeout_retried_and_card_survives(monkeypatch):
    cards, errors, log = _run_flow(monkeypatch)
    assert [c.axis for c in cards] == ["macro", "topic1", "topic2"]
    mem = cards[1]
    assert not mem.error                          # 재시도가 살렸다 — error 카드 아님
    assert {s.polarity for s in mem.scenarios} == {"positive", "negative"}
    assert any("scen_topic1:" in e and "타임아웃" in e for e in errors)
    assert any("scen_topic1:" in e and "재시도" in e for e in errors)
    assert any(name == "scen_topic1_retry" for name, _, _ in log)


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


def test_axis_split_failure_retried(monkeypatch):
    """축 배정 실패는 1회 재시도 — 운영 10/10 회차에서 axis_split 타임아웃으로
    전 카드가 배정 없이 생성된 실측(07-24~28). 재시도 성공 시 plan이 산다."""
    monkeypatch.setattr(report_axes, "_SPLIT_TIMEOUT", 0.1)
    log = []

    class _SplitFlaky(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            if self.name == "axis_split":         # 1차: 타임아웃 시뮬레이션
                await asyncio.sleep(0.5)
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _SplitFlaky(st, log), model="m",
        eff=None, live_research=False))
    assert any("axis_split" in e and "재시도" in e for e in errors)
    assert any(name == "axis_split_retry" for name, _, _ in log)
    # 재시도 plan이 pheno에 전달됐다 — focus가 프롬프트에 실림
    other_prompt = next(p for n, _, p in log if n == "pheno_topic2")
    assert "F +1.0%" in other_prompt


def test_other_axis_prompt_has_boundary_guard_and_raw_titles(monkeypatch):
    """'기타' 축 방어선 — axis_split이 죽으면 f1(메모리 관련성) 통과 클러스터만
    남아 메모리 주제가 '기타'로 새는 실측(07-25~28 '기타' 카드 7건 중 6건).
    ① 거시·메모리 배제 지시 상시 주입 ② 필터 이전 원시 제목 보충."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []
    asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="",
        f2_titles=["이란 휴전 협상 재개", "쉬인 홍콩 IPO 손실 전환"],
        cases=[], role_factory=lambda st: _Role(st, log), model="m",
        eff=None, live_research=False))
    other_prompt = next(p for n, _, p in log if n == "pheno_topic2")
    assert "[주제 경계]" in other_prompt
    assert "이란 휴전 협상 재개" in other_prompt   # 원시 제목 보충
    macro_prompt = next(p for n, _, p in log if n == "pheno_macro")
    assert "[주제 경계]" not in macro_prompt        # 다른 축엔 미주입


def test_prev_card_block_injected(monkeypatch):
    """연재 연속성 — 직전 회차 카드가 있으면 pheno 프롬프트에 [직전 회차 카드]
    블록+재탕 금지 지시 주입. 없던 5회차 연속 동일 헤드라인(07-28~30, DDR4
    +41.1% 반복) 실측이 배경: 월간 앵커는 한 달 내내 같은 델타라 직전 회차를
    모르면 매번 같은 수치가 헤드라인 주인공이 된다."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []
    prev = {"memory-cycle": {"id": "2026-07-29-2", "generatedAt": "2026-07-29T18:30:00+09:00",
                       "title": "DDR4 +41.1% MoM인데 생산지수 -8.2%",
                       "watch_signals": ["8월 Keepa 소매가", "SK하이닉스 컨콜"],
                       "deep_dive_topic": ""}}
    asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _Role(st, log), model="m",
        eff=None, live_research=False, prev_cards=prev))
    mem_prompt = next(p for n, _, p in log if n == "pheno_topic1")
    assert "[직전 회차 카드" in mem_prompt
    assert "DDR4 +41.1% MoM인데 생산지수 -8.2%" in mem_prompt
    assert "8월 Keepa 소매가" in mem_prompt
    assert "달라진 것" in mem_prompt                # 재탕 금지·변화 중심 지시
    macro_prompt = next(p for n, _, p in log if n == "pheno_macro")
    assert "[직전 회차 카드" not in macro_prompt   # 해당 축 직전 카드 없음 — 미주입


def test_no_prev_cards_no_block(monkeypatch):
    _, _, log = _run_flow(monkeypatch)              # prev_cards 미전달(첫 회차)
    for n, _, p in log:
        if n.startswith("pheno_"):
            assert "[직전 회차 카드" not in p


def test_axis_split_prompt_forbids_other_overlap(monkeypatch):
    """배정 프롬프트 자체도 'other는 두 축과 겹치지 않는 이벤트만' — 겹침 허용
    문구가 other까지 열려 있으면 메모리 최대 이슈가 '기타'로 중복 선정된다."""
    _, _, log = _run_flow(monkeypatch)
    split_prompt = next(p for n, _, p in log if n == "axis_split")
    assert "서로 다른" in split_prompt


def test_card_audit_swaps_title_on_violation(monkeypatch):
    """의미론 감사(v2 이식) — 위반 카드는 safe_title로 교체 + 진단 기록.
    수치 스윕은 숫자의 존재만 보므로 '제목이 근거 범위를 넘는 단정'은 여기서만
    잡힌다(legacy에만 있던 감사의 카드 경로 부재 — 07-30 사용자 지적)."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []

    class _AuditFlagsMemory(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            n = getattr(response_format, "__name__", "")
            if n == "_CardAuditOut":
                self.log.append((self.name, timeout, prompt))
                if self.name == "audit_topic1":
                    return response_format(ok=False, problems=["제목이 인과 단정"],
                                           safe_title="안전한 제목 +1.0%")
                return response_format(ok=True)
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _AuditFlagsMemory(st, log), model="m",
        eff=None, live_research=False))
    mem = next(c for c in cards if c.axis == "topic1")
    assert mem.title == "안전한 제목 +1.0%"     # 위반 → 대체 제목
    assert not mem.error                        # 카드는 산다(never-raise)
    assert any("audit_topic1" in e and "제목이 인과 단정" in e for e in errors)
    macro = next(c for c in cards if c.axis == "macro")
    assert macro.title == "헤드라인 -35.8%"     # ok=True 축은 그대로
    audit_prompt = next(p for n, _, p in log if n == "audit_topic1")
    assert "헤드라인 -35.8%" in audit_prompt    # 감사가 실제 제목·본문을 받는다
    assert "A면 좋다" in audit_prompt


def test_card_audit_failure_keeps_card(monkeypatch):
    """감사 자체가 죽어도 카드는 원형 유지 — 감사는 게이트지 생성자가 아니다."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []

    class _AuditBoom(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            if getattr(response_format, "__name__", "") == "_CardAuditOut":
                raise RuntimeError("audit down")
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _AuditBoom(st, log), model="m",
        eff=None, live_research=False))
    assert all(c.title == "헤드라인 -35.8%" and not c.error for c in cards)
    assert any(e.startswith("audit_") for e in errors)


# ── 수치 검증 게이트 + 연구 정정 역반영 (2026-07-31-1호 오독 사후) ────────────
def test_sweep_catches_fabricated_and_respects_labels():
    """"43%"는 "439%"의 부분열이 아니다 — 창작 수치 검출. 〔가정〕/〔계산〕
    선언 수치와 라벨 괄호 안 수치는 제외, 숫자 경계 없는 매칭은 오검증."""
    sweep = report_axes.sweep_unverified_numbers
    mat = "순수익률 439%라는 성과. 지수 24,442.94pt(-11.7%). CAPEX 44.2b"
    assert sweep("수익률 약 +43%를 기록〔근거: FT〕", mat) == ["+43%"]
    assert sweep("지수 24,442.94pt〔근거: YF〕", mat) == []      # 콤마 정규화
    assert sweep("하락 -1.7%였다〔근거: YF〕", mat) == ["-1.7%"]  # -11.7%에 오매칭 금지
    assert sweep("낙폭 -7.65%〔계산: 5.1 × 1.5 = -7.65%〕", mat) == []
    assert sweep("낙폭 약 -9.9%로 추정〔가정: 미공개〕", mat) == []
    assert sweep("CAPEX 44.2b〔근거: YF @2026-03 v2.1〕", mat) == []  # 괄호 안 제외
    # 부호 의미론(codex r1) — 뒤집힘은 미스, 부호째 일치·산문 무부호는 통과
    mat2 = "전일 -1.7% 하락, 목표 3.5%"
    assert sweep("반등 +1.7%였다〔근거: X〕", mat2) == ["+1.7%"]
    assert sweep("하락 -1.7%였다〔근거: X〕", mat2) == []
    assert sweep("낙폭 1.7%였다〔근거: X〕", mat2) == []
    # 원거리 〔가정〕 하나로 줄 전체 면제 불가(60자 창)
    far = "수익률 43%다. " + "긴 서술이 이어진다. " * 6 + "〔가정: 별개 항목〕"
    assert sweep(far, mat2) == ["43%"]


def test_pheno_number_gate_retry_fixes(monkeypatch):
    """1차 초안에 창작 수치 → 피드백 재생성이 고치면 주석 없이 발행."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []

    class _FabOnce(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            if getattr(response_format, "__name__", "") == "_PhenomenonOut" \
                    and self.name == "pheno_topic1":
                self.log.append((self.name, timeout, prompt))
                if "[수치 검증 실패" in prompt:
                    return response_format(title="헤드라인 -35.8%",
                                           phenomenon_md="- 정정된 불릿 -35.8%",
                                           watch_signals=["신호"])
                return response_format(title="헤드라인 +43%",
                                       phenomenon_md="- 수익률 +43%〔근거: FT〕")
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _FabOnce(st, log), model="m",
        eff=None, live_research=False))
    mem = next(c for c in cards if c.axis == "topic1")
    assert "43%" not in mem.phenomenon and "〔수치 검증" not in mem.phenomenon
    assert not any("pheno_topic1" in e and "수치 미확인" in e for e in errors)
    retry_prompts = [p for n, _, p in log
                     if n == "pheno_topic1" and "[수치 검증 실패" in p]
    assert retry_prompts and "43%" in retry_prompts[0]   # 미스 목록이 피드백에 실림


def test_pheno_number_gate_annotates_when_unfixed(monkeypatch):
    """재생성으로도 남는 창작 수치 — 본문 검증 주석 + 진단 기록, 카드는 산다."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []

    class _FabAlways(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            if getattr(response_format, "__name__", "") == "_PhenomenonOut" \
                    and self.name == "pheno_macro":
                self.log.append((self.name, timeout, prompt))
                return response_format(title="헤드라인",
                                       phenomenon_md="- 수익률 +43%〔근거: FT〕")
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _FabAlways(st, log), model="m",
        eff=None, live_research=False))
    mac = next(c for c in cards if c.axis == "macro")
    assert "〔수치 검증: 다음 수치는 수집 재료에서 확인되지 않았다 — +43%〕" \
        in mac.phenomenon
    assert not mac.error                                  # 카드는 산다
    assert any("pheno_macro" in e and "수치 미확인" in e for e in errors)
    assert sum(1 for n, _, _ in log if n == "pheno_macro") == 2  # 정확히 1회 재시도
    # 잔존 미확인 수치는 의미론 감사로 강제 전달 — 제목 정화 소관(codex r1)
    audit_prompt = next(p for n, _, p in log if n == "audit_macro")
    assert "결정적 수치 검증 실패" in audit_prompt and "+43%" in audit_prompt


def test_research_correction_backpropagates(monkeypatch):
    """심층 연구가 현상 분석 오류를 잡으면: 본문 정정 블록 + 제목 치환.
    wrong이 본문·제목에 없는 환각 정정은 무시(2026-07-31-1호 +43%/+439% 사후)."""
    from sector.report_contracts import (ResearchFinding, ResearchSource,
                                         StageIO as _SIO, StageResult as _SR)
    from sector import report_article
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)

    async def _fake_research(questions, *, model, now, cli=None,
                             per_q_timeout=0):
        return _SR(output=[ResearchFinding(
            qid="memory-q0", answer="시타델 블록 매각으로 이미 정리", label="근거",
            sources=[ResearchSource(url="https://ft.com/x")])],
            io=_SIO(key="research", label="연구"))

    monkeypatch.setattr(report_article, "run_research", _fake_research)
    log = []

    class _CorrRole(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            n = getattr(response_format, "__name__", "")
            if n == "_PhenomenonOut" and self.name == "pheno_topic1":
                self.log.append((self.name, timeout, prompt))
                return response_format(
                    title="펀드 마진 압박으로 조달 -35.8%",
                    phenomenon_md="- 마진 압박으로 조달 국면 -35.8%〔근거: FT〕",
                    deep_dive_topic="펀드 실낙폭",
                    research_questions=[{"question": "실낙폭은?"}],
                    watch_signals=["신호"])
            if n == "_ScenariosOut" and self.name.startswith("scen_topic1"):
                self.log.append((self.name, timeout, prompt))
                return response_format(
                    scenarios=[
                        {"polarity": "positive", "thesis": "A면 좋다",
                         "beneficiaries": [{"name": "전력", "kind": "sector",
                                            "direction": "indirect",
                                            "polarity": "benefit",
                                            "rationale": "전이"}]},
                        {"polarity": "negative", "thesis": "B면 나쁘다",
                         "beneficiaries": []}],
                    deep_dive_conclusion="정리 국면",
                    corrections=[
                        {"wrong": "마진 압박으로 조달", "right": "시타델 매각으로 정리",
                         "basis": "FT"},
                        {"wrong": "본문에 없는 문자열", "right": "무시돼야", "basis": ""}])
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _CorrRole(st, log), model="m",
        eff=None, live_research=True))
    mem = next(c for c in cards if c.axis == "topic1")
    assert "**추가 연구 후 정정**" in mem.phenomenon
    assert "시타델 매각으로 정리" in mem.phenomenon
    assert "마진 압박으로 조달" in mem.phenomenon      # 원문 보존(주석 방식)
    assert mem.title == "펀드 시타델 매각으로 정리 -35.8%"  # 제목은 치환
    assert "무시돼야" not in mem.phenomenon            # 환각 정정 무시
    assert mem.deep_dive.get("corrections_applied") == 1   # 성공은 오류 채널이 아니라 deep에
    assert not any("연구 정정" in e for e in errors)


def test_correction_without_findings_ignored(monkeypatch):
    """연구 결과 없이 온 corrections는 무시 — 정정의 근거는 연구뿐이다."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []

    class _CorrNoResearch(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            n = getattr(response_format, "__name__", "")
            if n == "_ScenariosOut":
                self.log.append((self.name, timeout, prompt))
                return response_format(
                    scenarios=[
                        {"polarity": "positive", "thesis": "A면 좋다",
                         "beneficiaries": [{"name": "전력", "kind": "sector",
                                            "direction": "indirect",
                                            "polarity": "benefit",
                                            "rationale": "전이"}]},
                        {"polarity": "negative", "thesis": "B면 나쁘다",
                         "beneficiaries": []}],
                    corrections=[{"wrong": "불릿", "right": "바뀐 불릿", "basis": ""}])
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, _, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _CorrNoResearch(st, log), model="m",
        eff=None, live_research=False))
    for c in cards:
        assert "**추가 연구 후 정정**" not in c.phenomenon


def test_unverified_title_gets_forced_marker(monkeypatch):
    """감사가 ok=true를 줘도 제목에 미확인 수치가 남으면 코드가 표식을 강제 —
    감사 실패·오판과 무관한 결정적 폴백(codex r2)."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []

    class _FabTitle(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            if getattr(response_format, "__name__", "") == "_PhenomenonOut" \
                    and self.name == "pheno_topic2":
                self.log.append((self.name, timeout, prompt))
                return response_format(title="펀드 +43% 급락",
                                       phenomenon_md="- 수익률 +43%〔근거: FT〕")
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _FabTitle(st, log), model="m",
        eff=None, live_research=False))
    oth = next(c for c in cards if c.axis == "topic2")
    assert oth.title.endswith("〔수치 미확인〕")     # 감사 ok=True여도 강제
    assert any("audit_topic2" in e and "표식 강제" in e for e in errors)


def test_focus_is_not_verification_material(monkeypatch):
    """plan.focus는 axis_split(LLM) 생성물 — 검증 재료로 인정하면 이전 단계
    오독이 스윕을 우회한다(codex r2). focus에만 있는 수치는 미확인 처리."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []

    class _EchoFocus(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            if getattr(response_format, "__name__", "") == "_PhenomenonOut" \
                    and self.name == "pheno_topic1":
                self.log.append((self.name, timeout, prompt))
                # focus "F +1.0%"의 수치를 그대로 반복 — 앵커·발췌엔 없다
                return response_format(title="헤드라인",
                                       phenomenon_md="- 배정 기준 +1.0%〔근거: 배정〕")
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _EchoFocus(st, log), model="m",
        eff=None, live_research=False))
    mem = next(c for c in cards if c.axis == "topic1")
    assert "〔수치 검증" in mem.phenomenon and "+1.0%" in mem.phenomenon
    assert any("pheno_topic1" in e and "수치 미확인" in e for e in errors)


def test_unassigned_clusters_supplied_to_pheno(monkeypatch):
    """미배정 클러스터 백스톱 — 2026-07-31-3호 실측: 아마존 실적 클러스터가
    f1~f3을 다 통과하고도 axis_split이 어느 축에도 안 넣어 전 카드에서 증발.
    배정에서 빠진 클러스터는 pheno에 [미배정 관측]으로 보충 공급한다."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []
    clusters = [SimpleNamespace(title="SOX 강세", axis="A", members=[]),
                SimpleNamespace(title="아마존 실적·AWS 성장", axis="B", members=[])]
    asyncio.run(report_axes.run_axes_flow(
        clusters=clusters, anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _Role(st, log), model="m",
        eff=None, live_research=False))
    # _Role의 split은 "SOX 강세"만 배정 — 아마존은 미배정
    for ax in ("macro", "topic1"):
        p = next(pp for n, _, pp in log if n == f"pheno_{ax}")
        assert "[미배정 관측" in p, ax
        assert "아마존 실적·AWS 성장" in p, ax


def test_ticker_only_beneficiary_name_mapped():
    """2026-08-03-1호 실측: 수혜 종목 name이 '005930.KS'·'GOOGL' 등 티커 단독 —
    같은 회차 안에서도 '삼성전자 (005930.KS)'와 혼재. 코드 백스톱으로 알려진
    티커는 '회사명 (티커)'로 치환한다."""
    fix = report_axes._fix_beneficiary_name
    assert fix("005930.KS") == "삼성전자 (005930.KS)"
    assert fix("000660.KS") == "SK하이닉스 (000660.KS)"
    assert fix("GOOGL") == "알파벳 (GOOGL)"
    assert fix("삼성전자 (005930.KS)") == "삼성전자 (005930.KS)"   # 정상 형식 불변
    assert fix("전력 인프라") == "전력 인프라"                     # 섹터명 불변
    assert fix("ZZZZ9") == "ZZZZ9"                                # 미지 티커 — 원형 유지


def test_flow_maps_ticker_names_in_cards(monkeypatch):
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []

    class _TickerRole(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            n = getattr(response_format, "__name__", "")
            if n == "_ScenariosOut":
                self.log.append((self.name, timeout, prompt))
                return response_format(scenarios=[
                    {"polarity": "positive", "thesis": "A면 좋다",
                     "beneficiaries": [
                         {"name": "005930.KS", "kind": "stock", "direction": "direct",
                          "polarity": "benefit", "rationale": "직접", "financials": "",
                          "causalChain": "수요 → 매출", "evidence": "삼성전자 수주 공시"},
                         {"name": "장비", "kind": "sector", "direction": "indirect",
                          "polarity": "benefit", "rationale": "간접", "financials": "",
                          "causalChain": "매출 → 투자", "evidence": "투자 자료"}]},
                    {"polarity": "negative", "thesis": "B면 나쁘다",
                     "beneficiaries": [
                         {"name": "반도체", "kind": "sector", "direction": "direct",
                          "polarity": "damage", "rationale": "직접", "financials": "",
                          "causalChain": "수요 → 매출", "evidence": "수요 자료"},
                         {"name": "장비", "kind": "sector", "direction": "indirect",
                          "polarity": "damage", "rationale": "간접", "financials": "",
                          "causalChain": "매출 → 투자", "evidence": "투자 자료"}]}])
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, _, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _TickerRole(st, log), model="m",
        eff=None, live_research=False))
    b = cards[0].scenarios[0].beneficiaries[0]
    assert b.name == "삼성전자 (005930.KS)"
    # 프롬프트에도 형식 강제 문구
    scen_prompt = next(p for n, _, p in log if n == "scen_macro")
    assert "회사명 (티커)" in scen_prompt


def test_cases_block_uses_casematch_schema(monkeypatch):
    """과거사례 주입은 CaseMatch 실스키마(episode_id·next_phase_labels·evidence)
    로 포맷 — 존재하지 않는 title/summary를 읽어 v2 전환 후 빈 블록("- : ")만
    주입돼 온 실측(08-10) 재발 차단."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []
    cases = [{"episode_id": "mem-2018-2019-memory-downcycle",
              "matched_phase_order": 1,
              "next_phase_labels": ["재고 급증", "가격 급락"],
              "evidence": [{"source": "MU 콜", "grade": "A",
                            "quote": "고객 재고 조정이 시작됐다",
                            "url": "", "knowable_at": "2018-12-19"}]}]
    asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=cases, role_factory=lambda st: _Role(st, log), model="m",
        eff=None, live_research=False))
    mem_prompt = next(p for n, _, p in log if n == "pheno_topic1")
    assert "mem-2018-2019-memory-downcycle" in mem_prompt
    assert "재고 급증 → 가격 급락" in mem_prompt
    assert "고객 재고 조정이 시작됐다" in mem_prompt
    assert "- : " not in mem_prompt                    # 빈 블록 재발 방지
    macro_prompt = next(p for n, _, p in log if n == "pheno_macro")
    assert "mem-2018-2019" not in macro_prompt         # 메모리 축에만 주입


def test_sweep_accepts_rounded_material_numbers():
    """반올림 표기 허용(08-06~10 매회 오탐 실측) — 재료 11.40609를 본문 11.41로.
    단 정수 토큰·부호 뒤집힘·%교차는 계속 잡는다(창작 탐지 유지)."""
    sweep = report_axes.sweep_unverified_numbers
    mat = "DDR5 11.40609USD/GB, DDR4 8.40532USD/GB, 지수 26,393.657pt, 하락 -1.70932%"
    assert sweep("리테일 11.41USD·8.41USD〔근거: Keepa〕", mat) == []
    assert sweep("지수 26,393.66pt〔근거: YF〕", mat) == []
    assert sweep("낙폭 -1.71%였다〔근거: YF〕", mat) == []      # 부호 일치 반올림
    assert sweep("반등 +1.71%였다〔근거: YF〕", mat) == ["+1.71%"]  # 뒤집힘은 불허
    assert sweep("수익률 43%다〔근거: X〕", mat + " 43.4% 상승") == ["43%"]  # 정수 불허
    assert sweep("점유율 11.41%다〔근거: X〕", mat) == ["11.41%"]   # %↔비% 교차 불허


def test_unassigned_cluster_numbers_are_material(monkeypatch):
    """배정 밖 클러스터의 실수치가 focus 경유로 본문에 와도 오탐하지 않는다
    (08-09-2 WTI 78.08 '미확인' 표식 발행 실측). 검증 재료 = 창 안 관측 전체."""
    monkeypatch.setattr(report_axes, "_SCENARIOS_TIMEOUT", 0.1)
    log = []
    clusters = [SimpleNamespace(title="SOX 강세", axis="A", members=[]),
                SimpleNamespace(title="WTI 78.08달러 급등", axis="B", members=[])]

    class _EchoUnassigned(_Role):
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            if getattr(response_format, "__name__", "") == "_PhenomenonOut" \
                    and self.name == "pheno_topic2":
                self.log.append((self.name, timeout, prompt))
                return response_format(title="유가 급등",
                                       phenomenon_md="- WTI 78.08달러〔근거: 관측〕")
            return await super().run(prompt, instructions=instructions,
                                     response_format=response_format,
                                     effort=effort, timeout=timeout)

    cards, errors, _ = asyncio.run(report_axes.run_axes_flow(
        clusters=clusters, anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=[], role_factory=lambda st: _EchoUnassigned(st, log), model="m",
        eff=None, live_research=False))
    oth = next(c for c in cards if c.axis == "topic2")
    assert "〔수치 검증" not in oth.phenomenon
    assert not any("pheno_topic2" in e and "수치 미확인" in e for e in errors)


def test_round_match_half_digit_and_zero_sign():
    """반치수 오차 허용(11.405→11.40/11.41 모두) + 0 부근 부호 무력화 차단."""
    sweep = report_axes.sweep_unverified_numbers
    assert sweep("가격 11.41USD〔근거: K〕", "가격 11.405USD") == []
    assert sweep("가격 11.40USD〔근거: K〕", "가격 11.405USD") == []
    assert sweep("반등 +1.25%〔근거: Y〕", "하락 -1.2489%") == ["+1.25%"]  # 부호 유지
    assert sweep("보합 +0.00%〔근거: Y〕", "변동 -0.001%") == []           # 0은 방향 무의미


class _DynamicTopicRole:
    """topics_v1 흐름의 완전한 구조를 돌리는 계약 fake."""

    def __init__(self, name, log, *, invalid_topic1_once=False,
                 invalid_topic2_always=False):
        self.name = name
        self.log = log
        self.invalid_topic1_once = invalid_topic1_once
        self.invalid_topic2_always = invalid_topic2_always

    async def run(self, prompt, instructions="", *, response_format=None,
                  effort=None, timeout=None):
        self.log.append((self.name, timeout, prompt))
        n = getattr(response_format, "__name__", "")
        if n == "_AxisPlanOut":
            return response_format(
                lead_axis="topic2",
                axes=[
                    {"axis": "macro", "label": "거시", "topic_key": "macro",
                     "focus": "금리와 달러", "event_titles": ["SOX 강세"],
                     "why_important": "광범위한 할인율 영향", "rank": 3,
                     "memory_related": False},
                    {"axis": "topic1", "label": "전력망", "topic_key": "ai-power-grid",
                     "focus": "AI 전력 수요", "event_titles": ["SOX 강세"],
                     "why_important": "설비투자 전이", "rank": 2,
                     "memory_related": False},
                    {"axis": "topic2", "label": "HBM 수요", "topic_key": "memory-cycle",
                     "focus": "HBM 수요 변화", "event_titles": ["SOX 강세"],
                     "why_important": "반도체 이익 전이", "rank": 1,
                     "memory_related": True},
                ],
            )
        if n == "_PhenomenonOut":
            return response_format(
                title=f"{self.name} 감사 제목",
                phenomenon_md="- 확인된 현상\n\n조건별 해석.",
                watch_signals=["다음 신호"],
            )
        if n == "_ScenariosOut":
            invalid = (self.name == "scen_topic1" and self.invalid_topic1_once) \
                or (self.name.startswith("scen_topic2") and self.invalid_topic2_always)
            if invalid:
                return response_format(scenarios=[
                    {"polarity": "positive", "thesis": "수요가 늘면 개선된다",
                     "beneficiaries": [
                         {"name": "전력 인프라", "kind": "sector",
                          "direction": "direct", "polarity": "benefit",
                          "rationale": "수요가 수주로 전이", "financials": "",
                          "causalChain": "수요 증가 → 수주 증가", "evidence": "수요 전망"},
                     ]},
                ])
            return response_format(scenarios=[
                {"polarity": "positive", "thesis": "수요가 늘면 개선된다",
                 "beneficiaries": [
                     # 잘못 stock으로 분류된 섹터명은 안전하게 sector로 강등한다.
                     {"name": "전력 인프라", "kind": "stock", "direction": "direct",
                      "polarity": "benefit", "rationale": "수주 증가", "financials": "",
                      "causalChain": "수요 증가 → 수주 증가", "evidence": ""},
                     {"name": "산업재", "kind": "sector", "direction": "indirect",
                      "polarity": "benefit", "rationale": "투자 증가", "financials": "",
                      "causalChain": "수주 증가 → 설비 투자", "evidence": "투자 계획"},
                 ]},
                {"polarity": "negative", "thesis": "금리가 오르면 지연된다",
                 "beneficiaries": [
                     {"name": "전력 인프라", "kind": "sector", "direction": "direct",
                      "polarity": "damage", "rationale": "발주 지연", "financials": "",
                      "causalChain": "금리 상승 → 발주 지연", "evidence": "금리 민감도"},
                     {"name": "산업재", "kind": "sector", "direction": "indirect",
                      "polarity": "damage", "rationale": "가동률 하락", "financials": "",
                      "causalChain": "발주 지연 → 가동률 하락", "evidence": "가동률"},
                 ]},
            ])
        if n == "_CardAuditOut":
            return response_format(ok=True)
        raise AssertionError(f"unexpected format {n}")


def test_axis_split_ranks_dynamic_topics_and_repairs_duplicate_topic_keys():
    class _DuplicateKeys:
        async def run(self, prompt, instructions="", *, response_format=None,
                      effort=None, timeout=None):
            return response_format(lead_axis="topic1", axes=[
                {"axis": "macro", "label": "거시", "topic_key": "macro",
                 "focus": "금리", "event_titles": [], "why_important": "할인율",
                 "memory_related": False, "rank": 2},
                {"axis": "topic1", "label": "전력망", "topic_key": "ai-infra",
                 "focus": "전력 수요", "event_titles": ["SOX 강세"],
                 "why_important": "설비투자", "memory_related": False, "rank": 1},
                {"axis": "topic2", "label": "반도체 장비", "topic_key": "ai-infra",
                 "focus": "장비 주문", "event_titles": ["장비 수주"],
                 "why_important": "이익 전이", "memory_related": False, "rank": 3},
            ])

    kwargs = dict(clusters=_clusters(), macro_block="", anchors=[_anchor()],
                  f2_titles=[], role=_DuplicateKeys())
    first = asyncio.run(report_axes.axis_split(**kwargs)).output
    second = asyncio.run(report_axes.axis_split(**kwargs)).output

    assert list(first) == ["macro", "topic1", "topic2"]
    assert first["macro"].label == "거시" and first["macro"].topic_key == "macro"
    assert first["topic1"].rank == 1 and first["topic1"].is_lead is True
    assert first["topic2"].topic_key not in {"topic1", "topic2", "ai-infra"}
    assert first["topic2"].topic_key == second["topic2"].topic_key
    assert len({p.topic_key for p in first.values()}) == 3


def test_flow_matches_continuity_by_topic_key_and_gates_case_memory():
    log = []
    cases = [{"episode_id": "mem-cycle-case", "matched_phase_order": 1,
              "next_phase_labels": ["재고 조정"], "evidence": []}]
    prev = {
        # 직전에는 같은 주제가 topic1이었다. 이번에는 topic2로 이동한다.
        "memory-cycle": {"id": "2026-09-03-2",
                         "generatedAt": "2026-09-03T18:30:00+09:00",
                         "title": "직전 HBM 제목", "watch_signals": ["재고"],
                         "deep_dive_topic": ""},
        "unrelated-topic": {"id": "2026-09-03-2", "generatedAt": "",
                            "title": "주제 불일치 제목", "watch_signals": [],
                            "deep_dive_topic": ""},
    }
    result = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[],
        cases=cases, role_factory=lambda st: _DynamicTopicRole(st, log), model="m",
        eff=None, live_research=False, prev_cards=prev))

    assert len(result) == 3
    cards, errors, lead_axis = result
    assert not errors
    assert [c.axis for c in cards] == ["macro", "topic1", "topic2"]
    assert [(c.label, c.topicKey) for c in cards] == [
        ("거시", "macro"), ("전력망", "ai-power-grid"), ("HBM 수요", "memory-cycle")]
    assert lead_axis == "topic2"
    prompts = {name: prompt for name, _, prompt in log if name.startswith("pheno_")}
    assert "직전 HBM 제목" in prompts["pheno_topic2"]
    assert "mem-cycle-case" in prompts["pheno_topic2"]
    assert "직전 HBM 제목" not in prompts["pheno_topic1"]
    assert "주제 불일치 제목" not in prompts["pheno_topic1"]
    assert "mem-cycle-case" not in prompts["pheno_topic1"]
    assert "mem-cycle-case" not in prompts["pheno_macro"]


def test_scenario_contract_retry_degrades_failure_and_falls_back_lead():
    log = []
    result = asyncio.run(report_axes.run_axes_flow(
        clusters=_clusters(), anchors=[_anchor()], macro_block="", f2_titles=[], cases=[],
        role_factory=lambda st: _DynamicTopicRole(
            st, log, invalid_topic1_once=True, invalid_topic2_always=True),
        model="m", eff=None, live_research=False))

    assert len(result) == 3
    cards, errors, lead_axis = result
    by_axis = {c.axis: c for c in cards}
    # rank 1 topic2가 계약 위반으로 죽으면 rank 2 topic1이 리드가 된다.
    assert lead_axis == "topic1"
    assert not by_axis["topic1"].error
    assert {s.polarity for s in by_axis["topic1"].scenarios} == {"positive", "negative"}
    assert all({b.direction for b in s.beneficiaries} == {"direct", "indirect"}
               for s in by_axis["topic1"].scenarios)
    assert by_axis["topic1"].scenarios[0].beneficiaries[0].kind == "sector"
    assert by_axis["topic2"].error
    assert by_axis["topic2"].scenarios == []
    assert by_axis["topic2"].label == "HBM 수요"
    assert by_axis["topic2"].topicKey == "memory-cycle"
    retry_prompts = {name: prompt for name, _, prompt in log if name.endswith("_retry")}
    assert "시나리오 계약 검증 실패" in retry_prompts["scen_topic1_retry"]
    assert "시나리오 계약 검증 실패" in retry_prompts["scen_topic2_retry"]
    macro_prompt = next(prompt for name, _, prompt in log if name == "scen_macro")
    assert "메모리 기업을 기본 수혜자로" in macro_prompt
    assert any("scen_topic2" in error and "계약" in error for error in errors)
