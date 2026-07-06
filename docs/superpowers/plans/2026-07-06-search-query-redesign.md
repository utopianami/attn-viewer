# 검색 쿼리 재설계 + Sonnet 뉴스 요약 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검색이 질문 시장에 맞는 언어·국가로 정제된 쿼리를 쓰게 하고, 커뮤니티/중복 노이즈를 수집 직후 제거하며, Sonnet이 큐레이션된 뉴스를 요약해 UI 패널과 최종 합성 양쪽에 공급한다.

**Architecture:** 플래너(plan 스테이지)가 `market_scope`와 유닛별 시장-언어 검색어를 생성 → 검색기(brave)는 scope에 맞는 country/lang 파라미터로 호출 → 수집 직후 도메인 블록리스트+URL 중복 제거 → 큐레이션 통과분을 Sonnet(`news_summary` 역할)이 요약 → 새 `news_summary` 레이어 + 합성 프롬프트 투입. UI `ra_x` 레이어는 raw 대신 큐레이션 통과분만 방출.

**Tech Stack:** Python 3.12, pydantic v2, httpx, pytest (engine/.venv), agent_framework(MAF) 기반 Role 래퍼.

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-07-06-search-query-redesign-design.md`
- Sonnet 모델 ID는 정확히 `"claude-sonnet-4-6"`, 단가 `(3.0, 15.0)` USD/MTok (2026-07-06 검증).
- never-raise 원칙: 새 스테이지 실패는 파이프라인을 막지 않는다 (degrade).
- 테스트 실행: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest <path> -v`
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 추가.
- structured output 스키마는 자유 dict/min·max 제약 미지원 — typed 모델 + 코드 clamp (plan.py 상단 주석 참조).

---

### Task 1: brave 검색기 country/search_lang 파라미터화

**Files:**
- Modify: `engine/tools/news/brave.py`
- Test: `engine/tests/test_search_quality.py` (신규)

**Interfaces:**
- Produces: `news_search(query, *, count=6, freshness="pd", country="kr", search_lang="ko", client=None) -> list[dict]`, `web_search(query, *, count=5, country="kr", search_lang="ko", client=None) -> list[dict]` — 기본값이 기존 하드코딩과 동일해 기존 호출부는 무변경 동작.

- [ ] **Step 1: Write the failing test**

`engine/tests/test_search_quality.py` 생성:

```python
"""검색 품질 보강 (2026-07-06 스펙) — 지오 파라미터·노이즈 필터·쿼리 선택."""
import httpx
import pytest

from tools.news import brave


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"results": [], "web": {"results": []}}


@pytest.mark.asyncio
async def test_news_search_passes_geo_params(monkeypatch):
    captured = {}

    async def fake_get(self, url, params=None, headers=None):
        captured.update(params or {})
        return _FakeResp()

    monkeypatch.setattr(brave.settings, "brave_api_key", "test-key")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    async with httpx.AsyncClient() as hc:
        await brave.news_search("European utility stocks", country="us",
                                search_lang="en", client=hc)
    assert captured["country"] == "us"
    assert captured["search_lang"] == "en"


@pytest.mark.asyncio
async def test_news_search_defaults_stay_kr(monkeypatch):
    captured = {}

    async def fake_get(self, url, params=None, headers=None):
        captured.update(params or {})
        return _FakeResp()

    monkeypatch.setattr(brave.settings, "brave_api_key", "test-key")
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    async with httpx.AsyncClient() as hc:
        await brave.news_search("유럽 전력주", client=hc)
    assert captured["country"] == "kr"
    assert captured["search_lang"] == "ko"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: FAIL — `TypeError: news_search() got an unexpected keyword argument 'country'`

- [ ] **Step 3: Write minimal implementation**

`brave.py`의 두 함수 시그니처와 params를 수정:

```python
async def news_search(query: str, *, count: int = 6, freshness: str = "pd",
                      country: str = "kr", search_lang: str = "ko",
                      client: httpx.AsyncClient | None = None) -> list[dict]:
    """뉴스 검색. freshness: pd(하루)|pw(주)|pm(월). 실패 시 빈 리스트 (never-raise는 호출자)."""
    ...
            params={"q": query, "country": country, "search_lang": search_lang,
                    "freshness": freshness, "count": count},
```

```python
async def web_search(query: str, *, count: int = 5,
                     country: str = "kr", search_lang: str = "ko",
                     client: httpx.AsyncClient | None = None) -> list[dict]:
    ...
            params={"q": query, "country": country, "search_lang": search_lang, "count": count},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: PASS (2개)

- [ ] **Step 5: Commit**

```bash
git add engine/tools/news/brave.py engine/tests/test_search_quality.py
git commit -m "feat(search): brave country/search_lang 파라미터화 (kr 하드코딩 제거)"
```

---

### Task 2: 수집 후처리 `_clean_pool` — 커뮤니티 도메인 차단 + URL 중복 제거

**Files:**
- Modify: `engine/stages/ra_external.py` (모듈 상수·헬퍼 추가)
- Test: `engine/tests/test_search_quality.py` (추가)

**Interfaces:**
- Produces: `ra_external._clean_pool(items: list[NewsItem]) -> list[NewsItem]`, `ra_external._BLOCKED_DOMAINS: tuple[str, ...]`
- Consumes: `contracts.packets.NewsItem`

- [ ] **Step 1: Write the failing test (실제 실패 케이스 회귀 픽스처 포함)**

`test_search_quality.py`에 추가:

```python
from contracts.packets import NewsItem
from stages.ra_external import _clean_pool

# 2026-07-06 yvon 피드백 실사고 — storage/users/yvon/chats/0bdf0cba... ra_x 레이어 원본 12건
YVON_RA_X_FIXTURE = [
    ("미국 동부 폭염·폭풍에 전력난 심화…전기요금 급등·100만 가구 정전", "https://theguru.co.kr/news/article.html?no=103980"),
    ("삼전 실적발표·하닉 나스닥 데뷔 [7/6~7/10 투자캘린더]│Global Money Club", "https://joongang.co.kr/gmc/article/25442473"),
    ("한은, 삼전·하이닉스 레버리지 ETF 경고⋯쏠림 심화 우려 - 이투데이", "https://etoday.co.kr/news/view/2600308"),
    ("독자 최애 코너는 투자 고수에게 듣는다 | 한국경제", "https://hankyung.com/article/2026070565251"),
    ("OPEC+, 5개월 연속 증산 전망…내년엔 공급과잉 가능성", "https://view.asiae.co.kr/article/2026070515221002820"),
    ("Heat wave: European countries report 3,700 excess deaths", "https://dw.com/en/heat-wave-european-countries-report-3700-excess-deaths/a-77823303"),
    ("보지냐 골키퍼 세계 랭킹 1위 등극", "https://bbs.ruliweb.com/community/board/300143/read/75832692"),
    ("삼전·닉스 더갈까?…반도체 쏠림 장세 속 숨은 소부장株는", "https://ebn.co.kr/news/articleView.html?idxno=1715170"),
    ("유럽 퍼킹 코리안들아 너희 열돔 다시 가져가라고", "https://bbs.ruliweb.com/community/board/300143/read/75821172"),
    ("유럽 실적 시즌 프리뷰: 애널리스트가 주목하는 3가지 포인트", "https://kr.investing.com/news/stock-market-news/article-2005049"),
    ("유럽 폭염 근황 ㄷㄷ - 포텐 터짐 최신순 - 에펨코리아", "https://www.fmkorea.com/best/10044003905"),
    ("유럽 폭염 근황 ㄷㄷ - 포텐 터짐 최신순 - 에펨코리아", "https://www.fmkorea.com/best/10044003905"),
]


def test_clean_pool_blocks_community_and_dedupes():
    items = [NewsItem(title=t, url=u) for t, u in YVON_RA_X_FIXTURE]
    cleaned = _clean_pool(items)
    urls = [n.url for n in cleaned]
    assert len(cleaned) == 8  # 루리웹 2건 + 펨코 2건(중복 포함) 제거
    assert not any("ruliweb.com" in u for u in urls)
    assert not any("fmkorea.com" in u for u in urls)
    assert "https://dw.com/en/heat-wave-european-countries-report-3700-excess-deaths/a-77823303" in urls


def test_clean_pool_dedupes_by_normalized_url():
    items = [
        NewsItem(title="a", url="https://Example.com/news/1?utm=x"),
        NewsItem(title="b", url="https://example.com/news/1"),
    ]
    assert len(_clean_pool(items)) == 1


def test_clean_pool_blocks_subdomains():
    items = [NewsItem(title="글", url="https://gall.dcinside.com/board/view/?id=stock&no=1")]
    assert _clean_pool(items) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: FAIL — `ImportError: cannot import name '_clean_pool'`

- [ ] **Step 3: Write minimal implementation**

`ra_external.py` 상단(기존 상수 `_CURATE_PER_UNIT` 근처)에 추가:

```python
from urllib.parse import urlparse

# 커뮤니티 게시판 — 뉴스 증거 자격 없음 (2026-07-06 yvon 피드백: 루리웹/펨코 글 노출)
_BLOCKED_DOMAINS = (
    "ruliweb.com", "fmkorea.com", "dcinside.com", "theqoo.net", "clien.net",
    "bobaedream.co.kr", "instiz.net", "mlbpark.donga.com", "humoruniv.com",
    "ppomppu.co.kr",
)


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: PASS (기존 2 + 신규 3)

- [ ] **Step 5: Commit**

```bash
git add engine/stages/ra_external.py engine/tests/test_search_quality.py
git commit -m "feat(search): 커뮤니티 도메인 차단 + URL 중복 제거 (_clean_pool)"
```

---

### Task 3: 플랜 확장 — market_scope + 유닛별 시장-언어 검색어

**Files:**
- Modify: `engine/contracts/packets.py` (PlanPacket, SubQuestion은 이미 search_queries 보유)
- Modify: `engine/stages/plan.py` (_PlanA, _SubQ, _PROMPT_A, _g0_merge)
- Test: `engine/tests/test_search_quality.py` (추가)

**Interfaces:**
- Produces: `PlanPacket.market_scope: Literal["kr","global","mixed"]` (기본 `"kr"`), `SubQuestion.search_queries`가 실제로 채워짐 (현재 `_g0_merge`가 누락 — 버그 동반 수정).
- Consumes: 없음 (plan은 최상류).

- [ ] **Step 1: Write the failing test**

`test_search_quality.py`에 추가 (`_g0_merge`는 순수 코드라 LLM 없이 테스트 가능):

```python
from stages.plan import _g0_merge, _PlanA, _PlanB, _SubQ


def test_g0_merge_carries_market_scope_and_sub_queries():
    a = _PlanA(
        standalone_question="유럽 전력주 전망", tier=3, knowledge_cutoff="2026-07-06",
        market_scope="global",
        sub_questions=[_SubQ(id="q1", text="유럽 유틸리티 주가",
                             search_queries=["European utility stocks 2026"])],
        search_queries=["Europe power crisis utilities"],
    )
    plan = _g0_merge("유럽 전력주 전망", [], a, _PlanB())
    assert plan.market_scope == "global"
    assert plan.sub_questions[0].search_queries == ["European utility stocks 2026"]


def test_g0_merge_invalid_scope_falls_back_to_kr():
    a = _PlanA(standalone_question="q", tier=1, knowledge_cutoff="2026-07-06",
               market_scope="europe")  # 어휘 밖 값
    plan = _g0_merge("q", [], a, _PlanB())
    assert plan.market_scope == "kr"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: FAIL — `_PlanA`에 `market_scope` 필드 없음 (pydantic ValidationError 또는 TypeError)

- [ ] **Step 3: Write minimal implementation**

(a) `packets.py` — `PlanPacket`의 `news_mode` 필드 아래에 추가:

```python
    market_scope: Literal["kr", "global", "mixed"] = "kr"  # 검색 언어·국가 라우팅 (2026-07-06)
```

(b) `plan.py` — `_SubQ`에 검색어 필드 추가:

```python
class _SubQ(_SO):
    id: str
    text: str
    depends_on: str | None = None
    search_queries: list[str] = Field(default_factory=list)
```

(c) `plan.py` — `_PlanA`에 필드 추가:

```python
class _PlanA(_SO):
    ...
    search_queries: list[str] = Field(default_factory=list)
    market_scope: str = "kr"  # kr|global|mixed (코드 검증)
```

(d) `_PROMPT_A`의 sub_questions·search_queries 줄을 다음으로 교체하고 market_scope 줄 추가:

```
- market_scope: 질문 대상 자산·시장의 소재지. 한국 종목/국내 시장=kr, 해외 종목/해외 시장=global, 한국+해외 비교=mixed.
- sub_questions: 서로 다른 증거가 필요한 축이 2개+일 때만 쪼갠다(tier0-1≤2, tier2≤4, tier3≤5). 각 {{id:"q1",text,depends_on:앞질문id|null,search_queries:[검색어 1~2개]}}. 검색 한 번으로 답하면 빈 배열.
- search_queries: 전체 질문용 검색어 1~2개. 종목 정식명+연도, 구어체 제거. market_scope가 global이면 검색어는 영어로, kr이면 한국어로, mixed면 영어·한국어를 섞어 작성 (sub_questions의 search_queries도 동일 규칙).
```

(e) `_g0_merge` — 서브질문 생성부(현재 `subs.append(SubQuestion(id=..., text=..., depends_on=...))`)를 검색어 포함으로 교체하고, 반환 `PlanPacket(...)`에 `market_scope` 추가:

```python
    subs = []
    for i, sq in enumerate(a.sub_questions[:5]):
        subs.append(SubQuestion(
            id=sq.id or f"q{i+1}", text=sq.text, depends_on=sq.depends_on or None,
            search_queries=[q for q in sq.search_queries if q.strip()][:2],
        ))

    scope = a.market_scope if a.market_scope in {"kr", "global", "mixed"} else "kr"
```

```python
    return PlanPacket(
        ...,
        news_mode=news_mode,  # type: ignore[arg-type]
        market_scope=scope,  # type: ignore[arg-type]
        ...
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py tests/test_contracts.py -v`
Expected: 전부 PASS (기존 계약 테스트 회귀 확인 포함)

- [ ] **Step 5: Commit**

```bash
git add engine/contracts/packets.py engine/stages/plan.py engine/tests/test_search_quality.py
git commit -m "feat(plan): market_scope 판정 + 유닛별 시장-언어 검색어 생성 (서브질문 검색어 누락 버그 수정)"
```

---

### Task 4: ra_external — 플래너 검색어 사용, freshness 완화, 지오 라우팅, _clean_pool 적용

**Files:**
- Modify: `engine/stages/ra_external.py` (`_search_fallback`, `_x_unit`, `_x_all`, `_brave_all`, `_web_all` 호출부, gather 후 정리)
- Test: `engine/tests/test_search_quality.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `news_search(country=, search_lang=)`, Task 2의 `_clean_pool`, Task 3의 `plan.market_scope`/`sq.search_queries`.
- Produces: `ra_external._geo_params(query: str, market_scope: str) -> dict[str, str]` (키: country, search_lang).

- [ ] **Step 1: Write the failing test**

```python
from stages.ra_external import _geo_params


def test_geo_params_by_scope():
    assert _geo_params("European utilities", "global") == {"country": "us", "search_lang": "en"}
    assert _geo_params("유럽 전력주", "kr") == {"country": "kr", "search_lang": "ko"}
    # mixed는 쿼리 언어로 판정
    assert _geo_params("유럽 전력주 전망", "mixed") == {"country": "kr", "search_lang": "ko"}
    assert _geo_params("European utility stocks", "mixed") == {"country": "us", "search_lang": "en"}
```

그리고 `_x_all`이 질문 원문 대신 플래너 검색어를 쓰는지 — `run_ra_external`을 통째로 돌리긴 무거우므로 쿼리 선택 로직을 순수 함수로 추출해 테스트:

```python
from stages.ra_external import _unit_search_query
from contracts.packets import PlanPacket, SubQuestion


def _mini_plan(**kw):
    base = dict(tier=2, original_question="지금 유럽에 전력난이잖아. 유럽 전력주식들 조사해줘",
                standalone_question="유럽 전력주 조사", knowledge_cutoff="2026-07-06")
    base.update(kw)
    return PlanPacket(**base)


def test_unit_search_query_prefers_planner_queries():
    plan = _mini_plan(search_queries=["European utility stocks heatwave"])
    assert _unit_search_query(plan, "q0") == "European utility stocks heatwave"


def test_unit_search_query_falls_back_to_question():
    plan = _mini_plan()
    assert _unit_search_query(plan, "q0") == "유럽 전력주 조사"


def test_unit_search_query_subquestion():
    plan = _mini_plan(sub_questions=[SubQuestion(
        id="q1", text="유럽 유틸리티 주가", search_queries=["Iberdrola RWE stock 2026"])])
    assert _unit_search_query(plan, "q1") == "Iberdrola RWE stock 2026"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: FAIL — `ImportError: cannot import name '_geo_params'`

- [ ] **Step 3: Write minimal implementation**

(a) `_clean_pool` 아래에 헬퍼 두 개 추가:

```python
def _geo_params(query: str, market_scope: str) -> dict[str, str]:
    """market_scope → brave country/search_lang. mixed는 쿼리 언어로 판정."""
    if market_scope == "global":
        return {"country": "us", "search_lang": "en"}
    if market_scope == "mixed":
        has_ko = any("가" <= ch <= "힣" for ch in query)
        return {"country": "kr", "search_lang": "ko"} if has_ko \
            else {"country": "us", "search_lang": "en"}
    return {"country": "kr", "search_lang": "ko"}


def _unit_search_query(plan: PlanPacket, unit_id: str) -> str:
    """유닛의 검색 쿼리 — 플래너 검색어 우선, 없으면 질문 텍스트 폴백."""
    if unit_id == "q0":
        return (plan.search_queries[0] if plan.search_queries
                else plan.standalone_question or plan.original_question)
    for sq in plan.sub_questions:
        if sq.id == unit_id:
            return sq.search_queries[0] if sq.search_queries else sq.text
    return plan.standalone_question
```

(b) `_search_fallback` 시그니처에 지오 전달 추가 (tavily 폴백은 쿼리 언어 그대로 — 변경 없음):

```python
async def _search_fallback(query: str, *, freshness: str, client,
                           count: int = 5, geo: dict[str, str] | None = None) -> list[dict]:
```

내부의 `news_search(...)` 호출에 `**(geo or {})` 전달:

```python
        rows = await news_search(query, count=count, freshness=freshness,
                                 client=client, **(geo or {}))
```

(c) `_x_unit` — 질문 원문 대신 선택된 쿼리 + freshness pd→pw + 지오:

```python
async def _x_unit(unit_id: str, query: str, *, geo: dict[str, str],
                  client) -> tuple[str, list[dict]]:
    """유닛 1개의 x_search — 주간(freshness=pw) 뉴스. brave→tavily 폴백."""
    rows = await _search_fallback(query, freshness="pw", client=client, geo=geo)
    return unit_id, rows
```

(d) `_x_all` 내 유닛 구성부를 쿼리·지오 기반으로 교체:

```python
            units = [("q0", _unit_search_query(plan, "q0"))]
            for sq in plan.sub_questions:
                if sq.search_queries and len(units) < _MAX_X_UNITS:
                    units.append((sq.id, _unit_search_query(plan, sq.id)))
            results = await asyncio.gather(
                *(_x_unit(uid, q, geo=_geo_params(q, plan.market_scope), client=hc)
                  for uid, q in units),
                return_exceptions=True,
            )
```

(e) `_brave_all` 내 `_search_fallback(q, freshness=freshness, client=hc)` 호출을:

```python
                    for r in await _search_fallback(
                            q, freshness=freshness, client=hc,
                            geo=_geo_params(q, plan.market_scope)):
```

(f) gather 직후, `_assign_ids` **앞**에 풀 정리 삽입 (ra_external.py:485 근처):

```python
        # 노이즈 제거 — 커뮤니티/중복은 curation 이전에 탈락 (2026-07-06)
        for pool in (x_search, web_knowledge):
            for uid in list(pool):
                pool[uid] = _clean_pool(pool[uid])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py tests/test_p1_offline.py tests/test_contracts.py -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add engine/stages/ra_external.py engine/tests/test_search_quality.py
git commit -m "feat(search): 플래너 검색어 사용 + freshness pw + 지오 라우팅 + 풀 정리 적용"
```

---

### Task 5: Sonnet 역할 등록 — settings + ROLE_MAP + 단가 버킷

**Files:**
- Modify: `engine/app/settings.py`
- Modify: `engine/providers.py`
- Test: `engine/tests/test_search_quality.py` (추가)

**Interfaces:**
- Produces: `settings.model_claude_sonnet == "claude-sonnet-4-6"`, `ROLE_MAP["news_summary"]`, `CostMeter`가 sonnet 콜을 `anthropic_sonnet` 버킷 `(3.0, 15.0)`으로 집계.

- [ ] **Step 1: Write the failing test**

```python
from app.settings import settings as app_settings
from providers import ROLE_MAP, CostMeter, _PRICE_PER_M


def test_news_summary_role_uses_sonnet():
    chain = ROLE_MAP["news_summary"]
    assert chain[0] == ("anthropic", "claude-sonnet-4-6", "low")
    assert chain[1][0] == "openai"  # gpt-mini 폴백


def test_sonnet_price_bucket():
    assert _PRICE_PER_M["anthropic_sonnet"] == (3.0, 15.0)
    meter = CostMeter()
    meter.add("anthropic", "claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert meter.usd["claude"] == pytest.approx(18.0)  # 3 + 15


def test_opus_bucket_unchanged():
    meter = CostMeter()
    meter.add("anthropic", "claude-opus-4-8", 1_000_000, 0)
    assert meter.usd["claude"] == pytest.approx(5.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: FAIL — `KeyError: 'news_summary'`

- [ ] **Step 3: Write minimal implementation**

(a) `settings.py` 모델 블록에 추가:

```python
    model_claude_sonnet: str = "claude-sonnet-4-6"  # 뉴스 요약 등 경량 역할 ($3/$15, 2026-07-06 검증)
```

(b) `providers.py` ROLE_MAP에 추가 (audit 아래):

```python
    "news_summary": [("anthropic", settings.model_claude_sonnet, "low"),
                     ("openai", settings.model_gpt_mini, "low")],
```

(c) `_PRICE_PER_M`에 버킷 추가:

```python
    "anthropic_sonnet": (3.0, 15.0),  # claude-sonnet-4-6 ($3/$15) — 2026-07-06 공식 단가 검증
```

(d) `CostMeter.add`의 버킷 판정을 sonnet 인지로 확장 (기존 두 줄 교체):

```python
        is_mini = "mini" in (model or "")
        if provider == "openai" and is_mini:
            bucket = "openai_mini"
        elif provider == "anthropic" and "sonnet" in (model or ""):
            bucket = "anthropic_sonnet"
        else:
            bucket = provider
```

참고: `_record`의 label 매핑에 `"anthropic_sonnet": "claude"` 추가 필요:

```python
        label = {"anthropic": "claude", "anthropic_sonnet": "claude",
                 "openai": "openai", "openai_mini": "openai"}.get(bucket, bucket)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py tests/test_registry.py -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add engine/app/settings.py engine/providers.py engine/tests/test_search_quality.py
git commit -m "feat(providers): news_summary 역할 추가 (sonnet-4-6, $3/$15 버킷)"
```

---

### Task 6: news_summary 스테이지 — Sonnet이 큐레이션 뉴스 요약

**Files:**
- Create: `engine/stages/news_summary.py`
- Modify: `engine/contracts/packets.py` (NewsSummaryPacket, LAYER_NAMES)
- Test: `engine/tests/test_search_quality.py` (추가)

**Interfaces:**
- Produces: `run_news_summary(plan: PlanPacket, ra: RaPacket, overrides: dict | None = None) -> NewsSummaryPacket | None` — 큐레이션 뉴스 없으면 None, LLM 실패는 raise (호출자가 degrade).
- Produces: `NewsSummaryPacket(lines: list[NewsSummaryLine], as_of: str)`, `NewsSummaryLine(text: str, url: str)`.
- Consumes: Task 5의 `Role("news_summary")`, `RaPacket.curated_items()`.

- [ ] **Step 1: Write the failing test**

```python
from contracts.packets import NewsSummaryPacket, NewsSummaryLine, LAYER_NAMES, RaPacket
from stages import news_summary as ns_stage


def test_news_summary_layer_registered():
    assert "news_summary" in LAYER_NAMES


@pytest.mark.asyncio
async def test_news_summary_returns_none_without_news():
    plan = _mini_plan()
    ra = RaPacket(status="ok")
    assert await ns_stage.run_news_summary(plan, ra) is None


@pytest.mark.asyncio
async def test_news_summary_builds_packet(monkeypatch):
    plan = _mini_plan()
    ra = RaPacket(status="ok", x_search={"q0": [NewsItem(
        id="q0:n0", title="Heat wave hits Europe", summary="3,700 deaths",
        url="https://dw.com/a")]})

    class _FakeRole:
        def __init__(self, *a, **k):
            pass

        async def run(self, *a, **k):
            return ns_stage._Summary(lines=[
                ns_stage._Line(text="유럽 폭염으로 전력 수요 급증", url="https://dw.com/a")])

    monkeypatch.setattr(ns_stage, "Role", _FakeRole)
    packet = await ns_stage.run_news_summary(plan, ra)
    assert isinstance(packet, NewsSummaryPacket)
    assert packet.lines[0].url == "https://dw.com/a"
    assert packet.as_of == "2026-07-06"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: FAIL — `ImportError` (NewsSummaryPacket / stages.news_summary 없음)

- [ ] **Step 3: Write minimal implementation**

(a) `packets.py` — `LAYER_NAMES`에 `"news_summary"` 추가:

```python
LAYER_NAMES = (
    "triage", "plan", "da_blind", "ra_x", "ra_web", "news_summary",
    "toss_trend", "toss_company", "price", "macro", "claims", "calc",
    "verify", "risk", "audit", "trace",
)
```

(b) `packets.py` — `NewsItem` 클래스 위에 추가:

```python
class NewsSummaryLine(_Strict):
    text: str
    url: str = ""


class NewsSummaryPacket(_Strict):
    """큐레이션 뉴스의 질문-관점 요약 (news_summary 역할, sonnet) — UI 패널 + 합성 투입."""

    lines: list[NewsSummaryLine] = Field(default_factory=list)
    as_of: str = ""
```

(c) `engine/stages/news_summary.py` 생성:

```python
"""NEWS_SUMMARY — 큐레이션 통과 뉴스를 질문 관점에서 요약 (sonnet, low).

실패 시 raise — 오케스트레이터가 degrade 처리 (파이프라인 비차단).
큐레이션 뉴스가 없으면 None (요약할 것이 없음 ≠ 실패).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from contracts.packets import NewsSummaryLine, NewsSummaryPacket, PlanPacket, RaPacket
from providers import Role

_MAX_ITEMS = 15          # 입력 뉴스 상한 (유닛 균등)
_MAX_LINES = 6


class _Line(BaseModel):
    text: str
    url: str = ""


class _Summary(BaseModel):
    lines: list[_Line] = Field(default_factory=list)


_INSTR = """너는 금융 뉴스 브리핑 작성자다. 질문에 답하지 마라. 뉴스 요약만 한다.
- 질문과 직접 관련된 사실만 3~6줄. 한 줄 = 한 사실 + 해당 출처 url.
- 관련 없는 기사는 무시하라. 요약할 관련 기사가 없으면 lines를 빈 배열로.
- 숫자·날짜는 기사에 있는 그대로. 지어내지 마라."""


async def run_news_summary(plan: PlanPacket, ra: RaPacket,
                           overrides: dict | None = None) -> NewsSummaryPacket | None:
    pools = ra.curated_items()
    items = [n for lst in pools.values() for n in lst][:_MAX_ITEMS]
    if not items:
        return None

    lines = "\n".join(
        f"- [{n.published_at or '?'}] {n.title} — {n.summary[:200]} ({n.url})"
        for n in items)
    prompt = (f"[질문] {plan.standalone_question or plan.original_question}\n"
              f"[기준시점] {plan.knowledge_cutoff}\n[뉴스]\n{lines}")

    role = Role("news_summary", overrides)
    val: _Summary = await role.run(prompt, _INSTR, response_format=_Summary)
    return NewsSummaryPacket(
        lines=[NewsSummaryLine(text=l.text, url=l.url) for l in val.lines[:_MAX_LINES]],
        as_of=plan.knowledge_cutoff,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py tests/test_contracts.py -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add engine/stages/news_summary.py engine/contracts/packets.py engine/tests/test_search_quality.py
git commit -m "feat(stages): news_summary 스테이지 — sonnet이 큐레이션 뉴스 요약"
```

---

### Task 7: 오케스트레이터·합성 연결 — ra_x 큐레이션 방출 + news_summary 레이어/합성 투입

**Files:**
- Modify: `engine/orchestrator.py` (ra_x 방출부 :177-182, news_summary 호출·방출, run_synthesize 호출부 :343-345)
- Modify: `engine/stages/synthesize.py` (`_render_context`·`run_synthesize`에 news_summary 추가)
- Test: `engine/tests/test_search_quality.py` (추가)

**Interfaces:**
- Consumes: Task 6의 `run_news_summary`, `NewsSummaryPacket`.
- Produces: `orchestrator._ra_x_layer_data(ra: RaPacket) -> dict` (테스트 가능하도록 추출), `run_synthesize(..., news_summary: NewsSummaryPacket | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
from orchestrator import _ra_x_layer_data


def test_ra_x_layer_emits_curated_only():
    raw = [NewsItem(id=f"q0:n{i}", title=f"t{i}", url=f"https://ex.com/{i}") for i in range(4)]
    ra = RaPacket(status="ok", x_search={"q0": raw}, curated={"q0": ["q0:n1", "q0:n3"]})
    data = _ra_x_layer_data(ra)
    urls = [it["url"] for it in data["items"]]
    assert urls == ["https://ex.com/1", "https://ex.com/3"]


def test_ra_x_layer_falls_back_to_all_when_no_curation():
    raw = [NewsItem(id="q0:n0", title="t", url="https://ex.com/0")]
    ra = RaPacket(status="ok", x_search={"q0": raw})
    assert len(_ra_x_layer_data(ra)["items"]) == 1
```

그리고 synthesize 컨텍스트에 요약 블록이 들어가는지:

```python
from contracts.packets import DaPacket
from stages.synthesize import _render_context


def test_render_context_includes_news_summary():
    plan = _mini_plan()
    summary = NewsSummaryPacket(lines=[NewsSummaryLine(
        text="유럽 폭염으로 전력 수요 급증", url="https://dw.com/a")], as_of="2026-07-06")
    ctx = _render_context(plan, DaPacket(status="ok"), None, None, None, None, [], None,
                          news_summary=summary)
    assert "[뉴스 요약]" in ctx
    assert "https://dw.com/a" in ctx
```

주의: `_render_context`의 현재 위치 인자 순서는 `(plan, da, ra, price, claim_table, verdict, calc_results, risk)` — 구현 전 `engine/stages/synthesize.py:139` 부근에서 실제 시그니처를 확인하고 테스트의 인자를 맞출 것.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/test_search_quality.py -v`
Expected: FAIL — `ImportError: cannot import name '_ra_x_layer_data'`

- [ ] **Step 3: Write minimal implementation**

(a) `orchestrator.py` — 헬퍼 추가 (`_plan_layer_data` 등 기존 헬퍼 근처):

```python
def _ra_x_layer_data(ra: RaPacket) -> dict:
    """ra_x 레이어 — 사용자에게는 큐레이션 통과분만 (raw 노출 금지, 2026-07-06)."""
    items = []
    for pool_items in ra.curated_items().values():
        for n in pool_items[:6]:
            items.append({"title": n.title, "url": n.url, "published_at": n.published_at})
    return {"narrative": ra.x_narrative, "items": items[:12]}
```

(b) `orchestrator.py:177-182`의 기존 ra_x 방출부를 교체:

```python
    if ra.x_narrative or ra.x_search:
        yield _layer("ra_x", _ra_x_layer_data(ra))
```

(c) `orchestrator.py` — ra_x 방출 직후 news_summary 실행·방출 추가 (import `from stages.news_summary import run_news_summary` 포함):

```python
    # NEWS_SUMMARY (sonnet) — 실패해도 비차단 (degrade)
    news_sum = None
    try:
        news_sum = await run_news_summary(plan, ra, overrides)
        if news_sum and news_sum.lines:
            yield _layer("news_summary", {
                "lines": [{"text": l.text, "url": l.url} for l in news_sum.lines],
                "as_of": news_sum.as_of,
            })
            models_used.add("sonnet-4.6")
    except Exception:  # noqa: BLE001
        degraded.append("news_summary")
```

(d) `orchestrator.py:343-345` — run_synthesize 호출에 전달:

```python
        draft = await run_synthesize(
            plan, da, ra=ra, price=pm.model_dump(), claim_table=table,
            verdict=verdict, calc_results=calc_results, risk=risk,
            news_summary=news_sum, overrides=overrides)
```

(e) `synthesize.py` — `_render_context` 시그니처 끝에 `news_summary=None` 키워드 추가, `[시장 트렌드]` 블록 앞에 삽입:

```python
    if news_summary and news_summary.lines:
        parts.append("[뉴스 요약 — 질문 관련 최신 사실]\n" + "\n".join(
            f"- {l.text} ({l.url})" for l in news_summary.lines))
```

`run_synthesize` 시그니처에 `news_summary=None` 추가하고 `_render_context` 호출에 전달:

```python
async def run_synthesize(plan: PlanPacket, da: DaPacket, *,
                         ra: RaPacket | None = None, price: dict | None = None,
                         claim_table: ClaimTable | None = None,
                         verdict: VerdictPacket | None = None,
                         calc_results: list[CalcResult] | None = None,
                         risk: RiskPacket | None = None,
                         news_summary=None,
                         overrides: dict | None = None) -> DraftAnswer:
    ctx = _render_context(plan, da, ra, price, claim_table, verdict,
                          calc_results or [], risk, news_summary=news_summary)
```

- [ ] **Step 4: Run full test suite**

Run: `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/ -v --ignore=tests/test_stages_live.py --ignore=tests/test_price_live.py --ignore=tests/test_toss_live.py`
Expected: 전부 PASS (live 테스트 제외)

- [ ] **Step 5: Commit**

```bash
git add engine/orchestrator.py engine/stages/synthesize.py engine/tests/test_search_quality.py
git commit -m "feat(orchestrator): ra_x 큐레이션 방출 + news_summary 레이어·합성 연결"
```

---

### Task 8: 프론트 뉴스 패널 — news_summary 레이어 렌더

**Files:**
- Modify: `public/index.html` (레이어 렌더러 — `ra_x` 레이어를 그리는 위치를 `grep -n "ra_x" public/index.html`로 찾아 그 위에 news_summary 블록 추가)
- Test: 수동 확인 (프론트 자동 테스트 없음 — 기존 코드베이스 관행 따름)

**Interfaces:**
- Consumes: Task 7의 `news_summary` 레이어 `{lines: [{text, url}], as_of}`.

- [ ] **Step 1: 기존 ra_x 렌더러 확인**

Run: `grep -n "ra_x\|toss_trend" /home/ryze_yn/attn-viewer/public/index.html | head -20`
기존 레이어 렌더 패턴(레이어 name → 렌더 함수 매핑)을 파악한다.

- [ ] **Step 2: news_summary 렌더 추가**

기존 패턴을 그대로 따라 `news_summary` 케이스 추가 — 요약 줄들을 뉴스 패널 상단에 리스트로, 각 줄 뒤 출처 링크. 스타일·클래스는 기존 ra_x 아이템과 동일 체계 사용 (새 CSS 최소화).

- [ ] **Step 3: 수동 확인**

Run: `node /home/ryze_yn/attn-viewer/server.mjs` (또는 기존 실행 중 서버 재시작) 후 브라우저에서 질문 1건 실행, 뉴스 패널 상단에 요약이 뜨고 기사 목록이 큐레이션분만인지 확인.

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "feat(ui): 뉴스 패널에 news_summary 요약 표시"
```

---

### Task 9: 실전 회귀 — 유럽 전력주 질문 재실행 (live)

**Files:** 없음 (검증 전용)

- [ ] **Step 1: live 스모크**

엔진 실행 환경에서 실제 질문 1건: "지금 유럽에 전력난이잖아. 유럽 전력주식들 조사해줘" 를 UI 또는 엔진 API로 실행.

- [ ] **Step 2: 검증 항목**

- plan 레이어: `market_scope == "global"`, search_queries가 영어
- ra_x 레이어: 커뮤니티 도메인 0건, 삼전/하이닉스류 국내 기사 감소
- news_summary 레이어 존재, 줄마다 출처 URL
- 최종 답변에 `[뉴스 요약]` 근거 반영
- cost summary에 sonnet 비용 집계 확인

- [ ] **Step 3: 이상 시**

실패 항목을 재현 픽스처로 `test_search_quality.py`에 추가하고 해당 Task로 돌아가 수정 (memory: 대량 실패·동일 사유 반복은 정책이 아니라 버그 신호).

---

## Self-Review 결과

- 스펙 커버리지: §1(플랜)→Task 3, §2(검색기)→Task 1·2·4, §3(Sonnet)→Task 5·6, §4(노출)→Task 7·8, §5(테스트 두 층)→각 Task 테스트 + Task 2 회귀 픽스처 + Task 9 live. 비범위(toss/macro 조건부) 미포함 확인.
- 타입 일관성: `_clean_pool`/`_geo_params`/`_unit_search_query`/`run_news_summary`/`_ra_x_layer_data` 이름·시그니처가 Task 간 일치.
- 플레이스홀더 없음 (Task 8 프론트는 기존 렌더 패턴 답습 지시 — 파일 구조가 단일 HTML이라 grep 후 답습이 정확한 방식).
