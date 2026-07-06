# 메모리 섹터 RAG 계획 (_claude)

작성: Claude, 2026-07-06
상태: 초안 — codex 계획(`*_codex.md`)과 교차 검토 후 확정

## 0. 목표

메모리 반도체 섹터에 대한 관련 데이터를 **미리, 계속** 모아두고,
질문이 들어오면 LLM이 이 축적된 데이터를 근거로 답하게 한다.

> **최우선 원칙 (yvon): 유료든 무료든 "자동 수집"이 되는 소스가 1등이다.**
> 품질이 아무리 좋아도 사람이 매번 손으로 받아와야 하는 소스는 P1 파이프라인의
> 의존성에서 뺀다(수동 등록 입구의 옵션일 뿐). 소스 평가 축은 품질보다 **자동화
> 가능성**이 먼저. → §2-6 자동화 필터가 이 원칙의 집행부.

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
| **B 하이퍼스케일러/소비** | MS, 구글, 아마존, 메타, 애플, 오라클 + GPU 클라우드(CoreWeave, Nebius 등, codex 채택) | 수요 신호의 원천 1 |
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
  "axis": "B",                        // A | A'(공급망/패키징) | B | C
  "entities": ["META"],
  "speaker": "마크 저커버그",           // 스피커 레지스트리 매칭 시, 없으면 null
  "edge": "B->A",
  "event_type": "demand_signal",      // demand_signal | supply_signal | price_signal | earnings | filing | policy
  "memory_segment": "hbm",            // hbm | dram | nand | mixed — HBM 사이클 ≠ NAND 사이클 (codex 채택)
  "direction": "neg",                 // A 주가 관점 호재(pos)/악재(neg)/중립(neutral)
  "magnitude": 2,                     // 1(언급)~3(가이던스·계약 등 확정 이벤트)
  "time_horizon": "immediate",        // immediate | next_quarter | next_2_4_quarters (codex 채택)
  "source_grade": "B",                // S(IR·공시 원문) A(정부·산업 통계) B(신뢰 언론) C(리포트 요약) D(커뮤니티·루머) (codex 채택)
  "title": "...",
  "raw_quote": "원문 인용 — 사실",
  "interpreted_signal": "LLM 해석 — 원문과 반드시 분리 저장 (codex 원칙 채택)",
  "numeric": {"value": 1.3e15, "unit": "tokens/month"},  // 발표 수치 있으면
  "url": "...", "source": "reuters.com"
}
```

답변 생성 규칙 (codex 채택): S/A급 근거가 있으면 B/C/D급보다 우선,
D급만 있으면 "루머/미확인" 표기, 영향 해석에는 반드시 경로(edge)를 붙임.

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
| 반도체 산업 통계 | D(검증) | WSTS 월간 매출(3MMA), SIA, SEMI 장비 billings | 월간 | codex D축 채택 — A/B/C 신호가 실제 수급으로 이어졌는지 검증하는 층 |

토큰 지표의 질적 신호 (codex C-2 채택 — 총량만이 아니라 **구성**이 메모리 수요를 결정):
output 토큰 비중(디코드 단계가 메모리 대역폭 부담↑), 컨텍스트 길이/캐시 가격
(KV 캐시 = 메모리 용량 부담), thinking 토큰(보이지 않는 수요), rate limit·
"capacity constrained" 발언(공급 부족의 정성 신호). OpenRouter 스냅샷에서
모델별 컨텍스트 윈도·캐시 단가도 함께 저장하면 추가 비용 없이 커버됨.

파생 지표 1개만 계산해 둔다: **토큰 총지출 방향** = 사용량 성장률 + 단가 변화율.
단가 하락이 "효율화(메모리 악재)"인지 "가격 내려도 총지출 증가(호재)"인지를
이 하나로 구분 — C→A 엣지 판정의 정량 근거.

저장: `storage/rag/memory_sector/metrics/{지표명}.jsonl` (1줄 = 1일 관측치).

### 2-3. 조합 지표 — 단독이 아니라 겹쳐 봐야 인사이트가 나오는 것들

**선행 사슬** (같은 AI 수요가 시차를 두고 단계별로 관측됨 — 사슬이 어디서
끊기는지로 "노이즈 vs 추세" 판정):

```
C 토큰 사용량(일별) → B capex 가이던스(분기) → 대만 서버 ODM 월매출(월별)
 → 한국 반도체 수출 10일 통계(월 3회) → A 분기 실적(분기)
```

| 지표 | 소스 | 주기 | 왜 |
|---|---|---|---|
| 대만 서버 ODM 월매출 (콴타·위스트론·인벤텍 등) | 대만 상장사 월매출 의무공시 | 월별 | AI 서버 조립 = 메모리 실수요 직전 단계. 분기보다 3배 빠름 |
| TSMC 월매출 | 동일 제도 | 월별 | A' 신호를 분기 대신 월 단위로 |
| 한국 반도체 수출 10일 통계 ✅ | **관세청 공공데이터 오픈 API** — 「(수출/수입) 주요품목별 10일 단위 잠정치」, 반도체가 10대 품목에 별도 항목. 1~10일→11일, 1~20일→21일, 월전체→익월 1일 공개 (2026-07-06 실재 검증) | 월 3회 | 삼전·하이닉스 매출의 최선행 공개 프록시. 수입 API로 반도체 장비 수입도 |
| **반도체 수출 비중** (파생) | 위 반도체 수출 ÷ 전체 수출 | 월 3회 | 한국 경제 내 반도체 사이클 위치를 단일 숫자로 |
| 메모리사 재고일수(DIO) | 분기 재무제표 (재고÷매출원가) | 분기 | 재고 감소 시작 = 업사이클 초입 (역사적 패턴) |
| 장비 발주 (ASML 수주잔고, AMAT·램리서치 매출) | 실적발표 | 분기 | 증설→6~12개월 뒤 공급 증가 — **공급 과잉을 미리 보는** 유일한 축 |
| B 건설중자산 (construction in progress) | 분기 재무제표 | 분기 | capex 실적치보다 앞선 미래 지출 신호 |

**괴리(divergence) 지표** — 수집한 시계열 두 개를 빼서 만드는 파생값 (P2 대시보드에서 계산):

1. **현물가 − 고정거래가 스프레드**: 현물 > 계약 = 다음 분기 계약가 인상 예고 (선행 호재)
2. **B의 말 vs 돈**: capex 가이던스(카드) vs 실적치(지표) 괴리 — 말만 앞서면 경고
3. **주가 vs 사슬 괴리**: 사슬 지표 상승 중인데 A 주가 하락 = 원인이 발언(카드)
   → "과민반응" 후보로 태깅. 애플 발언·메타 GPU 사례가 이 유형인지 사후 검증 가능
4. **이벤트 주가 반응 자동 계산** (codex E축 채택): magnitude≥2 카드마다
   당일/3일/5일 A 종목 수익률을 자동 기록 → 스피커별·이벤트유형별 반응 이력의 원료

정확한 수집 URL/API는 P1 구현 시 검증 (공시 제도 자체는 장기 존속 확실,
2026-07-06 기준 엔드포인트 미확인 상태임을 명시).

### 2-4. 소스 확장 — 지표/뉴스/스피커 3분류 (yvon 프레임)

**스피커 (발언을 뉴스 경유가 아니라 원문으로)**

- 이벤트 카드 스키마에 `speaker` 필드 추가 (없으면 null). 스피커 레지스트리 고정:
  젠슨 황(NVDA), 샘 올트먼, 다리오 아모데이, 나델라, 피차이, 저커버그, 팀 쿡,
  리사 수, 곽노정(하이닉스), 전영현(삼성), C.C. Wei(TSMC)
- **실적 콜 트랜스크립트** (분기): 회사 IR + 무료 트랜스크립트 사이트(구현 시 검증).
  Q&A의 메모리 조달·capex 발언이 뉴스보다 빠르고 왜곡 없음
- **스피커별 발언→주가 반응 이력**: speaker 필드 × 주가 시계열 조합으로
  "이 사람 발언은 평균 n일/±x% 반영" 산출 — P2 대시보드 파생 지표
- **컨퍼런스 캘린더** (GTC·Computex·CES·I/O·Build): 해당일 수집 강도 상향

**뉴스 (검색 그물 → 직구독 수도관)**

- **공시 API (최우선 추가)**: DART(한국 전자공시, 무료 공식 API) + SEC EDGAR(무료).
  시설투자·공급계약·실적의 원천. 관련성 판정 불필요(공시는 100% 관련),
  뉴스보다 선행. 카드 `event_type`에 `filing` 추가
- **전문 매체 RSS 직구독**: TrendForce 보도자료, DigiTimes, SemiAnalysis,
  더일렉, 전자신문 — brave 검색 보완, 무료·안정
- **SaveTicker** (yvon 추가, 2026-07-06 실측 검증): 한국어 실시간 글로벌 금융 뉴스
  요약 서비스. 수집은 **2단 무인증 호출**:
  ① `api.saveticker.com/api/news/list` — 신규 감지용. 비로그인 시 본문 83자 미리보기
  (전문은 로그인 필요), 제목+미리보기로 관련성 1차 필터. `search=` 파라미터 동작
  ② `api.saveticker.com/api/news/detail/{id}` — **무인증 전문 제공** (실측: 본문 블록
  전체 + `tickers` 종목 매핑 + `tags` + `content_labels`) — 관련 항목만 호출
  유용한 필드: `source`(로이터 등 원 출처 → 등급 매핑), "(카더라)" 라벨(→ D급 강등),
  `vote_stats`(국내 투자자 호악재 투표), `tickers`(엔티티 매핑 제공됨).
  **비공식 API 주의**: 저강도 폴링(10분+), 깨지면 웹 경유 강등, 원문은 내부 보관만

**지표 (달력)**

- **실적 캘린더**: A·B 종목 다음 실적발표일 → 대시보드 "다음 촉매 D-n" 표시,
  카드 해석 맥락(실적 직전/직후)

**의도적 제외**: X(트위터) 직접 수집(API 유료, 중요 트윗은 뉴스가 받아씀),
애널리스트 목표주가·공매도 잔고(3축 인과 모델 밖).

### 2-5. 무료 대체 스택 — 유료 인사이트의 ~80%를 무료로 재구성

| 유료가 주는 것 | 무료 경로 | 등급 | 한계 |
|---|---|---|---|
| TrendForce 가격 데이터시트 | **TrendForce 보도자료** (분기 방향+% 범위 정량 공개) + 국내 언론의 월간 고정거래가 보도 | A/B | 주간 정밀도·세부 품목 없음 |
| SemiAnalysis 유료 리포트 | 무료 공개 글 + **인용 추적 쿼리** (`SemiAnalysis memory HBM` 등 — 핵심 수치는 언론이 며칠 내 인용) | B | 시차 며칠, 조각 정보 |
| 기관용 리서치 | **국내 증권사 반도체 리포트** — 한경컨센서스·네이버 금융 무료 공개, TrendForce/Omdia 수치 인용 (P1에서 접근 경로 검증) | C | 리포트 자체가 2차 가공 |
| HBM 수요·가격 추정 | **실적 콜 원문** (마이크론 HBM 매출·가이던스, 하이닉스 완판 발언) — 유료 리서치의 원료 | S | 분기 주기 |
| AI 컴퓨트 추세 | **Epoch AI** (연구기관, 데이터셋 무료 공개) | A | 장기 추세용, 단기 신호 아님 |

무료로 정말 안 되는 것: ① 주간 세부 품목별 가격 레벨, ② HBM 공급사별 출하·가격
추정치. → **P1은 무료 스택 전체 구축, 유료(§6-1)는 사용해보고 결정.**

### 2-6. 자동화 필터 — P1 파이프라인은 아래만으로 구성 (사람 개입 0)

**✅ 완전 자동 (전부 무료)**: OpenRouter API(토큰 사용량·단가) / yahoo(주가·SOX·
분기 재무: capex 실적·DIO·건설중자산) / DART·EDGAR(공시) / brave 쿼리 매트릭스
(+SemiAnalysis 인용 추적) / 전문지 RSS / SaveTicker JSON API / Epoch AI / toss 피드

**✅ 완전 자동 추가**: 관세청 10일 수출/수입 잠정치 오픈 API (반도체 별도 품목,
공공데이터포털 무료 키 — 2026-07-06 검증) / SaveTicker 캘린더 API(매크로 이벤트)

**🟡 자동 가능, P1에서 검증 또는 깨짐 대비**: 대만 월매출 공시(정형, 엔드포인트 검증),
TrendForce 공개 차트 스크랩(깨지면 보도자료 경유로 자동 강등),
한경컨센서스 리포트(스크랩 검증), WSTS/SIA 보도자료

**❌ 수동 개입 필수 → 파이프라인 의존성에서 제외** (수동 등록 입구의 옵션일 뿐):
TrendForce Platinum 파일, 실적 콜 트랜스크립트, SemiAnalysis 유료
뉴스레터(결제·메일함 세팅 선행 + 전문 수신 여부 미확정)

블룸버그는 **목록에서 제거 (yvon 결정)** — 단독 보도는 통신사·SaveTicker가 몇 시간 내
릴레이하므로 일 2회 주기에서 무의미. 보완 규칙: SaveTicker 본문은 원문의 **한국어 요약**
이라 원문 직접인용(S급 raw_quote)이 필요한 magnitude 3 카드는 SaveTicker로 **감지** 후
brave로 원 기사 검색 → fetch_body로 원문 인용 **보강**하는 2단 처리.

원칙: **✅+🟡만으로 3축 모델 완성** — 수동 항목은 품질 부스터, 필수 아님.

### 2-7. SaveTicker — P1 정식 1차 뉴스 소스 (구현 스펙, 2026-07-06 실측 확정)

역할: brave 쿼리 매트릭스와 **병렬**로 도는 P1 1차 뉴스 수집원. 한국어 실시간
글로벌 금융 뉴스라 국내 투자자 관점 + 글로벌 커버리지를 동시에 얻음. 무인증.

수집 루프 (스케줄러 주기마다):
```
1. GET api.saveticker.com/api/news/list?page_size=50   (+ /top-stories 별도 1콜)
   - 검색 인덱스가 실시간이 아님(실측 확인) → search= 의존 금지.
     최신 목록을 통째로 받아 last_seen_id 이후 신규만 취함(증분)
2. 로컬 필터: 제목+83자 미리보기에 엔티티/키워드 매칭 → 후보 선별
   (기존 _clean_pool 도메인 필터는 SaveTicker엔 불필요 — 자체 편집물)
3. 후보만 GET /api/news/detail/{id} → 전문 + tickers + tags + source + vote_stats
4. sonnet 판정(§3-3 공통) → 카드화
```

필드 활용:
- `source` → 출처 등급 매핑 (로이터/블룸버그=B, 회사발표 인용=참고)
- 제목 `(카더라)` 라벨 → **D급 자동 강등** (자체 루머 표기 재활용)
- `tickers` → 엔티티 자동 매핑 (있을 때. 위 금값 기사처럼 빌 수 있음 → 제목 파싱 폴백)
- `vote_stats` (positive/negative 투표) → 국내 sentiment, toss 피드 보완
- `news_group_id` → SaveTicker 자체 중복 그룹 (dedup 힌트)

운영 안전장치 (비공식 API 전제):
- **저강도 폴링** 10분+ 간격, User-Agent 명시, 목록 1콜+후보 detail만(전량 detail 금지)
- 4xx/스키마 변경 감지 시 → 자동 비활성 + collector_status에 `saveticker: degraded` 기록,
  brave·RSS가 커버 (SaveTicker는 강화재지 단일 장애점 아님)
- 증분 커서(last_seen_id) 영속화로 재기동 시 중복 detail 호출 방지

**캘린더 API도 무인증 접근 가능** (2026-07-06 실측): `GET /api/calendar/events?
start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` → 매크로 경제 이벤트 목록.
필드 `event_date`(시각 포함)·`title`·`content`·`color`, **제목에 중요도 별점(★~★★★)**
내장 → 고중요 이벤트만 필터해 대시보드 "다음 촉매 D-n"(§2-4 실적 캘린더 항목)에 사용.
연준 인사 발언 일정도 포함. 스케줄러가 매일 향후 2주치를 당겨와 갱신.
※ 지금 확인된 건 **매크로 캘린더** — 개별 종목 실적발표일(종목 필터) 지원 여부는 P1에서 확인.

## 3. 수집→판정→저장 파이프라인

```
[스케줄러: 하루 2회]
  1. 뉴스 수집 (병렬 소스 → 공통 풀):
     a. SaveTicker 증분 (§2-7): list 폴링 → 로컬 필터 → detail 전문
     b. brave 쿼리 매트릭스 (geo 라우팅)
     c. 전문지 RSS
  2. _clean_pool: 커뮤니티 도메인 제거 + URL dedup + 기존 카드와 dedup
     (SaveTicker는 news_group_id·source 기준 교차 dedup)
  3. sonnet 배치 판정 1콜: 각 아이템 → {관련여부, axis, edge, event_type, direction, magnitude, summary}
     - "인과 엣지에 매핑 불가"면 drop → 관련성 필터가 곧 판정 단계
     - news_summary 스테이지의 구조화 출력 패턴 재사용
  4. 상위 magnitude 카드만 fetch_body로 본문 발췌 보강 (SaveTicker 요약 → 원문 인용 승격)
  5. 저장: storage/rag/memory_sector/cards/YYYY-MM/*.json + index.jsonl(1줄=1카드)
  6. 지표 수집 (레이어 2): OpenRouter 사용량·단가 스냅샷, TrendForce 스크랩,
     yahoo 주가/SOX → metrics/*.jsonl append (지표별 독립 try/except — 하나 깨져도 나머지 수집)
```

비용: 회당 뉴스 ~60건 판정 = sonnet 1~2콜(입력 ~10K 토큰) ≈ **$0.05/일 미만**.

### 유료 콘텐츠 인제스천 경로 (크롤링이 아니라 "배달 경로" 사용)

| 소스 유형 | 경로 | 구현 |
|---|---|---|
| 뉴스레터형 (SemiAnalysis, 블룸버그 뉴스레터) | **전용 메일함 구독 → IMAP 폴링** | HTML 파싱 → sonnet 판정 → 카드. 로그인·봇차단 문제 원천 회피 |
| 리포트형 (TrendForce Platinum 주간/월간 데이터시트) | **파일 다운로드 → inbox/ 폴더 감시** | 엑셀/PDF 파서로 가격 테이블 추출. 처음엔 수동 다운로드(월 수 건), 자동 로그인은 후순위 |
| 블룸버그 본문 | **크롤링 금지** (약관·봇차단) | 이메일 뉴스레터로 흡수 + 수동 클리퍼(읽다가 저장 버튼). 대형 뉴스는 어차피 통신사가 받아써 brave에 걸림 |
| 기타 인증 필요 소스 | 세션 쿠키 헤드리스 (최후 수단) | 깨지기 쉬움 — 위 경로 불가 시에만 |

라이선스 원칙: 원문 전문은 내부 보관(documents/)까지만, 타 사용자 노출 카드에는
수치·방향·자체 요약만.

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

1. **P1 수집기**: 뉴스 수집(**SaveTicker §2-7** + brave 쿼리 매트릭스 + RSS) + 판정 +
   카드 저장 + **지표 시계열 수집(레이어 2)** + 스케줄러
   + **수동 URL/문서 등록 입구** (codex MVP1 절충 — IR 자료·트랜스크립트는 자동화가 까다로우니
   수동 등록으로 시작, 원문은 `documents/`에 보관하고 카드가 참조). 산출물: index.jsonl + metrics/*.jsonl
2. **P2 대시보드**: 카드·가격 읽어 4-1 뷰 렌더 + 이벤트 주가 반응 자동 계산
3. **P3 QA 연결**: 질문 파이프라인에 구조화 검색 + `sector_rag` 레이어(raw RAG 노출,
   **반대 근거(contradictions) 블록 포함** — codex 채택, 기존 엔진의 반대 시나리오 사상과 일치)
4. **P4 (후순위)**: 임베딩 검색, D램 가격 직접 소스, 판정 피드백 루프,
   **Thesis Monitor**(투자 가설별 강화/약화 근거 추적, codex 화면 5) + 영향 경로 그래프(codex 화면 2)

API는 계약 우선 (codex 채택, 리포 컨벤션과 일치 — openapi.yaml에 먼저 정의):
`GET /api/memory-board`, `GET /api/memory-events`, `GET /api/memory-metrics`,
`POST /api/memory-documents`(수동 등록), `POST /api/memory-query`(응답에 answer + rawEvidence + contradictions)

## 6. 미해결 질문 (codex·yvon 논의 필요)

1. 유료 소스 결제 (2026-07-06 검증) — 품질 우선이면 권고 조합:
   **SemiAnalysis 뉴스레터**(C→B→A 인과 사슬을 그대로 정량화하는 유일한 리서치,
   HBM 세대별 가격·하이퍼스케일러 메모리 지출 추정의 업계 원천. 풀 Memory Model은
   기관 전용이라 뉴스레터가 진입점) + **TrendForce DRAMeXchange Platinum**
   (주간 현물/고정가 + 월간 데이터시트 — 파생 지표 정밀도의 원판).
   Omdia/TechInsights는 세컨드 오피니언 용도라 보류, IDC/Gartner는 헤드라인 무료라 불필요.
   라이선스 주의: 유료 자료는 수치·방향·자체 요약만 저장 (원문 재배포 금지 — 멀티유저 앱이므로)
2. API 키 발급 필요(둘 다 무료): OpenRouter(데이터셋), data.go.kr 공공데이터포털(관세청 수출 통계)
3. 스케줄러 위치 — engine 내 APScheduler vs 시스템 cron vs node(server.mjs) 쪽?
4. ~~엔비디아를 어디 두나~~ → **해소 (codex 프레임 채택)**: GPU/ASIC은 별도 엔티티 축이
   아니라 인과 경로의 중간 노드 (C→B→**GPU/ASIC**→HBM→A). 엔비디아 뉴스는 A' 축 카드로 수집
5. 대시보드 진입점 — 기존 index.html 내 탭 vs 별도 페이지?
6. codex와 분업 경계 제안: **claude = engine(P1 수집·판정·검색 API), codex = UI(P2·P3 렌더)** — 역제안 환영

## 7. codex 계획 교차 검토 (2026-07-06, docs/memory-rag-plan_codex.md 기준)

**합의 확인**: TSMC를 A에서 분리(양쪽 독립 도출 — 코덱스 "공급망/패키징 축" 명칭 채택),
raw RAG 기본 노출, 원문·해석 분리, 커뮤니티=D급 최하위.

**codex에서 채택** (본문 반영 완료): 출처 등급 S~D + 우선 규칙, memory_segment
(HBM/DRAM/NAND 구분), time_horizon, raw_quote/interpreted_signal 분리,
이벤트 주가 반응 자동 계산(1d/3d/5d), D축 산업 통계(WSTS/SIA/SEMI),
GPU 클라우드 엔티티, 토큰 질적 신호(output 비중·KV 캐시·thinking 토큰),
수동 ingestion 입구, API 계약 우선, contradictions 블록, Thesis Monitor(P4).

**codex가 가져가면 좋을 것** (이쪽 계획에만 있음):
- **OpenRouter 공개 데이터셋 API** — codex는 "전세계 token usage 공식 집계 거의 없음"에서
  추정으로 갔지만, OpenRouter가 일별 모델별 실측치를 무료 제공 (2026-07-06 검증, §2-2).
  추정(TokenDemandEstimate)보다 실측 우선
- 선행 사슬 지표: 대만 ODM **월매출**, 한국 반도체 수출 **10일** 중간집계
  (codex는 월간으로 잡음 — 10일 집계가 3배 빠름), DIO, ASML 수주
- 스피커 레지스트리 + 발언→반응 이력
- DART/EDGAR 공시 API (codex는 IR 페이지 크롤 — 공시 API가 더 안정적)
- 기존 엔진 재사용점: `_clean_pool`, geo 라우팅, news_summary 구조화 출력 패턴, 비용 산정

**미채택 (이유)**:
- 4레이어 인덱싱(Document/Chunk/Event/Thesis) 전체 — 1단계엔 과함.
  Document(원문 보관) + 카드(이벤트) 2층으로 시작, Chunk는 임베딩 도입(P4) 때
- MVP1을 완전 수동으로 시작 — 뉴스·지표 자동 수집은 기존 인프라로 비용이 거의 없어
  자동+수동 병행이 낫다 (절충안을 P1에 반영)

### 7-2. codex 2차 업데이트 반영 (codex가 2레이어로 수렴 + 신규 소스)

codex가 이벤트 카드+지표 시계열 2레이어 방향을 수용. 추가로 채택:
- **7종 데이터 분류** (지표/뉴스/스피커/공시/가격표/공급망/시장반응) — 카드 `event_type`을
  이 축으로 확장(speaker·product_policy·market_reaction·filing 추가)
- **신규 자동화 가능 무료 소스** (이 원칙에 정확히 부합 — P1 편입, 엔드포인트만 검증):
  - **Stanford DAM Memory Prices** — DRAM/HBM/NAND **장기 가격 CSV 다운로드**.
    §6-1 유료 갭(가격 시계열)을 상당 부분 무료로 메움
  - **Epoch AI AI Chip Components** — AI 칩designer별 HBM/CoWoS 소비 추정 (HBM 수요 proxy)
  - **TWSE/MOPS 대만 월매출** — ODM·TSMC 월매출 공식 공개 데이터
  - **SEC EDGAR API** — 하이퍼스케일러 capex 실적·PP&E·감가상각 (B축 "말 vs 돈")
- **조합 지표 2개 추가**: `HBM Tightness Index`(계약·인증·ASP·sold-out 발언 조합),
  `Supply Overbuild Risk`(HBM 증설+장비 수주+capex 급증 조합 — 사이클 꼭대기 경보)
- **유료 우선순위 재정렬** (codex 4-1): TrendForce/Omdia가 1순위(가격·출하·capacity),
  SemiAnalysis/Bloomberg는 해석 보강용 3순위. 단 자동화 원칙상 **Stanford DAM+Epoch+
  TWSE+EDGAR 무료 조합으로 시작**, 유료는 HBM ASP/vendor share가 정말 필요할 때
