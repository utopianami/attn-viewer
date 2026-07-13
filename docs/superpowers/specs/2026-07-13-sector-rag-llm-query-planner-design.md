# 섹터 RAG — LLM 쿼리 플래너 설계

작성일: 2026-07-13
승인: ryze_yn (채팅 브레인스토밍 세션)

## 목적

채팅에서 사용자가 질문하면 메모리 섹터 DB(이벤트 카드 508건+, 지표 시계열 18종)를
RAG처럼 검색해 답변 재료로 쓴다. 현재는 질문 내용을 보지 않고 "최근 14일 중요도 순
12장"을 꺼내는 수준이라, 질문에 맞는 카드·지표를 골라오도록 검색을 고도화한다.

## 현황과 갭

현재 (`engine/sector/retrieve.py` + `orchestrator.py` sector_rag 레이어):

- 트리거: 회사명(`entities.py`) 또는 토픽 키워드("메모리", "D램" 등) 감지 시 발동
- 검색: 최근 14일 고정, magnitude 내림차순 + pos/neg 각 2건 균형, k=12
- 지표: D램 현물가 1종만 typed_fact 승격, 사이클 판정 텍스트 주입 (63923ca)

갭 3가지:

1. **관련성 무시** — "HBM 공급 어때?"와 "낸드 가격 어때?"가 같은 카드 셋을 받음.
   카드의 `memory_segment`/`event_type`/텍스트를 검색에 안 씀.
2. **14일 고정 창** — "6월에 무슨 일 있었어?" 커버 불가.
3. **지표 라우팅 없음** — "한국 수출 어때?"에 `kr_semi_export`가 있는데 답변이 못 씀.

## 방식 결정 경위

- 규칙 기반(키워드 사전) vs LLM 쿼리 플래너 vs 임베딩 검토.
- 임베딩은 508건 규모에 과잉 (memory-rag-plan_codex.md: "수천 건 넘으면" 도입).
- 규칙 기반은 우회 표현("빅테크가 돈 계속 쓰고 있어?" → capex)과 확장 키워드 생성이
  불가능. 검색 정확도는 이 기능의 품질 핵심이므로 품질 우선 원칙(ryze_yn)에 따라
  **LLM 플래너를 기본 경로**로, 규칙 경로는 폴백 겸 대조군으로 둔다.
- LLM 플랜과 규칙 플랜을 둘 다 로그에 남겨 LLM의 실제 기여를 사후 측정 가능하게 한다.

## 설계

### 1. 게이트 (기존 유지 — 키워드)

"이 질문이 섹터 관련인가"만 기존 방식(엔티티/토픽 키워드)으로 판단.
무관 질문은 LLM 호출 없이 통과 → 비섹터 질문 비용·지연 0 유지.
섹터별 토픽 키워드 셋으로 구조화해 향후 타 섹터 추가 시 게이트만 등록하면 되게 한다.

### 2. LLM 쿼리 플래너 (신규 — `engine/sector/queryplan.py`)

경량 모델(sonnet, `light_models` 경로)에 질문 + 메뉴를 주고 구조화 출력으로 검색
계획을 받는다. providers.py의 `response_format` 구조화 출력 사용.

```yaml
SectorQueryPlan:
  sector: "memory"                  # 확장 대비 차원 — 지금은 고정
  segments: [hbm | dram | nand]     # 빈 목록 = 세그먼트 무관
  entities: [SAMSUNG, ...]          # entities.py 표준명
  metrics: [kr_semi_export, ...]    # METRIC_REGISTRY 키만 허용
  event_types: [earnings, ...]      # 빈 목록 = 무관
  days: 14                          # 기본 14, 최대 90 클램프
  keywords: ["점유율", "인증", ...]  # 카드 텍스트 대조용 확장 키워드 (최대 8개)
```

메뉴 = METRIC_REGISTRY의 지표 18종(이름+한글 설명) + 세그먼트/이벤트 타입 enum +
회사 표준명 목록. 프롬프트에 그대로 나열한다.

검증: pydantic으로 스키마 검증, `metrics`는 레지스트리에 없는 키 제거,
`days`는 [7, 90] 클램프. 검증 실패 = 폴백.

### 3. METRIC_REGISTRY (신규 — 단일 소스)

```python
# {metric_name: {"label": 한글 라벨, "desc": 플래너 메뉴용 설명, "keywords": 규칙 폴백용}}
```

플래너 메뉴, 규칙 폴백 매칭, 지표 요약 라벨이 전부 이 레지스트리 하나를 쓴다.
새 지표는 수집기 추가 시점에 여기 한 줄 등록 (18종 전수 등록으로 시작).

### 4. 검색 실행 (`retrieve.py` 확장)

플랜 기반 카드 스코어링으로 교체:

```text
score = w_seg·(memory_segment ∈ plan.segments or mixed)
      + w_ent·(entities 교집합)
      + w_kw·(keywords가 title+interpreted_signal에 등장하는 비율)
      + w_et·(event_type ∈ plan.event_types)
      + w_mag·magnitude + w_rec·최신성 + w_grade·출처등급(S>A>B>C>D)
```

- 기존 pos/neg 각 min(2, 보유수) 균형 보장 유지
- plan.days로 검색 창 결정 (기본 14일)
- 가중치는 상수로 시작 — 튜닝은 로그 데이터 쌓인 뒤

### 5. 지표 라우팅

plan.metrics에 선택된 지표마다 최신 관측치 요약을 텍스트 블록으로 합성 컨텍스트에
주입 (cycle_context와 같은 방식):

```text
[섹터 지표] 한국 반도체 수출: 2026-06 xx.x억달러 (MoM +x.x%, YoY +x.x%) — 출처 관세청
```

typed_fact 승격은 기존 안전 원칙 유지 — 시리즈 규칙이 확정된 D램 현물가만.
라벨 불명 시계열은 텍스트로만 (63923ca 원칙 그대로).

### 6. 폴백 + 대조 로그

- 플래너 타임아웃(5초)·오류·검증 실패 시 규칙 경로로 강등:
  기존 `extract_entities` + 토픽 키워드 + METRIC_REGISTRY keywords 매칭.
- 정상 경로에서도 규칙 플랜을 같이 계산해 `sector_rag` 레이어 출력에
  `{plan, rule_plan, planner_ms, fallback}` 필드로 기록 — LLM 기여 사후 측정용.
- never-raise: 섹터 레이어 실패가 답변 파이프라인을 죽이지 않는다 (기존 원칙).

### 7. 섹터 차원 (확장 대비 — 필터)

지금은 메모리 섹터 DB뿐이지만 타 섹터 추가에 대비해 하드코딩을 피한다:

- `SectorStore` 루트 경로를 섹터 id로 매개변수화 (현재 `memory_sector` 고정)
- `SectorQueryPlan.sector` 필드 (현재 "memory" 고정)
- 게이트의 토픽 키워드를 섹터별 셋으로 구조화

멀티섹터 실구현(타 섹터 수집기·판정)은 비범위 — 구조만 열어둔다.

## 에러 처리

| 상황 | 동작 |
| --- | --- |
| 플래너 타임아웃/오류 | 규칙 플랜으로 강등, `fallback: true` 기록 |
| 플랜 검증 실패 (미지 지표 등) | 해당 필드 정제 후 진행, 전부 무효면 폴백 |
| 지표 파일 없음/빈 시계열 | 해당 지표 요약만 생략 (never-raise) |
| 카드 0건 | 기존 무필터 폴백 유지 |

## 테스트

두 층 (test-with-real-upstream-outputs 원칙):

1. **수제 입력 + 모킹 플래너** — 결정적: 스코어링(세그먼트 부스트, 균형 보장,
   days 클램프), 지표 라우팅, 폴백 강등, 레지스트리 검증.
2. **실제 상류 출력** — 실제 `index.jsonl` 카드로 검색 결과 검증 + 실제 LLM 플래너
   출력 샘플(고정 질문 셋) 스키마 검증. live 테스트는 기존 `*_live.py` 패턴.

## 완성 기준 (배포 후 채팅 확인)

1. "HBM 공급 어때?" → 근거 카드가 HBM 세그먼트 위주
2. "한국 반도체 수출 어때?" → 답변에 실제 수출 수치 인용
3. "6월에 메모리 쪽 무슨 일 있었어?" → 6월 카드 검색됨
4. 비섹터 질문 → 플래너 미호출 (로그로 확인)

## 비범위 (YAGNI)

- 임베딩 검색 (카드 수천 건 도달 시 재검토)
- 멀티섹터 실구현 (구조만 개방)
- 채팅 UI 근거 필터
- 스코어 가중치 자동 튜닝
