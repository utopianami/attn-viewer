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
    search_queries: list[str] = Field(default_factory=list)


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
    market_scope: str = "kr"  # kr|global|mixed (코드 검증)


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
- market_scope: 질문 대상 자산·시장의 소재지. 한국 종목/국내 시장=kr, 해외 종목/해외 시장=global, 한국+해외 비교=mixed.
- sub_questions: 서로 다른 증거가 필요한 축이 2개+일 때만 쪼갠다(tier0-1≤2, tier2≤4, tier3≤5). 각 {{id:"q1",text,depends_on:앞질문id|null,search_queries:[검색어 1~2개]}}. 검색 한 번으로 답하면 빈 배열.
- contrast_questions: 원인/판단 질문에만 1~2개 (반대 방향). 검색 전용.
- needed_evidence: 답에 필요한 사실 3~7개. 각 {{entity,metric,period,source_type:news|price|macro|web|company,required:bool,obtainability:public|estimated|unavailable}}. 미공시는 unavailable.
- search_queries: 전체 질문용 검색어 1~2개. 종목 정식명+연도, 구어체 제거. market_scope가 global이면 검색어는 영어로, kr이면 한국어로, mixed면 영어·한국어를 섞어 작성 (sub_questions의 search_queries도 동일 규칙)."""

_PROMPT_B = """너는 금융 질문에서 정형 정보를 추출한다. 답하지 마라. 길게 추론하지 마라. 보이는 것만.

- fiscal_periods: 기간 표현을 {{expression, calendar_period, last_reported_period, basis:calendar|reported|unclear, resolved:bool}}. "지난 분기"는 확정하지 말고 unclear.
- metrics: 필요 계산 목록("기간 수익률","영업이익률 yoy(pp)"). 없으면 빈 배열.
- tickers_supplement: 사전에 없는 종목만 야후 심볼로 {{name, yahoo_symbol}} (애플→AAPL). 확신 없으면 unresolved_entities에 이름만.
- richness_grade: A(대형주·유명) / B(중형) / C(소형·희소).
- tier_opinion, cutoff_opinion: 질문 종류(0-4)와 지식시점을 독립 판정(교차확인용)."""


# 글로벌 주요 종목 별칭 → 야후 심볼 (결정적 프리매칭 — LLM 보완이 흔들려도 안 놓치게).
# 티커 추출이 LLM에만 의존하면 같은 질문도 런마다 누락이 갈림 (2026-07-09 woojin 재현 2회 실측)
_GLOBAL_ALIASES: dict[str, tuple[str, str]] = {  # 별칭 → (정식명, yahoo_symbol)
    "애플": ("Apple", "AAPL"), "Apple": ("Apple", "AAPL"), "AAPL": ("Apple", "AAPL"),
    "마이크론": ("Micron", "MU"), "Micron": ("Micron", "MU"), "MU": ("Micron", "MU"),
    "엔비디아": ("NVIDIA", "NVDA"), "NVIDIA": ("NVIDIA", "NVDA"), "NVDA": ("NVIDIA", "NVDA"),
    "테슬라": ("Tesla", "TSLA"), "Tesla": ("Tesla", "TSLA"),
    "마이크로소프트": ("Microsoft", "MSFT"), "Microsoft": ("Microsoft", "MSFT"),
    "구글": ("Alphabet", "GOOGL"), "알파벳": ("Alphabet", "GOOGL"),
    "아마존": ("Amazon", "AMZN"), "Amazon": ("Amazon", "AMZN"),
    "메타": ("Meta", "META"), "Meta": ("Meta", "META"),
    "인텔": ("Intel", "INTC"), "Intel": ("Intel", "INTC"),
    "AMD": ("AMD", "AMD"), "브로드컴": ("Broadcom", "AVGO"), "퀄컴": ("Qualcomm", "QCOM"),
    "ASML": ("ASML", "ASML"), "TSMC": ("TSMC", "TSM"), "도쿄일렉트론": ("Tokyo Electron", "8035.T"),
}


def _prematch_tickers(text: str) -> list[TickerCandidate]:
    """사전 코드 매칭 — universe_kospi(국내) + 글로벌 별칭, 결정적."""
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
    for alias, (name, sym) in _GLOBAL_ALIASES.items():
        if alias in text and sym not in seen:
            out.append(TickerCandidate(
                name=name, yahoo_symbol=sym, confidence="high", source="dict_match",
            ))
            seen.add(sym)
    return out[:6]


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

    # market_scope 검증 — 어휘 밖 값은 "kr" 폴백
    scope = a.market_scope if a.market_scope in {"kr", "global", "mixed"} else "kr"

    # 유닛 상한 — 서브질문 ≤5 (전체질문 포함 ≤6)
    subs = []
    for i, sq in enumerate(a.sub_questions[:5]):
        subs.append(SubQuestion(
            id=sq.id or f"q{i+1}", text=sq.text, depends_on=sq.depends_on or None,
            search_queries=[q for q in sq.search_queries if q.strip()][:2],
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

    # 티커 역보충 (G0, 결정적) — needed_evidence 엔티티가 tickers에 없으면 universe 정확명 매칭.
    # "우리 삼성이" 같은 축약 표현에서 질문 텍스트 사전매칭·LLM 보완이 모두 놓쳐도,
    # A가 needed_evidence에 정식명("삼성전자")을 쓰면 여기서 복원 (2026-07-09 woojin 재현 케이스)
    ticker_names = {t.name for t in tickers}
    uni_by_name = {it.get("name"): it.get("code") for it in _load_universe() if it.get("name")}
    for ne in needed:
        ent = ne.entity.strip()
        if not ent or ent in ticker_names:
            continue
        if ent in uni_by_name:
            code = uni_by_name[ent]
            tickers.append(TickerCandidate(
                name=ent, code=code, yahoo_symbol=f"{code}.KS",
                confidence="medium", source="dict_match",
            ))
            ticker_names.add(ent)
            notes.append(f"needed_evidence 엔티티 역보충: {ent}({code})")
        elif ent in _GLOBAL_ALIASES:
            name, sym = _GLOBAL_ALIASES[ent]
            tickers.append(TickerCandidate(
                name=name, yahoo_symbol=sym, confidence="medium", source="dict_match",
            ))
            ticker_names.update({ent, name})
            notes.append(f"needed_evidence 엔티티 역보충: {ent}→{sym}")

    # 국내 티커 code 보정 — LLM 보완분은 code가 비어 toss 수집 대상에서 빠짐
    # (woojin 재현 3·4회차: 토스가 EPS/PER을 주는데 code 부재로 호출 자체가 안 됨)
    for t in tickers:
        if t.code:
            continue
        sym = t.yahoo_symbol or ""
        if re.match(r"^\d{6}\.(KS|KQ)$", sym):
            t.code = sym[:6]
        elif t.name in uni_by_name:
            t.code = uni_by_name[t.name]
            if not t.yahoo_symbol:
                t.yahoo_symbol = f"{t.code}.KS"

    # 심볼 중복 제거 — 사전매칭·LLM 보완·역보충이 같은 종목을 다른 이름으로 넣을 수 있음
    dedup: list[TickerCandidate] = []
    seen_syms: set[str] = set()
    for t in tickers:
        key = t.yahoo_symbol or t.code or t.name
        if key in seen_syms:
            continue
        seen_syms.add(key)
        dedup.append(t)
    tickers = dedup

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
        market_scope=scope,  # type: ignore[arg-type]
        fiscal_periods=fiscal,
        metrics=b.metrics,
        richness=EvidenceRichness(grade=b.richness_grade if b.richness_grade in "ABC" else "B", prelim=True),
        g0_notes=notes,
    )
