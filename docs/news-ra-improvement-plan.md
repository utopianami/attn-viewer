# NEWS/RA 답변 워크플로우 개선 계획

## 대상

검토 대상은 `workflow-review.html#stage-news`의 `③b RA-외부 / NEWS` 단계다.

현재 흐름은 Brave/Tavily 검색, Toss trend/company 수집, web knowledge 조건부 수집,
curation, 본문 확보, atomic claim 추출, ASSEMBLER 병합, VERIFIER grounded 검사,
REFLECT 재조사로 이어진다.

따라서 개선의 핵심은 검색 소스를 단순히 늘리는 것이 아니라, 다음 네 가지를 더 엄격히
관리하는 것이다.

- 검색 결과가 질문에 충분한가
- 뉴스 claim이 실제 출처 span에 붙어 있는가
- 금융 답변으로 사용할 수 있는 강도의 근거인가
- 숫자, 기간, 단위가 typed fact로 검증 가능한가

## 주요 실패 모드

### 1. 검색 결과 품질 문제

검색 결과가 최신이더라도 질문과 직접 관련이 없거나, 제목/요약만 맞고 본문 근거가
약할 수 있다. 현재 curation 이후 바로 claim 추출로 넘어가면 애매한 검색 결과가
답변 근거로 승격될 위험이 있다.

### 2. 단일 출처 과잉 추론

주가, 실적, 이슈 질문에서 기사 한 개만으로 "원인은 X"라고 단정하면 위험하다.
단일 기사는 보통 관측된 설명 후보일 뿐이며, 독립 출처나 가격/실적 typed fact와
결합될 때만 더 강한 원인 claim으로 올려야 한다.

### 3. 최종 답변 claim drift

ASSEMBLER와 VERIFIER를 통과한 뒤에도 최종 SYNTH 과정에서 표현이 바뀌며 새로운
claim이 생길 수 있다. 최종 답변 문장 단위로 source claim과 연결되는지 다시 검사해야
한다.

### 4. 뉴스 수치의 비정형 사용

매출, 영업이익, 가이던스, 수주액, 시장 점유율 같은 숫자가 뉴스 문장으로만 남으면
계산 검증이나 단위 검증이 어렵다. 금융 답변에서는 숫자 claim을 structured typed fact로
승격해야 한다.

## 문헌 기반 개선 축

### 1. Retrieval quality evaluator

CRAG는 검색 결과를 그대로 사용하지 않고, 검색 결과가 correct, ambiguous, incorrect인지
평가한 뒤 corrective action을 수행하는 방향을 제안한다.

적용안:

- RA 내부에 `retrieval_quality` 판정 추가
- 값은 `enough`, `ambiguous`, `bad`, `unavailable`
- `bad`면 claim 추출 금지 후 query rewrite
- `ambiguous`면 보강 검색
- `enough`일 때만 atomic claim 추출

참고:

- Corrective Retrieval Augmented Generation, 2024
- https://arxiv.org/html/2401.15884v3

### 2. Retrieval necessity and sufficiency gate

Self-RAG는 검색 필요성, 검색 결과 관련성, 답변의 근거 지지 여부를 분리해서 평가한다.

현재 `news_mode`는 검색 여부 판단에 가깝다. 여기에 "수집된 증거가 이 질문에 충분한가"를
별도 게이트로 추가해야 한다.

적용안:

- `needs_news_retrieval`
- `retrieval_sufficiency`
- `evidence_relevance`
- `answer_support`

를 분리해서 기록한다.

참고:

- Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection
- https://arxiv.org/abs/2310.11511

### 3. Final unsupported claim sweep

Chain-of-Verification은 초안 이후 독립 검증 질문을 만들고 재확인하는 방식으로
hallucination을 줄이는 접근이다.

적용안:

- 최종 답변 직전 문장 단위 claim 추출
- 각 claim이 source URL, source title, source span, claim table row에 연결되는지 확인
- 연결되지 않는 claim은 삭제, 완화, 또는 "확인 불가"로 강등

참고:

- Chain-of-Verification Reduces Hallucination in Large Language Models
- https://arxiv.org/abs/2309.11495

### 4. Financial numeric claim typed fact화

FinanceBench와 FinQA 계열 문제의식은 금융 QA에서 evidence, 숫자, 기간, 계산 가능성이
핵심이라는 점이다.

적용안:

- 뉴스에서 추출한 숫자는 문장 claim으로만 보관하지 않는다.
- 가능한 경우 다음 구조로 승격한다.

```json
{
  "metric": "operating_income",
  "value": 1234,
  "unit": "KRW_100M",
  "period": "2026Q2",
  "as_of": "2026-07-06",
  "source_url": "...",
  "source_span": "..."
}
```

- CALC/AUDITOR가 typed fact를 대상으로 단위, 기간, 계산식을 검증한다.

참고:

- FinanceBench
- https://arxiv.org/abs/2311.11944
- FinQA
- https://aclanthology.org/2021.emnlp-main.300/

## 우선순위

### P0

- RA 내부 `retrieval_quality` 게이트 추가
- `bad` 검색 결과의 claim 추출 금지
- `ambiguous` 검색 결과의 보강 검색
- 최종 답변 직전 `unsupported_claim_sweep` 추가
- 뉴스성 claim에 source span이 없으면 삭제하거나 약화

### P1

- 단일 출처 원인론 방지
- `reported_factor`, `likely_factor`, `confirmed_driver` 같은 claim strength 라벨 추가
- 숫자 뉴스 claim을 typed fact로 정규화
- 독립 출처 수와 source quality scoring 추가

### P2

- adaptive retrieval budget 도입
- tier, evidence richness, retrieval quality에 따라 검색량 조절
- RA 전용 평가셋 구성
- unsupported claim rate, evidence recall, source precision 측정

## 권장 변경 흐름

```text
NEWS query
  -> retrieval
  -> retrieval_quality 평가
  -> bad: query rewrite
  -> ambiguous: 보강 검색
  -> enough: 본문 확보
  -> atomic claim 추출
  -> numeric claim typed_fact 승격
  -> ASSEMBLER claim table 병합
  -> VERIFIER grounded 검사
  -> SYNTH 초안
  -> unsupported_claim_sweep
  -> 최종 답변
```

## 결론

현재 NEWS/RA는 증거를 많이 모으는 구조는 이미 갖추고 있다. 다음 개선은 검색량을
늘리는 것이 아니라, 검색 결과의 충분성, claim grounding, 원인론 강도, 금융 수치의
typed fact화를 강화하는 쪽이 우선이다.

