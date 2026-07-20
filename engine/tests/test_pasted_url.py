"""사용자가 붙인 링크 처리 — URL 추출 + 접근성/페이월 판정 (오프라인, 네트워크 미사용)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.web.fetch_url as fu  # noqa: E402


def test_extract_urls_basic_and_trailing_punct():
    q = "이 기사 봐줘 https://n.news.naver.com/article/015/0005311853?sid=101 그리고 (https://ex.com/a)."
    urls = fu.extract_urls(q)
    assert urls[0] == "https://n.news.naver.com/article/015/0005311853?sid=101"
    assert "https://ex.com/a" in urls  # 닫는 괄호·마침표는 꼬리 제거


def test_extract_urls_dedup_and_cap():
    q = " ".join(f"http://x.com/{i}" for i in range(10)) + " http://x.com/0"
    urls = fu.extract_urls(q)
    assert len(urls) == fu._MAX_URLS          # 상한 적용
    assert len(urls) == len(set(urls))        # 중복 제거


def test_no_urls():
    assert fu.extract_urls("그냥 삼성전자 per 알려줘") == []


class _Resp:
    """스트리밍 응답 흉내 — status_code/headers/encoding + aiter_bytes."""
    def __init__(self, status_code, text="", headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.encoding = "utf-8"
        self._body = (text or "").encode()

    async def aiter_bytes(self):
        yield self._body


class _Ctx:
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc

    async def __aenter__(self):
        if self._exc:
            raise self._exc
        return self._resp

    async def __aexit__(self, *a):
        return False


class _Client:
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc

    def stream(self, method, url, **kw):
        assert kw.get("follow_redirects") is False   # 자동 리다이렉트 꺼져 있어야 (SSRF)
        return _Ctx(resp=self._resp, exc=self._exc)


def _run(coro):
    return asyncio.run(coro)


def test_fetch_ok(monkeypatch):
    import trafilatura
    monkeypatch.setattr(fu, "_is_safe_url", lambda u: True)   # SSRF 검사는 별도 테스트
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: "본" * 300)  # ≥ _MIN_CHARS
    monkeypatch.setattr(trafilatura, "extract_metadata",
                        lambda *a, **k: type("M", (), {"title": "제목", "sitename": "네이버", "date": "2026-07-20"})())
    art = _run(fu._fetch_one("http://n.news/x", _Client(_Resp(200, "<html>..</html>"))))
    assert art.status == "ok"
    assert art.title == "제목" and art.site == "네이버"
    assert len(art.content) >= fu._MIN_CHARS


def test_fetch_paywall_short_body(monkeypatch):
    import trafilatura
    monkeypatch.setattr(fu, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: "로그인이 필요합니다")  # 짧음
    art = _run(fu._fetch_one("http://paywall/x", _Client(_Resp(200, "<html>..</html>"))))
    assert art.status == "blocked" and art.reason == "paywall_or_empty"


def test_fetch_http_error(monkeypatch):
    monkeypatch.setattr(fu, "_is_safe_url", lambda u: True)
    art = _run(fu._fetch_one("http://x/404", _Client(_Resp(404, "nope"))))
    assert art.status == "blocked" and art.reason == "http_404"


def test_fetch_network_exception(monkeypatch):
    monkeypatch.setattr(fu, "_is_safe_url", lambda u: True)
    art = _run(fu._fetch_one("http://x/boom", _Client(exc=RuntimeError("dns"))))
    assert art.status == "error" and art.reason.startswith("fetch_failed")


def test_ssrf_blocks_localhost_and_metadata():
    # 실제 getaddrinfo — 내부/링크로컬은 차단되어야 (SSRF 방어)
    assert fu._is_safe_url("http://localhost:8801/internal") is False
    assert fu._is_safe_url("http://127.0.0.1/") is False
    assert fu._is_safe_url("http://169.254.169.254/latest/meta-data/") is False
    assert fu._is_safe_url("http://10.0.0.5/") is False
    assert fu._is_safe_url("ftp://example.com/x") is False          # http(s)만
    assert fu._is_safe_url("http://[::1]/") is False                # IPv6 loopback


def test_ssrf_blocks_via_fetch_one():
    art = _run(fu._fetch_one("http://127.0.0.1:8801/v1/answer", _Client(_Resp(200, "x"))))
    assert art.status == "blocked" and art.reason == "blocked_host"


def test_ssrf_blocks_redirect_to_internal(monkeypatch):
    # 최초 호스트는 안전하지만 302 Location이 내부망 → 매 홉 재검사로 차단돼야 (redirect SSRF)
    monkeypatch.setattr(fu, "_is_safe_url",
                        lambda u: "127.0.0.1" not in u and "internal" not in u)
    redir = _Resp(302, "", headers={"location": "http://127.0.0.1/secret"})
    art = _run(fu._fetch_one("http://public.example/ok", _Client(redir)))
    assert art.status == "blocked" and art.reason == "blocked_host"


def test_non_html_content_type_blocked(monkeypatch):
    monkeypatch.setattr(fu, "_is_safe_url", lambda u: True)
    resp = _Resp(200, "%PDF-1.4 ...", headers={"content-type": "application/pdf"})
    art = _run(fu._fetch_one("http://x/doc.pdf", _Client(resp)))
    assert art.status == "blocked" and art.reason == "not_html_or_too_large"


def test_streaming_size_cap(monkeypatch):
    # content-length 미표기여도 스트리밍 중 실제 크기로 중단 (메모리 폭주 방지)
    monkeypatch.setattr(fu, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(fu, "_MAX_BYTES", 10)
    resp = _Resp(200, "x" * 50, headers={"content-type": "text/html"})  # 50B > 10B cap
    art = _run(fu._fetch_one("http://x/big", _Client(resp)))
    assert art.status == "blocked" and art.reason == "not_html_or_too_large"
