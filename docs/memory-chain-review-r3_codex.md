최종 판정: **승인 보류**. 수렴 기준 적용 결과 **해소 5 / 미해소 5**다. 구현 명명·enum·세부 스키마 문제는 블로커에서 제외했다.

## 항목별 판정

| 항목 | 판정 | 근거 |
|---|---|---|
| R2-B1 | **[미해소]** | 문서 아카이브 미도입 때문은 아니다. `quote` 부분문자열 검증은 “카드에 있는 문구인가”만 확인하며, 그 문구가 statement를 지지하는지는 검증하지 않는다([v3 L127](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:127), [L130](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:130)). 또한 등록 가능 도메인을 publisher로 간주하므로 동일 보도자료가 두 도메인에 전재되면 독립 출처 2종으로 오측정된다. 이런 statement가 그대로 저장·주입된다([v3 L137](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:137)). |
| R2-B2 | **[해소]** | LLM은 metric 이름만 내고 코드가 관측값 전체를 덮어쓰며([v3 L133](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:133)), G2도 metric 식별자까지 비교한다([v3 L168](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:168)). 원래 지적한 LLM 수치 세탁 경로는 차단됐다. |
| R2-B3 | **[해소]** | ID 실존 검증·강등 규칙과 `VerdictPacket.chain_verdicts`, RISK 소비가 연결됐다([v3 L145](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:145), [L163](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:163), [L165](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:165)). YAML의 세부 필드 문제는 구현 계획 사항이다. |
| R2-B4 | **[미해소]** | 라이브 경로 비활성화는 반영됐지만([v3 L51](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:51), [L54](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:54)), 과거 `as_of` bundle을 언제·어떤 가용 시점 기준으로 구성하는지가 없다. 현 카드는 사건시각 `ts`만, 지표도 관측시각 `ts`만 가진다([contracts.py L13](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:13), [L36](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:36)). 따라서 뒤늦게 적재된 과거 데이터가 bundle 안에 들어가면 불변 hash로 오염이 고정된다. `as_of_violation`도 bundle 밖 “인용”만 센다([v3 L58](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:58)). |
| R2-B5 | **[해소]** | freshness 파생, 입력 부족 시 revision 미생성, stale 주입 금지, `rule_plan` 기반 결정적 선택과 0점 제외가 명시됐다([v3 L119](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:119), [L123](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:123), [L138](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:138), [L142](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:142)). collector ID 부재만으로 잘못된 값이 생성되지는 않는다. |
| R2-B6 | **[해소]** | 별도 계약, all-or-none, selector, aggregation, unavailable 결과가 실행 가능한 수준으로 정해졌다([v3 L173](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:173)). 세부 enum은 계획 단계로 넘겨도 된다. |
| R2-B7 | **[미해소]** | entailment 분모가 `ChainPacket.edges`로 한정된다([v3 L82](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:82)). 최종 답변의 사실·인과 주장과 edge 사이 coverage 계약은 없고, SYNTHESIZE 후검증도 형식 확인뿐이다([v3 L171](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:171)). 따라서 지원된 edge 몇 개만 packet에 넣고 최종 답변에 미지원 주장을 추가해도 `entailed_edge_ratio`와 `grounded_edge_ratio`가 모두 통과할 수 있다([v3 L200](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:200), [L206](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:206)). |
| R2-B8 | **[미해소]** | paired-validity·유효률·원시 결과 저장은 해소됐다([v3 L77](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:77), [L79](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:79)). 하지만 같은 5개 fixture에 실패할 때마다 judge prompt를 수정해 다시 통과시킨다([v3 L73](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:73), [L75](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:75)). 이는 tune set이지 calibration holdout이 아니므로 저지 정확성을 검증하지 못한다. |
| R2-R1 | **[해소]** | 수량 literal과 영문자 결합 식별자를 분리했다([v3 L107](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:107), [L135](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:135)). |
| R2-R2 | **[미해소]** | CI 하한 조건 자체는 추가됐다. 그러나 holdout 튜닝 금지를 선언하면서([v3 L62](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:62)) 실패 시 3부를 재작업하고 같은 holdout을 재측정한다([v3 L198](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:198)). 또한 효과크기 +0.3은 튜닝에 사용한 dev와 holdout을 합산한다. 반복 peek와 dev 혼합 때문에 CI와 효과크기가 낙관 편향된다. |

## Claude의 반박 3건

1. **문서 아카이브 미도입: 조건부 동의.**  
   현재 `raw_quote`는 수집 본문의 앞 500자다([judge.py L148](/home/ryze_yn/attn-viewer/engine/sector/judge.py:148)). 평가의 진실 기준을 frozen bundle의 저장 snippet으로 한정한다면 전문 아카이브나 span 좌표는 필수가 아니다. 다만 substring 검증은 statement entailment나 독립 원출처를 보장하지 않는다. 즉 아카이브 반박은 타당하지만, 그것만으로 B1이 해소되지는 않는다.

2. **인간 calibration 대체: 현재안에는 부동의.**  
   인간 검수가 불가능하다는 제약은 수용한다. 문제는 합성 calibration 자체가 아니라 같은 5개를 prompt 수정에 사용한 뒤 다시 시험하는 순환이다. fixture 표현만 인식하도록 과적합해도 전부 통과하며, 실제 답변의 미묘한 근거 오류나 GPT 계열 자기선호는 남는다. 인간 없이도 튜닝 fixture와 봉인된 synthetic/metamorphic calibration set을 분리하면 된다.

3. **frozen bundle 모드: 방향은 타당하지만 현재 계약은 불충분.**  
   라이브 경로 차단은 실행 간 drift를 막는다. 그러나 bundle 생성 전에 이미 들어온 backfill·revision을 제거하지는 못한다. `as_of` 당시 캡처한 bundle이 아니라면 오염을 그대로 동결한다. 전면 vintage 저장소 대신 `as_of = captured_at`인 동시점 캡처만 사용하거나, bundle 각 항목에 당시 가용성을 증명하는 ingestion/revision manifest가 필요하다.

## v3 신규 측정 결함

- **Holdout 오염:** 실패 후 같은 holdout으로 재작업·재측정하며, tuned dev를 효과크기에 합산한다.
- **분모 우회:** edge entailment를 추가했지만 최종 답변 주장→edge coverage가 없어 좋은 edge만 선택적으로 측정할 수 있다.
- **저지 tune/test 오염:** 같은 5개 fixture로 judge prompt를 튜닝하고 통과 여부도 판정한다.
- **거짓 독립 출처 측정:** 등록 도메인 다양성을 발행 주체 독립성으로 보고한다.
- **오염 bundle의 고정:** bundle 불변성은 생성 시점의 역사적 정합성을 보장하지 않는다.

승인에 필요한 블로커는 위 **R2-B1, B4, B7, B8, R2-R2** 다섯 건이다. 전문 문서 아카이브·인간 라벨·전면 vintage 저장소 자체를 요구하는 것은 아니다.