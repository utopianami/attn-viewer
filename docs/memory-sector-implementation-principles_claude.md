# 메모리 섹터 P1 구현 원칙 (_claude)

작성: 2026-07-06 야간 자율 구현 라운드 시작 전 (yvon 지시: "원칙 정리 먼저하고 시작")
스펙: docs/memory-sector-rag-plan_claude.md §1~8 (codex 교차검토 3회 반영본)

## 데이터 원칙

1. **자동 수집이 1등.** 사람 손이 필요한 소스는 P1 의존성에서 제외 (수동 입구는 옵션).
2. **never-block.** 수집기 하나의 실패가 다른 수집기·엔진 본체를 절대 막지 않는다.
   개별 try/except + collector_status 기록 + /healthz 노출.
3. **원문과 해석 분리.** raw_quote(사실)와 interpreted_signal(LLM 해석)은 다른 필드.
   출처 등급 S~D 필수, D급만 있으면 "루머/미확인".
4. **키 없으면 degrade, 죽지 않는다.** yvon이 발급할 키는 .env에 주석 플레이스홀더로
   남기고, 키 없는 수집기는 status=missing_key로 건너뛴다. 키를 넣는 순간 코드 수정
   없이 활성화되어야 한다.
5. **유료·비공식 소스 예의.** 저강도 폴링(10분+), UA 명시, 원문 전문은 내부 보관만.

## 코드 원칙

6. **1소스 = 1파일** (`engine/sector/collectors/*.py`), 공통 인터페이스.
   소스 추가·제거·장애 대응이 파일 하나로 끝난다.
7. **신규 의존성 0.** httpx·pydantic·기존 도구(brave/yahoo/toss/fetch_body)만 사용.
   RSS는 표준 xml 파서, 스케줄러는 asyncio 루프 (apscheduler 미설치 확인됨).
8. **기존 QA 파이프라인 무간섭.** engine/sector는 독립 패키지. orchestrator/stages
   기존 코드는 이번 라운드에서 수정하지 않는다 (P3 QA 연결은 다음 라운드).
9. **분업 경계 = 파일 경계.** claude는 engine/sector/** + storage/rag/memory_sector/**만.
   server.mjs·public/은 건드리지 않는다 (codex 영역). public/index.html 절대 커밋 금지.
10. **스케줄러는 기본 OFF.** SECTOR_SCHEDULER_ENABLED=true일 때만 주기 수집.
    운영 엔진(8801)에 배포돼도 사이드이펙트 없음. 수동 트리거 엔드포인트로 테스트.

## 프로세스 원칙

11. **테스트 2층** (기존 컨벤션): 수제 계약 테스트 + 실제 상류 응답 픽스처
    (SaveTicker·MOPS 실측 응답 보유). pytest sync + asyncio.run, pytest-asyncio 금지.
12. **커밋 단위 = 태스크.** Co-Authored-By 관례 유지. 진행 원장
    .superpowers/sdd/progress.md 갱신 — 컴팩션 후에도 이어서.
13. **구현 완료 후 리뷰 2중**: ① claude 전체 브랜치 코드리뷰 (서브에이전트),
    ② codex 리뷰 요청서를 docs/에 남김 (yvon 지시 "코덱스 리뷰 꼭").
14. **판정 LLM 비용 상한**: sonnet low, 배치 1~2콜/회. 사이클 스코어는 LLM 아닌
    규칙 기반 (재현·설명 가능).

## 이번 라운드 범위

- **IN**: engine/sector 패키지 전체 (수집기·판정·저장·검색·사이클·스케줄러),
  /v1/sector/* API, 테스트, .env 플레이스홀더
- **OUT**: P2 대시보드 UI (codex), P3 QA 파이프라인 연결 (orchestrator 수정 필요 —
  codex UI와 함께 다음 라운드), 임베딩 (P4)
