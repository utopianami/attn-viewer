"""테제 canonical 시드 8종 — 2부 T1.

전부 실제 레지스트리 어휘만 사용한다(가짜 세계 금지, r2-B6):
entities ⊆ sector.entities.ENTITY_PATTERNS canon, metrics ⊆ sector.metrics_registry.METRIC_REGISTRY,
event_types ⊆ sector.contracts.EventType, axis ⊆ sector.contracts.Axis,
segments ⊆ SectorCard.memory_segment 값 공간.

여기 항목은 dict로만 유지한다(런타임 검증은 thesis_contracts로 별도 수행) —
직렬화·저장 포맷과 pydantic 계약을 분리하기 위함.

meta_filter 그룹 고정 (2부 T9 블로커 2 — 2026-07-23 실 스토어
storage/rag/memory_sector/metrics/*.jsonl 조사 기반, 작업 리포트에 인벤토리 전문):
memory_price_usd_per_gb의 `category`(HBM/DRAM/NAND)는 이종 단위(USD/GB·USD billion·
% of component cost 등)를 가진 최대 10개 `item` 서브시리즈를 한데 묶어 그룹 가드가
전부 drop시킨다 — 그래서 `category` 대신 `item`으로 정확히 1개 서브시리즈를 고정한다
(`metrics_registry._GROUP_KEYS` 우선순위상 "item"이 "category"보다 앞선 그룹 키).
memory_capex·hyperscaler_capex·ai_chip_revenue도 동일 이유로 회사별 `item`(=`token`,
티커) 고정 — 컬렉터가 넣는 집계 시리즈가 없어 시드가 언급하는 회사마다 개별 항목으로
나열한다. openrouter_daily_tokens·token_price는 `model`이 그룹 키(모델별 시계열만
존재, 합계 없음) — 헤드라인 모델 1개를 고정한다.
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
            # HBM $/GB가 헤드라인(1차) — Stanford DAM item 서브시리즈 실존 확인.
            # DRAM은 HBM 공급의 capacity 전환 동인이라 병행 추적.
            {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
             "meta_filter": {"item": "HBM|HBM $/GB"}},
            {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
             "meta_filter": {"item": "DRAM|DRAM cheapest (Keepa)"}},
            # memory_capex는 집계 시리즈가 없어 시드가 언급하는 3사 개별 항목으로.
            {"metric": "memory_capex", "max_age_days": 120,
             "meta_filter": {"item": "005930.KS"}},   # 삼성전자
            {"metric": "memory_capex", "max_age_days": 120,
             "meta_filter": {"item": "000660.KS"}},   # SK하이닉스
            {"metric": "memory_capex", "max_age_days": 120,
             "meta_filter": {"item": "MU"}},           # 마이크론
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
            # 집계 시리즈 없음 — 시드가 언급하는 4개 하이퍼스케일러 개별 항목.
            {"metric": "hyperscaler_capex", "max_age_days": 120,
             "meta_filter": {"item": "MSFT"}},
            {"metric": "hyperscaler_capex", "max_age_days": 120,
             "meta_filter": {"item": "GOOGL"}},
            {"metric": "hyperscaler_capex", "max_age_days": 120,
             "meta_filter": {"item": "AMZN"}},
            {"metric": "hyperscaler_capex", "max_age_days": 120,
             "meta_filter": {"item": "META"}},
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
            # entities에 명시된 NVIDIA 헤드라인만(AMD·AVGO는 이 시드가 언급 안 함).
            {"metric": "ai_chip_revenue", "max_age_days": 120,
             "meta_filter": {"item": "NVDA"}},
            # openrouter_daily_tokens는 모델별 시계열만 존재(합계 없음) — 헤드라인
            # 고정 모델 사용(가장 최근 갱신되는 OpenAI 플래그십 모델 slug).
            {"metric": "openrouter_daily_tokens", "max_age_days": 14,
             "meta_filter": {"model": "openai/gpt-5.5-20260423"}},
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
            {"metric": "openrouter_daily_tokens", "max_age_days": 14,
             "meta_filter": {"model": "openai/gpt-5.5-20260423"}},
            # token_price는 openrouter_daily_tokens와 model slug 표기가 다르다
            # (버전 날짜 접미사 없음) — 카탈로그 실존 확인된 값으로 별도 고정.
            {"metric": "token_price", "max_age_days": 30,
             "meta_filter": {"model": "openai/gpt-5.5"}},
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
             "meta_filter": {"item": "DRAM|DRAM cheapest (Keepa)"}},
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
            {"metric": "memory_capex", "max_age_days": 120,
             "meta_filter": {"item": "005930.KS"}},   # 삼성전자
            {"metric": "memory_capex", "max_age_days": 120,
             "meta_filter": {"item": "000660.KS"}},   # SK하이닉스
            {"metric": "memory_capex", "max_age_days": 120,
             "meta_filter": {"item": "MU"}},           # 마이크론
            # 재고지수 — 공급 과잉이 가장 먼저 드러나는 서브시리즈(생산·출하 아님).
            {"metric": "kr_semi_production_index", "max_age_days": 45,
             "meta_filter": {"item": "생산자제품 재고지수(계절조정)"}},
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
            # 관세청 순별 누계 중 "01~20"(월중 가장 최근 갱신되는 구간)을 고정.
            {"metric": "kr_semi_export", "max_age_days": 20,
             "meta_filter": {"item": "01~20"}},
            {"metric": "memory_price_usd_per_gb", "max_age_days": 45,
             "meta_filter": {"item": "DRAM|DRAM cheapest (Keepa)"}},
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
             "meta_filter": {"item": "NAND|NAND cheapest (Keepa)"}},
        ],
    },
]
