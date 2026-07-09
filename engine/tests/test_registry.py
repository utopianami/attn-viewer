"""도구 레지스트리 (LLM 불필요 — CI 상시 실행 가능)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.registry import STAGE_ALLOWLIST, build_default_registry  # noqa: E402


def test_deterministic_tools_registered():
    reg = build_default_registry()
    for name in ("finance_math", "price_yahoo", "macro_yahoo", "toss_feed", "toss_company"):
        spec = reg.get(name)
        assert spec is not None and spec.kind == "deterministic"
        assert spec.fn is not None  # 결정적 도구는 호출 진입점이 있어야


def test_search_tools_env_gated(monkeypatch):
    reg = build_default_registry()
    # 2026-07-09 개편: ra_x = 네이버(키 게이팅) + 구글뉴스RSS(무키·상시)
    from app.settings import settings
    monkeypatch.setenv("NAVER_CLIENT_ID", "i")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "s")
    assert [s.name for s in reg.allowed("ra_x")] == ["naver_news", "gnews_rss"]
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(settings, "naver_client_id", "", raising=False)
    monkeypatch.setattr(settings, "naver_client_secret", "", raising=False)
    assert [s.name for s in reg.allowed("ra_x")] == ["gnews_rss"]  # 무키 RSS는 상시


def test_blind_stages_have_no_tools():
    reg = build_default_registry()
    assert reg.allowed("planner") == []
    assert reg.allowed("da") == []
    assert STAGE_ALLOWLIST["da"] == []


def test_capabilities_map(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "i")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "s")
    reg = build_default_registry()
    caps = reg.capabilities()
    assert caps["finance_math"] is True   # env 불필요
    assert caps["naver_news"] is True
    assert caps["gnews_rss"] is True      # 무키 — 상시
