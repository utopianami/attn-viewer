"""엔진 설정 — 루트 .env 단일 진실원.

주의: MAF AnthropicClient는 기본으로 ANTHROPIC_API_KEY를 찾음 →
여기서 CLAUDE_API_KEY를 읽어 명시 전달한다 (계획 확정 제약).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # 키 (.env 이름 그대로 — 2026-07-02 등록 확인)
    claude_api_key: str = ""
    openai_api_key: str = ""
    brave_api_key: str = ""
    tavily_api_key: str = ""

    # 모델 (2026-07-06 실물 확정 — /v1/models 목록 대조 + adaptive thinking 스모크)
    # 비용 절감: fable-5($10/$50) → opus-4.8($5/$25). grok은 제거 (검색 품질 대비 비쌈).
    model_claude: str = "claude-opus-4-8"
    model_claude_sonnet: str = "claude-sonnet-4-6"  # 뉴스 요약 등 경량 역할 ($3/$15, 2026-07-06 검증)
    model_gpt: str = "gpt-5.5"          # 플래그십 (5.5-mini는 없음)
    model_gpt_mini: str = "gpt-5.4-mini"  # 경량 (gpt-5.5-mini 미존재 → 5.4-mini)

    # 서버
    engine_port: int = 8801
    heartbeat_interval_s: float = 12.0

    # 수집 예산
    trend_news_cap: int = 30
    unit_cap: int = 6

    def capabilities(self) -> dict[str, bool]:
        return {
            "anthropic": bool(self.claude_api_key),
            "openai": bool(self.openai_api_key),
            "brave": bool(self.brave_api_key),
            "tavily": bool(self.tavily_api_key),
        }


settings = Settings()
