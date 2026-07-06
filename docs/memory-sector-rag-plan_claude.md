# 메모리 섹터 RAG 계획 (_claude)

작성: Claude, 2026-07-06
상태: 초안 — codex 계획(`*_codex.md`)과 교차 검토 후 확정

## 0. 목표

메모리 반도체 섹터에 대한 관련 데이터를 **미리, 계속** 모아두고,
질문이 들어오면 LLM이 이 축적된 데이터를 근거로 답하게 한다.

- RAG = 질문 시점에 관련 데이터 조각을 골라 LLM 프롬프트에 넣어주는 구조.
  (매번 웹검색하는 지금 방식과 달리, 미리 정제해둔 자산에서 꺼냄)
- **raw RAG 노출**: 답변에 어떤 조각이 뽑혀 들어갔는지 원문 그대로 화면에 보여준다.
  → 지금 뉴스 패널처럼, 근거를 사용자가 직접 검증 가능.

## 1. 도메인 모델 — 3축 + 인과 엣지

yvon 제안 3축을 그대로 쓰되, 한 가지 보정:

| 축 | 구성 | 역할 |
|---|---|---|
| **A 메모리 생산** | 삼성전자(005930), SK하이닉스(000660), 마이크론(MU) | 관측 대상 (주가가 결과값) |
| **A' 인접 생산** | TSMC(2330.TW / TSM) | 파운드리(위탁생산). 메모리사는 아니지만 HBM 패키징·AI칩 생산 능력이 메모리 수요의 선행 신호 |
| **B 하이퍼스케일러/소비** | MS, 구글, 아마존, 메타, 애플, 오라클 | 수요 신호의 원천 1 |
| **C AI 프론티어** | OpenAI, Anthropic, 구글(DeepMind), xAI | 수요 신호의 원천 2 (대부분 비상장 → 뉴스가 유일한 신호) |

> 보정 이유: TSMC는 D램/낸드를 만들지 않는 파운드리라 A에 그대로 넣으면
> 신호 해석이 꼬임. 별도 축(A')으로 두면 "TSMC CoWoS 증설 = HBM 수요 증가"
> 같은 선행 신호로 쓸 수 있음.

### 인과 엣지 (수집·판정의 논리 뼈대)

A 주가 = f(B 수요 신호, C 수요 신호, A 자체 공급 신호)

- **B→A**: capex(설비투자) 가이던스 증액 = 호재 / "메모리 비싸다" 발언·구매 축소 = 악재 /
  "GPU 남아서 클라우드 사업" = 인프라 과잉 신호 = 악재 (실사례: 애플 발언, 메타 GPU 잉여 → 메모리 주가 하락)
- **C→A**: AI 사용량·매출 성장 = 호재 / 사용량 감소·매출 부진 = 악재 /
  "더 적은 칩으로 같은 성능"(효율화) = 악재
- **A→A**: 감산·증산 발표, HBM 수주·공급계약, D램/낸드 고정거래가격 발표, 실적·재고

모든 수집 데이터는 이 엣지 중 하나에 매핑된다. 매핑 안 되는 데이터는 버린다
(→ 이번 검색품질 사고 재발 방지: "관련 없음"의 기준을 코드로 갖게 됨).

## 2. Raw 데이터 — 무엇을 모으나 (2레이어)

- **레이어 1 — 이벤트 카드**: 뉴스·발언·계약 같은 정성 신호. "왜 움직였나"를 설명.
- **레이어 2 — 정량 지표 시계열**: 토큰 사용량·토큰 단가·D램 현물가·capex 같은 숫자.
  "실제로 수요가 늘고 있나"를 발언과 무관하게 측정. (2026-07-06 소스 검증 완료, §2-2)

두 레이어는 같은 날짜축을 공유 → 차트에서 이벤트 마커와 지표 곡선을 겹쳐
"발언이 실제 지표로 이어졌는지"를 눈으로 검증하는 게 이 설계의 핵심 가치.

### 2-1. 레이어 1: 이벤트 카드

수집 단위는 **이벤트 카드** 하나. 스키마:

```json
{
  "id": "url 정규화 해시",
  "ts": "2026-07-06T09:00:00Z",
  "axis": "B",                        // A | A' | B | C
  "entities": ["META"],
  "edge": "B->A",
  "event_type": "demand_signal",      // demand_signal | supply_signal | price_signal | earnings | policy
  "direction": "neg",                 // A 주가 관점 호재(pos)/악재(neg)/중립(neutral)
  "magnitude": 2,                     // 1(언급)~3(가이던스·계약 등 확정 이벤트)
  "title": "...",
  "summary": "sonnet 1~2줄 요약",
  "url": "...", "source": "reuters.com",
  "raw_excerpt": "원문 발췌 (raw RAG 노출용)"
}
```

### 소스별 수집 항목

| 소스 (기존 도구 재사용) | 수집 내용 |
|---|---|
| brave news/web (`engine/tools/news/`) | 축별 뉴스 — 아래 쿼리 매트릭스. geo 라우팅·`_clean_pool`(커뮤니티 필터+dedup) 그대로 재사용 |
| `fetch_body` | 상위 카드의 본문 확보 (요약·발췌 품질용) |
| yahoo (`engine/tools/price/`) | A·A'·B 종목 일별 종가/등락률 + SOX(필라델피아 반도체지수) — 이벤트 카드와 같은 날짜축에 겹쳐 그리기 위함 |
| toss feed (`engine/tools/toss/`) | 국내 투자자 반응(삼전·하이닉스) — 참고 신호, direction 판정에는 미사용 |
| D램 가격 (TrendForce/DRAMeXchange) | **직접 API는 유료.** 1단계는 "DRAM contract price", "낸드 고정거래가격" 뉴스 기사로 간접 수집. 별도 소스 확보는 미해결 질문 §6 |

### 쿼리 매트릭스 (엔티티 × 주제, 영어 위주 + 국내 종목은 한국어 병행)

- A: `SK Hynix HBM supply contract`, `Samsung DRAM price cut`, `Micron guidance`, `삼성전자 감산`, `메모리 고정거래가격`
- A': `TSMC CoWoS capacity`, `TSMC AI revenue`
- B: `{MS|Google|Amazon|Meta|Apple|Oracle} capex guidance`, `hyperscaler memory procurement`, `{회사} datacenter spending cut`
- C: `OpenAI revenue`, `Anthropic usage`, `AI inference demand`, `AI compute efficiency breakthrough`

주기: **하루 2회** (미국 장 마감 후 + 한국 장 마감 후). freshness=pd(당일).

### 2-2. 레이어 2: 정량 지표 시계열 (2026-07-06 웹검색으로 소스 실재 검증)

| 지표 | 축 | 소스 | 주기 | 비고 |
|---|---|---|---|---|
| 토큰 사용량 (전체 + 모델별 top50) | C | **OpenRouter 공개 데이터셋 API** (`/api/.../datasets/rankings-daily`, openrouter.ai/data) | 일별 | API 키만 있으면 무료. 주간 ~20조 토큰, 전년比 4배 성장 확인. **주의: 전세계 총량이 아니라 OpenRouter 경유분의 표본** — 절대값이 아닌 성장률·모델 구성 변화로 해석 |
| 앱별 토큰 사용 순위 | C | OpenRouter app rankings API | 일별 | 수요가 어떤 용도(코딩/챗봇)에서 오는지 |
| 토큰 단가 ($/1M, 모델별) | C | OpenRouter `/models` 응답을 **매일 스냅샷 → 자체 시계열 구축** | 일별 | 프론티어 출력단가 2023년比 -94.5% 추세. 외부 참고: pricepertoken.com/pricing-history |
| 빅랩 공식 발표 수치 | C | 실적발표·블로그 (예: 구글 월 1.3경 토큰 '25.10, MS 분기 100조) | 비정기 | 이벤트 카드에 `numeric: {value, unit}` 필드 추가해 점 데이터로 차트에 표시 |
| D램/낸드 현물가 | A | TrendForce DataTrack 공개 차트 페이지 스크랩 | 일별 | **무료 API 없음** — 스크랩은 깨질 수 있는 의존성(리스크 명시). HBM은 현물시장 자체가 없어(수의계약) 뉴스 카드로만 |
| 하이퍼스케일러 capex 실적치 | B | yahoo financials (현금흐름표의 설비투자 항목) | 분기 | 가이던스(카드)와 실적치(지표)를 구분해 저장 |
| 주가·SOX 지수 | A/B | yahoo (기존) | 일별 | 기존 계획 그대로 |

파생 지표 1개만 계산해 둔다: **토큰 총지출 방향** = 사용량 성장률 + 단가 변화율.
단가 하락이 "효율화(메모리 악재)"인지 "가격 내려도 총지출 증가(호재)"인지를
이 하나로 구분 — C→A 엣지 판정의 정량 근거.

저장: `storage/rag/memory_sector/metrics/{지표명}.jsonl` (1줄 = 1일 관측치).

## 3. 수집→판정→저장 파이프라인

```
[스케줄러: 하루 2회]
  1. 쿼리 매트릭스 실행 (brave, geo 라우팅)
  2. _clean_pool: 커뮤니티 도메인 제거 + URL dedup + 기존 카드와 dedup
  3. sonnet 배치 판정 1콜: 각 아이템 → {관련여부, axis, edge, event_type, direction, magnitude, summary}
     - "인과 엣지에 매핑 불가"면 drop → 관련성 필터가 곧 판정 단계
     - news_summary 스테이지의 구조화 출력 패턴 재사용
  4. 상위 magnitude 카드만 fetch_body로 본문 발췌 보강
  5. 저장: storage/rag/memory_sector/cards/YYYY-MM/*.json + index.jsonl(1줄=1카드)
  6. 지표 수집 (레이어 2): OpenRouter 사용량·단가 스냅샷, TrendForce 스크랩,
     yahoo 주가/SOX → metrics/*.jsonl append (지표별 독립 try/except — 하나 깨져도 나머지 수집)
```

비용: 회당 뉴스 ~60건 판정 = sonnet 1~2콜(입력 ~10K 토큰) ≈ **$0.05/일 미만**.

### 검색(질문 시점)

1단계는 **벡터 임베딩 없이** 구조화 검색으로 시작 (하루 수십 건 규모에선
메타데이터 필터가 더 정확하고 설명 가능):

```
질문 → 엔티티/축 추출 (플래너가 이미 함)
     → 필터: entities ∩ 질문 엔티티, 최근 N일(기본 14일)
     → 랭킹: magnitude ↓, 최신순, direction 균형(호재·악재 모두 포함 강제)
     → 상위 K(기본 12) 카드 → LLM 컨텍스트 [메모리 섹터 근거] 블록
```

카드가 수천 건 넘어가면 2단계로 임베딩 추가 (OpenAI embedding, 키 이미 있음).
지금 넣는 건 YAGNI.

## 4. 화면

### 4-1. 메모리 섹터 대시보드 (신규 뷰)

```
┌─ A 주가 스트립: 삼전 | 하이닉스 | MU | (A') TSM | SOX — 스파크라인 + 등락률
├─ 정량 지표 줄: 토큰 사용량 곡선 | 토큰 단가 곡선 | D램 현물가 | capex(분기 막대)
│   — 빅랩 발표 수치는 점으로, magnitude≥2 이벤트는 마커로 같은 차트에 오버레이
├─ 오늘의 신호 요약 (sonnet 3~5줄, 카드+지표 근거 링크)
├─ 이벤트 타임라인 (세로, 최신순)
│   [B→A ▼악재 ②] Meta, 잉여 GPU로 클라우드 사업 검토 — reuters (발췌…)
│   [C→A ▲호재 ③] OpenAI 연매출 xx조 달성 — bloomberg (발췌…)
│   ← 축/방향/크기 필터 칩
└─ 가격 차트 위에 magnitude≥2 이벤트 마커 오버레이 (신호→주가 반응 검증용)
```

### 4-2. raw RAG 패널 (질문 답변 화면)

기존 뉴스 요약 레이어와 같은 패턴 — 새 레이어 `sector_rag`:
- 답변에 투입된 카드 K건을 **원문 발췌 + 판정(축/방향/크기) + 왜 뽑혔는지(매칭 엔티티·날짜)** 와 함께 표시
- 판정이 틀렸으면 카드 단위로 👎 피드백 → 판정 프롬프트 개선 루프의 입력

## 5. 단계 제안 (각 단계가 독립적으로 동작·검증 가능)

1. **P1 수집기**: 쿼리 매트릭스 + 판정 + 카드 저장 + **지표 시계열 수집(레이어 2)** + 스케줄러. 산출물: index.jsonl + metrics/*.jsonl 쌓임
2. **P2 대시보드**: 카드·가격 읽어 4-1 뷰 렌더
3. **P3 QA 연결**: 질문 파이프라인에 구조화 검색 + `sector_rag` 레이어(raw RAG 노출)
4. **P4 (후순위)**: 임베딩 검색, D램 가격 직접 소스, 판정 피드백 루프

## 6. 미해결 질문 (codex·yvon 논의 필요)

1. D램/낸드 현물가 — TrendForce 공개 차트 스크랩으로 시작하되, 깨지면 뉴스 간접 수집으로 강등? 유료 소스(DRAMeXchange) 결제 여부?
2. OpenRouter API 키 발급 필요 (데이터셋 API는 키 인증) — 무료 계정으로 충분한지 확인
3. 스케줄러 위치 — engine 내 APScheduler vs 시스템 cron vs node(server.mjs) 쪽?
4. B/C 엔티티 확정 — 엔비디아를 어디 두나? (메모리 소비자이자 A' 성격도 있음 → 별도 축?)
5. 대시보드 진입점 — 기존 index.html 내 탭 vs 별도 페이지?
6. codex와 분업 경계 제안: **claude = engine(P1 수집·판정·검색 API), codex = UI(P2·P3 렌더)** — 역제안 환영
