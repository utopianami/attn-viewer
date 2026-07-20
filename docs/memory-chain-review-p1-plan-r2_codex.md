최종 판정: **승인 보류**.  
해소는 **B2, B11** 두 건이며, 나머지 10건은 스펙 게이트 우회 또는 구현 실패 가능성이 남아 있다.

## B1~B12

| 항목 | 판정 | 근거 및 해소 방법 |
|---|---|---|
| B1 | **[미해소]** | 검출 대상이 여전히 `ra_x.items`, `sector_rag.cards`, 답변 URL뿐이다([v2 803행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:803), [931행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:931)). 실제 `ra_web`·`news_summary.lines`도 증거 레이어이고([orchestrator.py 243행](/home/ryze_yn/attn-viewer/engine/orchestrator.py:243), [310행](/home/ryze_yn/attn-viewer/engine/orchestrator.py:310)), `[근거:ghost]` 같은 bundle 밖 ID는 URL이 없어 통과한다. **해소:** 모든 증거 레이어와 답변의 URL·근거 ID·가격/매크로 provenance를 manifest와 대조한다. |
| B2 | **[해소]** | PLAN 직후 `knowledge_cutoff` 덮어쓰기, 섹터 랭킹 `ref_now`, 두 보충검색 차단이 실행 경로에 명시됐다([v2 979행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:979), [1051행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1051)). |
| B3 | **[미해소]** | hash가 `manifest.json`을 완전히 제외해 `as_of`, `availability`, `urls`, `card_ids`를 바꿔도 검증을 통과한다([v2 180행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:180), [896행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:896)). 또한 `macro.json`을 저장하지만 pipeline에는 `prices()`만 전달한다([210행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:210), [1068행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1068)). **해소:** 상대경로+내용과 hash 필드 제외 manifest 정규형을 함께 해시하고, `prices()`와 `macro()`를 하나의 snapshot으로 주입한다. |
| B4 | **[미해소]** | 500건 절단은 고쳤지만, 전향 holdout의 공식 캡처 절차가 RA·가격·매크로를 항상 `[]/{}/{}`로 넣는다([v2 283행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:283)). 따라서 원래 지적한 실제 증거 공백이 proven holdout에서 재현된다. **해소:** 캡처 시점의 실제 RA·quote·macro를 자동 수집하고, 가용한 채널의 빈 입력은 사유 없이는 거부한다. |
| B5 | **[미해소]** | snapshot fixture는 `regularMarketPrice`를 쓰지만([v2 1016행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1016)), 실제 조립 계약은 `token`·`last`를 요구한다([price_macro.py 33행](/home/ryze_yn/attn-viewer/engine/stages/price_macro.py:33), [yahoo.py 79행](/home/ryze_yn/attn-viewer/engine/tools/price/yahoo.py:79)). RA fixture의 `snippet`도 extra-forbid `NewsItem` 계약(`summary`, `content`)과 다르다([v2 1032행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1032), [packets.py 226행](/home/ryze_yn/attn-viewer/engine/contracts/packets.py:226)). **해소:** 실제 `quote()` 반환 스키마와 `NewsItem.model_dump()`만 bundle 계약으로 고정하고 그대로 실행되는 테스트를 제시한다. |
| B6 | **[미해소]** | ledger 키가 `(version, sealed_hash)`라 실패 후 같은 prompt version에서 sealed 파일만 바꾸면 다시 첫 시도를 할 수 있다([v2 1220행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1220)). 또한 봉인 생성기는 pilot의 `rubric`·`bundle_text`를 읽지만([1327행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1327)), pilot은 “answer_md만 저장”하고 runner 레코드 계약에도 두 필드가 없다([1230행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1230), [1319행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1319)). **해소:** prompt version당 hash 하나만 허용하고, 봉인 생성기가 case/bundle 원본을 직접 읽도록 한다. |
| B7 | **[미해소]** | 수치 변조 정규식이 모든 숫자를 바꿔 `[근거:c-1]` 같은 인용 ID까지 손상시킨다([v2 724행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:724)). 숫자에 무감하고 유령 ID만 잡는 저지도 통과할 수 있다. 임의 pilot이 숫자·countercase를 실제로 포함하는지도 검증하지 않는다. **해소:** 인용 span을 보호한 수치만 변조하고, base 축 점수·변형 대상 존재·변형 전후 차이를 봉인 생성 시 강제한다. |
| B8 | **[미해소]** | 동일 holdout 집합 재사용을 무조건 차단하므로 baseline 실행이 ledger에 기록된 뒤 candidate가 같은 집합으로 paired 비교할 수 없다([v2 1225행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1225)). 성공 기준도 “판정 출력”만 하고 실패 종료가 명시되지 않았다([1233행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1233)). **해소:** baseline+candidate를 단일 experiment로 원자 실행해 한 번만 소비하고, 90%·CI·+0.3 미달은 exit 1로 강제한다. |
| B9 | **[미해소]** | 점수 범위와 coverage 패스는 생겼지만 `uncovered_claim_ratio ≤ 0.2`는 평균 리포트만 있고 게이트가 아니다([v2 1230행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1230), [스펙 235행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:235)). **해소:** proven holdout에서 coverage 초과를 exit 1로 만들고, 3부부터 `entailed_edge_ratio` null을 허용하지 않는 전환 게이트를 명시한다. |
| B10 | **[미해소]** | case↔manifest 교차검증은 수동 `validate`에만 있고([v2 1275행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1275)), runner 게이트는 case의 `availability`만 확인한다([1225행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1225)). hash도 manifest를 보호하지 않아 unproven bundle을 proven으로 바꿀 수 있다. **해소:** runner가 ledger 기록 전에 hash-bound manifest와 case의 split·availability·as_of·captured_at을 매번 검증한다. |
| B11 | **[해소]** | 아래 별도 판정과 같다. |
| B12 | **[미해소]** | git 경로는 고쳤지만 regression 기준은 `verified_avg` 하나뿐이고 keyword 기준이 없다([v2 270행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:270), [1215행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1215)). 더구나 기준 리포트는 10문항인데([기준 리포트 1행](/home/ryze_yn/attn-viewer/engine/evals/out/report-20260714-211007.md:1)) 검사는 `--limit 5`다([v2 1357행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1357)). **해소:** 동일 ID 전체 코호트의 per-case verified·keyword 기준을 저장하고 양쪽 모두 퇴행 시 exit 1로 한다. |

## B11 명시 판정

**스펙과 정합하다.**

스펙은 초기 회고 케이스를 dev·진단용으로 두고([스펙 80행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:80)), 전향 holdout을 1부 직후부터 2·3부 기간에 축적한다고 명시한다([스펙 82행](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:82)). v2는 Task 0에서 이를 더 일찍 가동하므로 충돌하지 않는다.

정확한 행 번호만 정정하면, 일정 문구는 현재 파일의 **82~83행**이고 76행은 “성공 판정은 holdout 기준”이라는 원칙이다. 1부 완료를 dev baseline과 전향 축적 가동으로 정의하고 실제 배포 판정을 4부 proven holdout으로 미루는 해석은 맞다.

## v2 신규 블로커

1. **N1 — ingested_at 구현 예시가 즉시 실패한다.** 계획은 `card`·`obs`를 사용하지만([v2 157행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:157)), 실제 루프 변수는 `c`·`o`다([store.py 40행](/home/ryze_yn/attn-viewer/engine/sector/store.py:40), [96행](/home/ryze_yn/attn-viewer/engine/sector/store.py:96)).  
   **해소:** 예시와 구현을 `c.ingested_at`, `o.ingested_at`으로 고친다.

2. **N2 — `--pilot`이 holdout ledger 우회 경로다.** pilot은 판정·ledger 없이 답변을 저장하지만 dev-only 코드 제약이 없다([v2 1319행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1319)). `--pilot --split holdout`으로 무제한 peek가 가능하다.  
   **해소:** pilot은 `split=dev && availability=unproven`만 허용하고 holdout·compare와 조합되면 즉시 실패시킨다.

3. **N3 — holdout 10개·ID 유일성이 게이트가 아니다.** holdout 게이트는 proven과 `--limit`만 검사하고([v2 1225행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1225)), validate도 개수·중복을 확인하지 않는다([1275행](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1275)). 1개 또는 중복 케이스만으로도 성공 판정이 가능하다.  
   **해소:** ledger 전에 정확히 10개의 고유 proven ID와 요구 층화를 스키마 게이트로 강제한다.