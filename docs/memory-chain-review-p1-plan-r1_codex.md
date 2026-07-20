판정: 승인 불가. 계획대로 구현하면 주요 스펙 게이트가 강제되지 않거나 가짜 통과할 수 있다. 블로커 12건이다.

## 블로커

1. **[B1] `as_of_violation=0` 검출기가 실제 이벤트 구조를 읽지 않는다.**

   계획의 검출기는 `data.documents`와 `data.cards`만 순회한다([계획 684행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:684)). 실제 RA 레이어는 `items`([orchestrator.py 105행](/home/ryze_yn/attn-viewer/engine/orchestrator.py:105)), 뉴스 요약은 `lines`([orchestrator.py 243행](/home/ryze_yn/attn-viewer/engine/orchestrator.py:243))다. 최종 답변 본문도 검출기에 전달되지 않고 `final_meta`는 아예 사용하지 않는다([계획 993행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:993)). 테스트도 실제 `items`가 아닌 가짜 `documents` 구조를 써서 통과한다([계획 577행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:577)).

   따라서 RA나 최종 답변에 bundle 밖 URL이 들어가도 0으로 보고될 수 있다. `must_not_hit`도 기록만 하고 실패시키지 않는다. 실제 레이어·최종 답변·출처 ID를 검사하고, 한 건이라도 있으면 비정상 종료해야 한다.

2. **[B2] 케이스의 `as_of`가 파이프라인 기준 시점으로 강제되지 않는다.**

   `run_chain_suite`는 bundle 경로만 넘기고 `row["as_of"]`는 `run_qa`에 전달하지 않는다([계획 984행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:984)). 실제 PLAN은 기본적으로 오늘을 선택한다([plan.py 203행](/home/ryze_yn/attn-viewer/engine/stages/plan.py:203)). DA는 모델의 파라메트릭 지식으로 답하며([da.py 36행](/home/ryze_yn/attn-viewer/engine/stages/da.py:36)), 그 독립 답변 전문이 검증 결과와 무관하게 SYNTHESIZE에 들어간다([synthesize.py 106행](/home/ryze_yn/attn-viewer/engine/stages/synthesize.py:106)). 섹터 검색 점수도 bundle 시점이 아니라 실행 시각 `now`를 사용한다([retrieve.py 144행](/home/ryze_yn/attn-viewer/engine/sector/retrieve.py:144)).

   외부 검색만 끈다고 frozen 재생이 되지 않는다. PLAN 직후 `knowledge_cutoff == manifest.as_of`를 코드로 덮어쓰고 검증하며, 검색·랭킹의 기준 시계도 bundle `as_of`로 고정해야 한다.

3. **[B3] bundle이 불완전하고 불변성도 보장하지 않는다.**

   스펙은 카드·지표·가격/매크로·thesis·RA를 고정하고 bundle hash를 기록하도록 요구한다([스펙 52행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:52), [스펙 110행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:110)). 계획은 `prices.json`만 두며 macro와 thesis가 없고, hash도 없다([계획 523행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:523)). `bundle_text()`는 주석과 달리 지표·가격을 전혀 넣지 않는다([계획 649행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:649)). 반면 파이프라인은 bundle 지표를 답변 숫자로 사용할 수 있어, 저지는 실제 사용 근거를 bundle 밖이라고 오판한다.

   또한 기존 디렉터리를 `exist_ok=True`로 열고 파일을 덮어쓴다([계획 659행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:659)). baseline 후 bundle이 변경되어도 탐지할 방법이 없다. 내용 hash manifest, overwrite 거부, 실행 전 hash 검증이 필요하다.

4. **[B4] 실제 캡처는 카드가 잘리고 RA·가격은 전부 빈 상태가 된다.**

   `capture_bundle`의 `store.read_cards(days=None)`는 전량 조회가 아니다([계획 661행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:661)). 실제 `SectorStore` 기본 `limit=500`이고 최신순 500건만 반환한다([store.py 53행](/home/ryze_yn/attn-viewer/engine/sector/store.py:53)). 오래된 회고 시점은 최근 500건을 먼저 받은 뒤 `as_of`로 잘라 빈 bundle이 될 수 있다. 후보 목록 CLI도 같은 문제다.

   더구나 24개 캡처 루프는 `--ra-docs`와 `--prices`를 넘기지 않는다([계획 1127행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1127)). 결과는 사실상 섹터 저장소만 있는 bundle이다. `limit=10_000` 이상의 명시적 조회와 RA·price/macro 캡처가 케이스 생성의 필수 입력이어야 한다.

5. **[B5] Task 4·5의 코드와 테스트가 현재 계약에 직접 맞지 않는다.**

   - 테스트의 `PlanPacket`은 필수 `original_question`, `knowledge_cutoff`가 없다([계획 749행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:749), [packets.py 104행](/home/ryze_yn/attn-viewer/engine/contracts/packets.py:104)).
   - `SectorCard.direction="positive"`는 실제 허용값 `pos|neg|neutral|mixed`와 다르다([계획 541행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:541), [sector/contracts.py 22행](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:22)).
   - `Quote`, `RADocument`, `_package`, `pkt.documents`는 존재하지 않는다. 실제 계약은 raw dict인 `PriceMacroPacket.quotes`([packets.py 291행](/home/ryze_yn/attn-viewer/engine/contracts/packets.py:291))와 `RaPacket.x_search: dict[str,list[NewsItem]]`([packets.py 246행](/home/ryze_yn/attn-viewer/engine/contracts/packets.py:246))다.
   - `macro=[]`도 실제 `dict` 계약과 다르다.
   - 보충 검색 차단 지시의 `supp_docs=[]`는 실제 변수명이 아니다. 실제 흐름은 `(found, new_claims)`를 받는다([orchestrator.py 372행](/home/ryze_yn/attn-viewer/engine/orchestrator.py:372)).

   “구현 시 확인”이라는 주석으로는 해결되지 않는다. 현재 제시된 테스트와 본문은 그대로 실행할 수 없다.

6. **[B6] 봉인 calibration은 실행기의 게이트가 아니다.**

   `run_chain_suite`는 `run_selftest`만 호출한다([계획 959행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:959)); `run_sealed`는 Task 8의 수동 절차일 뿐이며, 이미 baseline을 저장한 뒤 실행한다([계획 1140행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1140), [계획 1148행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1148)). 봉인 셋이 없거나 실패해도 chain 평가 자체는 정상 종료한다.

   첫 시도 기록, prompt-version 및 sealed-set hash 결합, 재실행 금지 장치도 없다. 빈 sealed 리스트는 자동 통과한다. 봉인 통과 전 결과는 `invalid`로 표시하고 authoritative baseline을 다시 실행해야 한다.

7. **[B7] 봉인 변형의 정답이 기계적으로 알려져 있지 않다.**

   스펙은 방향 반전·countercase 삭제·가짜 ID·수치 변조를 요구한다([스펙 94행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:94)). 계획은 방향 반전 대신 verdict 삭제, 수치 변조 대신 무관한 허위 숫자 추가, 그리고 identity를 사용한다([계획 428행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:428), [계획 440행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:440)).

   특히 evidence 점수 정의가 rubric evidence의 `matched/total`인데([계획 122행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:122)), 숫자 한 줄을 추가해도 기존 matched/total은 내려가지 않는다. countercase 정규식도 실제 합성 지시의 “위험·반대 시나리오” 형식을 보장하지 않는다([synthesize.py 30행](/home/ryze_yn/attn-viewer/engine/stages/synthesize.py:30)). 올바른 저지가 실패하거나 방향에 무감한 저지가 통과할 수 있다.

8. **[B8] paired-validity 90%와 holdout 성공 기준이 구현되지 않는다.**

   계획 스스로 비교 실행을 제외했다고 명시한다([계획 1173행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1173)). 따라서 CI 하한, `+0.3`, 90% 폐기 조건을 실행하는 호출자가 없다.

   준비한 `paired_valid`도 candidate에 존재하는 교집합만 분모로 삼아 누락된 케이스를 숨길 수 있고, `axes.values()`만 검사해 일부 축만 있는 dict도 유효로 인정한다([계획 886행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:886)). 실행기는 null을 제외한 평균을 출력하고 목록만 기록한다([계획 1013행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1013)). `--split holdout --limit N`도 허용하며 `availability: proven` 필터와 holdout 1회 사용 기록이 없다.

9. **[B9] 필수 두 채점 패스가 완전히 누락됐다.**

   스펙의 `entailed_edge_ratio`와 `uncovered_claim_ratio`([스펙 104행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:104))가 계획의 결과 계약·실행·리포트 어디에도 없다. `AXES`는 5개 루브릭 축뿐이다([계획 116행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:116)). 따라서 ChainPacket에서 좋은 edge만 선택하거나 최종 답변에 미지원 주장을 추가해도 성공 기준을 검증할 수 없다.

   더불어 `ChainAxisScore.score`는 범위 제한 없는 `float`이고 matched/missing과 점수의 정합도 검증하지 않는다([계획 126행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:126)). 음수나 2.0도 유효 응답으로 들어가 평균과 CI를 오염시킨다.

10. **[B10] `availability: proven` 및 회고=dev 불변식이 코드로 강제되지 않는다.**

    스펙은 지금부터 `as_of=captured_at` 전향 캡처와 `ingested_at`을 요구한다([스펙 67행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:67)). 현재 `SectorCard`와 `MetricObservation`에는 `ingested_at`이 없고([sector/contracts.py 13행](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:13)), 저장 시에도 찍지 않는다([store.py 36행](/home/ryze_yn/attn-viewer/engine/sector/store.py:36)).

    캡처 CLI는 임의 과거 `--as-of`에 `--availability proven`을 붙일 수 있으며([계획 1103행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1103)), manifest는 이를 그대로 신뢰한다. 케이스 split·케이스 availability·manifest availability의 교차 검증도 없다. 회고 데이터가 holdout/proven으로 잘못 편입될 수 있다.

11. **[B11] Task 8 완료 시점에도 스펙의 holdout이 0개다.**

    스펙의 데이터셋 계약은 24문항 dev 14 + holdout 10이며, 배포 holdout은 proven이어야 한다([스펙 74행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:74)). 계획은 24개 전부 dev/unproven으로 만들고([계획 1117행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1117)), 전향 축적을 4부로 미룬다([계획 1174행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1174)).

    이 순서로는 Task 9에서 1부 완료를 승인할 수 없고, 2·3부 후 배포 시점에도 10개 proven holdout이 없을 수 있다. `ingested_at`과 전향 캡처는 Task 1보다 앞서 시작해야 한다.

12. **[B12] 기존 golden 회귀와 계획 명령 자체가 실패 가능 상태다.**

    스펙은 기존 `verified_ratio·keyword` 유지를 요구하지만([스펙 246행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:246)), 계획은 테스트 후 golden 한 문항을 실행할 뿐 이전 수치와 비교하거나 실패시키지 않는다([계획 1024행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1024)).

    또한 모든 명령의 cwd를 `engine/`으로 고정하면서([계획 25행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:25)) commit 단계는 `git add engine/...`을 사용한다([계획 225행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:225)). 이 위치에서는 `engine/engine/...`으로 해석되어 Task 1부터 pathspec이 실패한다.

## 권고

1. 반복 채점의 원시 결과를 전부 보존하라. 현재 병합 결과는 첫 응답의 `raw`만 남긴다([계획 171행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:171)). `r1/r2/r3`, reason, matched/missing, judge model을 각각 저장해야 판정 변동을 감사할 수 있다.

2. 케이스 작성보다 bundle 캡처가 먼저여야 한다. 현재 rubric 작성이 Step 2, bundle 캡처가 Step 3이다([계획 1117행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1117), [계획 1124행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1124)). `capture → manifest/hash 검증 → rubric evidence를 bundle ID에서 선택 → 케이스 스키마 검증` 순서가 안전하다.

## 필요한 재배치

수정 순서는 다음이어야 한다.

1. `ingested_at`·전향 캡처·불변 bundle/hash부터 활성화
2. 실제 `RaPacket`·`PriceMacroPacket` 계약에 맞춘 bundle mode 구현
3. 네트워크 함수를 모두 “호출되면 실패”로 monkeypatch한 orchestrator 통합 테스트
4. 실제 이벤트 레이어·최종 답변을 대상으로 누출 검출
5. 공개 fixture로 프롬프트 동결
6. 비권위 pilot 답변으로 새 봉인 셋 생성 → 첫 실행 결과 append-only 기록
7. 봉인 통과 후 authoritative baseline 재실행
8. proven holdout 전용 paired gate와 holdout 소비 기록 구현
9. 기존 golden 회귀까지 통과한 뒤 Task 9 리뷰

B1~B12가 해소되기 전에는 1부 완료나 다음 부 착수를 승인하면 안 된다.