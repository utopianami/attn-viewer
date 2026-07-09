# engine/sector/collectors/brave_matrix.py
"""축별 쿼리 매트릭스 — Google News RSS(무키) + geo 라우팅 + 커뮤니티/URL 필터 (2026-07-09 brave 제거)."""
from __future__ import annotations

import email.utils
import hashlib
import json
import re
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from sector.contracts import CollectorResult, RawNewsItem
from sector.store import SectorStore
from stages.ra_external import _BLOCKED_DOMAINS, _norm_url

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


# Google News RSS 폴백 — 무키·무료. brave 크레딧 소진 시에만 사용 (비공식 피드라
# 저강도 원칙: 8쿼리×2회/일. 깨지면 fail 카운트로 드러남 — SaveTicker와 같은 취급)
_GN_URL = "https://news.google.com/rss/search"


async def _google_news(q: str, kr: bool, client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get(_GN_URL, params={
        "q": f"{q} when:1d",
        "hl": "ko" if kr else "en-US",
        "gl": "KR" if kr else "US",
        "ceid": "KR:ko" if kr else "US:en"})
    resp.raise_for_status()
    out = []
    for it in ElementTree.fromstring(resp.content).iter("item"):
        pub = it.findtext("pubDate") or ""
        try:
            iso = email.utils.parsedate_to_datetime(pub).isoformat() if pub else ""
        except Exception:  # noqa: BLE001
            iso = ""
        src = it.find("source")
        out.append({"title": (it.findtext("title") or "").strip(),
                    "url": (it.findtext("link") or "").strip(),
                    "published_at": iso,
                    "source": ((src.text if src is not None else "") or "").strip().lower()})
    return out


# 구글 리다이렉트 → 원문 URL 해석 (커뮤니티 batchexecute 방식 — 2026-07 동작 확인).
# 비공식 우회라 언제든 깨질 수 있음 — 실패하면 None 반환, 호출자가 구글 링크 유지 (never-block).
_GN_SG = re.compile(r'data-n-a-sg="([^"]+)"')
_GN_TS = re.compile(r'data-n-a-ts="(\d+)"')
_GN_RES = re.compile(r'garturlres\\",\\"(https?://[^\\"]+)')
_GN_BATCH = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


async def _resolve_gn_url(url: str, client: httpx.AsyncClient) -> str | None:
    m = re.search(r"articles/([^?/]+)", url)
    if not m:
        return None
    try:
        page = await client.get(url, follow_redirects=True)
        sg, ts = _GN_SG.search(page.text), _GN_TS.search(page.text)
        if not (sg and ts):
            return None
        inner = json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
              None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            m.group(1), int(ts.group(1)), sg.group(1)])
        resp = await client.post(_GN_BATCH,
                                 data={"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]])},
                                 headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"})
        found = _GN_RES.search(resp.text)
        return found.group(1) if found else None
    except Exception:  # noqa: BLE001
        return None


async def _google_news_fallback(client: httpx.AsyncClient | None,
                                seen: set[str], items: list[RawNewsItem]) -> int:
    own = client is None
    client = client or httpx.AsyncClient(
        timeout=15, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    fails = 0
    try:
        for axis, q in _QUERIES:
            kr = bool(_HANGUL.search(q))
            try:
                rows = await _google_news(q, kr, client)
            except Exception:  # noqa: BLE001 — 쿼리 격리
                fails += 1
                continue
            for r in rows[:5]:
                if not r["title"] or not r["url"]:
                    continue
                real = await _resolve_gn_url(r["url"], client)
                if real:
                    host = urlparse(real).netloc.lower()
                    if any(host.endswith(d) for d in _BLOCKED_DOMAINS):
                        continue
                    r["url"], r["source"] = real, host
                nu = _norm_url(r["url"])
                if nu in seen:
                    continue
                seen.add(nu)
                items.append(RawNewsItem(
                    id="gn-" + hashlib.sha1(nu.encode()).hexdigest()[:12],
                    title=r["title"], preview=r["title"], content=r["title"],
                    source=r["source"] or "news.google.com", url=r["url"],
                    published_at=r["published_at"],
                    extra={"axis_hint": axis, "query": q, "via": "google_news_rss"}))
    finally:
        if own:
            await client.aclose()
    return fails


async def collect(store: SectorStore, client: httpx.AsyncClient | None = None) -> CollectorResult:
    """Google News RSS 주 경로 (2026-07-09 brave 완전 제거 — 기존 402 폴백을 승격).

    이름(NAME="brave_matrix")은 store·스케줄러 호환 위해 유지 — 실체는 gn 매트릭스.
    """
    items: list[RawNewsItem] = []
    seen: set[str] = set()
    fails = await _google_news_fallback(client, seen, items)
    status = "ok" if fails == 0 else "degraded"
    return CollectorResult(name=NAME, kind=KIND, items=items, status=status,
                           detail="" if not fails else f"query_fail={fails}")
