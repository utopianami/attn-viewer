"""v2 3축 카드 파이프라인 — 매크로 / 메모리 / 그 외 최중요 (2026-07-24 재설계).

사용자 지시: 기존 결과물(주장·최종의견·종합·완결 글) 제거, 카드 3장 교체.
각 축: 현상 분석 → (필요시) 주제 선정 후 추가 연구(웹) → 긍정/부정 시나리오
→ 시나리오별 직접/간접 수혜(피해) 섹터·종목 (+필요시 재무·현황).

설계: docs/superpowers/specs/2026-07-24-axes-report-redesign.md (codex r1 반영).
축별 never-raise — 실패 축은 error 카드로 발행, 전체 리포트는 죽지 않는다.
"""
from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel, Field

from sector.report_contracts import (AxisBeneficiary, AxisCard, AxisScenario,
                                     ResearchQuestion, StageIO, StageResult)
from sector.report_synthesis import _fmt_anchor  # 비교 종류(MoM/QoQ/YoY) 명시 — 감사 4.1 재발 차단

_AXES = ("macro", "memory", "other")
_AXIS_LABEL = {"macro": "매크로(거시)", "memory": "메모리 섹터", "other": "그 외 최중요 이슈"}

# 스테이지 상한(초) — 합계 최악 8,700s < 스케줄러 하드캡 3h (codex r1 H1)
_SPLIT_TIMEOUT = 1200.0   # 900s 실측 타임아웃(스모크 1회차) — CLI opus high 대형 프롬프트 여유
_PHENOMENON_TIMEOUT = 800.0
_RESEARCH_TIMEOUT = 1000.0     # 축당 — 질문 ≤2 × 360s + 여유
_SCENARIOS_TIMEOUT = 800.0
# CLI 다리 몫(초) — report_article 체인은 CLI(기본 600s)→API 폴백 2단인데, CLI가
# 파싱 재시도까지 하면 혼자 스테이지 예산을 소진해 API 폴백이 아예 못 뛴다
# (07-26~27 5회 연속 axis_split 1200s·scen_other 800s 타임아웃 실측). 스테이지
# 예산의 절반 이하로 잘라 폴백 시간을 보장한다.
_SPLIT_CLI_S = 480.0
_PHENO_CLI_S = 360.0
_SCEN_CLI_S = 360.0

STYLE = """[스타일 규칙 — 전 카드 공통]
- 모든 수치에 〔근거: 출처〕/〔가정〕/〔계산: 식 = 결과〕 라벨. 증감률은 비교 기준
  (MoM/QoQ/YoY·기간)을 분모와 함께 병기.
- 내부 프레임 용어(국면N, 사례 축 이름 등) 금지 — 자연어로만. 업계 용어·티커·회사
  약칭은 첫 언급에서 한 줄 정의.
- 면책·투자 권유 고지 금지. 평서체("~다"). 문단 2~3문장, 초단문 펀치라인 허용.
- 추측 금지 — 확인 못 한 것은 〔가정〕 라벨로 정직하게. 없는 수치를 만들지 마라."""


# ── [1] axis_split — 관측을 3축으로 배정 ─────────────────────────────────────
class _AxisPlanItem(BaseModel):
    axis: str = ""                 # macro | memory | other
    focus: str = ""                # 이 축의 핵심 현상 후보(수치 포함 한두 문장)
    event_titles: list[str] = Field(default_factory=list)
    why_important: str = ""        # other 축: 왜 이게 나머지 중 최중요인가


class _AxisPlanOut(BaseModel):
    axes: list[_AxisPlanItem] = Field(default_factory=list)


async def axis_split(clusters, macro_block: str, anchors, f2_titles: list[str],
                     *, role) -> StageResult:
    io = StageIO(key="axis_split", label="축 배정 — 매크로/메모리/그 외")
    t0 = time.monotonic()
    parts = ["[이벤트 클러스터 (12시간)]"]
    parts += [f"- {c.title} ({c.axis})" for c in clusters]
    if macro_block:
        parts.append("\n" + macro_block)
    if f2_titles:
        # f1 관련성 필터가 비메모리 최중요 이슈를 걸렀을 수 있다 — 원시 뉴스 제목을
        # 보충 공급(codex r1 H2 → r2 H2: f2가 아니라 f1 이전 원시 제목이어야 복구 가능)
        parts.append("\n[원시 뉴스 제목(필터 이전) — '그 외' 축 후보 보충]")
        parts += [f"- {t}" for t in f2_titles[:60]]
    parts.append("\n[수치 앵커 요약]")
    parts += [f"- {_fmt_anchor(a)}" for a in anchors[:20]]
    parts.append("""
[할 일]
위 관측을 정확히 3개 축으로 배정하라:
1. axis="macro" — 거시(지수·금리·환율·유가·통화정책·무역)에 집중한 현상.
2. axis="memory" — 메모리 반도체 관점의 현상.
3. axis="other" — 위 둘에 안 담긴 이슈 중 **가장 중요한 것 1개**
   (why_important에 선정 근거 — 시장 영향·수치로).
각 축: focus(핵심 현상 후보 — 반드시 수치 포함), event_titles(배정 이벤트 제목,
위 목록의 표현 그대로). 같은 이벤트를 macro와 memory 두 축에 넣는 것은 허용하나
(관점이 다르면), other에는 두 축과 **겹치지 않는** 이벤트만 넣어라 — 거시 지표나
메모리 반도체가 주인공인 이슈를 other로 중복 선정하지 마라.""")
    try:
        # effort medium — 편집(배정) 작업. high는 CLI 파싱 실패 재시도와 겹쳐
        # 1200s 스테이지 예산을 소진(스모크·21:00 회차 2연속 실측)
        res = await role.run("\n".join(parts), instructions="시황 편집장 — 축 배정.",
                             response_format=_AxisPlanOut, effort="medium",
                             timeout=_SPLIT_CLI_S)
        plans = {p.axis: p for p in res.axes if p.axis in _AXES}
        io.in_count, io.out_count = len(clusters), len(plans)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=plans, io=io)
    except Exception as exc:  # noqa: BLE001
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output={}, io=io, error=str(exc))


# ── [2a] phenomenon — 축별 현상 분석 + 추가 연구 판단 ────────────────────────
class _PhenoQuestion(BaseModel):
    """자유형 dict 금지 — anthropic 구조화 출력 400(codex H1과 동일 계열)."""
    question: str = ""
    why_needed: str = ""
    expected_form: str = ""
    search_hint: str = ""


class _PhenomenonOut(BaseModel):
    title: str = ""                # 수치 포함 카드 헤드라인
    phenomenon_md: str = ""        # 현상 분석 markdown
    deep_dive_topic: str = ""      # 추가 연구가 필요하면 주제 한 줄, 아니면 ""
    research_questions: list[_PhenoQuestion] = Field(default_factory=list)
    watch_signals: list[str] = Field(default_factory=list)


async def phenomenon(axis: str, plan: _AxisPlanItem, clusters, anchors,
                     macro_block: str, cases, *, role,
                     f2_titles: list[str] | None = None) -> StageResult:
    io = StageIO(key=f"pheno_{axis}", label=f"현상 분석 — {_AXIS_LABEL[axis]}")
    t0 = time.monotonic()
    titles = set(plan.event_titles)
    parts = [STYLE, f"\n[담당 축] {_AXIS_LABEL[axis]}",
             f"[핵심 현상 후보] {plan.focus}"]
    if axis == "other" and plan.why_important:
        parts.append(f"[선정 근거] {plan.why_important}")
    if axis == "other":
        # 방어선 — axis_split 실패 시 f1(메모리 관련성) 통과 클러스터만 남아
        # 메모리·거시 주제가 '기타'로 새는 운영 실측(07-25~28 '기타' 카드 7건 중
        # 6건이 DDR/SK하이닉스/CXMT/환율). 배정 유무와 무관하게 상시 주입.
        parts.append(
            "[축 경계] 거시(지수·금리·환율·유가·통화정책)와 메모리 반도체(DRAM·"
            "NAND·HBM, 메모리 제조사·장비·소재)는 별도 카드가 다룬다 — 그 주제가"
            " 주인공인 이슈는 이 축에서 제외하고, 나머지 이슈 중 시장 영향이 가장"
            " 큰 것 1개에 집중하라.")
    parts.append("\n[배정 관측 — 제목·발췌]")
    hit = 0
    for c in clusters:
        members = list(getattr(c, "members", []))
        if plan.event_titles and c.title not in titles \
                and not any(getattr(m, "title", "") in titles for m in members):
            continue
        hit += 1
        parts.append(f"- {c.title}")
        for m in members[:3]:
            ex = (getattr(m, "excerpt", "") or "")[:200]
            parts.append(f"    · {getattr(m, 'title', '')} — {ex}")
    if not hit:                                   # 배정 제목 미매칭 — 전체 제공
        for c in clusters:
            parts.append(f"- {c.title} ({c.axis})")
    if axis == "other" and f2_titles:
        # 원시 제목 보충 — 위 클러스터는 f1 통과분(메모리 중심)이라 비메모리
        # 최중요 이슈가 없을 수 있다(axis_split의 r2 H2와 같은 논리, 여기도 적용)
        parts.append("\n[원시 뉴스 제목(필터 이전) — 후보 보충]")
        parts += [f"- {t}" for t in f2_titles[:60]]
    if macro_block and axis == "macro":
        parts.append("\n" + macro_block)
        parts.append("⚠중요 표시 항목은 팩트 불릿에 반드시 포함하라.")
    parts.append("\n[수치 앵커 — 본문 수치는 여기 값·명시적 〔계산〕/〔가정〕만."
                 " 증감률 인용 시 괄호의 비교 종류(MoM/QoQ/YoY)를 그대로 표기]")
    parts += [f"- {_fmt_anchor(a)}" for a in anchors]
    if cases and axis == "memory":
        parts.append("\n[과거 유사 국면 참고]")
        for cs in cases[:3]:
            parts.append(f"- {cs.get('title', '')}: {str(cs.get('summary', ''))[:150]}")
    parts.append("""
[할 일]
1. phenomenon_md — 현상 분석 markdown:
   ① 첫 부분: 팩트 불릿 3~5개("무슨 일이 있었나" — 등락·수치가 먼저, 결과론이어도
      기본으로 깔린다) ② 이어서 해석 2~4문단(왜 움직였나, 무엇이 설명 안 되나).
2. title — 수치가 든 카드 헤드라인 한 문장.
3. 이 현상을 제대로 이해하는 데 지금 재료에 **없는** 정보가 필요하면:
   deep_dive_topic(주제 한 줄 — 예: "키미3 아키텍처가 학습 개선인지 인퍼런스
   개선인지, AI 지출 구조에 어떤 의미인지")과 research_questions 1~2개
   (question/why_needed/expected_form/search_hint). 필요 없으면 둘 다 비워라.
4. watch_signals — 이 현상의 다음 전개를 가르는 관찰 신호 2~4개(현재 상태 포함).""")
    try:
        res = await role.run("\n".join(parts),
                             instructions="시황 분석가 — 팩트 먼저, 숫자로 따진다.",
                             response_format=_PhenomenonOut, effort="high",
                             timeout=_PHENO_CLI_S)
        io.out_count = 1
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=res, io=io)
    except Exception as exc:  # noqa: BLE001
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=_PhenomenonOut(), io=io, error=str(exc))


# ── [2c] scenarios — 긍정/부정 + 직접/간접 수혜 ──────────────────────────────
class _ScenarioItem(BaseModel):
    polarity: str = "positive"     # positive | negative
    thesis: str = ""
    beneficiaries: list[AxisBeneficiary] = Field(default_factory=list)


class _ScenariosOut(BaseModel):
    scenarios: list[_ScenarioItem] = Field(default_factory=list)
    deep_dive_conclusion: str = ""  # 연구 결과 종합 결론(연구 없으면 "")


async def scenarios(axis: str, pheno: _PhenomenonOut, findings, anchors,
                    *, role, research_failed: str = "") -> StageResult:
    io = StageIO(key=f"scen_{axis}", label=f"시나리오 — {_AXIS_LABEL[axis]}")
    t0 = time.monotonic()
    parts = [STYLE, f"\n[담당 축] {_AXIS_LABEL[axis]}",
             "\n[현상 분석 — 이 위에서 시나리오를 세운다]", pheno.phenomenon_md]
    ok_findings = [f for f in (findings or []) if not getattr(f, "error", None)]
    if ok_findings:
        parts.append(f"\n[추가 연구 결과 — 주제: {pheno.deep_dive_topic}]"
                     "\n('근거' 라벨은 출처 확인됨, '가정'은 미확인)")
        for f in ok_findings:
            src = "; ".join(s.url for s in getattr(f, "sources", [])[:3]) or "출처 없음"
            parts.append(f"- [{f.label}] {f.answer[:500]}\n  출처: {src}")
    elif pheno.deep_dive_topic:
        # 연구가 필요하다고 판정됐는데 실패/생략 — 침묵하면 미확인 논점이 단정으로
        # 발행된다(codex r2 H3)
        parts.append(f"\n[추가 연구 실패/생략 — 주제: {pheno.deep_dive_topic}"
                     + (f" / 사유: {research_failed}" if research_failed else "") + "]"
                     "\n이 주제와 관련된 논점은 확인되지 않았다 — 반드시 〔가정〕으로"
                     " 서술하고 시나리오 확신을 그만큼 낮춰라. 확인 못 한 사실을"
                     " 근거처럼 쓰지 마라.")
    parts.append("\n[수치 앵커 — 증감률 인용 시 괄호의 비교 종류(MoM/QoQ/YoY)를 그대로 표기]")
    parts += [f"- {_fmt_anchor(a)}" for a in anchors[:25]]
    parts.append("""
[할 일]
1. (연구 결과가 있으면) deep_dive_conclusion — 연구가 현상 해석을 어떻게 바꾸는지
   결론 2~3문장(예: "키미3는 단기 가격을 낮췄지만 딥시크 때와 달리 메모리 수요는
   오히려 늘린다").
2. scenarios — positive / negative 각 1개. thesis는 전개 + **성립 조건**을 명시한
   조건부 서술(단정 금지 — "~면 ~다" 구조).
3. 각 시나리오의 beneficiaries 2~4개 — 직접(direct)/간접(indirect) 구분, 수혜
   (benefit)/피해(damage) 구분, 섹터(sector)/종목(stock, 티커 병기) 구분.
   1차 수혜만 나열하지 말고 **2차 전이 인사이트**를 반드시 포함하라
   (예: 클라우드 CAPEX 증액은 메모리에도 좋지만 전력 인프라에 더 좋다).
   rationale에 전이 경로를 수치 라벨과 함께. 비중 큰 항목은 financials에
   재무·현황 미니 분석(밸류에이션·실적 수치 — 근거 있는 것만, 없으면 빈 값).""")
    try:
        res = await role.run("\n".join(parts),
                             instructions="시나리오 전략가 — 조건부 서술, 전이 경로 중심.",
                             response_format=_ScenariosOut, effort="high",
                             timeout=_SCEN_CLI_S)
        io.out_count = len(res.scenarios)
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=res, io=io)
    except Exception as exc:  # noqa: BLE001
        io.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return StageResult(output=_ScenariosOut(), io=io, error=str(exc))


# ── 오케스트레이션 — 축별 순차, never-raise ──────────────────────────────────
async def run_axes_flow(*, clusters, anchors, macro_block: str, f2_titles: list[str],
                        cases, role_factory, model: str, eff, live_research: bool,
                        stage_cb=None) -> tuple[list[AxisCard], list[str]]:
    """카드 3장 생성. stage_cb(StageResult, items)로 사고흐름 기록.

    실패 격리: 축 하나가 죽어도 나머지 축은 진행 — 죽은 축은 error 카드."""
    errors: list[str] = []

    def _rec(sr: StageResult, items: list[str]):
        if stage_cb is not None:
            try:
                stage_cb(sr, items)
            except Exception:  # noqa: BLE001
                pass

    async def _bounded(coro, seconds: float, fallback: StageResult, name: str):
        try:
            return await asyncio.wait_for(coro, seconds)
        except asyncio.TimeoutError:
            errors.append(f"{name}: 스테이지 타임아웃({int(seconds)}s)")
            fallback.error = "timeout"
            return fallback

    t_flow = time.monotonic()
    # 전역 예산(codex r2 H1): 선행 필터 최악 소요와 스케줄러 하드캡(3h) 사이 여유 —
    # 예산 소진 시 남은 축은 즉시 error 카드로 강등해 리포트 저장을 보장.
    # 6600→6000: 시나리오 타임아웃 재시도 추가로 축당 최악이 +800s 늘어난 보정.
    # axis_split 재시도(+최악 1200s)는 예산 증액 없이 흡수 — 축별 예산 검사가
    # 남은 시간을 지키고, 배정 없는 3장보다 배정 있는 2장이 낫다.
    _FLOW_BUDGET_S = 6000.0

    sp = await _bounded(
        axis_split(clusters, macro_block, anchors, f2_titles,
                   role=role_factory("axis_split")),
        _SPLIT_TIMEOUT,
        StageResult(output={}, io=StageIO(key="axis_split", label="축 배정")),
        "axis_split")
    if sp.error:
        errors.append(f"axis_split: {sp.error}")
    if not (sp.output or {}):
        # 배정 실패는 사유 불문 1회 재시도 — 운영 10/10 회차 타임아웃 실측
        # (07-24~28). 배정 없이 내려가면 '기타' 축이 메모리 주제를 중복 선정한다.
        errors.append("axis_split: "
                      f"{'타임아웃' if sp.error == 'timeout' else '빈 배정'} — 재시도")
        sp2 = await _bounded(
            axis_split(clusters, macro_block, anchors, f2_titles,
                       role=role_factory("axis_split_retry")),
            _SPLIT_TIMEOUT,
            StageResult(output={}, io=StageIO(key="axis_split_retry",
                                              label="축 배정 재시도")),
            "axis_split_retry")
        if sp2.output:
            sp = sp2
    plans = sp.output or {}
    _rec(sp, [f"{k}: {v.focus[:80]}" for k, v in plans.items()])

    cards: list[AxisCard] = []
    for axis in _AXES:
        plan = plans.get(axis) or _AxisPlanItem(axis=axis, focus="", event_titles=[])
        if time.monotonic() - t_flow > _FLOW_BUDGET_S:
            errors.append(f"axis_{axis}: 시간 예산 소진 — 축 생략")
            cards.append(AxisCard(axis=axis, title=_AXIS_LABEL[axis],
                                  error="시간 예산 소진"))
            continue
        try:
            ph = await _bounded(
                phenomenon(axis, plan, clusters, anchors, macro_block, cases,
                           role=role_factory(f"pheno_{axis}"),
                           f2_titles=f2_titles),
                _PHENOMENON_TIMEOUT,
                StageResult(output=_PhenomenonOut(),
                            io=StageIO(key=f"pheno_{axis}", label="현상 분석")),
                f"pheno_{axis}")
            if ph.error:
                errors.append(f"pheno_{axis}: {ph.error}")
            pheno: _PhenomenonOut = ph.output
            _rec(ph, [pheno.title] if pheno.title else [])
            if not pheno.phenomenon_md.strip():
                cards.append(AxisCard(axis=axis, title=_AXIS_LABEL[axis],
                                      error=ph.error or "현상 분석 실패"))
                continue

            findings = []
            research_failed = ""
            questions = []
            for i, q in enumerate(pheno.research_questions[:2]):
                if (q.question or "").strip():
                    questions.append(ResearchQuestion(
                        qid=f"{axis}-q{i}", question=q.question,
                        why_needed=q.why_needed, expected_form=q.expected_form,
                        search_hint=q.search_hint))
            if questions and live_research:
                from sector.report_article import run_research
                rs = await _bounded(
                    run_research(questions, model=model, now=eff),
                    _RESEARCH_TIMEOUT,
                    StageResult(output=[],
                                io=StageIO(key=f"research_{axis}", label="추가 연구")),
                    f"research_{axis}")
                if rs.error:
                    errors.append(f"research_{axis}: {rs.error}")
                    research_failed = rs.error
                findings = rs.output
                if findings and all(getattr(f, "error", None) for f in findings):
                    research_failed = research_failed or "전 질문 실패"
                rs.io.key = f"research_{axis}"
                rs.io.label = f"추가 연구 — {_AXIS_LABEL[axis]}"
                _rec(rs, [f"{f.qid}: {(f.answer or f.error or '')[:100]}"
                          for f in findings])
            elif questions:
                research_failed = "웹 조사 비활성(replay 가드)"

            sc = await _bounded(
                scenarios(axis, pheno, findings, anchors,
                          role=role_factory(f"scen_{axis}"),
                          research_failed=research_failed),
                _SCENARIOS_TIMEOUT,
                StageResult(output=_ScenariosOut(),
                            io=StageIO(key=f"scen_{axis}", label="시나리오")),
                f"scen_{axis}")
            if sc.error:
                errors.append(f"scen_{axis}: {sc.error}")
            so: _ScenariosOut = sc.output
            if not so.scenarios:
                # 빈 시나리오는 사유 불문 1회 재시도 — CLI 구조화 출력 간헐 결함
                # (21:00 회차 memory 축 실측)뿐 아니라 타임아웃(07-27 저녁 scen_other
                # 실측)도 재시도 없이는 그대로 error 카드가 된다.
                errors.append(f"scen_{axis}: "
                              f"{'타임아웃' if sc.error == 'timeout' else '빈 시나리오'}"
                              " — 재시도")
                sc2 = await _bounded(
                    scenarios(axis, pheno, findings, anchors,
                              role=role_factory(f"scen_{axis}_retry"),
                              research_failed=research_failed),
                    _SCENARIOS_TIMEOUT,
                    StageResult(output=_ScenariosOut(),
                                io=StageIO(key=f"scen_{axis}_retry",
                                           label="시나리오 재시도")),
                    f"scen_{axis}_retry")
                if sc2.output.scenarios:
                    so = sc2.output
                    _rec(sc2, [f"{s.polarity}: {s.thesis[:80]}"
                               for s in so.scenarios])
            # 오염 방어: 구조화 출력 결함 시 결론에 XML 조각이 섞임 — 절단
            for marker in ("<parameter", "</deep_dive", "</parameter"):
                if marker in so.deep_dive_conclusion:
                    so.deep_dive_conclusion = \
                        so.deep_dive_conclusion.split(marker)[0].rstrip()
            _rec(sc, [f"{s.polarity}: {s.thesis[:80]}" for s in so.scenarios])

            scen_models = []
            for s in so.scenarios[:3]:
                # 불량 polarity·빈 thesis는 드롭 — positive로 보정하면 "긍정/부정
                # 각 1개" 요구가 조용히 깨진다(codex r2 H4)
                if s.polarity not in ("positive", "negative") or not s.thesis.strip():
                    continue
                scen_models.append(AxisScenario(polarity=s.polarity, thesis=s.thesis,
                                                beneficiaries=s.beneficiaries[:4]))
            pols = {s.polarity for s in scen_models}
            if scen_models and (pols != {"positive", "negative"}
                                or not any(s.beneficiaries for s in scen_models)):
                errors.append(f"scen_{axis}: 시나리오 불완전 — "
                              f"극성 {sorted(pols)}, 수혜 "
                              f"{sum(len(s.beneficiaries) for s in scen_models)}건")
            ok_f = [f for f in findings if not getattr(f, "error", None)]
            deep = {}
            if pheno.deep_dive_topic or ok_f:
                deep = {"topic": pheno.deep_dive_topic,
                        "conclusion": so.deep_dive_conclusion,
                        "findings": [f.model_dump() for f in ok_f]}
                if research_failed:
                    deep["research_failed"] = research_failed
            srcs = [s.model_dump() for f in ok_f for s in f.sources][:8]
            cards.append(AxisCard(
                axis=axis, title=pheno.title or _AXIS_LABEL[axis],
                phenomenon=pheno.phenomenon_md, deep_dive=deep,
                scenarios=scen_models, watch_signals=pheno.watch_signals[:4],
                sources=srcs,
                error="" if scen_models else (sc.error or "시나리오 생성 실패")))
        except Exception as exc:  # noqa: BLE001 — 축 격리
            errors.append(f"axis_{axis}: {exc}")
            cards.append(AxisCard(axis=axis, title=_AXIS_LABEL[axis], error=str(exc)))
    return cards, errors
