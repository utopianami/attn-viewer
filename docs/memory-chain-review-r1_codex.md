판정: 승인 보류. 현재 스펙대로 구현하면 자동 thesis가 기존 카드 해석 오류를 장기 기억으로 증폭할 수 있고, eval도 그 개선을 신뢰성 있게 판별하지 못합니다.

1. [블로커] “카드 ID 2개”는 주장 지지성과 출처 독립성을 보장하지 못한다.

   `summary`는 자유 문자열인데 근거 ID는 thesis 전체 배열이라, “각 주장별 2개”를 코드가 식별·드롭할 수 없습니다([스펙 L89](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:89), [스펙 L98](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:98)). 저장소는 ID만 중복 제거합니다([store.py L41](/home/ryze_yn/attn-viewer/engine/sector/store.py:41)). 실제로 동일 Stocktwits URL이 서로 다른 카드 ID로 저장돼 있습니다([index.jsonl L20](/home/ryze_yn/attn-viewer/storage/rag/memory_sector/index.jsonl:20), [index.jsonl L415](/home/ryze_yn/attn-viewer/storage/rag/memory_sector/index.jsonl:415)). 원문이 비어 있는데 추측성 `interpreted_signal`만 있는 S급 카드도 존재합니다([index.jsonl L2](/home/ryze_yn/attn-viewer/storage/rag/memory_sector/index.jsonl:2)).

   더구나 `interpreted_signal`은 계약상 LLM 해석인데([contracts.py L28](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:28)), 현재 evidence 변환은 이를 원문과 합쳐 증거로 취급합니다([evidence.py L22](/home/ryze_yn/attn-viewer/engine/sector/evidence.py:22)). 이는 “LLM 해석 → thesis → 답변”의 순환 검증입니다.

   `statements: [{text, supporting_evidence[], contradicting_evidence[]}]`로 구조화하고, 근거마다 `card_id`, canonical URL/document hash, 원문 span, source grade를 가져야 합니다. 최소 2개는 서로 다른 문서·발행 주체여야 하며, 빈 `raw_quote`와 D급, 자동 보존 공시는 지지 근거 수에서 제외해야 합니다.

2. [블로커] 부분 수집 실패가 자동 thesis를 오염시키는 경로가 열려 있다.

   스펙은 수집기 실패가 갱신을 막지 않는다고 명시하지만([스펙 L127](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:127)), 현재 수집기는 성공한 관측치를 수집기별로 즉시 저장한 뒤([runner.py L34](/home/ryze_yn/attn-viewer/engine/sector/runner.py:34)) 마지막에야 전체 상태를 기록합니다([runner.py L57](/home/ryze_yn/attn-viewer/engine/sector/runner.py:57)). updater가 부분 데이터와 실제 신호 부재를 구별할 필드가 Thesis 스키마에 없습니다.

   또한 `strengthening|weakening|mixed|stale` 하나로 방향과 신선도를 같이 표현해, 실패 시 기존 방향 상태가 소실됩니다. “새 인용이 없으면 stale” 규칙([스펙 L99](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:99))은 분기 CAPEX 같은 저빈도 지표([metrics_registry.py L21](/home/ryze_yn/attn-viewer/engine/sector/metrics_registry.py:21))를 매일 stale로 만들 수도 있습니다.

   `assessment`와 `freshness`를 분리하고, thesis별 필수 수집기·지표·허용 지연을 선언해야 합니다. 필수 입력이 불건전하면 해당 thesis만 마지막 정상 상태를 유지하고 `degraded/stale`만 별도 표시해야 합니다.

3. [블로커] 숫자 가드레일은 기존 G2와 정합하지 않고, 잘못 구현하면 자기 검증이 된다.

   스펙은 summary 숫자를 `key_metrics`에서 허용하면서([스펙 L100](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:100)) thesis를 `[결정적 수치]` 밖에 두라고 합니다([스펙 L101](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:101)). 그러나 SYNTHESIZE는 해당 절의 숫자만 사용하도록 되어 있습니다([synthesize.py L27](/home/ryze_yn/attn-viewer/engine/stages/synthesize.py:27)). 두 요구를 동시에 만족할 수 없습니다.

   기존 G2도 범용 숫자 검증기가 아니라 DA 모델 숫자와 `ClaimTable` 앵커를 대조하는 경로입니다([verify.py L327](/home/ryze_yn/attn-viewer/engine/stages/verify.py:327)). 현재 안전하게 `TypedFact`로 승격되는 섹터 지표도 canonical DRAM 시리즈뿐입니다([evidence.py L28](/home/ryze_yn/attn-viewer/engine/sector/evidence.py:28)). 제안된 `key_metrics`에는 다중 시계열을 구별하는 `meta`·관측 ID·source가 없습니다([contracts.py L36](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:36)).

   반대로 thesis를 감사의 `evidence_texts`에 넣으면, 감사기가 그 생성문 속 숫자를 앵커로 다시 받아 자기 검증합니다([audit.py L178](/home/ryze_yn/attn-viewer/engine/stages/audit.py:178)).

   thesis summary에는 숫자를 금지하고, 숫자는 원 관측 ID와 차원 정보가 보존된 `TypedFact`로만 `ClaimTable` 및 `[결정적 수치]`에 주입해야 합니다. 생성된 thesis 문장은 감사 evidence가 되어서는 안 됩니다.

4. [블로커] 체인과 thesis가 VERIFY·RISK를 우회한다.

   현재 ASSEMBLE에는 섹터의 정형 숫자만 들어갑니다([orchestrator.py L342](/home/ryze_yn/attn-viewer/engine/orchestrator.py:342)). RISK는 그 `ClaimTable`만 보고 먼저 실행되며([orchestrator.py L468](/home/ryze_yn/attn-viewer/engine/orchestrator.py:468)), 카드·사이클은 이후 SYNTHESIZE에 직접 전달됩니다([orchestrator.py L481](/home/ryze_yn/attn-viewer/engine/orchestrator.py:481)). 제안된 체인 객체에는 근거 카드 ID나 metric fact ID조차 없습니다([스펙 L108](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:108)).

   현재 RISK의 `grounded` 판정도 verified 여부가 아니라 단순히 존재하는 claim ID인지로 결정됩니다([risk.py L58](/home/ryze_yn/attn-viewer/engine/stages/risk.py:58)). 마지막 형식 강제 역시 SYNTHESIZE가 자유 텍스트 호출이라 프롬프트 소원에 불과합니다([synthesize.py L185](/home/ryze_yn/attn-viewer/engine/stages/synthesize.py:185)).

   `ChainPacket`을 VERIFY 이전에 만들고 각 edge에 `supporting_card_ids`, `metric_fact_ids`, `contradictions`, `inference/observed` 구분을 넣어야 합니다. RISK는 `VerdictPacket`의 verified 근거만 받아야 하며, 최종 답변에는 체인·조건 존재 여부를 검사하는 코드 후검증이 필요합니다.

5. [블로커] 축·경로 타입이 기존 sector 계약과 충돌하며 thesis 선택 규칙도 정의되지 않았다.

   Thesis 축은 `A|B|C|D|market`인데([스펙 L87](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:87)), 현재 계약은 `A|A_prime|B|C|C0|E|P|market`이며 D는 없습니다([contracts.py L8](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:8)). 기존 인과 그래프도 C0, A_prime, E, P 경로를 명시합니다([judge.py L61](/home/ryze_yn/attn-viewer/engine/sector/judge.py:61)). `C→B→A` 고정은 마이크론 실적(A 직접), 중국 규제(P→A), 장비·패키징(A_prime) 사건을 잘못 끼워 맞추게 됩니다.

   또한 queryplan에는 thesis ID나 axis가 없고 entity·metric·event type만 있습니다([queryplan.py L32](/home/ryze_yn/attn-viewer/engine/sector/queryplan.py:32)). 반대로 Thesis에는 entity·segment·metric selector가 없어 “관련 thesis 1~3개” 선택을 결정적으로 구현할 수 없습니다.

   기존 축 enum을 단일 소스로 재사용하고, `impact_path`를 typed edge 배열로 만들어야 합니다. 각 seed에는 `selectors: {entities, metrics, segments, event_types}`와 우선순위가 필요합니다.

6. [블로커] 플레이북 gate는 현재 데이터로 자동 채점할 수 있는 계약이 아니다.

   `operationalization`은 단순 문자열인지 확인할 뿐입니다([playbook.py L60](/home/ryze_yn/attn-viewer/engine/stages/playbook.py:60)). gate는 PLAN 전에 절차 텍스트로만 들어가고([playbook.py L138](/home/ryze_yn/attn-viewer/engine/stages/playbook.py:138)), SYNTHESIZE에는 gate가 아닌 connection만 들어갑니다([playbook.py L147](/home/ryze_yn/attn-viewer/engine/stages/playbook.py:147)). 실제 sector 지표 조회는 그보다 훨씬 뒤입니다([orchestrator.py L251](/home/ryze_yn/attn-viewer/engine/orchestrator.py:251)).

   테스트 플레이북의 “재고 8주 미만” gate([test_playbook_match.py L7](/home/ryze_yn/attn-viewer/engine/tests/test_playbook_match.py:7))에 대응하는 현 지표는 재고 “지수”뿐이라([metrics_registry.py L17](/home/ryze_yn/attn-viewer/engine/sector/metrics_registry.py:17)) 단위상 판정 자체가 불가능합니다.

   gate 계약에 `metric_id`, series selector, aggregation/window, comparator, threshold, unit, max_age를 추가하고, 조회 후 `GateResult(value, verdict, evidence_id|unavailable)`를 별도 생성해야 합니다. 비슷한 이름의 지표를 LLM이 대신 끼워 넣어서는 안 됩니다.

7. [블로커] eval의 `as_of`는 현재 실행 경로에서 죽은 필드라 미래 정보 누출을 막지 못한다.

   케이스에는 `as_of`가 있지만([스펙 L57](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:57)), 실행기는 질문 문자열만 `run_qa`에 넘깁니다([run_eval.py L24](/home/ryze_yn/attn-viewer/engine/evals/run_eval.py:24)). PLAN은 명시적 백테스트가 아니면 오늘을 사용합니다([plan.py L101](/home/ryze_yn/attn-viewer/engine/stages/plan.py:101)). 카드 검색도 기본적으로 현재 시각 기준이며([retrieve.py L144](/home/ryze_yn/attn-viewer/engine/sector/retrieve.py:144)), 지표 조회에는 cutoff 인자가 없습니다([store.py L104](/home/ryze_yn/attn-viewer/engine/sector/store.py:104)).

   따라서 7월 14일 케이스를 7월 20일 실행하면 이후 카드·지표·thesis와 사건 결과를 볼 수 있습니다. 현재 상태만 담는 `theses.jsonl` 역시 과거 시점 재생이 불가능합니다.

   eval 모드에서 `knowledge_cutoff`을 모델 추론이 아닌 실행 인자로 강제하고, 카드·지표·뉴스·thesis revision 모두 `<= as_of`인 고정 snapshot을 사용해야 합니다. thesis는 append-only revision에 `valid_from`, `input_snapshot_id`를 가져야 합니다.

8. [블로커] “답변 생성 모델과 분리된 opus-4.8 judge”라는 전제가 사실이 아니다.

   full profile의 최종 synthesizer도 Claude Opus를 사용합니다([providers.py L36](/home/ryze_yn/attn-viewer/engine/providers.py:36), [settings.py L28](/home/ryze_yn/attn-viewer/engine/app/settings.py:28)). 판단형 chain 케이스에서는 동일 모델이 자기 계열 답변의 문체와 구조를 선호하는 self-preference가 발생합니다.

   또한 judge가 답변과 rubric만 보면 `countercase`의 근거가 실제인지, 인용이 사건 당시 존재했는지 판정할 수 없습니다. 유창한 허위 체인도 높은 점수를 받을 수 있습니다.

   최소한 교차 provider judge를 사용하고, frozen evidence bundle만 근거로 채점해야 합니다. 인간 라벨 calibration set, 복수 judge의 불일치 처리, raw judge JSON·모델 버전·프롬프트 버전 저장도 필요합니다.

9. [블로커] `golden_chain.jsonl`은 현재 eval 하네스에서 읽히지 않으며 scorer 계약도 없다.

   실행기는 `golden.jsonl`을 하드코딩합니다([run_eval.py L45](/home/ryze_yn/attn-viewer/engine/evals/run_eval.py:45)). 현재 metric 레코드에는 chain 축이나 judge 결과가 없습니다([metrics.py L34](/home/ryze_yn/attn-viewer/engine/evals/metrics.py:34)). 스펙에는 judge 출력 스키마, invalid 응답·타임아웃 처리, evidence 축에서 목록 전부/일부 중 무엇을 1점으로 보는지도 없습니다.

   `--suite chain`, 구조화된 `ChainJudgeResult`, 실패 시 점수와 재시도 정책, 축별 원시 판정·사유 저장을 1부 계약에 명시해야 베이스라인 측정이 가능합니다.

10. [권고] 표본과 성공 기준이 judge 노이즈·과적합을 구분하기에 부족하다.

   12~15개의 이진 케이스에서 +0.3은 4~5문항 판정 변화입니다([스펙 L48](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:48), [스펙 L133](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:133)). 동일 케이스로 프롬프트를 반복 튜닝하면 쉽게 과적합됩니다. 현재 리포트도 코드 SHA, 데이터 snapshot, 모델·프롬프트 버전을 기록하지 않습니다([run_eval.py L31](/home/ryze_yn/attn-viewer/engine/evals/run_eval.py:31)).

   사건 유형·경로·긍정/부정을 층화한 dev/holdout 분리, baseline/candidate 답변을 같은 시점에 blind 재채점하는 paired 평가, 복수 judge 또는 반복 채점과 bootstrap CI가 필요합니다.

11. [블로커] 성공 기준을 통과해도 “근거가 강화된 체인”이라는 목표 달성을 보장하지 않는다.

   `mechanism`과 `state_link`는 그럴듯한 문장이나 제목만 추가해도 judge가 1점을 줄 수 있습니다. 기존 `verified_ratio`는 ClaimTable 내부 주장만 세므로([metrics.py L26](/home/ryze_yn/attn-viewer/engine/evals/metrics.py:26)), 직접 주입된 thesis·chain의 오류는 회귀 지표에 반영되지 않습니다. 미확인 수치는 수동 샘플링만 요구되어 자동 배포 게이트가 아닙니다([스펙 L136](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:136)).

   성공 기준에 최소한 다음 코드 지표가 필요합니다: `grounded_edge_ratio`, 독립 출처 비율, raw-span entailment 비율, contradiction coverage, `as_of_violation=0`, thesis 유래 unsupported numeric `=0`, stale/degraded thesis 사용률. 이 지표가 없으면 형식만 좋아지고 근거성은 그대로인 구현도 성공 처리됩니다.