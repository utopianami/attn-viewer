# 토스증권 공식 Open API ↔ WTS 갭 분석

- 조사일: 2026-07-21
- 공식 계약: 토스증권 OpenAPI 3.1.0, API 버전 1.2.4
- 비교 대상: 공식 API 27개 path(30 operations), 이 중 계좌 비의존 read-only 시장 기능 14개 / WTS 내부 API 51개 호출 경로
- 원칙: 수집 데이터는 토스 안에서만 가져온다. 주문·잔고·로그인 우회는 범위 밖이다.

## 결론

토스만으로도 좋은 리서치 원천을 구성할 수 있다. 다만 하나의 API로 해결하는 구조가 아니라
아래 세 층을 합치는 구조가 적합하다.

1. **공식 Open API — 시장 뼈대:** 현재가, 호가, 체결, 상·하한가, 분봉/일봉,
   종목 마스터·유의사항, 환율, KR/US 장 캘린더, 랭킹, 지수·국채·투자자별 매매대금.
2. **WTS 내부 API — 해석 재료:** 상세 시세, PER/PBR/PSR/EPS/BPS, 배당,
   종목별 개인/외국인/기관 수급, 프로그램 매매, 거래창구, 뉴스 전문, AI 시그널,
   커뮤니티, 경제 캘린더.
3. **결정적 파생층:** 위 JSON에서 수익률·수급 변화·뉴스 중복도·시그널 성과를 코드로 계산한다.
   LLM은 수집과 숫자 계산이 아니라 마지막 요약·해석에만 사용한다.

## 채택 규칙

- 공식 API와 WTS가 겹치면 **공식 API가 primary**, WTS는 fallback 또는 추가 필드 보강이다.
- 공식 API에 없는 뉴스·재무지표·종목 수급·AI·커뮤니티는 **WTS가 primary**다.
- 계좌·보유자산·주문·조건주문은 호출하지 않는다.
- 공식 API는 OAuth 2.0 토큰이 필요하다. 현재 실행 환경에는 client id/secret이 설정되어 있지
  않으므로 계약 분석은 가능하지만 live 비교는 키 설정 뒤 진행한다.
- WTS 내부 API는 비공개이므로 응답 fixture, 방어적 파서, schema drift 검사가 필수다.
- 일부 WTS 대시보드 POST는 공개 게스트 세션 헤더가 필요하다. UA-only 호출과 게스트
  세션 호출을 같은 인증 등급으로 취급하지 않는다.

## 영역별 소스 결정

| 영역 | 공식 Open API | WTS 내부 API | 현재 구현 | 결정 |
|---|---|---|---|---|
| 검색·식별 | 알고 있는 symbol의 종목 기본 정보 | 자동완성, 코드/심볼 해소, 메타·헤더·뱃지 | 없음 | **WTS로 발견 → 공식으로 검증** |
| 시세·호가·체결 | prices, orderbook, trades, price-limits | 현재가·상세시세·틱·상하한가, 내부 호가는 로그인 필요 | 미구현 | **공식 primary**, WTS 상세 필드/fallback |
| 차트 | KR/US 1분봉·일봉, 최대 200, before 커서 | 국내 일/분봉, 해외 일봉, 최대 300, nextDateTime | 국내 일/분봉 | **공식 primary**, WTS 보강 |
| 종목정보·재무 | 종목 기본정보, 매수 유의사항 | overview, 투자정보, PER/PBR/PSR/EPS/BPS, 배당, red flags | 대부분 구현, 일부 raw | **WTS primary**, typed schema 보강 |
| 수급·거래동향 | 코스피/코스닥 투자자별 매매대금 | 종목별 개인/외국인/기관, 프로그램, 거래창구 | 종목 수급·창구 | **WTS primary**, 공식 지수 수급 결합 |
| 뉴스 | 없음 | 피드 4탭, 회사별 뉴스, 기사 전문 | 구현 | **WTS primary** |
| AI 시그널 | 없음 | 상세·다건·대시보드·관심 카드·인텔리전스 | 미구현 | **다음 확장 후보** |
| 커뮤니티 | 없음 | 댓글, 게시판, 추천 프로필, 수익률 랭킹 | 미구현 | WTS 전용, 품질·개인정보 게이트 뒤 사용 |
| 랭킹·탐색 | 시장/토스체결 기준 랭킹 | 실시간 인기·대시보드 랭킹 | 미구현 | **둘 다 수집** — 시장행동과 관심도 분리 |
| 시장 컨텍스트 | 환율, KR/US 캘린더, 지수·국채 | 환율, 지수, 거래정보, 경제 캘린더 | 미구현 | 공식 시장축 + WTS 이벤트축 결합 |
| 세션·계좌 | OAuth, 계좌·보유·주문 | guest init, 로그인·개인화 경로 | INFO 무인증만 사용 | **계좌/주문 전부 제외** |
| 재무제표·공시·컨센서스 | 없음 | 경로 미발견 | 없음 | WTS XHR 추가 조사 대상 |

## 현재 코드와 계약의 갭

- `engine/tools/toss/`가 직접 사용하는 WTS 경로는 12개다.
- live smoke는 피드, 회사 번들, 국내 일봉의 3개 흐름만 검증한다. 국내 분봉은 live 테스트가 없다.
- `investment-indicators`, `dividend`, `red_flags`는 일부 raw dict로 전달되어 필드 계약과
  drift 탐지가 약하다.
- 클라이언트는 INFO 호스트 하나만 지원한다. CERT/API 공개 데이터와 공식 Open API는 별도
  base URL·인증 정책이 필요하다.
- 공식 OpenAPI는 계약이 완비되어 있으므로 이 계약에서 read-only client를 생성하고,
  WTS만 수동 계약으로 보완하는 편이 맞다.
- 2026-07-21 작업에서 공식 v1.2.4 snapshot·SHA-256 lock·14개 GET allowlist와 계약
  테스트를 추가했다.
- 회사 뉴스 상세의 신형 `result.kr.content[]` 계약과 추출기·오프라인/라이브 테스트를
  추가해 103자 프리뷰 회귀를 수정했다.
- 소스별 실측 품질과 사용 등급은 [토스 데이터 소스 품질 감사](./toss-source-quality-audit.md)에
  고정했다.

## 순차 실행안

1. **완료** — 공식 OpenAPI 버전·해시 고정, read-only 14개 기능 allowlist·계약 테스트.
2. **진행** — WTS 뉴스 상세 typed 계약 완료. 나머지 현재 경로 fixture·schema 강화.
3. **대기** — 공식 API 키 설정 뒤 공식↔WTS 시세·차트 live 비교.
4. **다음 구현** — 로그인 없이 가능한 랭킹·시장지표·환율·경제일정 typed 수집기.
5. **그다음** — AI 시그널 snapshot + 생성시각 가격 + 1시간·1일·5일 forward return.
6. **정책 완료/구현 대기** — 커뮤니티 원문·작성자 미저장, 시간 버킷 집계만 수집.
7. **후순위** — 재무제표·공시·컨센서스 WTS XHR 추가 조사.
8. **보류** — WebSocket은 공식 지원 전까지 역추적하지 않는다.

## 확정 구현 순서

1. `market_snapshot`: 실시간 랭킹 100, 시장지표, 환율, 거래정보, 경제 이벤트.
2. `signal_snapshot`: AI 배치·상세·생성시각·방향·현재 성과를 원본 시각과 함께 저장.
3. `signal_outcome`: Toss 차트만 사용해 1시간·1일·5일 forward return 계산.
4. `community_aggregate`: 종목별 분당 댓글·고유 작성자·보유표시·반응률만 집계.
5. `official_market_adapter`: credential 설정 뒤 공식 14개 GET을 primary로 전환.
6. 모든 런은 사용자별 `storage/users/<username>/toss/` 아래에 저장하고
   `ok/degraded/skipped`, 계약 버전, 수집시각을 남긴다.

## 공식 출처

- 안내: <https://home.tossinvest.com/ko/open-api>
- 개발자 문서: <https://developers.tossinvest.com/docs>
- LLM 안내: <https://developers.tossinvest.com/llms.txt>
- canonical 계약: <https://openapi.tossinvest.com/openapi-docs/latest/openapi.json>
