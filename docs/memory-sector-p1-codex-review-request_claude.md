# codex 리뷰 요청 — 메모리 섹터 P1 수집 엔진 (_claude)

작성: claude, 2026-07-07 (야간 자율 구현 라운드 종료)
yvon 지시: "구현 완료 후엔 코덱스 리뷰 꼭"

## 리뷰 대상

- 커밋 범위: `e701fd7..0e8f5ca` (구현 15커밋, 전부 main)
- 코드: `engine/sector/**` (계약·저장소·수집기 14종·judge·retrieve·cycle·API·스케줄러)
  + `engine/app/settings.py`(필드 추가) + `engine/app/main.py`(배선) + `engine/providers.py`(ROLE_MAP 1줄)
- 테스트: `engine/tests/test_sector_*.py` — 150/150 그린
  (`cd engine && .venv/bin/python -m pytest tests/ -q --ignore=tests/test_stages_live.py --ignore=tests/test_price_live.py --ignore=tests/test_toss_live.py`)
- 스펙: `docs/memory-sector-rag-plan_claude.md` §1~8, 원칙: `docs/memory-sector-implementation-principles_claude.md`
- claude 측 최종 리뷰(opus) 결과: APPROVE — Critical 0, Important 2(수정 완료), Minor 6
  (상세: `.superpowers/sdd/final-review-report.md`)

## 이미 라이브 검증된 것 (별도 인스턴스 8899, 실수집 2회)

- 뉴스 101건 수집 → sonnet 판정 → 카드 58장 (전 축 A/A'/B/C/C0/E/P 활용)
- 지표: OpenRouter 단가 80건, 앱차트 6건(미 ChatGPT 5위·한 Gemini 3위), MOPS 대만 월매출 6사,
  yahoo 12종목, 상태페이지 2건, SDK 다운로드, SaveTicker 캘린더 40건
- 키 없는 수집기 4종은 missing_key로 정상 skip, 수집기 개별 실패 격리 동작

## codex에게 특히 봐달라는 것 (UI를 얹을 당사자 관점)

1. **API 응답 형태가 P2 대시보드에 충분한가** — `GET /v1/sector/board`가 cycle+cards+status를
   주는데, 전광판 카드(§codex 화면 1)·타임라인(화면 4) 렌더에 부족한 필드가 있으면 지금 말해달라.
   openapi.yaml 계약은 codex 담당이므로 **이 엔진 응답을 기준으로 계약을 역작성 + 어긋나는 부분 지적**
2. `SectorCard.entities`가 휴리스틱(13사 사전)인데, UI 필터 칩으로 쓰기에 충분한지
3. `cycle.compute`의 `explain[]` 문자열이 사용자 노출 가능한 문장 수준인지
4. judge 프롬프트(`engine/sector/judge.py` `_INSTR`)의 축 정의 — codex 계획의 세계관과 일치하는지 검수
5. raw RAG 노출 관점: 카드의 raw_quote(원문)·interpreted_signal(해석) 분리가 화면 3 요구를 충족하는지

## 알려진 미해결 (리뷰에서 재발견 불필요)

- rss의 trendforce 피드 URL 미확정 (degraded로 동작, 실제 RSS URL 확보 필요)
- openrouter rankings 엔드포인트 경로는 키 발급 후 실측 확정 (defensive 파싱으로 대기)
- customs/kosis/ecos 응답 스키마도 키 발급 후 첫 실행에서 확정 (동일)
- `@app.on_event("startup")` deprecation 경고 (기능 정상, lifespan 전환은 추후)
- Minor 6건: `.superpowers/sdd/final-review-report.md` 참조

## 로컬 확인 방법

```bash
cd engine && ENGINE_PORT=8899 SECTOR_STORAGE_DIR=/tmp/sector_test \
  .venv/bin/python -m uvicorn app.main:app --port 8899 &
curl -X POST localhost:8899/v1/sector/collect -H 'Content-Type: application/json' -d '{"only": null}'
curl localhost:8899/v1/sector/board | jq .cycle
```

리뷰 결과는 `docs/memory-sector-p1-review_codex.md`로 남겨달라.
