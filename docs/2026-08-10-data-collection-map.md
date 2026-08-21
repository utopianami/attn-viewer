# 데이터 수집 지도 (2026-08-10)

이 리포가 어떤 데이터를 어디서, 언제, 왜 수집하는지의 전체 지도.
수집 경로는 4갈래다: ① 섹터 스토어 상시 수집(리포트·대시보드·메모리의 공통 원천),
② QA 질문 시 온디맨드, ③ 화면 표시용 온디맨드, ④ 외부 수집이 아닌 내부 생성·수동 큐레이션.
뷰어에서 보는 수집기 현황 페이지는 `docs/data-collection.html`(①의 표시용)이며, 이 문서가 상위 지도다.

관련: 모니터링·알림 구조는 [모니터링](#모니터링--알림) 절, 구현은 `engine/monitor/`.

## 실행 주기 요약

| 트리거 | 무엇이 | 언제 | 코드 |
|---|---|---|---|
| 주기 수집 | collect_all (수집기 전부) | 12시간마다 (완료 후 sleep 방식 — 매일 ~11분 드리프트) | `sector/scheduler.py`, `.env SECTOR_SCHEDULER_ENABLED` |
| 리포트 직전 보충 수집 | collect_all | KST 06:30·18:30 리포트 발화 시 마지막 수집이 1h보다 낡았으면 | `sector/report_scheduler.py _ensure_fresh_data` |
| 리포트 생성 | `python -m sector.report_pipeline --case-memory` (서브프로세스) | KST 06:30·18:30 (`.env REPORT_TIMES_KST`) | `sector/report_scheduler.py` |
| 수동 수집 | collect_all | `POST /v1/sector/collect` | `sector/api.py` |
| QA 도구 | 시세·뉴스·본문·토스 | 질문 들어올 때마다 | `engine/tools/` |

결과적으로 수집은 하루 ~4회(주기 2 + 리포트 직전 2), 약 6시간 간격.
리포트 파이프라인 자체(LLM 단계)는 네트워크 수집 없이 스토어만 읽는다
(`report_input.py`·`report_anchors.py`에 네트워크 클라이언트 없음).

## ① 섹터 스토어 상시 수집 — `engine/sector/collectors/` (21개 모듈)

산출물 두 갈래: **items(뉴스·공시)** → `sector/judge.py`(LLM)가 카드화 → 카드 스토어,
**observations(지표 관측치)** → 스토어 append. 저장 위치 `storage/rag/memory_sector/`.
수집기별 최근 상태는 `storage/rag/memory_sector/status.json`.

### 뉴스·공시 (items → 카드)

| 수집기 | 무엇을 | 어디서 | 비고 |
|---|---|---|---|
| saveticker | 국내 증권 뉴스 firehose **전량 raw 저장** + 키워드 통과분만 카드 | SaveTicker detail/{id} 순회 | 무손실 커서(scan_hwm/pending), raw는 `news_raw/` 월별 jsonl — casemem 코퍼스 확장 후보 |
| brave_matrix | 축별 쿼리 매트릭스 해외/국내 뉴스 | Google News RSS (무키, geo 라우팅) | 이름은 brave 시절 잔재 — brave는 2026-07-09 제거 |
| rss | 반도체 전문지 기사 | 전문지 RSS 피드 | 피드별 실패 격리 |
| dart_edgar | 기업 공시 (S급, 100% 관련 취급) | DART(키 필요) + SEC EDGAR(무키·UA 필수) | |

### 지표 (observations)

| 수집기 | 지표 | 어디서 | 비고 |
|---|---|---|---|
| macro | 나스닥·S&P·미10y·달러인덱스·원/달러·엔/달러·WTI | Yahoo | 시세는 야후 종가 원칙 |
| yahoo_metrics | 메모리 밸류체인 주가 스냅샷 | Yahoo | |
| stanford_dam | 메모리 소비자 리테일 최저호가 프록시 $/GB | Stanford DAM (무키) | 계약가 아님 — 방향성 참고 |
| kosis | 한국 반도체 생산·출하·재고지수(계절조정) | KOSIS | |
| customs_kr | 반도체 수출 10일 단위 잠정치 | 관세청 (data.go.kr) | |
| ecos | D램 수출물가지수 | 한국은행 ECOS | **키 미설정 — 미가동** |
| capex | MSFT·GOOGL·AMZN·META 분기 전사 CAPEX | Yahoo fundamentals (무인증) | AI 전용 아님 — 프록시 |
| supply | 메모리 3사 CAPEX + 장비 4사 분기 매출 | Yahoo fundamentals | 통화 혼재 — 절대값 합산 금지 |
| ai_chips | NVDA·AMD·AVGO 분기 전사 매출 | Yahoo | HBM 수요 선행 프록시 |
| mops_tw | 대만 상장사(TSMC·ODM) 월별 매출 | MOPS | |
| earnings_cal | 향후 21일 감시 종목 실적 발표일 | Nasdaq 캘린더 API | 미국 상장분만 |
| openrouter | LLM 토큰 단가·일일 토큰 소비량 | OpenRouter | AI 수요 프록시 |
| datalab | AI 앱 검색량(한국) | 네이버 데이터랩 | |
| sdk_downloads | SDK 다운로드 수 | 공개 소스 | |
| app_charts | AI 앱 랭킹 | 공개 소스 | |
| status_pages | AI 서비스 장애 이력 | 각 status page | |

소비자: 대시보드(카드·지표), 시황 리포트(3축 카드), 테제 레이어(collect_all 직후 갱신 훅),
casemem 코퍼스 확장(saveticker raw, Plan5).

## ② QA 질문 시 온디맨드 — `engine/tools/`

| 도구 | 무엇을 | 어디서 | 비고 |
|---|---|---|---|
| price/yahoo | 시세·시계열 | Yahoo | |
| news/naver | 국내 뉴스 검색 (주력) | 네이버 검색 API | 25,000콜/일, 키는 datalab과 별도 앱 |
| news/gnews_rss | 해외 뉴스 검색 | Google News RSS | 폴백 체인의 해외 담당 |
| news/fetch_body | 큐레이션 통과 상위 N개 기사 본문 (≤4,000자) | httpx + trafilatura | 실패는 조용히 스킵 |
| toss/* | 시세·종목 피드·기업정보·섹터 모멘텀 | 토스증권 (공식 OAuth 또는 WTS read-only 폴백) | |
| web/fetch_url | 사용자가 채팅에 붙인 URL 본문 | 해당 URL | |
| (배경지식) | 검색이 아니라 sonnet 생성 | — | brave·tavily 2026-07-09 제거, 재도입 금지 |

## ③ 화면 표시용 온디맨드

| 경로 | 무엇을 | 비고 |
|---|---|---|
| `sector/prices.py` | 대시보드 가격 시계열 90일 | Yahoo, 저장 안 함, api.py에서 1시간 캐시 |

## ④ 외부 수집 아님 — 내부 생성·수동 큐레이션 (메모리류)

| 층 | 데이터 | 출처 |
|---|---|---|
| casemem 과거사례 | 금융 위기 사례 시드 (오일쇼크~AI 슈퍼사이클) | `engine/casemem/seeds/` 수동 작성 + 규칙 증류(ingest_rules) |
| 히스토리 탭 사례 | 연도-테마 사례 | `storage/rag/history_cases/` 수동 작성 (작성가이드.md) |
| QA 메모리 체인 | 과거 QA 답변·판정 축적 | QA 실행 결과에서 생성 |
| 테제 | 테제 revision | ① 스토어 데이터로 `thesis_update` 갱신 |
| 사용자 문서 | documents·uploads·blog | 사용자 입력 |

별도 계획: 전체 뉴스 수집 시스템을 리포 밖에 구축 중(0~12h 주기) — 완성 시 엔진이 소비 예정 (2026-07-21 기록).

## 모니터링 + 알림

파이프라인별 **정합성·정확성·안정성** 점검을 주기 실행하고, 문제 발견 시
ward 텔레그램 봇으로 발송하는 구조. 구현: `engine/monitor/` (checks·alert·runner),
엔진 lifespan에 스케줄러 등록, 결과는 `GET /v1/monitor/health`.

| 축 | 뜻 | 대표 점검 |
|---|---|---|
| 안정성 | 파이프라인이 돌고 있는가 | 수집기 status error/degraded, 마지막 수집 경과, 리포트 슬롯 누락·publish_status |
| 정합성 | 데이터끼리 아귀가 맞는가 | saveticker 커서 불변식(backlog·pending 상한·calendar), 관측치 미래 타임스탬프, 리포트 id↔파일명 |
| 정확성 | 값이 말이 되는가 | 지표 급변(전 관측 대비 이상 변동), 필수 필드 결손, 지표별 신선도(레지스트리 기준) |

### 알림 규칙

- ward 텔레그램: `.env TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 설정 시 발송.
  미설정이면 `storage/monitor/alerts.jsonl` 기록만 — 토큰만 채우면 켜진다.
- **warn**은 등장·악화 시 1회만(ecos 미설정 같은 영구 상태의 반복 스팸 방지),
  **alert**는 쿨다운(기본 6h, `MONITOR_COOLDOWN_S`) 경과 시 재발송. 해소되면 회복 알림 1회.
- 발송 실패 시 sent로 기록하지 않고 다음 주기 재시도. 긴 메시지는 3,500자 청크 분할.
- 상태·이력: `storage/monitor/{health.json, state.json, alerts.jsonl}`.

### 판정 세부

- 수집 경과는 **가장 낡은 수집기** 기준(부분 수집이 전체 정상으로 가장되는 것 방지),
  임계 8h — 리포트 스케줄러 OFF 환경에선 수집 주기×1.25로 자동 완화.
- 리포트 슬롯: 발화+4h 유예 후에도 해당 슬롯 리포트가 없으면 alert.
  `publish_status=hold`는 검증 게이트의 정상 산출일 수 있어 warn.
- 캘린더형 지표(`*_calendar`)는 미래 ts가 정상이라 예외.
  급변 임계는 기본 50%, 분기 재무·토큰 소비량 등 고변동 지표는 완화
  (2026-08-10 실측: META capex +59%, 토큰 +113%가 전부 진짜 값).

### 실행·확인

- 자동: `.env MONITOR_ENABLED=true` → 엔진 lifespan에서 30분 주기(`MONITOR_INTERVAL_S`).
- 수동: `cd engine && .venv/bin/python -m monitor.runner`
- 조회: `GET /v1/monitor/health` (openapi.yaml 등재)
- 테스트: `cd engine && .venv/bin/python -m pytest -c pytest.ini tests/test_monitor_*.py -m "not live"`

### 한계 (알고 쓰기)

- 인프로세스 모니터라 **엔진 프로세스·호스트 자체의 사망은 탐지 못 한다**
  (엔진 죽음은 PM2가 복구, 호스트 죽음은 외부 감시가 필요 — 미구축).
- 리포트 파이프라인의 재시도 최악 경로(3h×3회)에서는 슬롯+4h alert가 "지연" 알림이 된다
  (실패 확정이 아님 — 완료되면 회복 알림).
- 지표 cadence·급변 임계표는 `monitor/checks.py` 상수 — 신규 지표는 기본값(30일·50%) 적용,
  필요 시 표에 추가. 장기적으로 METRIC_REGISTRY 통합 후보(codex 리뷰 #10).
