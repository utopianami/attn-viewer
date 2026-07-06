"""RA-외부 스테이지 — 외부 증거 수집 (설계 §③b 수집기 4종 + claim 추출, 수집기 단위 degrade).

수집기 (2026-07-03 설계 완전판, 2026-07-06 grok 제거):
- x_search    (unit별, 비용 상한 3콜): 당일 실시간 뉴스. brave(freshness=pd) → tavily 폴백.
              (grok live search는 정보 유효성 대비 검색비가 커서 제거 — 서사 대신 뉴스 rows)
- web_knowledge (brave web → tavily 폴백 + 5.5-mini 정리, unit): 배경지식·관행 웹서핑.
              발동 조건 = needed_evidence에 source_type=web 슬롯 존재 (설계 §PlanPacket)
- toss_trend  (코드 수집 + 5.5-mini 트렌드 합성, global): 4탭 피드 → TrendPacket.
              각 trend는 derived claim(근거 뉴스 id 필수)으로 claim table 편입 — 증거 세탁 차단
- toss_company (코드, ticker): 뉴스·PER·수급

claim 추출: 5.5-mini 1콜 — x_narrative·뉴스 헤드라인에서 원자 claim (entity/metric/as_of/ref).
news_mode=off면 검색·트렌드 skip. archive면 freshness 완화 + as_of 게이트는 VERIFIER(G3)가.
수집기 하나가 죽어도 나머지는 계속. REFLECT 재조사는 run_ra_research() 사용 (global 수집기 skip).
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from contracts import (
    AtomicClaim,
    ClaimNorm,
    EnvelopeMeta,
    NewsItem,
    PlanPacket,
    RaPacket,
    TrendPacket,
)
from providers import Role
from tools.news.brave import news_search, web_search
from tools.news.fetch_body import fetch_bodies
from tools.news.tavily import tavily_search
from tools.toss import TossClient, collect_company, collect_feed

# 비용 상한 (settings 이관 후보)
_MAX_X_UNITS = 3             # q0 + 서브질문 상위 2개
_MAX_WEB_UNITS = 3           # web_knowledge 유닛 상한
_CURATE_PER_UNIT = 5         # curation 유닛당 상한 (P1-2, F6: 노이즈가 정확도를 깎음)
_FETCH_BODY_TOP = 5          # 본문 수집 상한 (P1-1)

# 커뮤니티 게시판 — 뉴스 증거 자격 없음 (2026-07-06 yvon 피드백: 루리웹/펨코 글 노출)
_BLOCKED_DOMAINS = (
    "ruliweb.com", "fmkorea.com", "dcinside.com", "theqoo.net", "clien.net",
    "bobaedream.co.kr", "instiz.net", "mlbpark.donga.com", "humoruniv.com",
    "ppomppu.co.kr",
)


class _SO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _XClaim(_SO):
    text: str
    entity: str = ""
    metric: str = ""
    period: str = ""
    value: float | None = None  # 숫자 주장이면 수치 (G2/AUDIT 대조용)
    unit: str = ""              # percent|KRW|조원|억원 등
    as_of: str = ""            # 근거 날짜 (YYYY-MM-DD, 모르면 빈칸)
    url: str = ""
    type: str = "fact"         # fact|numeric|price|context|comparison|regulation|temporal


class _XClaims(_SO):
    claims: list[_XClaim] = Field(default_factory=list)


class _Trend(_SO):
    label: str
    stocks: list[str] = Field(default_factory=list)
    news_ids: list[str] = Field(default_factory=list)


class _TrendSynth(_SO):
    trends: list[_Trend] = Field(default_factory=list)


class _WebNote(_SO):
    note: str
    url: str = ""


class _WebKnowledge(_SO):
    notes: list[_WebNote] = Field(default_factory=list)


class _CurUnit(_SO):
    unit_id: str
    keep_ids: list[str] = Field(default_factory=list)


class _Curation(_SO):
    units: list[_CurUnit] = Field(default_factory=list)


def _clean_pool(items: list[NewsItem]) -> list[NewsItem]:
    """수집 직후 공통 후처리 — 커뮤니티 도메인 차단 + 정규화 URL 중복 제거."""
    out: list[NewsItem] = []
    seen: set[str] = set()
    for n in items:
        host = urlparse(n.url).netloc.lower()
        if any(host == d or host.endswith("." + d) for d in _BLOCKED_DOMAINS):
            continue
        key = (n.url or n.title).split("?")[0].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _to_news(article) -> NewsItem:
    return NewsItem(
        id=getattr(article, "news_id", getattr(article, "id", "")) or "",
        title=getattr(article, "title", ""),
        summary=getattr(article, "summary", ""),
        content=getattr(article, "content_text", ""),
        published_at=getattr(article, "created_at", "") or "",
        source_name=getattr(getattr(article, "source", None), "name", "") if hasattr(article, "source") else "",
        feed_count=getattr(article, "feed_count", 1),
        tabs=getattr(article, "tabs", []),
    )


_REL_AGE_RE = re.compile(
    r"(\d+)\s*(분|시간|주일|주|개월|달|일|minute|min|hour|day|week|month)s?\s*(?:전|ago)", re.I)
_ISO_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_AGE_DAYS = {"분": 0, "일": 1, "주일": 7, "주": 7, "개월": 30, "달": 30,
             "minute": 0, "min": 0, "day": 1, "week": 7, "month": 30}
_AGE_WORDS = {"오늘": 0, "today": 0, "어제": 1, "yesterday": 1, "하루 전": 1,
              "이틀 전": 2, "그제": 2, "그저께": 2}


def _norm_age(age: str) -> str:
    """검색 응답의 발행 시점("3일 전"/"2 hours ago"/ISO)을 ISO 날짜로 정규화 (P4-1).

    기준=오늘. 해석 실패 시 "" — 시점 불명 문서는 랭킹·cutoff 필터에서 중립 취급.
    """
    from datetime import date, timedelta
    age = (age or "").strip()
    if not age:
        return ""
    m = _ISO_RE.search(age)
    if m:
        return m.group(1)
    if age in _AGE_WORDS:
        return (date.today() - timedelta(days=_AGE_WORDS[age])).isoformat()
    m = _REL_AGE_RE.search(age)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit in ("시간", "hour"):
            days = n // 24  # "48시간 전" = 2일 전 (리뷰 #7)
        else:
            days = n * _AGE_DAYS.get(unit, 0)
        return (date.today() - timedelta(days=days)).isoformat()
    return ""


def _dict_to_news(r: dict) -> NewsItem:
    return NewsItem(
        title=r.get("title", ""), summary=r.get("description", ""),
        url=r.get("url", ""), published_at=_norm_age(r.get("age", "")),
        source_name=r.get("source", ""),
    )


async def _search_fallback(query: str, *, freshness: str, client, count: int = 5) -> list[dict]:
    """brave 뉴스 → tavily 뉴스 폴백 (허용목록 순서 = 폴백 순서)."""
    try:
        rows = await news_search(query, count=count, freshness=freshness, client=client)
        if rows:
            return rows
    except Exception:
        pass
    try:
        return await tavily_search(query, count=count, topic="news", days=7, client=client)
    except Exception:
        return []


async def _x_unit(unit_id: str, question: str, *, client) -> tuple[str, list[dict]]:
    """유닛 1개의 x_search — 당일(freshness=pd) 뉴스. brave→tavily 폴백.

    반환: (unit_id, news_rows)
    """
    rows = await _search_fallback(question, freshness="pd", client=client)
    return unit_id, rows


def _assign_ids(pools: dict[str, list[NewsItem]]) -> None:
    """검색 결과 NewsItem에 유닛 로컬 id 부여 (brave/tavily는 id 없음) — curation 선택 좌표."""
    for uid, items in pools.items():
        for i, n in enumerate(items):
            if not n.id:
                n.id = f"{uid}:n{i}"


async def curate_evidence(plan: PlanPacket, x_search: dict[str, list[NewsItem]],
                          web_knowledge: dict[str, list[NewsItem]],
                          overrides: dict | None) -> dict[str, list[str]]:
    """evidence curation (P1-2) — mini 1콜로 유닛별 '실제로 유용한' 기사만 선별 (상한 5/유닛).

    F6(HiREC): 검색 노이즈가 하류 정확도를 깎는다 — filter-to-few가 +13pp.
    mini 실패 시 빈 dict 반환 → curated_items()가 전량 폴백 (degrade 안전).
    """
    pools: dict[str, list[NewsItem]] = {}
    for src in (x_search, web_knowledge):
        for uid, items in src.items():
            pools.setdefault(uid, []).extend(items)
    if not pools or all(len(v) <= _CURATE_PER_UNIT for v in pools.values()) \
            and sum(len(v) for v in pools.values()) <= _CURATE_PER_UNIT * 2:
        return {}  # 애초에 적으면 curation 비용이 낭비

    unit_q = dict(plan.units())
    sections = []
    for uid, items in pools.items():
        q = unit_q.get(uid, plan.standalone_question)
        lines = "\n".join(
            f"- id={n.id} [{n.published_at or '?'}] {n.title} — {n.summary[:120]}"
            for n in items[:12])
        sections.append(f"[유닛 {uid}] 질문: {q}\n{lines}")

    role = Role("extract", overrides)
    try:
        val: _Curation = await role.run(
            "\n\n".join(sections)[:14000],
            f"기준시점: {plan.knowledge_cutoff}\n"
            "각 유닛의 질문에 답하는 데 실제로 유용한 기사만 id로 선택하라 (유닛당 최대 5개).\n"
            "- 제목이 관련돼 보여도 질문의 시점·종목·지표와 안 맞으면 제외하라.\n"
            "- 발행일이 기준시점에 가까운 기사를 우선하라. 기준시점 이후 발행 기사는 선택 금지.\n"
            "- 유용한 기사가 없는 유닛은 keep_ids를 빈 배열로.",
            response_format=_Curation,
        )
    except Exception:
        return {}

    def _within_cutoff(n: NewsItem) -> bool:
        # P4-2 코드 후처리 — cutoff 초과 문서는 랭킹에서 제외 (G3 as_of 게이트는 안전망)
        return not (n.published_at and n.published_at[:10] > plan.knowledge_cutoff)

    curated: dict[str, list[str]] = {}
    for u in val.units:
        if u.unit_id not in pools:
            continue
        valid = {n.id: n for n in pools[u.unit_id]}
        curated[u.unit_id] = [i for i in u.keep_ids
                              if i in valid and _within_cutoff(valid[i])][:_CURATE_PER_UNIT]
    # mini가 빠뜨린 유닛 = 미판정 — cutoff 이내에서 상위 3개 스캔 (앞쪽 슬라이스가
    # 전부 cutoff 초과면 유닛 증거가 통째로 사라지는 결함 방지, 리뷰 #5)
    for uid, items in pools.items():
        if uid not in curated:
            curated[uid] = [n.id for n in items if _within_cutoff(n)][:3]
    return curated


async def _extract_claims(narratives: dict[str, str], news: dict[str, list[NewsItem]],
                          overrides: dict | None) -> list[AtomicClaim]:
    """5.5-mini 1콜 — 수집 텍스트에서 원자 claim 추출 (설계: claim 추출은 mini)."""
    parts = []
    for uid, txt in narratives.items():
        if txt:
            parts.append(f"[{uid} 실시간 검색 서사]\n{txt[:2500]}")
    for uid, items in news.items():
        lines = []
        for n in items[:6]:
            lines.append(f"- {n.title} ({n.published_at or '?'}) {n.url}")
            if n.content:  # 본문 확보분(P1-1)은 발췌 포함 — 헤드라인보다 원자 claim이 정확
                lines.append(f"  본문: {n.content[:500]}")
        if lines:
            parts.append(f"[{uid} 뉴스]\n" + "\n".join(lines))
    if not parts:
        return []
    role = Role("extract", overrides)
    instr = (
        "아래 수집 텍스트에서 검증 가능한 원자 주장(claim)을 추출하라. 한 문장 한 주장.\n"
        "- 사실/수치/시세만. 의견·전망은 제외. 한 claim에 검증 가능한 사실 정확히 1개 —"
        " 더 쪼개지도 뭉치지도 마라.\n"
        "- entity(회사/지수), metric(무엇의 값·사건인지), as_of(근거 날짜), url(출처) 채워라.\n"
        "- type: fact | numeric(수치) | price(시세) | context |"
        " comparison(A가 B보다) | regulation(공시·규정 인용) | temporal(일정·발표일).\n"
        "- 숫자가 있으면 type=numeric으로 하고 value(숫자)·unit(percent|KRW|조원|억원 등)·period를 반드시 채워라.\n"
        "  (예: '영업이익 4,411억원' → value=4411, unit='억원')\n"
        "- 최대 12개, 중요한 것부터."
    )
    try:
        val: _XClaims = await role.run("\n\n".join(parts)[:12000], instr, response_format=_XClaims)
    except Exception:
        return []
    out = []
    for i, c in enumerate(val.claims[:12]):
        ctype = c.type if c.type in {"fact", "numeric", "price", "context",
                                     "comparison", "regulation", "temporal"} else "fact"
        out.append(AtomicClaim(
            id=f"ra_x:c{i}", text=c.text, type=ctype, source="ra_x",  # type: ignore[arg-type]
            norm=ClaimNorm(entity=c.entity, metric=c.metric, period=c.period,
                           value=c.value, unit=c.unit,
                           source_type="secondary", as_of=c.as_of),
            ref=c.url,
        ))
    return out


async def _collect_web_knowledge(plan: PlanPacket, *, client, overrides: dict | None,
                                 ) -> tuple[dict[str, list[NewsItem]], list[AtomicClaim], str]:
    """web_knowledge 수집기 — needed_evidence source_type=web 슬롯이 발동 조건."""
    web_slots = [ne for ne in plan.needed_evidence if ne.source_type == "web"][:_MAX_WEB_UNITS]
    if not web_slots:
        return {}, [], "skipped"
    results: dict[str, list[NewsItem]] = {}
    for i, slot in enumerate(web_slots):
        q = f"{slot.entity} {slot.metric}".strip()
        rows = []
        try:
            rows = await web_search(q, count=4, client=client)
        except Exception:
            pass
        if not rows:
            try:
                rows = await tavily_search(q, count=4, topic="general", client=client)
            except Exception:
                rows = []
        if rows:
            results[f"web{i}"] = [_dict_to_news(r) for r in rows]
    if not results:
        return {}, [], "degraded"

    # mini 정리 — 배경지식 노트 → context claim (웹 출처 부착)
    heads = []
    for uid, items in results.items():
        for n in items[:4]:
            heads.append(f"- {n.title}: {n.summary[:200]} ({n.url})")
    role = Role("extract", overrides)
    claims: list[AtomicClaim] = []
    try:
        val: _WebKnowledge = await role.run(
            "\n".join(heads)[:8000],
            "질문의 배경지식·제도·관행을 3~6개 노트로 정리하라. 각 노트에 출처 url. 사실만, 추측 금지.",
            response_format=_WebKnowledge,
        )
        for i, note in enumerate(val.notes[:6]):
            claims.append(AtomicClaim(
                id=f"ra_web:c{i}", text=note.note, type="context", source="ra_web",
                norm=ClaimNorm(source_type="secondary"),
                ref=note.url,
            ))
    except Exception:
        pass
    return results, claims, "ok"


async def _trend_synth(articles: list[NewsItem], overrides: dict | None) -> list[dict]:
    """5.5-mini 트렌드 합성 — 각 trend에 근거 뉴스 id 필수 (derived claim 편입용).

    설계는 10건/콜 배치 요약 후 합성이나, 제목+feed_count만 쓰므로 1콜로 충분 (비용·지연 절감).
    """
    if not articles:
        return []
    lines = "\n".join(
        f"[{a.id or i}] {a.title} (feed_count={a.feed_count})"
        for i, a in enumerate(articles[:30])
    )
    role = Role("extract", overrides)
    try:
        val: _TrendSynth = await role.run(
            lines,
            "뉴스 헤드라인에서 시장 트렌드 3~6개를 합성하라. 각 trend: label(한 줄), "
            "stocks(관련 종목명), news_ids(근거가 된 헤드라인의 [id] 목록 — 필수, 없으면 그 trend 버려라). "
            "feed_count 높은 기사(여러 종목 피드 동시 등장 = 시황)를 우선하라.",
            response_format=_TrendSynth,
        )
        return [
            {"label": t.label, "stocks": t.stocks, "news_ids": t.news_ids}
            for t in val.trends if t.news_ids
        ]
    except Exception:
        # mini 실패 → 코드 폴백 (feed_count 기반)
        return [{"label": a.title, "stocks": [], "news_ids": [a.id]}
                for a in articles[:8] if a.feed_count >= 2]


async def run_ra_external(plan: PlanPacket, overrides: dict | None = None) -> RaPacket:
    """수집기 4종 병렬 + claim 추출. 수집기 단위 degrade."""
    import httpx

    collector_status: dict[str, str] = {}
    narratives: dict[str, str] = {}
    x_search: dict[str, list[NewsItem]] = {}
    web_knowledge: dict[str, list[NewsItem]] = {}
    trend_packet: TrendPacket | None = None
    company: dict = {}
    claims: list[AtomicClaim] = []

    live = plan.news_mode != "off"
    freshness = "pm" if plan.news_mode == "archive" else "pw"

    async with httpx.AsyncClient(timeout=20) as hc:

        # ── x_search: 유닛별 당일 뉴스 (상한 3콜) — q0 + 검색어 있는 서브질문 상위
        async def _x_all():
            if not live:
                return
            units = [("q0", plan.standalone_question)]
            for sq in plan.sub_questions:
                if sq.search_queries and len(units) < _MAX_X_UNITS:
                    units.append((sq.id, sq.text))
            results = await asyncio.gather(
                *(_x_unit(uid, q, client=hc) for uid, q in units),
                return_exceptions=True,
            )
            any_ok = False
            for r in results:
                if isinstance(r, BaseException):
                    continue
                uid, rows = r
                if rows:
                    x_search.setdefault(uid, []).extend(_dict_to_news(x) for x in rows)
                    any_ok = True
            collector_status["x_search"] = "ok" if any_ok else "degraded"

        # ── brave 뉴스: 유닛별 검색어 + 대조질의 (검색 전용 — DA 투입 금지)
        async def _brave_all():
            if not live:
                return
            units = {"q0": plan.search_queries or [plan.standalone_question]}
            for sq in plan.sub_questions:
                if sq.search_queries:
                    units[sq.id] = sq.search_queries
            if plan.contrast_questions:
                units["contrast"] = plan.contrast_questions[:2]
            any_ok = False
            for uid, queries in units.items():
                items: list[NewsItem] = []
                for q in queries[:2]:
                    for r in await _search_fallback(q, freshness=freshness, client=hc):
                        items.append(_dict_to_news(r))
                if items:
                    x_search.setdefault(uid, []).extend(items[:8])
                    any_ok = True
            collector_status["brave_news"] = "ok" if any_ok else "degraded"

        # ── web_knowledge
        async def _web_all():
            nonlocal web_knowledge
            wk, wk_claims, status = await _collect_web_knowledge(plan, client=hc, overrides=overrides)
            web_knowledge = wk
            claims.extend(wk_claims)
            if status != "skipped":
                collector_status["web_knowledge"] = status

        # ── toss (trend + company)
        async def _toss_all():
            nonlocal trend_packet, company
            try:
                async with TossClient() as client:
                    tasks = []
                    if live:
                        tasks.append(("toss_trend", collect_feed(client)))
                    codes = [t.code for t in plan.tickers if t.code]
                    for code in codes[:3]:
                        tasks.append((f"toss_company:{code}",
                                      collect_company(code, client=client, news_size=5, trend_size=5)))
                    if not tasks:
                        return
                    results = await asyncio.gather(*(t[1] for t in tasks), return_exceptions=True)
                    for (label, _), res in zip(tasks, results):
                        key = label.split(":")[0]
                        if isinstance(res, BaseException):
                            collector_status[key] = "degraded"
                            continue
                        collector_status[key] = "ok"
                        if label == "toss_trend":
                            arts = [_to_news(a) for a in res]
                            trends = await _trend_synth(arts, overrides)
                            trend_packet = TrendPacket(
                                trends=trends, articles=arts, as_of=plan.knowledge_cutoff,
                            )
                            # derived claim 편입 — G1 증거 자격 없음(derived), 근거 뉴스 id 필수
                            for i, t in enumerate(trends):
                                claims.append(AtomicClaim(
                                    id=f"toss_trend:c{i}", text=t["label"], type="context",
                                    source="toss_trend", derived=True,
                                    norm=ClaimNorm(source_type="synth", as_of=plan.knowledge_cutoff),
                                    ref=",".join(str(x) for x in t.get("news_ids", [])[:5]),
                                ))
                        elif label.startswith("toss_company:"):
                            code = label.split(":")[1]
                            inv = res.get("info", {}).get("investment")
                            company[code] = {
                                "news": [_to_news(a).model_dump() for a in res.get("news", [])],
                                "info_per": getattr(inv, "per", None) if inv else None,
                                "trading_trend": [r.model_dump() for r in res.get("trading_trend", [])[:5]],
                            }
            except Exception:
                collector_status.setdefault("toss_trend", "degraded")

        # 수집기 단위 격리 — 하나의 예상 밖 예외가 RA 브랜치 전체를 죽이면 안 됨 (codex #18)
        results = await asyncio.gather(_x_all(), _brave_all(), _web_all(), _toss_all(),
                                       return_exceptions=True)
        for name, r in zip(("x_search", "brave_news", "web_knowledge", "toss_trend"), results):
            if isinstance(r, BaseException):
                collector_status.setdefault(name, "degraded")

        # ── curation (P1-2) → 본문 수집 (P1-1) → claim 추출
        _assign_ids(x_search)
        _assign_ids(web_knowledge)
        curated: dict[str, list[str]] = {}
        try:
            curated = await curate_evidence(plan, x_search, web_knowledge, overrides)
        except Exception:
            curated = {}

        # 본문은 curation 통과분만 (비용·지연 상한) — 실패해도 제목/요약으로 계속
        picked: list[NewsItem] = []
        keep_all = {i for ids in curated.values() for i in ids} if curated else None
        for items in list(x_search.values()) + list(web_knowledge.values()):
            for n in items:
                if keep_all is None or n.id in keep_all:
                    picked.append(n)
        try:
            await fetch_bodies(picked, top_n=_FETCH_BODY_TOP)
        except Exception:
            pass

        # ── claim 추출 (mini 1콜) — 서사 + curation 통과 뉴스(본문 포함)에서 원자 claim
        if narratives or x_search:
            extract_news = x_search
            if curated:
                extract_news = {}
                for uid, items in x_search.items():
                    keep = set(curated.get(uid, []))
                    kept = [n for n in items if n.id in keep] if uid in curated else items
                    if kept:
                        extract_news[uid] = kept
            claims.extend(await _extract_claims(narratives, extract_news, overrides))

    # q0 서사를 대표 narrative로 (하위 유닛 서사는 뒤에 병기)
    x_narrative = narratives.get("q0", "")
    for uid, txt in narratives.items():
        if uid != "q0":
            x_narrative += f"\n\n[{uid} 추가 검색]\n{txt}"

    oks = [v for v in collector_status.values() if v == "ok"]
    if not collector_status:
        status = "skipped"        # news_mode=off 등 — 애초에 안 돌림
    elif len(oks) == len(collector_status):
        status = "ok"
    elif oks:
        status = "degraded"       # 일부 성공
    else:
        status = "error"          # live 모드인데 전부 실패 — 숨기지 않음
    return RaPacket(
        meta=EnvelopeMeta(round=plan.meta.round, plan_ref=plan.plan_ref()),
        status=status,  # type: ignore[arg-type]
        x_narrative=x_narrative.strip(),
        x_search=x_search,
        web_knowledge=web_knowledge,
        toss_trend=trend_packet,
        toss_company=company,
        claims=claims,
        collector_status=collector_status,  # type: ignore[arg-type]
        curated=curated,
    )


async def run_ra_research(queries: list[str], *, seen_urls: set[str],
                          overrides: dict | None = None, tag: str = "r",
                          ) -> tuple[dict[str, list[NewsItem]], list[AtomicClaim]]:
    """재조사 전용 (REFLECT·answerability 보완) — 신규 확장 쿼리만 검색, global 수집기 skip.

    seen_urls 문서는 신규로 치지 않는다 (재조사 신규 0건 → unobtainable 판정용).
    tag: 호출별 claim id 접두사 — 여러 번 불릴 때 id 충돌 방지 (extra_claims 누적 구조).
    """
    import httpx

    found: dict[str, list[NewsItem]] = {}
    async with httpx.AsyncClient(timeout=20) as hc:
        # 쿼리 병렬 (리뷰 #9 — 직렬 최악 케이스 수 분) + 자체 쿼리 간 URL 중복 제거 (리뷰 #6)
        results = await asyncio.gather(
            *(_search_fallback(q, freshness="pw", client=hc) for q in queries[:4]),
            return_exceptions=True)
        local_seen = set(seen_urls)
        for i, rows in enumerate(results):
            if isinstance(rows, BaseException):
                continue
            fresh = []
            for r in rows:
                url = r.get("url")
                if url and url not in local_seen:
                    local_seen.add(url)
                    fresh.append(_dict_to_news(r))
            if fresh:
                found[f"{tag}{i}"] = fresh[:6]
    if not found:
        return {}, []
    _assign_ids(found)
    try:
        await fetch_bodies([n for items in found.values() for n in items],
                           top_n=_FETCH_BODY_TOP)
    except Exception:
        pass
    claims = await _extract_claims({}, found, overrides)
    for c in claims:
        c.id = f"{tag}:{c.id}"
    return found, claims
