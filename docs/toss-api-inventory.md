# 토스증권 API 통합 인벤토리 (에이전트용)

> **2026-07-21 기준 문서:** 토스증권 공식 Open API와 WTS 내부 API의 역할,
> 소스별 품질, 구현 순서, WTS 51개 호출 경로를 한곳에 합쳤다.
> [공식 Open API ↔ WTS 갭 분석](./toss-api-gap-analysis.md)과
> [토스 데이터 소스 품질 감사](./toss-source-quality-audit.md)는 상세 근거로 남긴다.

- 목적: **토스 안의 데이터만으로 read-only 증권 리서치 원천을 구성하는 기준 지도**.
- 공식 계약: OpenAPI 3.1.0, API v1.2.4, 27 paths / 30 operations,
  계좌 비의존 read-only 시장 기능 14개.
- WTS 실측: 최초 확인 2026-07-02 · 전면 확장 2026-07-15 · 품질 재실측 2026-07-21.
  웹앱 XHR 51개를 캡처하고 공개 범위에서 curl·typed parser·live test로 확인했다.
- 공식 API와 겹치는 시세·호가·체결·차트는 공식 API를 우선한다. WTS는 뉴스,
  재무지표, 종목 수급, AI 시그널, 커뮤니티 등 공식 API에 없는 영역을 맡는다.
- ⚠️ WTS 경로는 **비공개 내부 API**다. 로그인 우회, 계좌·주문 접근,
  상업적 대량 배포·재판매는 범위 밖이다.

## 한눈에 보는 결론

토스 안의 데이터만으로도 좋은 리서치 원천을 만들 수 있다. 하나의 API에 모든 역할을
맡기지 않고 다음 세 층을 합친다.

1. **공식 Open API — 시장 뼈대:** 현재가, 호가, 체결, 상·하한가, 분봉·일봉,
   종목 마스터, 환율, KR/US 장 캘린더, 랭킹, 지수·국채·투자자별 매매대금.
2. **WTS — 해석 재료:** 상세 시세, PER/PBR/PSR/EPS/BPS, 배당, 종목별 수급,
   프로그램 매매, 거래창구, 뉴스 전문, AI 시그널, 커뮤니티, 경제 일정.
3. **결정적 파생층:** 수익률, 수급 변화, 뉴스 중복도, AI 시그널 사후성과를 코드로
   계산한다. LLM은 수집과 숫자 계산이 아니라 마지막 요약·해석만 담당한다.

## 영역별 소스 선택

| 영역 | 채택 결정 | 사용 원칙 |
|---|---|---|
| 검색·종목 식별 | **WTS 발견 → 공식 검증** | 자동완성·코드 해소 후 공식 기본정보로 검증 |
| 시세·호가·체결·차트 | **공식 primary** | WTS 상세 필드·차트 커서는 보강/fallback |
| 종목정보·재무·수급 | **WTS primary** | 재무지표·배당·종목 수급에 공식 시장 수급 결합 |
| 뉴스 | **WTS primary · 증거 B** | 4탭으로 발견, 기사 전문을 출처·시각과 함께 근거로 사용 |
| AI 시그널 | **WTS 보조 · 증거 C** | 방향 후보로만 사용하고 1시간·1일·5일 수익률 검증 |
| 커뮤니티 | **WTS 집계 · 증거 D** | 원문·작성자 미저장, 활동과 반응 집계만 사용 |
| 랭킹·탐색 | **공식 + WTS 병행** | 시장·체결 랭킹과 토스 관심도를 별도 신호로 라벨링 |
| 시장 컨텍스트 | **공식 시장축 + WTS 이벤트축** | 환율·캘린더·지수에 WTS 경제 이벤트 결합 |

- 공식 API는 OAuth 2.0 자격증명이 필요하다.
- WTS 공개 GET은 주로 브라우저형 User-Agent로 동작한다. 일부 대시보드 POST는
  공개 WTS가 발급하는 `browser-tab-id`, `app-version`, `x-xsrf-token`이 필요하다.
- 계좌, 보유자산, 주문, 개인화 경로는 호출하지 않는다.

## 소스 품질과 증거 등급

| 등급 | 소스 | 사용법 |
|---|---|---|
| A — 사실값 | 공식 시세·차트·시장정보, WTS 재무지표·수급 | 숫자 주장과 계산의 직접 근거 |
| B — 기사 근거 | WTS 뉴스 피드·회사별 기사 전문 | 출처·시각을 보존해 주장 근거로 사용 |
| C — 보조 신호 | WTS AI 시그널 | 방향·이슈 후보, 사후성과 검증 필수 |
| D — 집계 심리 | WTS 커뮤니티 | 활동 집계만 사용, 사실 근거 금지 |

### 2026-07-21 실측 요약

- **뉴스:** 피드 4탭 102회 노출 / 94개 고유 기사 / 회사 기사 20건 모두 본문
  200자 초과 / 본문 중앙값 1,488.5자. 신형 `result.kr.content[]` 계약을 반영했다.
- **AI 시그널:** 배치 56~57종목 / 상세 12건 모두 HTTP 200 / 근거 배열 0/12 / 방향
  positive 11 대 negative 1. 후보 탐지에는 좋지만 사실 근거로는 부족하다.
- **랭킹·시장:** 랭킹 100종목·100고유 코드 / 시장 지표 10 / 미국 지표 6 /
  경제 이벤트 11 / 권장 polling 30초. 바로 유니버스와 배경축으로 쓸 수 있다.
- **커뮤니티:** 삼성전자·SK하이닉스 최근순 110건 표본, 종목별 고유 작성자 49명,
  페이지당 11건, 약 7분 시간폭. 원문·닉네임·프로필은 즉시 폐기한다.
- 모든 수집기는 HTTP 200뿐 아니라 최소 내용 길이, 필수 필드 비율, 고유 코드 수,
  cursor 연속성을 검사하고 `ok/degraded/skipped` 상태를 남긴다.

## 진행 현황과 확정 구현 순서

1. **완료 — 공식 계약 고정:** v1.2.4 snapshot, SHA-256 lock, 공식 read-only GET
   14개 allowlist와 계약 테스트.
2. **완료 — 뉴스 계약 회귀 수정:** 기사 본문 typed schema와 추출기,
   오프라인·라이브 품질 테스트.
3. **다음 — `market_snapshot`:** 랭킹 100, 시장지표, 환율, 거래정보,
   경제 이벤트를 typed 수집하고 기준시각 저장.
4. **그다음 — `signal_snapshot` → `signal_outcome`:** AI 생성시각·방향·현재 성과를
   고정하고 Toss 차트로 1시간·1일·5일 forward return 계산.
5. **후속 — `community_aggregate`:** 분당 댓글, 고유 작성자, 보유 표시,
   반응률만 수집하고 원문·식별값은 미저장.
6. **키 대기 — `official_market_adapter`:** OAuth 자격증명 설정 후 공식 14개 GET을
   primary로 전환하고 WTS 시세·차트와 live 비교.
7. **후순위:** 재무제표·공시·컨센서스 WTS XHR 추가 조사. WebSocket 역추적은
   공식 지원 전까지 보류.

모든 실행 결과는 사용자별 `storage/users/<username>/toss/` 아래에 저장하고 수집시각,
계약 버전, `ok/degraded/skipped` 상태를 함께 남긴다.

## 공식 계약과 출처

- 안내: <https://home.tossinvest.com/ko/open-api>
- 개발자 문서: <https://developers.tossinvest.com/docs>
- LLM 안내: <https://developers.tossinvest.com/llms.txt>
- canonical 계약: <https://openapi.tossinvest.com/openapi-docs/latest/openapi.json>
- 로컬 snapshot: `api-contracts/external/toss/openapi.json`
- hash lock·allowlist: `api-contracts/external/toss/lock.json`,
  `api-contracts/external/toss/read-only-operations.json`

## WTS 호스트 & 인증 모델

| 호스트 | 별칭 | 인증 | 용도 |
|---|---|---|---|
| `wts-info-api.tossinvest.com` | INFO | **혼합** — 공개 GET은 주로 UA만, 일부 대시보드 POST는 게스트 세션 | 시세·종목정보·차트·뉴스·AI시그널·랭킹 — 데이터 대부분 |
| `wts-cert-api.tossinvest.com` | CERT | **혼합** — 공개 GET은 무인증 200, 일부 대시보드 POST는 게스트 세션, 개인화·주문은 401 | 댓글·커뮤니티·경제캘린더·시장지표·(호가·잔고=인증필요) |
| `wts-api.tossinvest.com` | API | 게스트 세션 | init·서버시간·거래시간·로그인정보 |
| `wts-lc.tossinvest.com` · `sentry-public…` | — | — | 로깅/에러추적 — **무시** |

## 종목 식별자 규칙 (에이전트 필수)

- **국내**: `A`+6자리 (`A005930`). ISIN/guid는 `KR7005930003` — **커뮤니티·댓글 API는 ISIN을 subjectId로 사용**.
- **해외**: `US-{심볼}`(`US-AAPL`) 또는 내부 productCode(`US20100311002`, `NAS…`, `AMX…`). 차트는 `us-s` 경로.
- 거래소 필드: `marketCode`(KSP=코스피 등), `nxtSupported`(넥스트레이드 대체거래소 지원 여부).

## 1. 검색·식별

| 용도 | 호출 | 검증 |
|---|---|---|
| 자동완성 검색 | `POST /api/v3/search-all/wts-auto-complete` [INFO] body `{"query":"삼성","size":10}` | ✅ 200 (GET·타호스트는 400/403/405) |
| 코드/심볼 → 종목 해소 | `GET /api/v2/stock-infos/code-or-symbol/{A코드\|US-심볼}` [INFO] | ✅ |
| 다건 종목 메타 배치 | `GET /api/v1/stock-infos?codes=c1,c2,…` [INFO] | ✅ |
| 종목 기본메타 | `GET /api/v1/stock-detail/ui/A{code}/common` [INFO] — 상장일·marketCode·NXT지원·tradingSuspended | ✅ |
| 종목 헤더 | `GET /api/v1/stock-infos/header/A{code}` [INFO] | ✅ |
| 뱃지 | `GET /api/v1/stock-infos/A{code}/wts-badges` [INFO] | ✅ |

## 2. 시세 (실시간 스냅샷 — 폴링)

| 용도 | 호출 | 검증 |
|---|---|---|
| 현재가 | `GET /api/v3/stock-prices?meta=true&productCodes=A005930` [INFO] | ✅ |
| 상세 시세 | `GET /api/v3/stock-prices/details?productCodes=A005930` [INFO] | ✅ **OHLC·52주고저·시총·체결강도·상/하한가·전일거래량·통화** |
| 다건 시세 | `GET /api/v1/product/stock-prices?meta=true&productCodes=…` [INFO] | ✅ |
| 체결 틱 | `GET /api/v2/stock-prices/A{code}/ticks?viewType=krx_all&count=120&investMode=krx` [INFO] | ✅ |
| 상/하한가 | `GET /api/v2/stock-prices/A{code}/upper-lower` [INFO] | ✅ |
| **호가(orderbook)** | `GET /api/v3/trading/order/A{code}/order-book` [CERT] | ⚠️ **401 — 로그인 필수** |

> 진짜 실시간 스트리밍은 **WebSocket**으로 추정(playwright 캡처엔 안 잡힘 — 지연·인증 연결). read-only 에이전트는 위 REST 스냅샷을 수 초 간격 폴링으로 대체.

## 3. 차트

| 용도 | 호출 | 검증 |
|---|---|---|
| 국내 일봉 | `GET /api/v1/c-chart/kr-s/A{code}/day:1?count≤300&investMode=krx&useAdjustedRate=true` [INFO] | ✅ |
| 국내 분봉 | `GET /api/v1/c-chart/kr-s/A{code}/min:1?count&from={ISO KST}&useAdjustedRate=true` [INFO] | ✅ |
| 해외 일봉 | `GET /api/v1/c-chart/us-s/{US코드}/day:1?count=61&session=all&investMode=krx&useAdjustedRate=true` [INFO] | ✅ |

페이지네이션: `nextDateTime` 커서, 최신→과거 정렬. 주봉 `week:1`/월봉 `month:1` 추정(미검증).

## 4. 종목정보·재무·지표

| 용도 | 호출 | 검증 |
|---|---|---|
| 종목 개요 | `GET /api/v2/stock-infos/A{code}/overview` [INFO] | ✅ |
| 투자 정보(52주 고저·거래량) | `GET /api/v2/stock-infos/A{code}/investment` [INFO] | ✅ |
| 투자 지표(PER/PBR/PSR/EPS/BPS) | `GET /api/v1/stock-detail/ui/wts/A{code}/investment-indicators` [INFO] | ✅ |
| 배당 이력 | `GET /api/v1/stock-infos/dividend/A{code}/summary` [INFO] | ✅ (7KB) |
| 위험 신호 | `GET /api/v1/stock-infos/A{code}/red-flags` [CERT] | ✅ (삼전=빈 배열) |
| **재무제표·공시·컨센서스(목표주가)** | 미확정 | ❌ 추측 경로 전부 404 — **추가 캡처 필요**(종목정보 하위탭 클릭이 안 잡힘). 재무는 investment-indicators로 일부 대체 |

## 5. 수급·거래동향

| 용도 | 호출 | 검증 |
|---|---|---|
| 투자자별 수급(개인/외국인/기관) | `GET /api/v1/stock-infos/trade/trend/trading-trend?productCode=A{code}&size=60&number=P&key=K` [INFO] | ✅ |
| 프로그램 매매 | `GET /api/v1/stock-infos/trade/trend/program-trading?productCode=A{code}&…` [INFO] | ✅ |
| 거래창구 상위 | `GET /api/v1/mds/broker/trading-ranking?code=A{code}` [INFO] | ✅ (JP모간 등) |
| 거래 분석 | `GET /api/v1/trading/analysis/productCode/A{code}` [CERT] | ⚠️ 200이나 `result:null`(개인화 추정) |

페이지네이션: 응답 `pagingParam{number,size,key}` — key는 날짜 커서.

## 6. 뉴스

| 용도 | 호출 | 검증 |
|---|---|---|
| 피드 4탭 | `POST /api/v1/dashboard/wts/news` [INFO] body `{"type":<TYPE>,"indexCode":null}` | ✅ |
| 회사별 뉴스 | `GET /api/v2/news/companies/{6자리}?size=20&orderBy=latest` [INFO] | ✅ |
| 기사 본문 전문 | `GET /api/v2/news/{newsId}` [INFO] (목록 contentText는 103자 프리뷰) | ✅ 2026-07-21 응답은 `result.kr.content[]` 블록 구조 |

TYPE enum: `ALL_HIGHLIGHT`(주요)·`HOT`(최신)·`SOARING_STOCK`(급상승)·`PERSONALIZED`(인기)·`PERSONALIZE_HOLD`/`PERSONALIZE_WATCH`(로그인)·`INDEX`(지수).

> 2026-07-21 품질 실측: 4탭 합계 102회 노출 / 고유 기사 94건 / 교차 탭 8건,
> 요약 길이 중앙값 300자. 회사 뉴스 상세 스키마가 `result.kr.content[]`로 바뀌어
> 기존 `contentText` 추출기가 103자 프리뷰만 유지하던 회귀를 수정했다.

## 7. AI 시그널·요약 ⭐ (토스증권 AI 콘텐츠)

| 용도 | 호출 | 검증 |
|---|---|---|
| 종목 AI 시그널 상세 | `GET /api/v1/dashboard/wts/overview/ai-signals/detail?productCode=A{code}&productType=STOCKS` [INFO] | ✅ **방향(1/-1)·사유("미국 반도체 훈풍")·손익률** |
| 다건 시그널 요약 | `POST /api/v1/dashboard/wts/overview/ai-signals` [INFO] body `{"productCodes":["A005930"]}` | ✅ `reasoningDescription` |
| 시그널(대시보드) | `POST /api/v2/dashboard/wts/overview/signals` [INFO] | ✅ **게스트 세션에서 200** · UA 직접 호출은 400 |
| AI 시그널 관심 카드 | `GET /api/v2/reasoning-contents/interest` [INFO] | ✅ "토스증권 AI 시그널" 종목별 이슈·키워드 |
| 인텔리전스 전체 | `POST /api/v1/dashboard/intelligences/all` [INFO] | ✅ **게스트 세션에서 200** |

> 2026-07-21 품질 표본: 대시보드 배치 56~57종목, 개별 상세 12/12건 200,
> 방향 11 positive / 1 negative, `profitLossRate` 12/12 존재. 반면 근거 데이터 배열은
> 0/12로 비어 있었다. 따라서 AI 시그널은 사실 근거가 아니라 **2차 심리·모멘텀 신호**로만
> 사용하고, 생성 시점 이후 수익률을 별도 검증한다.

## 8. 커뮤니티·댓글 (⚠️ subjectId=ISIN)

| 용도 | 호출 | 검증 |
|---|---|---|
| 종목 토론 댓글 | `GET /api/v4/comments?subjectType=STOCK&subjectId={ISIN}&commentSortType={POPULAR\|RECENT}` [CERT] | ✅ 닉네임·본문·프로필 |
| 관련 게시판 | `GET /api/v1/boards/STOCK/{ISIN}/related` [CERT] | ✅ |
| 추천 프로필 | `GET /api/v1/community/board/{ISIN}/recommend-profiles` [CERT] | ✅ |
| 수익률 랭킹 | `GET /api/v1/community/top-rankings/TOP_10_PROFIT_ROSS_AMOUNT` [CERT] | ✅ |

댓글 페이지네이션: 응답 `key`는 마지막 `commentId`와 같으며 다음 요청의
`lastCommentId={key}`로 전달한다. `size`는 실측상 무시되고 페이지당 11건이다.
원문·닉네임·프로필 ID는 저장하지 않고 댓글 속도·고유 작성자·좋아요·답글·보유상태 등
집계치만 사용한다.

## 9. 랭킹·탐색

| 용도 | 호출 | 검증 |
|---|---|---|
| 실시간 인기/거래 종목 | `GET /api/v1/rankings/realtime/stock?size=10` [INFO] | ✅ |
| 대시보드 랭킹 | `POST /api/v2/dashboard/wts/overview/ranking` [CERT] | ✅ **게스트 세션에서 200** · UA 직접 호출은 400 |

## 10. 시장 지표 (지수·환율·캘린더)

| 용도 | 호출 | 검증 |
|---|---|---|
| 지수 시세 | `GET /api/v1/index-prices/{지수코드 예:COMP.NAI}` [INFO] | ✅ |
| 환율 | `GET /api/v1/dashboard/wts/overview/exchange-rates` [INFO] | ✅ |
| USD 기준환율 | `GET /api/v1/exchange/usd/base-exchange-rate` [API] | ✅ |
| 시장 지표 | `GET /api/v4/dashboard/wts/overview/indicator` [CERT] | ✅ |
| 지수 지표 | `GET /api/v1/dashboard/wts/overview/indicator/index?market=us` [CERT] | ✅ |
| 거래 정보 | `GET /api/v1/dashboard/wts/overview/trading-info` [INFO] | ✅ |
| **경제·실적 캘린더** | `GET /api/v2/dashboard/wts/overview/calendar/economic-events` [CERT] | ✅ 금통위·실업수당 등 일정 |

## 11. 시스템/세션

| 용도 | 호출 |
|---|---|
| 서버 시간 | `GET /api/v1/time` [API] |
| 장 운영시간(통합) | `GET /api/v2/system/trading-hours/integrated` [API] |
| 세션 init | `GET /api/v3/init?tabId=…` [API] |
| 게스트 세션 등록 | `POST /api/v1/tuba/wts/guests/upsert` [API] |
| 로그인 정보(게스트) | `POST /api/v3/login/wts/toss/login-info` [API] |
| 커미션 무료 타깃 여부 | `GET /api/v1/tuba/wts/distributions/is-target/by-device-id?code=…` [API] |

## 운영 수칙 (실측 안정치)

- 요청 간격 30~50ms · 동시 10~20 · 429 시 백오프 2→4→6s.
- 반드시 브라우저형 `User-Agent` 헤더. 공개 GET은 대부분 이 조건만으로 호출된다.
- 일부 대시보드 POST는 공개 WTS의 게스트 초기화 흐름이 발급하는 `browser-tab-id`,
  `app-version`, `x-xsrf-token`이 필요하다. 2026-07-21 실측에서 헤더 없는 직접 호출은 400,
  게스트 웹앱 호출은 200이었다. 계정 로그인이 아니라 공개 게스트 세션까지만 허용한다.
- **개인화·주문·호가·잔고는 로그인 세션이 필요(401)** → read-only 에이전트는 스킵.
- 비공개 API라 스키마·경로가 바뀔 수 있음 → 파서에 방어 코드.

## 에이전트 수집 파이프라인 권장 (하루종일 탐색용)

1. **유니버스**: `rankings/realtime/stock` + 뉴스 피드 4탭 → 관심 종목 코드 수집.
2. **종목별 팬아웃**(코드당): 시세(`stock-prices/details`) · AI시그널(`ai-signals/detail`) · 수급(`trading-trend`) · 지표(`investment-indicators`) · 배당 · 뉴스(`news/companies`) · 댓글(`comments`, ISIN 변환).
3. **시장 컨텍스트**: 지수·환율·경제캘린더는 1일 1~수회.
4. **차트**: 필요 시 일봉/분봉 커서 페이지네이션.
5. Sonnet은 위 결정적 수집 결과(JSON)를 받아 **요약·해석만** — 수집기 자체에 LLM 콜 없음(순수 deterministic).

## 미해결 / TODO
- 재무제표·공시·컨센서스(목표주가) 엔드포인트 미발견 — 종목 상세의 "종목정보" 하위탭을 실제로 클릭시키는 캡처 재시도 필요(getByText 클릭이 안 먹음).
- 실시간 WebSocket(호가·체결 스트림) URL·프로토콜 미확인.
- `search-all/wts-auto-complete`는 200이나 실측 `result:[]` — 정확한 body 필드(예: 지역/타입) 추가 확인 필요.

## ⚖️ 합법성·ToS
비공개 내부 API. 개인 리서치·읽기 수집엔 실무상 쓰이나 **토스 이용약관상 자동수집을 명시 허용하지 않음** — 상업적/대량 배포·재판매는 리스크. 레이트리밋 준수, 로그인 우회·주문 API 접근 금지 원칙.
