최종 판정: **승인 보류**.

r1 11개 항목 기준으로 **해소 1 / 부분해소 7 / 미해소 3**이다. 응답 문서의 두 “부분 유보”는 모두 현재 형태로 수용할 수 없다.

## r1 항목별 판정

| # | 판정 | 근거 |
|---|---|---|
| 1 | **[부분해소]** | `statements[]`와 근거 배열은 추가됐지만([v2 L139](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:139)), 서로 다른 발행 주체를 검증할 `publisher_id`가 없다. 현 `SectorCard`에도 canonical URL·doc hash·원문 span이 없고([contracts.py L13](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:13)), `raw_quote`는 본문 앞 500자일 뿐이다([judge.py L147](/home/ryze_yn/attn-viewer/engine/sector/judge.py:147)). 자동 보존 여부도 명시 필드 없이 생성문 문자열로만 표시된다([judge.py L225](/home/ryze_yn/attn-viewer/engine/sector/judge.py:225)). |
| 2 | **[부분해소]** | `assessment`와 `freshness` 분리는 반영됐지만, `required_inputs`는 metric과 max age만 가진다([v2 L144](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:144)). “해당 수집기 실패”를 판정할 collector ID가 없고 카드 수집기의 건강성도 선언할 수 없다. 또한 “revision을 갱신하지 않고 freshness만 변경”([v2 L157](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:157))은 append-only revision 모델과 충돌한다. |
| 3 | **[부분해소]** | statement 숫자 금지와 TypedFact 경유는 선언됐지만, LLM이 새 revision 전체를 생성하면서([v2 L151](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:151)) `key_metrics` 값도 만들 수 있다. observation ID를 저장소에서 역참조해 값·단위·source를 코드가 덮어쓴다는 계약이 없다. 현 `TypedFact`에는 metric·meta·관측시점이 없고([packets.py L280](/home/ryze_yn/attn-viewer/engine/contracts/packets.py:280)), G2는 값과 넓은 단위 그룹만 전역 비교한다([verify.py L89](/home/ryze_yn/attn-viewer/engine/stages/verify.py:89)). 자기 검증 위험이 남는다. |
| 4 | **[미해소]** | `ChainPacket` 위치만 VERIFY 앞으로 이동했다([v2 L170](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:170)). edge가 `AtomicClaim`이나 별도 edge verdict로 변환되는 계약이 없어 `VerdictPacket`은 여전히 claim ID만 판정한다([packets.py L377](/home/ryze_yn/attn-viewer/engine/contracts/packets.py:377)). 현 RISK도 VerdictPacket을 받지 않고 ClaimTable의 “존재하는 ID”만 확인한다([risk.py L36](/home/ryze_yn/attn-viewer/engine/stages/risk.py:36), [L58](/home/ryze_yn/attn-viewer/engine/stages/risk.py:58)). 따라서 체인 자체는 여전히 VERIFY를 우회한다. |
| 5 | **[부분해소]** | 축과 selector는 보완됐지만 `SectorEdge`는 기존 코드에 존재하지 않는다. `SectorCard.edge`는 자유 문자열이다([contracts.py L19](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:19))이고 judge 검증도 edge를 검사하지 않는다([judge.py L111](/home/ryze_yn/attn-viewer/engine/sector/judge.py:111)). 또한 “교집합 스코어 + priority”에 가중치·최소 일치점·0점 처리 규칙이 없다([v2 L168](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:168)). |
| 6 | **[부분해소]** | 필요한 필드 이름은 추가됐지만([v2 L190](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:190)), all-or-none 검증, selector 구조, aggregation/window 의미가 없다. 더구나 `GateResult`라는 이름은 이미 G1~G4 결과 계약으로 사용 중이다([packets.py L353](/home/ryze_yn/attn-viewer/engine/contracts/packets.py:353)). 현재 플레이북 검증기는 여전히 문자열 필드만 검사한다([playbook.py L49](/home/ryze_yn/attn-viewer/engine/stages/playbook.py:49)). |
| 7 | **[미해소]** | cutoff 인자와 `valid_from` 조회는 추가됐지만 historical snapshot 계약이 아니다. `MetricObservation`에는 수집·가용 시각이나 revision이 없고([contracts.py L36](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:36)), 저장소는 논리 키 중복을 버릴 뿐 빈티지를 보존하지 않는다([store.py L81](/home/ryze_yn/attn-viewer/engine/sector/store.py:81)). 따라서 7월 20일에 뒤늦게 적재된 7월 10일 관측도 7월 14일 실행에 노출된다. `input_snapshot`의 hash만으로는 과거 내용을 복원할 수도 없다([v2 L146](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:146)). |
| 8 | **[부분해소]** | judge를 GPT로 바꿨지만 답변 생성 파이프라인에도 GPT-5.5 DA가 참여한다([providers.py L29](/home/ryze_yn/attn-viewer/engine/providers.py:29)). “합성 모델과만 다른 provider”이지 답변 생성 전체와 독립적이지 않다. r1에서 요구한 인간 라벨 calibration set도 빠졌다. frozen bundle은 judge 입력으로만 명시돼 있고([v2 L89](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:89)), 답변 생성 입력을 같은 snapshot으로 고정하지 않는다. |
| 9 | **[해소]** | `--suite chain`, `ChainJudgeResult`, evidence 부분 점수, invalid/timeout 재시도 정책이 모두 계약에 들어갔다([v2 L86](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:86), [L91](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:91), [L107](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:107)). 단, null censoring 문제는 아래 신규 블로커다. |
| 10 | **[부분해소]** | 층화·dev/holdout·paired blind·반복 채점·bootstrap은 반영됐다. 하지만 성공 판정 표본은 holdout 8개뿐이고([v2 L50](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:50)), CI는 “병기”만 할 뿐 통과 조건이 아니다([v2 L110](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:110)). +0.3이 2~3문항 변화로 결정되는 문제는 남는다. |
| 11 | **[미해소]** | raw-span entailment와 contradiction coverage를 명시적으로 제외했고([응답 L23](/home/ryze_yn/attn-viewer/docs/memory-chain-review-r1-response_claude.md:23)), 추가된 `grounded_edge_ratio`도 “근거 ID가 하나라도 있는가”만 센다([v2 L221](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:221)). ID 존재는 지지성·verified 여부·edge와의 entailment를 보장하지 않는다. |

## r2 신규·잔존 결함

1. **[블로커 R2-B1] `statements` 근거 계약이 현재 카드 저장소에서 생성 불가능하다.**  
   `statement_id`, `publisher_id`, 완전한 contradicting evidence 스키마, span 좌표·hash 규칙이 없다([v2 L139](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:139)). 현 저장소는 카드 JSON만 기록하고 원문 문서를 hash와 함께 보존하지 않는다([store.py L36](/home/ryze_yn/attn-viewer/engine/sector/store.py:36)). `thesis_relation`도 thesis ID만 참조해 어느 revision·statement를 지지하는지 고정하지 못한다([v2 L181](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:181)).

2. **[블로커 R2-B2] LLM이 만든 `key_metrics`가 TypedFact 앵커로 세탁될 수 있다.**  
   코드가 `observation_id`를 역참조해 저장 원본과 값·단위·meta·source가 정확히 일치하는지 검증한다는 규칙이 없다([v2 L143](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:143)). 현 G2의 값·단위 비교 방식([verify.py L105](/home/ryze_yn/attn-viewer/engine/stages/verify.py:105))으로는 다른 metric의 우연히 같은 숫자도 앵커가 된다.

3. **[블로커 R2-B3] `ChainPacket`은 기존 패킷 계약과 VERIFY 출력에 연결되지 않는다.**  
   패킷에 schema version·EnvelopeMeta·edge ID가 없으며, `metric_fact_ids`의 대상도 기존 `TypedFact`인지 신규 타입인지 불명확하다([v2 L173](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:173)). `observed`는 임의의 존재하지 않는 ID 하나만 넣어도 통과하고, `contradictions`는 근거 ID가 아닌 자유 문자열이다([v2 L178](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:178)). `ChainEdgeVerdict` 또는 `VerdictPacket.chain_verdicts`가 필요하다.

4. **[블로커 R2-B4] `as_of`는 snapshot replay가 아니라 event-time 필터다.**  
   `available_at/ingested_at`, revision sequence, immutable bundle 위치가 필요하다. 현재 가격·매크로 경로는 cutoff를 넘기지 않고 현재값을 조회한다([price_macro.py L23](/home/ryze_yn/attn-viewer/engine/stages/price_macro.py:23)); 실제 quote 함수는 `until`을 지원하지만 호출되지 않는다([yahoo.py L71](/home/ryze_yn/attn-viewer/engine/tools/price/yahoo.py:71)). REFLECT 검색에도 cutoff 인자가 없다([ra_external.py L624](/home/ryze_yn/attn-viewer/engine/stages/ra_external.py:624)). 날짜 불명 뉴스도 현 필터에서는 통과한다([ra_external.py L286](/home/ryze_yn/attn-viewer/engine/stages/ra_external.py:286)). frozen bundle을 답변 생성에도 사용하거나, historical eval에서 재생 불가능한 branch를 꺼야 한다.

5. **[블로커 R2-B5] thesis 건강성과 선택이 결정적이지 않다.**  
   `required_inputs`에 collector/card query/min-count가 없고, stale revision의 합성 주입 허용 여부도 없다([v2 L144](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:144)). 또한 thesis 선택 입력인 query plan은 기본적으로 LLM이 생성한다([queryplan.py L155](/home/ryze_yn/attn-viewer/engine/sector/queryplan.py:155)). “결정적, LLM 없음”이라는 스펙 문구와 맞지 않는다. 결정성이 필요하면 `rule_plan`을 사용하고 0점 thesis 제외 규칙을 정의해야 한다.

6. **[블로커 R2-B6] 플레이북 gate 계약이 아직 executable schema가 아니다.**  
   기존 `GateResult`와 충돌하지 않는 별도 이름, 구조 필드 all-or-none validator, typed selector, 지원 aggregation/window 목록, 관측시점·가용시점 검증, `unavailable_reason`이 필요하다([v2 L190](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:190), [기존 GateResult L353](/home/ryze_yn/attn-viewer/engine/contracts/packets.py:353)).

7. **[블로커 R2-B7] 코드 성공 지표가 근거성을 측정하지 못한다.**  
   `grounded_edge_ratio`는 임의 ID로 채울 수 있고, 독립 출처 비율은 publisher identity가 없어 계산 불가하다. “thesis 유래 unsupported numeric”도 최종 자유 텍스트에 thesis provenance가 없어서 정확히 귀속할 수 없다([v2 L218](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:218)). 최소한 verified-and-entailed edge ratio, exact span integrity, contradiction evidence coverage를 별도 산출해야 한다.

8. **[블로커 R2-B8] judge 실패·calibration 계약이 배포 게이트로 불완전하다.**  
   `score=null`을 평균에서 제외하면 baseline/candidate 중 불리한 케이스가 선택적으로 사라질 수 있다([v2 L108](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:108)). paired case 양쪽 성공을 필수로 하고 최소 유효률을 정해야 한다. 인간 라벨 calibration, judge-vs-human 일치 기준, 반복 run별 원시 결과 계약도 필요하다.

9. **[권고 R2-R1] 숫자 regex의 제품명 오탐을 정의해야 한다.**  
   “숫자 패턴이면 statement 드롭”은 `HBM3E`, `DDR5` 같은 제품·세대 식별자까지 제거할 수 있다([v2 L140](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:140)). 수량 literal과 identifier를 분리해야 한다.

10. **[권고 R2-R2] holdout 통과는 점추정치가 아니라 CI 하한으로 판정해야 한다.**  
    holdout 8개를 유지한다면 최소한 paired bootstrap CI의 하한이 0보다 크다는 조건과 judge 유효률 조건이 필요하다([v2 L215](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:215)).

## 부분 유보 판정

- **raw-span entailment·contradiction coverage 흡수: 수용 불가.** Frozen-bundle judge는 최종 답변의 유창성을 평가하는 LLM 판정이고, edge/statement별 코드 지표가 아니다. `contradictions: string[]`의 존재도 반증 검색이나 근거 검증을 증명하지 않는다. 보조 judge로는 쓸 수 있지만 코드 배포 게이트를 대체할 수 없다.

- **외부 뉴스 cutoff 불완전: historical eval에서는 수용 불가.** 라이브 답변의 잔여 위험 공시로는 수용 가능하지만 `as_of_violation=0`을 주장하는 eval에서는 모순이다. 날짜 불명 문서는 fail-closed로 제외하고, 과거 eval은 frozen archive만 사용하거나 외부 검색·Toss·현재 fundamentals·live macro 경로를 비활성화해야 한다.

따라서 **R2-B1~B8 해소 전 승인 보류**다.