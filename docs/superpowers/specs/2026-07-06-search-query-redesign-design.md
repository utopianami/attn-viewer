# 검색 쿼리 재설계 + Sonnet 뉴스 요약 스테이지

날짜: 2026-07-06
상태: 사용자 설계 승인 완료 ("진행해, 보강 무조건")

## 배경 (실사고 케이스)

yvon의 2026-07-06 피드백(👎 "뉴스가 너무 관련없느데"): 유럽 전력주 질문에
뉴스 패널 12건 중 8건이 무관 — 국내 반도체 기사, 루리웹/에펨코리아 게시글
("보지냐 골키퍼...", "유럽 퍼킹 코리안들아...") 포함. 원인 3가지:

1. `engine/tools/news/brave.py:23` — 모든 검색이 `country=kr, search_lang=ko` 하드코딩.
2. `_x_unit`(`engine/stages/ra_external.py:163-169`) — 질문 **원문**(구어체 장문)을
   그대로 쿼리로 사용 + `freshness=pd`(당일만).
3. 도메인 필터·URL 중복 제거 없음 + `orchestrator.py:177-182`가 큐레이션 전
   raw 풀을 UI `ra_x` 레이어로 방출.

## 결정 사항

- **쿼리 설계는 플래너 주도** (사용자 선택): plan 1콜을 확장, 검색 시점 재작성 콜 없음.
- **Sonnet 요약은 패널 + 합성 둘 다** (사용자 선택).

## 설계

### 1. 플랜 확장 — market_scope + 시장 언어 검색어

- `PlanPacket`에 `market_scope: Literal["kr", "global", "mixed"] = "kr"` 추가
  (`engine/contracts/packets.py`).
- `engine/stages/plan.py` 프롬프트 확장:
  - market_scope 판정 기준: 질문 대상 자산·시장의 소재지 (한국 종목=kr,
    해외 종목/시장=global, 혼합 비교=mixed).
  - `search_queries`(q0 + 서브질문): global이면 **영어** 검색어,
    kr이면 한국어, mixed면 영어+한국어 병행(유닛당 2~3개 내 배분).
  - 기존 규칙 유지: 구어체 제거, 종목 정식명+연도.
- LLM 콜 수 변화 없음.

### 2. 검색기 수정

- `engine/tools/news/brave.py`: `news_search`/`web_search`에
  `country: str | None`, `search_lang: str | None` 파라미터 추가, kr 하드코딩 제거.
  - kr scope → `country=kr, search_lang=ko` (기존과 동일)
  - global → `country=us, search_lang=en`
  - mixed → 쿼리 언어별로 위 둘 중 선택 (간단 판정: 쿼리에 한글 포함 여부)
- `tavily.py` 폴백: 쿼리 언어 그대로 전달 (tavily는 언어 파라미터 불필요,
  변경 없음 확인만).
- `_x_unit`: 질문 원문 대신 **해당 유닛의 search_queries[0]** 사용
  (없으면 질문 원문 폴백). `freshness` pd → pw (archive 모드는 기존 pm 유지).
- 수집 직후 공통 후처리 (`ra_external.py` 신규 헬퍼 `_clean_pool`):
  - 커뮤니티 도메인 블록리스트: ruliweb.com, fmkorea.com, dcinside.com,
    theqoo.net, clien.net, bobaedream.co.kr, instiz.net, mlbpark.donga.com,
    humoruniv.com, ppomppu.co.kr
  - URL 정규화(쿼리스트링 제거 후 소문자) 기준 중복 제거.
  - x_search·brave_news·web_knowledge 풀 모두에 적용.

### 3. Sonnet 뉴스 요약 스테이지 (신규 역할 `news_summary`)

- `engine/app/settings.py`: `model_claude_sonnet: str = "claude-sonnet-4-6"`.
- `engine/providers.py`:
  - ROLE_MAP에 `"news_summary": [("anthropic", settings.model_claude_sonnet, "low"),
    ("openai", settings.model_gpt_mini, "low")]`.
  - `_PRICE_PER_M`에 `"anthropic_sonnet": (3.0, 15.0)` 버킷 추가
    (2026-07-06 공식 단가 검증) + `CostMeter.add`의 버킷 판정에 sonnet 분기.
- 위치: `curate_evidence` **통과분** 뉴스(제목+발췌, 유닛 질문 포함)를 입력으로
  질문 관점 요약 생성 — 유닛별 핵심 3~6줄 + 각 줄에 출처 URL.
- 구조화 출력(pydantic): `{summary_lines: [{text, url}], as_of}`.
- 실패 시 degrade: 요약 없음 → 기존 경로 그대로 (never-block, collector_status에
  `news_summary: degraded` 기록).

### 4. 노출

- 새 레이어 `news_summary` (`engine/contracts/packets.py`의 레이어 이름 목록에 등록,
  `orchestrator.py`에서 방출) — UI 뉴스 패널 상단 표시.
- `ra_x` 레이어는 **큐레이션 통과분만** 방출하도록 수정 (직접 노출 버그 제거).
- `engine/stages/synthesize.py`: `[뉴스 요약]` 블록으로 요약을 합성 프롬프트에 투입
  (기존 `[시장 트렌드]` 블록과 별개).

### 5. 테스트 (두 층 — 수제 입력 + 실제 상류 출력)

- 수제 계약 테스트 (`engine/tests/`):
  - market_scope별 brave 파라미터 (kr/global/mixed → country/search_lang)
  - `_clean_pool`: 블록리스트 도메인 제거, URL 중복 제거
  - `_x_unit`이 search_queries 우선 사용
  - `news_summary` 스키마 검증 + 실패 시 degrade 경로
- 회귀 픽스처: 이번 실제 케이스의 ra_x 12건을 픽스처로 저장,
  `_clean_pool` 통과 후 커뮤니티 4건(루리웹 2, 펨코 중복 2)이 제거되는지 확인.

## 비용 영향

Sonnet 1콜/질문 (low effort, 입력 큐레이션 뉴스 ~3-6K 토큰) ≈ $0.01-0.03.
검색 노이즈 감소로 하류 extract/curation 입력은 오히려 감소.

## 비범위 (이번에 안 함)

- toss_trend/macro의 market_scope 조건부 주입 (별도 이슈 — 이번 피드백의
  직접 원인 아님이 확인됨)
- tavily 쪽 국가/언어 파라미터 최적화
