# Plan 4 핸드오프 — 과거사례 지식층을 리포트 파이프라인에 붙이기

작성 2026-07-22. 대상: 리포트/오케스트레이터 담당 세션.

## 지금 상태 (건드리지 말 것, 이미 라이브)
과거사례 지식층 코어는 완성·라이브다. `engine/casemem/` (13커밋, 테스트 통과, 포트 8801).
- 질의 진입점: `casemem.query.query_case_memory(store, *, signals, as_of, sector="memory", k=5, llm_fn=None)` → `CaseQueryResult`
- HTTP: `POST /v1/case-memory/query {signals, as_of, sector, k}`, `GET /v1/case-memory/cases[/{id}]`
- 스토어: `casemem.store.CaseStore(REPO_ROOT/storage/rag/case_memory)`, `casemem.api._get_store()`가 빈 스토어면 시드 자동 적재
- **불변식**: as_of가 유일 시계, `knowable_at <= as_of` 국면만 가시(룩어헤드 차단). llm_fn=None이면 순수 결정적.

## Plan 4가 할 일 (계획서: docs/superpowers/plans/2026-07-21-case-memory-integration.md §다음Plan)
리포트가 **실제로** 이 층을 쓰게 만든다. 4가지:

1. **async LLM 리랭크 어댑터** — `rerank`의 `llm_fn`은 sync `(str)->str`인데 엔진 LLM(`providers.Role.run`)은 **async**다. 미스매치 해결 필요:
   - 권장: `engine/casemem/`에 async 질의 경로를 새로 두거나, 오케스트레이터(async 컨텍스트)에서 search는 동기로 하고 리랭크 LLM 콜만 `await Role('casemem_rerank').run(prompt)`로 처리 후 점수 적용.
   - `providers.py`의 ROLE_CHAIN에 `casemem_rerank` 역할 추가(sonnet·effort low 정도, `sector_query` 참고). temperature/결정성 낮게.
   - 절대 sync `llm_fn` 안에서 `asyncio.run()` 호출 금지(이미 도는 이벤트루프서 터짐).

2. **오케스트레이터 주입** — `engine/orchestrator.py`의 `sector_rag` 패턴(321~372·551~557·584~590) 그대로:
   - `profiles.py`에 `casemem_enabled: bool = False`(기본 OFF) 추가.
   - 주입 시점: SYNTHESIZE에 matched_case/phase/next_phases/evidence를, AUDITOR엔 evidence 편입.
   - signals는 오늘 관측(sector cards/metric에서 파생) → `query_case_memory` 입력. as_of는 eval 모드면 manifest as_of, 아니면 now.

3. **report_input seam는 이미 뚫려 있음** — `assemble_report_input(..., case_store=, signals=, as_of=)` 주면 `external_knowledge` 채워짐. Phase 2 파이프라인이 생기면 여기 연결.

4. **배포 게이트** (엔지니어 규칙): workflow-review.html·data-collection.html 현행화 + `pm2 restart attn-engine` + **Playwright 로그인→리포트 화면 스크린샷 눈확인**. curl/테스트만으로 완료보고 금지.

## 주의
- 이건 **유저 리포트 출력을 바꾸는 변경**이다 → 플래그 기본 OFF로 넣고, 켜서 스크린샷 검증 후에만 배포.
- `codex exec`는 이 환경서 먹통(샌드박스 셸 무한대기) — 리뷰는 하드타임아웃+self-review로.
- 커밋 전 브랜치 확인(공유 체크아웃).
