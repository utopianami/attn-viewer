# 메모리 섹터 체인 답변 설계 — Thesis 레이어 + 사건 기반 eval (v2)

작성일: 2026-07-20 (v2 — codex r1 리뷰 반영, docs/memory-chain-review-r1_codex.md)
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

#### 케이스셋

- `engine/evals/golden_chain.jsonl` — 최근(2026-06~07) 실제 사건 기반 **24문항**
  (사건 유형·영향 경로·긍정/부정을 층화해 **dev 16 + holdout 8** 분리, holdout은 프롬프트
  튜닝에 사용 금지, 성공 판정은 holdout 기준). 사건은 섹터 카드 저장소에서 실제 발생 건을
  골라 구성 (기억으로 사건을 만들지 않는다).
- 케이스 스키마:

```json
{
  "id": "cj-01",
  "type": "chain_judgment",
  "split": "dev | holdout",
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

#### as_of 강제 (미래 정보 누출 차단) — r1 #7

- `run_qa`에 `knowledge_cutoff` 실행 인자 추가 (모델 추론 아님 — 코드 강제).
- eval 모드에서 카드 검색(`sector/retrieve.py`)·지표 조회(`sector/store.py`)·thesis 조회에
  `cutoff` 인자를 관통시켜 `ts <= as_of`만 노출. thesis는 append-only revision이므로
  `valid_from <= as_of`인 최신 revision을 재생.
- 답변 내 `as_of` 이후 데이터 인용은 `as_of_violation`으로 코드 카운트 — **0 필수**.
- 외부 뉴스 검색 경로는 cutoff 강제가 불가하므로, eval 실행 시 수집 시점 필터
  (RA 문서 published_at <= as_of)로 차단하고 리포트에 잔여 위험을 명시.

#### 채점 — r1 #8, #9, #10

- 실행기: `run_eval.py --suite chain` 추가 (기존 `golden.jsonl` 경로는 불변).
- 저지: **교차 provider** — 합성이 Claude(Opus/Fable) 계열이므로 저지는 **gpt-5.5**.
  self-preference 차단.
- 저지 입력: 답변 + 루브릭 + **frozen evidence bundle**(as_of 시점 카드·지표 snapshot).
  근거 실재성(인용이 bundle에 존재하는가)까지 판정 — 유창한 허위 체인에 점수 주지 않음.
- 저지 출력 계약 `ChainJudgeResult`:

```json
{
  "case_id": "cj-01",
  "axes": {
    "mechanism":  {"score": 0, "reason": "..."},
    "state_link": {"score": 1, "reason": "..."},
    "verdict":    {"score": 1, "reason": "..."},
    "evidence":   {"score": 0.5, "matched": ["..."], "missing": ["..."]},
    "countercase": {"score": 0, "reason": "..."}
  },
  "judge_model": "gpt-5.5", "judge_prompt_version": "cj-v1", "raw": "..."
}
```

  - `evidence` 축은 부분 점수: matched/total. 나머지 축은 0/1.
  - invalid JSON·타임아웃: 1회 재시도, 재실패 시 해당 케이스 `score=null`로 리포트
    (0점 처리 금지 — 노이즈 오염 방지).
  - **반복 채점 2회**, 축 불일치 시 3회차로 타이브레이크. holdout 비교에는 bootstrap CI 병기.
  - baseline/candidate 비교는 **paired blind**: 두 답변을 같은 시점에 무작위 순서로 재채점.
- 리포트(`evals/out/report-*.md`)에 축별 평균 + 코드 SHA·golden snapshot hash·
  모델/프롬프트 버전 기록.
- **베이스라인을 개선 착수 전에 측정** — 이후 2·3부의 효과를 전후 비교.

### 2부. Thesis("현재 판") 레이어 — 완전 자동

- 신규: `engine/sector/thesis.py`, 저장 `storage/rag/memory_sector/theses.jsonl`
  (**append-only revision** — `valid_from`, `input_snapshot` 포함, eval 재생용. r1 #7)
- 시드 가설은 코드에 고정 (~8개, RAG 계획 Thesis Monitor 기반):
  HBM 공급 타이트 / 하이퍼스케일러 CAPEX 국면 / 프론티어 자금 학습→추론 이동 /
  토큰 수요 성장 / 메모리 가격 사이클 국면 / 공급과잉(overbuild) 리스크 /
  중국 경쟁 리스크 / NAND 회복 분리
- 스키마 (r1 #1, #2, #5 반영):

```yaml
ThesisRevision:
  id: string                  # 시드 고정 slug
  claim: string               # 가설 문장
  axis: SectorAxis            # 기존 contracts.py enum 재사용 (A|A_prime|B|C|C0|E|P|market)
  selectors:                  # 결정적 thesis 선택용 — queryplan 산출물과 매칭
    entities: string[]
    metrics: string[]
    segments: string[]        # hbm|dram|nand|...
    event_types: string[]
  priority: int               # 동률 시 선택 순서
  assessment: strengthening | weakening | mixed     # 방향 — 실패 시에도 보존
  freshness: fresh | degraded | stale               # 신선도 — 방향과 분리
  statements:                 # summary 자유문자열 대신 주장 단위 구조화
    - text: string            # 숫자 포함 금지 (코드 검증 — 숫자 패턴 검출 시 드롭)
      supporting: [{card_id, canonical_url, doc_hash, span, source_grade}]
      contradicting: [{card_id, ...}]
  key_metrics: [{metric, observation_id, latest_value, unit, ts, meta, source}]
  required_inputs:            # thesis별 필수 수집기·지표·허용 지연 선언
    - {metric: string, max_age_days: int}
  valid_from: string
  input_snapshot: {card_index_hash, metrics_hashes}
  updated_at: string
```

- 갱신 잡: 일일 수집 사이클 후 가설별 LLM 1콜(sonnet)이 최근 14일 카드 + 지표 요약을 읽고
  새 revision 생성.
- **완전 자동 가드레일** (r1 #1, #2, #3):
  1. statement별 supporting **2개 이상 + 서로 다른 문서·발행 주체**(canonical URL·doc_hash로
     dedupe) 필수 — 미달 statement는 코드가 드롭. 빈 `raw_quote` 카드, D급, 자동 보존 공시는
     지지 근거 수에서 제외. `interpreted_signal`(LLM 해석)은 근거로 세지 않고 원문 span만 인정.
  2. `required_inputs` 지표가 `max_age_days`를 넘거나 해당 수집기 실패 시: **갱신하지 않고
     직전 정상 revision 유지** + `freshness: degraded|stale`만 변경. 저빈도 지표(분기 CAPEX)는
     max_age를 길게 선언해 매일 stale이 되지 않게 한다.
  3. statement 텍스트에 **숫자 금지** (코드 검증). 숫자는 `key_metrics`(관측 ID·meta·source
     보존)에서만 → 파이프라인에는 `TypedFact`로 승격되어 ClaimTable·[결정적 수치] 절 경유.
     G2 정합성: thesis 유래 숫자도 기존 앵커 대조 경로를 탄다.
  4. thesis 문장은 답변의 "배경 판" 절로만 주입되고, **AUDIT의 evidence_texts에 넣지 않는다**
     (생성문 자기 검증 차단. r1 #3).

### 3부. 체인 합성 — 파이프라인 주입

- thesis 선택: queryplan 산출물(entities·metrics·event_types) × thesis `selectors` 교집합
  스코어 + priority — **결정적, LLM 없음** (r1 #5). 상위 1~3개 주입.
- **ChainPacket — VERIFY 이전 생성** (r1 #4): 사건 해석형·판단형 질문 한정, 경량 LLM이
  사건을 타입화하되 산출물은 코드 검증 가능한 계약:

```yaml
ChainPacket:
  event: string
  mechanism: string
  edges:                      # 기존 judge.py 인과 그래프 edge enum 재사용 — C→B→A 고정 아님
    - {edge: SectorEdge, kind: observed | inference,
       supporting_card_ids: string[], metric_fact_ids: string[],
       contradictions: string[]}
  thesis_relation: [{thesis_id, relation: supports | contradicts}]
  verdict: string
```

  - `observed` edge는 근거 ID 필수 — 없으면 코드가 `inference`로 강등.
  - RISK는 VerdictPacket의 **verified 근거만** 입력받는다 (현행 "존재하는 claim ID" 판정 강화).
- SYNTHESIZE 형식: 긍정/부정 시나리오 각각에 **근거 체인 + 인용 지표 + 유효/기각 조건** —
  프롬프트 지시 + **코드 후검증** (r1 #4): 시나리오 절에 체인·조건 존재를 검사, 미충족 시
  1회 재합성, 재실패 시 리포트 플래그.
- 플레이북 게이트 연결 (r1 #6): gate 계약에 **선택 필드** 추가 —
  `{metric_id, selector, aggregation, window, comparator, threshold, unit, max_age_days}`.
  채워진 gate만 코드가 지표 조회 후 `GateResult(value, verdict, evidence_id | unavailable)`
  생성. 대응 지표가 없거나 단위 불일치(예: 재고 "지수" vs "주수")면 **unavailable** —
  LLM이 유사 지표를 대입하는 것 금지. 기존 문자열 gate는 그대로 동작 (하위 호환).

### 4부. 검증·롤아웃

- `chain_judgment` eval 전후 비교 (1부 베이스라인 대비, holdout·paired blind).
- 배포는 `pm2 restart attn-engine`만.
- 배포 세션에서 `docs/workflow-review.html` 현행화 + 스크린샷 확인.

## 전역 제약

- **매 단계(1~4부 각각) 완료 시 codex 교차 리뷰** — 기존 패턴(`codex` CLI,
  docs/*-review-r*_codex.md 왕복 문서)을 따른다. 리뷰 반영 전 다음 단계 착수 금지.
- 숫자 불변식 유지: LLM 암산 숫자는 답변 진입 불가. thesis 유래 숫자는 TypedFact 경로만.
- thesis는 사실 출처가 아니라 배경 판 — 주입 프롬프트에 경계 문구 필수 (플레이북과 동일 원칙).
- 섹터 수집기 실패는 thesis 갱신을 막지 않는다 — 단, 해당 thesis는 직전 정상 revision 유지
  + freshness 강등 (r1 #2).
- 엔진 재시작은 pm2만, pkill 금지.
- 커밋 메시지는 작은따옴표 감싸기.

## 성공 기준 (r1 #10, #11 반영 — 형식 개선만으로 통과 불가하게 코드 지표 병행)

**LLM 저지 지표 (holdout, paired blind, bootstrap CI):**
- `mechanism`·`state_link` 각 +0.3 이상 (예: 0.2 → 0.5). 미달 시 3부 재작업 후 재측정.

**코드 지표 (배포 게이트 — 저지 없이 코드로 계산):**
- `as_of_violation` = 0
- thesis 유래 unsupported numeric = 0 (statement 숫자 검출 + TypedFact 경로 밖 숫자)
- `grounded_edge_ratio` (ChainPacket edge 중 근거 ID 보유 비율) — 베이스라인 대비 상승,
  목표 0.7 이상
- statement 독립 출처 비율(서로 다른 발행 주체 2+) = 1.0 (가드레일이므로 정의상 충족 — 위반은 버그)
- stale/degraded thesis 사용률 리포트 (게이트 아님, 추세 관찰)

**회귀:**
- 기존 golden.jsonl verified_ratio·keyword 유지.
