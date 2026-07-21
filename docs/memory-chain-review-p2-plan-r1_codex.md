## 판정

**승인 보류 — 블로커 12건.** 전체 분해와 T1→T6 의존 방향은 대체로 맞지만, 현재 형태로는 가드레일을 우회하거나 실제 운영 호출이 빠진 채 테스트만 통과할 수 있습니다.

## 블로커

1. **B1 — 지지성 검증이 장애·부분응답에서 fail-open입니다.**

   검증 예외·invalid·누락 판정을 모두 “근거 유지”로 처리하므로, 생성 LLM이 관계없는 저장 인용을 붙이고 검증기가 실패하면 그대로 revision에 들어갑니다. 이는 교차 검증 게이트 자체를 무력화합니다. 또한 응답 식별자가 `quote`라 중복 인용을 안전하게 대응시킬 수 없습니다. [계획:272](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:272), [계획:317](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:317), [스펙:209](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:209)

   검증 결과를 `(statement_id, card_id)`로 결속하고 입력 근거마다 정확히 1개 판정을 요구해야 합니다. 예외·누락·중복·미지 ID는 해당 신규 revision 전체를 skip해 직전 revision을 유지하면 never-block도 보존됩니다.

2. **B2 — `assessment`와 statement↔seed 관계를 LLM 그대로 신뢰합니다.**

   계획의 아키텍처는 LLM 제안을 “statement·근거 후보·metric 이름”으로 한정하지만, 실제 `_ProposalOut`에는 `assessment`가 있고 그대로 revision에 복사됩니다. 검증기는 quote가 statement를 지지하는지만 보고, statement가 seed claim과 관련 있는지 또는 assessment 방향과 일치하는지는 보지 않습니다. 따라서 “관계없는 참인 문장 + 임의의 strengthening”이 통과합니다. [계획:7](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:7), [계획:272](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:272), [계획:333](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:333)

   교차 검증에 statement↔seed claim 관계를 포함하고, 검증된 관계에서 assessment를 코드로 집계해야 합니다.

3. **B3 — verifier가 근거를 제거한 뒤 독립 출처를 재검사하지 않습니다.**

   현재 순서는 `filter_statements → verify_statements`이고, verifier 이후에는 단순히 `supporting < 2`만 봅니다. A/B가 전재 중복이고 C만 독립인 3개 근거가 처음에는 2개 주체로 통과한 뒤 C가 기각되면, A/B 두 건이 남아 독립 주체 1개인데도 저장됩니다. [계획:272](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:272), [계획:334](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:334), [스펙:204](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:204), [스펙:212](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:212)

   verifier 뒤 전체 `filter_statements`를 다시 실행해야 합니다.

4. **B4 — quote·publisher 구조 검증에 직접 우회가 남습니다.**

   `Evidence.quote`에는 비어 있지 않다는 제약이 없고, 단순 substring 구현이면 Python에서 `"" in raw_quote`가 참입니다. 빈 quote 한 건과 정상 quote 한 건으로 supporting 2건을 만들 수 있습니다. 빈 URL/publisher도 독립 주체에서 명시적으로 제외되지 않습니다. 또한 스펙은 등록 가능 도메인을 요구하지만 계획은 불완전한 2~3라벨 휴리스틱을 명시합니다. 실제 `SectorCard`에는 `canonical_url`이 아니라 단순 `url`만 있습니다. [계획:47](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:47), [계획:185](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:185), [계획:188](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:188), [contracts.py:27](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:27), [스펙:203](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:203)

   `quote.strip()`, 유효한 HTTP(S) URL, 비어 있지 않은 registrable domain을 요구하고, Evidence에 담긴 publisher 값은 믿지 말고 guard 내부에서 카드 URL로 매번 재파생해야 합니다. PSL 기반 구현을 쓰면 `engine/requirements.txt` 변경도 T3에 포함해야 합니다.

5. **B5 — key metric 역참조가 현재 저장 계약과 맞지 않습니다.**

   `MetricObservation`에는 `source` 필드가 없으므로, 스펙이 요구하는 source 역참조를 할 수 없습니다. 계획은 이를 `source="sector_store"` 기본값으로 대체해 원 관측 provenance를 잃습니다. [contracts.py:37](/home/ryze_yn/attn-viewer/engine/sector/contracts.py:37), [계획:49](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:49), [스펙:215](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:215)

   더 큰 문제는 metric 하나가 여러 `meta` 시계열을 포함한다는 점입니다. 같은 2026-07에 DRAM·NAND 값이 함께 있고, `read_metric`은 `ts`만 정렬하므로 “마지막 한 건”은 파일 적재 순서에 의해 NAND가 될 수 있습니다. [store.py:110](/home/ryze_yn/attn-viewer/engine/sector/store.py:110), [memory_price_usd_per_gb.jsonl:214](/home/ryze_yn/attn-viewer/storage/rag/memory_sector/metrics/memory_price_usd_per_gb.jsonl:214), [memory_price_usd_per_gb.jsonl:222](/home/ryze_yn/attn-viewer/storage/rag/memory_sector/metrics/memory_price_usd_per_gb.jsonl:222)

   고정된 meta/group selector를 seed에 두거나 그룹별 최신 관측을 모두 반환해야 합니다. 아울러 `resolve_key_metrics`는 선언상 `list`인데 테스트는 `(metrics, dropped)`를 요구하는 시그니처 충돌도 있습니다. [계획:191](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:191), [계획:255](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:255)

6. **B6 — seed·테스트가 운영 entity 어휘와 다른 가짜 세계를 사용합니다.**

   계획 테스트는 `"SK하이닉스"`를 seed와 카드 양쪽에 넣어 통과하지만, 운영 `extract_entities`는 `SK_HYNIX` 같은 canonical ID를 저장합니다. 실제 카드 필터에서는 seed entity가 매치되지 않습니다. [계획:71](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:71), [계획:371](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:371), [entities.py:7](/home/ryze_yn/attn-viewer/engine/sector/entities.py:7), [OpenAPI:2228](/home/ryze_yn/attn-viewer/openapi.yaml:2228)

   8개 seed를 `ENTITY_PATTERNS`, `Axis`, `EventType`, segment 어휘, `METRIC_REGISTRY`에 대해 실행 가능하게 검증해야 합니다. 현재 shape 테스트만으로는 metric 오타로 8개 thesis가 전부 skip되어도 통과합니다. [계획:103](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:103)

7. **B7 — 제시된 수량 정규식이 명시적 허용·금지 규칙을 모두 어깁니다.**

   계획의 정규식을 그대로 평가하면 허용해야 하는 `gpt-5.5`에서 `5.5`를 검출하고, 금지해야 하는 통화 결합 `USD12`·`12USD`는 놓칩니다. 테스트도 HBM3E·DDR5만 있어 이 오류를 잡지 못합니다. [계획:217](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:217), [계획:260](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:260), [스펙:217](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:217)

   `gpt-5.5`, HBM3E, DDR5, H100과 `$12`, `₩12`, `USD12`, `12 USD`, 퍼센트·bp·독립 숫자를 acceptance matrix로 고정해야 합니다.

8. **B8 — revision 참조·replay 계약이 Pydantic으로 강제되지 않습니다.**

   `revision_id == f"{id}@{valid_from}"`가 아니라 `startswith`만 검사하고, `axis`, `selectors`, `input_snapshot`은 넓은 `str/dict`입니다. 잘못된 revision ID나 replay 불가능한 snapshot도 저장됩니다. [계획:51](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:51), [계획:89](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:89), [스펙:175](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:175), [스펙:191](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:191)

   `Axis` 재사용, typed `Selectors`·`InputSnapshot`, canonical UTC timestamp, revision ID equality validator가 필요합니다. Snapshot은 최종 채택 근거만이 아니라 LLM prompt에 실제 제공된 모든 card/metric observation ID를 담고 이를 정확한 집합으로 테스트해야 합니다. 현재 테스트는 card ID가 하나라도 있으면 통과합니다. [계획:332](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:332), [계획:403](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:403)

9. **B9 — thesis bundle 기능이 실제 전향 캡처 경로에 배선되지 않았습니다.**

   테스트는 `thesis_store=tstore`를 직접 전달하지만, 운영 절차가 호출하는 `cmd_capture`는 현재 `capture_bundle`에 그 인자를 전달하지 않습니다. `None`이 “미포함”이면 새 proven bundle에도 thesis가 없고, “자동 탐색” 의미라면 그 동작과 테스트가 계획에 없습니다. [계획:437](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:437), [계획:462](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:462), [build_chain_cases.py:128](/home/ryze_yn/attn-viewer/engine/evals/build_chain_cases.py:128), [README-chain.md:31](/home/ryze_yn/attn-viewer/engine/evals/README-chain.md:31)

   또한 실 `as_of`는 날짜인데 revision `valid_from`은 timestamp라 단순 문자열 비교 시 당일 revision이 제외됩니다. 기존 24개 bundle에는 파일이 없으므로 `EvalBundle.theses()`가 `[]`를 반환하는 하위호환 테스트도 필요합니다. 실제 `cmd_capture` 통합 테스트에서 당일 이전 revision 포함·캡처 이후 revision 제외를 검증해야 합니다.

10. **B10 — 신규 API가 OpenAPI 계약을 누락합니다.**

    Task 6은 `api.py`와 bundle만 수정하고 `openapi.yaml`을 포함하지 않습니다. 이는 계약 우선 규칙 위반이며, 현재 route-contract 테스트가 새 FastAPI route를 즉시 실패시킵니다. [계획:430](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:430), [AGENTS.md:21](/home/ryze_yn/attn-viewer/AGENTS.md:21), [openapi-routes.test.mjs:52](/home/ryze_yn/attn-viewer/test/contract/openapi-routes.test.mjs:52)

    T6 첫 단계가 `/v1/sector/theses` path와 엄격한 Thesis 응답 스키마 추가여야 하며 `npm run check:openapi`와 `npm run test:contract`가 완료 조건이어야 합니다.

11. **B11 — 테스트가 실제 파이프·역할·불변식을 검증하지 않아 가짜 통과가 가능합니다.**

    - `update_thesis`가 verifier를 전혀 호출하지 않아도 정상 생성 테스트가 통과합니다. fake verifier의 호출 횟수나 기각 결과가 integration assertion에 없습니다. [계획:360](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:360), [계획:393](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:393)
    - required-input 테스트는 `_Updater({})` 호출 후 validation 실패를 삼켜도 `None`이 되어 통과하므로 “LLM 호출 전 gate”를 증명하지 않습니다. [계획:417](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:417)
    - `update_all`이 실제 `Role("thesis_updater")`와 `Role("thesis_verifier")`를 생성하는지, 두 provider가 다른지, runner가 호출하는지 테스트가 없습니다.
    - freshness 테스트는 required input 하나/min_count=1의 fresh·stale만 보므로 `degraded`나 `min_count`를 구현하지 않아도 통과합니다. [계획:158](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:158)
    - updater 예외가 수집 반환·status를 방해하지 않는지와, 모든 collector가 실패해도 updater가 호출되는지 검증하지 않습니다. 실제 runner는 여기서 계약을 강제해야 합니다. [runner.py:15](/home/ryze_yn/attn-viewer/engine/sector/runner.py:15)

    호출 spy와 sentinel role을 사용해 실제 순서, post-verifier 재가드, pre-LLM required gate, ROLE_MAP 배선, flag off, 양방향 never-block을 각각 검증해야 합니다.

12. **B12 — append-only 운영 데이터 생성이 교차 리뷰보다 먼저입니다.**

    Task 7은 PM2 재시작과 첫 append를 먼저 하고, 그 뒤에 Codex 리뷰를 합니다. 잘못된 revision은 append-only 파일에서 제거할 수 없으므로 순서가 반대여야 하며, 스펙의 단계별 교차 리뷰 규칙에도 어긋납니다. [계획:481](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:481), [계획:483](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:483), [스펙:271](/home/ryze_yn/attn-viewer/docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md:271)

    전체 테스트·정적 재감사·Codex 승인 후에만 PM2 재시작과 첫 live append를 수행해야 합니다.

## 권고

- **답변 경로 무접촉은 현재 성립합니다.** 현재 orchestrator는 bundle에서 store/snapshot만 사용하고 thesis를 읽지 않습니다. [orchestrator.py:176](/home/ryze_yn/attn-viewer/engine/orchestrator.py:176), [orchestrator.py:330](/home/ryze_yn/attn-viewer/engine/orchestrator.py:330) 다만 이를 “주입 가드 구현 완료”라고 부르면 안 됩니다. 계획 self-review의 해당 문구는 “P2에서는 주입 자체가 없음, P3 게이트”로 바꾸고, P3에서 background-only·AUDIT 제외·stale 금지·주입 시 수량 재검사·`disable_p23` off/on을 코드 테스트해야 합니다. [계획:490](/home/ryze_yn/attn-viewer/docs/superpowers/plans/2026-07-21-thesis-layer-p2.md:490)

- **ROLE_MAP 형태와 모델 설정 이름 자체는 실코드와 맞습니다.** `(provider, model, effort)` 튜플, `model_claude_sonnet`, `model_gpt_mini`, `Role.run(..., response_format=...)`는 호환됩니다. [providers.py:25](/home/ryze_yn/attn-viewer/engine/providers.py:25), [providers.py:147](/home/ryze_yn/attn-viewer/engine/providers.py:147), [settings.py:28](/home/ryze_yn/attn-viewer/engine/app/settings.py:28) 문제는 선언이 아니라 production factory 배선 테스트 부재입니다.

- 월 단위 timestamp의 “말일 해석”은 진행 중인 달에서는 미래 시각이 되어 오히려 낙관적입니다. 월말 기준을 유지하려면 age를 0으로 clamp한다는 의미를 명시하고, 미래·invalid timestamp는 fail-closed 처리하십시오. `update_thesis(now=...)`의 14일 카드 선택도 실제 시계가 아니라 주입된 `now`를 사용해야 테스트가 시한부가 되지 않습니다.

- `contradicting`은 스키마에 있지만 proposal과 guard·verifier 경로에는 없습니다. 항상 빈 배열로 둘 의도라면 명시하고, 사용한다면 supporting과 동일한 quote/card 검증을 적용해야 합니다.

- scheduler와 CLI가 겹치면 “기존 ID 검사 후 append” 사이에 race가 생깁니다. 파일 잠금 또는 원자적 단일-writer를 추가하고, 같은 내용의 revision을 매 수집마다 반복 append할지 정책도 고정하는 편이 좋습니다.

## 권장 태스크 순서

1. OpenAPI/공유 MetricObservation provenance 계약 확정
2. typed Thesis 계약·canonical seed
3. store·freshness·revision identity
4. 구조 guard
5. fail-closed 교차 verifier
6. updater 직접 통합 테스트
7. runner hook·never-block 테스트
8. 실제 `cmd_capture` bundle 배선·API
9. 전체 Python/Node/OpenAPI 회귀
10. Codex 교차 리뷰
11. PM2 배포·첫 live append·산출물 재감사

이 순서로 B1~B12를 닫으면 2부 구현 착수 가능한 계획으로 수렴합니다.