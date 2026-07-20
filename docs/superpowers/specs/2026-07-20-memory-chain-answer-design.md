# 메모리 섹터 체인 답변 설계 — Thesis 레이어 + 사건 기반 eval

작성일: 2026-07-20
승인: yvon (2026-07-20 대화)

## 문제

시나리오(긍정/부정) 답변에서 **근거 체인**이 약하다. 기대하는 체인:

```
사건 (예: 신규 프론티어 모델 발표, 마이크론 실적)
  → 메커니즘 분해 (추론 개선인가 학습 효율인가 / 수요 신호인가 공급 신호인가)
  → 현재 판과 대조 (프론티어는 지금 어디에 돈을 쓰는가, CAPEX 국면, 공급사 포지션)
  → 판단 (위협적이다/아니다, 어느 시나리오를 지지/반박하는가)
```

### 원인 진단 (2026-07-20 코드 확인)

- 섹터 카드(월 1,000장+)·지표 시계열(18종)·사이클 판정은 구현되어 SYNTHESIZE에 주입됨.
- 그러나 RAG 계획(docs/memory-rag-plan_codex.md)의 **Thesis 레이어("현재 판" 상태)가 미구현**.
  카드는 개별 사건, 지표는 개별 숫자일 뿐, "프론티어 자금이 학습→추론으로 이동 중" 같은
  종합 상태가 어디에도 없음 → 모델이 파라메트릭 지식으로 때움 → 미확인 수치·얕은 나열.
- 플레이북 게이트(예: "재고 주수 확인")는 절차만 주고 채울 판 정보가 없어 공회전.
- eval은 must_include/must_not 키워드 체크뿐 — 체인 품질이 측정되지 않음.

### 유저 피드백 근거 (storage/users/*/feedback)

- jihwan: [확인되지 않은 수치] 다수 — 레퍼런스인지 할루시네이션인지 구분 불가
- yvon: too_shallow (맘다니 — 직격 섹터·2차 파급까지 원함), 하이닉스 ADR 미발견
- woojin: 통화 착오 — 기대 답안: 숫자 계산 → 가정의 한계 → 2차 파급 추적

## 결정 사항 (유저 확정)

| 항목 | 결정 |
| --- | --- |
| 스코프 | 메모리 섹터 먼저 (기존 `sector_rag_enabled` 프로필 게이트 유지) |
| 정답지 용도 | **측정용 eval 셋** — 답변 주입용 아님, 파이프라인이 스스로 도달해야 함 |
| 수치 깊이 | 근거 체인형 — 사건 메커니즘 분해 + 현재 판 연결 + 판단. 밸류에이션 계산 강제 아님 |
| Thesis 관리 | **완전 자동** — 수동 검수 없음, 구조적 가드레일로 오염 차단 |
| 진행 방식 | **매 단계 codex 교차 리뷰** 후 다음 단계 진행 |

## 아키텍처

구현 순서 = 배포 단위. 각 부는 독립 배포 가능.

### 1부. 사건 기반 정답지 eval (`chain_judgment`)

- `engine/evals/golden_chain.jsonl` — 최근(2026-06~07) 실제 사건 12~15개.
  사건은 섹터 카드 저장소에서 실제 발생 건을 골라 구성 (기억으로 사건을 만들지 않는다).
- 케이스 스키마:

```json
{
  "id": "cj-01",
  "type": "chain_judgment",
  "question": "질문 텍스트",
  "as_of": "2026-07-14",
  "rubric": {
    "mechanism": "사건을 메커니즘으로 분해했는가 (예: 추론 개선 vs 학습 효율)",
    "state_link": "현재 판(프론티어 자금 사용처·CAPEX 국면·공급사 포지션)과 연결했는가",
    "verdict": "위협적이다/아니다 등 방향 판단을 명시했는가",
    "evidence": ["이 답에 나와야 할 지표·근거 목록"],
    "countercase": "반대 의견이 실근거와 함께 있는가"
  },
  "must_not": ["금지 표현"]
}
```

- 채점: LLM 저지(opus-4.8, 답변 생성 모델과 분리)가 루브릭 5개 축을 각 0/1로 판정 +
  기존 keyword/verified 메트릭 병행.
  리포트에 축별 평균 추가 (`evals/out/report-*.md`).
- **베이스라인을 개선 착수 전에 측정** — 이후 2·3부의 효과를 전후 비교.

### 2부. Thesis("현재 판") 레이어 — 완전 자동

- 신규: `engine/sector/thesis.py`, 저장 `storage/rag/memory_sector/theses.jsonl`
- 시드 가설은 코드에 고정 (~8개, RAG 계획 Thesis Monitor 기반):
  HBM 공급 타이트 / 하이퍼스케일러 CAPEX 국면 / 프론티어 자금 학습→추론 이동 /
  토큰 수요 성장 / 메모리 가격 사이클 국면 / 공급과잉(overbuild) 리스크 /
  중국 경쟁 리스크 / NAND 회복 분리
- 스키마:

```yaml
Thesis:
  id: string            # 시드 고정 slug
  claim: string         # 가설 문장
  axis: A|B|C|D|market
  status: strengthening | weakening | mixed | stale
  summary: string       # 현재 판 서술 3~5문장 (모든 주장에 카드 인용)
  supporting_card_ids: string[]
  contradicting_card_ids: string[]
  key_metrics: [{metric, latest_value, unit, ts}]
  updated_at: string
```

- 갱신 잡: 일일 수집 사이클 후 가설별 LLM 1콜(sonnet)이 최근 14일 카드 + 지표 요약을 읽고 갱신.
- **완전 자동 가드레일** (오염 차단, 수동 검수 대체):
  1. summary의 모든 주장은 실존 카드 ID 2개 이상 인용 필수 — 미달 주장은 코드가 드롭
  2. 신규 인용 근거가 없으면 갱신하지 않고 `stale` 플래그만 (LLM 기억 채움 차단)
  3. summary 속 숫자는 `key_metrics`(지표 관측값)에서만 — 대조는 코드(G2 패턴)
  4. thesis 텍스트는 답변의 "배경 판" 절로만 주입, [결정적 수치] 절 진입 금지 (기존 G2 불변식 유지)

### 3부. 체인 합성 — 파이프라인 주입

- sector_rag 경로 확장 (`engine/orchestrator.py` sector 블록):
  queryplan 엔티티·지표 → 관련 thesis 1~3개 선택해 컨텍스트 주입.
- 신규 체인 스텝 (사건 해석형·판단형 질문 한정, 경량 LLM):
  질문 속 사건을 타입화 — `{mechanism, impact_path(C→B→A 엣지), thesis_relation(지지/반박+id), verdict}`.
- SYNTHESIZE 프롬프트 형식 강제: 긍정/부정 시나리오 각각에
  **근거 체인 + 인용 지표 + 유효 조건/기각 조건** 필수.
- 플레이북 게이트 연결: 게이트 `operationalization`에 대응하는 지표가 있으면 값을 채워
  게이트 판정 가능하게 (공회전 해소).

### 4부. 검증·롤아웃

- `chain_judgment` eval 전후 비교 (1부 베이스라인 대비).
- 배포는 `pm2 restart attn-engine`만.
- 배포 세션에서 `docs/workflow-review.html` 현행화 + 스크린샷 확인.

## 전역 제약

- **매 단계(1~4부 각각) 완료 시 codex 교차 리뷰** — 기존 패턴(`codex` CLI,
  `runCodexSummary`/`codex exec`, docs/workflow-improvement-review-r*_codex.md 왕복 문서)을 따른다.
  리뷰 반영 전 다음 단계 착수 금지.
- 숫자 불변식 유지: LLM 암산 숫자는 답변 진입 불가 (CALC/지표 관측값만).
- thesis는 사실 출처가 아니라 배경 판 — 주입 프롬프트에 경계 문구 필수 (플레이북과 동일 원칙).
- 섹터 수집기 실패는 thesis 갱신을 막지 않는다 (독립 실패, stale 강등).
- 엔진 재시작은 pm2만, pkill 금지.
- 커밋 메시지는 작은따옴표 감싸기.

## 성공 기준

- `chain_judgment` 루브릭 축별 평균이 베이스라인 대비 상승 — 목표: mechanism·state_link 각 +0.3 이상
  (예: 0.2 → 0.5). 미달 시 3부 프롬프트·체인 스텝을 재작업하고 재측정.
- 기존 golden.jsonl 회귀 없음 (verified_ratio·keyword 유지).
- 미확인 수치 빈도 감소 (eval 수동 샘플링에서 확인).
