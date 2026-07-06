"""PLAN 스테이지 — 답변 전 선행작업 (병렬 2콜 A/B → G0 코드 게이트).

A(Fable·low): 질문 이해 묶음 — 재작성·tier·시점·쪼개기·대조질의·필요증거·검색어
B(mini·low): 기계 추출 — 기간 후보·지표·티커 보완·richness + tier/시점 교차판정
G0(코드): 병합·검증 — tier/시점 불일치 보수 채택, news_mode 유도, tier4 2단 확인,
          재작성 엔티티 보존, 티커 2차 매칭, 유닛 상한
"""

from __future__ import annotations

import asyncio
import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from contracts import (
    EvidenceRichness,
    FiscalPeriod,
    NeededEvidence,
    PlanPacket,
    SubQuestion,
    TickerCandidate,
)
from providers import Role
from tools.price.yahoo import _load_universe

TODAY = date.today().isoformat()


class _SO(BaseModel):
    """structured output용 베이스 — additionalProperties:false 강제 (OpenAI strict + Anthropic)."""

    model_config = ConfigDict(extra="forbid")

# 실행 동사 — tier4 2단 확인용 (주문/실행 지시)
_ORDER_VERBS = re.compile(r"(사줘|팔아|매도해|매수해|주문|체결|이체|출금|넣어줘|처분해)")


# ---- LLM 응답 부분 스키마 (A/B 콜) ----
# 주의: structured output(OpenAI strict + Anthropic)은 자유 dict/제약(min·max) 미지원.
# 중첩은 typed 모델, 정수 범위는 코드에서 clamp.

class _SubQ(_SO):
    id: str
    text: str
    depends_on: str | None = None


class _NeedEv(_SO):
    entity: str
    metric: str
    period: str = ""
    source_type: str = "news"
    required: bool = True
    obtainability: str = "public"


class _FiscalP(_SO):
    expression: str
    calendar_period: str | None = None
    last_reported_period: str | None = None
    basis: str = "unclear"
    resolved: bool = False


class _TickerSup(_SO):
    name: str
    yahoo_symbol: str


class _PlanA(_SO):
    standalone_question: str
    tier: int  # 0-4 (min/max 미지원 → 코드 clamp)
    event_time_start: str | None = None
    event_time_end: str | None = None
    knowledge_cutoff: str = TODAY
    sub_questions: list[_SubQ] = Field(default_factory=list)
    contrast_questions: list[str] = Field(default_factory=list)
    needed_evidence: list[_NeedEv] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)


class _PlanB(_SO):
    fiscal_periods: list[_FiscalP] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    tickers_supplement: list[_TickerSup] = Field(default_factory=list)
    unresolved_entities: list[str] = Field(default_factory=list)
    richness_grade: str = "B"
    tier_opinion: int = 1  # 0-4 (코드 clamp)
    cutoff_opinion: str = TODAY


_PROMPT_A = """너는 금융 QA의 계획(PLAN) 단계다. 질문에 답하지 마라. 작업 계획만 만든다.
지어내지 마라. 불확실하면 비워라. 원 질문의 의도를 바꾸지 마라.

- standalone_question: 대화 이력의 지시어("그럼","그거")를 독립 질문으로 재작성. 위험하면 원문 유지.
- tier: 0 설명 / 1 사실찾기 / 2 계산·비교·원인 / 3 판단(살만해?) / 4 주문·실행. 가정적 매매 계산은 3. 애매하면 높은 쪽.
- knowledge_cutoff: 기본 오늘({today}). 명시적 백테스트만 과거.
- sub_questions: 서로 다른 증거가 필요한 축이 2개+일 때만 쪼갠다(tier0-1≤2, tier2≤4, tier3≤5). 각 {{id:"q1",text,depends_on:앞질문id|null}}. 검색 한 번으로 답하면 빈 배열.
- contrast_questions: 원인/판단 질문에만 1~2개 (반대 방향). 검색 전용.
- needed_evidence: 답에 필요한 사실 3~7개. 각 {{entity,metric,period,source_type:news|price|macro|web|company,required:bool,obtainability:public|estimated|unavailable}}. 미공시는 unavailable.
- search_queries: 전체 질문용 검색어 1~2개. 종목 정식명+연도, 구어체 제거."""

_PROMPT_B = """너는 금융 질문에서 정형 정보를 추출한다. 답하지 마라. 길게 추론하지 마라. 보이는 것만.

- fiscal_periods: 기간 표현을 {{expression, calendar_period, last_reported_period, basis:calendar|reported|unclear, resolved:bool}}. "지난 분기"는 확정하지 말고 unclear.
- metrics: 필요 계산 목록("기간 수익률","영업이익률 yoy(pp)"). 없으면 빈 배열.
- tickers_supplement: 사전에 없는 종목만 야후 심볼로 {{name, yahoo_symbol}} (애플→AAPL). 확신 없으면 unresolved_entities에 이름만.
- richness_grade: A(대형주·유명) / B(중형) / C(소형·희소).
- tier_opinion, cutoff_opinion: 질문 종류(0-4)와 지식시점을 독립 판정(교차확인용)."""


def _prematch_tickers(text: str) -> list[TickerCandidate]:
    """사전 코드 매칭 — universe_kospi 결정적. 지주사 그룹명은 confidence 낮춤."""
    uni = _load_universe()
    out: list[TickerCandidate] = []
    seen: set[str] = set()
    # 정확 종목명 우선, 그다음 부분 포함
    for it in uni:
        name = it.get("name", "")
        if name and name in text and name not in seen:
            code = it.get("code")
            out.append(TickerCandidate(
                name=name, code=code, yahoo_symbol=f"{code}.KS",
                confidence="high", source="dict_match",
            ))
            seen.add(name)
    return out[:5]


async def run_plan(question: str, history: list | None = None,
                   overrides: dict | None = None) -> PlanPacket:
    """PLAN 실행 — 실제 A/B LLM 콜 + G0 코드 병합. never-raise는 오케스트레이터가."""
    prematched = _prematch_tickers(question)
    ctx = f"[오늘] {TODAY}\n[질문] {question}"
    if history:
        turns = "\n".join(f"- {t.get('role')}: {str(t.get('content',''))[:200]}" for t in history[-4:])
        ctx = f"[오늘] {TODAY}\n[대화 이력]\n{turns}\n[질문] {question}"

    role_a = Role("planner", overrides)
    role_b = Role("plan_extract", overrides)
    a, b = await asyncio.gather(
        role_a.run(ctx, _PROMPT_A.format(today=TODAY), response_format=_PlanA),
        role_b.run(ctx, _PROMPT_B, response_format=_PlanB),
        return_exceptions=True,
    )
    # A(질문이해)가 실패하면 원문 기반 최소 계획으로 폴백 (never-raise)
    if isinstance(a, BaseException):
        a = _PlanA(standalone_question=question, tier=2, knowledge_cutoff=TODAY)
    if isinstance(b, BaseException):
        b = _PlanB()

    return _g0_merge(question, prematched, a, b)


def _g0_merge(question: str, prematched: list[TickerCandidate],
              a: _PlanA, b: _PlanB) -> PlanPacket:
    """G0 게이트 — 순수 코드 병합·검증."""
    notes: list[str] = []

    # tier: A·B 불일치 시 보수적(높은 쪽) 채택. LLM 값 clamp (SO 제약 못 걸어서)
    a_tier = max(0, min(4, a.tier))
    b_tier = max(0, min(4, b.tier_opinion))
    tier = max(a_tier, b_tier)
    if a_tier != b_tier:
        notes.append(f"tier 불일치 A={a_tier} B={b_tier} → {tier}(높은쪽)")

    # tier4 2단 확인 — 실행 동사 없으면 강등 (오차단 방지)
    if tier == 4 and not _ORDER_VERBS.search(question):
        tier = 3
        notes.append("tier4 판정이나 실행동사 없음 → 3 강등")

    # knowledge_cutoff: 불일치 시 원문 기준(오늘) 보수 채택
    cutoff = a.knowledge_cutoff or TODAY
    if a.knowledge_cutoff != b.cutoff_opinion:
        cutoff = TODAY if not re.search(r"20\d\d", question) else a.knowledge_cutoff
        notes.append(f"cutoff 불일치 → {cutoff}")

    # news_mode 유도 (코드)
    if tier == 0 and not a.sub_questions:
        news_mode = "off"
    elif cutoff < TODAY:
        news_mode = "archive"
    else:
        news_mode = "live"

    # standalone 엔티티 보존 검사 — 원문 종목이 재작성에서 사라지면 원문 유지
    standalone = a.standalone_question or question
    for tc in prematched:
        if tc.name in question and tc.name not in standalone:
            standalone = question
            notes.append("재작성이 종목명 누락 → 원문 유지")
            break

    # 티커: 사전매칭 + LLM 보완 (unverified 플래그)
    tickers = list(prematched)
    known = {t.name for t in tickers}
    for sup in b.tickers_supplement:
        if sup.name and sup.yahoo_symbol and sup.name not in known:
            tickers.append(TickerCandidate(
                name=sup.name, yahoo_symbol=sup.yahoo_symbol, confidence="low",
                source="llm", verified=False,
            ))

    # 유닛 상한 — 서브질문 ≤5 (전체질문 포함 ≤6)
    subs = []
    for i, sq in enumerate(a.sub_questions[:5]):
        subs.append(SubQuestion(
            id=sq.id or f"q{i+1}", text=sq.text, depends_on=sq.depends_on or None,
        ))

    _VALID_ST = {"news", "price", "macro", "web", "company"}
    needed = []
    for ne in a.needed_evidence:
        st = ne.source_type if ne.source_type in _VALID_ST else "news"
        ob = ne.obtainability if ne.obtainability in {"public", "estimated", "unavailable"} else "public"
        try:
            needed.append(NeededEvidence(
                entity=ne.entity, metric=ne.metric, period=ne.period,
                source_type=st, required=ne.required, obtainability=ob,  # type: ignore[arg-type]
            ))
        except Exception:
            continue

    fiscal = []
    for fp in b.fiscal_periods:
        basis = fp.basis if fp.basis in {"calendar", "reported", "unclear"} else "unclear"
        try:
            fiscal.append(FiscalPeriod(
                expression=fp.expression, calendar_period=fp.calendar_period,
                last_reported_period=fp.last_reported_period,
                basis=basis, resolved=fp.resolved,  # type: ignore[arg-type]
            ))
        except Exception:
            continue

    return PlanPacket(
        tier=tier,
        original_question=question,
        standalone_question=standalone,
        event_time_start=a.event_time_start,
        event_time_end=a.event_time_end,
        knowledge_cutoff=cutoff,
        tickers=tickers,
        unresolved_entities=b.unresolved_entities,
        sub_questions=subs,
        search_queries=a.search_queries[:3],
        contrast_questions=a.contrast_questions[:2],
        needed_evidence=needed,
        news_mode=news_mode,  # type: ignore[arg-type]
        fiscal_periods=fiscal,
        metrics=b.metrics,
        richness=EvidenceRichness(grade=b.richness_grade if b.richness_grade in "ABC" else "B", prelim=True),
        g0_notes=notes,
    )
