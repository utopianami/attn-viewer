"""테제 canonical 시드 8종 — 2부 T1.

전부 실제 레지스트리 어휘만 사용한다(가짜 세계 금지, r2-B6):
entities ⊆ sector.entities.ENTITY_PATTERNS canon, metrics ⊆ sector.metrics_registry.METRIC_REGISTRY,
event_types ⊆ sector.contracts.EventType, axis ⊆ sector.contracts.Axis,
segments ⊆ SectorCard.memory_segment 값 공간.

여기 항목은 dict로만 유지한다(런타임 검증은 thesis_contracts로 별도 수행) —
직렬화·저장 포맷과 pydantic 계약을 분리하기 위함.
"""
from __future__ import annotations

SEED_THESES: list[dict] = [
    {
        "id": "hbm-tightness",
        "claim": "HBM 공급은 패키징·수율 병목으로 구조적으로 타이트하다.",
        "axis": "A",
        "priority": 1,
        "selectors": {
            "entities": ["SK_HYNIX", "SAMSUNG", "MICRON", "NVIDIA"],
            "metrics": ["memory_price_usd_per_gb", "memory_capex"],
            "segments": ["hbm"],
            "event_types": ["supply_signal", "demand_signal"],
        },
        "required_inputs": [
            # HBM 가격 시리즈가 1차 입력 (stanford_dam이 CSV category를 동적 태깅 —
            # 스토어에 HBM 관측 실존). DRAM은 HBM 공급의 capacity 전환 동인이라 병행 추적.
            {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
             "meta_filter": {"category": "HBM"}},
            {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
             "meta_filter": {"category": "DRAM"}},
            {"metric": "memory_capex", "max_age_days": 120},
        ],
    },
    {
        "id": "hyperscaler-capex-phase",
        "claim": "하이퍼스케일러 CAPEX는 여전히 확장 국면에 있다.",
        "axis": "B",
        "priority": 1,
        "selectors": {
            "entities": ["MICROSOFT", "GOOGLE", "AMAZON", "META"],
            "metrics": ["hyperscaler_capex", "earnings_calendar"],
            "segments": ["mixed"],
            "event_types": ["earnings", "demand_signal"],
        },
        "required_inputs": [
            {"metric": "hyperscaler_capex", "max_age_days": 120},
        ],
    },
    {
        "id": "frontier-train-to-inference",
        "claim": "AI 프론티어 워크로드의 무게중심이 훈련에서 추론으로 이동하고 있다.",
        "axis": "C",
        "priority": 2,
        "selectors": {
            "entities": ["OPENAI", "ANTHROPIC", "NVIDIA", "MICROSOFT"],
            "metrics": ["ai_chip_revenue", "openrouter_daily_tokens", "token_price"],
            "segments": ["mixed"],
            "event_types": ["product_policy", "demand_signal"],
        },
        "required_inputs": [
            {"metric": "ai_chip_revenue", "max_age_days": 120},
            {"metric": "openrouter_daily_tokens", "max_age_days": 14},
        ],
    },
    {
        "id": "token-demand-growth",
        "claim": "토큰 사용량의 구조적 성장이 AI 인프라 수요를 계속 견인한다.",
        "axis": "C0",
        "priority": 2,
        "selectors": {
            "entities": ["OPENAI", "MICROSOFT", "GOOGLE"],
            "metrics": ["openrouter_daily_tokens", "token_price"],
            "segments": ["mixed"],
            "event_types": ["demand_signal", "product_policy"],
        },
        "required_inputs": [
            {"metric": "openrouter_daily_tokens", "max_age_days": 14},
            {"metric": "token_price", "max_age_days": 30},
        ],
    },
    {
        "id": "memory-price-cycle",
        "claim": "DRAM 현물가는 상승 사이클에 진입했다.",
        "axis": "A",
        "priority": 1,
        "selectors": {
            "entities": ["SAMSUNG", "SK_HYNIX", "MICRON"],
            "metrics": ["memory_price_usd_per_gb", "memory_capex"],
            "segments": ["dram"],
            "event_types": ["price_signal", "supply_signal"],
        },
        "required_inputs": [
            {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
             "meta_filter": {"category": "DRAM"}},
        ],
    },
    {
        "id": "supply-overbuild-risk",
        "claim": "메모리 3사의 공격적 증설이 향후 공급 과잉 리스크로 번질 조짐이다.",
        "axis": "A",
        "priority": 2,
        "selectors": {
            "entities": ["SAMSUNG", "SK_HYNIX", "MICRON", "CXMT"],
            "metrics": ["memory_capex", "kr_semi_production_index"],
            "segments": ["mixed"],
            "event_types": ["supply_signal", "filing"],
        },
        "required_inputs": [
            {"metric": "memory_capex", "max_age_days": 120},
            {"metric": "kr_semi_production_index", "max_age_days": 45},
        ],
    },
    {
        "id": "china-competition-risk",
        "claim": "CXMT를 위시한 중국 메모리 자국화가 가격·점유율에 지정학 리스크로 작용한다.",
        "axis": "P",
        "priority": 2,
        "selectors": {
            "entities": ["CXMT", "SAMSUNG", "SK_HYNIX"],
            "metrics": ["kr_semi_export", "kr_semi_export_share", "memory_price_usd_per_gb"],
            "segments": ["dram"],
            "event_types": ["policy", "supply_signal"],
        },
        "required_inputs": [
            {"metric": "kr_semi_export", "max_age_days": 20},
            {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
             "meta_filter": {"category": "DRAM"}},
        ],
    },
    {
        "id": "nand-decoupling",
        "claim": "NAND는 DRAM·HBM 사이클과 분리되어 독자적인 수급 흐름을 보인다.",
        "axis": "A",
        "priority": 3,
        "selectors": {
            "entities": ["SAMSUNG", "SK_HYNIX", "KIOXIA", "MICRON"],
            "metrics": ["memory_price_usd_per_gb"],
            "segments": ["nand"],
            "event_types": ["price_signal", "supply_signal"],
        },
        "required_inputs": [
            {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
             "meta_filter": {"category": "NAND"}},
        ],
    },
]
