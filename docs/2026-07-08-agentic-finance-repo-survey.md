# 금융 에이전틱 오픈소스 서베이 — 질문 라우팅·블록 조합 관점 (2026-07-08)

> 목적: QA 엔진의 단일 고정 워크플로우를 "질문 유형별 라우팅 + 블록 조합형"으로 개선하기 위한 레퍼런스 조사.
> 방법: deep-research 워크플로우 (검색 각도 5개 병렬 → 소스 22개 수집 → claim 110개 추출 → 25개 표본 3표 적대 검증, 24 확정 / 1 반박).
> 모든 repo 상태(HEAD·릴리스·활성도)는 2026-07-08 웹 검증 기준.

## TL;DR — 세 문장 요약

1. **"질문 유형을 분류해서 다른 파이프라인으로 보내는" 설계를 실제로 구현한 금융 repo는 거의 없다.** 조사한 활성 repo 전부가 입력을 티커+날짜로 고정한 단일 트레이딩 워크플로우다 — 즉 우리가 하려는 건 흔한 걸 베끼는 게 아니라 앞서가는 것.
2. 대신 주류 패턴은 셋: **(a) 고정 뼈대 + 블록 멤버십만 가변** (TradingAgents·ai-hedge-fund의 애널리스트 레지스트리), **(b) 플래너가 실행 중 다음 에이전트를 고르는 동적 위임** (LangAlpha·FinRobot Desktop), **(c) 명시적 의도 분류기로 도구 페이로드를 제한** (학술: Agentic GraphRAG 논문).
3. 종합 권고: **앞단에 구조화 출력 분류기(Pydantic `Literal`) → 유형별로 수집·검증 블록 서브셋 선택, 단 claim 조립→계산→검증 "스파인"은 고정** — 조사된 모든 활성 시스템이 자유 DAG 합성이 아닌 이 보수적 조합을 택했다.

---

## 1. repo별 상세

### 1.1 TradingAgents (TauricResearch) — 계층 파이프라인 + 토론 검증 [신뢰도: 높음, 3-0]

- **구조**: LangGraph 기반. 애널리스트 팀(펀더멘털/센티먼트/뉴스/기술) → bull/bear 리서처 구조화 토론 → 트레이더 → 리스크 관리(공격/중립/보수 3관점 토론) → 포트폴리오 매니저. HEAD 01477f9 (2026-07-05) 직접 검증.
- **질문 라우팅**: **없음.** 입력은 티커+날짜 고정. 코드에서 유일한 "route"는 데이터 벤더 폴백(`route_to_vendor`). 조건부 엣지는 도구 호출 루프·토론 라운드 지속 판단에만 사용.
- **조합성**: `build_analyst_execution_plan(selected_analysts)` — 4개 고정 `AnalystNodeSpec` 레지스트리에서 서브셋을 골라 조립. 하류 위상(토론→트레이더→리스크)은 고정. 라우팅은 질문 유형이 아니라 **태스크 난이도→모델 티어** (요약·검색은 경량 모델, 결정·리포트는 딥싱킹 모델) 수준.
- **통신**: 자연어 대화가 아닌 **구조화 리포트 + 전역 상태(global state)** 가 기본, 자연어는 토론에서만. "긴 대화 전달 중 정보 소실(telephone effect)" 방지 목적 — 우리 ASSEMBLER/claim table과 같은 문제의식.
- **검증/리플렉션**: 두 층. ① 실행 중 — 적대적 토론 + facilitator 판정 (단, **검증 실패→재수집 되돌림 엣지는 없음**, 그래프 선형). ② 실행 간 — 결정을 로그에 남기고 다음 실행 때 실현 수익률(SPY 대비 알파 포함)을 조회해 리플렉션 생성, 같은 종목 5건+교차 종목 3건 교훈을 PM 프롬프트에 주입하는 **결과 기반 사후 학습 루프** (`~/.tradingagents/memory/trading_memory.md`).

### 1.2 ai-hedge-fund (virattt) — 병렬 팬아웃 + 레지스트리 [신뢰도: 높음, 3-0]

- **구조**: LangGraph StateGraph. start → 선택된 애널리스트들 **병렬 실행** → risk_management → portfolio_manager → END. main 2026-07-08 확인.
- **질문 라우팅**: 없음 (`add_conditional_edges` 부재).
- **조합성**: `ANALYST_CONFIG` 중앙 레지스트리 (버핏·그레이엄·다모다란 등 페르소나 + 기술/펀더멘털 애널리스트). 호출자가 `selected_analysts` 서브셋 지정 → 그 노드만으로 그래프 구성, 미지정 시 전체. 코드 주석 "`# Always add risk and portfolio management`" — **수렴 지점은 항상 고정**.
- **패턴명**: "위상 고정 + 노드 멤버십 가변" — 우리 DISPATCH 3브랜치 구조와 가장 유사.

### 1.3 FinRobot Desktop (AI4Finance) — Lead Agent 라우팅 표방 [신뢰도: 중간 — README 자기서술]

- v0.1.0 (2026-07-07 릴리스). 조사 대상 중 유일하게 "리드 에이전트가 태스크 유형별로 파이프라인을 골라 라우팅"을 표방: Lead Agent 1 + 파이프라인 서브에이전트 5(Data→Analysis→Modeling→Synthesis→Report) + 토론 에이전트 3(bull/bear/judge)로 7개 파이프라인(기업 리서치·DCF·comps·LBO·DDM·실적·IC 메모) 커버.
- ⚠ 코드 수준 라우팅 동작은 미검증 (README 기반). 구 논문의 "Smart Scheduler/Director Agent" 설계는 현 코드에 없음 (**0-3 반박** — 구 논문과 현 코드베이스는 다른 시스템).

### 1.4 LangAlpha (Chen-zexi) — planner-composed 라우팅 [신뢰도: 높음, 단 deprecated]

- **구조**: 정적 엣지는 START→coordinator 하나뿐. coordinator(인사말 vs 본 처리 이진 분기) → planner가 질문을 Step 리스트(태스크·담당 에이전트)로 분해 → **supervisor가 구조화 출력 Router로 실행 중 다음 에이전트(researcher/market/browser/analyst/coder/reporter)를 동적 선택** (`Command(goto=response.next)`), 반복·정제 허용.
- **핵심 반면교사**: `ticker_type: Literal["company","market","multiple","ETF","compare"]` 분류기가 **있는데도 파이프라인 분기에 안 쓰고 프롬프트 컨텍스트로만 사용** — "분류만 하고 라우팅에 안 쓰는" 함정의 실제 사례. (우리 tier 0-4가 정확히 같은 상태.)
- 226 stars, 2026-03-26 공식 deprecated. 후속 ginlix-ai/LangAlpha ("Claude Code for Investing")는 미조사.

### 1.5 Agentic GraphRAG (arXiv 2605.18770, ETH Zurich 2026-04) — 가장 명시적인 의도 라우팅 [신뢰도: 높음, 단 논문]

조사 전체에서 "질문 유형 분류 → 파이프라인 차등"을 가장 명시적으로 구현한 사례. 셋 다 원문 축어 검증:

1. **Zero-shot intent router** — 질의를 5개 의도(search_companies/explore_network/get_node_history/analytics/all_tools)로 분류해 **메인 에이전트에 주입되는 도구 페이로드를 동적으로 제한**. 근거는 tool overload 방지 (매크로 집계 질문엔 탐색 도구 차단). 애매하면 all_tools 폴백.
2. **제한 리플렉션 루프 (최대 4회)** — 각 반복이 직전 도구 결과에 조건화. 실패 시 백엔드가 **결정론적 절차 피드백** ("그래프 조회 실패 → 전문 검색 폴백 제안" 같은 다음 유효 복구 단계)을 주입해 처음부터 재시작하지 않음.
3. **5상태 결정론적 FSM** (S0 명확화~S4 심층 검색)이 실행 트레이스·대화 이력을 검사해 합성 호출을 제약 — LLM이 아닌 규칙 기반 멀티턴 제어층.

⚠ GitHub repo가 아닌 단일 논문. 공개 구현체 존재 여부 미확인.

### 1.6 LangGraph 공식 패턴 3종 [신뢰도: 높음]

1. **Routing**: LLM이 Pydantic `Literal` 구조화 출력으로 분류 → conditional edge가 `state["decision"]` 읽어 분기. 우리 유형 라우팅에 그대로 치환 가능한 표준형.
2. **Orchestrator-worker (Send API)**: 실행 시점에 워커 수를 동적 생성. 단 노드 타입 집합은 정적 — "사전 선언 레지스트리 위 동적 팬아웃"이지 임의 DAG 합성이 아님.
3. **Plan-and-Execute**: planner→agent→replan 3노드 루프. 단 계획이 DAG가 아닌 `List[str]` 순차 실행 — 노트북 스스로 "DAG로 개선 여지(LLMCompiler 방향)" 한계 명시.

### 1.7 학술 분류 (arXiv 2408.06361v2) [신뢰도: 중간 — 유추 적용]

금융 LLM 에이전트를 "LLM as Trader"(직접 매매 결정: news/reflection/debate/RL-driven 하위분류)와 "LLM as Alpha Miner"(writer+judge 이중 루프)로 이분 — 태스크 성격에 따라 파이프라인 구조 자체가 달라진다는 방증. 질문 라우팅 분류는 아니므로 유추 적용.

---

## 2. 종합 권고 — 우리 엔진에의 적용 [검증 findings 교차 종합]

1. **라우팅**: 앞단에 `Literal` 기반 구조화 출력 분류기 (예: `question_type: Literal["fact_lookup","event_interpretation","stock_judgment","industry_analysis","strategy"]`). 분류 결과가 파이프라인 전체를 갈아끼우기보다 **수집 블록·도구 페이로드 서브셋을 제한**하는 GraphRAG 방식이 실증된 최소 변경 경로. **LangAlpha처럼 분류만 하고 안 쓰는 함정 주의** (현행 tier가 이 상태).
2. **조합**: 조사된 모든 활성 repo가 자유 DAG 합성이 아닌 **중앙 블록 레지스트리 + 고정 스파인(수렴 지점 고정) + 멤버십 가변**을 채택. 우리도 수집 블록을 레지스트리화하고 ASSEMBLE→CALC→VERIFY 스파인은 고정 유지가 안전. 동적 팬아웃이 필요해지면 Send API 패턴.
3. **검증**: 우리의 재조사(REFLECT) 루프는 조사 대상 대부분에 **없는 강점** — 유지. 추가할 것: ① GraphRAG의 **결정론적 절차 피드백** (게이트 실패 시 실패 사유 + 다음 유효 복구 단계를 코드가 제안) + 반복 상한, ② TradingAgents의 **결과 기반 사후 리플렉션** (예측형 질문의 실현 결과를 로그→다음 답변 프롬프트에 교훈 주입). ③ 산업 분석·판단형에는 bull/bear+judge **토론 블록**이 유형별 차별화 포인트.

## 3. 커버리지 공백·주의사항

- FinGPT, OpenBB(+copilot), FinMem, FinAgent, StockAgent: 검증 통과 claim 없음 → 리포트 제외 (조사 실패인지 관련성 부족인지 불명). 특히 OpenBB copilot은 실사용 QA 제품이라 라우팅이 있을 가능성 — 후속 조사 후보.
- FinRobot: README 자기서술 기반, 코드 라우팅 미검증.
- Agentic GraphRAG: 논문만, 구현체 미확인. 5개 의도 분류의 오분류율/all_tools 폴백 비중 실측치 미확인.
- LangAlpha: deprecated — 코드 패턴 참고용. 후속 ginlix-ai/LangAlpha 미조사.
- 열린 질문: LangAlpha가 ticker_type 분류를 분기에 안 쓴 이유 (실패한 시도였나, 미완성이었나)?

## 4. 조사 통계

각도 5 · 소스 22 · claim 추출 110 · 검증 표본 25 (확정 24, 반박 1) · 합성 후 findings 11 · 에이전트 콜 104.
