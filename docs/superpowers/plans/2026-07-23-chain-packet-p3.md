# ChainPacket 체인 합성 + SYNTHESIZE 주입 (스펙 3부) Implementation Plan (v4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

v4 — codex r3 잔존 블로커 4건 반영: **1**(golden 양팔 밀폐 — T1: baseline은 pre-P3 SHA 워크트리 캡처(기존 유지), **candidate(identity 비교·T10 회귀 게이트 포함)도 현재 HEAD 커밋의 별도 clean 워크트리**(`git worktree add <tmp> HEAD`)에서 동일 고정 시계·동일 canned 역할로 실행 — 공유 작업트리의 dirty 파일(예: orchestrator.py:418 price layer `sector_momentum` 키) 오염 차단. canned 역할 목록을 실제 호출 역할 15종으로 교정: planner·plan_extract·sector_query·da_gpt·da_fable·extract·web_knowledge·news_summary·calc_program·verifier·verifier_cross·risk·synthesizer·audit·casemem_rerank) · **2**(게이트 입력 결정화·강화 — T2·T4: `is_memory_question` 입력은 **원 질문**(triage 정제된 사용자 입력 `question` — LLM 재작성 `standalone_question` 금지) + `build_rule_plan(question)`(원 질문 기반 규칙 플랜). 규칙 강화: `_MEMORY_TOPIC_TERMS`에서 `"웨이퍼"` 단독 제거(메모리 특이 토큰 아님), 3사+문맥 규칙의 문맥어에서 `"반도체"` 일반어 제거 — 메모리 특이 문맥(메모리·D램·낸드·HBM·NAND·DRAM)만 인정. 음성 테스트 2건 추가: "TSMC 웨이퍼 가격 전망"·"삼성전자 파운드리 반도체 실적", 기존 음성 4건 유지) · **3**(체인 자유문 RISK 재주입 제거 — T6: RISK 프롬프트에서 chain의 자유문 `event`·`mechanism` 렌더 제거 — RISK는 **verified claim 텍스트 + chain_verdicts(grounded edge id·axis 참조)만** 받는다(`[인과 체인 판정]` 절은 edge_id·edge·kind·근거확인 여부만 — 전부 코드 산출·열거값). ChainEdge에 claim provenance는 추가하지 않음(스코프 최소화 — 체인은 VERIFY 이전 생성이라 verified 필터 불가). SYNTHESIZE의 event/mechanism 렌더는 유지 — 시나리오 계약에 필요하고 SYNTHESIZE는 어차피 전체 근거·claim을 보는 스테이지: "미검증 텍스트 부재" 계약은 **RISK 한정**임을 명시. RISK 프롬프트에 chain event/mechanism 자유문 부재 assertion 추가) · **4**(resolver 정밀 — T5·T10: price fixture ID를 실 shape `price:000660.KS`로 교정(price_macro.py:47 `price:{q['token']}`, token=yahoo_symbol). 스냅샷 방출은 `typed_fact_snapshot(table)` 헬퍼로 — **중복 fact ID는 방출 시점 ValueError fail-hard**(조용한 덮어쓰기 금지). resolver도 **비공백 + 전 소스 유일 해소** 강제 — 빈 id·다중 해소(스냅샷∪카드∪NewsItem에서 2개 이상 객체로 해소)는 ValueError(측정 오류). 중복 ID 테스트 추가). 설정 사항: r2-4·5·6 해소분·비블로킹 권고 2건·r1 해소 목록은 무변경 유지(재개방 금지).

v3 — codex r2 잔존 블로커 7건 반영: **1**(golden 밀폐 — T1: T1 커밋 SHA 고정 워크트리 캡처+`_meta.captured_at_sha` 기록·고정 시계 seam(plan.TODAY·queryplan.date·ra_external.date·retrieve.\_dt)·casemem `_STORE` 선주입으로 라이브 시드 기록 차단·matched playbook golden 케이스(user_id 배선)·on-arm 테스트는 `overrides={"disable_p23": False}` 명시) · **2**(메모리 게이트 — T2 `is_memory_question(question, rule_plan)` 결정적 판정: 토픽 키워드 명시 목록/segments/3사+문맥, `memory_sector_active = plan_query 성공 ∧ is_memory_question` — 엔비디아 CUDA·애플 아이폰·구글 광고·삼성 스마트폰 음성 4건+양성 테스트) · **3**(RISK verified-only — T6: 입력 claim 목록 자체를 verified로 교체+`valid_ids`도 verified 제한 — "추가" 방식 폐기) · **4**(날짜·ID fail-closed — T6: `date.fromisoformat` 실파서·불가능 날짜 거부·cutoff 미파싱 시 전 edge 불인정·인용 ID 비공백+전 소스 유일 해소, NewsItem.id `""` 기본값 테스트) · **5**(metric identity 엄격 — T6: 태그 claim은 같은 non-empty ID anchor만, untagged anchor 우회 금지 회귀 테스트·ID 없는 claim은 스코프 밖 명시) · **6**(unit·yoy fail-closed — T8: 참여 자격 = 유한값+비공백 unit+check.unit 정확 일치(빈 unit 불참→unit_mismatch)·yoy 기준점 ±45일 고정 창·registry canonical unit 마이그레이션) · **7**(resolver 전수 — T5가 chain layer에 체인 생성 시점 전체 TypedFact 스냅샷 방출, T10 resolver는 그 스냅샷으로 정확 역참조(`price:*`·`toss:*` fixture)·미해석 id는 ValueError fail-hard). 비블로킹 권고 2건: chain layer 방출 `_layer("chain", ..., round_)`로 packet meta와 round 일치 · "바이트 동일" 표현 전면 "JSON 구조 등치(고정 시계)"로 교정. r2 해소 확인 목록(SCHEMA_VERSION 분리·CHAIN_EDGES 8개·event-type opt-in·SYNTHESIZE 렌더·시나리오 H2 경계·플레이북 평가 이동+생산자·grounded 분모·EnvelopeMeta 실 round)은 무변경.

v2 — codex r1 블로커 9건 전면 반영: B1(전역 SCHEMA_VERSION 무변경·CHAIN_SCHEMA_VERSION 분리·off-arm 바이트 동일성 golden 하네스) · B2(effective_disable_p23 = run override > settings, 1회 결정 관통·eval arm 파라미터) · B3(memory_sector_active — plan_query 성공 결정적 게이트, sector_rag_enabled 아님) · B4(canonical CHAIN_EDGES 레지스트리 — judge 방출·ChainEdge validator 공용 + build_rule_plan 결정적 event-type 추출) · B5(SYNTHESIZE에 event/mechanism/verdict/thesis_relation/contradicting 렌더·RISK에 verified claim 원문·run_chain 강등 사유 가시화) · B6(소스별 날짜 필드 fail-closed grounding·시나리오 validator에 chain_verdicts·tier≥3 명시) · B7(keyword 교량 기각 — canonical metric ID 관통, 정확 키/label/유일 최장 alias, 0·복수 매칭 → anchor 사용 거부) · B8(게이트 평가 PLAN 이후 이동·sector_metric_notes 순서·selector.series+혼합단위 거부·생산자 태스크 신설+마이그레이션 명시) · B9(grounded 분모=실제 edge 집합·초과/중복=오류·judge row 정합 대조·구조화 resolver·thesis 컨텍스트·entailed None fail-hard). 판정 3건(G2 keyword 기각 / 시나리오 강화 수용 / EnvelopeMeta 실제 round 기록)·권고 6건 전부 반영. 태스크 9→11개 재번호(T1 identity 하네스·T9 생산자 신설).

v1 — 2부 SHIPPED(main=57cf3f 계열) 기반. 답변 파이프라인에 3부 전체를 disable_p23 단일 토글 뒤에 넣는 초안.

**Goal:** 답변 파이프라인에 ① thesis "배경 판" 절 주입(결정적 선택·fresh/degraded만) ② ChainPacket 체인 합성(VERIFY 이전·코드 실존 검증) ③ VERIFY chain_verdicts 산출 + RISK 소비 ④ SYNTHESIZE 긍정/부정 시나리오 계약(코드 후검증·1회 재합성) ⑤ 플레이북 구조 게이트(all-or-none, 소비+생산) — 전부 `effective_disable_p23=True`면 통째로 꺼져 기존 경로와 **JSON 구조 등치(고정 시계)**(golden 하네스로 증명).

**Architecture:** 선택·검증·게이트는 전부 코드(LLM 신뢰 없음): thesis 선택은 `build_rule_plan` 스코어링(결정적), ChainPacket 인용 ID는 실존 검증·미실존 드롭·빈 supporting 강등, chain_verdicts는 VERIFY의 코드 재검증(존재+소스별 날짜 fail-closed), 시나리오 계약은 마크다운 구조 마커+grounded edge의 코드 후검증, 게이트 값은 store 관측 역참조(series·meta·unit 전체 코드 검증). LLM은 chain 제안(sonnet)과 시나리오 서술만 한다. 숫자는 전부 TypedFact 경로(주입 절엔 수치 없음).

**Tech Stack:** Python 3.12(engine/.venv)·pydantic v2·기존 Role/SectorStore/ThesisStore. 생산자는 Node(lib/playbooks.mjs — `npm test` 게이트). 신규 HTTP 라우트 없음(openapi 무변경).

**스펙:** docs/superpowers/specs/2026-07-20-memory-chain-answer-design.md §3부 + §2부 가드레일 5 + "1부 완료 스코프"의 4부 승계 게이트 + 전역 제약

## v2 조정 — 컨트롤러 판정과 실코드가 충돌한 지점 (코드 우선)

1. **build_rule_plan event-type 추출은 opt-in 파라미터** (B4 문면과 다름): `plan.event_types`는 라이브 검색 스코어·필터에 직접 쓰인다(`sector/retrieve.py:126·179·189`). 무조건 채우면 토글 밖에서 검색 결과가 바뀌어 B1(off-arm 구조 등치)과 충돌. 해소: `extract_event_types(question)`을 공개 결정적 함수로 추가하고 `build_rule_plan(question, include_event_types=False)` 기본 off — thesis 스코어링 경로만 `True`로 호출. 스코어 식의 event_types 항은 실제 추출로 라이브가 되고(B4 취지 충족), 검색 경로는 무변경.
2. **orchestrator `run_verify` 호출은 2곳** (orchestrator.py:496·568) — v1의 "3곳" 정정 (권고 4). `_g2_supported` 호출부도 **1곳**(verify.py:340) — v1의 "2곳" 정정.
3. **플레이북 실측**: 제외 파일(clusters/holdout/holdout-report) 제외 JSON **24개**, `holdout_passed` 4개, 구조 필드 가진 gate **0개** (리뷰의 26개와 집계 범위 차이 — 결론 동일: 소비자만 추가하면 영구 무동작 → T9 생산자 태스크 + 마이그레이션 명시).
4. **judge.py CHAIN_EDGES 결속은 수집기 경로**: `judge_items`는 답변 파이프라인(run_qa) 밖의 수집 잡 — off-arm 구조 등치 계약(run_qa의 프롬프트·layer·final)에 저촉되지 않음. 카드 `edge` 정규화는 신규 판정분부터 적용.
5. **metric fact `period`는 범위형 가능**: `sector:dram_price_mom`의 period는 `"2026-06→2026-07"`. grounding의 날짜 대조는 `period.split("→")[-1]`을 `sector.period.parse_period`로 해석 — 파싱 불가·빈 값은 fail-closed(not grounded).
6. **구조 등치 계약의 정의 (v3 교정 — "바이트 동일" 표현 폐기, r2 권고)**: off-arm에서 **동일 고정 시계 하에** (a) 전 LLM 프롬프트(role별 instructions+prompt), (b) 방출 layer 스트림, (c) FinalAnswer dump가 3부 이전과 JSON 구조 등치(canonical 직렬화 비교 아님). 실제 프롬프트에는 모듈 로드 TODAY(plan.py:28)·호출 시 date.today()(queryplan.py:131)가 들어가므로 시계 고정 없인 등치가 정의되지 않는다(r2-1b — T1이 고정). 전부 수동 dict 조립이라 TypedFact/VerdictPacket/DraftAnswer의 기본값 신규 필드(모델 내부 직렬화에 새 키)는 이 계약 무저촉 — golden 하네스가 (a)(b)(c)를 대조.

## 스펙-코드 불일치 (실코드 대조 — v2 확정 해소)

1. **TypedFact schema_version**: TypedFact엔 자체 버전 없음, 패킷들이 전역 `SCHEMA_VERSION=1`(packets.py:18) 공유. **해소(B1):** 전역은 **무변경(=1)**. 신규 ChainPacket만 자체 `CHAIN_SCHEMA_VERSION=1` 스탬프. TypedFact 신규 필드 `metric`·`observation_id`는 기본값 추가(구 직렬화 하위호환 테스트). `period`는 이미 존재.
2. **edge 값 공간**: judge.py에 edge 열거 없음(자유 문자열, 기본 `"B->A"`; 축 집합 `_VALID_AXIS`만 존재, judge.py:25). **해소(B4):** 축 곱집합이 아니라 **명시 열거 `CHAIN_EDGES`** — judge.py `_INSTR`의 실제 인과 사슬(C0→C→B→[GPU/ASIC=A_prime]→A, 보조 A_prime/E/P/market→A)에서 도출한 8개 유향 edge. contracts/packets.py에 정의(단일 진실원), sector/judge.py가 import해 `_validate_row`에서 미등록 edge를 축 기반 결정적 폴백으로 정규화, ChainEdge validator는 멤버십 검사. 드리프트 가드: `nodes(CHAIN_EDGES) == judge._VALID_AXIS`.
3. **rule_plan의 event_types**: `build_rule_plan`(sector/queryplan.py:83)은 event_types 미기입. **해소(B4+v2 조정 1):** `extract_event_types` 키워드 규칙(실존 `EventType` Literal 위) 신설, thesis 스코어링 경로 opt-in — 스코어 항이 실추출로 라이브.
4. **"2부 주입 경로+3부 전체 무효"**: 2부는 답변 경로 무접촉 배송 — disable_p23 하나가 배경 판 주입과 3부 신규 경로 전체를 관장(`thesis_update_enabled`는 갱신 잡 전용 별개).
5. **EnvelopeMeta·VerdictPacket**: 스펙 명칭 그대로 실존(packets.py:49·377). ChainPacket.meta는 **필수 필드**로, 실제 생성 시점의 `EnvelopeMeta(round=round_, plan_ref=plan.plan_ref())` 기록 — ANSWERABILITY 보충검색이 첫 VERIFY 전에 round\_를 올릴 수 있으므로 round 0 고정 금지 (판정 3 수용).

## Global Constraints

- **effective_disable_p23 — run당 1회 결정, 전 경로 관통 (B2)**: `run_qa` 진입부에서 `effective_disable_p23 = bool((overrides or {}).get("disable_p23", settings.disable_p23))` — run override가 환경설정보다 우선(1부 계획 1385~1391행의 단일 명령 2-arm 계약: off-arm=`overrides["disable_p23"]=True`). import-time 싱글턴 직접 참조 금지 — 모든 P3 분기(thesis·chain·chain_verdicts·G2 metric identity·RISK 체인 입력·시나리오·구조 게이트)는 이 지역 변수만 본다. `settings.disable_p23: bool = False`(기본 ON)는 env `DISABLE_P23` 폴백.
- **memory_sector_active — 명시적 메모리 판정 게이트 (B3·r2-2)**: `profile.sector_rag_enabled`는 비메모리 산업·전략 질문에서도 True — 부적격. `plan_query` 성공(내부 `is_sector_question`, queryplan.py:46) **단독도 부적격** — `extract_entities` 1개면 True라 "엔비디아 CUDA 소프트웨어 매출"·"애플 아이폰 판매량"·"구글 광고 매출"·"삼성 스마트폰"도 통과(r2-2). 최종: `memory_sector_active = (outcome is not None) and is_memory_question(question, build_rule_plan(question))` — **입력은 원 질문 (r3-2)**: `question`은 triage가 돌려준 사용자 입력 정제본(orchestrator.py:185 — /deep 접두어 제거뿐, LLM 재작성 아님)이고 rule_plan도 `build_rule_plan(question)`으로 원 질문에서 결정적으로 재유도 — LLM 산출 `plan.standalone_question`·`outcome.rule_plan`(standalone 기반, orchestrator.py:327) 사용 금지(PLAN 오재작성으로 게이트가 열리는 경로 차단). `is_memory_question`은 T2의 결정적 함수(메모리 토픽 키워드 명시 목록 / `rule_plan.segments` 비공백 / 메모리 3사+**메모리 특이 문맥** — `"반도체"` 일반어 불인정, r3-2). thesis·chain·시나리오를 전부 그 뒤에 묶는다. 음성 6건+양성 테스트(T2)·비메모리 full-profile·엔티티-only 통합 테스트(T10) 포함.
- **off-arm 구조 등치 (B1·r2-1·r3-1)**: `effective_disable_p23=True`면 동일 고정 시계 하에서 프롬프트·layer 스트림·FinalAnswer가 3부 이전과 JSON 구조 등치 — T1의 golden 하네스(T1 커밋 SHA 고정 워크트리 캡처·고정 시계·임시 store·playbook 케이스)와의 등치 테스트가 전 태스크의 상시 회귀 게이트. **identity 비교(candidate 쪽)도 dirty 공유 작업트리가 아니라 현재 HEAD 커밋의 clean 워크트리에서 실행 (r3-1 — 절차는 T1)**. metric-tagged G2·시나리오·게이트 전부 포함해 신규 동작은 토글 안쪽에만.
- **stale thesis 주입 금지** — fresh + degraded(라벨 병기)만. 선택된 `revision_id`를 thesis layer에 기록.
- **AUDIT evidence_texts에 thesis 주입 절 불포함** — `_audit_evidence()` 헬퍼 추출로 시그니처 수준 보장.
- **숫자 불변식**: thesis 유래 숫자는 TypedFact 경로만. 배경 판 절엔 수치 미포함 — 렌더 시점 `thesis_guard.quantity_literal` 코드 검증, 위반 statement 드롭. revision_id·타임스탬프도 절 본문 미포함.
- **임의 ID로 grounded 채우기 불가**: ChainPacket 인용 ID는 (섹터 카드 ∪ curated NewsItem ∪ typed_facts) 실존 집합 대조 — 미실존 드롭, supporting·metric 인용이 다 비면 `observed`→`inference` 강등. VERIFY가 독립 재검증 + **실제 날짜 파서 fail-closed**(카드 `ts`·NewsItem `published_at`은 `date.fromisoformat`, metric fact `period`는 `parse_period` — 빈 값·불가능 날짜·cutoff 자체 미파싱·cutoff 초과 전부 not grounded, B6·r2-4). 인용 ID는 **비공백 + 전 소스에서 유일 해소**일 때만 실존 인정(r2-4 — `NewsItem.id` 기본값 `""` 차단).
- **LLM 유사 지표 대입 금지**: 구조 게이트 값은 코드가 store에서 조회·집계.
- **all-or-none 게이트**: 구조 필드가 일부만 있으면 그 gate의 구조 판정 전체 무시 + 로그(문자열 gate로만 동작).
- **답변 경로 기존 동작 무영향**: 신규 경로는 전부 never-raise — 단 실패는 **삼키지 않고 degraded 표식으로 가시화**(B5: `run_chain`은 `(packet|None, 강등사유)` 튜플 반환, 호출부가 기록).
- **pm2 재시작만**(`pm2 restart attn-engine`), 커밋 작은따옴표·**명시적 git add**(공유 체크아웃 — `git -C /home/ryze_yn/attn-viewer add <파일들>` 나열). 커밋 전 브랜치 확인(main).
- 신규 HTTP 라우트 없음 — openapi 무변경. `npm test`·`npm run check:openapi`는 회귀 게이트(T9·T10), **fallback·`|| true` 금지, exit code가 게이트**.
- 프론트(public/index.html) 미변경 — 신규 layer name은 `CHAT_LAYER_TITLE` 미등록으로 필터. workflow-review 현행화는 T11 컨트롤러.
- cwd `/home/ryze_yn/attn-viewer/engine`, 테스트 `.venv/bin/python -m pytest tests/... -q`.

## File Structure

- Create: `engine/tests/p23_harness.py`+`engine/tests/fixtures/p23_off_golden.json`(T1), `engine/stages/thesis_context.py`(T3·T4), `engine/stages/chain.py`(T5), `engine/tests/fixtures/playbook_structured_gate.json`(T8)
- Modify: `engine/contracts/packets.py`·`engine/contracts/__init__.py`·`engine/app/settings.py`·`engine/sector/judge.py`·`engine/sector/queryplan.py`(T2), `engine/stages/synthesize.py`(T4·T7), `engine/orchestrator.py`(T4~T8), `engine/providers.py`(T5), `engine/stages/verify.py`·`engine/sector/evidence.py`·`engine/stages/risk.py`(T6), `engine/stages/playbook.py`·`engine/sector/metrics_registry.py`(T8), `lib/playbooks.mjs`·`lib/playbooks.test.mjs`(T9), `engine/evals/chain_judge.py`·`engine/evals/metrics.py`·`engine/evals/run_eval.py`(T10)
- 테스트: `engine/tests/test_p23_off_identity.py`, `test_chain_contracts.py`, `test_thesis_select.py`, `test_thesis_inject.py`, `test_chain_stage.py`, `test_chain_verify_risk.py`, `test_scenario_contract.py`, `test_playbook_gates.py`, `test_chain_eval_wiring.py`, `test_p23_integration.py`

---

### Task 1: off-arm 구조 등치 하네스 + golden 캡처 (밀폐 — SHA 고정 워크트리·고정 시계·임시 store, 코드 변경 전 필수 선행)

**Files:**
- Create: `engine/tests/p23_harness.py`, `engine/tests/fixtures/p23_off_golden.json`, `engine/tests/test_p23_off_identity.py`

**Interfaces:**
- `FIXED_TODAY = "2026-07-10"` — bundle `as_of`와 동일. 등치 계약: "**동일 고정 시계 하에서** (a) 전 LLM 프롬프트 (b) layer 스트림 (c) FinalAnswer dump의 JSON 구조 등치" (r2 권고 — canonical 직렬화 비교 아님)
- `_hermetic(tmp_path)` contextmanager — pytest 의존 없음(캡처 `__main__`과 테스트가 공유), 전 패치 try/finally 원복:
  1. **시계 고정 (r2-1b)** — 코드에 이미 있는 monkeypatch 가능 seam(모듈 attr) 사용, 프로덕션 seam 신설 불필요: `stages.plan.TODAY = FIXED_TODAY`(plan.py:28 — 프롬프트 조립부 162·173행은 호출 시점에 모듈 attr을 읽어 패치 유효. `_PlanA` 필드 기본값(78·93행)은 import 시 고정이지만 canned plan 출력이 cutoff를 명시하고 eval 경로는 bundle as_of가 덮으므로 무영향) / `_FixedDate(date)` 서브클래스(`today()` == FIXED_TODAY)를 `sector.queryplan.date`(75·131행)·`stages.ra_external.date`(187·195행)에 대입 / `sector.retrieve._dt`(150행 `datetime.now` 폴백 — 최신성 점수)도 고정 래퍼로 대입
  2. **casemem 임시 store (r2-1c)**: orchestrator casemem 블록은 canned query 패치와 **별개로** `casemem.api._get_store()`를 직접 호출(orchestrator.py:381)하고, `_get_store`는 `_STORE is None`이면 라이브 경로 초기화+시드 기록(api.py:25~31). → `casemem.api._STORE = CaseStore(tmp_path / "cm")` **선주입**(비-None → 초기화·시드 분기 미진입), 종료 시 원복. `casemem.async_query.query_case_memory_async` canned 패치(고정 빈 매치)는 유지 — 리랭크 비결정 차단
  3. **playbook 격리+실매칭 (r2-1d)**: `stages.playbook.STORAGE_ROOT = tmp_path / "storage"`(모듈 attr — `load_playbooks`가 호출 시점 참조) + `users/golden-user/corpus/playbooks/hbm-cycle.json`에 유효 플레이북 기록: `status="holdout_passed"`, `conclusionType="방향 판단"`(canned triage `question_type="stock_judgment"`의 `_TYPE_MAP` 허용값), `matchKeys=["HBM"]`(비유비쿼터스 2점·mk_hits 1·단독이라 마진 통과 — "SK하이닉스"는 `_UBIQUITOUS_NAMES` 1점 강등이라 matchKey 부적격), **문자열 게이트만**(pre-P3 코드에 없는 구조 계약을 golden에 넣지 않는다)
  4. 고정 시드 SectorStore(카드 3장·`memory_price_usd_per_gb` 관측 2건, ts 고정) → `evals.bundle.capture_bundle(store, out, as_of=FIXED_TODAY, availability="unproven", ra_docs=[고정 1건], prices={"quotes": [...]}, macro={})`
  5. `providers.Role` monkeypatch — **role name 전수 canned, 실제 호출 역할 15종 (r3-1 교정 — "triage"·"plan"·"da"·"answerability"는 role name이 아님)**: `planner`·`plan_extract`(plan.py:170~171 — triage.py:101도 이 이름 재사용), `sector_query`(queryplan.py:152), `da_gpt`·`da_fable`(da.py:85~89), `extract`(answerability.py:126·ra_external.py:272·322·402), `web_knowledge`(ra_external.py:365), `news_summary`(news_summary.py:56), `calc_program`(calc.py:113), `verifier`·`verifier_cross`(verify.py:298~302·394~395·422~423), `risk`(risk.py:47), `synthesizer`(synthesize.py:234), `audit`(audit.py:240·273), `casemem_rerank`(orchestrator.py:389) — 전부 providers.py `_ROLES` 실존 키. 미등록 role name은 KeyError 즉시 실패로 누락 가시화(T10에서 `chain_synth` 추가). 모든 콜의 `(role_name, instructions, prompt)`를 순서대로 기록
- `run_pipeline(question: str, *, overrides_extra: dict | None = None, user_id: str = "", tmp_path) -> dict` — `run_qa(question, overrides={"eval_bundle": str(bundle), **(overrides_extra or {})}, user_id=user_id)` 수집 → `{"prompts": [...], "layers": [...], "final": {...}}` 반환. 정규화: `elapsed_s`·`cost`·`planner_ms` 키 제거(값 비결정)
- golden은 **케이스 2개** (r2-1d — v2는 `user_id=""`라 matched 경로가 전혀 실행되지 않던 결함): `base` = (질문 `"SK하이닉스 HBM 현물가 흐름 어때?"`, `user_id=""`) / `playbook` = (같은 질문, `user_id="golden-user"`) — playbook 케이스에선 plan 프롬프트에 `format_gates` 헤더·synthesize 프롬프트에 `format_connection`이 실려 golden에 고정 = **lib 산 matched playbook이 엔진 프롬프트에 미치는 영향의 off-arm 회귀 감시**(T8 문자열 게이트 하위 호환의 실측 근거)
- **양팔 밀폐 (r2-1a + r3-1)**: 공유 작업트리는 dirty(`settings.py`·`orchestrator.py`·`synthesize.py` 등 타 세션 변경 실측 — 예: orchestrator.py:418 price layer에 커밋 전 `sector_momentum` 키가 이미 추가돼 있어, 여기서 실행하면 P3 구현 전부터 clean-SHA golden과 달라진다) — **baseline·candidate 양쪽 다 clean 워크트리에서 실행**:
  - **baseline(캡처)**: **T1 커밋 SHA에 고정한 격리 워크트리**에서: `git -C /home/ryze_yn/attn-viewer worktree add /tmp/p3-golden-wt <T1커밋SHA>` → `cd /tmp/p3-golden-wt/engine && /home/ryze_yn/attn-viewer/engine/.venv/bin/python -m tests.p23_harness --capture`(venv는 본 체크아웃 것 재사용 — cwd가 워크트리 engine이라 import는 워크트리 코드) → fixture를 본 체크아웃에 복사 → `git worktree remove /tmp/p3-golden-wt`. 캡처 스크립트가 워크트리 `git rev-parse HEAD`를 `_meta.captured_at_sha`로, FIXED_TODAY를 `_meta.fixed_today`로 golden에 기록
  - **candidate(identity 비교, r3-1)**: identity 테스트 실행도 공유 작업트리가 아니라 **각 태스크 커밋 직후의 현재 HEAD 커밋으로 만든 별도 clean 워크트리**에서, 동일 고정 시계·동일 canned 역할로: `git -C /home/ryze_yn/attn-viewer worktree add /tmp/p3-cand-wt HEAD` → `cd /tmp/p3-cand-wt/engine && /home/ryze_yn/attn-viewer/engine/.venv/bin/python -m pytest tests/test_p23_off_identity.py -q`(golden fixture는 HEAD에 커밋돼 있어 워크트리에 포함) → `git -C /home/ryze_yn/attn-viewer worktree remove /tmp/p3-cand-wt`. 타 세션 dirty 파일 오염 차단 — **각 태스크의 "T1 identity green" 회귀와 T10 Step 5의 회귀 게이트 전부 이 절차로 실행**
- `test_p23_off_identity.py::test_off_arm_structural_identity_to_pre_p3_golden` — 케이스별 `run_pipeline(q, overrides_extra={"disable_p23": True}, user_id=...)` == `golden["cases"][case_id]`(`_meta` 제외 JSON 등치). **pre-P3 코드는 미지 override 키를 무시하므로 캡처 시점에도 green** — 이후 전 태스크 상시 회귀
- **on-arm 게이트 충돌 해소 (r2-1e)**: 전체 스위트 `DISABLE_P23=true` 게이트(T10 Step 5) 하에서 on-arm 테스트는 **명시적으로 `overrides_extra={"disable_p23": False}`** 전달 — run override가 env 설정보다 우선(B2 seam의 존재 증명 겸함). T10 통합 테스트가 이 형태로 작성된다

- [ ] **Step 1: 하네스+identity 테스트 작성 → 커밋** (테스트 전용 — 프로덕션 무변경) — `'test(chain): 3부 off-arm 구조 등치 하네스 — 고정 시계·casemem 임시 store·playbook 케이스 (3부 T1, r2-1)'`
- [ ] **Step 2: SHA 고정 워크트리 캡처** — 위 baseline 명령 그대로. golden `_meta.captured_at_sha` == T1 커밋 SHA 확인 → fixture 복사
- [ ] **Step 3: 재실행 결정성 확인** — 워크트리에서 캡처 2회 diff 0 (고정 시계라 날짜 경계 무관 — `_meta` 포함 완전 동일)
- [ ] **Step 4: Commit + 워크트리 제거** — `'test(chain): pre-P3 golden 캡처 — SHA 고정 워크트리·고정 시계 (3부 T1, r2-1)'` → 커밋 직후 **candidate 워크트리 절차(r3-1)로 identity test green 확인** (fixture가 HEAD에 실렸으므로 워크트리에서 실행 가능 — 공유 작업트리 실행 금지)

---

### Task 2: 계약 — ChainPacket·CHAIN_EDGES·PlaybookGate + TypedFact 확장 + disable_p23 + judge 결속 + event-type 추출

**Files:**
- Modify: `engine/contracts/packets.py`, `engine/contracts/__init__.py`, `engine/app/settings.py`, `engine/sector/judge.py`, `engine/sector/queryplan.py`
- Test: `engine/tests/test_chain_contracts.py`

**Interfaces (Produces — 신규 모델은 전부 `_Strict` 상속, packets.py 내):**
- `SCHEMA_VERSION = 1` **무변경** (B1). `CHAIN_SCHEMA_VERSION = 1` 신설 — ChainPacket 전용
- `CHAIN_EDGES = ("C0->C", "C->B", "B->A_prime", "B->A", "A_prime->A", "E->A", "P->A", "market->A")` — judge.py `_INSTR` 인과 사슬의 명시 열거(곱집합 금지, B4). 노드 집합 == `judge._VALID_AXIS` 드리프트 가드 테스트. contracts→sector 방향 import 없음(sector가 contracts를 import — evidence.py 선례)
- `sector/judge.py`: `from contracts.packets import CHAIN_EDGES` + `_DEFAULT_EDGE = {"A": "B->A", "A_prime": "A_prime->A", "B": "B->A", "C": "C->B", "C0": "C0->C", "E": "E->A", "P": "P->A", "market": "market->A"}`; `_validate_row`에 `if row.edge not in CHAIN_EDGES: row.edge = _DEFAULT_EDGE[row.axis]` (axis는 직전에 검증됨 — 방출 edge가 레지스트리 밖일 수 없음, B4 "judge와 ChainEdge가 실제로 함께 사용")
- `sector/queryplan.py`: `_EVENT_TYPE_TERMS: dict[str, tuple[str, ...]]` — 실존 `EventType` Literal(sector/contracts.py:9) 9종 전부에 한국어 키워드: `demand_signal=("수요","발주","주문")`, `supply_signal=("공급","증설","감산","수율")`, `price_signal=("가격","현물가","고정가","인상","인하")`, `earnings=("실적","영업이익","컨콜")`, `filing=("공시",)`, `policy=("관세","수출통제","제재","보조금","규제")`, `speaker=("발언","ceo")`, `product_policy=("신제품","출시","로드맵")`, `market_reaction=("급등","급락")`; `extract_event_types(question: str) -> list[str]`(매칭 event_type, 정의 순서, [:4]); `build_rule_plan(question, include_event_types: bool = False)` — True일 때만 `event_types=extract_event_types(question)` (v2 조정 1 — 검색 경로 무변경)
- `sector/queryplan.py` += **명시적 메모리 판정 게이트 (r2-2·r3-2 강화)**: `_MEMORY_TOPIC_TERMS = ("hbm", "고대역폭", "d램", "디램", "dram", "낸드", "nand", "메모리 반도체", "메모리 사이클", "메모리 가격", "메모리 업황")` — **`"웨이퍼"` 단독 제거 (r3-2: 파운드리·TSMC 질문도 잡는 비특이 토큰. `TOPIC_TERMS_BY_SECTOR`(검색 게이트, queryplan.py:28)는 무변경)**, `_MEMORY_MAKER_TERMS = ("삼성전자", "삼전", "하이닉스", "hynix", "마이크론", "micron")`, `_MEMORY_CONTEXT_TERMS = ("메모리", "d램", "디램", "dram", "낸드", "nand", "hbm")` — **`"반도체"` 일반어 제거 (r3-2: 메모리 특이 문맥만 인정)** + `is_memory_question(question: str, rule_plan: SectorQueryPlan) -> bool`(결정적·LLM 없음) — ① 메모리 토픽 키워드 포함 ② `rule_plan.segments` 비공백 ③ 메모리 3사 명칭 ∧ `_MEMORY_CONTEXT_TERMS` 중 1개 동시 존재이면 True. `is_sector_question`(queryplan.py:46)은 **검색 게이트로 무변경** — `extract_entities` 1개면 True라 thesis·chain 게이트로는 부적격(엔비디아 CUDA·애플 아이폰·구글 광고·삼성 스마트폰 전부 통과, r2-2)
- `TypedFact` += `metric: str = ""`(METRIC_REGISTRY 키), `observation_id: str = ""` (기존 생성부 무변경 — 기본값)
- `ThesisRelation(thesis_revision_id: str, relation: Literal["supports", "contradicts"])`
- `ChainEdge(edge_id: str, edge: str, kind: Literal["observed", "inference"], supporting_card_ids: list[str] = Field(default_factory=list), metric_fact_ids: list[str] = Field(default_factory=list), contradicting_card_ids: list[str] = Field(default_factory=list))` — `edge`는 `edge in CHAIN_EDGES` field_validator (멤버십 — 패턴 아님)
- `ChainPacket(schema_version: int = CHAIN_SCHEMA_VERSION, meta: EnvelopeMeta, event: str, mechanism: str, edges: list[ChainEdge] = Field(default_factory=list), thesis_relation: list[ThesisRelation] = Field(default_factory=list), verdict: str = "")` — **meta 필수(기본값 없음)**: 생성 시점 round·plan_ref 강제 (판정 3)
- `ChainEdgeVerdict(edge_id: str, grounded: bool, note: str = "")`
- `VerdictPacket` += `chain_verdicts: list[ChainEdgeVerdict] = Field(default_factory=list)`
- `PlaybookGateSelector(series: str | None = None, meta_filter: dict = Field(default_factory=dict))`
- `PlaybookGateCheck(order: int, check: str, metric_id: str, selector: PlaybookGateSelector = Field(default_factory=PlaybookGateSelector), aggregation: Literal["last", "mean_window", "yoy"], window_days: int = 0, comparator: Literal[">=", "<=", ">", "<", "=="], threshold: float, unit: str, max_age_days: int)` — `threshold` 유한성 validator(`math.isfinite`, 권고 6)
- `PlaybookGateOutcome(order: int, metric_id: str, value: float | None = None, verdict: Literal["pass", "fail", "unavailable"], evidence_observation_id: str = "", unavailable_reason: Literal["", "no_metric", "unit_mismatch", "stale_data"] = "")` — model_validator: `verdict=="unavailable" ⇔ unavailable_reason != "" ∧ value is None`, `verdict∈{pass,fail} ⇒ value is not None ∧ unavailable_reason == ""` (권고 6)
- `DraftAnswer` += `scenario_flags: list[str] = Field(default_factory=list)`
- `LAYER_NAMES` += `"thesis"`, `"chain"`
- `engine/app/settings.py` += `disable_p23: bool = False` (주석: 3부 답변 경로 주입 전체 off — 4부 2-arm 승계. run override가 우선, `thesis_update_enabled`와 별개)
- `contracts/__init__.py` export: CHAIN_EDGES, CHAIN_SCHEMA_VERSION, ChainEdge, ChainEdgeVerdict, ChainPacket, PlaybookGateCheck, PlaybookGateOutcome, PlaybookGateSelector, ThesisRelation (+`__all__`)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_contracts.py
import pytest
from pydantic import ValidationError

from app.settings import Settings
from contracts import (CHAIN_EDGES, CHAIN_SCHEMA_VERSION, LAYER_NAMES, SCHEMA_VERSION,
                       ChainEdge, ChainEdgeVerdict, ChainPacket, DraftAnswer,
                       EnvelopeMeta, PlanRef, PlaybookGateCheck, PlaybookGateOutcome,
                       TypedFact, VerdictPacket)


def test_global_schema_version_untouched_and_backcompat():
    assert SCHEMA_VERSION == 1                     # B1 — 전역 무변경
    assert CHAIN_SCHEMA_VERSION == 1
    old = VerdictPacket.model_validate({"schema_version": 1})   # 구 직렬화본
    assert old.chain_verdicts == []                             # 신규 필드 기본값


def test_typed_fact_metric_identity_fields():
    f = TypedFact(id="thesis:hbm-tightness:memory_price_usd_per_gb", value=0.1,
                  unit="USD/GB", metric="memory_price_usd_per_gb",
                  observation_id="a" * 16, period="2026-07")
    assert f.metric == "memory_price_usd_per_gb" and f.observation_id == "a" * 16
    assert TypedFact(id="x", value=1.0, unit="KRW").metric == ""  # 기존 생성부 무변경


def test_chain_edges_registry_nodes_match_judge_axes():
    from sector.judge import _VALID_AXIS
    nodes = {n for e in CHAIN_EDGES for n in e.split("->")}
    assert nodes == _VALID_AXIS                    # 드리프트 가드 (단일 진실원)
    assert "B->A" in CHAIN_EDGES and "A_prime->A" in CHAIN_EDGES and "C0->C" in CHAIN_EDGES
    assert "A->A" not in CHAIN_EDGES and "market->C" not in CHAIN_EDGES  # 곱집합 금지 (r1-B4)


def test_judge_emission_normalized_into_registry():
    from sector.judge import _DEFAULT_EDGE, _JudgeRow, _validate_row
    assert set(_DEFAULT_EDGE.values()) <= set(CHAIN_EDGES)
    row = _validate_row(_JudgeRow(idx=0, relevant=True, axis="A_prime",
                                  edge="A_prime → A"))          # 자유 문자열
    assert row.edge == "A_prime->A"                # 축 기반 결정적 폴백
    row2 = _validate_row(_JudgeRow(idx=0, relevant=True, axis="B", edge="B->A"))
    assert row2.edge == "B->A"                     # 실존 edge 보존


def test_extract_event_types_deterministic_and_opt_in():
    from sector.judge import _VALID_EVENT_TYPE
    from sector.queryplan import build_rule_plan, extract_event_types
    got = extract_event_types("SK하이닉스 HBM 증설로 공급 과잉 안 와?")
    assert "supply_signal" in got and set(got) <= _VALID_EVENT_TYPE
    assert extract_event_types("오늘 날씨 어때?") == []
    # 기본 off — 검색 경로(retrieve.py:126 event_type 스코어) 무변경 (v2 조정 1)
    assert build_rule_plan("HBM 증설 어때?").event_types == []
    rp = build_rule_plan("HBM 증설 어때?", include_event_types=True)
    assert "supply_signal" in rp.event_types       # thesis 스코어링 전용 opt-in


def test_is_memory_question_explicit_gate():
    from sector.queryplan import (build_rule_plan, is_memory_question,
                                  is_sector_question)

    def gate(q):
        return is_memory_question(q, build_rule_plan(q))

    # 음성 6건 — 전부 is_sector_question은 True (r2-2 경계 증명: 앞 4건은 엔티티,
    # 뒤 2건은 TSMC 엔티티+검색측 "웨이퍼" 토픽·삼성전자 엔티티). r3-2 추가 2건:
    # "웨이퍼" 단독·3사+"반도체" 일반어로는 게이트가 열리지 않는다
    negatives = ("엔비디아 CUDA 소프트웨어 매출 전망 어때?", "애플 아이폰 판매량 어때?",
                 "구글 광고 매출 성장 어때?", "삼성전자 갤럭시 스마트폰 신제품 어때?",
                 "TSMC 웨이퍼 가격 전망 어때?",
                 "삼성전자 파운드리 반도체 실적 어때?")
    for q in negatives:
        assert is_sector_question(q) and not gate(q)
    # 양성 — ① 토픽 키워드 ② segments ③ 3사+메모리 문맥
    assert gate("SK하이닉스 HBM 현물가 흐름 어때?")
    assert gate("낸드 업황 바닥 지났나?")
    assert gate("삼성전자 메모리 실적 어때?")
    assert not gate("")


def test_chain_edge_value_space_and_kind():
    ChainEdge(edge_id="e0", edge="B->A", kind="observed", supporting_card_ids=["c1"])
    ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference")
    with pytest.raises(ValidationError):
        ChainEdge(edge_id="e2", edge="A->A", kind="observed")   # 미등록 edge
    with pytest.raises(ValidationError):
        ChainEdge(edge_id="e3", edge="B->A", kind="guessed")    # kind Literal


def test_chain_packet_meta_records_real_round_and_plan_ref():
    meta = EnvelopeMeta(round=1, plan_ref=PlanRef(tier=3, knowledge_cutoff="2026-07-21"))
    cp = ChainPacket(meta=meta, event="HBM 증설 발표", mechanism="공급 확대 기대",
                     edges=[ChainEdge(edge_id="e0", edge="A_prime->A", kind="inference")],
                     thesis_relation=[{"thesis_revision_id":
                                       "hbm-tightness@2026-07-21T00:00:00",
                                       "relation": "supports"}])
    assert cp.schema_version == CHAIN_SCHEMA_VERSION
    assert cp.meta.round == 1 and cp.meta.plan_ref.tier == 3   # 실제 라운드 (판정 3)
    with pytest.raises(ValidationError):
        ChainPacket(event="x", mechanism="y")       # meta 필수 — 기본 빈 meta 금지
    with pytest.raises(ValidationError):
        ChainPacket(meta=meta, event="x", mechanism="y",
                    thesis_relation=[{"thesis_revision_id": "t@1", "relation": "maybe"}])
    v = VerdictPacket(chain_verdicts=[ChainEdgeVerdict(edge_id="e0", grounded=False,
                                                       note="근거 없음")])
    assert v.chain_verdicts[0].grounded is False


def test_playbook_gate_contracts_and_validators():
    chk = PlaybookGateCheck(order=1, check="D램 가격 수준",
                            metric_id="memory_price_usd_per_gb",
                            selector={"meta_filter": {"category": "DRAM"}},
                            aggregation="last", comparator=">=", threshold=0.05,
                            unit="USD/GB", max_age_days=45)
    assert chk.window_days == 0 and chk.selector.series is None
    with pytest.raises(ValidationError):
        PlaybookGateCheck(order=1, check="x", metric_id="m", aggregation="median",
                          comparator=">=", threshold=1.0, unit="u", max_age_days=1)
    with pytest.raises(ValidationError):            # threshold 유한성 (권고 6)
        PlaybookGateCheck(order=1, check="x", metric_id="m", aggregation="last",
                          comparator=">=", threshold=float("nan"), unit="u",
                          max_age_days=1)
    out = PlaybookGateOutcome(order=1, metric_id="memory_price_usd_per_gb",
                              verdict="unavailable", unavailable_reason="no_metric")
    assert out.value is None
    with pytest.raises(ValidationError):            # verdict/reason 정합 (권고 6)
        PlaybookGateOutcome(order=1, metric_id="m", verdict="unavailable")
    with pytest.raises(ValidationError):
        PlaybookGateOutcome(order=1, metric_id="m", verdict="pass", value=None)


def test_layer_names_settings_default_and_scenario_flags():
    assert "thesis" in LAYER_NAMES and "chain" in LAYER_NAMES
    # env 오염 무관 — 인스턴스가 아니라 모델 필드 기본값 검사 (권고 3:
    # `DISABLE_P23=true pytest`에서도 통과해야 함)
    assert Settings.model_fields["disable_p23"].default is False
    assert Settings(disable_p23=True).disable_p23 is True
    assert DraftAnswer(answer_markdown="x").scenario_flags == []
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/test_chain_contracts.py -v` → ImportError (CHAIN_EDGES 등 미존재)
- [ ] **Step 3: 구현** — 위 Interfaces 전부. judge/queryplan 변경 후 기존 `test_sector_judge.py`·섹터 검색 테스트 무변경 통과 확인(edge 정규화는 미등록 값만 건드림·event_types는 opt-in)
- [ ] **Step 4: 통과 + 회귀** — 신규 green + `.venv/bin/python -m pytest tests/ -q` 전체 green + **T1 identity 테스트 green**
- [ ] **Step 5: Commit** — `'feat(chain): 3부 typed 계약 — CHAIN_EDGES 레지스트리·ChainPacket(CHAIN_SCHEMA_VERSION)·PlaybookGate validator·event-type 추출·is_memory_question 게이트(메모리 특이 문맥만)·disable_p23 (3부 T2, r2-2·r3-2)'`

---

### Task 3: thesis 선택기 — 결정적 rule_plan 스코어링

**Files:**
- Create: `engine/stages/thesis_context.py`
- Test: `engine/tests/test_thesis_select.py`

**Interfaces:**
- `@dataclass ThesisPick(rev: ThesisRevision, freshness: str, score: int)`
- `score_thesis(rp: SectorQueryPlan, rev: ThesisRevision) -> int` — `len(set(rp.entities) & set(rev.selectors.entities)) * 2 + len(set(rp.metrics) & set(rev.selectors.metrics)) * 1 + len(set(rp.event_types) & set(rev.selectors.event_types)) * 1` (스펙 식 — event_types 항은 T2 `extract_event_types`로 **라이브**, B4)
- `select_from_revisions(rp, revs: list[ThesisRevision], store, now: datetime) -> list[ThesisPick]` — 0점 제외 → `sector.thesis_store.freshness(rev, store, now)` → stale 제외 → 정렬 `(-score, priority, rev.id)` → 상위 1~3개
- `select_theses(question: str, tstore: ThesisStore, store, now) -> list[ThesisPick]` — `build_rule_plan(question, include_event_types=True)` + `tstore.latest_all()` 위임 (라이브 경로). eval bundle 경로는 orchestrator가 `EvalBundle.theses()` → `ThesisRevision.model_validate` 후 select_from_revisions 직접 호출 (T4)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_select.py
import datetime as dt

from sector.contracts import MetricObservation
from sector.queryplan import SectorQueryPlan, build_rule_plan
from sector.store import SectorStore
from sector.thesis_contracts import RequiredInput, Selectors
from sector.thesis_store import ThesisStore
from stages.thesis_context import score_thesis, select_from_revisions, select_theses
from tests.test_thesis_contracts import make_rev

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)


def _store(tmp_path):
    s = SectorStore(tmp_path / "s")
    s.append_observations([MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    return s


def test_score_weights_deterministic_with_real_event_extraction():
    # 인위적 SectorQueryPlan이 아니라 실제 추출 경로 (r1-B4): make_rev의
    # selectors.event_types == ["supply_signal"] — "증설"이 supply_signal로 추출됨
    rp = build_rule_plan("SK하이닉스 HBM 증설에도 현물가 오를까?",
                         include_event_types=True)
    assert "SK_HYNIX" in rp.entities and "memory_price_usd_per_gb" in rp.metrics
    assert "supply_signal" in rp.event_types
    assert score_thesis(rp, make_rev()) == 4          # 1×2 + 1×1 + 1×1 — 3항 전부 라이브
    assert score_thesis(SectorQueryPlan(), make_rev()) == 0
    assert score_thesis(SectorQueryPlan(entities=["MICRON"]), make_rev()) == 0


def test_select_excludes_zero_and_stale_ranks_by_priority(tmp_path):
    store = _store(tmp_path)
    rp = SectorQueryPlan(entities=["SK_HYNIX"], metrics=["memory_price_usd_per_gb"])
    r_hit = make_rev()                                 # score 3, fresh
    r_hit2 = make_rev(id="memory-price-cycle", priority=2,
                      revision_id="memory-price-cycle@2026-07-21T00:00:00")  # 동점 — priority 뒤
    r_zero = make_rev(id="nand-decoupling",
                      revision_id="nand-decoupling@2026-07-21T00:00:00",
                      selectors=Selectors(entities=["KIOXIA"], metrics=[],
                                          segments=["nand"], event_types=[]))
    r_stale = make_rev(id="china-competition-risk",
                       revision_id="china-competition-risk@2026-07-21T00:00:00",
                       required_inputs=[RequiredInput(metric="kr_semi_export",
                                                      max_age_days=30)])  # 관측 없음 → stale
    picks = select_from_revisions(rp, [r_stale, r_hit2, r_zero, r_hit], store, NOW)
    assert [p.rev.id for p in picks] == ["hbm-tightness", "memory-price-cycle"]
    assert picks[0].freshness == "fresh" and picks[0].score == 3
    assert picks[0].rev.revision_id == "hbm-tightness@2026-07-21T00:00:00"


def test_select_caps_top3(tmp_path):
    store = _store(tmp_path)
    rp = SectorQueryPlan(entities=["SK_HYNIX"])
    revs = [make_rev(id=f"t{i}", revision_id=f"t{i}@2026-07-21T00:00:00", priority=i)
            for i in range(5)]
    assert len(select_from_revisions(rp, revs, store, NOW)) == 3


def test_select_theses_uses_rule_plan_not_llm(tmp_path):
    store = _store(tmp_path)
    ts = ThesisStore(tmp_path / "s")
    ts.append(make_rev())
    picks = select_theses("SK하이닉스 HBM 현물가 흐름 어때?", ts, store, NOW)
    assert [p.rev.id for p in picks] == ["hbm-tightness"]
    assert select_theses("오늘 날씨 어때?", ts, store, NOW) == []   # 0점 전원 제외
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (freshness는 `sector.thesis_store.freshness` 재사용 — 재구현 금지. T1 identity green 유지)
- [ ] **Step 5: Commit** — `'feat(chain): thesis 결정적 선택기 — rule_plan 스코어링(3항 라이브)·0점/stale 제외·top3 (3부 T3)'`

---

### Task 4: 배경 판 주입 — 렌더·TypedFact 승격·effective_disable_p23/memory_sector_active 배선·AUDIT 격리

**Files:**
- Modify: `engine/stages/thesis_context.py`, `engine/stages/synthesize.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_thesis_inject.py`

**Interfaces:**
- `render_thesis_section(picks: list[ThesisPick]) -> str` — 빈 picks → `""`. 형식:
  - 헤더 `[배경 판 — 섹터 현재 가설 (자동 합성·경향 참고)]` + 경계 문구: "아래는 축적 근거로 자동 유지되는 '배경 가설'이다. 사실 근거로 단정 인용하지 말고 해석의 배경으로만 써라. 이 절의 가설 관련 수치는 [결정적 수치] 절의 값만 인용하라."
  - 가설당: `- ({assessment}{", 입력 일부 노후" if degraded}) {claim}: {statement texts "; " 연결}` — revision_id·타임스탬프·key_metrics 값은 절에 미포함
  - 렌더 직전 코드 검증: `thesis_guard.quantity_literal(text)`에 잡히는 statement/claim 라인 드롭
- `thesis_typed_facts(picks) -> list[TypedFact]` — key_metrics → `TypedFact(id=f"thesis:{rev.id}:{km.metric}", value=km.value, unit=km.unit, period=km.ts, label=f"{rev.id} 관련 지표 {km.metric}", source=km.source, metric=km.metric, observation_id=km.observation_id)`. id 중복은 상위 pick first-wins
- `stages/synthesize.py`: `_render_context(..., thesis_section: str = "")`·`run_synthesize(..., thesis_section: str = "")` — 비면 기존 출력과 동일 문자열. 위치: `[메모리 섹터 근거]` 뒤·`[과거사례 대조]` 앞
- `orchestrator.py`:
  - **run_qa 진입부** (meter 설정 직후): `from app.settings import settings` 후 `effective_disable_p23 = bool((overrides or {}).get("disable_p23", settings.disable_p23))` — **B2: run당 1회 결정.** 이후 어떤 P3 분기도 `settings.disable_p23` 직접 참조 금지 (overrides는 line 191에서 `role_overrides`로 재대입되므로 반드시 재대입 전 원본에서 읽는다)
  - sector_rag 블록: `memory_sector_active = False` 초기화, `outcome = await plan_query(...)` 직후 `memory_sector_active = outcome is not None and is_memory_question(question, build_rule_plan(question))` — **B3+r2-2+r3-2: 원 질문 기반 결정적 판정.** `question`은 triage 반환 사용자 입력 정제본(orchestrator.py:185 — LLM 재작성 아님), rule_plan도 `build_rule_plan(question)`으로 원 질문에서 재유도 — LLM 산출 `plan.standalone_question`(PLAN 오재작성으로 게이트 개방 가능)·`outcome.rule_plan`(standalone_question 기반, orchestrator.py:327) 금지. `is_memory_question`은 T2의 결정적 함수 (`is_sector_question` 단독은 엔티티 1개로 True — 부적격)
  - `_audit_evidence(ra, sector_cycle_text, sector_metric_notes, sector_cards, case_matches) -> tuple[list[str], dict[str, str]]` — 기존 ⑧ AUDITOR evidence 조립 블록(orchestrator.py:604~630) 그대로 추출(동작 불변). thesis 파라미터 없음
  - casemem 블록 뒤(run_assemble 전):

```python
    thesis_picks, thesis_section = [], ""
    if not effective_disable_p23 and memory_sector_active:
        try:
            import datetime as _th_dt
            from sector.thesis_contracts import ThesisRevision as _ThRev
            from sector.thesis_store import ThesisStore as _ThStore
            from sector.queryplan import build_rule_plan as _th_rule
            from stages.thesis_context import (render_thesis_section,
                                               select_from_revisions, thesis_typed_facts)
            if eval_bundle:
                _th_store = eval_bundle.store()
                _th_revs = [_ThRev.model_validate(t) for t in eval_bundle.theses()]
                _th_now = _th_dt.datetime.fromisoformat(
                    eval_bundle.manifest["as_of"]).replace(tzinfo=_th_dt.timezone.utc)
            else:
                from sector.api import _get_store as _th_get
                _th_store = _th_get()
                _th_revs = _ThStore(_th_store.root).latest_all()
                _th_now = _th_dt.datetime.now(_th_dt.timezone.utc)
            thesis_picks = select_from_revisions(
                _th_rule(plan.standalone_question or question,
                         include_event_types=True), _th_revs, _th_store, _th_now)
            if thesis_picks:
                thesis_section = render_thesis_section(thesis_picks)
                sector_facts = list(sector_facts) + thesis_typed_facts(thesis_picks)
                yield _layer("thesis", {
                    "selected": [{"revision_id": p.rev.revision_id,
                                  "claim": p.rev.claim,          # eval judge 컨텍스트용 (r1-B9)
                                  "score": p.score, "freshness": p.freshness}
                                 for p in thesis_picks],
                    "typed_facts": [{"id": f.id, "label": f.label, "value": f.value,
                                     "unit": f.unit, "period": f.period}
                                    for f in thesis_typed_facts(thesis_picks)]})
        except Exception:  # noqa: BLE001 — never-raise, 무주입 폴백 (표식은 남김)
            degraded.append("thesis")
            thesis_picks, thesis_section = [], ""
```

  - run_synthesize 호출에 `thesis_section=thesis_section` 전달, ⑧ evidence 조립을 `_audit_evidence(...)` 호출로 치환
- eval bundle 모드: `EvalBundle.theses()`(bundle.py:167)가 as_of 경계 선택본 — 라이브 store 오염 없음

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_thesis_inject.py
import inspect

from contracts import DaPacket, PlanPacket, UnitAnswer
from sector.thesis_contracts import Evidence, Statement
from sector.thesis_guard import quantity_literal
from stages.synthesize import _render_context
from stages.thesis_context import ThesisPick, render_thesis_section, thesis_typed_facts
from tests.test_thesis_contracts import make_rev


def _pick(freshness="fresh", **kw):
    return ThesisPick(rev=make_rev(**kw), freshness=freshness, score=3)


def _st(text):
    sup = [Evidence(card_id=f"c{i}", canonical_url=f"https://p{i}.com/1",
                    publisher_id=f"p{i}.com", quote="q") for i in (1, 2)]
    return Statement(statement_id="s1", text=text, supporting=sup)


def test_render_boundary_label_and_no_numbers():
    sec = render_thesis_section([_pick()])
    assert "[배경 판" in sec and "사실 근거로 단정 인용하지" in sec
    assert "HBM 수요가 공급을 앞선다" in sec            # make_rev statement text
    assert quantity_literal(sec) == []                  # 수량 literal 0 (코드 검증)
    assert "0.1" not in sec and "revision_id" not in sec and "2026-07-21" not in sec
    assert render_thesis_section([]) == ""


def test_render_degraded_label_and_bad_statement_dropped():
    sec = render_thesis_section([
        _pick(freshness="degraded",
              statements=[_st("HBM 수요가 공급을 앞선다"), _st("가격 12% 급등")])])
    assert "입력 일부 노후" in sec
    assert "12%" not in sec                             # 주입 시점 이중 차단


def test_thesis_typed_facts_carry_metric_identity():
    facts = thesis_typed_facts([_pick()])
    assert facts[0].id == "thesis:hbm-tightness:memory_price_usd_per_gb"
    assert facts[0].metric == "memory_price_usd_per_gb"
    assert facts[0].observation_id == "x" * 16          # make_rev key_metrics 그대로
    assert facts[0].value == 0.1 and facts[0].period == "2026-07"


def _ctx(**kw):
    plan = PlanPacket(tier=2, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")
    da = DaPacket(unit_answers=[UnitAnswer(unit_id="q0", model="da_gpt",
                                           answer_text="a")])
    return _render_context(plan, da, None, None, None, None, [], None, **kw)


def test_synthesize_off_path_identical():
    base = _ctx()
    assert _ctx(thesis_section="") == base              # off 경로 동일 컨텍스트
    with_t = _ctx(thesis_section="[배경 판 — 섹터 현재 가설 (자동 합성·경향 참고)]\n- x")
    assert "[배경 판" in with_t and "[배경 판" not in base


def test_audit_evidence_helper_excludes_thesis_by_signature():
    from orchestrator import _audit_evidence
    params = inspect.signature(_audit_evidence).parameters
    assert "thesis_section" not in params and "thesis_picks" not in params
    from contracts import RaPacket
    texts, docs = _audit_evidence(RaPacket(), "", [], [], [])
    assert isinstance(texts, list) and isinstance(docs, dict)


def test_effective_toggle_resolved_from_run_overrides():
    # B2 — orchestrator 소스에 결정 시점이 하나뿐인지 (run override > settings)
    import inspect as _i
    import orchestrator
    src = _i.getsource(orchestrator.run_qa)
    assert 'get("disable_p23", settings.disable_p23)' in src
    assert src.count("effective_disable_p23 =") == 1    # run당 1회 결정
```

- [ ] **Step 2~3: 실패 확인 → 구현** (⑧ 블록 추출은 diff 최소 — 추출 전후 기존 audit 테스트 green)
- [ ] **Step 4: 통과 + 회귀** — 전체 pytest + **T1 identity green** (off-arm에선 thesis 블록 자체가 스킵 — 프롬프트·layer 불변)
- [ ] **Step 5: Commit** — `'feat(chain): thesis 배경 판 주입 — effective_disable_p23 1회 결정·memory_sector_active 원질문 게이트·수량 0 검증·AUDIT 격리 (3부 T4, r3-2)'`

---

### Task 5: ChainPacket 생성 (VERIFY 이전) — 코드 실존 검증·강등 사유 가시화

**Files:**
- Create: `engine/stages/chain.py`
- Modify: `engine/providers.py` (`"chain_synth": [("anthropic", settings.model_claude_sonnet, "low")]` — `"thesis_updater"`(providers.py:42) 아래), `engine/orchestrator.py`
- Test: `engine/tests/test_chain_stage.py`

**Interfaces:**
- structured output `_ChainOut{event, mechanism, verdict, edges: [{edge, kind, supporting_card_ids, metric_fact_ids, contradicting_card_ids}], thesis_relation: [{thesis_revision_id, relation}]}` (LLM 제안일 뿐 — 검증은 코드)
- `async run_chain(plan: PlanPacket, table: ClaimTable, sector_cards: list, ra: RaPacket, thesis_picks: list, *, round_: int = 0, role=None, overrides=None) -> tuple[ChainPacket | None, str]` — **반환 2번째 원소 = 강등 사유** (`""`=정상, `"llm_error"`, `"invalid_output"`, `"all_edges_dropped"` — B5: 예외 삼킴 뒤 무표식 금지):
  1. 입력 조립: claim 목록(id·text·source), 섹터 카드(id·title·interpreted_signal), typed_facts(id·label), thesis(revision_id·claim), **CHAIN_EDGES 열거**·kind 정의를 프롬프트에
  2. LLM 1콜 (`role or Role("chain_synth", overrides)`, effort low)
  3. 코드 검증 (LLM 불신): `edge not in CHAIN_EDGES` → 드롭 / 인용 ID 실존 대조(supporting·contradicting ⊆ {sector_cards id} ∪ {`ra.curated_items()` 전 유닛 NewsItem id}, metric_fact_ids ⊆ {table.typed_facts id}) — 미실존 드롭 / supporting과 metric이 모두 비면 `observed`→`inference` 강등 / thesis_relation revision_id ∉ {p.rev.revision_id} → 드롭 / `edge_id` 코드 순번 부여(`e0`, `e1`, …)
  4. `meta=EnvelopeMeta(round=round_, plan_ref=plan.plan_ref())` — **실제 생성 라운드** (판정 3)
  5. 내부 예외 → `(None, "llm_error")` 등 — never-raise + 사유
- `typed_fact_snapshot(table: ClaimTable) -> dict[str, dict]` (stages/chain.py, r3-4) — `{f.id: {"label", "value", "unit", "source", "metric", "period"} for f in table.typed_facts}` 조립 전에 **중복 fact ID 검사: `len({f.id for f in table.typed_facts}) != len(table.typed_facts)` → `ValueError`(중복 id 나열)**. dict 조립의 조용한 덮어쓰기 금지 — 중복 ID는 상류 fact 조립 버그이자 resolver 유일 해소의 전제 붕괴라 방출 시점에 오류로 드러낸다(never-raise 계약의 명시적 예외 — 측정 무결성, r3-4)
- orchestrator: ANSWERABILITY 뒤·첫 `run_verify`(orchestrator.py:496) 직전 —

```python
    chain = None
    if not effective_disable_p23 and memory_sector_active and table.claims:
        from stages.chain import run_chain, typed_fact_snapshot
        chain, chain_note = await run_chain(plan, table, sector_cards, ra,
                                            thesis_picks, round_=round_,
                                            overrides=overrides)
        if chain_note:
            degraded.append(f"chain:{chain_note}")   # B5 — 강등 표식 가시화
        if chain is not None:
            yield _layer("chain", {
                **chain.model_dump(mode="json"),
                # r2-7 — 체인 생성 시점 전체 TypedFact 스냅샷: ChainPacket이 인용
                # 가능한 집합(table.typed_facts)과 정확히 일치 — eval resolver의
                # 정확 역참조원 (price:*·ret:*·toss:*·sector:*·thesis:* 전 유래).
                # r3-4 — 헬퍼가 중복 fact ID를 방출 시점 ValueError로 fail-hard
                "typed_fact_snapshot": typed_fact_snapshot(table)},
                round_)                       # r2 권고 1 — layer round == meta.round
```

  (REFLECT 라운드 재생성 없음 — 판정 3 수용: 체인은 사건-기제 서술, 재조사는 근거 보강. 라운드 0이 아니라 **생성 시점 round\_**를 meta에 기록)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_stage.py
import asyncio

import pytest

from contracts import AtomicClaim, ClaimTable, PlanPacket, RaPacket, TypedFact
from sector.contracts import SectorCard
from stages.chain import run_chain, typed_fact_snapshot
from stages.thesis_context import ThesisPick
from tests.test_thesis_contracts import make_rev


def _plan():
    return PlanPacket(tier=3, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")


def _card(cid):
    return SectorCard(id=cid, ts="2026-07-20T00:00:00", axis="A", direction="pos",
                      magnitude=2, source_grade="A", title=f"t-{cid}",
                      interpreted_signal="sig", raw_quote="본문", url="https://a.com/1",
                      entities=["SK_HYNIX"])


def _table():
    return ClaimTable(
        claims=[AtomicClaim(id="cl-1", text="HBM 수요 강세", type="fact", source="da_gpt")],
        typed_facts=[TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB")])


class _Role:
    model = "fake-sonnet"
    def __init__(self, out): self.out, self.calls = out, 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        return response_format.model_validate(self.out)


_PROPOSAL = {
    "event": "HBM 증설 보도", "mechanism": "공급 확대 기대", "verdict": "혼조",
    "edges": [
        {"edge": "B->A", "kind": "observed",
         "supporting_card_ids": ["card-1", "ghost"],
         "metric_fact_ids": ["sector:dram_price", "no-such-fact"],
         "contradicting_card_ids": ["ghost2"]},
        {"edge": "C->B", "kind": "observed", "supporting_card_ids": ["ghost"],
         "metric_fact_ids": [], "contradicting_card_ids": []},
        {"edge": "A->A", "kind": "observed", "supporting_card_ids": ["card-1"],
         "metric_fact_ids": [], "contradicting_card_ids": []}],
    "thesis_relation": [
        {"thesis_revision_id": "hbm-tightness@2026-07-21T00:00:00",
         "relation": "supports"},
        {"thesis_revision_id": "ghost@2026-01-01T00:00:00", "relation": "contradicts"}]}


def test_code_validation_drops_demotes_assigns_ids_and_meta():
    picks = [ThesisPick(rev=make_rev(), freshness="fresh", score=3)]
    cp, note = asyncio.run(run_chain(_plan(), _table(), [_card("card-1")], RaPacket(),
                                     picks, round_=1, role=_Role(_PROPOSAL)))
    assert note == "" and cp is not None
    assert cp.meta.round == 1 and cp.meta.plan_ref.tier == 3   # 실제 생성 라운드 (판정 3)
    assert [e.edge_id for e in cp.edges] == ["e0", "e1"]
    e0, e1 = cp.edges
    assert e0.supporting_card_ids == ["card-1"]          # ghost 드롭
    assert e0.metric_fact_ids == ["sector:dram_price"]   # no-such-fact 드롭
    assert e0.contradicting_card_ids == []               # ghost2 드롭
    assert e0.kind == "observed"
    assert e1.kind == "inference"                        # 빈 supporting → 강등
    assert len(cp.edges) == 2                            # A->A 레지스트리 밖 → 드롭
    assert [t.thesis_revision_id for t in cp.thesis_relation] == \
        ["hbm-tightness@2026-07-21T00:00:00"]            # 미주입 revision 드롭


def test_never_raise_returns_reason_marker():
    class _Boom:
        model = "boom"
        async def run(self, *a, **k): raise RuntimeError("down")
    cp, note = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [],
                                     role=_Boom()))
    assert cp is None and note == "llm_error"            # B5 — 무음 None 금지


def test_all_edges_dropped_is_visible():
    bad = dict(_PROPOSAL, edges=[{"edge": "A->A", "kind": "observed",
                                  "supporting_card_ids": [], "metric_fact_ids": [],
                                  "contradicting_card_ids": []}])
    cp, note = asyncio.run(run_chain(_plan(), _table(), [], RaPacket(), [],
                                     role=_Role(bad)))
    assert cp is None and note == "all_edges_dropped"


def test_snapshot_duplicate_fact_id_fails_hard():
    # r3-4 — dict 조립의 조용한 덮어쓰기 금지: 중복 ID는 방출 시점 오류
    snap = typed_fact_snapshot(_table())
    assert set(snap) == {"sector:dram_price"}
    assert snap["sector:dram_price"]["unit"] == "USD/GB"
    dup = ClaimTable(typed_facts=[
        TypedFact(id="price:000660.KS", value=250000.0, unit="KRW"),
        TypedFact(id="price:000660.KS", value=1.0, unit="KRW")])
    with pytest.raises(ValueError):
        typed_fact_snapshot(dup)
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (T1 identity green — off-arm은 chain 블록 스킵)
- [ ] **Step 5: Commit** — `'feat(chain): ChainPacket 합성 스테이지 — CHAIN_EDGES 검증·미실존 드롭·observed 강등·meta 실라운드·강등 사유 가시화·TypedFact 스냅샷 layer(round 일치·중복 ID fail-hard) (3부 T5, r2-7·r3-4)'`

---

### Task 6: VERIFY chain_verdicts(소스별 날짜 fail-closed) + G2 canonical metric ID + RISK 실소비

**Files:**
- Modify: `engine/stages/verify.py`, `engine/sector/evidence.py`, `engine/stages/risk.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_chain_verify_risk.py`

**Interfaces:**
- `run_verify(..., overrides=None, metric_identity: bool = False, chain: ChainPacket | None = None, sector_cards: list | None = None)` — 기존 keyword 뒤 추가. `chain` 있으면 `chain_verdicts` 채움 (코드 판정 — 생성부 불신 독립 재검증):
  - edge별 `grounded=True` 조건 전부 충족: ① 인용 ID **비공백 + 유일 해소 (r2-4)** — supporting·contradicting은 sector_cards∪ra NewsItem에서, metric_fact_ids는 table.typed_facts에서, **전 소스 합집합 기준 정확히 1개 객체로 해소**될 때만 실존 인정. `NewsItem.id` 기본값은 `""`(packets.py:227)이고 `_dict_to_news`(ra_external.py:199)는 id를 생성하지 않는다 — 빈 인용은 "실존 ID" 집합 진입 불가, 소스 간 중복 id는 해소 불가 → 불인정 ② supporting 또는 metric **비어있지 않음** ③ 인용 전원 **as-of clean — 실제 파서 fail-closed (B6·r2-4)**: 정규식+문자열 비교가 아니라 `_parse_iso(s) = datetime.date.fromisoformat(s[:10])`(예외 → None) — 빈 값·`0000-00-00`·`2026-02-30` 같은 불가능 날짜 전부 거부. **cutoff 자체도 파싱**: `_parse_iso(plan.knowledge_cutoff)`가 None이면 전 edge grounded=False(note=`cutoff_unparsable`) — 잘못된 cutoff에서 fail-open 금지. 카드=`_parse_iso(c.ts)`, NewsItem=`_parse_iso(n.published_at)`(`ts` 아님), metric fact=`f.period.split("→")[-1]`을 `sector.period.parse_period`(v2 조정 5) — 각 None → fail, 파싱된 `date`끼리 `≤ cutoff` 비교. 미충족 시 grounded=False + note 사유
  - grounded 정의: kind와 독립(판정 3 수용) — inference도 실존·as-of-clean 인용이 있으면 grounded 가능
- **G2 canonical metric ID 관통 (B7 — keyword 교량 기각)**:
  - `_numeric_anchors(...) -> list[tuple[float, str, str]]` — `(value, unit, metric_id)`. typed_facts는 `f.metric` 그대로(섹터·thesis 유래는 생성 시점에 ID 보유 — NL 매핑 불필요), calc/price/macro 유래는 `""`
  - `_claim_metric_id(norm_metric: str) -> str` — claim 자유 문장 → 레지스트리 ID: ① 정확 키 일치 ② 정확 label 일치(소문자) ③ **유일 최장 alias**(`METRIC_REGISTRY[*]["keywords"]` 중 claim 문자열에 포함되는 최장 alias가 정확히 한 metric 소유일 때만). 0개 또는 복수 매칭 → `""` (fail-closed)
  - `_g2_supported(value, unit, anchors, claim_metric_id: str = "") -> bool` — **엄격 대칭 (r2-5)**: `claim_metric_id != ""`(canonical 태그 claim)이면 **같은 non-empty metric_id를 가진 anchor만** 대조 자격 — untagged anchor 사용 전면 금지(불일치 tagged anchor에서 거부돼도 동일값·동단위 untagged 가격/수익률 anchor로 재통과하는 우회 차단). `claim_metric_id == ""`이면 untagged anchor로 기존 판정 그대로·태그 anchor는 부적격 — **ID 없는 claim의 기존 동작 유지는 우회가 아니라 스코프 밖**(r2-5 명시: 가격·토스 TypedFact 생산자는 metric 미태그이고 그 값 대조는 기존 G2 경로 그대로). (교차 지표 동수치 앵커링 차단: `memory_price_usd_per_gb`의 keywords `"가격"`이 `"토큰 가격"` claim과 오매칭되던 r1-B7 사례가 최장 alias 규칙으로 `token_price`에 귀속)
  - 호출부(verify.py:340, 1곳): `metric_identity`가 True일 때만 `claim_metric_id=_claim_metric_id(c.norm.metric)` 전달, False면 `""` 고정 — **G2 변경도 토글 안쪽** (B1)
- `sector/evidence.py sector_typed_facts`: 생성 TypedFact 2건에 `metric="memory_price_usd_per_gb"`, `observation_id=observation_id(metric, last.ts, last.meta)`(`sector.thesis_contracts.observation_id`) 기입 — 데이터 태그일 뿐 off-arm 판정 무영향(위 `metric_identity` 게이트)
- `run_risk(..., force: bool = False, chain: ChainPacket | None = None, verdict: VerdictPacket | None = None)` — **verdict 있으면(on-arm) 입력 claim 계약 자체를 교체 (r2-3 — v2의 "verified 원문 절 추가" 방식 폐기, 추가 아님)**:
  - `verified_ids = {v.claim_id for v in verdict.verdicts if v.final == "verified"}`
  - `[수집된 claim 목록]`(risk.py:51)을 **verified claim만**으로 재구성 — unverified/rejected claim 텍스트는 프롬프트 어디에도 없음(bear case 구동 불가, 원문 각 160자·최대 40건 기존 상한 유지)
  - `valid_ids`(risk.py:58)도 verified ID 집합으로 제한 — 미검증 ID supporting은 strip → 그 bear는 `label="scenario"` 강등(`grounded` 라벨 사칭 불가)
  - chain 있으면 `[인과 체인 판정]` 절 — edge별 `- {edge_id} {edge} ({kind}, {'근거확인' if grounded else '미확인'})` **만** (verdict.chain_verdicts 대조). **체인 자유문 `event`·`mechanism`은 RISK 프롬프트에 렌더하지 않는다 (r3-3)**: 체인은 VERIFY 이전에 전체 claim(rejected 포함)을 입력받아 생성되므로 그 자유문에 rejected claim 텍스트가 복제될 수 있음 — RISK의 "미검증 텍스트가 프롬프트 어디에도 없음" 계약을 지키려면 RISK는 **verified claim 텍스트 + chain_verdicts가 참조하는 구조 필드(edge_id·`edge`(CHAIN_EDGES 열거값)·kind Literal·grounded)만** 받는다. ChainEdge에 claim provenance는 추가하지 않음(스코프 최소화 — VERIFY 이전 생성이라 verified 필터 자체가 불가). **SYNTHESIZE의 event/mechanism 렌더(T7)는 유지** — 시나리오 계약에 필요하고, SYNTHESIZE는 어차피 전체 근거·claim을 보는 스테이지: "미검증 텍스트 부재" 계약은 **RISK 한정**
  - verdict None(off-arm·기존 호출) → 기존 전 claim 목록·기존 valid_ids·기존 프롬프트 그대로 (등치 게이트)
- orchestrator: `run_verify` **2곳**(orchestrator.py:496·568)에 `metric_identity=not effective_disable_p23, chain=chain, sector_cards=sector_cards` 추가, `run_risk`에 `chain=chain, verdict=(None if effective_disable_p23 else verdict)` 추가 — off-arm은 `verdict=None`으로 기존 claim 계약 그대로(등치 게이트), on-arm은 chain 강등(None)이어도 verified-only 입력 유지(r2-3: 교체 조건은 toggle이지 chain 유무가 아님). verify layer data에 `"chain_verdicts": [...]` 포함(chain 없으면 키 생략 — off-path 동일)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_verify_risk.py
import asyncio

from contracts import (AtomicClaim, ChainEdge, ChainPacket, ClaimTable, ClaimVerdict,
                       EnvelopeMeta, NewsItem, PlanPacket, RaPacket, TypedFact,
                       VerdictPacket)
from stages.risk import run_risk
from stages.verify import _claim_metric_id, _g2_supported, run_verify
from tests.test_chain_stage import _card, _plan

_META = EnvelopeMeta()


def _table():
    return ClaimTable(
        claims=[AtomicClaim(id="cl-1", text="HBM 수요가 견조하다", type="context",
                            source="da_gpt")],
        typed_facts=[
            TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB",
                      period="2026-07", metric="memory_price_usd_per_gb"),
            TypedFact(id="sector:dram_price_mom", value=11.1, unit="percent",
                      period="2026-06→2026-07", metric="memory_price_usd_per_gb"),
            TypedFact(id="bad-period", value=1.0, unit="USD/GB", period="")])


def _chain():
    # event·mechanism은 식별 가능한 자유문 — RISK 프롬프트 부재 assertion용 (r3-3)
    return ChainPacket(meta=_META, event="증설 루머 이벤트 서술",
                       mechanism="공급 확대 기제 서술", edges=[
        ChainEdge(edge_id="e0", edge="B->A", kind="observed",
                  supporting_card_ids=["card-1"]),
        ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference"),
        ChainEdge(edge_id="e2", edge="C->B", kind="observed",
                  supporting_card_ids=["card-future"]),
        ChainEdge(edge_id="e3", edge="B->A", kind="observed",
                  metric_fact_ids=["no-such-fact"]),
        ChainEdge(edge_id="e4", edge="B->A", kind="observed",
                  supporting_card_ids=["news-1"]),
        ChainEdge(edge_id="e5", edge="B->A", kind="inference",
                  metric_fact_ids=["sector:dram_price_mom"]),
        ChainEdge(edge_id="e6", edge="B->A", kind="observed",
                  metric_fact_ids=["bad-period"]),
        ChainEdge(edge_id="e7", edge="C->B", kind="observed",
                  supporting_card_ids=["card-impossible"]),
        ChainEdge(edge_id="e8", edge="B->A", kind="observed",
                  supporting_card_ids=[""])])


def _ra_with_news(published_at):
    return RaPacket(x_search={"q0": [
        NewsItem(id="news-1", title="t", published_at=published_at),
        NewsItem(title="무ID 항목", published_at="2026-07-19T00:00:00")]})  # id="" 기본값


def test_chain_verdicts_source_typed_dates_fail_closed():
    cards = [_card("card-1")]
    future = _card("card-future"); future.ts = "2026-07-25T00:00:00"  # cutoff 이후
    impossible = _card("card-impossible")
    impossible.ts = "2026-02-30T00:00:00"       # 불가능 날짜 — 정규식은 통과했었음 (r2-4)
    verdict = asyncio.run(run_verify(
        _plan(), _table(), _ra_with_news(""), [],
        chain=_chain(), sector_cards=cards + [future, impossible]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e0"].grounded is True
    assert by_id["e1"].grounded is False        # 인용 전무
    assert by_id["e2"].grounded is False and "as_of" in by_id["e2"].note  # 미래 카드
    assert by_id["e3"].grounded is False        # 미실존 fact
    assert by_id["e4"].grounded is False        # NewsItem published_at 빈 값 → fail-closed
    assert by_id["e5"].grounded is True         # 범위형 period "→" 해석 (v2 조정 5)
    assert by_id["e6"].grounded is False        # period 빈 값 → fail-closed
    assert by_id["e7"].grounded is False        # 2026-02-30 — fromisoformat 거부 (r2-4)
    assert by_id["e8"].grounded is False        # 빈 인용 ID — id="" NewsItem 실존해도 불인정


def test_cutoff_unparsable_fails_closed():
    plan = _plan(); plan.knowledge_cutoff = "26-07-21"     # 미파싱 cutoff (r2-4)
    verdict = asyncio.run(run_verify(
        plan, _table(), _ra_with_news("2026-07-19T09:00:00"), [],
        chain=_chain(), sector_cards=[_card("card-1")]))
    assert verdict.chain_verdicts and all(not v.grounded
                                          for v in verdict.chain_verdicts)


def test_duplicate_id_across_sources_not_uniquely_resolved():
    # "card-1"이 카드와 NewsItem 양쪽에 실존 → 유일 해소 실패 → 불인정 (r2-4)
    ra = RaPacket(x_search={"q0": [NewsItem(id="card-1", title="충돌",
                                            published_at="2026-07-19T00:00:00")]})
    verdict = asyncio.run(run_verify(_plan(), _table(), ra, [],
                                     chain=_chain(), sector_cards=[_card("card-1")]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e0"].grounded is False


def test_news_published_at_clean_passes():
    verdict = asyncio.run(run_verify(
        _plan(), _table(), _ra_with_news("2026-07-19T09:00:00"), [],
        chain=_chain(), sector_cards=[_card("card-1")]))
    by_id = {v.edge_id: v for v in verdict.chain_verdicts}
    assert by_id["e4"].grounded is True         # published_at 실존·cutoff 이내


def test_chain_none_keeps_packet_shape():
    verdict = asyncio.run(run_verify(_plan(), _table(), RaPacket(), []))
    assert verdict.chain_verdicts == []          # off-path 무영향


def test_claim_metric_id_exact_unique_longest_alias():
    assert _claim_metric_id("memory_price_usd_per_gb") == "memory_price_usd_per_gb"
    assert _claim_metric_id("D램 현물가") == "memory_price_usd_per_gb"  # 유일 alias "현물가"
    # "토큰 가격"은 token_price alias(최장) — memory의 "가격"보다 김 → 교차 오귀속 차단 (r1-B7)
    assert _claim_metric_id("토큰 가격") == "token_price"
    assert _claim_metric_id("영업이익률") == ""    # 무매칭 → fail-closed
    assert _claim_metric_id("") == ""


def test_g2_metric_identity_strict_no_untagged_bypass():
    tagged = [(5.0, "percent", "memory_price_usd_per_gb")]
    assert _g2_supported(5.0, "percent", tagged,
                         claim_metric_id="memory_price_usd_per_gb")
    assert not _g2_supported(5.0, "percent", tagged, claim_metric_id="token_price")
    # r2-5 회귀: 불일치 tagged anchor + 동일값·동단위 untagged anchor 조합 — 우회 불가
    mixed = [(5.0, "percent", "token_price"), (5.0, "percent", "")]
    assert not _g2_supported(5.0, "percent", mixed,
                             claim_metric_id="memory_price_usd_per_gb")
    assert not _g2_supported(5.0, "percent", tagged, claim_metric_id="")  # 태그 anchor 부적격
    untagged = [(5.0, "percent", "")]
    assert _g2_supported(5.0, "percent", untagged, claim_metric_id="")    # 스코프 밖 — 기존 동작


def test_sector_typed_facts_now_carry_metric(tmp_path):
    from sector.contracts import MetricObservation
    from sector.evidence import sector_typed_facts
    from sector.store import SectorStore
    from sector.thesis_contracts import observation_id
    s = SectorStore(tmp_path / "s")
    meta = {"category": "DRAM", "item": "ddr5_16gb"}
    s.append_observations([
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-06", value=0.09,
                          unit="USD/GB", meta=meta),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    facts = sector_typed_facts(s)
    price = next(f for f in facts if f.id == "sector:dram_price")
    assert price.metric == "memory_price_usd_per_gb"
    assert price.observation_id == observation_id("memory_price_usd_per_gb",
                                                  "2026-07", meta)


def test_risk_on_arm_verified_only_input_and_ids(monkeypatch):
    captured = {}
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, prompt, instr, response_format=None, **kw):
            captured["prompt"] = prompt
            return response_format.model_validate({"bear_cases": [
                {"text": "b", "supporting_claim_ids": ["cl-bad"]}], "wrong_if": ""})
    monkeypatch.setattr("stages.risk.Role", _FakeRole)
    table = ClaimTable(claims=[
        AtomicClaim(id="cl-1", text="HBM 수요가 견조하다", type="context",
                    source="da_gpt"),
        AtomicClaim(id="cl-bad", text="점유율 90% 확보 루머", type="fact",
                    source="da_gpt")])
    verdict = VerdictPacket(verdicts=[
        ClaimVerdict(claim_id="cl-1", final="verified"),
        ClaimVerdict(claim_id="cl-bad", final="unverified")])
    risk = asyncio.run(run_risk(_plan(), table, chain=_chain(), verdict=verdict))
    assert "HBM 수요가 견조하다" in captured["prompt"]     # verified 원문 (r1-B5)
    assert "점유율 90% 확보 루머" not in captured["prompt"]  # r2-3 — 미검증 텍스트 전면 부재
    assert "[인과 체인 판정]" in captured["prompt"] and "e0" in captured["prompt"]
    # r3-3 — 체인 자유문(event·mechanism)은 RISK 프롬프트에 재주입되지 않는다
    assert "증설 루머 이벤트 서술" not in captured["prompt"]
    assert "공급 확대 기제 서술" not in captured["prompt"]
    assert risk.bear_cases[0].label == "scenario"          # 미검증 ID supporting 거부
    assert risk.bear_cases[0].supporting_claim_ids == []   # valid_ids ⊆ verified (r2-3)
    captured.clear()
    asyncio.run(run_risk(_plan(), table))                  # off-path — 기존 계약 그대로
    assert "점유율 90% 확보 루머" in captured["prompt"]     # 전 claim 목록 유지 (등치)
    assert "[인과 체인 판정]" not in captured["prompt"]
```

  (주의: `_table()`의 claim은 `type="context"`·`source="da_gpt"`·secondary 아님 → G1 후보 0 = LLM 무호출 — verify 오프라인 관례. RISK 테스트는 run_verify 경유 대신 VerdictPacket을 직접 조립 — verified/unverified 경계를 결정적으로 고정)

- [ ] **Step 2~4: 실패→구현→통과+회귀** — 기존 G2 테스트 전량 green(미태그 anchor·`metric_identity=False` 기본값 무변경 확인) + **T1 identity green** (off-arm: metric_identity=False·chain=None → 기존 판정·프롬프트 동일)
- [ ] **Step 5: Commit** — `'feat(chain): VERIFY chain_verdicts 실제 날짜 파서 fail-closed·인용 ID 유일 해소·G2 metric identity 엄격·RISK verified-only 입력 계약+체인 자유문 미렌더 (3부 T6, r2-3·4·5, r3-3)'`

---

### Task 7: SYNTHESIZE 시나리오 계약 — grounded edge 요구·코드 후검증·1회 재합성

**Files:**
- Modify: `engine/stages/synthesize.py`, `engine/orchestrator.py`
- Test: `engine/tests/test_scenario_contract.py`

**Interfaces:**
- `_SCENARIO_INSTR`(상수) — `_INSTR`에 조건부 append: "답변 말미에 `## 긍정 시나리오`와 `## 부정 시나리오` 절을 각각 두라. 각 절은 4줄 필수: `- 체인:`([인과 체인] 절의 edge_id 인용 — 근거확인된 edge 포함), `- 지표:`([결정적 수치] 절 항목 인용, 없으면 정확히 '지표 없음'), `- 유효 조건:`, `- 기각 조건:`. 숫자는 [결정적 수치] 절의 값 외에 쓰지 마라."
- `_render_context(..., chain: ChainPacket | None = None, chain_verdicts: list | None = None)` — chain 있으면 `[인과 체인]` 절 렌더 (B5 — **event/mechanism/verdict/thesis_relation/contradicting 포함, 길이 상한**): 헤더 줄 `사건: {event[:200]} / 기제: {mechanism[:300]} / 판정: {verdict[:200]}`, edge별 `- {edge_id} {edge} ({kind}/{'근거확인' if grounded else '미확인'}): 인용 {supporting_card_ids + metric_fact_ids}{' / 반증 카드 ' + contradicting_card_ids if any}`, thesis_relation별 `- (테제) {thesis_revision_id} {relation}`
- `validate_scenarios(answer_md: str, chain: ChainPacket, typed_facts: list[TypedFact], chain_verdicts: list[ChainEdgeVerdict]) -> list[str]` — 코드 후검증 (빈 리스트 = 통과, B6·판정 2 강화판):
  - **정확한 H2 절 경계**: `## 긍정 시나리오`·`## 부정 시나리오` 각 절 = 해당 헤더부터 다음 `## ` 또는 EOF까지 — 마커 검사는 절 내부 한정
  - 각 절에 `- 체인:`·`- 지표:`·`- 유효 조건:`·`- 기각 조건:` 라인 존재 + **콜론 뒤 payload 비어있지 않음**
  - `- 체인:` 라인의 `\be\d+\b` **정확 토큰**이 chain 실존 edge_id ⊆ ∧ ≥1, 그리고 인용 edge 중 **≥1이 chain_verdicts에서 grounded=True** (ungrounded-only 체인 불인정)
  - typed_facts 비어있지 않으면 `- 지표:`가 fact의 label 또는 id를 ≥1 포함, 비어있으면 payload가 정확히 `지표 없음`
- `run_synthesize(..., chain=None, chain_verdicts=None, scenario_required: bool = False)` — scenario_required ∧ chain 존재: 1차 합성 → validate → 미충족 시 1회 재합성(컨텍스트에 `[재합성 — 시나리오 계약 미충족]\n` + 사유) → 재실패 시 `DraftAnswer.scenario_flags = issues` (답변 유지)
- orchestrator: `run_synthesize(..., thesis_section=thesis_section, chain=chain, chain_verdicts=verdict.chain_verdicts, scenario_required=(plan.tier >= 3 and chain is not None and risk.applicable))` — **`plan.tier >= 3` 명시** (B6: routing.py:17 `risk_forced`는 tier2에서도 applicable 가능 — force_on 프로필·requires_countercase). scenario_flags 발생 시 `degraded.append("scenario_contract")` — FinalAnswer.degraded로 관찰(eval이 잡음)

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_scenario_contract.py
import asyncio

from contracts import (ChainEdge, ChainEdgeVerdict, ChainPacket, ClaimTable, DaPacket,
                       EnvelopeMeta, PlanPacket, TypedFact, UnitAnswer)
from stages.synthesize import run_synthesize, validate_scenarios

_CHAIN = ChainPacket(meta=EnvelopeMeta(), event="HBM 증설 보도",
                     mechanism="공급 확대 기대", edges=[
    ChainEdge(edge_id="e0", edge="B->A", kind="observed",
              supporting_card_ids=["card-1"]),
    ChainEdge(edge_id="e1", edge="A_prime->A", kind="inference")])
_VERDICTS = [ChainEdgeVerdict(edge_id="e0", grounded=True),
             ChainEdgeVerdict(edge_id="e1", grounded=False)]
_FACTS = [TypedFact(id="sector:dram_price", value=0.1, unit="USD/GB",
                    label="D램 현물가 (ddr5_16gb)")]

# 권고 2 반영: 근거 없는 수량("2건 이상") 제거 — 숫자 불변식과 충돌 금지
_GOOD = """결론.

## 긍정 시나리오
- 체인: e0 (B->A) 경로 유지
- 지표: D램 현물가 (ddr5_16gb) 상승 지속
- 유효 조건: 하이퍼스케일러 발주 유지 보도 확인
- 기각 조건: 발주 축소 보도

## 부정 시나리오
- 체인: e0 역전 — 발주 둔화
- 지표: D램 현물가 (ddr5_16gb) 하락 전환
- 유효 조건: 재고 경고 보도 누적
- 기각 조건: 가격 반등
"""


def test_validate_good_and_missing_section():
    assert validate_scenarios(_GOOD, _CHAIN, _FACTS, _VERDICTS) == []
    bad = _GOOD.split("## 부정 시나리오")[0]
    assert any("부정 시나리오" in i
               for i in validate_scenarios(bad, _CHAIN, _FACTS, _VERDICTS))


def test_validate_rejects_fake_edge_ungrounded_and_empty_payload():
    fake = _GOOD.replace("체인: e0", "체인: e9")
    assert any("체인" in i for i in validate_scenarios(fake, _CHAIN, _FACTS, _VERDICTS))
    ungrounded = _GOOD.replace("체인: e0 (B->A) 경로 유지", "체인: e1 경유") \
                      .replace("체인: e0 역전 — 발주 둔화", "체인: e1 역전")
    # grounded=True edge 0개 인용 → 불인정 (r1-B6)
    assert any("체인" in i
               for i in validate_scenarios(ungrounded, _CHAIN, _FACTS, _VERDICTS))
    empty = _GOOD.replace("- 유효 조건: 하이퍼스케일러 발주 유지 보도 확인", "- 유효 조건:")
    assert any("유효 조건" in i
               for i in validate_scenarios(empty, _CHAIN, _FACTS, _VERDICTS))


def test_validate_metric_contract():
    no_metric = _GOOD.replace("D램 현물가 (ddr5_16gb)", "임의 지표")
    assert any("지표" in i
               for i in validate_scenarios(no_metric, _CHAIN, _FACTS, _VERDICTS))
    # facts 없음 → '지표 없음'만 허용 (권고 2 — 계약 정합 fixture)
    ok = _GOOD.replace("- 지표: D램 현물가 (ddr5_16gb) 상승 지속", "- 지표: 지표 없음") \
              .replace("- 지표: D램 현물가 (ddr5_16gb) 하락 전환", "- 지표: 지표 없음")
    assert validate_scenarios(ok, _CHAIN, [], _VERDICTS) == []
    assert any("지표" in i for i in validate_scenarios(_GOOD, _CHAIN, [], _VERDICTS))


def _plan_da():
    plan = PlanPacket(tier=3, original_question="q", standalone_question="q",
                      knowledge_cutoff="2026-07-21")
    da = DaPacket(unit_answers=[UnitAnswer(unit_id="q0", model="da_gpt",
                                           answer_text="a")])
    return plan, da


def test_resynthesis_once_then_flag(monkeypatch):
    answers = ["시나리오 절 없는 답", "여전히 없는 답"]
    prompts = []
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, ctx, instr, **kw):
            prompts.append(ctx)
            return answers[len(prompts) - 1]
    monkeypatch.setattr("stages.synthesize.Role", _FakeRole)
    plan, da = _plan_da()
    draft = asyncio.run(run_synthesize(plan, da, chain=_CHAIN,
                                       chain_verdicts=_VERDICTS,
                                       scenario_required=True))
    assert len(prompts) == 2                             # 정확 1회 재합성
    assert "시나리오 계약 미충족" in prompts[1]
    assert draft.scenario_flags                          # 재실패 플래그
    assert draft.answer_markdown == "여전히 없는 답"


def test_success_and_off_path_single_call(monkeypatch):
    calls = []
    class _FakeRole:
        def __init__(self, name, overrides=None): pass
        async def run(self, ctx, instr, **kw):
            calls.append((ctx, instr))
            return _GOOD
    monkeypatch.setattr("stages.synthesize.Role", _FakeRole)
    plan, da = _plan_da()
    draft = asyncio.run(run_synthesize(
        plan, da, claim_table=ClaimTable(typed_facts=_FACTS),   # 권고 2 — facts 실존과 정합
        chain=_CHAIN, chain_verdicts=_VERDICTS, scenario_required=True))
    assert len(calls) == 1 and draft.scenario_flags == []
    ctx, instr = calls[0]
    assert "## 긍정 시나리오" in instr                   # 계약 지시
    assert "[인과 체인]" in ctx and "공급 확대 기대" in ctx  # mechanism 렌더 (r1-B5)
    calls.clear()
    asyncio.run(run_synthesize(plan, da))                # off-path
    assert len(calls) == 1
    assert "## 긍정 시나리오" not in calls[0][1] and "[인과 체인]" not in calls[0][0]
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (validate의 지표 대조는 run_synthesize에 전달된 claim_table.typed_facts 기준 — 없으면 빈 목록. T1 identity green)
- [ ] **Step 5: Commit** — `'feat(chain): SYNTHESIZE 시나리오 계약 — H2 절 경계·grounded edge 요구·비어있지 않은 payload·tier3 명시·1회 재합성 (3부 T7)'`

---

### Task 8: 플레이북 구조 게이트 소비자 — PLAN 이후 평가·series/unit 코드 검증·all-or-none

**Files:**
- Modify: `engine/stages/playbook.py`, `engine/orchestrator.py`, `engine/sector/metrics_registry.py` (r2-6 canonical unit)
- Create: `engine/tests/fixtures/playbook_structured_gate.json` (실존 holdout_passed 플레이북 1건을 손 마이그레이션 — 라이브 경로 fixture, B8)
- Test: `engine/tests/test_playbook_gates.py`

**Interfaces (stages/playbook.py):**
- `_STRUCT_KEYS = ("metric_id", "aggregation", "comparator", "threshold", "unit", "max_age_days")` (selector·window_days는 선택)
- `parse_gate_checks(pb: dict) -> tuple[list[PlaybookGateCheck], list[str]]` — gate별: _STRUCT_KEYS 전무 → 문자열 gate(무로그 — 하위 호환) / 전부 존재+validate 통과 → 채택 / 일부만 또는 validate 실패 → 구조 판정 전체 무시 + 로그. `aggregation ∈ ("mean_window","yoy")`인데 `window_days <= 0` → 불완전
- `evaluate_gate(check, store, now: datetime) -> PlaybookGateOutcome` — 전부 코드:
  - `check.metric_id not in METRIC_REGISTRY` 또는 필터 후 관측 0건 → `unavailable/no_metric`
  - **관측 필터 (B8 — selector 전체 참여)**: `meta_filter.items() ⊆ o.meta.items()` **그리고** `selector.series`가 있으면 `metrics_registry._group_key(o.meta) == selector.series` (하드 필터 — 이종 시리즈 혼입 차단)
  - **참여 자격 — fail-closed (r2-6)**: 게이트 계산에 참여하는 관측은 ① `math.isfinite(value)` ② **비공백 unit** ③ `aggregation != "yoy"`면 `o.unit == check.unit` **정확 일치** — 전부 필수. 빈 unit 관측(실측: `search_interest_kr`에 다수)은 **불참** — check.unit으로 임의 해석·평균 혼입 금지. meta_filter·series 통과 관측은 있는데 참여 관측 0건 → `unavailable/unit_mismatch`
  - **혼합 단위 거부 (B8 — 유지)**: 필터 후 관측들의 비어있지 않은 unit이 2종 이상 → `unavailable/unit_mismatch` (참여 자격 이전 단계의 시리즈 혼입 신호). yoy는 참여 관측 간 단일 비공백 unit 일치 필수 + 산출 단위 percent 고정 — check.unit != "percent"면 `unit_mismatch`
  - `sector.period.parse_period`로 ts 해석 — 미래·파싱불가 관측 무효(fail-closed), 최신 유효 관측 나이 > max_age_days → `unavailable/stale_data`
  - aggregation: `last` / `mean_window`(now−window_days 내 평균) / `yoy` — 기준점은 최신 참여 관측 ts−365일의 **±45일 고정 창** 내 최근접 관측만 (r2-6: 무제한 "최근접"은 6개월 전 값도 기준으로 삼는다), 창 내 부재 → `unavailable/stale_data`. 값 = (최신/기준점 − 1)×100
  - comparator 적용 → `pass|fail`, `evidence_observation_id = observation_id(metric, ts, meta)` (최신 관측)
- `evaluate_playbook_gates(pb, store, now) -> tuple[list[PlaybookGateOutcome], list[str]]`
- **unitless 지표 canonical unit 마이그레이션 (r2-6)**: `sector/metrics_registry.py`의 빈 unit 실측 지표에 canonical unit 명시 — `search_interest_kr`에 `"unit": "index"`, `app_rank`에 `"unit": "rank"` 키 추가(레지스트리 = 단일 진실원, 생산자·게이트 공용 참조). 수집 관측의 unit 백필 전까지 해당 지표 게이트는 참여 0 → `unit_mismatch` — **fail-closed가 기본, 조용한 통과 없음**. T9 생산자 프롬프트 metric 메뉴에 canonical unit 병기
- **orchestrator — 평가 배치 이동 (B8)**: ⓪′(PLAN 전, orchestrator.py:200~208)이 아니라 **casemem 블록 뒤·ASSEMBLE 전** — `plan.knowledge_cutoff` 실존(eval 경로는 line 231에서 이미 manifest `as_of`로 덮여 있어 **단일 식으로 양경로 충족**), `sector_metric_notes`도 line 320에서 이미 초기화됨(**init 순서 결함 해소** — 앞에서 append 시 소실되던 문제):

```python
    if playbook and not effective_disable_p23:
        try:
            from stages.playbook import evaluate_playbook_gates, parse_gate_checks
            _gate_store = eval_bundle.store() if eval_bundle else None
            if _gate_store is None:
                from sector.api import _get_store as _pb_get
                _gate_store = _pb_get()
            import datetime as _pb_dt
            _gate_now = _pb_dt.datetime.fromisoformat(
                plan.knowledge_cutoff + "T23:59:59+00:00")
            gate_outcomes, gate_logs = evaluate_playbook_gates(playbook, _gate_store,
                                                               _gate_now)
            for o in gate_outcomes:
                if o.verdict in ("pass", "fail") and o.value is not None:
                    chk = next(c for c in parse_gate_checks(playbook)[0]
                               if c.order == o.order)
                    sector_metric_notes.append(
                        f"[플레이북 게이트] {chk.check}: {o.metric_id}={o.value} "
                        f"{chk.unit} ({o.verdict}, 관측 {o.evidence_observation_id[:8]})")
            yield _layer("playbook", {
                "matched": playbook["slug"],
                "gate_outcomes": [o.model_dump() for o in gate_outcomes],
                "gate_logs": gate_logs})
        except Exception:  # noqa: BLE001
            degraded.append("playbook_gates")
```

  (unavailable은 notes 미기재 — 수치 없음, layer에만. 값의 답변 진입은 `sector_metric_notes` → 합성 `[결정적 수치]` 절 경로만, synthesize.py:136~137)
- 기존 `format_gates`·`format_connection`·`_valid_playbook`·문자열 gate 경로 무변경. **마이그레이션 명시 (B8 — 무동작 은폐 금지)**: 현 저장소 24개 플레이북은 전부 문자열 게이트 유지 — 구조 게이트는 T9 생산자로 **신규 합성분부터** 활성. 라이브 경로 검증은 손 마이그레이션 fixture 1건으로

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_playbook_gates.py
import datetime as dt
import json
from pathlib import Path

from sector.contracts import MetricObservation
from sector.store import SectorStore
from sector.thesis_contracts import observation_id
from stages.playbook import (_valid_playbook, evaluate_gate, evaluate_playbook_gates,
                             parse_gate_checks)

NOW = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)

_STRUCT = {"order": 1, "check": "D램 가격 수준", "operationalization": "현물가 확인",
           "metric_id": "memory_price_usd_per_gb",
           "selector": {"meta_filter": {"category": "DRAM"}},
           "aggregation": "last", "comparator": ">=", "threshold": 0.05,
           "unit": "USD/GB", "max_age_days": 45}


def _pb(gates):
    return {"slug": "s", "situation": "x", "triggers": [], "topics": [],
            "conclusionType": "방향 판단", "gates": gates, "connection": "c",
            "status": "holdout_passed"}


def test_parse_all_or_none():
    checks, logs = parse_gate_checks(_pb([_STRUCT]))
    assert len(checks) == 1 and logs == []
    partial = {"order": 2, "check": "y", "operationalization": "z",
               "metric_id": "memory_price_usd_per_gb"}          # 일부만 — 전체 무시
    checks, logs = parse_gate_checks(_pb([partial]))
    assert checks == [] and len(logs) == 1
    legacy = {"order": 3, "check": "y", "operationalization": "z"}  # 문자열 gate
    checks, logs = parse_gate_checks(_pb([legacy]))
    assert checks == [] and logs == []                          # 하위 호환 — 무로그
    mw = dict(_STRUCT, aggregation="mean_window")               # window_days 없음
    checks, logs = parse_gate_checks(_pb([mw]))
    assert checks == [] and len(logs) == 1


def _store(tmp_path, obs):
    s = SectorStore(tmp_path / "s")
    s.append_observations(obs)
    return s


def test_evaluate_pass_with_evidence_observation(tmp_path):
    meta = {"category": "DRAM"}
    store = _store(tmp_path, [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta=meta)])
    (chk,), _ = parse_gate_checks(_pb([_STRUCT]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and out.value == 0.1
    assert out.evidence_observation_id == observation_id(
        "memory_price_usd_per_gb", "2026-07", meta)


def test_evaluate_unavailable_reasons(tmp_path):
    (chk,), _ = parse_gate_checks(_pb([_STRUCT]))
    assert evaluate_gate(chk, _store(tmp_path / "a", []),
                         NOW).unavailable_reason == "no_metric"
    bad_unit = _store(tmp_path / "b", [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="KRW/GB", meta={"category": "DRAM"})])
    assert evaluate_gate(chk, bad_unit, NOW).unavailable_reason == "unit_mismatch"
    old = _store(tmp_path / "c", [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2025-01", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    assert evaluate_gate(chk, old, NOW).unavailable_reason == "stale_data"


def test_selector_series_filters_and_mixed_units_refused(tmp_path):
    # B8 — series가 평가 알고리즘에 실참여 + 이종 단위 혼합 평균 차단
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta={"category": "DRAM", "item": "ddr5_16gb"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=90.0,
                          unit="KRW/GB", meta={"category": "DRAM", "item": "ddr4_8gb"})])
    sel = dict(_STRUCT, selector={"series": "ddr5_16gb",
                                  "meta_filter": {"category": "DRAM"}})
    (chk,), _ = parse_gate_checks(_pb([sel]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and out.value == 0.1        # _group_key 하드 필터
    (chk2,), _ = parse_gate_checks(_pb([_STRUCT]))            # series 없음 → 혼재
    assert evaluate_gate(chk2, store, NOW).unavailable_reason == "unit_mismatch"


def test_evaluate_yoy_percent_unit(tmp_path):
    meta = {"category": "DRAM"}
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2025-07", value=0.08,
                          unit="USD/GB", meta=meta),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    yoy = dict(_STRUCT, aggregation="yoy", window_days=400, unit="percent",
               comparator=">=", threshold=10.0, max_age_days=45)
    (chk,), _ = parse_gate_checks(_pb([yoy]))
    out = evaluate_gate(chk, store, NOW)
    assert out.verdict == "pass" and abs(out.value - 25.0) < 0.01
    wrong = dict(yoy, unit="USD/GB")
    (chk2,), _ = parse_gate_checks(_pb([wrong]))
    assert evaluate_gate(chk2, store, NOW).unavailable_reason == "unit_mismatch"


def test_yoy_baseline_outside_fixed_window_is_stale(tmp_path):
    # r2-6 — 기준점 ±45일 고정 창: 6개월 전 값이 "1년 전 최근접"으로 선택되면 안 됨
    meta = {"category": "DRAM"}
    yoy = dict(_STRUCT, aggregation="yoy", window_days=400, unit="percent",
               comparator=">=", threshold=10.0, max_age_days=45)
    (chk,), _ = parse_gate_checks(_pb([yoy]))
    near = _store(tmp_path / "near", [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2025-08", value=0.08,
                          unit="USD/GB", meta=meta),   # −365일에서 31일 — 창 안
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    assert evaluate_gate(chk, near, NOW).verdict in ("pass", "fail")
    far = _store(tmp_path / "far", [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-01", value=0.08,
                          unit="USD/GB", meta=meta),   # 약 6개월 전 — 창 밖
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
                          unit="USD/GB", meta=meta)])
    assert evaluate_gate(chk, far, NOW).unavailable_reason == "stale_data"


def test_empty_unit_and_nonfinite_observations_do_not_participate(tmp_path):
    # r2-6 — 빈 unit 관측을 check.unit으로 해석 금지·NaN 불참 → 참여 0 = unit_mismatch
    store = _store(tmp_path, [
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07", value=0.2,
                          unit="", meta={"category": "DRAM"}),
        MetricObservation(metric="memory_price_usd_per_gb", ts="2026-07",
                          value=float("nan"), unit="USD/GB",
                          meta={"category": "DRAM"})])
    (chk,), _ = parse_gate_checks(_pb([_STRUCT]))
    assert evaluate_gate(chk, store, NOW).unavailable_reason == "unit_mismatch"


def test_registry_unitless_metrics_have_canonical_unit():
    from sector.metrics_registry import METRIC_REGISTRY
    assert METRIC_REGISTRY["search_interest_kr"]["unit"] == "index"   # r2-6 마이그레이션
    assert METRIC_REGISTRY["app_rank"]["unit"] == "rank"


def test_hand_migrated_fixture_valid_and_adopted(tmp_path):
    # B8 — 실존 holdout_passed 플레이북 1건의 손 마이그레이션본 (라이브 경로 fixture)
    pb = json.loads((Path(__file__).parent / "fixtures"
                     / "playbook_structured_gate.json").read_text())
    assert _valid_playbook(pb) and pb["status"] == "holdout_passed"
    checks, logs = parse_gate_checks(pb)
    assert len(checks) >= 1 and logs == []
    store = _store(tmp_path, [MetricObservation(
        metric=checks[0].metric_id, ts="2026-07", value=0.1,
        unit=checks[0].unit, meta=dict(checks[0].selector.meta_filter))])
    outs, logs2 = evaluate_playbook_gates(pb, store, NOW)
    assert any(o.verdict in ("pass", "fail") for o in outs) and logs2 == []


def test_evaluate_playbook_gates_wraps(tmp_path):
    store = _store(tmp_path, [MetricObservation(
        metric="memory_price_usd_per_gb", ts="2026-07", value=0.1,
        unit="USD/GB", meta={"category": "DRAM"})])
    outs, logs = evaluate_playbook_gates(
        _pb([_STRUCT, {"order": 9, "check": "문자열만", "operationalization": "o"}]),
        store, NOW)
    assert len(outs) == 1 and outs[0].verdict == "pass" and logs == []
```

- [ ] **Step 2~4: 실패→구현→통과+회귀** (기존 test_playbook_match.py 무변경 통과 = 문자열 하위 호환 증거. T1 identity green — off-arm은 게이트 블록 스킵, ⓪′ 매칭·기존 playbook layer 무변경)
- [ ] **Step 5: Commit** — `'feat(chain): 플레이북 구조 게이트 소비 — PLAN 이후 평가·참여 자격 fail-closed·yoy 고정 창·canonical unit 마이그레이션·all-or-none (3부 T8, r2-6)'`

---

### Task 9: 플레이북 구조 게이트 생산자 — lib/playbooks.mjs 합성 계약 확장 (B8)

**Files:**
- Modify: `lib/playbooks.mjs`, `lib/playbooks.test.mjs`

**Interfaces:**
- `ENGINE_METRIC_IDS`(상수) — `engine/sector/metrics_registry.py`의 키 목록 미러(주석에 동기 규칙 명시 — 드리프트 시 엔진이 `no_metric`으로 fail-closed하므로 안전 방향)
- `buildPlaybookPrompt`(playbooks.mjs:146) 게이트 규칙에 추가: "게이트에 **구체 수치 기준**이 카드에 실재할 때만 선택 필드를 채워라: `metric_id`(다음 목록에서만: {ENGINE_METRIC_IDS}), `selector`({series, meta_filter}), `aggregation`(last|mean_window|yoy), `window_days`, `comparator`(>=|<=|>|<|==), `threshold`(숫자), `unit`(레지스트리 canonical unit과 일치 — 메뉴에 병기, r2-6), `max_age_days`. 카드에 근거 없는 값을 지어내지 마라 — 없으면 필드 자체를 생략(문자열 게이트로 동작)."
- `validatePlaybook`(playbooks.mjs:116) 확장 — 생산자 측 all-or-none: gate에 구조 필드가 **일부만** 있거나 `metric_id ∉ ENGINE_METRIC_IDS` 또는 `threshold` 비유한수면 구조 필드 전부 strip + dropped 사유(`구조 필드 불완전 — 문자열 게이트로 강등`). 완전하면 보존. 기존 evidence/operationalization 검증 무변경 (하위 호환 — 구 플레이북 JSON 그대로 통과)
- **마이그레이션 문서화**: 기존 24개 플레이북은 재합성 전까지 문자열 게이트 — 구조 게이트는 신규 `synthesizePlaybook` 산출분부터 활성 (moduledoc 주석 + 이 계획 명기. "이미 켜졌다" 류 보고 금지)

- [ ] **Step 1: 실패하는 테스트** (lib/playbooks.test.mjs에 추가 — 기존 테스트 스타일 준수)

```js
// lib/playbooks.test.mjs 에 추가
test("buildPlaybookPrompt는 구조 게이트 필드 지시와 metric 메뉴를 포함한다", () => {
  const prompt = buildPlaybookPrompt({ slug: "s", situation: "x", cardIds: [] }, []);
  assert.match(prompt, /metric_id/);
  assert.match(prompt, /memory_price_usd_per_gb/);   // ENGINE_METRIC_IDS 메뉴
  assert.match(prompt, /max_age_days/);
});

test("validatePlaybook은 완전한 구조 게이트를 보존하고 불완전분은 strip한다", () => {
  const base = { order: 1, check: "c", operationalization: "o", evidence: ["k1"] };
  const full = { ...base, metric_id: "memory_price_usd_per_gb",
    selector: { meta_filter: { category: "DRAM" } }, aggregation: "last",
    comparator: ">=", threshold: 0.05, unit: "USD/GB", max_age_days: 45 };
  const partial = { ...base, order: 2, metric_id: "memory_price_usd_per_gb" };
  const badId = { ...full, order: 3, metric_id: "no_such_metric" };
  const { playbook, dropped } = validatePlaybook(
    { gates: [full, partial, badId] }, new Set(["k1"]));
  assert.equal(playbook.gates[0].metric_id, "memory_price_usd_per_gb"); // 완전 → 보존
  assert.equal(playbook.gates[1].metric_id, undefined);   // 일부만 → strip (all-or-none)
  assert.equal(playbook.gates[2].metric_id, undefined);   // 미등록 id → strip
  assert.ok(dropped.some((d) => d.includes("구조 필드")));
});
```

- [ ] **Step 2~3: 실패 확인 → 구현** — `npm test` 실패 → 구현 → green
- [ ] **Step 4: 회귀** — `cd /home/ryze_yn/attn-viewer && npm test && npm run check:openapi` (exit code 게이트) — 기존 플레이북 하위 호환 확인
- [ ] **Step 5: Commit** — `'feat(playbook): 구조 게이트 생산자 계약 — 합성 프롬프트 metric 메뉴·validatePlaybook all-or-none strip·기존 24개 문자열 유지 명시 (3부 T9)'`

---

### Task 10: eval 배선(정확 분모·구조화 resolver·fail-hard) + 통합 테스트 + 전체 회귀

**Files:**
- Modify: `engine/evals/chain_judge.py` (`judge_edge_entailment`·`resolve_edge_evidence`), `engine/evals/metrics.py` (`chain_layer`·`grounded_edge_ratio`), `engine/evals/run_eval.py` (`_run_one_chain` — arm 파라미터·chain 소비·`entailed_edge_ratio` 실측, run_eval.py:479~545)
- Test: `engine/tests/test_chain_eval_wiring.py`, `engine/tests/test_p23_integration.py`

**Interfaces:**
- `evals/metrics.py`:
  - `chain_layer(layers) -> dict | None` — `name == "chain"` layer의 data
  - `grounded_edge_ratio(layers) -> float | None` — **분모 = chain layer의 실제 edge 집합** (B9). verify layer(최신 round) `chain_verdicts` 대조: 누락 verdict → False 계수, **verdict의 edge_id가 chain에 없거나 중복 → `ValueError`** (측정 무결성 — 은폐 금지). chain 부재·edges 빈 목록 → None
- `evals/chain_judge.py`:
  - `resolve_edge_evidence(edges: list[dict], bundle, layers) -> dict[str, str]` — **구조화 ID 역참조·전수 (B9·r2-7)**: 카드 id → `bundle.store().read_cards()` title+raw_quote / NewsItem id → `bundle.ra_news_items()` title+snippet / metric fact id → **chain layer의 `typed_fact_snapshot`**(T5가 체인 생성 시점 `table.typed_facts` 전체를 id→{label,value,unit,source,metric,period}로 방출 — ChainPacket이 인용 가능한 집합과 정확히 일치: sector·thesis뿐 아니라 `price:*`·`ret:*`·`toss:*` 유래까지. sector_rag/thesis layer 부분 탐색 폐기). **미해석·비공백 위반·다중 해소 전부 `ValueError`** (r2-7+r3-4 fail-hard): ① 빈 인용 id → `ValueError` ② 미해석 id → `ValueError`(T5 코드 검증이 인용 실존을 보장하므로 정상 실행의 미해석은 측정 오류 — 저지에게 넘기지 않고 run이 실패한다) ③ **전 소스(카드∪NewsItem∪`typed_fact_snapshot`) 합집합에서 정확히 1개 객체로 해소되지 않으면 — 즉 2개 이상이면 — `ValueError`**(r3-4: 다중 해소는 어느 근거 원문을 저지에 넣었는지 정의 불가 = 측정 오류. VERIFY의 유일 해소 강제(T6·r2-4)와 동일 원칙을 resolver에도 적용). `"(미해석 인용)"` 마킹 폐기·자유 문자열 검색 금지
  - `async judge_edge_entailment(case_id, edges: list[dict], evidence_by_id: dict[str, str], role, *, thesis_claims: list[str] | None = None, raws_sink=None) -> float | None` — 구조화 판정 `_EdgeOut{rows: [{edge_id, entailed: bool, reason}]}`. 프롬프트: edge별 인용 근거 원문(resolver 결과) + **thesis_claims 포함**(캡처 시 — B9). **반환 rows 정합 대조 (B9)**: `{row.edge_id} != {edge.edge_id}` 집합 불일치·중복·미지 id → invalid → 1회 재시도 → None. 반환 = entailed / **전체 edge**. edges 빈 목록 → None
- `run_eval._run_one_chain(case, role, *, arm: bool | None = None) -> dict` (B2 — 4부 2-arm 승계 좌석): `overrides={"eval_bundle": str(bundle_path)}` + (`arm is not None`이면 `{"disable_p23": arm}` 병합). rec에 `"disable_p23": arm`, `"grounded_edge_ratio"`, `"layers_had_chain": chain_layer(layers) is not None` 추가, `entailed_edge_ratio`는 chain layer 있을 때 `judge_edge_entailment(...)` 실측(resolver+thesis 포함), 없으면 None + `"entailed_none_reason": "no_chain_layer"`. `resolve_edge_evidence`의 `ValueError`는 삼키지 않고 전파 — run_chain_suite 실패(r2-7 fail-hard)
- `check_entailed_gate(records) -> list[str]`(순수 함수) — **chain layer가 있는데 `entailed_edge_ratio is None`인 케이스 id 목록** — run_chain_suite가 비어있지 않으면 리포트 저장 후 **exit 1** (1부 계획 1420행의 3부 전환 게이트 — null 허용 종료, B9)
- ChainPacket layer는 run_qa가 방출(T5 — `typed_fact_snapshot` 포함, layer round == packet meta.round, r2 권고 1) — eval은 layers 경유 소비. find_violations는 chain layer에 url 없음 → 무영향

- [ ] **Step 1: 실패하는 테스트**

```python
# engine/tests/test_chain_eval_wiring.py
import asyncio

import pytest

from evals.chain_judge import judge_edge_entailment
from evals.metrics import chain_layer, grounded_edge_ratio


def _layers(verdicts):
    return [
        {"kind": "layer", "name": "chain", "round": 0, "data": {
            "event": "e", "mechanism": "m", "verdict": "",
            "edges": [{"edge_id": "e0", "edge": "B->A", "kind": "observed",
                       "supporting_card_ids": ["card-1"], "metric_fact_ids": [],
                       "contradicting_card_ids": []},
                      {"edge_id": "e1", "edge": "A_prime->A", "kind": "inference",
                       "supporting_card_ids": [], "metric_fact_ids": [],
                       "contradicting_card_ids": []}],
            "thesis_relation": [],
            "typed_fact_snapshot": {                    # r2-7 — T5 방출면과 동형
                # r3-4 — 실 ID shape: price_macro.py:47 `price:{q['token']}`,
                # token=yahoo_symbol(price_macro.py:187) → 국내 종목은 000660.KS
                "price:000660.KS": {"label": "000660.KS 현재가", "value": 250000.0,
                                    "unit": "KRW", "source": "yahoo:000660.KS",
                                    "metric": "", "period": ""},
                "toss:000660:per": {"label": "SK하이닉스 PER", "value": 12.3,
                                    "unit": "ratio", "source": "toss:000660",
                                    "metric": "", "period": ""}}}},
        {"kind": "layer", "name": "verify", "round": 0, "data": {
            "counts": {"verified": 1, "unverified": 0, "rejected": 0},
            "chain_verdicts": verdicts}},
    ]


def test_grounded_ratio_denominator_is_chain_edge_set():
    # e1 verdict 누락 → False 계수 (분모 = 실제 edge 집합, r1-B9)
    layers = _layers([{"edge_id": "e0", "grounded": True, "note": ""}])
    assert chain_layer(layers)["edges"][0]["edge_id"] == "e0"
    assert grounded_edge_ratio(layers) == 0.5
    assert chain_layer([]) is None and grounded_edge_ratio([]) is None


def test_grounded_ratio_extra_or_duplicate_verdict_is_error():
    with pytest.raises(ValueError):                     # 미지 edge verdict (r1-B9)
        grounded_edge_ratio(_layers([{"edge_id": "e9", "grounded": True, "note": ""}]))
    with pytest.raises(ValueError):                     # 중복 verdict
        grounded_edge_ratio(_layers([{"edge_id": "e0", "grounded": True, "note": ""},
                                     {"edge_id": "e0", "grounded": False, "note": ""}]))


class _Role:
    model = "fake"
    def __init__(self, rows): self.rows, self.calls = rows, 0
    async def run(self, prompt, instructions="", response_format=None, **kw):
        self.calls += 1
        return response_format.model_validate({"rows": self.rows})


_EDGES = _layers([])[0]["data"]["edges"]
_EV = {"card-1": "card-1: HBM 증설 본문"}


def test_judge_edge_entailment_ratio_over_all_edges_with_context():
    role = _Role([{"edge_id": "e0", "entailed": True, "reason": ""},
                  {"edge_id": "e1", "entailed": False, "reason": "근거 없음"}])
    ratio = asyncio.run(judge_edge_entailment(
        "cj-t", _EDGES, _EV, role, thesis_claims=["HBM 공급은 구조적으로 타이트하다"]))
    assert ratio == 0.5                                   # 분모 = 전체 edge
    assert asyncio.run(judge_edge_entailment("cj-t", [], _EV, role)) is None


def test_judge_edge_entailment_row_mismatch_returns_none():
    # 누락·중복·미지 edge_id 전부 invalid — 1회 재시도 후 None (r1-B9)
    missing = _Role([{"edge_id": "e0", "entailed": True, "reason": ""}])
    assert asyncio.run(judge_edge_entailment("cj-t", _EDGES, _EV, missing)) is None
    assert missing.calls == 2                             # 정확 1회 재시도
    unknown = _Role([{"edge_id": "e0", "entailed": True, "reason": ""},
                     {"edge_id": "e9", "entailed": True, "reason": ""}])
    assert asyncio.run(judge_edge_entailment("cj-t", _EDGES, _EV, unknown)) is None


def test_resolver_uses_full_snapshot_and_fails_hard_on_unresolved():
    # r2-7 — price:*·toss:* 인용이 chain layer 스냅샷만으로 정확 역참조
    # (r3-4 — ID는 실 shape: price:{token}, 국내는 price:000660.KS)
    from evals.chain_judge import resolve_edge_evidence
    layers = _layers([])
    edges = [{"edge_id": "e0", "supporting_card_ids": [],
              "metric_fact_ids": ["price:000660.KS", "toss:000660:per"],
              "contradicting_card_ids": []}]
    ev = resolve_edge_evidence(edges, None, layers)   # metric id는 bundle 불요
    assert "250000" in ev["price:000660.KS"] and "KRW" in ev["price:000660.KS"]
    assert "PER" in ev["toss:000660:per"]
    with pytest.raises(ValueError):                   # 미해석 = 측정 오류 fail-hard
        resolve_edge_evidence([{"edge_id": "e0", "supporting_card_ids": [],
                                "metric_fact_ids": ["price:ghost"],
                                "contradicting_card_ids": []}], None, layers)
    with pytest.raises(ValueError):                   # 빈 인용 id — 비공백 강제 (r3-4)
        resolve_edge_evidence([{"edge_id": "e0", "supporting_card_ids": [""],
                                "metric_fact_ids": [],
                                "contradicting_card_ids": []}], None, layers)


class _StubStore:
    # EvalBundle.store()의 소비면(read_cards)만 모사 — bundle.py:125 시그니처와 동형
    def __init__(self, cards): self._cards = cards
    def read_cards(self, **kw): return self._cards


class _StubBundle:
    # EvalBundle 소비면(store()·ra_news_items())만 모사 — bundle.py:159·162
    def __init__(self, cards, news): self._cards, self._news = cards, news
    def store(self): return _StubStore(self._cards)
    def ra_news_items(self): return self._news


def test_resolver_multi_resolution_is_error():
    # r3-4 — 같은 id가 스냅샷과 카드 양쪽에 실존 → 유일 해소 실패 = 측정 오류
    from evals.chain_judge import resolve_edge_evidence
    from tests.test_chain_stage import _card
    layers = _layers([])
    bundle = _StubBundle([_card("price:000660.KS")], [])
    with pytest.raises(ValueError):
        resolve_edge_evidence([{"edge_id": "e0", "supporting_card_ids": [],
                                "metric_fact_ids": ["price:000660.KS"],
                                "contradicting_card_ids": []}], bundle, layers)


def test_entailed_gate_pure_fn():
    from evals.run_eval import check_entailed_gate
    with_chain = {"id": "c1", "layers_had_chain": True, "entailed_edge_ratio": None}
    ok = {"id": "c2", "layers_had_chain": True, "entailed_edge_ratio": 0.8}
    no_chain = {"id": "c3", "layers_had_chain": False, "entailed_edge_ratio": None}
    assert check_entailed_gate([with_chain, ok, no_chain]) == ["c1"]  # 1부 1420행 게이트
```

```python
# engine/tests/test_p23_integration.py — B3/r2-2 게이트 + on-arm 통합 (하네스 재사용)
from tests.p23_harness import run_pipeline


def test_non_memory_full_profile_no_thesis_no_chain(tmp_path):
    # full 프로필(sector_rag_enabled=True)이지만 is_sector_question=False —
    # 게이트가 프로필이 아니라 memory_sector_active임을 증명 (r1-B3)
    out = run_pipeline("코스피 은행 배당주 지금 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": False})
    names = [l["name"] for l in out["layers"]]
    assert "thesis" not in names and "chain" not in names
    assert not any("chain" in d for d in out["final"]["degraded"])


def test_entity_only_question_blocked_by_memory_gate(tmp_path):
    # r2-2 — NVIDIA 엔티티로 is_sector_question=True(검색 게이트 통과)여도
    # is_memory_question=False → thesis·chain 미가동
    out = run_pipeline("엔비디아 CUDA 소프트웨어 매출 전망 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": False})
    names = [l["name"] for l in out["layers"]]
    assert "sector_rag" in names                  # 검색 경로는 기존대로
    assert "thesis" not in names and "chain" not in names


def test_on_arm_sector_question_emits_thesis_and_chain(tmp_path):
    # r2-1e — 전체 스위트 `DISABLE_P23=true` 게이트에서도 green: run override가
    # env 설정에 우선(B2 seam 실증) — 명시적 disable_p23=False 전달
    out = run_pipeline("SK하이닉스 HBM 현물가 흐름 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": False})
    names = [l["name"] for l in out["layers"]]
    assert "chain" in names
    chain_l = [l for l in out["layers"] if l["name"] == "chain"][-1]
    assert chain_l["round"] == chain_l["data"]["meta"]["round"]   # r2 권고 1
    assert "typed_fact_snapshot" in chain_l["data"]               # r2-7 방출면
    verify = [l for l in out["layers"] if l["name"] == "verify"][-1]
    assert "chain_verdicts" in verify["data"]


def test_off_arm_override_suppresses_everything(tmp_path):
    out = run_pipeline("SK하이닉스 HBM 현물가 흐름 어때?", tmp_path=tmp_path,
                       overrides_extra={"disable_p23": True})
    names = [l["name"] for l in out["layers"]]
    assert "thesis" not in names and "chain" not in names   # B2 — run override arm
```

  (하네스 canned role에 `chain_synth` 추가 — 실존 카드 id 인용 proposal. T1 golden은 off-arm이라 무영향)

- [ ] **Step 2~4: 실패→구현→통과**
- [ ] **Step 5: 전체 회귀** — `cd /home/ryze_yn/attn-viewer/engine && .venv/bin/python -m pytest tests/ -q` 전부 green + `DISABLE_P23=true .venv/bin/python -m pytest tests/ -q` green(권고 3의 env 내성 포함 — on-arm 통합 테스트는 명시 `disable_p23: False` override라 이 게이트와 무충돌, r2-1e) + `cd /home/ryze_yn/attn-viewer && npm run check:openapi && npm test` — **fallback·`|| true` 금지, exit code가 게이트**. 타 세션 유래 기존 실패는 파일 소관 확인 후 명시 격리. **identity 회귀(`test_p23_off_identity.py`)는 커밋 후 T1 candidate 워크트리 절차(HEAD clean 워크트리)로 실행해 green 확인 (r3-1 — dirty 공유 트리의 타 세션 변경이 등치를 깨는 오염 차단)**
- [ ] **Step 6: Commit** — `'feat(chain): eval 배선 — grounded 분모 정확화·row 정합 대조·스냅샷 resolver 전수+비공백·유일 해소·미해석 fail-hard·thesis 컨텍스트·entailed None fail-hard·arm 파라미터 (3부 T10, r2-7·r3-4)'`

---

### Task 11: codex 리뷰 → 승인 후 배포 → 라이브 스모크

- [ ] **Step 1: codex 리뷰** — 신규 4파일 + 수정 13파일 diff. 관점: ① off-arm 구조 등치(golden **양팔** 밀폐 — baseline SHA 워크트리 캡처 + candidate HEAD clean 워크트리 실행·고정 시계·임시 store·playbook 케이스 포함) ② effective_disable_p23 단일 결정·관통(on-arm 명시 override 포함) ③ memory_sector_active — is_memory_question **원 질문** 게이트(standalone_question 미사용·메모리 특이 문맥만) ④ CHAIN_EDGES 단일 진실원(judge/validator 공용) ⑤ grounding fail-closed(실제 날짜 파서·인용 ID 유일 해소) ⑥ G2 metric ID 엄격(untagged 우회 금지)·RISK verified-only(**체인 자유문 event·mechanism 미렌더**) ⑦ 게이트 배치·series·참여 자격·yoy 창·생산자 계약 ⑧ eval 분모·정합·스냅샷 resolver 전수(**중복 ID 방출 fail-hard·비공백·유일 해소**)·fail-hard ⑨ 숫자 불변식·AUDIT 격리. 블로커 반영→승인 왕복(docs/memory-chain-review-p3-*.md). **리뷰 반영 전 다음 단계 금지.**
- [ ] **Step 2 (승인 후에만): 배포** — 커밋 완료·브랜치 확인 후 `pm2 restart attn-engine`. 신규 패키지 0 확인.
- [ ] **Step 3: 라이브 스모크** — 실질문 1건("SK하이닉스 지금 사도 될까?")을 기본(ON)으로 실행 → thesis·chain layer, 배경 판 절·시나리오 절·chain_verdicts 실물 확인 + 답변 수량 literal 출처 육안 점검. 이어 동일 질문을 오프라인 orchestrator 직호출 스크립트에서 `overrides={"disable_p23": True}`로(PM2 환경 변경 금지 — B2 방식 그대로) → thesis/chain layer 0건·기존 형태 답변. 두 실행의 layer 목록 diff를 보고에 기록.
- [ ] **Step 4: 렛저 기록** — `.superpowers/sdd/progress.md` 갱신. **workflow-review.html 현행화+스크린샷은 컨트롤러가 같은 세션 마지막에.**

---

## Self-Review 기록 (v2)

- **B1**: 전역 SCHEMA_VERSION=1 무변경(T2 테스트로 고정) / CHAIN_SCHEMA_VERSION 분리 / G2 metric identity·시나리오·게이트 전부 effective 토글 안쪽(`metric_identity` 파라미터 포함) / T1 golden 하네스가 pre-P3 캡처본과 off-arm의 프롬프트·layer·final 등치를 전 태스크 상시 검증
- **B2**: `effective_disable_p23` run_qa 진입부 1회 결정(overrides 재대입 전 원본에서) — 소스 수준 테스트(T4)로 결정 지점 단일성 고정, `_run_one_chain(arm=...)` 좌석(T10)으로 1부 1385~1391 2-arm 계약 승계
- **B3**: `memory_sector_active = plan_query 성공`(is_sector_question 결정적 게이트) — 비메모리 full-profile 통합 테스트(T10)
- **B4**: CHAIN_EDGES 명시 열거 8개(judge \_INSTR 인과 사슬 도출) — judge `_validate_row` 정규화 + ChainEdge 멤버십 validator + 노드=\_VALID_AXIS 드리프트 가드. event_types는 `extract_event_types` 실추출(스코어 3항 전부 라이브, 인위 SectorQueryPlan 테스트 제거) — 단 opt-in(v2 조정 1: 검색 경로 보호)
- **B5**: T7 렌더에 event/mechanism/verdict/thesis_relation/contradicting(길이 상한) / RISK에 verified claim **원문** + chain_verdicts / run_chain `(packet, 사유)` 튜플 — 호출부가 `chain:{사유}` degraded 기록
- **B6**: 소스별 날짜 필드(카드 ts·NewsItem published_at·fact period) 전부 fail-closed / validator에 chain_verdicts 전달·grounded≥1 요구·H2 절 경계·비어있지 않은 payload·정확 edge 토큰 / `scenario_required = plan.tier >= 3 and chain and risk.applicable`
- **B7**: keyword 교량 폐기 — 생성 시점 canonical metric ID(섹터·thesis fact) + claim측 정확 키/label/유일 최장 alias, 0·복수 → anchor 사용 거부. 미태그 anchor 기존 동작(회귀 0)
- **B8**: 평가를 casemem 뒤로 이동(plan.knowledge_cutoff 단일 식이 eval as_of까지 커버 — line 231 선덮임) / sector_metric_notes init(line 320) 이후 append / selector.series `_group_key` 하드 필터 + 혼합 단위 거부 / T9 생산자 태스크 신설 + "기존 24개는 문자열 유지, 신규 합성분부터" 명시 + 손 마이그레이션 fixture 라이브 경로 테스트
- **B9**: grounded 분모=실제 edge 집합·누락 False·초과/중복 ValueError / judge row 정합(누락·중복·미지 → None) / 구조화 resolver(카드·NewsItem·metric fact ID 역참조) / thesis claim judge 컨텍스트 포함 / `check_entailed_gate` — chain 존재 시 None은 exit 1(1부 1420)
- **판정 3건**: G2 keyword 기각 수용(B7) / 시나리오 강화 수용(B6) / EnvelopeMeta 실제 round\_·plan_ref 기록(meta 필수 필드화, round 0 고정 폐기)
- **권고 6건**: 실존 식별자만(CHAIN_EDGES가 이제 A_prime->A·C->B의 정본) / \_GOOD 수량 제거·facts 정합 / settings는 model_fields 기본값 검사 / run_verify 2곳 정정 / ChainPacket.meta 실값 테스트 / Field(default_factory)·threshold 유한성·Outcome 정합 validator
- 성공 기준 계측: 주입 수량 literal 0(T4), grounded_edge_ratio(T10), entailed_edge_ratio(T10 실측), stale/degraded 사용률(thesis layer freshness)
- 커밋 11개 전부 명시적 add·작은따옴표, 라이브 영향 코드는 T11 승인 후 배포

## Self-Review 기록 (v3 — codex r2 잔존 7건 매핑)

- **r2-1 (golden 밀폐, T1)**: (a) T1 커밋 SHA 고정 워크트리에서 캡처 + `_meta.captured_at_sha` 기록 — dirty 공유 작업트리(settings/orchestrator/synthesize 수정 중) 오염 차단 (b) 시계 고정 — 기존 모듈 attr seam만으로 `stages.plan.TODAY`·`sector.queryplan.date`·`stages.ra_external.date`·`sector.retrieve._dt` 패치(FIXED_TODAY=bundle as_of), 등치 정의를 "동일 고정 시계 하 JSON 구조 등치"로 교정 (c) `casemem.api._STORE` 선주입 — orchestrator.py:381의 `_get_store()` 직접 호출이 query 패치를 우회해 라이브 시드를 기록하던 경로 차단 (d) golden 케이스 2개 — `user_id="golden-user"` matched playbook이 plan(format_gates)·synthesize(format_connection) 프롬프트에 실리는 회귀 감시 (e) on-arm 테스트는 `overrides_extra={"disable_p23": False}` 명시 — `DISABLE_P23=true` 전체 스위트 게이트와 무충돌 + B2 run-override-우선 seam 실증
- **r2-2 (메모리 게이트, T2·T4·T10)**: `is_memory_question(question, rule_plan)` 결정적 함수 — 메모리 토픽 키워드 명시 목록 / `rule_plan.segments` / 3사+메모리 문맥. `memory_sector_active = plan_query 성공 ∧ is_memory_question`. 음성 4건(엔비디아 CUDA·애플 아이폰·구글 광고·삼성 스마트폰 — 전부 `is_sector_question`은 True임을 함께 단언) + 양성 3건(T2) + 엔티티-only 통합(T10)
- **r2-3 (RISK verified-only, T6)**: verdict 있으면 claim 목록을 verified만으로 **교체**(추가 아님) + `valid_ids`도 verified 제한 — 미검증 텍스트 프롬프트 부재·미검증 supporting strip("scenario" 강등) 테스트. verdict None(off-arm)은 기존 경로 그대로(등치 게이트)
- **r2-4 (날짜·ID fail-closed, T6)**: `date.fromisoformat` 실파서 — 빈 값·불가능 날짜(`2026-02-30`) 거부, **cutoff 미파싱 → 전 edge 불인정**(`cutoff_unparsable`). 인용 ID는 비공백+전 소스 유일 해소만 인정 — `NewsItem.id` `""` 기본값·소스 간 중복 id 테스트
- **r2-5 (metric identity 엄격, T6)**: 태그 claim은 같은 non-empty ID anchor만 — untagged anchor 우회 금지, "불일치 tagged + 동일값 untagged" 조합 거부 회귀 테스트. ID 없는 claim은 기존 동작 — 우회가 아니라 스코프 밖(명시)
- **r2-6 (unit·yoy fail-closed, T8)**: 참여 자격 = 유한값+비공백 unit+check.unit 정확 일치(빈 unit 불참 → 참여 0이면 `unit_mismatch`)·혼합 단위 거부 유지·yoy 기준점 −365일 ±45일 고정 창(밖 → `stale_data`)·registry canonical unit 마이그레이션(`search_interest_kr`="index"·`app_rank`="rank") + T9 메뉴 병기
- **r2-7 (resolver 전수, T5·T10)**: chain layer에 체인 생성 시점 전체 `table.typed_facts` 스냅샷 방출(인용 가능 집합과 정확 일치) → resolver는 그 스냅샷만으로 metric 인용 역참조(`price:*`·`toss:*` fixture), 미해석 id는 `ValueError` fail-hard(전파 — 측정 오류로 run 실패)
- **권고 2건**: chain layer 방출 `_layer("chain", ..., round_)` — packet meta.round와 일치(통합 테스트 대조) / "바이트 동일" 표현 전면 "JSON 구조 등치(고정 시계)"로 교정(계약 정의·Goal·제약·태스크·테스트명)
- r2 해소 확인 목록(스키마 분리·CHAIN_EDGES·opt-in 추출·SYNTHESIZE 렌더·시나리오 H2 경계·게이트 이동+생산자·grounded 분모·EnvelopeMeta round)은 설계 무변경 유지

## Self-Review 기록 (v4 — codex r3 잔존 4건 매핑)

- **r3-1 (golden 양팔 밀폐, T1·T10)**: baseline은 pre-P3 SHA 워크트리 캡처(기존 유지), **candidate(identity 비교)도 각 태스크 커밋 직후 HEAD의 clean 워크트리**(`git worktree add /tmp/p3-cand-wt HEAD`)에서 동일 고정 시계·동일 canned 역할로 실행 — dirty 공유 트리(orchestrator.py:418 `sector_momentum` 등 타 세션 변경) 오염 차단, T10 Step 5 회귀 게이트도 동일 절차 명시. canned 역할 목록을 실제 호출 역할 15종으로 교정(planner·plan_extract·sector_query·da_gpt·da_fable·extract·web_knowledge·news_summary·calc_program·verifier·verifier_cross·risk·synthesizer·audit·casemem_rerank — 전 항목 call-site 라인 병기, "triage/plan/da/answerability" 류 비실존 이름 제거)
- **r3-2 (게이트 입력 결정화·강화, T2·T4)**: `is_memory_question` 입력 = **원 질문 `question`**(triage 정제 사용자 입력, orchestrator.py:185) + `build_rule_plan(question)`(원 질문 재유도) — LLM 산출 `plan.standalone_question`·`outcome.rule_plan`(standalone 기반) 금지. 규칙 강화: `_MEMORY_TOPIC_TERMS`에서 `"웨이퍼"` 단독 제거(검색측 `TOPIC_TERMS_BY_SECTOR`는 무변경), 3사+문맥 규칙은 `_MEMORY_CONTEXT_TERMS`(메모리·d램·디램·dram·낸드·nand·hbm)만 — `"반도체"` 일반어 제거. 음성 테스트 2건 추가("TSMC 웨이퍼 가격 전망 어때?"·"삼성전자 파운드리 반도체 실적 어때?" — 둘 다 `is_sector_question`은 True), 기존 음성 4건·양성 3건 유지
- **r3-3 (체인 자유문 RISK 재주입 제거, T6)**: RISK `[인과 체인 판정]` 절은 `edge_id·edge(CHAIN_EDGES 열거값)·kind·근거확인 여부`만 — 자유문 `event`·`mechanism` 미렌더. RISK 입력 = verified claim 텍스트 + chain_verdicts 구조 필드뿐 → rejected claim이 체인 자유문에 복제돼도 프롬프트 진입 불가. ChainEdge claim provenance는 스코프 밖(VERIFY 이전 생성 — verified 필터 불가), SYNTHESIZE의 event/mechanism 렌더는 유지("미검증 텍스트 부재" 계약은 RISK 한정 명시). 테스트: `_chain()` 자유문을 식별 문자열로 바꾸고 RISK 프롬프트 부재 assertion 추가
- **r3-4 (resolver 정밀, T5·T10)**: price fixture ID 실 shape 교정 `price:000660.KS`(price_macro.py:47 `price:{q['token']}`·187행 token=yahoo_symbol). 스냅샷 방출은 `typed_fact_snapshot(table)` 헬퍼 — **중복 fact ID는 방출 시점 `ValueError` fail-hard**(조용한 dict 덮어쓰기 금지, never-raise 계약의 명시적 예외로 문서화 + 중복 케이스 테스트). resolver도 비공백 + 전 소스(카드∪NewsItem∪스냅샷) **유일 해소** 강제 — 빈 id·다중 해소는 `ValueError`(스텁 bundle로 카드/스냅샷 충돌 테스트 추가)
- 설정 사항 무변경: r2-4·5·6 해소 설계, 비블로킹 권고 2건(layer round 일치·"JSON 구조 등치" 표현), r1 해소 목록 전부 재개방 없음
