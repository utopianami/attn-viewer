# Codex Review R1 — 에이전틱 워크플로우 개선 계획

## Verdict

REQUEST CHANGES — 방향은 맞지만, §5 라우팅과 P1 묶음이 현행 엔진 구조·선행 RA 계획·불변식 비용을 과소평가한다.

## 지적사항

1. [critical] §5 “프로필 방식 ~200줄”은 현재 코드와 맞지 않는다  
근거: 계획은 “각 스테이지가 프로필을 보고 실행/생략”한다고 쓰지만 `orchestrator.py`는 deep 진입 후 PLAN, 3브랜치 fan-out, NEWS_SUMMARY, SECTOR_RAG, ASSEMBLE, CALC, VERIFY, RISK, SYNTH, AUDIT를 순서대로 하드코딩한다. 특히 DISPATCH는 “3브랜치 무조건 fan-out”이다: `engine/orchestrator.py:177-186`, `docs/workflow-review.html:386-390`. `PlanPacket`에도 question_type/profile/depth 필드가 없다: `engine/contracts/packets.py:103-127`.  
제안: §5를 별도 설계 과제로 격상하라. 최소 변경 범위는 `TriageResult`, `PlanPacket` 또는 별도 `WorkflowProfile`, layer payload, `run_da/run_ra_external/run_price_macro/run_verify/run_risk`, 테스트 픽스처까지 포함한다. “~200줄” 삭제.

2. [critical] “사실 조회: DA 끔, 뉴스/웹 끔~1콜, CALC 켬, 30초” 초기값은 현재 엔진에서 무근거 답변을 만들 수 있다  
근거: CALC는 `table.calc_requests`와 `table.typed_facts`가 없으면 바로 빈 결과다: `engine/stages/calc.py:93-95`. typed_facts는 현재 시세/토스 PER 중심이며 kg.db 공시 수치는 아직 RA 개선 계획의 미구현 항목이다: `engine/stages/assemble.py:239-254`, `docs/2026-07-06-ra-system-improvement-plan.md:31-47`. 계획은 이 전제를 “kg.db 연동과 맞물림”으로만 처리한다: `docs/workflow-routing-plan.html:327-333`.  
제안: fact_lookup 라우팅은 kg_search + 공시 typed_fact가 먼저 들어온 뒤 켜라. 그 전에는 DA 또는 최소 RA/price를 끄면 안 된다.

3. [major] A1/A2는 “프롬프트 구조만 변경”이 아니다  
근거: G1은 `_g1_judge()` 하나가 `(verdict, note, judged_by)`만 반환하고 `ClaimVerdict.judged_by`는 `fable|gpt|code` 리터럴이다: `engine/stages/verify.py:156-177`, `engine/contracts/packets.py:359-364`. AUDIT도 숫자·지시어는 코드이고 LLM은 신규 엔티티/인용 판정 일부다: `engine/stages/audit.py:168-180`, `engine/stages/audit.py:236-300`. 별도 외부 역할 재제시 결과를 보존하려면 계약 필드와 trace가 필요하다.  
제안: A1/A2를 “프롬프트만”이 아니라 `ClaimVerdict` 또는 별도 audit evidence 필드 변경 포함으로 재산정하라. A/B 로그 없이는 디버깅이 불가능하다.

4. [major] A3 소프트 리밋은 dexter식 도구 루프와 현재 REFLECT 구조가 다르다  
근거: 현행 REFLECT 쿼리는 LLM이 매 턴 도구를 고르는 구조가 아니라 `run_verify()`가 코드로 `RetryDirective`를 만든 뒤 `run_ra_research()`가 검색한다: `engine/stages/verify.py:331-367`, `engine/orchestrator.py:327-356`. 중복 방지는 exact string `seen_queries`뿐이다: `engine/orchestrator.py:253-256`, `engine/orchestrator.py:345-350`. dexter의 경고 주입은 자율 도구 루프 전제다: `docs/2026-07-08-dexter-analysis.md:43-48`.  
제안: “경고 주입” 대신 코드 레벨 query similarity dedup/rewrite로 설계하라. 경고를 넣으려면 재계획 LLM 경로에만 제한 적용해야 한다.

5. [major] D1은 P1 라우팅과 병렬 착수할 항목이 아니라 선행 의존성이다  
근거: 계획 D1은 kg.db와 결합한다고 쓰지만 `tools/registry.py`의 allowlist에는 kg 계열 도구가 없고 `SourceType`도 `news|price|macro|web|company`뿐이다: `engine/tools/registry.py:35-44`, `engine/contracts/packets.py:26-31`. RA 계획은 kg_search를 1순위 본체로 따로 잡고 있다: `docs/2026-07-06-ra-system-improvement-plan.md:31-47`.  
제안: P1 순서를 `kg_search/뉴스 통합 → retrieval_quality/strength/span → 라우팅`으로 바꿔라. 라우팅은 사용할 블록이 실제로 생긴 뒤 해야 한다.

6. [major] D2 “claim당 독립 소스 수 하한”은 낮은 난이도가 아니다  
근거: 현재 `AtomicClaim.provenance`는 독립 도메인이 아니라 내부 claim source enum 병합이다: `engine/contracts/packets.py:160-174`. `NewsItem`에는 URL/source_name이 있지만 claim에는 `ref` 문자열 하나만 있다: `engine/contracts/packets.py:225-234`, `engine/contracts/packets.py:173-174`. RA 개선안은 source span과 독립 출처 카운트를 별도 §3로 잡았다: `docs/2026-07-06-ra-system-improvement-plan.md:116-125`.  
제안: D2를 RA §3과 병합하라. 먼저 `ref_domain/ref_span/source_grade` 같은 계약을 추가하고, 그 다음 하한을 A/B하라.

7. [major] A5 적응형 종료·심화는 P2가 아니라 P3에 가깝다  
근거: `_MAX_ROUNDS = 2`는 answerability 보완검색과 REFLECT가 공유한다: `engine/orchestrator.py:45`, `engine/orchestrator.py:284-304`, `engine/orchestrator.py:326-383`. `EnvelopeMeta.round`는 패킷과 UI layer에 관통된다: `engine/contracts/packets.py:48-52`, `engine/orchestrator.py:48-49`. depth 추가는 비용뿐 아니라 round 의미, 캐시, layer 교체 규칙을 바꾼다.  
제안: 조기 종료만 P2로 쪼개고, depth 추가는 P3로 내려라.

8. [major] RISK 라우팅 초기값이 위험하다  
근거: 계획은 사건 해석에서 RISK를 끈다: `docs/workflow-routing-plan.html:323-330`. 그러나 현행 RISK는 tier 3 판단 질문만 통과하고, bear case를 코드가 grounded/scenario로 라벨링한다: `engine/stages/risk.py:36-67`. 사건 해석도 원인론/시장 반응/반대 설명이 필요한 경우가 많고, RA 계획도 RISK 근거 다양성을 미해결 약점으로 둔다: `docs/2026-07-06-ra-system-improvement-plan.md:158-160`.  
제안: “event_interpretation + 원인/시장영향/전망 포함”이면 RISK lite를 켜라. 단순 과거 사실만 끄는 식으로 조건을 좁혀라.

9. [major] 섹터 메모리를 “산업 분석 1차 소스”로 두는 것은 현재 구현과 맞지 않는다  
근거: 현행 `sector_rag`는 질문 문자열로 14일 카드 검색을 하고, 결과를 synth/audit 증거로 넣을 뿐 claim table의 1차 source로 승격하지 않는다: `engine/orchestrator.py:214-232`, `engine/orchestrator.py:421-427`. 계획 표는 산업 분석에서 섹터 메모리를 “1차 소스”라고 둔다: `docs/workflow-routing-plan.html:325`.  
제안: sector memory는 “보조 맥락/관측 카드”로 표기하라. 1차 소스 승격은 source_grade와 원문 provenance가 claim 계약에 들어간 뒤 검토해야 한다.

10. [major] C1 평가 하네스가 LLM 심판 편향 문제를 스스로 해결하지 못한다  
근거: 계획은 C1을 rubric + LLM 심판으로 P1 선행 과제라고 한다: `docs/workflow-routing-plan.html:211-214`, `docs/workflow-routing-plan.html:350-354`. 같은 계획은 LLM 심판 단독 금지를 말한다: `docs/workflow-routing-plan.html:155-158`, `docs/workflow-routing-plan.html:286-287`. 근거 문서도 TNR 수치 외삽 주의를 명시한다: `docs/2026-07-08-agentic-workflow-patterns-survey.md:28-32`.  
제안: C1은 “작은 골든셋 + 코드 지표 + 수동 샘플링”으로 정의하라. LLM judge는 보조 신호로만 둬야 한다.

11. [minor] 근거 강도 표현이 여러 곳에서 과하다  
근거: A1 근거는 수학·논리 도메인 프리프린트이고 금융 외삽 미검증이라고 원 문서가 경고한다: `docs/2026-07-08-agentic-workflow-patterns-survey.md:19-26`. A5의 -0.6%는 독립 재현 없는 2025-10 프리프린트다: `docs/2026-07-08-agentic-workflow-patterns-survey.md:34-38`. OpenBB의 계층화는 제품 컨텍스트 우선순위이지 kg.db/cache/web 순서의 직접 실험이 아니다: `docs/2026-07-08-agentic-workflow-patterns-survey.md:91-94`.  
제안: 계획 본문에서 “근거 강함”을 “구현 패턴 확인”과 “효과 실증”으로 분리하라.

## 우선순위 이의

- §5 유형 라우팅은 P1에서 내려야 한다. kg_search, source span, source count, retrieval_quality가 없으면 차등표의 핵심 칸들이 공중에 떠 있다.
- D1은 최우선 P1이 맞지만 “라우팅과 결합”이 아니라 RA 개선안 §1로 독립 선행해야 한다.
- D2는 P1 단독 항목이 아니다. RA §3의 claim strength/source span과 같은 변경이다.
- A4는 P2가 아니라 A3와 함께 P1 후보가 더 맞다. 현재 retry_directive reason은 있지만 복구 단계가 빈약하고, 적용 지점은 이미 `RetryDirective.reason/queries`로 존재한다.
- A5는 조기 종료만 P2, depth 추가는 P3.
- C2/C3는 운영 리스크가 커서 P2로 너무 빠르다. 시장 데이터 저장 금지, 만료, 사용자별 격리, 오염 제거 정책이 먼저다.

## 누락

- 오분류 처리: TRIAGE 확장에 confidence/unknown/abstain이 없다. 현재 `TriageResult`는 route와 fresh flag뿐이다: `engine/stages/triage.py:20-24`.
- 프로필 승급 규칙: “PLAN이 승급만 가능”은 보수적이지만 비용 폭주를 만든다. 승급 사유를 layer/meta에 남기고, 승급 가능한 필드 범위를 제한해야 한다.
- 프로필과 tier 충돌: 현행 tier는 G2/G4/RISK를 직접 제어한다: `engine/stages/verify.py:195-217`, `engine/stages/risk.py:36-41`. question_type과 tier의 우선순위가 계획에 없다.
- 운영 예산: P1 묶음은 C1, 라우팅, A1/A2/A3, D1/D2를 동시에 건드린다. 비용·지연·품질 회귀를 분리 측정할 실험 순서가 없다.
- 테스트 전략: `engine/tests`는 stage 단위 회귀가 많지만 profile matrix 테스트 계획이 없다. 최소한 5유형 × 핵심 불변식 테스트가 필요하다.
- UI/layer 호환: `LAYER_NAMES`는 고정이고 profile/skip reason layer가 없다: `engine/contracts/packets.py:20-24`.
- never-raise 보존: 스테이지 생략을 “안 돌림”으로 구현하면 fallback packet/status semantics가 흔들린다. skipped packet을 fan-in에 계속 넣을지 명시해야 한다.
- 개인정보/메모리 오염: C2/C3는 장기 메모리 저장 정책과 삭제/만료/사용자 스코프가 빠졌다.

## 좋은 점

- CALC, claim table, VERIFY, RISK, AUDIT를 버리지 않는 방향은 맞다.
- “분류만 하고 라우팅에 안 쓰는” 함정을 지적한 점은 현행 tier 구조에 정확히 맞는다.
- dexter에서 가져올 것과 버릴 것을 분리한 판단은 대체로 건전하다.
- 차등표를 초기값으로 두고 측정하겠다는 태도는 좋다. 다만 그 전에 적용 가능한 계약과 지표를 먼저 깔아야 한다.
