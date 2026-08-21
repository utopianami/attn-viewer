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

    # ---- 메모리 섹터 P1 (2026-07-06) — 키는 루트 .env, 없으면 해당 수집기 missing_key로 skip ----
    openrouter_api_key: str = ""      # openrouter.ai 무료 키 (datasets 랭킹용; /models는 키 불필요)
    data_go_kr_api_key: str = ""      # data.go.kr 공공데이터포털 (관세청 수출)
    kosis_api_key: str = ""           # kosis.kr (생산·출하·재고지수)
    ecos_api_key: str = ""            # ecos.bok.or.kr (D램 수출물가지수)
    dart_api_key: str = ""            # opendart.fss.or.kr (한국 공시)
    naver_client_id: str = ""         # developers.naver.com 데이터랩
    naver_client_secret: str = ""
    # 검색 API 전용 앱 (데이터랩 앱에는 "검색" 스코프 추가 불가 — 별도 신청, 2026-07-09)
    naver_search_client_id: str = ""
    naver_search_client_secret: str = ""
    # 토스증권 공식 Open API(OAuth client credentials). 없으면 공식 도구만 비활성,
    # WTS 공개 read-only 폴백과 Yahoo는 계속 동작한다.
    toss_client_id: str = ""
    toss_client_secret: str = ""
    # 공개 WTS 게스트 세션이 필요한 일부 대시보드 조회용. 허용 헤더:
    # browser-tab-id, app-version, x-xsrf-token (쿠키·Authorization 금지).
    toss_wts_guest_headers_json: str = ""
    sector_scheduler_enabled: bool = False        # 원칙 10 — 기본 OFF
    sector_collect_interval_s: int = 43200        # 하루 2회
    sector_storage_dir: str = ""                  # 비면 REPO_ROOT/storage/rag/memory_sector

    # 시황 리포트 스케줄러 (Phase 3) — 기본 OFF, .env REPORT_SCHEDULER_ENABLED로 활성화
    report_scheduler_enabled: bool = False
    report_times_kst: str = "04:39,16:39"         # 수집(43200s 주기) 직후 창을 노린 시각
    # v2 3축 카드(2026-07-24 재설계) — "axes"(기본) | "legacy"(주장·완결 글, 롤백용)
    report_format: str = "axes"

    # 테제(Thesis) 갱신 훅 (2부 T6) — collect_all 직후 자동 실행, 기본 ON
    thesis_update_enabled: bool = True

    # 3부 답변 경로 주입 전체 off (4부 2-arm 승계용, 3부 T2). run override가 우선하며
    # thesis_update_enabled(수집측 갱신 훅)와는 별개 — 이건 답변 경로 소비측 게이트.
    disable_p23: bool = False

    # 데이터 파이프라인 모니터 (engine/monitor/) — 기본 OFF, .env MONITOR_ENABLED로 활성화
    monitor_enabled: bool = False
    monitor_interval_s: int = 1800                # 30분 주기 점검
    monitor_cooldown_s: int = 21600               # 같은 알림 재발송 억제 6h
    telegram_bot_token: str = ""                  # ward 텔레그램 봇 — 비면 파일 기록만
    telegram_chat_id: str = ""

    # A/B 실험 플래그
    reaudit_mode: str = "off"       # "on" → A1 역할 재제시 재감사 활성 (arXiv 2606.05976)
    refute_mode: str = "off"        # "on" → A2 반증 자세 검증 활성 (동의 편향 완화, TNR<25% 대응)

    # 수집 예산
    trend_news_cap: int = 30
    unit_cap: int = 6

    def capabilities(self) -> dict[str, bool]:
        return {
            "anthropic": bool(self.claude_api_key),
            "openai": bool(self.openai_api_key),
        }


settings = Settings()
