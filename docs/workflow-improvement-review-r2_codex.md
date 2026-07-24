# Codex Review R2 — 에이전틱 워크플로우 개선 계획 v2.1

## Verdict

APPROVE with nits — R1 blocking 대부분은 v2.1에 반영됐다. 다만 Stage 1 라우팅은 “품질 영향 없는 보수적 차등”으로 보려면 프로필별 불변식과 평가 게이트를 더 명시해야 한다.

## R1 반영 확인표

| 항목 | 반영 여부 | 비고 |
|---|---:|---|
| R1-1 `~200줄` 과소산정 | 반영 | 수치 삭제, `TriageResult`·프로필 계약·orchestrator·stages·layer·tests 범위 명시됨. `docs/workflow-routing-plan.html:352` |
| R1-2 fact_lookup 고속 경로 위험 | 반영 | Stage 1은 DA 단일·뉴스 1콜 유지, Stage 2는 kg 착지 후로 게이트됨. `docs/workflow-routing-plan.html:305`, `:333` |
| R1-3 A1/A2 프롬프트만 아님 | 반영 | `ClaimVerdict` 필드 + trace 로그 포함으로 범위 확장. `docs/workflow-routing-plan.html:150` |
| R1-4 A3 REFLECT 구조 불일치 | 반영 | 경고 주입 중심에서 코드 레벨 유사도 dedup/rewrite로 재설계. 현행 exact-string 구조와 맞음. `engine/orchestrator.py:253`, `:345` |
| R1-5 D1은 선행 의존 | 반영 | kg_search를 선행 트랙으로 분리, Stage 2 전제화. `docs/workflow-routing-plan.html:243`, `:362` |
| R1-6 D2 난이도 과소산정 | 반영 | RA §3 source span/source count와 병합, 계약 선행 후 A/B. `docs/workflow-routing-plan.html:249` |
| R1-7 A5 P2 과속 | 반영 | 조기 종료 P2, depth 추가 P3로 분리. `docs/workflow-routing-plan.html:174` |
| R1-8 event RISK 끔 위험 | 부분반영 | RISK lite 조건부로 수정됨. 다만 “원인론·시장영향·전망 포함” 판정 필드가 아직 프로필 계약에 명시되지 않음. `docs/workflow-routing-plan.html:330`, `:333` |
| R1-9 sector memory 1차 소스 오류 | 반영 | “보조 맥락 확대”로 정정. `docs/workflow-routing-plan.html:324`, `:333` |
| R1-10 C1 LLM judge 편향 | 반영 | 골든셋 + 코드 지표 + 수동 샘플링, LLM judge 보조로 재정의. `docs/workflow-routing-plan.html:211` |
| R1-11 근거 강도 과장 | 반영 | 구현 패턴 확인 vs 효과 실증 분리. `docs/workflow-routing-plan.html:142` |
| 우선순위 이의: 라우팅 P1 강등 | 부분반영 | Stage 1/2 분할로 완화. P1 유지 자체는 수용 가능하나, Stage 1 차등의 안전 조건은 추가 명시 필요. |
| 우선순위 이의: D1 최우선 선행 | 반영 | kg_search/news 통합 선행 트랙화. |
| 우선순위 이의: D2 단독 P1 아님 | 반영 | P2 + RA §3 병합. |
| 우선순위 이의: A4 P1 승격 | 반영 | A3와 함께 P1. `docs/workflow-routing-plan.html:164`, `:363` |
| 우선순위 이의: A5 분리 | 반영 | 위와 같음. |
| 우선순위 이의: C2/C3 P2 과속 | 부분반영 | 정책 설계 선행은 들어갔지만 구현 승인 조건은 아직 약함. |
| 누락: triage confidence/abstain | 반영 | confidence, abstain → 풀코스. `docs/workflow-routing-plan.html:338` |
| 누락: 프로필 승급 규칙 | 반영 | 승급 사유 meta, 필드 범위 제한. `docs/workflow-routing-plan.html:342` |
| 누락: profile/tier 충돌 | 반영 | tier 안전 제어 우선, question_type 폭 제어. `docs/workflow-routing-plan.html:340` |
| 누락: 운영 예산/실험 순서 | 반영 | C1 선행, 실험 한 번에 하나. `docs/workflow-routing-plan.html:142`, `:363` |
| 누락: profile matrix 테스트 | 반영 | 5유형 × 핵심 불변식 테스트 명시. `docs/workflow-routing-plan.html:343` |
| 누락: UI/layer 호환 | 반영 | plan layer 우선 검토로 노출. `docs/workflow-routing-plan.html:341` |
| 누락: never-raise/skipped packet | 반영 | skipped 패킷 fan-in 발신 명시. `docs/workflow-routing-plan.html:341` |
| 누락: C2/C3 개인정보/오염 | 부분반영 | 만료·사용자 스코프·오염 제거·시장 데이터 저장 금지 언급. 삭제/열람/무효화/테스트 기준은 아직 없음. |

## 부분 반박 2건에 대한 판정

**(a) 라우팅 2단계 분할: 부분 동의.**  
fact_lookup 고속 경로를 kg_search 이후 Stage 2로 미룬 점은 R1의 핵심 우려를 대부분 해소한다. 현행 CALC는 `table.typed_facts`가 없으면 빈 결과를 반환하므로 `engine/stages/calc.py:93`처럼 kg 전 DA/뉴스를 끄면 위험했는데, v2.1은 이 부분을 막았다.

다만 Stage 1도 완전히 “kg 불요 안전 차등”은 아니다. REFLECT 한도 축소, DA 이중→단일, 뉴스 폭 조절, RISK on/off, 검증 “숫자·시점만”은 모두 답변 품질에 직접 영향을 준다. 특히 현행 orchestrator는 3브랜치 fan-out이 하드코딩되어 있고 `engine/orchestrator.py:177`, 프로필 필드가 `PlanPacket`에 없으며 `engine/contracts/packets.py:103`, RISK는 tier만 보고 켜진다 `engine/stages/risk.py:36`. 따라서 P1 유지는 가능하지만, Stage 1 승인 조건은 “증거 소스 제거 없음”만으로 부족하다. 최소한 각 프로필의 생략/축소 가능 필드, tier override 금지, event RISK lite 판정 입력, C1 통과 기준을 스펙에 넣어야 한다.

**(b) C2/C3 정책 설계 선행 + P2 유지: 조건부 동의.**  
정책 설계를 P2 선행 서브태스크로 두는 것은 괜찮다. 그러나 P2 항목명이 여전히 “노트 + flush” 구현으로 읽히므로, 정책 설계가 통과하기 전에는 저장/주입 구현을 시작하지 않는다고 못박는 편이 낫다. 이 레포는 문서/분석 저장을 사용자 스코프로 강제하고 있고, 실제 서버에도 사용자별 storage 경로가 섞여 있다. 메모리는 그보다 오염 위험이 크므로 `storage/users/<username>/...`, 만료, 삭제, 시장 데이터 금지, 프롬프트 주입 방지, 회귀 테스트가 acceptance criteria여야 한다.

## 신규 지적

- [major] Stage 1 “증거 소스 제거 없음”과 차등표가 완전히 일치하지 않는다. 표에서는 fact lookup의 sector memory 끔, DA 단일, 뉴스 1콜, RISK 끔, 검증 축소가 들어간다. 이것이 “소스 제거가 아니라 폭 축소”라면 용어를 분리해야 한다. 지금 문구대로면 구현자가 Stage 1을 과감히 줄여도 되는 것으로 오해할 수 있다.

- [major] RISK lite 조건의 계약이 비어 있다. “원인론·시장영향·전망 포함 시”는 5종 question_type만으로 판정되지 않는다. `TriageResult` 확장에 `risk_intent` 또는 `requires_countercase`류 필드를 넣거나, PLAN 승급 규칙에서만 켤지 정해야 한다.

- [minor] C1 설명과 로드맵 표현이 약간 어긋난다. 본문은 “소규모 골든셋 + 코드 지표 + 수동 샘플링”인데 로드맵은 “골든셋+코드 지표”로 줄어 있다. 수동 샘플링을 완료 기준에 유지하는 게 좋다.

## 남은 결정 항목

- Stage 1 라우팅을 P1로 승인하되, 프로필별 축소 가능 필드와 acceptance criteria를 먼저 고정할지.
- RISK lite 판정 필드를 TRIAGE에 둘지, PLAN 승급에 둘지.
- C2/C3는 P2 “정책 설계만”인지, 정책 승인 후 구현까지 같은 P2에 포함할지.
- C1의 최소 골든셋 규모, 코드 지표, 수동 샘플링 통과 기준.
