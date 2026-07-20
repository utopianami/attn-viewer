최종 판정: **승인 보류**. 6건 중 **5건 해소, B1 1건 미해소**다.

| 항목 | 판정 | 근거 |
|---|---|---|
| B1 | **[미해소]** | 근거 토큰 검사가 쉼표 앞 첫 토큰만 읽어([계획 T4](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1020)), 실제 comma-joined RA ref의 후속 ID가 검증되지 않는다([ra_external.py](/home/ryze_yn/attn-viewer/engine/stages/ra_external.py:534)). 반대로 실제 가격 ref는 `yahoo:<symbol>`인데([price_macro.py](/home/ryze_yn/attn-viewer/engine/stages/price_macro.py:42)), 허용 목록은 `yahoo`와 symbol을 따로 등록해 정상 인용을 거부한다([계획 T4](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1036)). `calc`도 여전히 무조건 허용된다. 이는 각각 게이트 무력화와 정상 실행 실패에 해당한다. |
| B4 | **[해소]** | `capture_bundle`이 proven의 당일 캡처와 빈 채널 사유를 직접 강제하고 manifest에 기록한다([계획 T0](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:202)). 공식 proven 절차도 auto-live를 강제한다([계획 T0](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:321)). |
| B6 | **[해소]** | 서로 다른 base 2개 × 변형 5종 = 정확히 10개를 검사하며, `run_sealed` 시작점에서 구조 오류를 거부한다([계획 T3](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:820)). |
| B7 | **[해소]** | 각 base의 `verdict=1`, `countercase=1`, `evidence>0`을 요구하므로 항상-0 무감각 저지가 통과할 수 없다([계획 T3](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:835)). |
| B8 | **[해소]** | **원자성 요구를 충족한다.** holdout 단독 실행을 금지하고, 한 명령이 같은 코드·bundle에서 `disable_p23`만 바꿔 off-arm과 on-arm을 연속 생성한다. 첫 답변 전에 `claimed`를 기록하며 실패해도 claimed 집합 재사용이 금지되므로 외부 baseline 주입과 실패 후 재관측이 모두 차단된다([계획 T7](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1346)). 여기서의 판정은 평가 프로토콜 원자성 기준이며, ledger의 잠금·내구 기록은 Task 9 구현 리뷰에서 확인하면 된다. |
| B10 | **[해소]** | runner가 split·availability·as_of·manifest hash를 교차검증하고, proven은 `captured_at[:10] == manifest.as_of`까지 강제하므로 hash-valid 회고 bundle 위장이 통과하지 않는다([계획 T7](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-20-chain-eval-p1.md:1368)). |

승인 조건은 B1 하나다. **모든 쉼표 구분 근거를 전부 검증하고, `yahoo:<symbol>` 같은 실제 ref 문자열을 manifest provenance에 등록하며, `calc`도 실제 생성된 근거에 결속**하면 계획 승인이 가능하다.