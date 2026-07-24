# Case-Memory Architecture Research — Temporal KG vs Structured-JSONL + Rules

작성: Claude (deep research), 2026-07-21
대상: 메모리 반도체 데일리 리포트가 API처럼 질의할 "역사적 금융 케이스 메모리"의 아키텍처 결정

> **어떻게 읽나 (jargon 없이):** 이 문서는 "과거 사이클/위기를 어떻게 저장하고 꺼내 쓸 것인가"를 묻는다.
> 후보는 4가지 — ① 지금 우리가 쓰는 **구조화 JSONL**(키워드+메타데이터 필터), ② **벡터**(임베딩 유사도),
> ③ **그래프 DB**(엔티티·관계를 노드·엣지로), ④ **하이브리드**(BM25+벡터+리랭크). 결론부터 말하면,
> 우리 규모(케이스 수십 건)에서는 그래프 DB·전용 벡터 DB는 **오버엔지니어링**이고, 지금의
> 구조화 JSONL + 룰(플레이북) 패턴을 **시간 인식(bitemporal)** 케이스 레코드로 확장하는 것이
> 증거상 가장 방어 가능한 선택이다. 그래프/임베딩은 트리거 조건이 충족될 때 단계적으로 추가한다.

---

## 0. Executive Summary

1. **그래프 DB(Graphiti/Zep)의 진짜 가치는 "bitemporal 비손실 무효화 + 멀티홉 순회"** 딱 하나다. 이건
   실재하고 벡터 스토어가 못 하는 기능이 맞다. 하지만 회의적 증거가 강하다: 그래프 RAG는 **~10만 문서
   이상 + 멀티홉 질의가 상시 패턴**일 때나 값을 한다. 수십 건 규모에서는 인제스천마다 여러 번의 LLM 호출과
   Neo4j 운영 비용을 회수하지 못한다. Letta가 **대화를 파일에 저장하고 `grep`만 줘서 LOCOMO 74%**를 찍은
   사례가 이 판단의 결정적 근거다.
2. **모든 에이전트 메모리 "SOTA" 벤치마크는 벤더 자가측정**이다. Zep의 LOCOMO 84% 주장은 Mem0 CTO가
   분모 조작(카테고리 5 제외)을 지적해 58.4%로 정정됐고, Zep는 조용히 "24%p 앞선다"를 "10%p"로 낮췄다.
   이 분야에 **중립 리더보드는 없다**. 아키텍처 주장(bitemporal·하이브리드 검색)은 코드로 검증되지만,
   랭킹 주장은 살아남지 못한다.
3. **OpenAI의 "Temporal Agents with Knowledge Graphs" 쿡북조차 프로토타입은 SQLite로 시작**하라고 하고,
   그래프 DB를 처음부터 강제하지 않는다. 방법론(statement 추출 → 시제 분류 → triplet/entity 추출 →
   Invalidation Agent로 비손실 무효화 → 멀티홉 tool 검색)은 우리 카드 파이프라인과 거의 동형이다.
4. **소규모 케이스 코퍼스에서는 알고리즘보다 메타데이터 품질이 지배적**이다. 메타데이터 필터가 MRR을
   0.12 → 0.68로 끌어올리는 반면(k=5), 리랭킹은 "보조"였다. Willison은 446개 문서를 SQLite에서 순수
   코사인으로 브루트포스했다. 수십 건이면 알고리즘은 무의미하고, **메타데이터 스키마와 리랭크(구조적) 단계**가
   전부다.
5. **CBR + LLM은 살아있는 연구 패턴이지만 금융 프로덕션 실적은 사실상 전무**하다. 진짜 중요한 발견은
   인지과학의 **구조적 vs 표면적 유사도** 구분이다. "이건 2018 메모리 글럿 같다"는 **구조적** 주장(과잉공급→
   재고 축적→가격 붕괴→마진 압박)인데, 키워드·임베딩 검색은 **표면** 매처라 "메모리"·"2018"이라는 단어만
   공유하는 가짜 유사를 반환한다("mere-appearance" 함정). 고전적 해법은 **MAC/FAC** — 값싼 표면 필터로
   후보를 좁히고, 비싼 구조적 정렬로 리랭크. 우리 파이프라인의 "필터 → 구조적 리랭크"가 정확히 이 구조다.
6. **LLM이 서사에서 뽑은 if/then 룰은 검증된 룰이 아니라 "가설 깔때기"로만 취급**해야 한다. LLM은
   인과에 유창하지만 인과를 확립하지 못한다("Causal Parrots"). 최악의 함정은 **파라메트릭 lookahead 편향** —
   2024년에 학습된 LLM은 2018–2020년이 어떻게 끝났는지 이미 "안다". 이 누수는 **모델 가중치 안에** 있어서
   어떤 DB도 못 막는다. 컷오프 매칭 모델 + 포인트인타임 입력 + Deflated Sharpe/PBO 없이는 룰 신뢰도가 오염된다.
7. **포인트인타임(bitemporal) 규율은 필수**다. 핵심은 **valid-time이 아니라 transaction-time(=`knowable_at`)
   as-of 필터**다. "Q1에 대해 참인 것"이 아니라 "T 시점에 우리가 알 수 있었던 것"으로 검색해야 백테스트가
   미래를 소비하지 않는다. 우리 플레이북 스키마에 이미 `asOf` 필드가 있으니 씨앗은 심어져 있다.

**한 줄 권고:** 메모리-사이클 케이스 레이어는 **진짜 temporal KG가 아니라, 구조화 JSONL + 룰 패턴의
시간 인식 확장**으로 간다. Document(원문 보관) + Case Card(시간축 있는 이벤트/에피소드) 2층을 유지하고,
검색은 **메타데이터 as-of 필터 → BM25 → (임베딩 브루트포스, 선택) → 구조적 리랭크**로. 그래프/임베딩은
아래 §11의 트리거가 켜질 때만 추가한다.

---

## Q1. Temporal KG 에이전트 메모리 — 현 상태와 언제 값을 하나

### 모델: episodes → entities → edges
**Graphiti**가 오픈소스 엔진, **Zep**이 그 위의 상용 매니지드 플랫폼이다. 데이터 모델은 동일:
- **Episodes** = 원본 인제스천 층(메시지/JSON/텍스트) = 프로버넌스. 파생된 모든 fact는 episode로 역추적된다.
- **Entities**(노드) = 사람/제품/개념. 새 episode가 올 때마다 요약이 변한다.
- **Facts/Edges** = `(Entity)-[Relationship]-(Entity)` 트리플. 엣지는 라벨뿐 아니라 "하이드레이션된"
  자연어 문장("Alice is the sibling of Bob")도 저장하고, **시맨틱 검색은 이 문장 위에서** 돈다
  (Graphiti 개발자가 HN에서 확인: <https://news.ycombinator.com/item?id=41445445>).
  출처: <https://github.com/getzep/graphiti>, <https://www.getzep.com/product/open-source/>.

### Bitemporal 모델 (진짜 차별점)
엣지마다 **두 개의 독립 시간축**:
- **Valid time** (`valid_at`/`invalid_at`): 그 fact가 **세계에서** 참이었던 때.
- **Transaction/ingestion time**: 시스템이 그것을 **알게 된** 때 (source episode에 연결).

모순 정보가 오면 옛 엣지를 **삭제가 아니라 무효화**한다 — "지금 참인 것, 또는 과거 임의 시점에 참이었던 것을
질의". 이건 플랫 벡터 스토어가 진짜로 못 하는 실재 기능이다. Zep 논문: <https://arxiv.org/abs/2501.13956>
(Rasmussen et al., 2025-01).

### 검색: 하이브리드 + 리랭킹
Graphiti는 세 신호를 융합: (1) 임베딩 코사인, (2) BM25 풀텍스트, (3) 그래프 순회(BFS). 리랭킹은
**LLM 호출이 아니라 그래프 거리/근접**으로 — 질의 시점 지연·비용을 낮추려는 의도적 선택. 벤더 보고 지연
~155ms(LOCOMO)/~162ms(LongMemEval) **평균**(P95 아님, 벤더 자가측정).

### 성숙도·라이선스·백엔드·비용 (2026)
- **라이선스: Apache-2.0** (Graphiti). 진짜 관대한 오픈소스. <https://github.com/getzep/graphiti>,
  교차확인 <https://atlan.com/know/zep-vs-mem0/>.
- **성숙도**: 2026 중반 ~v0.29.x, ~29k stars, ~196 릴리스, MCP 서버 + FastAPI REST 동봉. 주로 Python.
- **백엔드**: Neo4j(주력, 5.26+), FalkorDB(1.1.2+, 임베디드 "Lite" 포함), Amazon Neptune.
  **Kuzu는 있으나 deprecated 표기**(상류 미유지). 즉 "Kuzu=경량 임베디드" 얘기는 2026 기준 죽었고,
  경량 경로는 이제 FalkorDB-Lite다.
- **인프라 부담**: 진짜 그래프 DB(Neo4j) + episode마다 여러 LLM 추출 호출. **쓰기 경로가 비싸다**
  (statement 추출 + 시제 추출 + triplet/entity 추출). 이게 정직한 비용 — 쓰기·LLM 무거운 인제스천.
- **Zep 가격**: 크레딧 기반, 그래프는 ~$25/mo Flex 티어부터 (<https://atlan.com/know/zep-vs-mem0/>).

### CRITICAL — 그래프 DB는 언제 값을 하나 (회의적 근거)
회의 증거가 강하고 다출처다. **수십 건 규모에서 temporal KG 메모리는 오버엔지니어링.**
- **외부 스토어 임계**: 외부 벡터/그래프 DB는 **"10억 벡터 규모"**에서나 운영비를 정당화하고, 통상 에이전트
  메모리(테넌트당 수십만~수백만 벡터)는 **단일 Postgres + pgvector가 별도 벡터 DB보다 낫고 운영비도 낮다**
  (<https://hindsight.vectorize.io/blog/2026/05/12/case-against-external-vector-dbs-agent-memory>).
- **GraphRAG 임계**: 실무 컨센서스 — 그래프 RAG는 **~10만 문서 이상 + 멀티홉/교차 질의가 상시 패턴**일 때만
  값을 한다. 그 아래에서는 벡터 검색이 "엔지니어링 비용의 몇 분의 일로" 정확도 대부분을 잡는다
  (<https://cognilium.ai/blogs/rag-vs-graphrag>).
- **가장 날카로운 반례**: **Letta가 대화를 파일에 저장하고 에이전트에 `grep`만 줘서 LOCOMO 74.0%**를
  기록 — 정교한 그래프 시스템과 대등하거나 능가
  (<https://essays.bloo-mind.ai/posts/2026-05-20-mem-eval/>). 파일+grep이 74%면, 수십 건에 temporal
  그래프의 한계 가치는 정당화하기 매우 어렵다.
- **비결정성 비판(HN)**: LLM 추출 스키마는 자체 온톨로지를 안 주면 "비결정적 LLM이라 매번 달라진다";
  온톨로지 만들기는 "엄청난 노동 + 무수한 엣지케이스". 개발자도 커스텀 스키마 지원이 아직 to-do라고 인정
  (<https://news.ycombinator.com/item?id=41445445>). **KG 메모리의 진짜 숨은 비용은 저장이 아니라
  추출 품질·일관성**이다.

### Zep "SOTA" 주장 — 코로보레이션 or 벤더 편향?
**심하게 벤더 편향. 헤드라인 수치는 전부 의심.**
- **DMR 94.8% vs MemGPT 93.4%** — Zep 자가측정, 1.4점차. Zep 스스로 나중에 DMR이 너무 쉽다고 인정.
- **LongMemEval "최대 18.5% 향상, 90% 지연 감소"** — Zep 자가보고 (<https://arxiv.org/abs/2501.13956>).
- **LOCOMO 분쟁이 벤더 편향의 결정타**: Zep가 "84%" 블로그 → Mem0 CTO가
  <https://github.com/getzep/zep-papers/issues/5>에서 **"카테고리 5 질문을 분모에서 제외하면서
  분자에는 카테고리 5 정답을 포함"** = ~25점 부풀림을 지적, 정정치 **58.44% ± 0.20**. Zep는 조용히
  "24%p 앞선다"를 "10%p"(75.14%)로 수정.
- **메타 비판이 압권** (<https://essays.bloo-mind.ai/posts/2026-05-20-mem-eval/>): LOCOMO 정답키
  오류율 ~6.4%(천장 ~93.6%이라 그 이상은 "수학적으로 불가"); LLM 심판이 **의도적 오답의 62.81%를 정답 처리**;
  LongMemEval-S는 ~115K 토큰이라 "메모리가 아니라 컨텍스트 윈도 관리를 측정"; 그리고
  **"모든 시스템이 자기가 고른 벤치마크에서 SOTA라고 보고한다."** 결론: *"같은 시스템이 누가 돌리느냐에 따라
  38%도 92%도 나오는 분야는 신뢰할 벤치마크가 있는 분야가 아니다."*

> **증거 얇음/벤더 편향 플래그:** 이 분야 에이전트-메모리 벤치마크 수치는 거의 전부 벤더 자가측정이고 깨끗한
> 제3자 리더보드가 없다. Zep의 *아키텍처* 주장(bitemporal·하이브리드·질의 시점 LLM 없음)은 코드로 검증되고
> 견고하나, *랭킹/SOTA* 주장은 독립 검증을 못 견딘다.

---

## Q2. OpenAI "Temporal Agents with Knowledge Graphs" 쿡북

**URL (둘 다 라이브):**
- 렌더: <https://developers.openai.com/cookbook/examples/partners/temporal_agents_with_knowledge_graphs/temporal_agents>
- 노트북: <https://github.com/openai/openai-cookbook/blob/main/examples/partners/temporal_agents_with_knowledge_graphs/temporal_agents.ipynb>

경로에서 보이듯 **"partners" 쿡북**(외부 파트너 공저, 2025-08 공개) — 그래프 접근에 약한 홍보 프레이밍이 있음.

### 구체적 방법
**1. 엔티티/관계 추출 (다단계·다중 LLM 호출):**
- `text-embedding-3-small` 기반 **시맨틱 청킹**(고정 윈도 아님).
- **Statement 추출**: LLM이 청크를 원자적 주–술–목 주장으로 분해, 대명사/약어 해소. 각 statement에
  `StatementType`(Fact/Opinion/Prediction)과 `TemporalType`(Static/Dynamic/Atemporal) 태깅.
- **Triplet & entity 추출**: 엔티티에 타입·설명, 술어는 **통제 어휘**(IS_A, HAS_A, LOCATED_IN,
  HOLDS_ROLE, PRODUCES…). 숫자값은 별도 `Numeric` 엔티티로.

**2. 시제 충돌 해소 / superseded 엣지 무효화:**
- statement마다 `valid_at`(+ 선택 `invalid_at`)을 별도 LLM 패스로.
- Static=시점, `valid_at`만, 거짓 안 됨 / Dynamic=양쪽 경계, 후속 모순 fact가 supersede / Atemporal=경계 없음.
- **"Invalidation Agent"**가 새 트리플을 기존 그래프와 비교, 모순 탐지, stale 엣지에 `t_invalid`·
  `invalidated_by` 표기 — **"비손실"**(옛 fact가 validity 창과 함께 질의 가능). Graphiti의 bitemporal
  무효화와 정확히 동형.

**3. 멀티홉 검색:** task-oriented(순차 서브태스크·고정 순회) / hypothesis-oriented(주장 → 확인/반박/진화)
두 플래너. 검색은 fixed/free-form/semi-structured **tool 호출**로 노출, 여러 연결된 fact를 걸쳐 추론.

### 구체적 권고
- **모델 티어링**: GPT-4.1로 프로토타입(정확도) → 프롬프트 안정되면 **4.1-mini/-nano**로 내리고 **distillation**으로
  품질 유지.
- **프로덕션 하드닝**: 선형 파이프라인 → **스테이지드 비동기 아키텍처**(단계별 큐 + 워커 풀); 엣지마다
  **수치 relevance 점수(recency × trust × query-frequency)** + **아카이빙 정책**으로 그래프를 lean하게;
  출력 검증(ISO-8601, 통제 어휘, 모델 기반 sanity); 드리프트 모니터.
- **저장**: 프로토타입은 **SQLite**("대규모엔 부적합"이라 명시), 프로덕션은 pgvector 기반 또는 그래프 DB
  (Neo4j). **처음부터 그래프 DB를 강제하지 않음.**

### 명시된 트레이드오프
- **토큰 비용이 헤드라인**: statement마다 여러 LLM 호출(추출+시제+triplet). 배칭·비동기로 일부 상쇄.
- 시맨틱 청킹 + 직렬 LLM 호출 지연, 병렬 워커로 완화.
- 복잡도: "프로토타입 → 프로덕션" 절 전체가 사실상 "나이브 선형 파이프라인은 확장 안 되니 큐·희소화·검증 등
  실제 인프라 엔지니어링이 필요하다"는 경고다.

> **핵심:** 벤더 툴(Graphiti/Zep)과 OpenAI 자체 쿡북이 **같은 방어 가능한 능력**으로 수렴한다 —
> **bitemporal 비손실 fact 무효화 + 멀티홉 순회**. "T 시점에 무엇이 참이었나" 추론과 교차문서 멀티홉이
> **규모 있게** 필요할 때 값을 한다. 수십 건이면 모든 회의 출처(Postgres-first, ~10만 문서 GraphRAG 임계,
> Letta의 file+grep 74%)가 그래프 + 다중 LLM 인제스천은 **오버엔지니어링**이라고 말한다.

---

## Q3. 금융을 위한 CBR / 유사(analog) 검색

### CBR + LLM은 2025–2026 살아있는 패턴인가? — 그렇다, 단 대부분 연구.
CBR의 고전 4단계(Retrieve → Reuse → Revise → Retain)가 RAG에 자연스럽게 맵핑되며 2024–2026 논문 클러스터가 있다.
- **CBR-RAG** (Wiratunga et al., arXiv:2404.04302, ICCBR'24) — 정전(canonical) "CBR+RAG" 논문(법률 QA).
  <https://arxiv.org/abs/2404.04302>
- **Review of CBR for LLM Agents** (arXiv:2504.06943, 2025-04) — 케이스 검색·적응·학습 수식 모델 + 프레임워크
  카탈로그(DS-Agent, CaseGPT, CBR-RAG). <https://arxiv.org/abs/2504.06943>
- **MCBR-RAG** (멀티모달, arXiv:2501.05030), **CBR for Driving** (arXiv:2506.20531),
  **CBR for Test Script Gen** (arXiv:2503.20576 — **Huawei Datacom 산업 배치** 보고, 드문 실배치 신호).

**금융 특화 유사추론 논문** (당신 유스케이스에 직결):
- **DeFine: Decision-Making with Analogical Reasoning over Factor Profiles** (arXiv:2410.01772, 2024-10, Tencent
  AI Lab 저자 포함) — 가장 관련. 케이스를 **"factor profiles"**(결정 관련 속성)로 표현, **표면 텍스트 유사가
  아니라 factor 매칭**으로 검색 → 명시적으로 구조 > 표면. **유사 예시 ~5개가 최적.** <https://arxiv.org/abs/2410.01772>
- **AD-FCoT** (arXiv:2509.12611, 2025-09) — 역사적 유사를 CoT에 주입. **증거 얇음/약한 결과 플래그**:
  유사 검색이 *수작업*(손으로 고른 2개), gain은 미미(54.92% vs 54.70%, +0.22pp). 프레이밍만 인용, 메커니즘은 X.
- **FinSrag / FinSeer** (arXiv:2502.05878, 2025-02) — "CBR" 라벨은 아니나 기능적으로 시계열 세그먼트 유사 검색.
  도메인 특화 리트리버 FinSeer가 **텍스트·전통 거리(순수 임베딩) 리트리버를 모두 능가** — "나이브 임베딩 검색이
  목적특화 유사 리트리버보다 못하다"는 금융 최강 증거. <https://arxiv.org/abs/2502.05878>

### 구조적 vs 표면적 유사 — 핵심 구분 (금융 유사에 직결)
수십 년 인지과학이 뒷받침하고, 금융에 직접 load-bearing:
- **Gentner Structure-Mapping Theory** (Cognitive Science 1983): 유추는 base 객체 간 **관계 시스템**이 target에도
  성립함을 나르는 것 — "관계가 박혀 있는 객체와 무관하게" 관계/인과 구조.
  <https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf>
- **"mere-appearance" 실패 모드**: 사람(과 나이브 리트리버)은 구조가 아니라 **표면 유사로 회상**한다 —
  "표면 특징(객체·행위자 정체성)을 공유하는 서술을 회상하는 소위 mere-appearance 회상의 우세."
  <https://courses.csail.mit.edu/6.803/pdf/finlayson.pdf>
  **금융에 직결:** 키워드/임베딩 검색은 *표면* 매처다. "이건 2018 메모리 글럿 같다"는 *구조적* 주장(과잉공급→
  재고 축적→가격 붕괴→마진 압박)인데, 표면 리트리버는 "메모리"·"반도체" 단어만 공유하는 2018 기사를 반환하고
  구조적으로 동형인 2015 유가 글럿·2001 광섬유 글럿을 놓친다. **plain 임베딩 RAG를 유사 케이스에 쓰지 말라는
  가장 강한 이론적 논거.**
- **고전 엔지니어링 해법 MAC/FAC** (Forbus, Gentner & Law, 1995) — "Many Are Called, Few Are Chosen":
  **2단계** 리트리버 — stage 1(MAC)은 값싼 *비구조적* 콘텐츠 벡터 내적(표면 필터), stage 2(FAC)는 살아남은
  소수에 대해 비싼 *구조적* 정렬(SME). <https://www.qrg.northwestern.edu/ideas/smeidea.htm>
  **아키텍처 핵심:** 임베딩/BM25 = MAC(표면 프리필터); 구조적/인과 리랭크 = FAC. 현대 하이브리드 RAG의
  "retrieve-then-rerank"가 관계 구조 없는 MAC/FAC이고, 최근 CBR-에이전트 논문은 정확히 이걸 재발명한다.

> **문헌 자체에 대한 반대 주의:** 구조 vs 표면 분리는 논쟁적이다. 회상 실험 결과는 "혼재" — 표면이 회상을 몰지만
> *일단 회상된 뒤 어느 유사가 유용한지는 구조가 결정*한다는 게 더 일관된 발견
> (<https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11724687/>). "구조적 검색이 무조건 낫다"는 미정 실증이며,
> **설계 prior**로 취급.

### 반대: 학술뿐인가, 실배치되나? CBR이 plain RAG를 이기나?
- **배치**: 대부분 학술, 얇지만 실산업 신호(Huawei arXiv:2503.20576). 리뷰 스스로 대부분 PoC이고 "상업 배치·실프로덕션
  언급 없음"이라 인정. **금융에 발표된 프로덕션 CBR은 사실상 없음.**
- **CBR이 RAG를 이기나?** 약하고 비일관. 통제 교차 벤치마크가 희소("comparative empirical studies are limited").
  가장 깔끔한 양성은 금융 인접 FinSeer, 가장 깔끔한 음성/null은 AD-FCoT(+0.22pp, 수작업 유사).
  **정직한 결론: "구조/factor 기반 유사 검색이 나이브 임베딩보다 낫다"는 중간 지지, "풀 CBR 사이클이 RAG를
  이긴다"는 근거 부족 — 증거 얇음 플래그.**

---

## Q4. 소규모-N 케이스 코퍼스 — 구조화 vs 벡터 vs 그래프 vs 하이브리드

### 수십 건 케이스 카드에 dense 벡터/그래프는 오버킬인가? — 대체로 그렇다.
소규모 코퍼스에 벡터-DB *인프라*(HNSW, ANN 튜닝)는 오버킬이라는 강한 실무 컨센서스(임베딩을 *신호*로 쓰는 건
여전히 유효). 그래프는 더 정당화 불가 — **수십 건 큐레이션 코퍼스에 그래프 DB를 권하는 실무 가이드를 하나도
못 찾음**. 실무가 인용 임계:
- **~10,000 문서** 아래에서 ANN이 브루트포스에 진다: "1만 문서 미만이면 임베딩·HNSW 인덱스 유지 오버헤드가
  한계 recall 이득보다 크다" (<https://medium.com/@ThinkingLoop/when-to-ditch-your-vector-db-for-simple-bm25-b4f044f1076b>).
- **Willison의 "그냥 브루트포스"**: 446개 문서 관련 콘텐츠를 SQLite에서 순수 코사인(446×446≈198,916 비교,
  1,536차원)으로 — 벡터 DB 없이 (<https://til.simonwillison.net/llms/openai-embeddings-related-content>).
  수십 건이면 즉시.
- **HN "Vector databases are the wrong abstraction"** (<https://news.ycombinator.com/item?id=41985176>):
  임베딩은 별도 스토어가 아니라 데이터 옆 컬럼/인덱스여야. pgvector·sqlite-vec·DuckDB로 충분. sqlite-vec는
  수백만 벡터에 브루트포스로 "완벽 recall, sub-100ms" → 수십 건이면 마이크로초.

### 구조화/메타데이터 필터 vs 하이브리드(BM25+dense+rerank) — 언제 무엇이 이기나
가장 유용한 *정량* 발견: **소규모 well-labeled 코퍼스에서는 검색 알고리즘이 아니라 메타데이터 필터가 지배 레버.**
- AMAQA(arXiv:2505.13557): LLM 생성 메타데이터 필터가 **MRR 0.12 → 0.68 (k=5만에)** — 바닐라 RAG의 k=100 최고를
  능가. "리랭킹은 어느 정도 향상시키나, **지배적 기여는 효과적 메타데이터 필터링**." 필터+리랭크가 천장:
  k=40에 ~0.84 MRR. <https://arxiv.org/pdf/2505.13557>
- 하이브리드 표준 레시피: "하이브리드(BM25+dense, RRF)를 베이스라인으로 시작, 최대 품질은 크로스인코더 리랭커
  추가 — 단일 최대 향상" (<https://towardsdatascience.com/hybrid-search-and-re-ranking-in-production-rag/>).

**언제 무엇이 이기나:**
- **순수 구조화/메타데이터 필터가 이긴다**: 카드에 좋은 큐레이션 속성이 있고 질의가 제약으로 환원될 때
  (sector=semis, regime=oversupply, era=post-2015). 소규모-N + 풍부한 메타데이터의 sweet spot. AMAQA 수치가
  지배를 보임.
- **BM25 단독이 이긴다**: 정확/내비게이션 질의, 통제 어휘(티커·회사·키워드). 저지연.
- **Dense/하이브리드가 값을 한다**: 질의가 패러프레이즈/시맨틱하고 어휘 불일치가 recall을 깰 때. **키워드-온리에
  대한 최강 반론:** "BM25 최대 한계는 어휘 불일치 — 'heart attack symptoms'가 'myocardial infarction warning
  signs'를 놓친다"(<https://mbrenndoerfer.com/writing/bm25-search-algorithm-elasticsearch-implementation>).
  **금융은 이게 만연** — "memory glut" vs "DRAM oversupply" vs "inventory correction in semis"는 토큰을 0개 공유.
  이게 키워드-온리의 recall 손실 리스크.

### 소규모-N 케이스 코퍼스에 대한 종합 권고 (출처가 수렴)
**구조화 메타데이터 필터 + BM25를 주 검색으로, 임베딩은 값싼 브루트포스 2차 신호(벡터 DB·그래프 없음),
선택적으로 작은 크로스인코더 or LLM/구조적 리랭크를 "FAC" 단계로** — Q3의 표면 vs 구조 유사 문제 방어.
이 규모에서 알고리즘은 거의 무의미(Willison 446, sqlite-vec 완벽 recall); **메타데이터 품질과 리랭크/구조 단계가
전부**(AMAQA 0.12→0.68). 전용 벡터/그래프 DB는 조기 최적화.

> **Q3⇄Q4 연결:** MAC/FAC가 통합 설계 — Q4의 "값싼 검색"이 MAC(표면), Q3의 구조적 유사 우려가 FAC.
> FAC/리랭크 단계를 짓는 것이 "2018이라는 단어에 매칭"하는 대신 "과잉공급 *구조*에 매칭"해 가짜 유사를 막는 곳.

---

## Q5. LLM으로 서사에서 if/then 룰 증류

**결론 선제시:** LLM이 역사적 서사에서 "증류"한 룰은 **검증된 룰이 아니라 가설 깔때기**로만. LLM은 인과에
유창하나 실증적으로 인과 확립을 못 한다. 엄밀한 검증은 나이브한 "알파 발견" 주장 대부분을 deflate한다.

### 추출 기법 (SOTA)
금융 텍스트에서 인과(조건→결과) 추출 연구는 활발: 금융 이벤트 인과 마이닝(LLM+이벤트 그래프,
<https://link.springer.com/article/10.1007/s44443-025-00330-w>), FinCausal 계열
(<https://arxiv.org/html/2401.13545>), ECC Analyzer(트랜스크립트 계층 추출+RAG,
<https://arxiv.org/pdf/2404.18470>), LLM 알파-마이닝(AlphaAgent <https://arxiv.org/html/2502.16789v2>).
**믿을 만한 것들의 공통 아키텍처: LLM은 탐색 *방향*을 제안하고, 결정론적 비-LLM 엔진이 실증 프로토콜을 강제.**

### 함정 1 — Hindsight/lookahead 편향 (보이지 않는 것)
**가장 중요하고 가장 과소평가**된 함정 — **누수가 입력 파이프라인이 아니라 모델 가중치 안에** 있어 일반 데이터
감사로 보이지 않는다.
- **"Detecting Lookahead Bias in LLM Forecasts"** (arXiv:2512.23847): 2019-09~11 실적 콜로 리스크를 예측시키면
  모델이 **COVID-19를 >25% 케이스에서 언급** — 공개되기 몇 달 전. "memorization ⊃ look-ahead bias".
  <https://arxiv.org/pdf/2512.23847>
- **"Summoning the Oracle to Slay It"** (arXiv:2605.24564) — **"파라메트릭 look-ahead bias"** 명명:
  "2024에 학습된 LLM은 2018–2020 주가가 어느 쪽으로 갔는지 이미 안다… 데이터 파이프라인이 아니라 모델
  가중치에 상주, 표준 감사에 보이지 않음." <https://arxiv.org/html/2605.24564>
- **암기 스모킹건**: GPT-4o가 "학습 창 내 날짜의 S&P 500 종가를 1% 미만 오차로 정확히 회상"
  (<https://paperswithbacktest.com/course/look-ahead-bias-llm-trading>).
- **측정 벤치**: Look-Ahead-Bench(arXiv:2601.13770)가 시제 다른 레짐 간 알파 감쇠로 lookahead 측정, "표준
  LLM에서 유의한 lookahead" 발견 (<https://arxiv.org/abs/2601.13770>).
- **완화**(전부 연구급): 엔티티 뉴트럴링 프롬프트, 포스트-컷오프 테스트, **컷오프 매칭 leak-free 모델**
  (ChronoBERT/ChronoGPT), inference-time unlearning. **프롬프트 제약은 파라메트릭 누수를 못 없앤다.**

**함의:** LLM이 학습 컷오프 *이전* 텍스트에서 "증류"한 룰은 오염됐다. 룰이 에피소드 결말에 대해 prescient해 보이면
암기를 의심. 깨끗한 테스트는 모델 컷오프 *이후* 텍스트 OOS 또는 컷오프 매칭 모델뿐.

### 함정 2 — 단일 에피소드 과적합 / 다중검정(p-해킹)
서사 코퍼스는 최악의 substrate — 설득력 있는 일화(콜 하나, 포스트모템 하나)가 일반 룰로 읽히고 LLM은 N=1에서
기꺼이 일반화한다. 방화벽은 전적으로 방법론.
- **Bailey, Borwein, López de Prado & Zhu, "Pseudo-Mathematics and Financial Charlatanism"** (AMS Notices 2014;
  SSRN 2308659): 몇 개 구성만 시험해도 높은 시뮬 성과는 사소; 메모리 효과 하에 **백테스트 과적합은 *음의* OOS
  기대수익**을 낳음. "시험한 구성 수를 보고하지 않으면 과적합 위험 평가 불가." **PBO**(Prob. of Backtest
  Overfitting) 도입. <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659>
- **Harvey, Liu & Zhu, "…and the Cross-Section of Expected Returns"** (RFS 2016; NBER w20592): "factor zoo" —
  새 factor는 **t-stat > ~3.0**(2.0 아님) 필요. <https://www.nber.org/papers/w20592> LLM 제안 룰 하나하나가
  거대한 다중비교 더미의 검정 하나다.

### 함정 3 — 환각된 인과 (LLM이 인과 링크를 발명)
매우 잘 문서화됨.
- **"Causal Parrots: LLMs May Talk Causality But Are Not Causal"** (arXiv:2308.13067; TMLR 2023): LLM은 "데이터에
  박힌 인과 지식을 낭송"할 뿐. <https://arxiv.org/abs/2308.13067>
- **Corr2Cause** (arXiv:2306.05836; ICLR 2024): 17개 LLM이 상관→인과 추론에서 "거의 랜덤"; 변수명 바꾸면 깨짐
  (패턴 매칭, 추론 아님). <https://arxiv.org/abs/2306.05836>
- **"Failure Modes of LLMs for Causal Reasoning on Narratives"** (arXiv:2410.23884) — *직접 당신 케이스*:
  **서사 순서 편향**(나중 언급 사건을 앞 사건의 결과로 취급), **텍스트 근접하나 무관한 요소 간 가짜 인과 생성**.
  실적 콜 산문에서 엉터리 "X→Y" 룰을 만드는 게 정확히 이것. <https://arxiv.org/pdf/2410.23884>
- **ReCITE** (arXiv:2505.18931): 최고 모델(Claude Opus 4.5)도 F1=0.535; "생성 엣지의 85–90%는 텍스트 근거가
  있으나 **17–33%만 정답과 일치**" — 그럴듯하지만 틀린 링크. <https://arxiv.org/html/2505.18931v4>

**함의:** LLM이 서사 순서를 인과로 오인하고 텍스트상 그럴듯하나 틀린 인과 엣지를 높은 비율로 낼 것으로 가정.
**텍스트 근거 ≠ 인과 타당성.**

### 함정 4 — 신뢰도 miscalibration
- **"Mind the Confidence Gap"** (arXiv:2502.11028; TMLR 2025): 9 LLM × 3 데이터셋 체계적 **과신**, RLHF 대형
  모델이 *더* miscalibrated일 수 있고, 엔티티 특화 질의(=특정 티커 룰)에서 캘리브레이션 실패.
  <https://arxiv.org/abs/2502.11028>
- 신뢰도는 반대 압박에 *불안정*(sycophantic drift).

**함의:** **LLM 자기보고 신뢰도를 룰 필터로 쓰지 말 것.** 정확도와 decorrelated이고 프롬프트로 조작됨.
(→ 룰을 LLM 신뢰도로 가중하는 어떤 설계와도 직접 충돌.)

### 검증 방법론 — 실제로 어떻게 검증하나
금융-ML 툴킷이 "수천 변형 시험 후 승자 보고" 문제를 위해 만들어졌다:
- **Deflated Sharpe Ratio (DSR)** — Bailey & López de Prado 2014 (SSRN 2460551): 시행 수·왜도·첨도·표본 길이로
  Sharpe 보정. 마이닝된 룰에 대해 보고할 **단일 최중요 숫자**. <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551>
- **PBO** + **Purged K-Fold + Embargo, CPCV** (López de Prado): 라벨이 미래 사건에 의존하고 표본이 겹쳐 표준 CV가
  누수 → **purging**(라벨 창이 테스트와 겹치는 학습표본 제거) + **embargo** → OOS Sharpe *분포*(DSR/PBO 입력).
- **탐색 예산 보고** 필수 — LLM 룰 마이닝은 *제안 룰 수 × 프롬프트/임계 변형 수*까지 포함.
- **모범 프로토콜** — "From Hypotheses to Factors" (arXiv:2604.26747): "에이전트가 탐색 방향을 통제하나 세션 내
  평가 규칙은 수정 불가"; 봉인된 스플릿(train 2020–22 / validation 2023 진단용 / **순수 OOS 2024–26**);
  포인트인타임 변수 위 제약 DSL로 forward-looking feature 방지; append-only 감사 추적.
  <https://arxiv.org/html/2604.26747v1>

**최소 신뢰 스택:** (1) OOS 전 룰 동결; (2) 전체 탐색 예산 보고; (3) 포스트-컷오프/leak-free 모델로 검증;
(4) CPCV(purge+embargo); (5) DSR+PBO; (6) 독립 인과-타당성 체크; (7) LLM 자기보고 신뢰도 무시.

### 반대 결론 — 신뢰 가능? 아니면 과적합 쓰레기?
**대부분 가설 생성이고 검증 실적은 얇고 미입증 — "된다" 주장에 강한 회의.**
- **AlphaAgent** (arXiv:2502.16789, KDD 2025): 스스로 과적합/p-해킹이 "백테스트에선 유의하나 급감하는 가짜
  factor"를 낳고 LLM이 "이미 착취된 비효율을 주로 복제"한다고 인정 — **LLM-마이닝 신호는 구조적으로 crowded**.
- **최강 음성** — "Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?"
  (arXiv:2505.07078; **KDD '26**): "LLM 파생 알파는 좁고 편향된 평가의 방법론적 산물일 가능성." 2004–2024
  단순 buy-and-hold가 FinMem·FinAgent를 능가. survivorship·look-ahead·data-snooping·pretraining 누수 지목.
  <https://arxiv.org/html/2505.07078v5>

**Net:** LLM 증류 if/then 룰은 정당한 아이디어 깔때기지, 그 자체로 신뢰할 룰의 원천이 아니다.

---

## Q6. 긴 금융 문서 청킹 / 표현

### Anthropic "Contextual Retrieval" (1차 출처)
<https://www.anthropic.com/engineering/contextual-retrieval>. 나이브 청킹의 핵심 실패(청크가 원문에서
떨어지면 지시대상 상실 — "회사 매출 3% 성장"이 어느 회사·분기인지 모름)를 공격. 임베딩 전에 Claude가
청크별 짧은 컨텍스트("50-100 토큰")를 써서 앞에 붙임. 3층: **Contextual Embeddings + Contextual BM25 + 리랭킹**.
- **개선(직접 인용, top-20 검색 실패율, 베이스 5.7%):** Contextual Embeddings 단독 **-35%**(→3.7%);
  + Contextual BM25 **-49%**(→2.9%); + 리랭킹 **-67%**(→1.9%).
- **비용/임계(당신 케이스에 load-bearing):** 프롬프트 캐싱 시 문서 100만 토큰당 **$1.02**. 그리고 명시적
  "안 해도 됨" 임계: **"지식베이스가 200,000 토큰(약 500페이지) 미만이면 전체를 프롬프트에 그냥 넣어라"** —
  검색 파이프라인 자체가 선택. **소규모 큐레이션 코퍼스라면 몇몇 FOMC 의사록/트랜스크립트가 통째로 컨텍스트에
  들어가 검색이 불필요할 수 있다.**

### Late chunking (Jina, 1차 출처)
<https://jina.ai/news/late-chunking-in-long-context-embedding-models/> · arXiv:2409.04701. 나이브 청킹은 청크를
독립 임베딩해 "장거리 컨텍스트 의존성을 파괴". Late chunking은 **먼저 문서 전체**를 트랜스포머에 통과시켜
토큰 임베딩에 문서 전역 컨텍스트를 담고, 그 다음 청크 경계를 적용·평균풀. 청크당 LLM 호출 없음(Anthropic과 대비).
- BeIR(~256토큰): NFCorpus 23.46%→29.98% 등. 규칙: "문서가 길수록 late chunking이 효과적."
  **한계:** long-context 임베딩 모델 필요(8,192 토큰), 짧은 텍스트에선 이득 소멸. 매우 긴 트랜스크립트는 8K 초과 가능.

### 반대: 시맨틱 청킹이 값을 하나? (회의론이 이긴다)
- **"Is Semantic Chunking Worth the Computational Cost?"** (Findings of NAACL 2025; arXiv:2410.13070):
  "시맨틱 청킹의 계산 비용은 일관된 성능 이득으로 정당화되지 않는다", **고정 200단어 청크가 시맨틱을 맞먹거나
  능가**. <https://arxiv.org/abs/2410.13070>
- **Chroma 기술 보고** (<https://www.trychroma.com/research/evaluating-chunking>): 시맨틱이 **recall 91.9%**로
  최고이나, recursive character가 **end-to-end 정답 정확도(~69% vs 54%)**로 이김 — **높은 recall이 더 나은
  답으로 이어지지 않음**(시맨틱 청크가 너무 잘게 쪼개져 LLM이 걸쳐 추론 못 함). 이 "recall ≠ downstream 정확도"
  갭이 가장 중요한 반대 발견.

**Q6 결론:** 긴 금융 문서엔 **고정/recursive 청킹 + 오버랩 + 리랭커**가 방어 가능한 기본. Contextual Retrieval은
긴 문서 검색 향상에 최강 증거지만 청크당 LLM 호출 비용; late chunking은 값싼 중간(long-context 임베딩 모델 게이트).
시맨틱 청킹은 (peer-reviewed 증거상) 값을 못 함. **코퍼스가 ~200K 토큰 미만이면 Anthropic 자체 조언대로 검색을
건너뛰고 전부 컨텍스트에 넣어라.**

> **벤더 편향 주의:** Anthropic의 35/49/67%, Jina의 BeIR 이득은 자기 스택 자가보고. 금융 코퍼스에서 중립 재현 아님.

---

## Q7. 포인트인타임 정확성 / lookahead 누수 방지

### T 시점에 알 수 있던 것만 surface — bitemporal 모델
두 독립 축:
- **Valid time** — fact가 현실에서 참인 때(가변; 소급 정정 허용).
- **Transaction/system time** — fact가 **DB에 도착/알 수 있게 된** 때(불변).

**원하는 보장 = transaction-time 축의 as-of 질의.** 정정된 실적 수치는 valid time이 원래 분기에 있지만
*transaction time*은 정정일 → `transaction_time <= T` 필터로 정정을 T에 안 보이게. **valid-time-only("Q1에 대해
참인 것")는 누수, transaction-time("T에 우리가 안 것")은 안 함.** 이게 전부다.
참조: <https://v1-docs.xtdb.com/concepts/bitemporality/>, <https://en.wikipedia.org/wiki/Bitemporal>.

### 왜 중요 — 백테스트의 survivorship·lookahead 편향
- **Survivorship**: CRSP 1926–2001 **7.4%(무편향) vs 9.0%(편향)** 연율; delisting return 정정(Shumway & Warther,
  JF 1999)에서 성과 관련 Nasdaq 상장폐지 return의 옳은 대체값 **≈ −55%** — 정정 후 "Nasdaq 규모효과는 애초 없었다"
  (발표된 anomaly가 실은 survivorship). <https://tylergshumway.org/Shumway-DelistingBiasCRSPs-1999.pdf>
- **Lookahead 채널**: 정정 실적(원래 날짜에 쓰면 누수), 보고 지연(period-end 값은 몇 주 뒤에야 filed),
  식별자 드리프트(오늘 티커/CUSIP을 과거에 적용).

### 벤더 PIT 제품
- **Compustat Point-in-Time** (S&P Global) — 레퍼런스. **1987-03**부터 월별 스냅샷, active+inactive,
  preliminary vs finalized 포착. <https://www.marketplace.spglobal.com/en/datasets/compustat-financials-(8)>
- **CRSP** — delisting return 포함 survivorship-free.
- **vBase (validityBase)** — 데이터/신호 해시를 퍼블릭 블록체인에 앵커해 tamper-evident PIT/OOS 기록.
  *당신 타임스탬프의 위변조 방지*를 풀지만 **상류 backfill·LLM 누수는 못 품**. <https://www.vbase.com/>

### 구현 패턴
- **SQL:2011 temporal tables**(application-time+system-versioned) — DB2/MariaDB/SQL Server. *Postgres는 네이티브
  미지원 → valid/transaction 컬럼 직접 롤.*
- **XTDB** — 목적특화 bitemporal, 불변 transaction time, 순서 뒤바뀐 도착 허용.
- **Datomic** — 불변 "DB as a value", `db.asOf(t)`. **주의: 단일 transaction-time 축 — 진짜 bitemporal 아님,
  과거 rewrite/branch 불가** → 정정을 valid-time과 함께 깔끔히 모델 불가. 진짜 bitemporal은 XTDB.
- **Feature-store PIT join / as-of join (당신 RAG 메모리에 가장 관련)** — 라벨 시점 T마다 `event_timestamp <= T`인
  feature만 조인. **이걸 직접 훔쳐라: 검색된 모든 문서/fact가 `knowable_at` 타임스탬프를 지니고, 검색은 as-of
  필터 `knowable_at <= T`.**

### 반대 — 깨끗한 bitemporal 스토어도 여전히 누수하는 곳
1. **벤더 backfill 무플래그**(#1 조용한 누수) — 벤더가 인제스천 전 정정을 조용히 덮어씀 → transaction-time 컬럼이
   *오염된* 입력을 충실히 보존. PIT는 벤더 자체 PIT 규율만큼만 좋다.
2. **LLM 학습 데이터에 박힌 lookahead**(LLM-구동 메모리의 킬러) — COVID-2019 누수(Q5). **당신 bitemporal DB가
   못 고침 — 누수가 모델 가중치 안**. LookAheadBench식 탐지 하네스 + "컷오프 이전 창을 추론하는 LLM은 본질적으로
   의심" 규칙 필요.
3. **타임스탬프 입도**: 발행 vs 발견 vs 인덱싱 vs 전달 시간; 자기보고 웹페이지 날짜는 신뢰 불가 → 날짜 필터 웹
   검색은 안전한 PIT 소스 아님.
4. **정정의 정정**, **preliminary-vs-final 모호성**(final 행에 키하면 preliminary로 거래했을 전략이 누수).

### 방어 가능한 설계
(a) 불변 `knowable_at`/transaction-time 축의 bitemporal 저장; (b) **as-of 검색(`knowable_at <= T`)만이 메모리로의
유일한 경로**; (c) delisted/reconstituted 포함 survivorship-free 유니버스 + dated 식별자; (d) preliminary vs
restated 별도 타임스탬프; (e) — DB가 못 고치는 부분 — **LLM lookahead 탐지 하네스** + 룰 신뢰도가 역사적 창에서
파생될 때 포스트-컷오프/컷오프 매칭 모델 사용.

> **Q5⇄Q7 연결:** Q7 PIT 규율은 Q5 룰 신뢰도에 *필요하나 불충분*. 완벽한 bitemporal 스토어는 *입력*이 T에 알 수
> 있었음을 보장하지만, LLM이 룰을 생성/채점했고 그 LLM이 T 이후 학습됐다면 룰 신뢰도는 여전히 파라메트릭 누수로
> 오염. **완전 깨끗한 신뢰도 = 포인트인타임 입력 + 컷오프 매칭(또는 포스트-컷오프 테스트) 모델 + DSR/PBO.**

---

## Q8. 하이브리드 검색 베스트 프랙티스 (2026 초)

### 컨센서스 레시피
정착된 2026 프로덕션 패턴: **BM25 + dense → RRF → 크로스인코더 리랭커 → LLM.** BM25는 정확/희소 term(티커·CUSIP·
GAAP 항목·날짜), dense는 패러프레이즈/개념; 어느 것도 모든 질의에서 이기지 않음. RRF는 *순위만*으로 융합(점수
비호환 회피), 표준 상수 **k=60**. 출처: <https://denser.ai/blog/hybrid-search-for-rag/>,
<https://aiworkflowlab.dev/article/how-to-build-hybrid-search-rag-bm25-rrf-fusion-cross-encoder-reranking>.

### 금융 문서 1차 벤치 (당신 도메인 최강 증거)
"From BM25 to Corrective RAG" (<https://arxiv.org/html/2604.01733v1>):

| 방법 | Recall@1 | Recall@5 | Recall@10 | MRR@3 |
|---|---|---|---|---|
| BM25 | 0.293 | 0.644 | 0.735 | 0.411 |
| Dense (text-embedding-3-large) | 0.248 | 0.587 | 0.703 | 0.351 |
| Hybrid RRF | 0.308 | 0.695 | 0.801 | 0.433 |
| **Hybrid + Cohere Rerank** | **0.472** | **0.816** | **0.861** | **0.605** |

Load-bearing: (1) 리랭킹이 **최대 향상**(+17.2pp MRR@3). (2) **금융 문서에서 BM25가 dense를 이김** — dense-only
파이프라인에 대한 직접 경고. (3) **HyDE는 역효과**(LLM 생성 가짜 금융 수치가 노이즈) — 피할 안티패턴.

### LLM 쿼리 플래너 / 구조화 검색 — dense와 경쟁 가능한가?
증거상 **구조화/큐레이션 데이터엔 올바른 도구이고 dense를 보완(대체 아님)**하며, 필드는 *agentic* 오케스트레이션으로
이동 중:
- **Text-to-SQL / 구조화 질의가 이김**: 집계·정확 필터·계산("정확 매치의 더 직접·정밀한 메커니즘"). RAG/dense는
  free-text 필드에서 이김.
- **자체 금융 metadata-RAG 1차** (<https://arxiv.org/html/2510.24402v1>, FinanceBench): 청크 벡터에 메타데이터를
  넣어 **F1 32.9 → 43.2 (+31%)**; 커스텀 메타데이터 리랭커가 상용 리랭킹에 근접(F1 44.4)하며 API 비용 제거.
  **주의:** 공격적 메타데이터 *확장*(공유 엔티티로 "관련" 청크 당김)은 **역효과** — F1 37.3→33.2, 환각 14.7→22.2%.
  → 메타데이터는 프리필터/임베딩 강화에 쓰고, **그래프식 확장에는 쓰지 말 것**.

**결론:** *소규모 큐레이션 코퍼스* + 깨끗한 구조(날짜·티커·문서타입·수치)에는 LLM 쿼리 플래너/self-query가 정확·
비용에서 종종 우월. dense는 free-text/패러프레이즈 슬라이스에 여전히 필요. (Azure는 최소 노력 수준에서 쿼리
플래닝을 아예 생략 — 플래너 자체가 선택적 오버헤드.)

### 반대 — 하이브리드/리랭킹이 오버킬인 곳
- **작고 잘 범위된 코퍼스에 리랭커는 거의 무의미**: 크로스인코더는 후보 풀이 크고 generic일 때 값을 함;
  메타데이터 필터가 이미 "도메인 전문가가 15분에 리뷰할 만큼" 좁히면 리랭커는 실비용에 한계 이득.
  (<https://bigdataboutique.com/blog/rag-reranking-improving-retrieval-quality-with-cross-encoders>).
- **눈감고 리랭킹 추가 금지**: "NDCG@10/MRR을 평가셋에서 안 돌렸으면 검색이 병목인지도 모른다."
- **단순 필터가 이길 때**: 메타데이터 필터/text-to-SQL이 결정론적으로 질의를 푸는 구조화 코퍼스. 200K 미만이면
  검색 자체가 불필요.

**Q8 결론:** 기본 레시피는 BM25+dense→RRF(k=60)→리랭크이고 금융 벤치가 리랭킹이 최대 레버(+17pp)임을 검증.
하지만 *작고 깨끗한 구조화* 금융 코퍼스엔 메타데이터 필터/LLM 쿼리 플래너가 정밀·비용에서 종종 이기고, 리랭킹은
한계적이며 dense-only는 능동적 리스크(BM25>dense, HyDE 해로움). **각 단계 추가 전 라벨셋에서 NDCG@10/MRR 측정** —
전 출처 공통·비벤더 조언.

---

## 10. 비교 표 — 구조화 vs 벡터 vs 그래프 vs 하이브리드 (우리 스택 관점)

| 축 | 구조화 JSONL (현재) | Dense 벡터 | 그래프 DB (Graphiti/Zep) | 하이브리드 (BM25+dense+rerank) |
|---|---|---|---|---|
| **비용(운영)** | 매우 낮음 (파일 append) | 낮음~중(브루트포스면 낮음, 전용 DB면 중) | **높음** (Neo4j/FalkorDB + episode마다 다중 LLM 추출) | 중 (임베딩 + 리랭커 API/모델) |
| **복잡도** | 매우 낮음 | 낮음(수십 건이면 브루트포스) | **높음** (온톨로지·비결정 추출·인프라) | 중 (RRF 융합 + 리랭커 튜닝) |
| **언제 쓰나** | 소규모-N + 풍부한 메타데이터, 정확/필터 질의 | 패러프레이즈·어휘 불일치 recall이 문제일 때 | **~10만 문서 + 상시 멀티홉 + "T에 참" 시간추론** | recall+정밀 둘 다 필요한 중~대규모 |
| **소규모-N 적합** | ★★★ (AMAQA: 메타데이터가 지배) | ★★ (신호로는 유용, 전용 DB는 오버킬) | ✗ (수십 건엔 오버엔지니어링; Letta grep=74%) | ★★ (필터가 좁히면 리랭커 한계 이득) |
| **anti-vector JSONL 스택 fit** | **네이티브** | 임베딩 컬럼으로 브루트포스 추가 가능 | 별도 스토어·패러다임 = 큰 이탈 | BM25/임베딩/리랭크 단계 추가 = 점진 |
| **bitemporal/PIT** | `asOf`/`knowable_at` 컬럼으로 직접 구현 | 기본 미지원(메타데이터로 롤) | **네이티브(진짜 차별점)** | 미지원(메타데이터로 롤) |
| **설명가능성(raw 노출)** | ★★★ (카드 원문 그대로) | ★ (유사도 점수) | ★★ (엣지·프로버넌스) | ★★ |
| **구조적 유사(FAC)** | 리랭크 단계로 추가 | 표면(MAC)만 | 그래프 순회가 관계 일부 포착 | 리랭커가 근사 |

---

## 11. 권고 — 우리 제약에 대한 결정 (단계적)

**결정: 메모리-사이클 케이스 레이어는 진짜 temporal KG가 아니라, 지금의 구조화 JSONL + 룰(플레이북) 패턴을
시간 인식 케이스 레코드 + 구조화/하이브리드 검색으로 확장한다.**

근거 요약: (1) 수십 건 규모에 그래프 DB·전용 벡터 DB는 모든 회의 출처가 오버엔지니어링이라 판정(Letta grep 74%,
~10만 문서 GraphRAG 임계, Postgres-first). (2) 우리가 이미 원하는 유일한 그래프 고유 능력(bitemporal 무효화)은
`knowable_at` 컬럼 + as-of 필터로 JSONL에서 직접 얻는다 — 플레이북 스키마에 이미 `asOf`가 있다. (3) 소규모에서
지배 레버는 알고리즘이 아니라 메타데이터 품질 + 구조적 리랭크(=MAC/FAC의 FAC). (4) OpenAI 쿡북조차 SQLite로 시작.

### MVP (지금 — 그래프/임베딩 없음)
- **2층 유지**: `documents/`(원문 보관) + **Case Card**(사이클 에피소드/시간축 이벤트). codex 계획의
  Document/Chunk/Event/Thesis 4층은 아직 넣지 말 것(임베딩 도입 P4 때 Chunk).
- **케이스 카드에 bitemporal 필드 추가**: 모든 fact/카드에 `event_time`(valid)과 **`knowable_at`(transaction)**
  둘 다. 검색은 **`knowable_at <= T` as-of 필터가 유일한 진입 경로**. 이게 백테스트 lookahead 방어의 뼈대.
- **검색 파이프라인 = MAC/FAC**: ① 메타데이터 as-of 필터(sector/regime/era/segment/direction) → ② BM25 키워드
  → ③ (선택) 임베딩 브루트포스(벡터 DB 없이, sqlite 코사인) → ④ **구조적 리랭크**(LLM 또는 규칙 기반: 인과 사슬
  형태 매칭 — "과잉공급→재고→가격→마진"). ④가 "2018 단어 매칭" 대신 "글럿 구조 매칭"을 막는 곳.
- **룰(플레이북)은 가설 깔때기로만**: LLM 증류 룰을 그대로 신뢰 X. 스키마에 이미 있는 `reservations`·`asOf`
  활용, **LLM 자기보고 신뢰도로 가중 금지**(Q5 함정 4). 사이클 판정은 계속 규칙 기반 가중합(재현·설명 가능).
- **메모리-반도체는 FULL, 나머지 위기는 RULE-only** (기존 2-tier 유지). FULL 케이스도 그래프가 아니라
  source chunks + time-causal timeline + 정량 backbone을 **같은 JSONL 날짜축**에.
- Q6 임계 활용: **케이스 코퍼스 원문이 ~200K 토큰 미만이면 검색 없이 컨텍스트에 통째로** 넣는 것도 옵션.

### 트리거 — 임베딩을 추가할 때
- 구조화 필터로 **놓치는 질의가 반복**되고 원인이 어휘 불일치("memory glut" vs "DRAM oversupply")로 진단될 때.
- 이때도 **전용 벡터 DB 금지** — 임베딩 컬럼 + 브루트포스(sqlite-vec/pgvector). 카드 수가 수천 건 넘을 때만.
- 추가 전 **라벨셋에서 NDCG@10/MRR 측정**해 검색이 진짜 병목인지 확인(Q8 공통 조언).

### 트리거 — 그래프를 추가할 때 (아마 오지 않음)
- **동시 충족** 시에만: (a) 진짜 멀티홉 교차문서 질의가 상시 패턴, (b) "T에 무엇이 참이었나" 시간추론이 as-of
  필터로 부족, (c) 케이스 코퍼스가 수십 건을 훨씬 넘어 규모 성장. 그전엔 JSONL + as-of가 지배.
- 그래도 간다면 Graphiti(Apache-2.0) + FalkorDB-Lite로 시작하되, **비결정 추출 품질**이 진짜 비용임을 명심.

### 룰 신뢰도를 언젠가 백테스트할 때 (Q5+Q7)
- **포인트인타임 입력 + 컷오프 매칭(또는 포스트-컷오프) 모델 + 탐색 예산 보고 + DSR/PBO + CPCV(purge+embargo)**
  없이는 신뢰도 미보고. LookAheadBench식 탐지를 룰 파이프라인에 넣기.

---

## 12. 증거가 얇은 곳 (플래그)

- **에이전트 메모리 벤치마크 전반**: 전부 벤더 자가측정, 중립 리더보드 없음. Zep/Mem0 LOCOMO 숫자는 서로
  반박됨. "SOTA" 주장은 아키텍처 주장과 분리해 discount.
- **"풀 CBR 사이클이 RAG를 이긴다"**: 통제 교차 벤치마크 희소. 지지되는 건 "구조/factor 기반 유사가 나이브
  임베딩보다 낫다"(중간 지지)까지.
- **금융 프로덕션 CBR**: 발표된 실배치 사실상 없음(산업 신호는 Huawei 테스트생성뿐, 금융 아님).
- **구조 vs 표면 유사**: 회상 실험은 혼재 — "구조적 검색이 무조건 낫다"는 미정 실증, 설계 prior로만.
- **청킹 벤더 수치**: Anthropic 35/49/67%, Jina BeIR은 자기 스택 자가보고, 금융 중립 재현 아님.
- **후기 arXiv 프리프린트 클러스터**(2512.xx–2607.xx lookahead/causal/alpha 논문들): 최근이라 peer-review 미확인.
  방향성으로 인용, 정착된 결과 아님. Corr2Cause GPT-4 F1, 일부 벤더 지연/가격 수치도 2차 인용.
- **크리스탈 갭**: 학습된 레짐/위기 임베딩을 LLM-CBR 케이스 레이어와 융합한 사례를 못 찾음. 현재 위기/레짐 분석은
  고전 ML이고 케이스-카드 LLM 검색이 아님 — "이건 2018 글럿 같다" 검색을 지으면 미개척 영역.

---

## 부록 — 핵심 1차 출처

- OpenAI Temporal Agents 쿡북: <https://developers.openai.com/cookbook/examples/partners/temporal_agents_with_knowledge_graphs/temporal_agents>
- Graphiti: <https://github.com/getzep/graphiti> · Zep 논문: <https://arxiv.org/abs/2501.13956>
- 에이전트 메모리 벤치 회의: <https://essays.bloo-mind.ai/posts/2026-05-20-mem-eval/> · Postgres-first: <https://hindsight.vectorize.io/blog/2026/05/12/case-against-external-vector-dbs-agent-memory>
- Anthropic Contextual Retrieval: <https://www.anthropic.com/engineering/contextual-retrieval> · Jina late chunking: <https://arxiv.org/abs/2409.04701>
- 시맨틱 청킹 회의(NAACL 2025): <https://arxiv.org/abs/2410.13070> · Chroma: <https://www.trychroma.com/research/evaluating-chunking>
- 금융 하이브리드 벤치: <https://arxiv.org/html/2604.01733v1> · 금융 메타데이터 RAG: <https://arxiv.org/html/2510.24402v1>
- CBR-RAG: <https://arxiv.org/abs/2404.04302> · DeFine(factor profiles): <https://arxiv.org/abs/2410.01772> · FinSeer: <https://arxiv.org/abs/2502.05878>
- MAC/FAC: <https://www.qrg.northwestern.edu/ideas/smeidea.htm> · Structure-Mapping: <https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf>
- Causal Parrots: <https://arxiv.org/abs/2308.13067> · 서사 인과 실패: <https://arxiv.org/pdf/2410.23884> · Corr2Cause: <https://arxiv.org/abs/2306.05836>
- 파라메트릭 lookahead: <https://arxiv.org/html/2605.24564> · lookahead 탐지: <https://arxiv.org/pdf/2512.23847> · Look-Ahead-Bench: <https://arxiv.org/abs/2601.13770>
- Pseudo-Mathematics(백테스트 과적합): <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659> · DSR: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551> · Factor Zoo: <https://www.nber.org/papers/w20592>
- LLM 알파 부정 결과(KDD'26): <https://arxiv.org/html/2505.07078v5> · From Hypotheses to Factors: <https://arxiv.org/html/2604.26747v1>
- XTDB bitemporality: <https://v1-docs.xtdb.com/concepts/bitemporality/> · Compustat PIT: <https://www.marketplace.spglobal.com/en/datasets/compustat-financials-(8)> · Shumway delisting: <https://tylergshumway.org/Shumway-DelistingBiasCRSPs-1999.pdf>
- 소규모-N 브루트포스(Willison): <https://til.simonwillison.net/llms/openai-embeddings-related-content> · 메타데이터 지배(AMAQA): <https://arxiv.org/pdf/2505.13557>
