"""리포트 입력 메트릭 allowlist — 상수만(leaf 모듈, 순환 import 불가).
사이클/수요/공급/AI 수요 대표 시리즈. report_input·report_anchors가 공유."""

REPORT_METRICS = [
    "memory_price_usd_per_gb",   # 현물가 — 사이클 핵심
    "kr_semi_production_index",  # 생산·재고
    "kr_semi_export",            # 수출액 — 수요 선행
    "memory_capex",              # 3사 CAPEX — 공급 증설
    "equip_revenue",             # 장비사 매출 — 공급 선행
    "hyperscaler_capex",         # 전방 capex
    "ai_chip_revenue",           # AI칩 매출
    "tw_monthly_revenue",        # 대만 ODM/TSMC
    "token_price",               # 토큰 단가 — AI 수요
    "openrouter_daily_tokens",   # 토큰 사용량 — AI 수요
]
