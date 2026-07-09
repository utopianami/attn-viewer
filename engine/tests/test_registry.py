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
    monkeypatch.setenv("BRAVE_API_KEY", "b")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    # env_ok는 os.environ + settings 이중 확인 (2026-07-09) — 게이팅 검증은 둘 다 비워야
    from app.settings import settings
    monkeypatch.setattr(settings, "tavily_api_key", "", raising=False)
    # ra_x allowlist = [brave_news, tavily] — 키 충족한 것만
    allowed = [s.name for s in reg.allowed("ra_x")]
    assert allowed == ["brave_news"], allowed


def test_blind_stages_have_no_tools():
    reg = build_default_registry()
    assert reg.allowed("planner") == []
    assert reg.allowed("da") == []
    assert STAGE_ALLOWLIST["da"] == []


def test_capabilities_map(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "b")
    reg = build_default_registry()
    caps = reg.capabilities()
    assert caps["finance_math"] is True   # env 불필요
    assert caps["brave_news"] is True
