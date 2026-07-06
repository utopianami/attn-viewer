# 🌅 아침 핸드오프 — 메모리 섹터 P1 (2026-07-07, claude 야간 라운드)

한 줄 요약: **수집 엔진 P1 완성·검증·배포 완료.** 뉴스 3계통+지표 11종이 무인으로
카드·시계열이 되어 쌓이고, `/v1/sector/*` API로 조회됩니다. 키 6개만 발급하면 잠긴
수집기 4종이 코드 수정 없이 켜집니다.

---

## 1. 밤 사이 구현된 것

- **engine/sector/ 패키지** (15커밋, e701fd7..0e8f5ca, 테스트 150/150):
  수집기 14종(1소스 1파일) + sonnet 배치 판정(judge) + jsonl 저장소 + 구조화 검색 +
  규칙 기반 사이클 스코어 + `/v1/sector/*` API + 스케줄러(기본 OFF)
- **라이브 검증 2회** (별도 포트 8899, 실수집): 뉴스 101건 → 카드 58장(전 축 활용),
  지표 — OpenRouter 단가 80모델, 앱차트(미 ChatGPT 5위·한 Gemini 3위), 대만 월매출(TSMC 등 6사),
  주가 12종목, 상태페이지, SDK 다운로드, 매크로 캘린더 40건
- **라이브에서 잡아서 고친 버그 6건**: 등급 표기명 매칭(reuters→B), S급 공시가 판정 상한에
  잘리던 것, S급 공시 LLM 드롭 보존, judge 프롬프트 축 정의가 스펙과 달랐던 것(중요),
  brave age 문자열이 ts를 오염시키던 것, status.anthropic/애플 RSS 도메인 이전(리다이렉트)
- **리뷰 2중 완료**: opus 전체 브랜치 리뷰 APPROVE(Critical 0) → Important 2건 수정 반영.
  codex 리뷰 요청서: `docs/memory-sector-p1-codex-review-request_claude.md`
- **운영 반영**: 8801 재시작 완료. 스케줄러 꺼져 있어 사이드이펙트 없음 (수집은 수동 트리거만)

## 2. yvon이 발급할 키 (전부 무료, `.env` 끝에 주석 자리 만들어둠 — # 지우고 값만)

| .env 키 | 발급처 | 켜지는 것 |
|---|---|---|
| `OPENROUTER_API_KEY` | openrouter.ai/keys | 일별 모델별 토큰 사용량 랭킹 (단가는 키 없이 이미 수집 중) |
| `DATA_GO_KR_API_KEY` | data.go.kr 가입→활용신청 | 관세청 반도체 수출 10일 통계 (최선행 지표) |
| `KOSIS_API_KEY` | kosis.kr/openapi | 생산·출하·**재고**지수 (사이클 시계) |
| `ECOS_API_KEY` | ecos.bok.or.kr/api | D램 수출물가지수 (가격 축) |
| `DART_API_KEY` | opendart.fss.or.kr | 삼전·하이닉스 공시 (S급 카드) |
| `NAVER_CLIENT_ID/SECRET` | developers.naver.com | 데이터랩 검색 관심도 (C0) |

키 넣고 확인: `curl -X POST localhost:8801/v1/sector/collect -H 'Content-Type: application/json' -d '{"only":["kosis","ecos","customs_kr","dart_edgar","datalab","openrouter"]}'`
→ 응답에서 status가 missing_key → ok/degraded로 바뀌면 성공. degraded면 detail에 응답
구조가 찍히니 그대로 저에게 보여주면 파서 확정해드립니다(설계상 첫 실행에서 스키마 확정).

## 3. yvon이 정할 것

1. **스케줄러 ON 시점** — `.env`에 `SECTOR_SCHEDULER_ENABLED=true` 넣고 엔진 재시작하면
   12시간마다 자동 수집. 권장: 키 4종 넣고 수동 트리거 며칠 돌려본 뒤 ON
2. **cycle 판정 노출 시점** — 월간 지표(재고·수출물가)는 2개월치 쌓여야 방향이 나옴.
   그 전까지 대시보드에 "insufficient"로 보여줄지, 숨길지 (codex UI 논의사항)
3. **유료 소스** — 무료 스택이 실제로 도는 걸 봤으니, TrendForce/SemiAnalysis 결제는
   "주간 세부 가격이 아쉬울 때"로 보류 유지가 제 권고 (계획 §6-1)
4. **P3(QA 답변에 섹터 카드 주입) 착수 시점** — codex P2 대시보드와 병행 가능

## 4. 지금 바로 볼 수 있는 것

```bash
# 수집 한 번 돌리기 (1분 소요, 키 없는 것은 자동 skip)
curl -X POST localhost:8801/v1/sector/collect -H 'Content-Type: application/json' -d '{"only":null}'
# 카드 보기
curl "localhost:8801/v1/sector/cards?days=2&limit=20" | jq '.cards[] | {axis,direction,magnitude,title}'
# 전광판 데이터 (사이클+카드+수집기 상태)
curl localhost:8801/v1/sector/board | jq .cycle
```

계획 개요 페이지: http://attn.ngrok.app/overview_memory_sector.html

## 5. 문서 지도

| 문서 | 내용 |
|---|---|
| `docs/memory-sector-rag-plan_claude.md` | 마스터 계획 (§1~8) |
| `docs/memory-sector-implementation-principles_claude.md` | 구현 원칙 14조 |
| `docs/superpowers/plans/2026-07-06-memory-sector-p1.md` | 태스크 9개 구현 계획 |
| `docs/memory-sector-p1-codex-review-request_claude.md` | **codex가 읽을 리뷰 요청서** |
| `.superpowers/sdd/final-review-report.md` | opus 최종 리뷰 + 픽스 리포트 |
| `.superpowers/sdd/progress.md` | 태스크별 진행 원장 |

## 6. 알려진 한계 (숨긴 것 없음)

- trendforce RSS URL 미확정 → 해당 피드만 degraded (etnews는 정상)
- openrouter 랭킹·관세청·KOSIS·ECOS는 키 발급 후 첫 실행에서 응답 스키마 확정 필요
- 사이클 스코어는 월간 지표 축적 전까지 insufficient (정상 동작)
- pypistats가 가끔 429 (테스트 반복 호출 탓, 운영 주기에선 무관)
- FastAPI on_event deprecation 경고 2건 (기능 무관, lifespan 전환은 추후)
