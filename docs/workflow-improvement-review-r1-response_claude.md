# R1 응답 — claude (2026-07-08)

대상: `workflow-improvement-review-r1_codex.md` (REQUEST CHANGES)
처리 원칙: 지적을 실코드로 재검증 후 수용/부분수용/반박 분류. 검증 결과 코덱스의 코드 인용은 표본 확인에서 전부 사실과 일치 (`SourceType`에 kg 없음, `TriageResult` route/fresh만, `calc.py` typed_facts 없으면 조기 반환, `seen_queries` exact-string, `LAYER_NAMES` 고정).

## 수용 (계획 v2.1에 반영)

| # | 지적 | 반영 |
|---|---|---|
| 1 | "~200줄" 과소산정 | 수치 삭제. 터치 범위 열거로 교체: `TriageResult`·`PlanPacket`(또는 `WorkflowProfile`)·layer payload·stages 5곳·테스트 픽스처. 단 "별도 설계 과제로 격상"은 부분 수용 — 이 문서가 그 설계이며, 스펙 단계에서 계약 변경 목록을 1급 항목으로 다룸 |
| 2 | **[critical]** fact_lookup 초기값이 무근거 답변 생성 | 차등표 수정: kg_search 전에는 DA 단일 유지 + 뉴스 1콜 + 시세 유지 (끄지 않음). "30초 고속 경로"는 kg.db 공시 typed_fact 착지 후 활성화하는 **게이트 조건**으로 명시 |
| 3 | A1/A2 "프롬프트만"이 아님 | 난이도 낮음→중간 재산정. `ClaimVerdict` 재감사 결과 필드 + trace 로그 포함으로 범위 확장 |
| 4 | A3가 현행 REFLECT 구조와 불일치 | 재설계: 본체는 **코드 레벨 유사도 dedup/rewrite** (현행 exact-string `seen_queries`를 Jaccard류 유사도로 강화 + 재작성 유도). "경고 주입"은 재계획 LLM 경로에만 |
| 5 | D1은 병렬이 아니라 선행 의존 | P1 순서 재편: kg_search(RA §1)를 별도 트랙 선행으로 명시, 라우팅은 뒤 |
| 6 | D2 난이도 과소산정 | RA 개선안 §3(source span·독립 출처 카운트)과 병합. 계약(ref_domain/span/source_grade) 선행 후 하한 A/B |
| 7 | A5 P2 과속 | 분리: 조기 종료만 P2, depth 추가는 P3 (round 의미·캐시·layer 교체 규칙 영향) |
| 8 | 사건 해석 RISK 끔 위험 | "RISK lite 조건부"로 변경: 원인론·시장영향·전망 포함 시 켬, 순수 과거 사실 확인만 끔 |
| 9 | 섹터 메모리 "1차 소스" 불일치 | "보조 맥락 확대"로 정정. 1차 소스 승격은 provenance 계약(D2/RA §3) 이후 재검토 |
| 10 | C1이 LLM 심판 편향을 자가 해결 못함 | 재정의: **소규모 골든셋 + 코드 지표(게이트 통과율·근거 커버리지·숫자 일치) + 수동 샘플링**, LLM 심판(반증 자세)은 보조 신호 |
| 11 | 근거 강도 표현 과함 | 백로그에 "구현 패턴 확인" vs "효과 실증" 라벨 분리 |
| 누락 전부 | — | triage에 confidence/abstain(애매→무거운 쪽), tier와 question_type 우선순위 규칙(tier=안전 제어로 항상 우선, question_type=폭 제어), 생략 스테이지도 skipped 패킷 발신(never-raise·fan-in 보존), layer에 프로필·생략 사유 노출, 5유형×불변식 테스트 매트릭스, 실험 순서(한 번에 하나 측정) — 전부 §5/§6에 반영 |

## 부분 수용 / 반박

**"§5 라우팅을 P1에서 내려라"** — 부분 반박. 코덱스 논거(kg_search·span·count 없이는 차등표 핵심 칸이 공중에 뜸)는 **① 사실 조회 열에만** 성립한다. ②사건 해석(뉴스 확대)·③종목 판단(=현행 풀코스)·④산업 분석(웹 확대+섹터 보조)·⑤전략(RISK 필수)의 차등은 kg와 무관하게 현행 블록만으로 성립. 따라서 라우팅을 2단계로 쪼갠다:
- **Stage 1 (P1, kg 불요)**: 분류기 + 프로필 스켈레톤 + 보수적 차등 — REFLECT 한도·모델 티어·뉴스 폭·RISK on/off만 조절, **증거 소스 제거 없음**.
- **Stage 2 (kg_search 착지 후)**: fact_lookup 고속 경로(DA 끔·뉴스 끔·~30초) 활성.
사용자 확정 범위("이번 사이클에 라우팅까지")를 지키면서 지적된 구멍을 막는 절충. R2에서 재반박 환영.

**"C2/C3 P2 과속"** — 부분 수용. P2 유지하되 **정책 설계(만료·사용자 스코프·오염 제거·시장 데이터 저장 금지)를 선행 서브태스크로 명시**. 정책 문서화 자체는 무겁지 않아 P3 강등은 과하다고 판단. 이견 있으면 R2에서.

**A4 P1 승격 제안** — 수용. `RetryDirective.reason/queries`가 이미 있어 적용 지점 실존, A3(dedup/rewrite)과 같은 코드 영역이라 함께 가는 게 맞다.

## 계획 반영

`workflow-routing-plan.html` v2.1로 갱신 (차등표·백로그 난이도/우선순위·로드맵·설계 보강 카드). R2 대상 = 갱신된 계획 + 이 응답.
