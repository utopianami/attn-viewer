# 메모리 섹터 체인 답변 설계 — Thesis 레이어 + 사건 기반 eval (v3)

작성일: 2026-07-20 (v3 — codex r2 반영, docs/memory-chain-review-r2_codex.md)
승인: yvon (2026-07-20 대화 — 스펙 왕복은 claude↔codex에 위임)

## 문제

시나리오(긍정/부정) 답변에서 **근거 체인**이 약하다. 기대하는 체인:

```
사건 (예: 신규 프론티어 모델 발표, 마이크론 실적)
  → 메커니즘 분해 (추론 개선인가 학습 효율인가 / 수요 신호인가 공급 신호인가)
  → 현재 판과 대조 (프론티어는 지금 어디에 돈을 쓰는가, CAPEX 국면, 공급사 포지션)
  → 판단 (위협적이다/아니다, 어느 시나리오를 지지/반박하는가)
```

### 원인 진단 (2026-07-20 코드 확인)

- 섹터 카드·지표 시계열·사이클 판정은 구현되어 SYNTHESIZE에 주입됨.
- 그러나 **Thesis 레이어("현재 판" 상태)가 미구현** — 카드는 개별 사건, 지표는 개별 숫자일 뿐,
  종합 상태가 없어 모델이 파라메트릭 지식으로 때움 → 미확인 수치·얕은 나열.
- 플레이북 게이트는 절차만 주고 채울 판 정보가 없어 공회전.
- eval은 키워드 체크뿐 — 체인 품질이 측정되지 않음.

### 유저 피드백 근거 (storage/users/*/feedback)

- jihwan: [확인되지 않은 수치] 다수 / yvon: too_shallow·하이닉스 ADR 미발견 /
  woojin: 기대 답안 = 숫자 계산 → 가정의 한계 → 2차 파급 추적

## 결정 사항 (유저 확정)

| 항목 | 결정 |
| --- | --- |
| 스코프 | 메모리 섹터 먼저 (`sector_rag_enabled` 프로필 게이트 유지) |
| 정답지 용도 | 측정용 eval 셋 — 답변 주입용 아님 |
| 수치 깊이 | 근거 체인형 (밸류에이션 계산 강제 아님) |
| Thesis 관리 | 완전 자동 — 구조적 가드레일로 오염 차단 |
| 진행 방식 | 매 단계 codex 교차 리뷰. **인간 라벨·수동 검수는 불가** (유저 확정) |

## 아키텍처

구현 순서 = 배포 단위. 각 부는 독립 배포 가능.

### 1부. 사건 기반 정답지 eval (`chain_judgment`)

#### 측정 범위 선언 (r2-B4)

이 eval은 **"주어진 증거에서 체인 구성 품질"**을 측정한다. 라이브 검색·수집 품질은 측정
범위 밖이며 기존 `golden.jsonl`이 담당한다. 따라서 실행은 **frozen bundle 모드**다:

- 케이스 생성 시점에 케이스별 **frozen evidence bundle**을 캡처해 저장
  (`engine/evals/bundles/cj-XX/` — as_of 시점의 섹터 카드·지표 관측·가격/매크로 값·
  thesis revision·RA 문서. 이후 불변).
- eval 실행은 섹터 검색·가격·매크로·thesis 조회를 bundle로 대체하고, 라이브 외부 검색
  (RA·REFLECT·Toss)은 **비활성화**. 재생 불가능한 경로를 끄는 것이 `as_of_violation=0`을
  실제로 보장하는 유일한 방법이다 (event-time 필터만으로는 늦게 적재된 데이터 누출을 못 막음).
- 날짜 불명 문서는 bundle 생성 시 **fail-closed 제외**.
- `as_of_violation` = 답변이 bundle 밖 데이터를 인용한 건수 (코드 검출) — **0 필수**.

#### 케이스셋

- `engine/evals/golden_chain.jsonl` — 최근(2026-06~07) 실제 사건 기반 **24문항**,
  사건 유형·영향 경로·긍정/부정 층화, **dev 14 + holdout 10**. holdout은 프롬프트 튜닝
  사용 금지, 성공 판정은 holdout 기준. 사건은 섹터 카드 저장소에서 실제 발생 건만 사용.
- 케이스 스키마: `{id, type, split, question, as_of, bundle_path, rubric{mechanism,
  state_link, verdict, evidence[], countercase}, must_not[]}` (v2와 동일 루브릭 5축).

#### 채점

- 실행기: `run_eval.py --suite chain` (기존 `golden.jsonl` 경로 불변).
- 저지: 교차 provider **gpt-5.5** (합성이 Claude 계열. DA에 GPT가 참여하나 최종 문장을
  쓰는 모델과 분리가 목적 — 한계는 리포트에 명시). 저지 입력은 답변 + 루브릭 + frozen bundle.
- **저지 self-test (인간 calibration 대체, r2-B8):** 결함을 심은 합성 답변 fixture 5개
  (mechanism 누락 / 조작 인용 / 미래 정보 사용 / countercase 없음 / 정상)를 저지가 전부
  정확 판정해야 본채점 진행. 실패 시 저지 프롬프트를 수정하고 재시도 — 채점 결과 폐기.
  근거: 유저가 수동 검수 불가를 확정했으므로 인간 라벨 셋은 만들 수 없다.
- 출력 계약 `ChainJudgeResult`: 축별 `{score, reason}` (evidence는 matched/total 부분 점수),
  `judge_model`·`judge_prompt_version`·`raw` 저장. invalid/타임아웃 1회 재시도 후 `null`.
- **paired-validity (r2-B8):** baseline/candidate **양쪽 모두 유효한 케이스만** 비교에 산입.
  유효 케이스 비율 90% 미만이면 결과 폐기하고 재실행.
- 반복 채점 2회 + 축 불일치 시 3회차 타이브레이크. 반복 run별 원시 결과 전량 저장.
- **edge 단위 entailment 패스 (r2-B7, r2 유보 재판정 수용):** 최종 답변 채점과 별개로,
  ChainPacket의 각 edge에 대해 저지가 "인용된 근거 span이 이 edge 주장을 지지하는가"를
  개별 판정 → `entailed_edge_ratio` 산출. 답변 유창성과 분리된 edge granularity 측정.
- 리포트에 축별 평균 + 코드 SHA·bundle hash·모델/프롬프트 버전 기록.
- **베이스라인을 개선 착수 전에 측정.**

### 2부. Thesis("현재 판") 레이어 — 완전 자동

- 신규: `engine/sector/thesis.py`, 저장 `storage/rag/memory_sector/theses.jsonl`
  (**append-only revision**, `revision_id`·`valid_from`·`input_snapshot` 포함).
- 시드 가설 ~8개 코드 고정 (HBM 타이트 / CAPEX 국면 / 프론티어 자금 학습→추론 /
  토큰 수요 / 가격 사이클 / 공급과잉 / 중국 경쟁 / NAND 분리).
- 스키마:

```yaml
ThesisRevision:
  id: string                  # 시드 slug
  revision_id: string         # {id}@{valid_from} — 참조는 revision 단위로 고정
  claim: string
  axis: string                # contracts.py SectorCard.axis와 동일 값 공간
  selectors: {entities: [], metrics: [], segments: [], event_types: []}
  priority: int
  assessment: strengthening | weakening | mixed
  statements:
    - statement_id: string
      text: string            # 수량 literal 금지 (식별자 HBM3E·DDR5 등은 허용, r2-R1)
      supporting:             # 2개 이상, publisher_id 2종 이상
        - {card_id, canonical_url, publisher_id, quote}
      contradicting:          # 같은 스키마 (없으면 빈 배열)
        - {card_id, canonical_url, publisher_id, quote}
  key_metrics: [{metric, observation_id, value, unit, ts, meta, source}]
  required_inputs: [{metric, max_age_days, min_count}]
  valid_from: string
  input_snapshot: {card_ids: [], metric_observation_ids: []}   # hash 아닌 ID 목록 — 재생 가능
  updated_at: string
```

- **freshness는 저장 필드가 아니라 파생 상태다** (r2 #2 append-only 충돌 해소):
  조회 시점에 `required_inputs` 대비 코드가 계산 — `fresh | degraded | stale`.
  수집기 건강성은 별도 collector ID 없이 **지표 최신성으로 판정** (지표가 수집기의 관측
  가능한 산출물이므로 — 이중 선언 제거).
- 갱신 잡: 일일 수집 사이클 후 가설별 sonnet 1콜, 최근 14일 카드 + 지표 요약 입력.
  required_inputs 불충족 시 새 revision을 만들지 않는다 (직전 revision이 그대로 최신 —
  freshness가 파생이므로 자동으로 degraded/stale 표시됨).
- **가드레일 (코드 검증, LLM 신뢰 없음):**
  1. `publisher_id` = canonical URL의 등록 가능 도메인 (코드 파생, LLM 입력 아님).
     statement별 supporting 2+ & publisher_id 2종+ — 미달 statement 드롭.
     빈 raw_quote·D급·자동 보존 공시 카드는 지지 수에서 제외. interpreted_signal 불인정.
  2. `quote`는 **해당 카드의 저장된 raw_quote/title의 부분문자열**임을 코드 검증 — 불일치
     시 해당 근거 무효. (문서 아카이브·span 좌표 인프라 없이 인용 조작을 차단하는 등가물.
     r2-B1의 doc_hash/span 요구는 이 검증으로 목적 달성 — 별도 문서 저장소는 미도입.)
  3. **key_metrics는 LLM이 metric 이름만 제안** — 코드가 store에서 최신 관측을 역참조해
     observation_id·value·unit·ts·meta·source를 **덮어쓴다** (r2-B2 세탁 차단).
  4. statement 텍스트 수량 literal 금지 — 검출 규칙: 단위·%·통화가 결합된 수치 또는 독립
     수사(數詞). 영문자와 결합된 식별자(HBM3E, DDR5, H100, gpt-5.5)는 허용 (r2-R1).
  5. thesis 문장은 "배경 판" 절로만 주입, AUDIT evidence_texts 불포함.
     주입 허용: fresh + degraded(라벨 병기). **stale은 주입 금지** (r2-B5).

### 3부. 체인 합성 — 파이프라인 주입

- **thesis 선택은 결정적** (r2-B5): 입력은 LLM queryplan이 아닌 **rule_plan** (기존
  extract_entities 기반). 스코어 = entities 일치×2 + metrics 일치×1 + event_types 일치×1.
  **0점 thesis 제외**, 동률은 priority. 상위 1~3개의 **revision_id**를 주입·기록.
- **ChainPacket** (VERIFY 이전 생성, 기존 패킷 계약 준수 — schema_version·EnvelopeMeta):

```yaml
ChainPacket:
  schema_version: string
  event: string
  mechanism: string
  edges:
    - edge_id: string
      edge: string                    # judge.py 인과 그래프 edge 값 공간
      kind: observed | inference
      supporting_card_ids: string[]   # 실존 검증 — 미실존 ID는 드롭
      metric_fact_ids: string[]       # TypedFact.id 참조 (섹터 관측 유래)
      contradicting_card_ids: string[] # 자유 문자열 아닌 card_id (r2-B3)
  thesis_relation: [{thesis_revision_id, relation: supports | contradicts}]
  verdict: string
```

  - 코드 검증: 인용 ID 실존 확인 → 미실존 드롭, supporting이 비면 `observed`→`inference`
    강등. **임의 ID로 grounded를 채울 수 없다** (r2-B7의 grounded_edge_ratio 반박 해소).
  - **VerdictPacket에 `chain_verdicts` 추가** (r2-B3): edge별
    `ChainEdgeVerdict{edge_id, grounded: bool, note}`. VERIFY가 산출, RISK·SYNTHESIZE·
    eval이 소비. RISK 입력은 verified claim + chain_verdicts로 강화.
- TypedFact 확장: 섹터 유래 fact에 `metric`·`observation_id`·`period` 필드 추가
  (schema_version 증가). G2 대조 시 metric 식별자까지 일치 요구 — 우연히 같은 숫자의
  타 지표 앵커링 차단 (r2 #3).
- SYNTHESIZE: 긍정/부정 시나리오 각각 근거 체인 + 인용 지표 + 유효/기각 조건 —
  프롬프트 + 코드 후검증(미충족 1회 재합성, 재실패 플래그).
- 플레이북 게이트 (r2-B6): 신규 계약명 **`PlaybookGateCheck`/`PlaybookGateOutcome`**
  (기존 GateResult와 별개). 선택 구조 필드
  `{metric_id, selector{series?, meta_filter?}, aggregation: last|mean_window|yoy,
  window_days, comparator, threshold, unit, max_age_days}` — **all-or-none**: 일부만
  있으면 전체 무시 + 로그. 충족 gate만 코드가 조회·판정,
  `PlaybookGateOutcome{value, verdict, evidence_observation_id | unavailable_reason:
  no_metric|unit_mismatch|stale_data}`. LLM 유사 지표 대입 금지. 문자열 gate 하위 호환.

### 4부. 검증·롤아웃

- `chain_judgment` 전후 비교 (holdout·paired blind) → 통과 시 배포(`pm2 restart attn-engine`)
  → 같은 세션에서 `docs/workflow-review.html` 현행화(파이프라인 그래프에 thesis·ChainPacket
  반영) + playwright 스크린샷 눈 확인.

## 전역 제약

- 매 단계 codex 교차 리뷰 (docs/memory-chain-review-r*_codex.md 왕복). 리뷰 반영 전 다음 단계 금지.
- 숫자 불변식: LLM 암산 숫자 답변 진입 불가. thesis 유래 숫자는 TypedFact 경로만.
- thesis는 배경 판 — 주입 프롬프트 경계 문구 필수.
- 수집 실패 시 해당 thesis는 직전 revision 유지 + 파생 freshness 강등.
- 엔진 재시작 pm2만. 커밋 메시지 작은따옴표.

## 성공 기준

**LLM 저지 (holdout, paired blind):**
- `mechanism`·`state_link`: **paired bootstrap CI 하한 > 0** (r2-R2) **그리고**
  dev+holdout 합산 +0.3 이상. 미달 시 3부 재작업 후 재측정.
- `entailed_edge_ratio` ≥ 0.6 (edge 단위 entailment 패스).

**코드 지표 (배포 게이트):**
- `as_of_violation` = 0 (frozen bundle 모드로 구조 보장 + 위반 검출)
- thesis 주입 텍스트의 수량 literal = 0 (**주입 시점 코드 검증** — 최종 자유 텍스트 귀속
  문제(r2-B7)는 주입 전 차단으로 해소)
- `grounded_edge_ratio` (실존 검증된 근거 ID 보유 edge 비율) ≥ 0.7
- statement 독립 출처(publisher_id 2종+) 위반 = 0 (가드레일 위반은 버그)
- 저지 유효 케이스 비율 ≥ 90%, self-test fixture 전부 통과
- stale/degraded thesis 사용률 리포트 (게이트 아님)

**회귀:** 기존 golden.jsonl verified_ratio·keyword 유지.

## r2 유보 항목의 처리 (요약)

- **문서 아카이브·span hash 미도입** — quote-substring 검증으로 인용 조작 차단 목적 달성.
  카드 원문 500자 한계는 인정하나, 이 스펙의 목표(체인 구성 품질)에 문서 전문 아카이브는
  비례하지 않는 인프라. 근거 부족 statement는 드롭되므로 fail-safe.
- **인간 라벨 calibration 미도입** — 유저 확정 제약(검수 불가). 결함 주입 fixture self-test로 대체.
- **빈티지 저장소 전면 도입 대신 frozen bundle 모드** — r2-B4가 제시한 대안 그 자체를 채택.
  라이브 답변 경로의 잔여 시점 위험은 eval 범위 밖으로 명시 (기존 golden.jsonl 영역).
