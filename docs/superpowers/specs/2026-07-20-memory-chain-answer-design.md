# 메모리 섹터 체인 답변 설계 — Thesis 레이어 + 사건 기반 eval (v5)

작성일: 2026-07-20 (v5 — codex r1~r4 왕복 반영, docs/memory-chain-review-r*_codex.md)
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

**bundle 가용성 정합 (r3-B4):** 기존 저장소에는 적재 시각이 없어 과거 as_of의 가용성을
증명할 수 없다. 처리:

- **회고 케이스** (2026-06~07 기존 사건): `availability: unproven` 표기.
  **dev·진단 전용 — 배포 판정에서 제외** (r4: candidate가 새 체인·thesis 경로로 누출
  데이터를 baseline보다 더 활용할 수 있어, 동일 bundle이어도 paired delta가 편향될 수
  있음. "상쇄" 논리 철회).
- **전향 케이스**: 지금부터 `as_of = captured_at` 동시점 캡처로만 생성 — 가용성이 정의상
  증명됨. 신규 사건 발생 시 케이스를 계속 추가 (holdout 회전의 공급원, 아래).
- 지금부터 모든 신규 카드·지표 관측에 `ingested_at` 스탬프 추가 — 이후 bundle은
  ingestion manifest를 갖는다.

#### 케이스셋

- `engine/evals/golden_chain.jsonl` — 최근(2026-06~07) 실제 사건 기반 **24문항**,
  사건 유형·영향 경로·긍정/부정 층화, **dev 14 + holdout 10**. holdout은 프롬프트 튜닝
  사용 금지, 성공 판정은 holdout 기준. 사건은 섹터 카드 저장소에서 실제 발생 건만 사용.
- 케이스 스키마: `{id, type, split, question, as_of, bundle_path,
  availability: proven | unproven, rubric{mechanism, state_link, verdict, evidence[],
  countercase}, must_not[]}` (루브릭 5축은 v2와 동일).
- 초기 24문항은 대부분 회고(unproven·dev 전용)로 시작 — 개발·진단·튜닝에 사용.
  **배포 판정 holdout은 `availability: proven` 전향 케이스만으로 구성한다** (r4-B4).
  전향 케이스는 1부 배포 직후부터 신규 사건마다 동시점 캡처로 축적 (이 섹터는 사건이
  일 단위로 발생하므로 2·3부 구현 기간에 holdout 10개 확보 가능).

#### 채점

- 실행기: `run_eval.py --suite chain` (기존 `golden.jsonl` 경로 불변).
- 저지: 교차 provider **gpt-5.5** (합성이 Claude 계열. DA에 GPT가 참여하나 최종 문장을
  쓰는 모델과 분리가 목적 — 한계는 리포트에 명시). 저지 입력은 답변 + 루브릭 + frozen bundle.
- **저지 calibration (인간 라벨 대체, r2-B8·r3):** fixture를 두 층으로 분리해
  tune/test 순환을 차단한다.
  - **튜닝 fixture 7개(02·05·06 포함) 매 실행 필수** (공개): mechanism 누락 / 유령 인용
    (02) / 미래 정보 / countercase 없음 / 정상(05) / 유령 인용 음성(06) 등. 저지 프롬프트
    개발·수정에 사용. 유령 인용 감도(ghost 변형)는 튜닝 fixture 02·06이 담당한다.
  - **봉인 calibration 셋 8개 (cj-v7 확정 계약)**: **무수정 실제 베이스라인 답변**
    (직전 권위/파일럿 실행 산출물 중 base 전제조건 충족분에서 선정)에 metamorphic 변형을
    가해 정답 관계가 기계적으로 알려진 셋. **프롬프트 버전당 1회만 평가, 첫 시도 통과
    필수.** 실패 시 튜닝 fixture로만 수정하고, 새 프롬프트 버전에는 **새로 생성한 봉인
    셋**을 쓴다. 봉인 셋 통과 없이는 채점 결과 무효.
    - **변형 4종 × base 2개 = 8항목 (cj-v7)**: flip_verdict(verdict zero) /
      strip_countercase(countercase zero) / tamper_numbers(evidence lower) /
      identity(verdict==base). strip_evidence(evidence zero)·ghost 변형은 봉인에서 제거 —
      cj-v5 실측에서 strip_evidence는 패러프레이즈 매칭으로 관계가 불안정했고, ghost는
      무수정 base에 구조적으로 무력 — 튜닝 fixture(02·05·06)가 담당한다.
    - **counter-leak 어휘 fail-closed 사전 필터**: strip_countercase 산출물에 반대 신호
      어휘(리스크·우려·하락·반대·틀릴·약화·제한·한계·희석·선반영·공급과잉·확인 불가·
      downside·risk)가 잔존하면 make_sealed_set에서 ValueError. 최종 적합성은 저지와
      독립된 리뷰어가 봉인 실행 전에 확인하고, 확인 결과와 잔존 텍스트 hash를 기록한다.
      봉인 결과를 본 뒤 base를 교체하는 것은 금지된다.
    - 봉인 항목의 rubric은 케이스 원본이 아닌 **generic calibration rubric**(저지 실행 전
      고정 — mechanism·state_link·verdict·countercase는 일반 정의, evidence 목록만 케이스
      상속). 봉인 목적은 저지 감도 교정이지 케이스 적합도가 아니다.
    - base 전제조건: 저지 기준 verdict=1·countercase=1·evidence>0 (**봉인 실행과 동일
      구성(generic rubric·judge_context)으로 2회 일관 사전심사** — 전제조건 심사는 base
      선정이지 변형 관계 튜닝이 아님) + 정적 적합성
      (countercase 절·본문 수치). base 데이터를 봉인 실패를 보고
      재구성하는 것 금지 — 부적합 시 실답변 표본을 늘려 재선정.
    - **ledger 키 바인딩**: calibration ledger 키를 (version, sealed_hash,
      judge_config_hash)로 확장. judge_config_hash = sha256(provider + model ID + effort +
      chain_judge._INSTR + _JudgeOut.model_json_schema 직렬화)[:16]. 세 키 모두 일치할
      때만 기존 pass를 재사용 — 모델·프롬프트 설정이 바뀌면 봉인을 반드시 재실행한다.
- 출력 계약 `ChainJudgeResult`: 축별 `{score, reason}` (evidence는 matched/total 부분 점수),
  `judge_model`·`judge_prompt_version`·`raw` 저장. invalid/타임아웃 1회 재시도 후 `null`.
- **paired-validity (r2-B8):** baseline/candidate **양쪽 모두 유효한 케이스만** 비교에 산입.
  유효 케이스 비율 90% 미만이면 결과 폐기하고 재실행.
- 반복 채점 2회 + 축 불일치 시 3회차 타이브레이크. 반복 run별 원시 결과 전량 저장.
- **edge 단위 entailment 패스 (r2-B7):** ChainPacket의 각 edge에 대해 저지가
  "인용된 근거 span이 이 edge 주장을 지지하는가"를 개별 판정 → `entailed_edge_ratio`.
- **답변 주장 커버리지 패스 (r3-B7 — 좋은 edge만 골라 측정하는 우회 차단):** 저지가
  최종 답변에서 사실·인과 주장을 추출하고, 각 주장이 grounded edge 또는 bundle 근거에
  연결되는지 판정 → `uncovered_claim_ratio` (미지원 주장 / 전체 주장). ChainPacket에
  넣지 않은 주장도 분모에 포함되므로 선택적 측정이 불가능하다.
- 리포트에 축별 평균 + 코드 SHA·bundle hash·모델/프롬프트 버전 기록.
- **베이스라인을 개선 착수 전에 측정.**

#### 1부 완료 스코프 (2026-07-20 확정 — codex 최종 판정 "조건부 승인")

**1부 = "eval core + 진단 베이스라인" 완료.** 2-arm experiment 실행기는 4부 완료 대상.

- **cj-v4 리포트(report-chain-20260720-152545)는 진단 전용** — 효과크기·배포 판정에
  사용 금지. 재감사 최종 artifact: report-chain-20260720-152545-reaudit.md (as_of 0건).
- **sealed v1~v7 소진·실패 — 재개봉 금지** (ledger 기록 보존). authoritative off/on
  측정과 봉인 첫 통과는 **4부 experiment로 이연**: 2·3부 개선 후 candidate 답변이
  base 전제조건을 충족하는 시점(부트스트랩 역설 해소)에 새 버전(v8+)·새 hash로 첫 시도.
- 근거: 30개 실답변 전수 심사(감사: sealed-base-screening-audit-20260720.jsonl)에서
  margin-safe base 1개(cj-15) — 현 계약으로 1부 재추첨 지속은 비경제적.
- **base 계약 vs 선정 margin 구분**: 계약 전제조건은 verdict=1·countercase=1·evidence>0,
  **운영 선정 기준은 evidence≥0.5 × 2회 일관**(게이트 시점 저지 분산 대비 margin — v7
  소진 실측). 방향성 반대 어휘 목록(코드 `_COUNTER_LEAK_TERMS`와 정합): 리스크·우려·
  하락·반대·틀릴·약화·희석·선반영·공급과잉·downside·risk — 인식론적 헤징(확인 불가·
  한계·제한)은 반대 방향 신호가 아니므로 제외.
- "봉인 미통과 점수 무효" 규정의 적용: cj-v4 수치는 무효가 아니라 **진단값 지위** —
  authoritative 지위만 봉인 통과 실행에 유보.

**4부 승계 필수 게이트** (codex 확정):
1. candidate calibration base는 dev/calibration pool에서만 — holdout 답변 사용 금지
2. candidate 코드·judge 설정 동결 후 v8+ 새 버전·새 sealed hash로 첫 시도 (v7 재사용 금지)
3. self-test·sealed 통과를 holdout claim보다 먼저 실행
4. fresh proven holdout ≥10에서 단일 명령 disable_p23 off/on 2-arm
5. paired-validity·CI·+0.3·uncovered/entailed·as_of·회귀 게이트 전부 + ledger 원자 종료
6. 개선 후에도 적합 base <2면 4부 중단 — 임계 완화·holdout base 사용 금지, 사전 고정
   dev calibration cohort 확장으로만 해소

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
     시 해당 근거 무효 (인용 조작 차단. 문서 전문 아카이브는 미도입 — r3 조건부 동의 확보).
     추가로 (r3-B1):
     - **지지성 검증**: 갱신 잡과 분리된 검증 LLM(교차 provider)이 "이 quote가 이
       statement를 지지하는가"를 판정 — 기각된 근거는 무효 (드롭 방향만 있는 fail-safe,
       생성 LLM 자기 검증 아님).
     - **전재 중복 탐지**: supporting 카드들의 quote를 정규화 후 유사도 비교 — 실질 동일
       내용이면 도메인이 달라도 **1개 발행 주체로 계수** (보도자료 전재를 독립 출처로
       오측정하는 것 차단).
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
- `mechanism`·`state_link`: **holdout(전원 `availability: proven` 전향 케이스)에서만**
  paired bootstrap CI 하한 > 0 그리고 +0.3 이상 (dev는 튜닝 전용 — 효과크기에 합산하지
  않음. 회고 unproven 케이스는 배포 판정 불산입, r4-B4).
- **holdout 1회 사용 원칙 (r3-R2):** 실패 시 사용한 holdout은 dev로 편입하고,
  전향 케이스(신규 사건, as_of=captured_at)로 보충한 **새 holdout**으로 재측정.
  같은 holdout 반복 peek 금지.
- `entailed_edge_ratio` ≥ 0.6, `uncovered_claim_ratio` ≤ 0.2.

**코드 지표 (배포 게이트):**
- `as_of_violation` = 0 (frozen bundle 모드로 구조 보장 + 위반 검출)
- thesis 주입 텍스트의 수량 literal = 0 (**주입 시점 코드 검증** — 최종 자유 텍스트 귀속
  문제(r2-B7)는 주입 전 차단으로 해소)
- `grounded_edge_ratio` (실존 검증된 근거 ID 보유 edge 비율) ≥ 0.7
- statement 독립 출처(전재 중복 제외 후 발행 주체 2종+) 위반 = 0 (가드레일 위반은 버그)
- 저지 유효 케이스 비율 ≥ 90%, 봉인 calibration 셋 첫 시도 통과
- stale/degraded thesis 사용률 리포트 (게이트 아님)

**회귀:** 기존 golden.jsonl verified_ratio·keyword 유지.

## 미도입 인프라와 그 대체 (r2~r3 왕복 확정)

- **문서 전문 아카이브·span hash** — quote-substring 검증(조작 차단) + 검증 LLM 지지성
  판정 + 전재 중복 탐지로 대체 (r3 조건부 동의).
- **인간 라벨 calibration** — 튜닝 fixture / 봉인 metamorphic calibration 셋 분리로 대체.
- **전면 vintage 저장소** — frozen bundle + 회고 케이스 paired 전용 + 전향 케이스
  동시점 캡처 + 신규 데이터 ingested_at 스탬프로 대체.
