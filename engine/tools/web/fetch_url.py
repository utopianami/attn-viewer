"""사용자가 채팅에 붙인 URL의 기사 본문 수집 — httpx GET → trafilatura.extract.

기존 뉴스 본문 수집기(tools/news/fetch_body)와 같은 방식(httpx+trafilatura)을 재사용한다.
유료·로그인·차단·JS-only 페이지는 본문이 안 나오므로 status로 구분해 상위(orchestrator)에서
사용자에게 "접근 불가"를 안내하게 한다. 절대 추측으로 본문을 지어내지 않는다.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 질문 텍스트에서 http(s) URL 추출 — 공백·따옴표·괄호 등 경계 문자 전까지
_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"'`|]+")

_MIN_CHARS = 250      # 본문이 이보다 짧으면 유료/로그인/차단/JS-only 로 간주
_MAX_CHARS = 4000     # NewsItem.content 상한과 동일
_MAX_URLS = 3         # 한 질문에서 처리할 링크 상한 (지연·비용 보호)
_TIMEOUT_S = 10.0
_MAX_BYTES = 5_000_000     # 응답 본문 상한 (대용량/바이너리 방어)
_MAX_REDIRECTS = 4         # 수동 리다이렉트 추적 상한


@dataclass
class FetchedArticle:
    url: str
    status: str               # "ok" | "blocked" | "error"
    title: str = ""
    content: str = ""
    site: str = ""
    published_at: str = ""
    reason: str = ""          # blocked/error 사유 (http_403, paywall_or_empty, ...)


def extract_urls(text: str) -> list[str]:
    """질문 텍스트에서 고유 http(s) URL을 앞에서부터 최대 _MAX_URLS개."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,);]}'\"…")   # 문장부호 꼬리 제거
        if u and u not in seen:
            seen.add(u)
            out.append(u)
            if len(out) >= _MAX_URLS:
                break
    return out


def _is_safe_url(url: str) -> bool:
    """SSRF 방어 — http(s)만 허용, 내부망·loopback·link-local(클라우드 메타데이터)로
    해석되는 호스트는 차단. 사용자가 임의 URL을 붙이면 서버가 그걸 GET하기 때문."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _looks_html(resp) -> bool:
    ctype = (resp.headers.get("content-type") or "").lower()
    if ctype and not any(t in ctype for t in ("text/html", "application/xhtml", "text/plain")):
        return False
    clen = resp.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > _MAX_BYTES:
        return False
    return True


async def _safe_get(url: str, client):
    """리다이렉트를 수동 추적하며 매 홉마다 _is_safe_url 재검사 (SSRF: 최초 호스트만
    검사하고 자동 리다이렉트하면 공개→내부망 우회가 가능하다). 본문은 스트리밍하며
    _MAX_BYTES에서 중단(대용량/바이너리로 메모리 폭주 방지). 반환: (html_text, error_reason)."""
    from urllib.parse import urljoin
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not _is_safe_url(current):
            return None, "blocked_host"
        async with client.stream("GET", current, headers={"User-Agent": _UA},
                                 follow_redirects=False) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    return None, f"http_{resp.status_code}"
                current = urljoin(current, loc)   # 상대 Location 처리
                continue
            if resp.status_code != 200:
                return None, f"http_{resp.status_code}"
            if not _looks_html(resp):
                return None, "not_html_or_too_large"
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > _MAX_BYTES:          # content-length 미표기여도 실제 크기로 중단
                    return None, "not_html_or_too_large"
            if not body:
                return None, "empty"
            return body.decode(resp.encoding or "utf-8", errors="replace"), ""
    return None, "too_many_redirects"


async def _fetch_one(url: str, client) -> FetchedArticle:
    try:
        import trafilatura
    except ImportError:
        return FetchedArticle(url, "error", reason="extractor_unavailable")
    if not _is_safe_url(url):
        return FetchedArticle(url, "blocked", reason="blocked_host")
    try:
        html, err = await _safe_get(url, client)
    except Exception as exc:
        return FetchedArticle(url, "error", reason=f"fetch_failed:{type(exc).__name__}")
    if err:
        return FetchedArticle(url, "blocked", reason=err)
    if not html:
        return FetchedArticle(url, "blocked", reason="empty")
    try:
        text = trafilatura.extract(html, include_comments=False,
                                   include_tables=False)
    except Exception as exc:
        return FetchedArticle(url, "error", reason=f"extract_failed:{type(exc).__name__}")
    if not text or len(text.strip()) < _MIN_CHARS:
        # 본문 미검출 = 유료/로그인/봇차단/JS-only. 지어내지 말고 blocked로.
        return FetchedArticle(url, "blocked", reason="paywall_or_empty")
    title = site = published = ""
    try:
        md = trafilatura.extract_metadata(html)
        if md:
            title = (md.title or "")[:300]
            site = md.sitename or ""
            published = md.date or ""
    except Exception:
        pass
    return FetchedArticle(url, "ok", title=title,
                          content=text.strip()[:_MAX_CHARS],
                          site=site, published_at=published)


async def fetch_articles(urls: list[str], *, timeout_s: float = _TIMEOUT_S) -> list[FetchedArticle]:
    """URL 목록을 병렬 수집. 각 항목은 개별적으로 ok/blocked/error 판정된다."""
    if not urls:
        return []
    import httpx
    async with httpx.AsyncClient(timeout=timeout_s) as hc:
        results = await asyncio.gather(*(_fetch_one(u, hc) for u in urls),
                                       return_exceptions=True)
    out: list[FetchedArticle] = []
    for u, r in zip(urls, results):
        if isinstance(r, BaseException):
            out.append(FetchedArticle(u, "error", reason=f"gather:{type(r).__name__}"))
        else:
            out.append(r)
    return out
