"""구글 뉴스 RSS 검색 — 해외 뉴스 담당 (2026-07-09 구성: 국내=네이버, 해외=구글뉴스 RSS).

무료·키 불요. `when:` 연산자로 시의성 제어 (freshness pd→1d, pw→7d 대응).
주의: ① 비공식 피드 — 형식 변경 리스크 ② 기사 link가 news.google.com 리다이렉트 URL
(브라우저에선 원문으로 넘어가나 서버측 본문 수집은 안 됨 — description 요약으로 보충).
표준 xml 파서만 사용 (신규 의존성 금지 — sector/collectors/rss.py와 동일 원칙).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

_URL = "https://news.google.com/rss/search"
_UA = {"User-Agent": "Mozilla/5.0"}
_FRESH_TO_WHEN = {"pd": "1d", "pw": "7d", "pm": "30d"}
_HTML_RE = re.compile(r"<[^>]+>")

# 구글 리다이렉트 → 원문 URL 해석 (sector/collectors/brave_matrix.py 검증 구현 포트, 2026-07 동작).
# batchexecute는 비공식 내부 엔드포인트 — 언제든 깨질 수 있어 실패=None(구글 링크 유지)이 정상
# 경로이고, 대량 호출 시 429 — 저강도(질문당 상위 몇 건)로만 쓸 것.
_GN_SG = re.compile(r'data-n-a-sg="([^"]+)"')
_GN_TS = re.compile(r'data-n-a-ts="(\d+)"')
_GN_RES = re.compile(r'garturlres\\",\\"(https?://[^\\"]+)')
_GN_BATCH = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


async def resolve_gn_url(url: str, client: httpx.AsyncClient) -> str | None:
    """news.google.com 리다이렉트 → 원문 URL. 실패 시 None (호출자가 구글 링크 유지)."""
    import json as _json
    m = re.search(r"articles/([^?/]+)", url)
    if not m:
        return None
    try:
        page = await client.get(url, follow_redirects=True)
        sg, ts = _GN_SG.search(page.text), _GN_TS.search(page.text)
        if not (sg and ts):
            return None
        inner = _json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
              None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            m.group(1), int(ts.group(1)), sg.group(1)])
        resp = await client.post(_GN_BATCH,
                                 data={"f.req": _json.dumps([[["Fbv4je", inner, None, "generic"]]])},
                                 headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"})
        found = _GN_RES.search(resp.text)
        return found.group(1) if found else None
    except Exception:  # noqa: BLE001
        return None


def _iso(pub: str) -> str:
    try:
        return parsedate_to_datetime(pub).date().isoformat()
    except Exception:
        return ""


async def gnews_search(query: str, *, count: int = 5, freshness: str = "pw",
                       lang: str = "en", resolve: int = 3,
                       client: httpx.AsyncClient | None = None) -> list[dict]:
    """뉴스 검색. lang: en(미국판)|ko(한국판). 실패 시 빈 리스트 (never-raise는 호출자).

    resolve: 상위 N건의 원문 URL 해석 시도 (429 방지 저강도 원칙 — 실패 시 구글 링크 유지).
    """
    when = _FRESH_TO_WHEN.get(freshness, "7d")
    if lang == "ko":
        params = {"q": f"{query} when:{when}", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    else:
        params = {"q": f"{query} when:{when}", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, headers=_UA, follow_redirects=True)
    try:
        resp = await client.get(_URL, params=params)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        out = []
        for item in root.iter("item"):
            if len(out) >= count:
                break
            title = (item.findtext("title") or "").strip()
            source = (item.findtext("source") or "").strip()
            # 제목 꼬리의 " - 매체명" 제거 (source 태그와 중복)
            if source and title.endswith(f" - {source}"):
                title = title[: -len(source) - 3].strip()
            desc = _HTML_RE.sub("", item.findtext("description") or "").strip()
            out.append({
                "title": title,
                "url": (item.findtext("link") or "").strip(),
                "description": desc[:300],
                "age": _iso(item.findtext("pubDate") or ""),
                "source": source,
            })
        for r in out[:max(resolve, 0)]:
            real = await resolve_gn_url(r["url"], client)
            if real:
                r["url"] = real
                r["source"] = httpx.URL(real).host or r["source"]
        return out
    finally:
        if own:
            await client.aclose()
