# engine/sector/collectors/brave_matrix.py
"""축별 쿼리 매트릭스 — 기존 brave 도구 + geo 라우팅 + 커뮤니티/URL 필터 재사용."""
from __future__ import annotations

import hashlib
import re

import httpx

from sector.contracts import CollectorResult, RawNewsItem
from sector.store import SectorStore
from stages.ra_external import _BLOCKED_DOMAINS, _norm_url
from tools.news.brave import news_search

NAME = "brave_matrix"
KIND = "news"
_HANGUL = re.compile(r"[가-힣]")

# (axis, query) — 2026-07-09 다이어트: 18→8개, 월 무료 크레딧($5=1,000쿼리) 안에서 운용.
# 뺀 것의 근거: 한국어 일반 뉴스=SaveTicker·RSS가 실시간 커버 / MU·빅테크 실적 숫자=
# EDGAR·capex 수집기가 커버 / E축(폰·PC)=KOSIS·수출 지표+SaveTicker가 커버.
_QUERIES: list[tuple[str, str]] = [
    ("A", "SK Hynix HBM supply contract"),      # HBM 계약·인증 — tightness 원료
    ("A", "Samsung DRAM price"),                # 가격 방향 뉴스
    ("A", "메모리 고정거래가격"),                 # 국내 고정가 — 지오 라우팅 유지
    ("A_prime", "TSMC CoWoS capacity"),         # 패키징 병목 — HBM 선행
    ("B", "hyperscaler AI capex memory"),       # 수요 원천 (4사 통합 쿼리)
    ("C", "AI inference demand"),               # 토큰 수요 서사
    ("P", "HBM export control"),                # 정책 충격
    ("P", "CXMT DRAM capacity"),                # 중국 공급 — tightness 완화 신호
]


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    items: list[RawNewsItem] = []
    seen: set[str] = set()
    fails = 0
    for axis, q in _QUERIES:
        kr = bool(_HANGUL.search(q))
        try:
            rows = await news_search(q, count=5, freshness="pd",
                                     country="kr" if kr else "us",
                                     search_lang="ko" if kr else "en", client=client)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 402:
                # 월 크레딧 소진 — 나머지 쿼리 헛호출 금지, 다음 결제주기에 자동 복구
                return CollectorResult(
                    name=NAME, kind=KIND, items=items, status="degraded",
                    detail="quota_exceeded — Brave 월 무료 크레딧 소진 (다음 달 자동 복구)")
            fails += 1
            continue
        except Exception:  # noqa: BLE001
            fails += 1
            continue
        for r in rows:
            url = r.get("url") or ""
            host = (r.get("source") or "").lower()
            if any(host.endswith(d) for d in _BLOCKED_DOMAINS):
                continue
            nu = _norm_url(url)
            if nu in seen:
                continue
            seen.add(nu)
            items.append(RawNewsItem(
                id="bv-" + hashlib.sha1(nu.encode()).hexdigest()[:12],
                title=r.get("title") or "", preview=r.get("description") or "",
                content=r.get("description") or "", source=host, url=url,
                published_at="",  # brave age("2 hours ago")는 타임스탬프가 아님 — extra로
                extra={"axis_hint": axis, "query": q, "age": r.get("age") or ""}))
    status = "ok" if fails == 0 else "degraded"
    return CollectorResult(name=NAME, kind=KIND, items=items, status=status,
                           detail="" if not fails else f"query_fail={fails}")
