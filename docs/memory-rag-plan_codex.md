# Memory Sector RAG Plan - Codex

작성일: 2026-07-06

## 목적

메모리 섹터에 집중하는 전용 RAG를 만든다. 목표는 LLM이 "삼성전자, SK하이닉스, Micron 같은 메모리 생산 업체의 주가와 실적에 어떤 뉴스가 실제로 중요한가"를 더 잘 답하게 만드는 것이다.

핵심은 단순 뉴스 검색이 아니라, 원천 데이터를 아래 논리 구조로 정리하는 것이다.

```text
AI 사용량/매출/제품 모멘텀
  -> 하이퍼스케일러 CAPEX/서버 구매/클라우드 수요
  -> GPU/ASIC/TPU 출하와 고대역폭 메모리 수요
  -> HBM, DRAM, NAND 가격/재고/공급계약
  -> 메모리 업체 실적, 가이던스, 주가 반응
```

## 기본 세계관

사용자의 3축은 유지한다.

- A. 메모리 공급/생산 축: Samsung Electronics, SK hynix, Micron
- B. 메모리 소비/인프라 축: Amazon, Microsoft, Alphabet/Google, Meta, Apple, Oracle, CoreWeave 등
- C. AI 프론티어 수요 축: OpenAI, Anthropic, Google DeepMind, xAI, Meta AI 등

단, TSMC는 A에 그대로 넣기보다 `AI 반도체 공급망/패키징 축`으로 별도 분류하는 것이 더 정확하다. TSMC는 메모리 업체가 아니지만, Nvidia/AMD/Google TPU/Apple silicon의 선단 공정과 CoWoS/advanced packaging 병목을 통해 HBM 수요에 강한 선행 신호를 준다.

## RAG가 답해야 하는 질문

1. 이 뉴스는 메모리 수요에 긍정인가, 부정인가?
2. 영향 경로는 HBM인가, 범용 DRAM인가, NAND인가?
3. 단기 주가 재료인가, 2~4분기 뒤 실적 재료인가?
4. 삼성전자, SK하이닉스, Micron 중 누구에게 더 유리한가?
5. 원문 근거는 무엇이며, LLM이 해석한 부분과 원문 사실은 어떻게 구분되는가?

## Claude 교차검토 반영 - 확정 방향

Claude 초안의 좋은 점은 RAG를 문서 검색으로 시작하지 않고, `이벤트 카드 + 정량 지표 시계열`의 2레이어로 나눈 것이다. Codex 쪽 계획도 이 방향으로 업데이트한다.

### 1. 데이터는 7종류로 분리한다

뉴스/지표/스피커만으로는 부족하다. 실제 저장 타입은 아래 7개로 둔다.

| 타입 | 역할 | 예시 |
| --- | --- | --- |
| 지표 | 숫자와 시계열 | 토큰 사용량, DRAM spot, CAPEX, 서버 출하 |
| 뉴스 | 사건과 내러티브 | Meta excess compute, Apple memory cost complaint |
| 스피커 | 누가 어떤 톤으로 말했는지 | CFO 컨콜, Jensen Huang, Sam Altman, Lisa Su |
| 공시/원문 문서 | 뉴스보다 강한 1차 근거 | DART, SEC EDGAR, earnings release, 10-K/10-Q |
| 가격표/제품 정책 | AI 토큰 경제의 단가 변화 | OpenAI/Claude/Gemini pricing, rate limits, cache pricing |
| 공급망/운영 데이터 | A/B/C를 잇는 중간 병목 | TSMC CoWoS, 대만 ODM 월매출, 장비 수주 |
| 시장 반응 | 사건이 실제 가격에 반영됐는지 | SK하이닉스/삼성/MU/NVDA/SOX 1D/3D/5D 반응 |

### 2. 레이어 1 - 이벤트 카드

뉴스, 발언, 공시, 계약, 정책 변화는 먼저 이벤트 카드로 정규화한다. LLM이 raw RAG에 보여줄 기본 단위도 이벤트 카드다.

```yaml
MemoryEventCard:
  id: string
  ts: string
  axis: A | A_prime | B | C | D | market
  entities: string[]
  edge: A_to_A | A_prime_to_A | B_to_A | C_to_A | D_to_A | market_to_A
  event_type: demand_signal | supply_signal | price_signal | earnings | filing | policy | speaker | product_policy | market_reaction
  direction: positive | neutral | negative | mixed
  magnitude: 1 | 2 | 3
  title: string
  summary: string
  source: string
  source_url: string
  source_grade: S | A | B | C | D
  speaker: string | null
  raw_excerpt: string
  affected_companies: string[]
  memory_tags: hbm | dram | nand | ssd | capex | gpu | tpu | token | pricing | supply_chain
```

판정 규칙:

- 인과 엣지에 매핑되지 않는 데이터는 버린다.
- `direction`은 A축 메모리 업체 주가/실적 관점이다.
- `magnitude=3`은 가이던스, 계약, 실적, 공시처럼 확인 강도가 높은 이벤트다.
- 스피커 발언은 뉴스로 묻지 말고 `speaker` 필드를 채운다.

### 3. 레이어 2 - 정량 지표 시계열

뉴스만 모으면 나이브해진다. 아래 시계열을 같은 날짜축에 저장하고, 이벤트 마커와 겹쳐 봐야 한다.

| 지표 | 축 | 수집처 | 주기 | 해석 |
| --- | --- | --- | --- | --- |
| OpenRouter 모델별 token usage | C | OpenRouter datasets API | 일별 | 전세계 총량이 아니라 OpenRouter 표본. 성장률/모델 믹스 proxy로 사용 |
| OpenRouter app token ranking | C | OpenRouter app rankings API | 일별 | 수요가 coding/chat/agent 중 어디서 오는지 |
| 모델별 token price snapshot | C | OpenRouter models/pricing + OpenAI/Anthropic/Gemini pricing | 일별 | input/output/cache 가격 변화 |
| Big Lab 공식 사용량 수치 | C | OpenAI/Anthropic/Google 공식 발표 | 비정기 | WAU, paid users, API usage, revenue run-rate |
| DRAM/NAND spot | D | TrendForce DataTrack | 일별/주간 | 가격 방향성. 유료/스크랩 리스크 명시 |
| Server shipment / AI server mix | D/B | TrendForce, IDC/Omdia | 분기/월간 | 실제 서버 수요 검증 |
| Hyperscaler CAPEX actual | B | SEC filing, cash flow statement, IR | 분기 | 가이던스가 실제 지출로 이어졌는지 |
| 대만 서버 ODM 월매출 | B/D | TWSE/MOPS 월매출 공시 | 월간 | AI 서버 조립 수요의 빠른 proxy |
| TSMC 월매출 | A_prime | TWSE/MOPS, TSMC monthly revenue | 월간 | AI accelerator/CoWoS 수요 proxy |
| 한국 반도체 수출 10일/월간 | D | 관세청/산업통상자원부/무역협회 | 월 3회/월간 | 삼성/하이닉스 매출 선행 proxy |
| 메모리사 DIO | A | 재무제표 | 분기 | 재고 감소 여부 |
| 장비 발주/수주잔고 | D | ASML, AMAT, Lam, KLA 실적 | 분기 | 6~12개월 뒤 공급 증가 리스크 |
| 주가/SOX/peer reaction | market | Yahoo/KRX/Nasdaq | 일별 | 이벤트가 시장에 반영됐는지 |

저장 위치 초안:

```text
storage/rag/memory_sector/cards/YYYY-MM/*.json
storage/rag/memory_sector/index.jsonl
storage/rag/memory_sector/metrics/{metric_name}.jsonl
```

### 4. 조합 지표

단독 지표보다 아래 파생 지표가 더 중요하다.

```text
C token usage
  -> B CAPEX guidance/actual
  -> Taiwan ODM monthly revenue
  -> Korea semiconductor export
  -> A earnings/inventory
```

파생 지표:

- `Token Spend Direction` = token usage growth + effective token price change
- `Spot - Contract Spread` = DRAM/NAND 다음 계약가 압력
- `B 말 vs 돈` = capex guidance와 actual capex 괴리
- `주가 vs 사슬 괴리` = 수요 사슬은 강한데 A 주가가 빠지는지
- `HBM Tightness Index` = HBM 계약/인증/ASP/capacity/sold-out 발언 조합
- `Supply Overbuild Risk` = HBM 증설 + 장비 수주 + CAPEX 급증 조합

### 4-1. 유료 데이터 우선순위

유료 데이터는 무조건 많이 살 필요가 없다. RAG에 진짜 필요한 유료 데이터는 `공개 자료로는 숫자 시계열을 안정적으로 얻기 어려운 것`이다.

| 우선순위 | 유료 소스 | 사야 하는 데이터 | 이유 | 무료 대체 |
| --- | --- | --- | --- | --- |
| 1 | TrendForce DataTrack / DRAMeXchange | DRAM spot/contract price, NAND wafer/contract price, server DRAM price, enterprise SSD price | 메모리 사이클 판단의 핵심. 뉴스보다 가격 시계열이 중요 | 공개 TrendForce price page/press release는 일부만 가능 |
| 1 | TrendForce DataTrack | server shipment, AI server shipment/mix, DRAM/NAND capacity, supplier capex | B축 수요가 실제 서버 출하로 이어지는지 검증 | IDC/Omdia 기사 요약, ODM 월매출 proxy |
| 1 | Omdia DRAM/NAND Memory Trackers | HBM shipment, ASP, market share, capacity, production, DRAM/NAND supply-demand | HBM은 현물시장이 없어서 계약/출하/ASP 데이터 가치가 큼 | 회사 IR의 HBM 코멘트, TrendForce 보도자료 |
| 2 | Yole Group Memory / HBM monitors | HBM 장기 수요, 공급망, packaging, 기술 로드맵 | 중장기 thesis와 supply bottleneck 검증 | 회사 IR, TechInsights/TrendForce 무료 요약 |
| 2 | TechInsights Memory subscription | DRAM/NAND/HBM 기술, cost, die/package, node 전환, 로드맵 | 기술 변화가 원가/공급에 미치는 영향 분석 | 무료 webinar/기사, 회사 발표 |
| 2 | DigiTimes / 대만 전문지 | TSMC CoWoS, substrate, ODM, 공급망 월간 뉴스 | 대만 공급망에서 가장 빠른 현장 신호 | TWSE/MOPS 월매출, 회사 공시 |
| 3 | SemiAnalysis | AI infra, GPU cluster, hyperscaler capex quality, accelerator supply chain | B/C축과 GPU/HBM 연결 해석이 강함 | Big Tech IR, Nvidia/AMD/Broadcom/TSMC 실적 |
| 3 | Bloomberg / Reuters | 비상장 AI 회사 매출/사용량/계약 단독 기사 | OpenAI/Anthropic 같은 C축 데이터는 공식 공개가 적음 | 공식 블로그, OpenRouter proxy |

구매 판단:

- `TrendForce/Omdia`가 1순위다. 이유는 DRAM/NAND/HBM 가격·출하·capacity가 RAG의 검증 레이어이기 때문이다.
- `Yole/TechInsights`는 장기 thesis와 기술/공급망 분석용이다. 매일 전광판에는 덜 중요하지만, 분기 리포트에는 유용하다.
- `DigiTimes/SemiAnalysis/Bloomberg/Reuters`는 뉴스/해석 보강용이다. 숫자 시계열보다 우선순위는 낮다.

저장 원칙:

- 라이선스가 허용하면 시계열 값을 저장한다.
- 라이선스가 제한적이면 `direction`, `change_rate`, `period`, `source_meta`, `chart_link`만 저장한다.
- 유료 리포트 전문이나 표 전체를 raw RAG에 그대로 노출하지 않는다.
- raw RAG에는 짧은 근거, 출처명, 날짜, 라이선스-safe 요약만 표시한다.

### 4-2. TrendForce/Omdia 대체 후보

TrendForce/Omdia를 완전히 대체하기는 어렵다. 특히 HBM의 `ASP, shipment, vendor share, capacity`는 전문 tracker 없이는 정확한 시계열 확보가 어렵다. 다만 MVP와 전광판은 아래 대체 조합으로 충분히 시작할 수 있다.

| 후보 | 대체 범위 | 자동화/수집성 | 품질 평가 | 링크 |
| --- | --- | --- | --- | --- |
| SemiAnalysis Memory Model | DRAM/NAND supply-demand, fab floor to spot market, memory cycle | 계약 확인 필요 | 유료 대체 후보 중 가장 직접적 | https://semianalysis.com/memory-model/ |
| Stanford DAM Memory Prices | DRAM/HBM/NAND 장기 가격, CSV 다운로드 | CSV 다운로드 가능 | 공개 장기 시계열로 매우 유용. 단, 투자용 단기 tracker 대체는 아님 | https://dam.stanford.edu/memory-prices.html |
| Epoch AI AI Chip Components | AI chip designer별 HBM/CoWoS/logic consumption estimate | 데이터 다운로드 가능 | HBM 수요 proxy로 좋음. 공급사별 ASP/share 대체는 아님 | https://epoch.ai/data/ai-chip-components |
| Epoch AI HBM bandwidth/cost insights | AI chip memory bandwidth, HBM component cost share | 공개 데이터/차트 | C축 token/compute demand와 HBM 연결에 유용 | https://epoch.ai/data-insights/hbm-shipped |
| DRAMeXchange 공개 페이지 | DRAM/NAND spot 일부 | 웹 페이지/스크랩 가능성 | TrendForce 계열. 무료 범위는 제한적이지만 가격 방향성 확인 가능 | https://www.dramexchange.com/ |
| TrendForce 공개 price page | DRAM spot 일부 | 웹 페이지/스크랩 가능성 | 무료 범위의 가격 방향성 확인 | https://www.trendforce.com/price/dram/dram_spot |
| TWSE/MOPS 월매출 | Quanta, Wiwynn, Wistron, Inventec, Foxconn, TSMC 월매출 | 공식 공개 데이터 | AI server/TSMC 수요 proxy로 강함 | https://www.twse.com.tw/en/trading/statistics/index04.html |
| SEC EDGAR APIs | hyperscaler CAPEX actual, depreciation, PP&E, cash flow | 공식 API | B축 "말 vs 돈" 검증에 강함 | https://www.sec.gov/search-filings/edgar-application-programming-interfaces |
| 메모리/AI 공급망 기업 IR | SK hynix, Micron, Samsung, Nvidia, AMD, Broadcom, ASML, AMAT, Lam, KLA | 공식 IR 수집 | 원문 신뢰도 높음. 수급 숫자는 불완전 | 각사 IR |

대체 설계:

```text
HBM 정확 수치 대체:
  Omdia HBM Tracker 없음
  -> Epoch AI HBM consumption/cost
  -> SemiAnalysis Memory Model, 가능하면
  -> Nvidia/AMD/Broadcom/Google TPU revenue
  -> TSMC CoWoS/월매출
  -> SK hynix/Micron/Samsung HBM 발언
  -> HBM Tightness Index로 표시
```

```text
DRAM/NAND 가격 대체:
  TrendForce contract tracker 없음
  -> DRAMeXchange/TrendForce 공개 spot
  -> Stanford DAM 장기 가격
  -> 언론에 인용된 contract price 변화
  -> Amazon/retail/Keepa 기반 consumer DRAM/SSD 가격 proxy
  -> Spot/Proxy Direction으로 표시
```

```text
AI server shipment 대체:
  TrendForce server shipment 없음
  -> TWSE/MOPS ODM 월매출
  -> Nvidia data center revenue
  -> Supermicro/Dell/HPE AI server backlog
  -> Oracle/CoreWeave RPO/backlog
  -> Hyperscaler CAPEX actual
```

권장:

- 품질 높은 유료 대체를 찾는다면 `SemiAnalysis Memory Model`을 먼저 평가한다.
- 무료/공개 자동화로 시작하려면 `Stanford DAM + Epoch AI + TWSE/MOPS + SEC EDGAR + IR` 조합이 가장 실용적이다.
- 그래도 HBM ASP/vendor share/shipment 숫자가 필요하면 Omdia류 tracker가 필요하다.

### 4-3. 바로 자동화 가능한 지표 소스

뉴스는 기존 `save`/뉴스 수집 파이프라인으로 어느 정도 커버된다. 따라서 MVP에서 중요한 것은 뉴스로 바로 보이지 않는 지표를 자동 수집하는 것이다.

| 소스 | 자동화 | 핵심 지표 | 역할 |
| --- | --- | --- | --- |
| OpenRouter datasets | 가능 | 모델별 token usage, app token ranking | C축 AI 사용량 proxy |
| OpenRouter/OpenAI/Anthropic/Gemini pricing | 가능 | input/output/cache token price | token spend direction |
| Epoch AI | 가능 | AI chip HBM/CoWoS/logic consumption, HBM bandwidth proxy | C축 compute demand와 HBM 연결 |
| Stanford DAM | 가능 | DRAM/HBM/NAND 장기 가격 CSV | 장기 가격 proxy |
| TWSE/MOPS | 가능 | 대만 ODM/TSMC 월매출 | AI server/TSMC 수요 proxy |
| SEC EDGAR | 가능 | hyperscaler CAPEX actual, PP&E, depreciation, cash flow | B축 "말 vs 돈" 검증 |
| 한국 수출 데이터 | 가능 | 반도체/메모리 수출액, 10일/20일/월간, YoY/MoM | A축 삼성/하이닉스 매출 선행 proxy |
| 회사 IR/실적 PDF | 가능 | HBM sold-out, ASP, capex, inventory, customer qualification | A/B/C 원문 근거 |

자동화 불확실/보류:

| 소스 | 이유 |
| --- | --- |
| TrendForce/Omdia | 품질은 좋지만 API/CSV/SFTP/export 계약 가능 여부 확인 전까지 바로 자동화 후보로 보지 않는다. |
| SemiAnalysis | 구독은 가능해도 구조화 API/자동 다운로드 가능 여부가 불명확하다. |

### 4-4. 한국 반도체 수출 데이터

한국 수출 데이터는 메모리 섹터 전광판의 핵심 무료 지표다. 삼성전자와 SK하이닉스 실적보다 먼저 공개되는 매출 proxy로 쓸 수 있다.

봐야 할 지표:

| 지표 | 의미 |
| --- | --- |
| 반도체 수출액 | 전체 반도체 업황 |
| 메모리 반도체 수출액 | 삼성전자/SK하이닉스 직접 proxy |
| 일평균 수출액 | 조업일 왜곡 제거 |
| YoY / MoM | 업사이클/다운사이클 방향 |
| 10일/20일 수출 | 월간 지표보다 빠른 선행 신호 |
| 국가별 수출 | 중국/미국/대만/홍콩 수요 변화 |

소스 후보:

- 관세청 수출입 무역통계
- 산업통상자원부 월간 수출입 동향
- 한국무역협회 K-stat
- 공공데이터포털 API 또는 CSV

전광판 표현:

```text
Korea Memory Export
YoY: +xx%
MoM: +xx%
Daily Avg: +xx%
Signal: 회복 | 둔화 | 과열 | 데이터 부족
```

RAG에서의 역할:

```text
뉴스: AI 서버 수요 강함
지표: 메모리 수출 YoY 증가
판단: 수요 뉴스가 실제 매출 proxy로 확인됨
```

주의:

- 총 반도체 수출과 메모리 수출을 분리해야 한다.
- 가격 상승 효과와 물량 증가 효과를 구분하기 어렵다. 가능하면 수출액과 물량/단가 proxy를 같이 본다.
- 10일/20일 수출은 변동성이 크므로 3개월 이동평균이나 월간 확정치와 같이 본다.

### 5. 구조화 검색을 먼저 쓴다

초기에는 벡터 임베딩보다 구조화 검색이 낫다. 데이터가 하루 수십 건 수준이면 메타데이터 필터가 더 설명 가능하고 raw RAG 노출도 쉽다.

```text
질문
  -> 엔티티/축/메모리 태그 추출
  -> 최근 N일 필터, 기본 14일
  -> magnitude, source_grade, 최신성으로 랭킹
  -> 호재/악재/반대근거 균형 강제
  -> 상위 K개 카드 + 관련 metric window를 LLM 컨텍스트로 전달
```

카드가 수천 건을 넘고, 구조화 필터로 놓치는 질문이 많아질 때 임베딩을 추가한다.

### 6. 수집 파이프라인 초안

```text
스케줄러
  1. 뉴스/공시/RSS/IR 쿼리 실행
  2. 커뮤니티/중복 URL 제거
  3. LLM 판정: 관련성, axis, edge, event_type, direction, magnitude
  4. 상위 magnitude 카드만 본문 fetch로 raw_excerpt 보강
  5. 카드 저장
  6. 지표 수집: OpenRouter, TrendForce, Yahoo, TWSE/MOPS, 한국 수출
  7. 지표별 독립 실패 처리
```

P1에서는 데이터 수집이 하나 깨져도 전체 파이프라인이 멈추면 안 된다.

### 7. 역할 분담 제안

Claude 초안의 분업 제안은 합리적이다.

- Claude: engine/P1 수집기, 판정기, 구조화 검색 API
- Codex: OpenAPI 계약, Express endpoint, 전광판 UI, raw RAG 패널

단, 이 프로젝트는 OpenAPI 계약 우선 원칙이 있으므로 P1 API도 `openapi.yaml`부터 정의한다.

## 데이터 수집 구조

## Source Registry - ABCD별 실제 수집처

수집 우선순위는 `공식/규제 원문 -> 산업 통계 -> 신뢰 언론/데이터 벤더 -> 커뮤니티/루머` 순서다. RAG에 넣을 때는 출처 등급을 저장하고, 답변에서는 S/A급 근거를 B/C/D급보다 우선한다.

### A. 메모리 공급/생산 축

목적: 공급 업체의 실적, 가격, 재고, CAPEX, HBM 계약, 고객 인증, bit growth, ASP 방향을 잡는다.

| 대상 | 1차 수집처 | 보조 수집처 | 봐야 할 필드 |
| --- | --- | --- | --- |
| Samsung Electronics | Samsung IR earnings releases: https://www.samsung.com/global/ir/financial-information/earnings-release/ | Samsung IR presentations/events: https://www.samsung.com/global/ir/ir-events-presentations/ | Memory 매출/영업이익, DRAM/NAND 코멘트, HBM 고객 인증, CAPEX, inventory |
| SK hynix | SK hynix earnings releases: https://www.skhynix.com/ir/UI-FR-IR06/ | SK hynix IR main: https://www.skhynix.com/ir/UI-FR-IR01/ | HBM 매출 비중, HBM3E/HBM4, Nvidia/고객 인증, DRAM ASP, CAPEX, 재고 |
| Micron | Micron quarterly results: https://investors.micron.com/quarterly-results | Micron events/presentations: https://investors.micron.com/events-and-presentations | HBM 매출/계약, long-term agreement, DRAM/NAND ASP, bit shipments, gross margin |
| TSMC | TSMC IR: https://investor.tsmc.com/english | TSMC press: https://pr.tsmc.com/english | CoWoS/advanced packaging, HPC 매출, AI accelerator 수요, CAPEX |
| 보조 메모리 업체 | 각사 IR/공시 | 신뢰 언론/산업 리포트 | NAND/SSD 회복, 공급 축소, 가격 코멘트 |

TSMC는 메모리 생산 업체가 아니라 `AI accelerator/advanced packaging supply chain`으로 저장한다. HBM 수요의 선행 지표로는 중요하지만 A축의 Samsung/SK hynix/Micron과 같은 분류로 섞지 않는다.

수집 주기:

- 실적 시즌: 발표 당일 즉시
- IR/컨퍼런스 자료: 주 1회 체크
- SEC/공시: 주 1회 체크

### B. 하이퍼스케일러/메모리 소비 축

목적: 실제 AI 서버/데이터센터 투자가 늘고 있는지, 줄고 있는지, 과잉인지 판단한다. 메모리 생산 업체 주가는 이 축의 CAPEX와 compute utilization 코멘트에 민감하다.

| 대상 | 1차 수집처 | 보조 수집처 | 봐야 할 필드 |
| --- | --- | --- | --- |
| Amazon/AWS | Amazon quarterly results: https://ir.aboutamazon.com/quarterly-results/default.aspx | Amazon IR overview: https://ir.aboutamazon.com/overview/default.aspx | AWS 성장률, AI 수요, CAPEX, 데이터센터 투자, backlog/guide |
| Microsoft/Azure | Microsoft earnings: https://www.microsoft.com/en-us/investor/earnings | Microsoft SEC filings: https://www.microsoft.com/en-us/investor/sec-filings | Azure AI 수요, cloud growth, AI capacity constraint, CAPEX, depreciation |
| Alphabet/Google | Alphabet investor: https://abc.xyz/investor/ | Alphabet earnings call pages, Google blog | technical infrastructure CAPEX, servers vs DC/network 비중, TPU/GPU 배치, Gemini usage |
| Meta | Meta IR: https://investor.atmeta.com/home/default.aspx | Meta financials: https://investor.atmeta.com/financials/ | AI CAPEX, data center buildout, excess capacity, compute resale, infra utilization |
| Apple | Apple IR: https://investor.apple.com/investor-relations/default.aspx | Apple earnings call: https://www.apple.com/investor/earnings-call/ | on-device AI, iPhone/Mac 수요, DRAM/NAND 소비, AI 기능 지연/강화 |
| Oracle | Oracle IR: https://investor.oracle.com/home/default.aspx | Oracle events: https://investor.oracle.com/events-and-presentations/default.aspx | OCI 성장률, RPO, AI cloud backlog, GPU cluster 수요 |
| CoreWeave | CoreWeave IR: https://investors.coreweave.com/overview/default.aspx | CoreWeave quarterly results: https://investors.coreweave.com/financials/quarterly-results/default.aspx | GPU cloud 수요, revenue backlog, capex/debt, utilization, customer concentration |

수집 주기:

- Big Tech 실적/콜: 발표 당일
- IR 이벤트/SEC filings: 주 1회
- 클라우드/AI 인프라 단독 기사: 매일

특히 수집해야 할 표현:

- "capacity constrained"
- "technical infrastructure"
- "AI infrastructure demand"
- "servers"
- "data centers and networking"
- "backlog"
- "RPO"
- "excess capacity"
- "monetize compute"
- "capex guidance"

### C. AI 프론티어 수요 축

목적: AI 사용량, 매출, API/consumer adoption, 신규 모델 출시, compute partnership이 실제 메모리 수요를 밀어 올리는지 판단한다.

| 대상 | 1차 수집처 | 보조 수집처 | 봐야 할 필드 |
| --- | --- | --- | --- |
| OpenAI | OpenAI news: https://openai.com/news/ | OpenAI infrastructure posts, Microsoft/OpenAI/Oracle 관련 공식 발표 | WAU/DAU, API 사용량, revenue run-rate, Stargate/data center, compute partnership |
| Anthropic | Anthropic news: https://www.anthropic.com/news | Google/Broadcom partnership: https://www.anthropic.com/news/google-broadcom-partnership-compute | Claude 사용량, enterprise adoption, Google/AWS/Broadcom compute, capacity shortage |
| Google DeepMind/Gemini | DeepMind blog: https://deepmind.google/blog/ | Gemini updates: https://blog.google/products-and-platforms/products/gemini/ | Gemini 사용량, 신규 모델, inference product 확대, TPU 수요 |
| Meta AI | Meta IR/공식 블로그 | Meta AI/newsroom | Meta AI 사용자 수, Llama 전략, 내부 AI infra 수요, compute resale 신호 |
| xAI/기타 | 회사 공식 블로그/X 공식 계정 | 신뢰 언론 | 데이터센터/GPU cluster, 모델 출시, 사용자 성장 |

수집 주기:

- 공식 모델/제품 발표: 매일
- 사용량/매출/compute deal 뉴스: 매일
- 비공식 추정치: D급 또는 B/C급으로 저장하고 원문 사실과 분리

주의:

- C축은 비상장 회사가 많아 숫자 신뢰도가 낮다.
- "매출이 늘었다"보다 "사용량이 늘어 inference compute가 늘었는가"가 메모리 수요에는 더 중요하다.
- OpenAI/Anthropic 같은 회사의 compute deal은 B축 hyperscaler CAPEX와 중복되므로 event dedupe가 필요하다.

### C-2. Token Economy / Inference Demand 축

이 레이어가 없으면 RAG가 나이브해진다. 메모리 수요는 단순히 "AI 회사가 잘 된다"가 아니라 `얼마나 많은 토큰이, 어떤 모델에서, 어떤 latency/concurrency로, 어떤 context length로 처리되는가`에 의해 결정된다.

핵심 관점:

```text
token usage 증가
  -> inference compute 증가
  -> GPU/ASIC utilization 증가
  -> HBM bandwidth/KV cache/serving memory pressure 증가
  -> AI accelerator 추가 구매 또는 utilization 상승
  -> HBM/DRAM/SSD 수요 변화
```

전세계 token usage는 공식 집계가 거의 없다. 따라서 직접값과 proxy를 분리한다.

#### 1. 직접 수집 가능한 데이터

| 데이터 | 수집처 | 의미 |
| --- | --- | --- |
| 모델별 API 가격 | OpenAI pricing: https://openai.com/api/pricing/ | 토큰당 가격, 모델 믹스 변화, 가격 인하/인상 |
| Claude API 가격 | Anthropic pricing: https://docs.anthropic.com/en/docs/about-claude/pricing | input/output/cache 가격, 모델별 가격 압력 |
| Gemini API 가격 | Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing | multimodal token 가격, thinking token 포함 여부 |
| Gemini token/rate docs | Gemini token docs: https://ai.google.dev/gemini-api/docs/tokens / rate limits: https://ai.google.dev/gemini-api/docs/rate-limits | TPM/RPM/RPD, token counting 방식 |
| Claude rate/spend limits | Anthropic rate limits: https://docs.anthropic.com/en/api/rate-limits | enterprise/API usage ceiling proxy |
| ChatGPT WAU/사용자 발표 | OpenAI usage/adoption posts | consumer AI demand proxy |
| OpenAI enterprise/consumer adoption | OpenAI business/resources posts | workplace adoption, paid subscriber, enterprise penetration |

#### 2. 추정해야 하는 데이터

| 추정 지표 | 계산/추정 방법 | 한계 |
| --- | --- | --- |
| provider별 monthly token volume | API revenue / blended token price | revenue가 비공개이거나 subscription 포함 |
| output token share | 모델 가격표와 product type으로 추정 | output token이 input보다 compute/HBM 부담이 큼 |
| inference revenue per token | 가격표의 input/output/cache weighted average | discount, batch, enterprise 계약 반영 어려움 |
| effective token price trend | 동일 모델군의 $/1M token 변화 추적 | 가격 인하는 수요 증가와 margin 압박을 동시에 의미 |
| model mix | pricing/model launch/traffic/product note로 추정 | provider 내부 믹스는 비공개 |
| context length pressure | long-context 모델 출시, coding/agent 사용 증가, cache 가격으로 추정 | 실제 평균 context는 비공개 |
| concurrency pressure | rate limit, latency 이슈, outage, capacity constrained 발언 | anecdotal risk |

#### 3. token 지표에서 봐야 할 것

단순히 토큰 수가 많다는 것보다 아래가 더 중요하다.

- `output tokens`: input보다 대체로 더 비싼 구간이며 decode 단계에서 memory bandwidth와 latency 부담이 크다.
- `context length`: 긴 context는 KV cache 메모리 부담을 키운다.
- `concurrency`: 동시에 많은 요청을 처리해야 하면 serving capacity와 HBM 용량/대역폭 부담이 커진다.
- `reasoning/thinking tokens`: 사용자에게 보이지 않는 내부 토큰이 늘면 실제 compute/token demand가 증가한다.
- `cache read/write`: context caching 가격과 사용 증가는 long-context inference가 늘고 있다는 신호다.
- `price cuts`: 수요 탄력성을 자극할 수 있지만, 같은 매출당 필요한 token volume이 커진다는 의미이기도 하다.
- `API vs subscription`: API는 token volume 추정이 상대적으로 쉽고, subscription은 사용량/원가 압박을 봐야 한다.
- `modal mix`: text보다 image/video/audio는 tokenization과 compute profile이 다르므로 별도 태그가 필요하다.

#### 4. Token Economy 저장 스키마

```yaml
TokenPricingSnapshot:
  id: string
  provider: openai | anthropic | google | xai | meta | other
  model: string
  captured_at: string
  effective_from: string | null
  input_price_per_1m: number | null
  output_price_per_1m: number | null
  cache_write_price_per_1m: number | null
  cache_read_price_per_1m: number | null
  batch_discount: string | null
  modality: text | image | audio | video | multimodal
  context_window: number | null
  source_url: string
  source_grade: S

TokenUsageSignal:
  id: string
  provider: string
  product: chatgpt | claude | gemini | api | enterprise | coding | other
  signal_type: wau | dau | subscriber_count | api_revenue | revenue_run_rate | traffic | rate_limit | outage | capacity_constraint
  value: number | string | null
  unit: users | dollars | tokens | requests | qualitative
  period: string
  raw_quote: string
  source_url: string
  source_grade: S | A | B | C | D
  confidence: number

TokenDemandEstimate:
  id: string
  provider: string
  period: string
  estimate_method: revenue_divided_by_blended_price | traffic_model | disclosed_usage | analyst_estimate
  estimated_input_tokens: number | null
  estimated_output_tokens: number | null
  estimated_total_tokens: number | null
  blended_price_per_1m: number | null
  assumptions: string[]
  caveats: string[]
  confidence: number
```

#### 5. Token 지표와 메모리 영향 연결

```yaml
TokenMemoryImpact:
  token_signal_id: string
  impact_channel: hbm_bandwidth | hbm_capacity | gpu_utilization | server_dram | nvme_storage | networking
  direction: positive | negative | mixed | unclear
  reasoning:
  affected_companies:
  time_horizon: immediate | next_quarter | next_2_4_quarters | long_term
```

예시:

```text
OpenAI가 ChatGPT WAU 900M과 subscriber 50M을 공개
  -> consumer inference demand base 확대
  -> high concurrency serving capacity 필요
  -> GPU/HBM utilization 상승
  -> B축 hyperscaler 또는 Stargate CAPEX 정당화
  -> HBM 공급사에 구조적 긍정
```

```text
주요 모델 API 가격이 50% 인하
  -> 단위 token 매출은 하락
  -> 사용량 탄력성이 크면 총 token volume 증가
  -> inference capacity 수요는 증가할 수 있음
  -> 단, provider margin/ROI 우려는 B축 CAPEX sentiment에 부정 가능
```

#### 6. Raw RAG에서 token 데이터를 보여주는 방식

LLM 답변 아래에 `Token Evidence` 블록을 둔다.

```text
Token Evidence
1. Provider: OpenAI
   Metric: ChatGPT WAU / paid subscribers
   Raw: [공식 발표 원문]
   Memory link: consumer inference concurrency -> HBM bandwidth/capacity

2. Provider: Anthropic
   Metric: Claude Sonnet input/output price
   Raw: [가격표 snapshot]
   Memory link: token price decline -> possible usage elasticity / margin pressure

3. Provider: Google
   Metric: Gemini output price incl. thinking tokens
   Raw: [가격표 snapshot]
   Memory link: hidden reasoning tokens increase effective compute/token demand
```

#### 7. 전광판에 추가해야 할 token 카드

기존 메모리 전광판에 아래 카드를 추가한다.

- Global Token Demand Proxy
- API Price Index
- Output Token Premium
- Long Context / KV Cache Pressure
- Frontier AI Usage Momentum
- Inference Margin Pressure

각 카드는 긍정/중립/부정이 아니라 `수요 증가`, `가격 압박`, `혼재`, `데이터 부족`으로 표시한다.

### D. 가격/수급/산업 검증 축

목적: A/B/C 뉴스가 실제 DRAM/NAND/HBM 수급으로 연결되는지 검증한다.

| 데이터 | 1차 수집처 | 보조 수집처 | 봐야 할 필드 |
| --- | --- | --- | --- |
| 전체 반도체 매출/지역별 매출 | WSTS: https://www.wsts.org/ | SIA market data: https://www.semiconductors.org/data-resources/market-data/ | monthly sales, 3MMA, product category, region |
| 장비/팹 투자 | SEMI Market Intelligence: https://www.semi.org/en/products-services/market-intelligence | SEMI Fab Forecast | fab capacity, equipment billings, materials, packaging |
| DRAM/NAND 가격 | TrendForce/DRAMeXchange | Omdia, Gartner, 언론 요약 | spot/contract price 방향, QoQ 변화, 서버 DRAM/NAND 가격 |
| 출하/수요 | IDC/Gartner/Omdia | 회사 실적 코멘트 | server, PC, smartphone shipment |
| 한국 반도체 수출 | 한국 관세청/산업통상자원부/무역협회 | 통계청/언론 요약 | memory export value, YoY/MoM, destination |
| 대만 공급망 | 대만 경제부/거래소/회사 월매출 | Digitimes/TrendForce | TSMC, ASE, 장비/패키징 업체 월매출 |
| 시장 가격 반응 | 거래소/finance API | Yahoo Finance, Nasdaq, KRX | 이벤트 전후 주가, peer reaction, ETF reaction |

수집 주기:

- WSTS/SIA/SEMI: 월간
- DRAM/NAND 가격: 주간 또는 데이터 라이선스 허용 범위
- 한국 수출: 월간, 발표 당일
- 주가 반응: 이벤트 당일/3일/5일 자동 계산

주의:

- 유료 데이터는 라이선스 위반 없이 `direction`, `change_rate`, `source_meta`만 저장한다.
- 가격 데이터가 없으면 LLM이 뉴스만 보고 과잉 해석하므로, D축은 RAG 답변의 검증 레이어로 항상 붙인다.

### A. 메모리 공급/생산 업체

수집 대상:

- Samsung Electronics
- SK hynix
- Micron
- 필요시 Kioxia, Western Digital, Nanya, Winbond

필수 원천 데이터:

- 분기 실적 발표 자료
- 컨퍼런스콜 스크립트/준비 발언
- IR 프레젠테이션
- 연차보고서/10-K/20-F
- CAPEX 코멘트
- bit shipment, ASP, inventory, utilization 관련 발언
- HBM 세대별 코멘트: HBM3E, HBM4, 고객 인증, 공급계약
- DRAM/NAND 제품 믹스
- 장기 공급계약, minimum price, prepayment, take-or-pay 성격의 표현

주요 추출 필드:

```yaml
company:
period:
source_type: earnings_release | transcript | filing | presentation | press_release
memory_segment: hbm | dram | nand | ssd | foundry_related | mixed
metric_type: asp | bit_shipment | inventory | capex | margin | utilization | customer_certification | supply_contract
direction: positive | neutral | negative | mixed
time_horizon: immediate | next_quarter | next_2_4_quarters | long_term
raw_quote:
interpreted_signal:
affected_names: [Samsung, SK hynix, Micron]
confidence:
source_url:
published_at:
```

공식 출처:

- Samsung IR earnings releases: https://www.samsung.com/global/ir/financial-information/earnings-release/
- SK hynix IR earnings releases: https://www.skhynix.com/ir/UI-FR-IR06/
- Micron quarterly results: https://investors.micron.com/quarterly-results
- Micron events and presentations: https://investors.micron.com/events-and-presentations

### B. 하이퍼스케일러/메모리 소비 축

수집 대상:

- Amazon/AWS
- Microsoft/Azure
- Alphabet/Google Cloud/TPU
- Meta
- Apple
- Oracle
- CoreWeave, Nebius, Crusoe, Lambda 등 GPU cloud

필수 원천 데이터:

- 분기 실적 발표
- 컨퍼런스콜 중 CAPEX, AI infrastructure, cloud demand 발언
- data center buildout 발표
- 서버/네트워크/데이터센터 투자 비중
- GPU/TPU/ASIC 배치 관련 발언
- cloud backlog, AI revenue, AI usage growth
- excess capacity, compute resale, capex cut, depreciation pressure 관련 발언

주요 추출 필드:

```yaml
company:
period:
source_type: earnings_release | transcript | filing | press_release | official_blog | credible_news
demand_channel: cloud_ai | internal_ai | consumer_ai | enterprise_ai | device_ai | resale_compute
capex_signal: accelerating | stable_high | slowing | cutting | excess_capacity
compute_signal: gpu | tpu | asic | mixed | unknown
memory_impact: hbm_positive | dram_positive | nand_positive | negative | unclear
raw_quote:
interpreted_signal:
linked_memory_suppliers:
confidence:
source_url:
published_at:
```

공식 출처:

- Amazon quarterly results: https://ir.aboutamazon.com/quarterly-results/default.aspx
- Microsoft earnings: https://www.microsoft.com/en-us/investor/earnings
- Alphabet investor relations: https://abc.xyz/investor/
- Meta investor relations: https://investor.atmeta.com/home/default.aspx

### C. AI 프론티어 수요 축

수집 대상:

- OpenAI
- Anthropic
- Google DeepMind/Gemini
- Meta AI
- xAI
- Mistral, Perplexity 등 필요시

필수 원천 데이터:

- 사용자 수/사용량/DAU/WAU/API 사용량
- 신규 모델 출시
- inference 비용/가격 인하/토큰 가격 변화
- enterprise adoption
- compute partnership
- data center partnership
- 모델 성능 둔화, usage 감소, 매출 둔화, 규제 리스크
- 신규 product surface: agent, coding, video, search, enterprise, science

주요 추출 필드:

```yaml
company:
event_type: model_launch | usage_metric | revenue_metric | compute_deal | datacenter | pricing | negative_usage | regulation
ai_demand_signal: accelerating | stable | decelerating | uncertain
compute_intensity: training_heavy | inference_heavy | mixed | unknown
memory_impact: hbm | dram | nand | storage | unclear
raw_quote:
interpreted_signal:
downstream_path:
confidence:
source_url:
published_at:
```

공식/준공식 출처:

- OpenAI business/compute posts: https://openai.com/news/
- OpenAI Stargate infrastructure posts: https://openai.com/index/building-the-compute-infrastructure-for-the-intelligence-age/
- Anthropic news: https://www.anthropic.com/news
- Anthropic Google/Broadcom compute partnership: https://www.anthropic.com/news/google-broadcom-partnership-compute
- Google DeepMind blog: https://deepmind.google/blog/
- Gemini updates: https://blog.google/products-and-platforms/products/gemini/

### D. 가격/수급 데이터

이 축은 A/B/C 뉴스를 실제 메모리 가격으로 연결하는 검증 레이어다.

수집 대상:

- DRAM spot price
- DRAM contract price
- NAND spot/contract price
- HBM 공급계약/가격 코멘트
- enterprise SSD 가격
- inventory days
- channel inventory
- server shipment
- smartphone/PC shipment

가능한 출처:

- TrendForce/DRAMeXchange
- Omdia
- Gartner
- IDC
- SEMI
- WSTS
- 한국 반도체 수출 통계
- 대만/한국 월간 수출입 데이터

주의:

- 유료 데이터는 원문 전문 저장 대신 라이선스에 맞는 요약/메타데이터만 저장한다.
- 가격 데이터는 "값"보다 "방향 변화"와 "변화율"을 우선 저장한다.

### E. 주가 반응/시장 해석 데이터

RAG의 답변 품질을 높이려면 원문 사실과 시장 반응을 분리해야 한다.

수집 대상:

- 이벤트 전후 주가 반응: 당일, 3일, 5일
- 관련 ETF/동종업계 반응
- sell-side note headline
- 뉴스에서 언급된 우려: capex bubble, excess compute, AI usage slowdown
- 긍정 해석: long-term supply agreement, HBM shortage, cloud backlog growth

추출 필드:

```yaml
event_id:
tickers:
price_reaction_1d:
price_reaction_3d:
peer_reaction:
market_narrative:
is_reaction_confirmed: true | false
source_url:
```

## 원천 신뢰도 등급

RAG 검색 결과에는 항상 출처 등급을 붙인다.

```text
S급: 회사 IR, SEC filing, 공식 블로그, 실적 컨퍼런스콜 원문
A급: 규제기관/산업기관 통계, SEMI/WSTS/정부 수출 통계
B급: 신뢰도 높은 언론의 단독/확인 기사
C급: 증권사 리포트 요약, 서드파티 데이터 요약
D급: 커뮤니티, X, 미확인 루머
```

답변 생성 시 규칙:

- S/A급이 있으면 B/C/D급보다 우선한다.
- D급만 있는 경우 "루머/미확인"으로 표시한다.
- 시장 반응과 원문 사실을 섞지 않는다.
- "이 뉴스가 SK하이닉스에 좋다"는 해석은 반드시 영향 경로를 붙인다.

## 인덱싱 논리 구조

일반 RAG처럼 문서 chunk만 넣으면 안 된다. 메모리 섹터는 이벤트-인과관계 RAG가 필요하다.

### 1. Document Layer

원문 단위:

- 실적 발표 PDF
- 컨퍼런스콜 스크립트
- SEC filing
- 공식 블로그
- 뉴스 기사
- 산업 리포트 요약

저장 필드:

```yaml
document_id:
source_url:
publisher:
company:
published_at:
source_grade:
document_type:
raw_text:
```

### 2. Evidence Chunk Layer

LLM 검색 단위:

```yaml
chunk_id:
document_id:
text:
page_or_section:
quoted_span:
entities:
metrics:
event_tags:
memory_tags:
time_horizon:
source_grade:
```

### 3. Event Layer

투자 판단 단위:

```yaml
event_id:
event_date:
event_type:
actor_company:
affected_companies:
summary:
raw_evidence_chunk_ids:
impact_path:
memory_impact:
confidence:
contradicting_event_ids:
```

예시:

```text
Meta가 excess AI compute를 외부 판매 검토
  -> AI infra 과잉 투자 우려
  -> GPU/HBM 신규 주문 지속성 의심
  -> HBM 공급사 주가 단기 부정
```

단, 이 구조는 "추론"이므로 원문 근거와 별도 필드로 저장한다.

### 4. Thesis Layer

투자 관점 단위:

```yaml
thesis_id:
name:
claim:
supporting_event_ids:
contradicting_event_ids:
status: strengthening | weakening | mixed | stale
last_updated_at:
```

예시 thesis:

- HBM shortage remains structurally tight
- Hyperscaler AI CAPEX remains accelerating
- AI inference demand offsets training cycle volatility
- Excess compute risk is rising
- NAND recovery is separate from HBM cycle

## Raw RAG 화면 설계

전광판에서 LLM 답변만 보여주면 안 된다. 반드시 "raw 근거" 패널을 같이 둔다.

### 화면 1: 메모리 전광판

상단 카드:

- HBM 수요 신호
- DRAM 가격 신호
- NAND 가격 신호
- Hyperscaler CAPEX 신호
- AI Frontier usage 신호
- 이번 주 이벤트

각 카드는 세 상태만 쓴다.

```text
긍정 / 중립 / 부정
```

색상은 보조 정보일 뿐이고, 텍스트 라벨을 반드시 같이 표시한다.

### 화면 2: 영향 경로 그래프

왼쪽에서 오른쪽으로 흐름을 보여준다.

```text
C. AI Frontier
  -> B. Hyperscaler/Cloud
  -> GPU/ASIC/TPU
  -> HBM/DRAM/NAND
  -> A. Memory Producers
  -> Stock/earnings reaction
```

노드는 클릭 가능해야 한다.

클릭 시:

- 관련 이벤트
- raw quote
- source grade
- affected tickers
- LLM 해석
- 반대 근거

를 보여준다.

### 화면 3: Raw RAG 패널

질문 답변 아래에 항상 붙인다.

```text
Answer
LLM의 요약/판단

Raw RAG
1. Source: Alphabet Q1 2026 earnings call
   Grade: S
   Matched text: "CapEx was ..."
   Why it matters: AI infra capex -> server/accelerator demand -> HBM demand

2. Source: SK hynix FY2026 Q1 earnings
   Grade: S
   Matched text: "..."
   Why it matters: supplier-side HBM capacity/ASP signal

Contradictions
1. Source: Meta excess compute report
   Grade: B
   Why it conflicts: possible overcapacity signal
```

Raw RAG에는 LLM 요약이 아니라 원문 chunk와 메타데이터를 먼저 보여준다. 요약은 접힌 영역으로 둔다.

### 화면 4: 이벤트 타임라인

한 줄 카드 구조:

```text
날짜 | 회사 | 이벤트 | 영향 축 | 메모리 영향 | 근거 등급 | 관련 종목
```

필터:

- A/B/C 축
- HBM/DRAM/NAND
- 긍정/중립/부정
- S/A/B/C/D 출처 등급
- 최근 7일/30일/분기

### 화면 5: Thesis Monitor

주요 투자 가설별로 강화/약화 근거를 보여준다.

예시:

```text
Thesis: HBM shortage remains structurally tight
Status: strengthening

Supporting:
- Anthropic multi-GW TPU capacity agreement
- Alphabet technical infrastructure capex increase
- Micron HBM supply commentary

Contradicting:
- Meta excess compute monetization report
- AI usage slowdown reports, if confirmed
```

## LLM 답변 구조

질문: "Meta가 남는 GPU로 클라우드 사업한다는 뉴스가 하이닉스에 왜 악재야?"

답변 형식:

```text
결론:
단기적으로는 SK하이닉스/HBM sentiment에 부정적이다.

근거:
1. Meta가 AI compute를 초과 보유하고 있다면 hyperscaler의 추가 GPU/HBM 주문 지속성에 의심이 생긴다.
2. HBM은 GPU/AI accelerator에 붙는 고부가 메모리라, AI infra 과잉 우려가 곧 HBM demand multiple 하락으로 연결된다.
3. 다만 이것이 실제 주문 취소인지, 단순 monetization 전략인지는 원문에서 확인해야 한다.

반대 근거:
Meta가 compute resale을 하더라도 전체 AI usage가 증가하고, 다른 hyperscaler/OpenAI/Anthropic 수요가 더 강하면 구조적 수요는 유지될 수 있다.

Raw RAG:
[원문 chunk 목록]
```

## 초기 MVP 범위

1단계는 문서 업로드형 RAG가 아니라 `이벤트 카드 + 지표 시계열` 수집기로 시작한다. 문서 chunk RAG는 raw evidence 보강용이지 MVP의 중심이 아니다.

### MVP 1

- `memory_sources`와 query matrix 정의
- 이벤트 카드 스키마 확정
- OpenRouter token usage/pricing snapshot 수집
- TrendForce DataTrack 링크/메타데이터 등록, 가능하면 공개 차트 값 수집
- Yahoo/KRX/Nasdaq 기반 A/B/market 주가 반응 수집
- 공식 IR/RSS/공시 URL 수동 등록
- LLM 판정으로 axis, edge, direction, magnitude 부여
- `storage/rag/memory_sector/index.jsonl`과 `metrics/*.jsonl`에 저장
- raw RAG 패널에 카드 원문 발췌 표시

### MVP 2

- RSS/IR/공시 페이지 주기적 체크
- DART/SEC EDGAR 추가
- 대만 월매출, 한국 반도체 수출, TSMC 월매출 추가
- 신규 이벤트 자동 생성과 dedupe
- 전광판 카드 자동 업데이트
- 이벤트 타임라인과 지표 차트 오버레이

### MVP 3

- 구조화 질문 검색 API
- `sector_rag` 레이어를 답변 파이프라인에 연결
- 호재/악재/반대근거 균형 검색
- thesis monitor
- 판정 피드백 루프
- 필요할 때 임베딩 검색 추가

## 저장 스키마 초안

```yaml
MemoryDocument:
  id: string
  title: string
  source_url: string
  source_grade: S | A | B | C | D
  publisher: string
  company: string
  axis: A | B | C | D | market
  document_type: earnings | transcript | filing | news | industry_data | blog | presentation
  published_at: string
  ingested_at: string
  raw_text_path: string

MemoryChunk:
  id: string
  document_id: string
  text: string
  entities: string[]
  memory_tags: hbm | dram | nand | ssd | capex | gpu | tpu | usage | revenue | pricing
  sentiment: positive | neutral | negative | mixed
  source_grade: S | A | B | C | D

MemoryEvent:
  id: string
  title: string
  event_date: string
  axis: A | A_prime | B | C | D | market
  edge: A_to_A | A_prime_to_A | B_to_A | C_to_A | D_to_A | market_to_A
  event_type: demand_signal | supply_signal | price_signal | earnings | filing | policy | speaker | product_policy | market_reaction
  actor_company: string
  affected_companies: string[]
  speaker: string | null
  direction: positive | neutral | negative | mixed
  magnitude: 1 | 2 | 3
  memory_impact: hbm_positive | hbm_negative | dram_positive | dram_negative | nand_positive | nand_negative | mixed | unclear
  impact_path: string
  evidence_chunk_ids: string[]
  contradiction_chunk_ids: string[]
  confidence: number

MemoryMetricObservation:
  id: string
  metric_name: string
  observed_at: string
  axis: A | A_prime | B | C | D | market
  entity: string
  value: number | string | null
  unit: string
  period: string
  source_url: string
  source_grade: S | A | B | C | D
  caveats: string[]

MemoryDerivedSignal:
  id: string
  signal_name: token_spend_direction | spot_contract_spread | capex_words_vs_money | stock_chain_divergence | hbm_tightness | supply_overbuild_risk
  calculated_at: string
  inputs: string[]
  direction: positive | neutral | negative | mixed
  summary: string
  caveats: string[]

MemoryThesis:
  id: string
  claim: string
  status: strengthening | weakening | mixed | stale
  supporting_event_ids: string[]
  contradicting_event_ids: string[]
  updated_at: string
```

## 구현 시 OpenAPI 우선 API 후보

프론트가 ad hoc으로 데이터를 가정하지 않도록 API 계약부터 만든다.

```text
GET /api/memory-board
GET /api/memory-events
GET /api/memory-events/:id
GET /api/memory-documents
POST /api/memory-documents
GET /api/memory-theses
POST /api/memory-query
```

`POST /api/memory-query` 응답은 반드시 다음을 포함한다.

```yaml
ok:
answer:
rawEvidence:
contradictions:
events:
theses:
```

## 중요한 설계 원칙

1. RAG는 "뉴스 검색"이 아니라 "인과관계 검색"이어야 한다.
2. 원문 사실, 시장 반응, LLM 해석을 분리 저장한다.
3. C축의 AI 사용량/매출 둔화 뉴스는 단독으로 끝나지 않고 B축 CAPEX와 A축 HBM/DRAM 수요로 연결해야 한다.
4. 부정 뉴스는 반드시 "실제 주문 감소"인지 "sentiment 악화"인지 구분한다.
5. Raw RAG를 기본 노출해서 사용자가 LLM 해석을 검증할 수 있게 한다.
