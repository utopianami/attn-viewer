# 답변 품질 개선 연구 (2026-07-03)

목표: deep QA 파이프라인의 답변 품질을 체계적으로 높인다.
방법: 현재상태 진단(운영 관찰) + deep-research(웹 팬아웃 26출처 → 128주장 추출 → 3표 적대검증 → 확정 9건·기각 4건).

---

## ① 현재상태

### 완성된 것 (M5 기준)
TRIAGE → PLAN(A/B+G0) → [DA 이중 블라인드 · RA-외부 4수집기 · PRICE/MACRO] →
ASSEMBLER(충돌해소) → CALC(finance_math) → VERIFIER(G1샤딩+G2/G3/G4 코드) →
REFLECT(≤2라운드) → RISK(tier3) → SYNTH → AUDITOR. 전 스테이지 layer 스트리밍 + 비용 표시.

실측 (한화오션 tier2, 2026-07-03): claims 61 · verified 50/미검증 10 · 감사 12/14 지지 ·
REFLECT 1라운드 발동 · ~2.5분 · ~$1.2.

### 실전에서 드러난 약점 (오늘 하루 운영 관찰, 영향 큰 순)

| # | 약점 | 증상/근거 |
|---|---|---|
| W1 | **평가셋·회귀 감지 부재** | 골든 문항 0개. 품질 변화를 사용자 체감으로만 발견 (메타클라우드, 미검증 폭탄 모두 사용자가 발견). 개선이 개선인지 측정 불가 |
| W2 | **근거가 얕다 — 뉴스 제목/요약만** | Brave description 1~2문장 + grok 서사만으로 G1 판정. 본문 미수집 → 검증이 "제목과 안 모순됨" 수준. PER 등 "확인 불가" 빈발 |
| W3 | **G1 판정 캘리브레이션 미측정** | 심판(Fable/GPT)의 supported/unsupported가 맞는지 검사한 적 없음. uncertain 처리 방침도 임의 |
| W4 | **followup 경로가 얕음** | 직전 턴 raw 재사용 + 1콜 합성. 새 검색 없이 답하다 컨텍스트 빈약하면 사과성 답변 |
| W5 | **CALC 발동률 낮음** | plan.metrics 있을 때만. 시세 외 재무수치(매출·영업이익)는 typed_facts가 없어 계산 불가 → 뉴스 수치 의존 |
| W6 | **멀티턴 맥락 빈약** | history = 원문+답변요약+plan_summary. 대화가 길어지면 참조 해소 품질 미검증 |
| W7 | **검색어 품질 미검증** | PLAN이 만든 search_queries가 실제로 좋은 문서를 가져오는지 측정 없음 |
| W8 | **DA-DA 불일치 신호 저활용** | 마킹+집중검증 승격만. 불일치 지점을 재조사 쿼리로 직접 안 씀 |
| W9 | **depth 레버 없음** | 간단 질문도 풀 파이프라인 ~2.5분/$1.2 |
| W10 | **RISK 근거 다양성** | contrast 검색 결과가 RISK에 직결 안 됨 |

### 지금 갖고 있는 자산
전량 보존 raw layers(평가셋 소재) · 피드백 UI(👍👎+태그, 오늘 추가) · claim 단위 계약 · 스테이지 분리 구조.

---

## ② 리서치 결과 (적대 검증 통과 9건)

> 표기: [높음]=3-0 표결·복수 독립출처, [중간]=단일출처/프리프린트/미복제. 기각 4건은 §부록.

**F1. [높음] 인용 '존재'가 아니라 '출처가 주장을 실제로 지지(entailment)하는가'를 감사해야 한다.**
딥리서치 제품들의 인용 정확도는 40~80%에 불과 (DeepTRACE — GPT/Perplexity/Copilot/Gemini 출력 감사).
AAR 표준이 4지표 제안: Provenance Coverage / **Provenance Soundness**(entailment) / Contradiction Transparency / Audit Effort.
→ 우리 AUDITOR는 숫자 대조만 함. claim-출처 entailment 감사로 확장 여지. (arxiv 2602.13855, 2509.04499)

**F2. [높음] claim 분해 굵기(granularity)는 튜닝 파라미터다 — 과분해도 저분해도 해롭다.**
과분해(FActScore식 23개/답변)는 -6.24pp, 저분해(1.7개)는 **불지지(NOT SUPPORTED) recall이 8%로 붕괴**
(거친 claim은 "지지됨"으로 쏠림). 중간(~8개)이 최적 (JPMorgan AI, EACL 2026).
→ 게이트 품질은 전체 정확도가 아니라 **불지지 recall**로 모니터링해야 저분해 회귀가 보인다. (arxiv 2602.21857)

**F3. [중간] claim을 6종 타입(수치·시점·개체속성·비교·규제·계산)으로 분류해 타입별 검증기로 라우팅하면 환각률이 절반~1/3.**
FinGround(ACL 2026 Industry): 동일 검색 조건 통제 실험에서 최강 베이스라인 대비 환각 68% 감소.
분류 체계 제거 시 환각률 약 2배 (4.9%→11.7%). 계산형 검증은 LLM이 아니라 47개 공식 템플릿 재계산(±0.5% 허용오차) — 90.2% F1,
FActScore식이 57%만 잡는 계산 오류를 100% 포착. → 우리 G1/G2/G3 분리가 옳은 방향임을 검증 + 확장 방향 제시. (arxiv 2604.23588)

**F4. [높음] 계산형 claim은 결정적 재계산이 실측 우월 — 독립 3계 교차 검증.**
FinGround(위) + FinMAN(EMNLP 2025: 코드 Executor 제거 -18.75%, 단계별 Evaluator 제거 -31.64%) +
VERAFI(Amazon: 결정적 검증 정책 추가 +4.3pp). → finance_math/G2 설계 자체를 3개 독립 연구가 검증.
확장: "검증"을 넘어 **공식 라이브러리 기반 재계산**(한국판: PER/PBR/배당수익률/YoY/증감률) + 허용오차 명시. (2604.23588, EMNLP 2025.225, 2512.14744)

**F5. [중간·조건부] 값싼 verifier의 적대 수락 게이트(prover-verifier)는 ~3콜로 84~97% 정밀 서브셋을 만들지만, verifier가 도메인 밖이면 신호가 역전(-7.1pp)된다.**
PVD(NYU): GPQA에서 +32pp, HLE에서는 역전 — "verifier는 어렴풋이 아는 것만 도전하고 모르는 건 수락".
→ 한국 주식 도메인에서 골든셋으로 verifier 신호 확인 **후에만** 도입. 조용히 역전되므로 무검증 도입 금지. (arxiv 2605.25133)

**F6. [높음] 최대 병목은 답변측 검증이 아니라 검색이다 — 그리고 답은 "많이"가 아니라 "겨냥해서 적게".**
FinTMMBench: 최고 시스템 오류의 46.5%가 retrieval (계산+추론 합계 42.5%보다 큼).
HiREC(ACL 2025): **답변가능성(answerability) 판정 + 부족 시 보완질문 생성 재검색** + 패시지 필터로 +13.14pp,
쿼리당 3.7개 패시지만 사용. 필터 없이 recall만 올리면 정확도 하락(노이즈 충돌).
→ REFLECT의 학술 검증판. 트리거를 "게이트 실패 후"에서 **합성 전 answerability 판정**으로 전진 +
재조사를 "원질문 재시도"가 아닌 "부족 근거 겨냥 보완질문"으로. (2503.05185, FinTMMBench)

**F7. [중간] 시점 정보를 검증 단계(G3)가 아니라 검색·랭킹 자체에 넣으면 수치 정확도 상승.**
FinTMMBench ablation: 인덱스 노드의 시점 속성 제거 시 4지표 전부 하락, 산술 태스크 최대 -31% 상대.
→ 수집 문서의 published_at을 랭킹·필터에 직접 사용, G3는 잔여 안전망으로. (FinTMMBench)

**F8. [높음] 금융 계산 오류는 공식 선택/데이터 추출/계산 3단계에서 따로 나므로, "공식 계획"을 명시적 선행 단계로 분리 + 중간 산출물 검증.**
FinMAN 전문가 오류 분석 350건: 계산 오류 84%, 추출 관련 72% (추출을 독립 태스크로 떼면 잘 풀림).
Formulator(공식 계획) 제거 시 -44.07pp. → CALC 앞에 "어떤 공식·어떤 수치가 필요한가" 계획 서브스텝,
검증을 최종 답변만이 아니라 중간 산출물(추출 수치·선택 공식)에도. (EMNLP 2025.225)

**F9. [중간] 지속 평가 실용 프레임: 골든셋은 시점 앵커 + 근거 라벨 + claim 타입 라벨, 그리고 "검색 recall"과 "답변 정확도"를 분리 추적.**
FinTMMBench/LOFin 설계 패턴. 게이트 품질은 불지지 recall(F2)로. AAR 4지표를 운영 KPI 후보로.
단, "이 평가 체계를 돌리면 품질이 지속 개선된다"는 프로덕션 실사례는 미확보 — 측정 설계의 번안 제안. (2602.13855, 2503.05185, 2505.20368)

### 주의사항 (리서치 자체 한계)
- 핵심 출처 다수가 2025.12~2026.05 프리프린트, 독립 복제 없음 (FinGround·PVD·VERAFI·AAR).
- **전부 미국 시장 기준** (SEC·NASDAQ·영어). 한국 주식·한국어·DART·토스 환경 이전성 미검증 — 특히 공식 템플릿(K-IFRS), 시점 표기(억/조, 회계연도), verifier 도메인 역량.
- 기각 4건(0-3/1-2 표결): "코드 실행이 환각 4.1→1.2%" 류 — 근거 불충분으로 계획에서 제외.
- 딥리서치 제품들의 내부 검색 패턴 1차 근거는 미확보 (출력 감사와 학술 프록시까지만).

---

## ③ 개선사항 (리서치 ↔ 약점 매핑)

| 우선순위 | 개선 | 근거 | 해결하는 약점 |
|---|---|---|---|
| **P0** | 골든셋 + 평가 하네스 (모든 개선의 전제) | F9, F2 | W1, W3, W7 |
| **P1** | 검색 개선: 본문 수집 + evidence curation + answerability 전진 + 보완질문 재검색 | F6 (최대 병목) | W2, W7 |
| **P2** | claim 타입 라우팅 + granularity 튜닝 + 불지지 recall 모니터 | F2, F3 | W3 |
| **P3** | CALC 확장: 한국 공식 템플릿 + 토스 재무 typed_facts + 공식 계획 서브스텝 | F4, F8 | W5 |
| **P4** | 시점 메타를 검색 랭킹에 (G3 전진 배치) | F7 | W2 |
| **P5** | AUDITOR entailment 감사 + followup에 answerability 적용 | F1, F6 | W4 |
| **P6 (조건부)** | PVD 수락 게이트 — 골든셋에서 verifier 신호 검증 통과 시에만 | F5 | 비용·지연 |

리서치가 지지하지 않은 것 (하지 않을 일): self-consistency 다수결 확대 (F5 대비 비용 열위 + 관련 주장 기각),
무분별한 검색량 확대 (F6: 노이즈로 역효과), 검증 없는 PVD 도입 (신호 역전).

---

## ④ 구체적 변경 계획

### P0. 골든셋 + 평가 하네스 — 1~2일
1. **골든 문항 20개 구축** (`engine/tests/golden/questions.json`):
   - 유형 배분: 수치(YTD·기간수익률) 5 · 원인분석 5 · tier3 판단 4 · 개념 2 · followup 2 · 함정(미공시·조작수치) 2
   - 각 문항에 라벨: 시점 앵커, 기대 근거(출처 URL/데이터), 기대 수치(±허용오차), claim 타입, "정답이 없어야 정답"인 항목 표시
   - 소재: 보존된 raw layers + 오늘까지의 실질문 (메타클라우드·한화오션 케이스 포함 — 회귀 방지)
2. **평가 러너** (`engine/tests/eval_golden.py`): 문항별 파이프라인 실행 → 자동 채점
   - 수치: 기대값 ±오차 일치 / 검색: 기대 근거 URL 도메인 히트율(retrieval recall) / 답변: LLM-judge 1콜(기준표 고정)
   - **분리 리포트**: 검색 recall vs 답변 정확도 vs 불지지 recall (F2·F9) — 병목이 어디인지 즉시 판별
3. **회귀 프로토콜**: 파이프라인 변경 시 골든셋 실행 → 이전 점수와 diff. 야간 자동 실행(비용 ~$25/회는 주 2회로 제한)
4. 피드백 UI(👍👎) 데이터를 골든셋 후보 큐로 (👎+태그 → 문항화)

### P1. 검색 개선 — 2~3일 (최대 기대효과)
1. **뉴스 본문 수집** (`tools/news/fetch_body.py` 신설): 상위 N(=5)개 뉴스만 본문 fetch(trafilatura류 추출) → NewsItem.content 채움. 토스 뉴스는 이미 본문 API 있음(`api/v2/news/{id}`) — 활성화만
2. **evidence curation** (`stages/ra_external.py`): 수집 후 mini 1콜로 유닛별 관련성 필터 → 상위 3~5개만 검증·합성에 전달 (F6: "적게, 겨냥해서"). 원본은 raw 보존
3. **answerability 판정 전진** (`stages/verify.py` → `run_answerability`): ASSEMBLER 직후 "이 증거로 각 유닛에 답할 수 있나" 코드+mini 판정 → 불가 유닛은 **보완질문 생성**(원질문 재시도 금지) → 재조사. 현 REFLECT는 게이트 실패 후 발동하는 2차 안전망으로 유지
4. **DA-DA 불일치 → 보완질문 직결** (W8): disagreement의 claim_key로 재조사 쿼리 자동 생성

### P2. claim 타입 라우팅 — 1~2일
1. `AtomicClaim.type` 확장: 기존 fact/numeric/price/definition/risk/context + **comparison, regulation, temporal** (contracts)
2. `stages/verify.py` 라우팅: 수치·계산→G2(결정적), 시점→G3, 비교→양변 수치 각각 G2 후 비교 재계산, 개체속성·사실→G1(LLM), 규제→G1+출처 필수
3. claim 추출 프롬프트에 granularity 지침: "답변당 6~10개, 한 문장에 검증 가능한 사실 1개" (F2 중간 굵기)
4. 골든셋 리포트에 **불지지 recall** 추가 — 조작수치 함정 문항이 unverified/rejected로 잡히는 비율

### P3. CALC 확장 — 2일
1. **한국 공식 템플릿** (`tools/calc/formulas_kr.py`): PER/PBR/배당수익률/YoY/QoQ/증감률/괴리율/시총 — 입력 슬롯 정의 + ±0.5% 허용오차 명시 (F3·F4)
2. **토스 재무 → typed_facts** (`stages/price_macro.py` 또는 assemble): toss_company의 PER·수급 수치를 TypedFact로 승격 → 재무 claim도 G2 대조 가능
3. **공식 계획 서브스텝** (F8): calc.py 프로그램 작성 프롬프트를 2단 구조로 — ①필요 공식·수치 식별(누락 시 needed_evidence로 반환→재조사 연결) ②프로그램 작성. 추출 수치 자체도 검증 대상에 포함
4. followup 경로(W4)에 P1-3 answerability 적용: 직전 raw로 답 불가 판정 시 targeted 검색 1회 후 답변

### P4. 시점 랭킹 — 0.5일
1. NewsItem.published_at 정규화(상대시간 "3일 전" → 날짜) — 수집 시점에
2. curation(P1-2) 랭킹에 시점 가중치: knowledge_cutoff 근접 우대, cutoff 초과 문서는 랭킹에서 제외(G3는 안전망)

### P5. AUDITOR entailment — 1일
1. `stages/audit.py`에 ④번째 검사: 답변의 인용문장 ↔ 근거(뉴스 본문·서사) entailment를 mini 배치 판정 → "출처가 주장을 지지하지 않음" 이슈 유형 추가
2. 운영 KPI 노출: answer_meta에 provenance_soundness(지지 인용 비율) 추가 → 골든셋 추이 추적

### P6 (조건부). PVD 수락 게이트 — 골든셋 검증 후
1. 골든셋에서 실험: Haiku/mini verifier가 Fable prover 답변에 도전 → 수락 서브셋 정밀도 측정
2. 정밀도 ≥85% & 커버리지 ≥50%일 때만: 수락 claim은 G1 스킵(비용↓), 거부 claim만 정밀 검증
3. 신호 역전(-) 시 도입 포기 — 문서에 실험 결과 기록

### 실행 순서 제안
**1주차**: P0(골든셋) → P1(검색) — 측정 기반 확보 + 최대 병목 해소
**2주차**: P2(타입 라우팅) → P3(CALC) → P4(시점) — 골든셋으로 각 단계 효과 실측
**3주차**: P5(감사 확장) → P6(조건부 실험) + 골든셋 리포트로 전후 비교 발표

예상 효과(리서치 실측치의 보수적 번안): 검색 개선 계열이 가장 큼(원 연구 +13pp급),
타입 라우팅·CALC 확장이 수치 환각 감소(원 연구 절반~1/3), 골든셋은 효과 측정 자체를 가능하게 함.

---

## ⑤ 구현 상세 스펙 (implementation-level, 2026-07-03 확정)

> 전제: 데모 전까지 런타임 동결. P0는 테스트 전용이라 런타임 무위험 — 동결 중에도 진행 가능.
> P1~P5는 데모 후 착수. 각 항목은 "파일 → 함수/스키마 → 배선 → 검증" 순서로 바로 코딩 가능하게 기술.

### P0. 골든셋 + 평가 하네스 (런타임 무변경 — 동결 중 진행 가능)

**P0-1. 문항 스키마** — `engine/tests/golden/questions.json`
```json
{
  "version": 1,
  "questions": [
    { "id": "g01", "kind": "numeric",
      "question": "삼성전자 올해 얼마나 올랐어?",
      "expect": { "metric": "ytd_return", "symbol": "005930.KS",
                  "tolerance_pct": 1.0, "must_verified_label": true } },
    { "id": "g07", "kind": "causal",
      "question": "삼성전자 하이닉스 하락 원인 분석해줘", "history": [],
      "expect": { "must_mention_any": [["메타"], ["클라우드", "cloud"]],
                  "min_news_citations": 1,
                  "judge_rubric": "실제 시장 서사를 주원인으로 짚고 근거 URL을 달았는가" } },
    { "id": "g15", "kind": "trap",
      "question": "삼성전자 2026년 3분기 영업이익 알려줘",
      "expect": { "must_abstain": true,
                  "abstain_markers": ["미공시", "확인 불가", "발표 전"] } },
    { "id": "g17", "kind": "followup",
      "question": "그럼 하이닉스보다 나은거야?",
      "history_from": "g01",
      "expect": { "judge_rubric": "직전 턴(삼성전자 수익률) 맥락을 유지한 비교인가" } }
  ]
}
```
- kind enum: `numeric | causal | judgment(tier3) | concept | followup | trap`
- 20문항 배분: numeric 5 / causal 5 / judgment 4 / concept 2 / followup 2 / trap 2
- 소재 우선순위: ① 회귀 케이스(메타클라우드 g07, 한화오션, "카카오 YTD") ② storage 실질문 ③ 신규 함정

**P0-2. 채점기** — `engine/tests/golden/scorers.py`
```python
async def score_numeric(expect, answer_md, layers) -> Score   # 야후 재계산 → 답변 숫자 regex 추출 → ±tol 비교
async def score_causal(expect, answer_md, layers) -> Score    # must_mention_any(코드) + judge 1콜(rubric 고정, mini)
async def score_trap(expect, answer_md, layers) -> Score      # abstain_markers 존재 + 미검증 라벨 확인
async def score_judgment(expect, answer_md, layers) -> Score  # judge 1콜: 근거·반대시나리오·지시어금지 체크리스트
def score_retrieval(expect, layers) -> Score                  # ra_x/ra_web layer의 URL·도메인 히트
def score_unsupported_recall(expect, layers) -> Score         # trap/조작수치가 verify layer에서 unverified|rejected인가
```
- `Score = {passed: bool, value: float, detail: str}` — 실패 사유 필수 (diff 리포트용)
- judge 프롬프트는 파일 상수로 고정 + 버전 주석 (judge 변경 = 점수 비교 불가 → 버전 올리고 전체 재채점)

**P0-3. 러너** — `engine/tests/eval_golden.py`
```
사용: .venv/bin/python tests/eval_golden.py [--only g01,g07] [--save results/YYYY-MM-DD.json]
동작: 문항별 run_qa() 직접 호출(HTTP 불필요) → layers/final 수집 → kind별 채점
출력: ① 문항별 pass/fail+사유 ② 3축 요약(검색 recall / 답변 정확도 / 불지지 recall)
      ③ --save 시 results/에 JSON 저장, 직전 결과와 자동 diff (회귀 ↓표시)
비용 가드: 총 grok 콜 상한 옵션(--cheap: news_mode 강제 off 문항은 스킵 안 함)
followup 문항: history_from 문항의 최근 저장 결과에서 raw_layers 로드해 history 구성
```
- 예상 비용/시간: 풀런 ~$25 / ~50분 (문항 순차; 병렬 3이면 ~20분)
- **회귀 판정 규칙**: 3축 중 어느 축이든 직전 대비 -10%p 이상 하락 시 빨간 표시 + 원인 문항 나열

**P0-4. 피드백 → 골든셋 공급 파이프** — `engine/tests/golden/from_feedback.py`
```
동작: storage/users/*/chats/*.json 의 messages[].feedback (rating=down) 수집
  → {question, answer 요약, tags, review, chatId} 를 golden/candidates.json 에 append (중복 chatId 스킵)
  → 사람이 candidates를 보고 questions.json으로 승격 (자동 승격 금지 — 라벨은 사람이)
주기: 수동 실행 or 주 1회. 개선 사이클: 👎 리뷰 확인 → 문항화 → 개선 → 골든셋으로 회귀 확인
```
(전제: 코덱스 피드백 저장 구조 확인 — `server.mjs /feedback` 엔드포인트가 message에 저장하는 필드명 기준으로 구현)

### P1. 검색 개선 (데모 후 1순위)

> ✅ **2026-07-03 구현 완료** (P4 포함). 기록:
> - P1-1 `tools/news/fetch_body.py` (trafilatura, curation 통과 상위 5개, 실패 조용히 스킵)
> - P1-2 `curate_evidence()` + `RaPacket.curated` + `curated_items()` — verify/synth/claim추출/audit 전부 curation 통과분 사용
> - P1-3 `stages/answerability.py` — 코드 프리패스(커버리지 구멍) + mini 판정 + 보완질문, ASSEMBLE→CALC 후 배선, REFLECT와 라운드 상한 2 공유
> - P1-4 DA-DA 불일치 → "최신 공식 수치" 쿼리 직결 (프리패스, mini 불경유)
> - 파생 수정 ①: G1 판정 캐리오버(`g1_cache`, supported만 재사용) + 캡 32→48 — 보완검색으로 claim이 70+로 늘며 "판정 캡 초과" ×11 재발한 구조 결함 해소 (verified 37→32 하락이 47→50 상승으로 반전)
> - 파생 수정 ②: AUDIT 앵커에 근거 원문 숫자 포함(`_evidence_numbers`) + 복합 수사("1조 9,421억원") 합산 대조 + new_fact 코드 필터(근거 원문 실재 이름 탈락) — 본문이 합성에 유입되며 생긴 감사 오탐 8/18 → 26/27 해소
> - 검증: 오프라인 34/34 (test_p1_offline.py 신설) + 라이브 p1/ra 스테이지 + E2E 스팟체크 3회(한화오션·카카오) — verify 47/8, 실패 사유 전원 개별 판정(동일 사유 반복 0), audit 잔여 1건은 진짜 무근거 수치(CB 전환가)

**P1-1. 뉴스 본문 수집** — `engine/tools/news/fetch_body.py` (신설)
```python
async def fetch_bodies(items: list[NewsItem], *, top_n=5, timeout_s=8) -> None
# curation 통과 상위 N개만. httpx GET → trafilatura.extract() (pip 추가) → item.content 채움 (≤4000자)
# 실패는 조용히 스킵(제목/요약으로 동작 유지). 토스 뉴스는 api/v2/news/{id} 본문 API 사용 (이미 존재)
```
배선: ra_external 수집 완료 후 curation(P1-2) → 통과분만 fetch_bodies → G1 evidence와 synthesize 컨텍스트에 content 사용
의존성: `pyproject.toml`에 trafilatura 추가

**P1-2. evidence curation** — `stages/ra_external.py`에 `curate_evidence()` 추가
```python
async def curate_evidence(plan, x_search, web_knowledge, overrides) -> dict[str, list[NewsItem]]
# mini 1콜 (SO): 유닛별로 "이 질문에 답하는 데 실제로 유용한 기사"만 id 선택, 유닛당 상한 5
# 프롬프트 핵심: "제목이 관련돼 보여도 질문의 시점·종목·지표와 안 맞으면 제외" (F6: 노이즈가 정확도를 깎음)
# 반환된 것만 하류(verify/synth) 전달. 원본 전량은 RaPacket에 그대로 (raw 보존 원칙)
```
계약: RaPacket에 `curated: dict[str, list[str]]` (선택된 NewsItem id) 필드 추가 (contracts)

**P1-3. answerability 판정 + 보완질문** — `stages/answerability.py` (신설)
```python
class SupplementQuestion(_Strict): unit_id: str; question: str; search_queries: list[str]
class AnswerabilityResult(_Strict):
    unit_verdicts: dict[str, Literal["answerable","partial","unanswerable"]]
    supplements: list[SupplementQuestion]   # 상한 3

async def run_answerability(plan, table, ra, overrides) -> AnswerabilityResult
# ① 코드 프리패스: coverage uncovered(required) 유닛은 무조건 partial 이하
# ② mini 1콜: 유닛별 "현 증거로 답 가능한가 + 불가면 '무엇이 부족한지'를 겨냥한 보완질문 생성"
#    보완질문 규칙: 원질문 재서술 금지, 부족한 사실 하나를 특정 ("2026 Q1 카카오 영업이익 컨센서스")
```
오케스트레이터 배선 (orchestrator.py):
```
ASSEMBLE → CALC → **run_answerability** → supplements 있으면 run_ra_research(보완질문 쿼리)
  → 재조립 → VERIFY (기존 REFLECT 루프는 게이트 실패용 2차 안전망으로 유지, 총 라운드 상한 2 공유)
```
layer: `verify` layer에 `answerability` 필드로 표기 (프론트는 기존 verify 렌더러 재사용)

**P1-4. DA-DA 불일치 → 보완질문 직결** — `stages/answerability.py` 코드 프리패스에 추가
```python
# table.da_disagreements의 claim_key → f"{entity} {metric} 최신 공식 수치" 보완 쿼리 자동 생성 (mini 불경유)
```

### P2. claim 타입 라우팅

> ✅ **2026-07-03 구현 완료.** P2-1 contracts type +3종·DA/RA 스키마·프롬프트 정의 1줄,
> P2-2 verify `_ROUTE` (regulation ref 없으면 LLM 불경유 즉시 미검증, comparison은 value 있을 때만 G2
> — 스키마가 단일 value라 양변 재검산은 불가, 관계 서술은 G1 담당으로 스펙 조정),
> P2-3 granularity 지침(답변당 6~10개·claim당 사실 1개). P2-4는 P0 보류에 따라 이월.
> 검증: 오프라인 test_p2_offline.py 5건 + 스팟체크(발표일+비교 질문) — temporal claim이 G3+G1로
> 잘못된 발표일(7/7)을 기각하고 답변에 날짜 엇갈림 명시, comparison은 시세 기반 응답.
>
> **P1/P4 적대 리뷰 (2026-07-03, 에이전트) 반영 완료** — fix-first 3건 + 마이너 7건 전부:
> ①0건-reflect 레이어가 실측 verify 표시를 지움→verify 데이터 병합 방출+프론트 주석형,
> ②보완·재조사 증거가 컨텍스트 쿼터에 밀림→supplement/reflect 유닛 우선 정렬(+본문 8건),
> ③보완검색 라운드 상승이 replan 영구 봉인→replan_available 파라미터,
> ④G2 통과가 캡 초과에 밀림→판정 순서 교체, ⑤curation 폴백 슬라이스→스캔,
> ⑥재조사 자체 쿼리 간 URL 중복, ⑦_norm_age 주일/이틀/48시간, ⑧seen_queries 성공 후 마킹,
> ⑨재조사 쿼리 병렬화, ⑩unobtainable 시 claims 레이어 재방출.
> 반영 후 스팟체크(삼성전자): supp 계열 미검증 0건(수정 전 4~5건), verify 60/8, audit 32/32 severe=False.

**P2-1. 타입 확장** — `contracts/packets.py`
```python
type: Literal["fact","numeric","price","definition","risk","context",
              "comparison","regulation","temporal"]      # +3
```
DA/RA 추출 스키마·프롬프트에 타입 정의 1줄씩 추가 (비교="A가 B보다", 규제="공시·규정 인용", 시점="일정·발표일")

**P2-2. 라우팅 테이블** — `stages/verify.py`
```python
_ROUTE = {
  "numeric":   ["G2"],          "price": ["G2"],
  "comparison":["G2_BOTH"],     # 양변 값 각각 G2 + 부등호 재검산 (finance_math greater)
  "temporal":  ["G3","G1"],     "regulation": ["G1_STRICT"],  # 출처 ref 없으면 즉시 unverified
  "fact": ["G1"], "definition": [], "context": [], "risk": []
}
```
G1 후보 선정 로직을 `_ROUTE 기반 + load_bearing/2차출처 보정`으로 교체

**P2-3. granularity 지침** — DA/RA claim 추출 프롬프트에 1줄:
"claims는 답변당 6~10개. 한 claim에 검증 가능한 사실 정확히 1개 — 더 쪼개지도 뭉치지도 마라." (F2)

**P2-4. 불지지 recall 모니터** — P0 러너의 trap 문항 채점이 담당 (score_unsupported_recall). 추가 코드 불필요

### P3. CALC 확장

> ✅ **2026-07-03 구현 완료.** P3-1 `tools/calc/formulas_kr.py` (8공식+동의어 매핑, 프롬프트 few-shot 주입),
> P3-2 toss per→TypedFact 승격(assemble), P3-3 `_Programs.missing_inputs` 2단 구조 →
> answerability 보완질문 합류(run_calc 3-튜플 반환), P3-4 followup mini 프리패스+brave 1쿼리.
> 검증: 오프라인 test_p3_offline.py 4건(전 공식 finance_math 실행 확인) + 스팟체크(삼성전자 PER·YTD·배당) —
> PER 23.48배(toss 승격 passthrough), YTD +140.86%(템플릿 계산), 배당수익률 missing 보고→
> "연간 주당배당금" 표적 재검색까지 설계 경로 전부 실동작. 파생 수정: 감사 반올림 인지 톨러런스
> (half-step — "PER 23배" vs 앵커 23.48 오탐 해소).

**P3-1. 한국 공식 템플릿** — `engine/tools/calc/formulas_kr.py` (신설)
```python
FORMULAS = {
  "ytd_return":   {"inputs":["price_now","price_yearstart"], "program":[...], "tol_pct":0.5},
  "period_return":{"inputs":["price_now","price_base"], ...},
  "per":          {"inputs":["price_now","eps_ttm"], ...},
  "pbr":          {"inputs":["price_now","bps"], ...},
  "div_yield":    {"inputs":["dps","price_now"], ...},
  "yoy":          {"inputs":["value_now","value_prev_year"], ...},
  "qoq":          {"inputs":["value_now","value_prev_q"], ...},
  "gap_pct":      {"inputs":["value_a","value_b"], ...},     # 괴리율
}
def match_formula(metric_text: str) -> str | None   # "올해 수익률"→ytd_return 동의어 매핑
```
calc.py: 프로그램 작성 프롬프트에 매칭된 템플릿을 few-shot으로 주입 → 작성 오류·단위 실수 감소

**P3-2. 토스 재무 → typed_facts** — `stages/assemble.py`
```python
# ra.toss_company[code]["info_per"] 등 → TypedFact(id=f"toss:{code}:per", unit="ratio", source="toss:...")
# → G2 앵커·CALC 입력 자격. 승격 목록: per, (수집 확장 시) eps/bps/배당
```

**P3-3. 공식 계획 서브스텝 (F8)** — `stages/calc.py` 프롬프트를 2단 구조로
```
_Programs 스키마에 추가: missing_inputs: list[{metric, needed: str}]
① 각 요청에 formulas_kr 템플릿 매칭 → 필요한 입력이 typed_facts에 있는지 판정
② 있으면 프로그램 작성 / 없으면 missing_inputs로 보고 (지어내기 금지)
orchestrator: missing_inputs → answerability supplements로 전달 (P1-3과 합류) → 재조사에서 수치 확보 시도
```

**P3-4. followup 강화** — `stages/followup.py`
```python
# run_followup에 프리패스 추가: mini 1콜 "직전 raw로 답 가능?" →
#   불가면 brave 1쿼리(질문 그대로) 검색 후 그 결과 포함해 합성 (grok 불경유 — 경량 유지)
# 소요: +1 mini콜 + 조건부 brave 1콜, 지연 +2~4s
```

### P4. 시점 랭킹

> ✅ **2026-07-03 구현 완료** (P1-2에 얹음). `_norm_age()` (한/영 상대시점→ISO, 실패 시 "" 중립),
> curation 프롬프트에 기준시점 근접 우대 + cutoff 이후 선택 금지, 코드 후처리로 cutoff 초과 드롭.

**P4-1. published_at 정규화** — `stages/ra_external.py` `_dict_to_news()`
```python
def _norm_age(age: str) -> str   # "3일 전"/"2 hours ago"/"2026-07-01" → ISO 날짜 (기준=오늘). 실패 시 ""
```
**P4-2. curation 랭킹 가중치** — P1-2 프롬프트에: "발행일이 기준시점에 가까운 기사 우선,
기준시점(knowledge_cutoff) 이후 기사는 선택 금지" + 코드 후처리로 cutoff 초과 문서 드롭 (G3는 안전망)

### P5. AUDITOR entailment (F1)

> ✅ **2026-07-03 구현 완료.** audit ④ 검사 신설 — markdown 링크에서 (인용 문장, URL) 쌍 추출(상한 8),
> curated 근거 원문(url→본문)과 mini 배치 판정 entail|neutral|contradict.
> contradict = [인용 불일치] 인라인 + citation_mismatch 이슈 + severe, neutral = 리포트만.
> `AuditReport.provenance_soundness`(entail 비율) → answer_meta·프로세스 뷰("인용 일치율 N%") 노출.
> 검증: 오프라인 test_p5_offline.py 3건 + 스팟체크(한화에어로) — 인용일치율 1.0,
> 미지지 숫자 3건은 전부 답변이 이미 '미검증' 라벨한 모델 기억 수치(정당한 강화 표시).

**P5-1.** — `stages/audit.py`에 4번째 검사
```python
# 답변에서 (문장, 인용 URL) 쌍 추출 (markdown 링크 regex)
# → 해당 URL의 NewsItem.content/제목과 문장을 mini 배치 판정: entail | neutral | contradict
# → contradict = AuditIssue(kind="citation_mismatch") + 인라인 플래그, neutral = 리포트만
# → AuditReport에 provenance_soundness: float (entail 비율) 추가 → answer_meta 노출 → 골든셋 추이 추적
```
계약: AuditIssue.kind에 "citation_mismatch" 추가, AuditReport에 provenance_soundness 필드 (contracts)

> **P2/P3/P5 적대 리뷰 (2026-07-03, 에이전트, 재현 검증 포함) 반영 완료** — fix-first 4건 + 마이너 5건:
> ①(치명) 2차출처 context/definition/risk가 G1 미후보 → 무검증 verified 통과 → 2차출처는 빈 라우트여도 G1 후보,
> ②toss PER(ratio) 앵커가 DA "배" 단위와 비호환으로 불발 → 단위 3그룹(pct/mult/abs) 분리,
> ③DA regulation은 ref가 없어 구조적 즉시-미검증+REFLECT 낭비 → DA에서 regulation 타입 제거(fact 강등),
> ④헤드라인 200자에 entailment 판정 → 정당 인용이 neutral 스팸 → 본문(≥300자) 확보 문서만 판정·neutral은 비율만,
> ⑤값 없는 DA comparison 게이트 0개 통과 → G2 미정형 처리, ⑥missing_inputs 빈 metric 필터+엔티티 없으면 스킵,
> ⑦severe를 detail 부분문자열이 아닌 kind로, ⑧판정 문장에서 감사 라벨 제거, ⑨followup brave 타임아웃 8s.
> + 빈 실패 사유("uncertainty=high" 경로) 노트 추가. 오프라인 49/49, 최종 스팟체크(카카오 PER):
> verify 63/14, audit 32/33·인용일치율 0.8, PER 31.74배(toss 승격), 잔여 플래그 전원 정당.

### P6 (조건부). PVD 수락 게이트 — 골든셋 완성 후 실험만
```
실험 스크립트: tests/exp_pvd.py — 골든셋 답변의 verified claim 30개에 대해
  mini(verifier)가 "반박 시도" 1콜 → 수락/도전 → 수락 서브셋의 실제 정답률을 골든 라벨로 측정
채택 기준: 정밀도 ≥85% AND 커버리지 ≥50% → G1 스킵 게이트로 채택 / 미달 → 문서에 기록하고 폐기
```

### 작업 순서 & 의존성

> **2026-07-03 사용자 결정: P0(골든셋)은 보류** — 아직 데이터(실질문·피드백)가 적음.
> 피드백이 쌓이면 재개. 검증은 당분간 스테이지 라이브 테스트 + 실질문 스팟체크로 대체.
> **확실히 개선될 것부터 바로 진행: P1 → P4 → P2 → P3 → P5 순.**

```
[1] ✅ P1-2 curation → P1-1 본문 fetch → P1-3 answerability+보완질문 → P1-4 DA불일치 직결
[2] ✅ P4 시점 랭킹 (P1-2에 얹음)
[3] ✅ P2 claim 타입 라우팅 + granularity
[4] ✅ P3 CALC 확장 (공식 템플릿·토스 재무 승격·공식 계획) + P3-4 followup 강화
[5] ✅ P5 AUDITOR entailment
[보류] P0 골든셋 (피드백 쌓이면) · P6 PVD (P0 이후)

→ 2026-07-03 P1~P5 전체 완료. 적대 리뷰 2회(19건) 반영. 관측된 비용: 답변당 $1.4~1.9
  (P1 이전 대비 상승 — G1 캡 48·보완검색·entailment. 품질 우선 결정에 따름, 필요 시 캡 조정)
```
각 단계 완료 기준: 오프라인 테스트 통과 + 실질문 1개 스팟체크 (한화오션/카카오 류).

### 데모 안전 수칙
- 데모 전: engine/·server.mjs·index.html 변경 금지. P0 파일은 tests/ 아래만 (런타임 임포트 없음 확인)
- 데모 후 작업은 스테이지 단위 커밋 — 문제 시 스테이지 단위 롤백

---

## 부록: 기각된 주장 (3표 적대검증 탈락 — 계획에 사용 금지)
- "코드 실행 전환으로 환각 4.1%→1.2%" (0-3), "PAL+하이브리드 검색 +9.9pp" (0-3) — arxiv 2603.04663 출처 신뢰 불가
- "Sonnet 4 도구 라우팅 33.3%→90.4%" (1-2) — VERAFI 세부 수치 검증 실패
- "안정성 신호(self-consistency)가 +4pp에 그침 vs PVD +29~35pp" (0-3) — 비교 조건 불일치

리서치 원자료: 26출처 · 추출 128주장 · 검증 25 · 확정 21 → 병합 9건. 전문은 워크플로 출력 보관.
