# ryze QA 엔진 구현 계획

- 날짜: 2026-07-02
- 목표: `attn.ngrok.app/#chat` 채팅에 다단계 검증 금융 QA 백엔드를 붙인다.
- 구조: attn-viewer(Node, 기존 유지) → Python 사이드카 `engine/` (FastAPI + Microsoft Agent Framework) → Claude/GPT/Grok API + 도구.
- 분류: **Agentic Workflow** (2026-07-02 확정) — 계획(PLAN)·도구 사용(RA-외부/PRICE/CALC)·반성(REFLECT)·멀티에이전트(생산자 GPT/실증자 Grok/심판 Fable) 4패턴 전부 보유. 검증 게이트(G0~G4)를 가진 멀티에이전트 리서치 파이프라인. ※ "Agentic RAG"는 부정확 — v1엔 자체 문서저장소(벡터 DB)가 없음, 라이브 소스(웹/X/토스) 우선이 설계 선택.
- 워크플로 상세 리뷰 문서: [`docs/workflow-review.html`](./workflow-review.html) — 스테이지별 승인/수정 리뷰용.
- 유래: 설계 패널(독립 설계 3안: pragmatist / contract-first / product-evolution → 심사 3인: 기술 정확성 / 답변 품질 / 유지보수성) 종합안.
  - 골격 = contract-first의 검증 아키텍처(typed 계약 + 코드 게이트)
  - 접합 = pragmatist의 최소 변경 통합(NDJSON, runChatAnswer 본문만 교체)
  - 확장성 = product-evolution의 WORKFLOWS 레지스트리 + CALC를 fan-in 뒤에 배치

## 확정 제약 (사용자 지시)

- v1은 **3사 모델 전부 사용** (providers 체크박스는 수신·기록만).
- thinkLevel(1-3) / depth(high/xhigh/max)는 **v1에서 무시** — 가장 잘 답하는 단일 워크플로 하나.
- **질문 분해 실행 · REFLECT 재조사 · tier 3 반대 시나리오(RISK)는 v1 포함** — 비용보다 답변 품질 우선 (2026-07-02 사용자 지시: 핵심 기능을 버전 뒤로 미루지 않는다).
- 코드 모듈화 필수 — 이후 모드 카탈로그(pulse/checklist/thesis/funnel 등) 확장 대비.
- API 키는 루트 `.env`에 등록 완료 (2026-07-02): `CLAUDE_API_KEY` / `OPENAI_API_KEY` / `XAI_API_KEY`.
  - ⚠ MAF `AnthropicClient`는 기본으로 `ANTHROPIC_API_KEY`를 찾음 → `settings.py`가 `CLAUDE_API_KEY`를 읽어 `api_key=`로 명시 전달할 것.
  - 뉴스 폴백 체인용 `BRAVE_API_KEY` / `TAVILY_API_KEY`도 등록 완료 (`~/longshot-wiki/tools/`에서 복사, 2026-07-02).
  - 주의: Tavily는 dev 키(무료 1K 크레딧/월), Brave는 유료 계정 — 폴백 순서상 Brave 우선이므로 실사용량 모니터링.
- 방향: **뉴스 우선(news-first)**, 내부 memory/raw(observe)는 보조·검증 레이어.

### 확정 제약 추가 (2026-07-02 후속 지시)

- **DA 배치 확정**: 전체 질문 유닛 = gpt-5.5·high + fable-5·think8k(이중 블라인드) / 각 서브질문 유닛 = gpt-5.5·high.
- **수집 정보 전량 보존**: 답변을 위해 수집한 모든 중간 산출물을 원본 그대로 저장한다 — 서브질문, 각 유닛 sub-answer, 뉴스 원문/요약, 트렌드, 매크로, 시세, claim table, verify 결과, 재조사 라운드. "나중에 쓸 일이 있음" (재분석·디버깅·평가셋). 저장 위치 = `ChatArtifacts.layers`(가공본) + `trace` layer에 raw evidence 전량(doc_id/URL/타임스탬프 포함). 잘라내지 않는다.
- **진행 중 중간 표시 (스트리밍 UX)**: 답변 생성 중 채팅창에 순서대로 노출한다 — ① 질문 분해(q1/q2/q3…) ② 각 q의 sub-answer ③ 뉴스(어떤 게 있는지) ④ 현재 트렌드 ⑤ 매크로 상황 → 마지막에 **[최종답변]**. 목적 = 디버깅 + 사용자가 진행 중임을 인지. layer가 완료되는 즉시 표시(폴링).
- **백그라운드 실행 + persistence**: 사용자가 질문 후 브라우저를 꺼도, 엔진은 백그라운드로 계속 돌고 결과를 채팅에 append한다. 다시 들어오면 완성된(또는 진행 중인) 답변이 달려 있다. 기존 attn-viewer 구조(202 Accepted + setImmediate 백그라운드 job + 파일 저장 + 폴링)가 이미 이걸 지원 — 엔진 job이 이 자리에 들어가고, 2차 리뷰의 "Node 부팅 시 running 스윕"은 크래시 복구용 보완.

---

## 1. 워크플로 설계

### 1.1 v1 그래프

```
QuestionInput
 → ① PLAN (병렬 2콜: fable-5·think4k 질문이해 ∥ 5.5-mini·low 기계추출+교차판정 → G0 코드 병합·검증):
    질문 재작성 · 종류 분류(tier 0-4) · event_time_range/knowledge_cutoff · 티커 후보
    · sub_questions(+depends_on, 0~5개) · 대조질의 · 필요증거 슬롯 · 검색쿼리 · richness 잠정
 → switch-case: tier==4(주문 요청) → ②′ BLOCKED ("실행 못 함" + 올바른 질문 안내) → 종료
 → ② DISPATCH (코드) — 유닛 목록 = [전체질문 + sub_questions]를 3개 브랜치에 전달
    무조건 fan-out (조건부 edge 금지). 수집 scope 3종:
    global(전체 질문당 1회 — 공통 컨텍스트) / unit(유닛별) / ticker(티커별)
    ├ ③a DA: 블라인드 독립 답변 — 무조건 실행, 도구 금지.
    │   전체 질문 유닛 = gpt-5.5·high + fable-5·think8k 이중 블라인드
    │     (deep-x Claude×Codex 계승 — 두 모델 불일치 = 집중 검증 신호)
    │   서브질문 유닛 = gpt-5.5·high
    │   유닛 프롬프트 = [전체 질문 + 서브질문 전체 목록] + "이 서브질문에 답하라"
    │   (전체 맥락을 파악한 상태로 유닛 답변 — 2026-07-02 지시)
    │   ※ G1 교차 채점: da_fable 출처 claim은 GPT가, 나머지는 Fable이 판정
    │     (자기 채점 방지 — 코드가 출처별 심판 라우팅)
    ├ ③b RA-외부 (외부 증거 수집 오케스트레이터) — 내부 병렬 수집기 4종:
    │   - x_search (grok-4, unit): X/웹 실시간 정보·반응. 자유텍스트만(구조화 금지),
    │     claim 추출은 5.5-mini. 폴백 grok→brave(freshness=pd)→tavily. news_mode 적용
    │   - web_knowledge (Brave/Tavily + 5.5-mini·low, unit): 배경지식·관행 웹서핑
    │     (예: 리밸런싱 질문 → 국내외 기관 리밸런싱 방식/일정/영향 수집)
    │   - toss_trend (코드 + 5.5-mini·low, global): 토스 feed/news 4탭 → 트렌드 합성 (하단)
    │   - toss_company (코드, ticker): 토스 stocks/{code}/news·analytics·transaction-status
    └ ③c PRICE·MACRO (코드, LLM 없음) — 3층 수집:
        ① global: 기본 매크로 세트 (KOSPI/KOSDAQ·S&P500·USD/KRW·미10년금리·WTI 등,
          Yahoo 심볼 결정적 수집, 세트는 settings)
        ② ticker: 질문 티커들의 시세 시계열 (Yahoo+universe_kospi)
        ③ unit별 추가 체크: 서브질문 전용 종목·needed_evidence의 price 슬롯
          (기간 시계열)·metrics 요구 기간 스캔 후 추가 수집 (2026-07-02 지시)
    ※ 내부 RA(observe 메모리/원문)는 v1 제외 — 2026-07-02 사용자 지시 "지금 하지 말 것".
      도구 자리만 유지, G1 근거는 외부 RA + CALC로 충당
    ※ 유닛/수집기 병렬은 브랜치 내부 asyncio.gather — 그래프는 3-브랜치 고정,
      fan-in 배리어 결정성 보존 (브랜치당 패킷 1개)
 → add_fan_in_edges (배리어: 3패킷 전부 도착)
 → ④ ASSEMBLER (순수 코드): 유닛별 claim + 통합 claim table·충돌표
    우선순위 CALC > 1차소스 > 최신성 > DA
 → ⑤ CALC (GPT가 program 작성 → finance_math.py 결정적 실행)
    ※ fan-in 뒤 배치 — 증거 유래 typed_facts로 계산 (핵심 결정)
 → ⑥ VERIFIER: G2 숫자·G3 as-of·G4 지시어 금지 = 순수 코드 게이트,
    G1 근거성만 Claude claim별 구조화 판정 → 코드 집계 + enforce_g2() 최종 강제
    ↺ REFLECT: 발동 사유 = 핵심 주장 게이트 실패 / 미해소 충돌(DA-DA 사실형 포함) / 커버리지 구멍.
      ★ 배타 라우팅 (2차 리뷰 critical): verifier 뒤는 switch-case(재조사↔risk) —
        무조건 edge 2개면 REFLECT 발동 순간에도 라운드1 답이 최종 방출되는 버그
      규칙 (적대 리뷰 반영):
      - 재조사는 신규 확장 쿼리 강제 (동일 쿼리 재실행 금지 — seen_queries/seen_doc_ids 캐리,
        하네스 안전장치 복원)
      - 재조사 결과 신규 문서 0건이면 즉시 unobtainable 마킹 후 종료 (라운드 소비 금지,
        답변에 "해당 증거 미존재/미공시" 라벨)
      - retry_directives에 replan 타입 허용: 실패 원인이 시점/기간/티커 해석이면
        1회 한정 PLAN 부분 재실행 (원문+실패 사유 주입)
      - 최대 2라운드 (하네스 ③′ 상한 그대로)
 → ⑥′ RISK (tier 3만, fable-5·think4k): bear case 패킷 — supporting_claim_ids 필수,
    미참조 항목은 코드가 "시나리오(미검증)" 자동 강등 (프롬프트 소원 금지 — 2차 리뷰)
 → ⑦ SYNTHESIZER (Claude, extended thinking) — 2단계 합성:
    유닛별 sub-answer 정리 → claim table·RISK 패킷과 함께 최종 종합
    검증 통과 claim만 단정, 미검증 라벨
 → ⑧ AUDITOR (5.5-mini 추출 + 코드 대조) — 2차 리뷰로 최종 텍스트 게이트로 확장:
    ① 숫자: ClaimTable/CALC 매칭 없는 신규 숫자 = unsupported → "[확인되지 않은 수치]" 인라인 라벨
    ② G4 지시어 패턴 최종 텍스트 재검사 → 자동 완곡화 + directive_hits[] layer 노출
    ③ ClaimTable/RiskPacket에 없는 신규 엔티티·사건 서술 플래그
 → ⑨ FINALIZER → yield_output(FinalAnswer + trace)
```

**toss_trend 파이프라인** (2026-07-02 신설, 2차 리뷰 반영):
1. `tossinvest.com/feed/news` 4탭 수집 (JSON 엔드포인트는 M2 PoC) → 중복 제거 → **상한: dedup 후 상위 30건** (settings)
2. **배치 요약**: 10건/콜 × 5.5-mini 3~4콜 (뉴스별 1콜 아님 — 콜 폭발 방지). feed-count(다종목 동시 등장=시황) 신호 활용
3. 요약 묶음 → 1콜 합성: `TrendPacket` {trends[]: {label, 관련 종목/섹터, 근거 뉴스 id}, as_of}
4. **각 trend는 derived claim(source=toss_trend_synth, 근거 뉴스 id 필수)으로 claim table 편입** — "컨텍스트"로 G1 우회하는 증거 세탁 차단. G1 근거로는 원본 뉴스만 인정, SYNTH 인용 시 뉴스 id 필수. **DA에는 주지 않음**
5. 질문 간 캐싱 없음(사용자 지시 유지) — 단 같은 질문의 REFLECT 라운드 간 재사용 (round≥1 skip)

### PLAN 스테이지 상세 — 답변을 잘하기 위한 선행작업 전부

PLAN은 tier 분류기가 아니라 **"답을 만들기 전에 미리 해야 하는 일" 전체를 수행하는 선행작업 스테이지**다.
(2026-07-02 적대 리뷰 3방향 반영 — 평결: "필드 목록은 성립하나 PLAN이 틀렸을 때의 감지·복구가 없다" → 아래는 오류 봉쇄를 포함한 확정 설계)

**구조: PLAN은 GPT 1콜이 아니라 3단 구성이다**

```
① 사전 코드: 티커 후보 매칭 — 후보+confidence (확정 아님. 지주사/그룹명
   exact match는 무조건 문맥 선택으로 강등. KOSDAQ/미국 우주 + 별칭 사전 포함)

② 병렬 2콜 (2026-07-02 변경: 난이도별 분할 — "서로 엮인 필드는 같은 콜에" 원칙):
   [A — 어려운 판단] Fable, thinking ~4k:
     질문 이해 묶음 (상호 의존이라 분리 불가): standalone_question · tier ·
     event_time_range/knowledge_cutoff · sub_questions(+depends_on) ·
     contrast_questions · needed_evidence · 유닛별 search_queries
   [B — 기계 추출] GPT 경량, low effort:
     원문에서 바로 뽑히는 것: fiscal_periods 후보 · metrics · tickers 보완 ·
     evidence_richness 잠정 + (교차확인용) tier/시점 독립 판정
   → 벽시계 = max(A, B) ≈ A. 이득: A의 필드 과적재 해소(12→7) + 교차확인
     직렬 콜 제거(B에 통합) + effort 차등

③ G0 sanity 게이트 (순수 코드) — 병합 + 검증:
   - A vs B의 tier·시점 불일치 → 보수적 채택 (tier 높은 쪽, 시점은 원문 재확인)
   - news_mode 코드 유도 (LLM 불필요): knowledge_cutoff 과거 → archive, 개념 질문 → off
   - tier4 판정 → 실행동사+명령형 패턴 재확인 (오차단 방지 2단 확인)
   - standalone_question → 원문 엔티티 보존율 검사 (재작성 왜곡 감지)
   - 티커 2차 매칭: standalone_question 기준 결정적 재실행, 불일치 시 기각
   - 유닛 총량 상한: DA·RA-외부 유닛 ≤ 6, contrast는 전체질문+핵심 sub 1개만
```

**PlanPacket 필드 (적대 리뷰 반영 구조):**

| 필드 | 구조·규칙 | 오류 봉쇄 |
|---|---|---|
| `schema_version` | 신설 — 최상류 계약의 진화 대비 | 체크포인트 resume·폴백 프로바이더·영속 layer의 tolerant reader (M0 테스트) |
| `tier` | 질문 종류 (설명/사실찾기/계산/판단/주문). 가정적 매매 시나리오 계산("지금 들어가서 12만원 가면 수익률?")=판단(3) few-shot. 애매하면 높은 쪽 | G0 tier4 2단 확인. tier 스키마 최상단 배치 |
| `standalone_question` | 재작성하되 **원문 항상 병행 보관**, 최종 합성은 원문 기준 | G0 엔티티 보존율 검사 |
| `event_time_range` + `knowledge_cutoff` | 기존 question_as_of를 둘로 분리 — "2024년에 왜 빠졌어?"는 사건=2024, 지식=now(회고 분석 허용). 백테스트("그때 샀으면")만 지식=과거 | G3는 knowledge_cutoff만 집행 — 과거 사건 질문에서 증거 전량 기각 방지 |
| `tickers[]` | 후보+confidence. LLM 보완 티커는 `unverified` 플래그 → **PRICE 응답의 종목명 역검증(코드)** 통과해야 CALC 입력 승격 | "엉뚱한 종목의 정확한 시세" 조용한 오답 차단 |
| `sub_questions[]` | tier별 0~5개 + **`depends_on`** (bridge 질문: "하이닉스 최대 HBM 고객사의 실적 영향은?" — 의존 유닛은 선행 답으로 검색어 채운 뒤 브랜치 내부 2파 실행) | 유닛 상한 (G0) |
| `contrast_questions[]` | **검색(RA-외부) 전용 — DA 투입 금지.** 무근거 반대 claim을 시스템이 제조해 가짜 충돌로 REFLECT를 태우는 경로 차단. 생성형 반대 시나리오는 RISK 스테이지로 일원화 | tier 2+ 원인/판단 질문만 생성 |
| `needed_evidence[]` | 자유 문장 금지 → `{entity, metric, period, source_type, required, obtainability}` 슬롯 (source_type enum = news\|price\|macro\|web\|company — 실제 수집기와 정렬, 2차 리뷰). **커버리지 1차 판정 = ASSEMBLER 코드 매칭** — G1에는 모호 슬롯만 (Claude 다운이어도 REFLECT 사유③ 유지). source_type=web 슬롯 존재가 web_knowledge 발동 조건 | `unobtainable`(미공시 등)은 REFLECT 제외 — "정직한 빈칸" 라벨로 SYNTHESIZER 직행 |
| `news_mode` | (구 retriever_routing 대체 — 죽은 필드 정리) 브랜치 내부 파라미터: `live` / `archive`(knowledge_cutoff 과거 → 시점 한정 검색) / `off`(순수 개념 질문) — 하네스의 NEWS 시간민감도 게이트 복원. filing은 도구가 없으므로 enum에서 제거 | 무조건 fan-out과 양립 (skip은 브랜치 내부 판단) |
| `fiscal_periods[]` | **검색 전 확정 금지** → `{calendar_period, last_reported_period, basis, resolved:false}` — 수집 후 ASSEMBLER가 실제 최신 보고 분기로 late-binding 확정 ("지난 분기" = 7/2 기준 달력 Q2(미공시) vs 보고 Q1 충돌 해소) | 틀린 분기의 정확한 숫자가 게이트를 통과하는 경로 차단 |
| `metrics[]` | 필요한 지표·계산 예측 → CALC 준비 (FinQA step program) | — |
| `search_queries[]` | 유닛별, 엔티티 정규화 + 시점 한정 | REFLECT 재조사는 **신규 확장 쿼리 강제** (동일 쿼리 재실행 = 공회전 차단) |
| `evidence_richness` | PLAN은 **잠정치만** → ASSEMBLER가 실수집량(근거 수·소스 다양성)으로 확정 재산출 — ai-berkshire 원형은 실측 기반 rating | 유명도 프록시 퇴화(대형주=A 편향) 방지 |

**멀티턴 history 계약 (신설):** 직전 N턴의 ① user 원문 ② assistant 답변 1문단 요약 ③ **이전 PlanPacket 요약 블록(tickers/fiscal_periods/knowledge_cutoff)**. "그럼 작년엔?"의 참조 해소는 답변 전문이 아니라 이전 계획의 구조화 필드로 — 싸고 정확함.

**문헌 인용의 정직한 구분** (적대 리뷰 수용):
- **메커니즘 이식** (그대로 동작): claim 단위 검증(FActScore/RAGChecker), 결정적 계산(FinQA), as-of 규율(Zep/Graphiti), tier/티커/RISK(ryze·ai-berkshire 운영 경험)
- **아이디어 차용** (원 논문은 훈련된 모듈·디코딩 신호, 우리는 프롬프트 — 품질 격차 가능성을 문헌 자신이 예측): 분해(AirRAG/RQ-RAG), 재작성(정정: 정확한 근거는 conversational query rewriting 계열), 필요증거 예측(FLARE), 교정 재검색(CRAG). → **M5에서 no-op 대조 실측** (재작성/분해 있음 vs 없음 골든 비교) — 프롬프트 버전이 실제 개선인지 데이터로 확인.

### 1.2 모델 배치 (역할 분리)

| 역할 | 모델 | 담당 |
|---|---|---|
| 계획자 | **Claude Fable** (`AnthropicClient`, 짧은 thinking) | **PLAN** — 오류가 가장 회복 비싼 스테이지에 가장 강한 모델 (2026-07-02 변경, GPT가 경량 교차확인) · RISK bear case |
| 생산자 | gpt-5.5 (`OpenAIChatClient`, Responses) · high | DA 블라인드 (전 유닛) + 전체질문은 fable-5·think8k 이중 블라인드. da_fable claim의 G1은 GPT가 교차 채점 (자기 채점 방지) |
| 추출·교차확인 | gpt-5.5-mini · low | PLAN-B(기계추출+교차판정) · claim 추출 · 토스 뉴스 요약 · web_knowledge 정리 · AUDIT 추출 (감사 독립성 — Fable 답변을 Fable이 감사하지 않도록 GPT 계열 고정) |
| 계산 프로그램 | gpt-5.5 · med | CALC program 작성 (2026-07-02 mini→본체 상향 — 사실 선택 실수 방지) |
| 실증자 | grok-4 (`OpenAIChatCompletionClient`, base_url=x.ai) · 기본(PoC) | RA-외부 x_search — X/웹 실시간 (자유 텍스트만 — 구조화 출력 금지) |
| 심판 | claude-fable-5 (`AnthropicClient`, thinking) | G1 검증(8k) · SYNTHESIZE(16k) |
| 결정적 코드 | — | 토스 수집 · PRICE·MACRO · finance_math 실행 · ASSEMBLER · G0/G2/G3/G4 · AUDIT 대조 |

주: PLAN이 Claude여도 심판 오염이 아니다 — G1이 검증하는 것은 DA/NEWS/CALC가 만든 **주장(claim)**이지 계획이 아니므로, 자기 답을 자기가 채점하는 구조가 되지 않는다 (답변 claim 생산은 여전히 GPT/Grok). M2 Planner A/B로 데이터 재확인, ROLE_MAP 설정이라 교체 비용은 한 줄.

**단계별 effort/thinking 기본값** (원칙: 판단에 화력, 옮겨적기는 싸게. 전부 profile 설정 — 골든 문항으로 튜닝, v2 depth 레버가 이 표를 통째로 스케일):

| 단계 | effort/thinking | 이유 |
|---|---|---|
| PLAN-A 질문이해 (Fable) | thinking ~4k (짧게) | 첫 콜 지연 민감, 오류는 G0+replan이 봉쇄 |
| PLAN-B 기계추출+교차확인 (GPT 경량) | low | 원문 추출 + tier/시점 독립 판정 (A와 병렬) |
| DA 블라인드 — 전체질문 (gpt-5.5 + fable-5) | high / think~8k | 이중 블라인드 — 불일치가 검증 신호 (2026-07-02 지시) |
| DA 블라인드 — 서브질문 (gpt-5.5) | high (사용자 지정) | M2 A/B로 med 대비 이득 실측 — 없으면 med 회귀 제안 |
| NEWS (Grok) | 기본값 — M2 PoC | 본체는 검색. xAI effort 파라미터 미검증 |
| 추출류 — claim 추출·AUDIT 추출·뉴스 요약 (5.5-mini) | low | 기계적 구조화 |
| CALC program 작성 (gpt-5.5) | med | 2026-07-02 상향 (mini→본체): 사실 선택 실수는 단위검사를 통과하는 "검증된 오답" — 질문당 1콜이라 비용 미미. Fable 불필요 (프로그램 작성은 GPT 강점 + 직렬 구간 지연 최소화) |
| G1 검증 (Claude) | thinking ~8k | 미묘한 불일치 탐지 — 아끼지 않는 곳 ① |
| RISK (Claude) | thinking ~4k | 좁고 명확한 과제 |
| SYNTHESIZER (Claude) | thinking ~16k | 최종 품질 결정 — 아끼지 않는 곳 ② |

**모델 ID 확정** (2026-07-02 M2 PoC 실측 — 전부 실재 확인):
- Claude 본체 = `claude-fable-5` (PLAN-A·G1·RISK·SYNTH)
- GPT 본체 = `gpt-5.5` (DA 블라인드) — 레포 기존 codex 설정과 동일 계열
- GPT 경량 = `gpt-5.5-mini` 급 (PLAN-B·claim 추출·감사 추출) — "판단은 본체, 옮겨적기는 mini" 기준. mini가 기간 변환 품질 미달이면 본체+effort low로 승격 (설정 한 줄)
- Grok = `grok-4` (NEWS) — base_url 경로 자체가 PoC 항목

- 심판은 답을 생산하지 않는다 (자기 답 자기 검증 오염 배제).
- 폴백에도 분리 유지: Claude 다운 → GPT가 verify/synth를 맡으면 DA는 Grok으로 교체.
- 역할→모델 매핑은 `ROLE_MAP` 데이터 — profile이 override 가능.

### 1.3 불변식

1. **브랜치는 절대 raise하지 않고 항상 패킷을 발신한다** — skipped/degraded/error 빈 패킷 포함. fan-in 배리어가 항상 결정적. 브랜치 타임아웃 60s.
2. **모든 숫자는 CALC(결정적 계산)에서만** — LLM 암산 경로 없음. Claude verdict 뒤에도 `enforce_g2()` 코드가 최종 강제. AUDITOR가 이중 안전망.

### 1.4 Degradation 매트릭스

| 장애 | 동작 |
|---|---|
| 토스 다운 | toss_trend/toss_company degraded — X검색·웹 수집은 계속, 답변에 표기 |
| Grok 다운 | x_search 폴백 체인 grok → Brave(freshness=pd) → Tavily |
| GPT 다운 | DA → Grok 교체, 추출·G0 교차확인 → Claude 폴백 |
| Claude 다운 | PLAN → GPT 폴백, G1 skip(코드 게이트 계속), SYNTH → GPT + DA → Grok 교체 |
| 키 누락 | 부팅 실패 아님 — capability off, `/healthz` 노출 |
| 사이드카 다운 | Node가 기존 failed 경로 재사용 |

침묵 저하 금지 — 모든 저하는 답변과 layer에 노출.

### 1.5 v2/v3 유예 (지금 심는 훅)

> 2026-07-02 변경: 질문 분해 실행·REFLECT·RISK는 **v1로 승격** (사용자 지시 — 답변 품질 핵심 기능은 미루지 않는다). 아래는 순수하게 "기능 추가"인 것만 남김.

| 항목 | 시기 | 훅 |
|---|---|---|
| thinkLevel→depth 매핑 (분해 폭·REFLECT 라운드·thinking 예산 조절 레버) | v2 | WorkflowProfile.depth_profile 자리 |
| 모드 카탈로그 (pulse/checklist/thesis/funnel) | v3 | WORKFLOWS 레지스트리 (M7 더미 모드 리허설) |
| Toss 실시간·프록시 스크레이퍼 | v2/v3 | tools/http.py 프록시 슬롯 |
| 체크포인트 resume·HITL | v2/v3 | FileCheckpointStorage는 v1부터 기록 |

---

## 2. 코드 관리 / 폴더 구조

배치: **attn-viewer 레포 안 `engine/`** (별도 레포 아님 — 계약 원자적 커밋, 단일 배포 호스트).
server.mjs는 리팩터링하지 않고 `runChatAnswer()` 본문만 교체(~40줄), 신규 Node 코드는 `lib/engine-client.mjs` 하나.

```
attn-viewer/
├── server.mjs                    # runChatAnswer(dirs, chatId) 본문만 교체
├── lib/engine-client.mjs         # [신규] POST + NDJSON 소비 → writeChat으로 layer append
├── .env                          # 키 단일 진실원 + ENGINE_URL=http://127.0.0.1:8801
└── engine/                       # [신규] Python 사이드카
    ├── pyproject.toml            # agent-framework-openai, agent-framework-anthropic==1.0.0b260630(핀),
    │                             #   fastapi, uvicorn, httpx, pydantic-settings
    ├── app/
    │   ├── main.py               # FastAPI: POST /v1/answer(NDJSON), GET /healthz
    │   ├── stream.py             # WorkflowEvent → NDJSON 브리지
    │   └── settings.py           # 루트 .env 로드, capability 맵
    ├── contracts/                # ★ 스키마가 계약
    │   ├── packets.py            # PlanPacket, DaPacket, EvidencePacket, AtomicClaim(+norm),
    │   │                         #   ClaimTable, VerdictPacket(retry_directives), AuditReport, FinalAnswer
    │   ├── events.py             # LayerEnvelope — ChatArtifacts.layers와 1:1
    │   └── api.py                # AnswerRequest 등
    ├── providers/factory.py      # ROLE_MAP(역할→폴백체인=데이터) + make_client()
    ├── workflows/
    │   ├── registry.py           # WORKFLOWS = {"qa": (build_qa_v1, QA_V1_PROFILE)}
    │   ├── profile.py            # WorkflowProfile: tool_allowlists, role_overrides, depth_profile
    │   ├── qa_v1.py              # build_qa_v1(profile): WorkflowBuilder 조립
    │   └── executors/            # 모드 간 공유 (복제 금지)
    │       ├── plan.py scout_news.py scout_da.py scout_ra.py price.py
    │       ├── assembler.py calc.py verifier.py synthesizer.py auditor.py finalizer.py
    ├── gates/
    │   ├── g1_grounding.py       # Claude claim별 판정 + 코드 집계
    │   ├── g2_numeric.py g3_asof.py g4_compliance.py   # 순수 코드
    ├── tools/
    │   ├── base.py               # ToolSpec: In/Out Pydantic, required_env, degrade, 이중 표면
    │   ├── registry.py           # TOOLS + 스테이지 allowlist 집행
    │   ├── http.py               # 공용 httpx — 프록시 훅 유일 지점
    │   ├── news/brave.py tavily.py
    │   ├── toss/feed.py company.py price.py  # ★ 토스 모듈 — 트렌드 피드·회사(공시/뉴스/애널리틱스/거래동향)·차트. 규칙 명확, 적극 활용 (2026-07-02)
    │   ├── price/yahoo.py (+universe_kospi.json) macro.py  # 시세 + 매크로 지표(지수/환율/금리/유가)
    │   ├── calc/finance_math.py  # 하네스에서 무수정 벤더링
    │   └── memory/observe.py     # v1 미사용 (내부 RA 보류) — 자리만 유지
    └── tests/
        ├── test_gates.py test_finmath.py test_assembler.py test_contracts.py
        └── golden/               # 5문항 픽스처 (상대시점 질문 포함)
```

### Node ↔ Python 계약

```
POST /v1/answer
{ "mode": "qa", "question": "...", "history": [...],
  "providers": ["anthropic","openai","grok"],   # v1 기록만
  "think_level": 2 }                             # v1 기록만

응답 = NDJSON 스트림 (Node가 유일 소비자 — 브라우저 SSE 불필요):
{"type":"heartbeat"}                            ← 10~15s 주기 (SYNTH 침묵 구간 abort 방지 — 2차 리뷰)
{"type":"layer","name":"plan","round":0,"data":{...},"createdAt":"..."}
{"type":"final","answer":"...md...","meta":{"degraded":[...],"audit":{...},
  "plan_summary":{...},        ← 멀티턴용 확정 PlanPacket 요약 (Node가 assistant 메시지에 저장)
  "models_used":[...]}}        ← providers 기록값과 실행값 불일치를 정직하게 노출
{"type":"error","message":"..."}
engine-client: idle 타임아웃(heartbeat 기준) + 전체 데드라인 8분 + per-chat 뮤텍스.
run_id 부여 — 클라이언트 disconnect 시 FastAPI가 워크플로 취소.

GET /healthz → {ok, capabilities:{anthropic,openai,grok,observe,brave,...}}
```

- `engine-client.mjs`: layer 이벤트마다 `writeChat`으로 `artifacts.layers` append → 기존 폴링이 실시간 표시. **프론트/OpenAPI 변경 0.**
- layer 이름 고정 어휘 (2026-07-02 브랜치 개편 반영): `plan / da_blind / ra_x / ra_web / toss_trend / toss_company / price / macro / claims / calc / verify / risk / audit / trace` (+ REFLECT 라운드는 `verify` layer에 round별 기록).

**채팅 중간 출력 — UX 확정 요구 (2026-07-02 사용자 지시):**
- 각 스테이지의 결과물은 완료 즉시 채팅에 **보이는 형태로** 표시되어야 한다 (layer 저장만으로 끝이 아니라 사용자가 읽을 수 있는 렌더링).
- **특히 `plan` layer의 sub_questions(쪼갠 질문들)는 채팅에 반드시 표시** — 하네스 /deep의 "분해 직후 하위질문 목록 즉시 출력" 규칙 계승. 사용자가 시스템이 질문을 어떻게 이해하고 쪼갰는지 답변 전에 확인 가능해야 함.
- 우선 표시 대상(사용자 가독 렌더링 필요): plan(sub_questions·tier·시점·richness) → ra_x·toss_trend(헤드라인/트렌드) → claims(충돌표) → verify(게이트 통과/실패) → audit(숫자 검증·지시어 히트). 나머지 layer는 접힌 상세로. REFLECT 재라운드 layer는 round 필드로 최신 교체(이전 보존).
- 구현 순서: v1은 layer별 간이 텍스트 렌더링(프론트 최소 수정), 스테이지별 전용 렌더러는 이후 — layer 이름 고정 어휘가 이 확장의 근거.
- 기동: `uvicorn engine.app.main:app --port 8801` (systemd/pm2로 Node와 나란히).

---

## 3. MAF 구현 (검증된 API만)

- 패키지: `agent-framework` 1.10.0 stable. `agent-framework-anthropic==1.0.0b260630` **베타 — 정확 핀 필수** (`--pre`).
- 클래스: `AnthropicClient` / `OpenAIChatClient`(Responses) / `OpenAIChatCompletionClient`(Grok용 base_url). `Agent`(구 ChatAgent), `@handler` executor, `WorkflowBuilder`, `add_switch_case_edge_group`, `add_fan_in_edges`, `WorkflowEvent(type=...)`, `FileCheckpointStorage`.
- 구조화 출력: `agent.run(text, options={"response_format": PydanticModel})` → `resp.value` — **Anthropic/OpenAI만, Grok 금지.**
- 진행 이벤트: `ctx.add_event(WorkflowEvent(type="progress", data={"layer":..., "data":...}))` → NDJSON 1:1.
- 체크포인트: superstep 경계 자동 = fan-in 직전 보존. v1은 기록만.

```python
def build_qa_v1(profile):
    b = WorkflowBuilder(start_executor=plan,
        checkpoint_storage=FileCheckpointStorage(settings.checkpoint_dir))
    b.add_switch_case_edge_group(plan, [
        Case(condition=lambda p: p.tier == 4, target=blocked),
        Default(target=dispatch)])
    for br in (da, ra_ext, price_macro):              # 3브랜치 (2차 리뷰 정정 — 4브랜치 잔재 제거)
        b.add_edge(dispatch, br)                      # 무조건 fan-out
    b.add_fan_in_edges([da, ra_ext, price_macro], assembler)
    for a, z in [(assembler, calc), (calc, verifier),
                 (risk, synthesizer), (synthesizer, auditor), (auditor, finalizer)]:
        b.add_edge(a, z)
    # ★ REFLECT 배타 라우팅 (2차 리뷰 critical 수정): 무조건 edge 2개로 두면
    #   REFLECT 발동 순간에도 라운드1 답이 risk→synth로 흘러 최종 방출됨 (100% 재현)
    b.add_switch_case_edge_group(verifier, [
        Case(condition=lambda v: bool(v.retry_directives) and v.round < 2, target=dispatch),
        Default(target=risk)])
    #   ※ replan은 그래프 전이가 아니라 dispatch 내부 서브루틴 (PLAN-A 1콜 직접,
    #     tier·차단 판정은 라운드1 값 고정 — switch-case 재통과 방지)
    #   ※ 라운드 상태는 전 패킷 공통 EnvelopeMeta{round, plan_ref} + shared state
    #     ReflectState{seen_queries, seen_doc_ids} (체크포인트 직렬화 포함) — M0 계약에 명시
    # risk 내부: tier < 3이면 즉시 passthrough (skipped 패킷 — 불변식 1 준수)
    #   risk 출력은 SynthInput{verdict, claim_table, risk|skipped} 래핑 — 직렬 노드 캐리 규칙
    return b.build()
```

### PoC 필수 4항목 (M2 스파이크, 반나절)

1. ✅ **Grok via `OpenAIChatCompletionClient(base_url=x.ai)`** — 확인 완료(2026-07-02), httpx 직결 폴백 불필요.
2. xAI live-search 파라미터 options 통과 여부 — 불가 시 Brave/Tavily 상시 병행.
3. ✅ **anthropic thinking + structured output 동시 동작 확인** — Fable은 `thinking.type.adaptive` + `output_config.effort`(low/medium/high) 방식. budget_tokens 미지원. 문서 think4k/8k/16k = effort low/medium/high로 매핑.
4. ✅ **fan-in 핸들러 = `list` 수신** 확인 — ASSEMBLER `list[BranchPacket]` 확정. 핸들러 메시지 파라미터 타입 주석 필수.
5. **토스 JSON 엔드포인트** — 일부 확보/확인 완료 (2026-07-02):
   - ✅ 회사별 뉴스: `wts-info-api.tossinvest.com/api/v2/news/companies/{code}?size&number` + 본문 상세 `api/v2/news/{id}` — **하네스 `internal/ingest/toss.go` + `cmd/ryze/toss_ingest.go`에 작동 코드 존재, 이식 참고** (KST 무타임존 시각 파싱, 인터리브 페이지네이션 중단 조건, feed-count 집계 — 같은 기사가 여러 종목 피드에 등장하면 시황 뉴스로 라우팅하는 신호. toss_trend에도 재사용)
   - ✅ 이 서버에서 프록시 없이 직접 호출 성공 확인 (하네스 주석의 "KR IP 필요 + RYZE_TOSS_PROXY"는 하네스 실행 환경 기준 — 우리 호스트는 직접 OK. 단 tools/http.py 프록시 슬롯은 유지, 차단 시 NodeMaven 전환)
   - ⬜ 남은 PoC: feed/news 4탭(인기/주요/최신/급상승)·analytics·transaction-status 엔드포인트 (api/v2 계열 추정), 레이트리밋 실측

---

## 4. Tool 관리

**도구 2계급:**

- **결정적 도구** (`finance_math`, `price_yahoo`, `observe`): 에이전트 `@tool` 바인딩 **금지**. Executor 코드가 직접 호출 — G2의 전제.
- **에이전트 바인딩** (`brave`, `tavily`, grok_live): 탐색적 검색만 `as_agent_tool()` 래핑. PLAN/DA/VERIFY 에이전트는 도구 없음 (blind by code).

```python
class ToolSpec(BaseModel):
    name: str
    kind: Literal["deterministic", "http", "agent_search"]
    In: type[BaseModel]; Out: type[BaseModel]
    required_env: list[str] = []
    timeout_s: float = 20.0
    degrade: Literal["skip", "fallback", "fail"] = "skip"

STAGE_ALLOWLIST = {               # 순서 = 폴백 순서, registry가 코드로 집행
    "ra_x":        ["grok_live", "brave_news", "tavily"],  # X/웹 실시간 (폴백 체인)
    "ra_web":      ["brave_news", "tavily"],               # 배경지식 웹서핑
    "ra_toss":     ["toss_feed", "toss_company"],          # 토스 트렌드·회사
    "price_macro": ["price_yahoo", "macro_yahoo"],         # v2: toss_price 폴백 추가
    "calc":        ["finance_math"],
    "planner": [], "da": [],                                # blind by code
}
```

- 부팅 시 required_env + healthcheck → capability 맵 → `/healthz` + degrade 판단 주입.
- 새 도구 = 모듈 1 + registry 1줄 + allowlist. 새 모드 = profile+graph + WORKFLOWS 등록 (Node/API 무수정).
- 외부 HTTP는 전부 `tools/http.py` 경유 — NodeMaven/cf-bypass는 향후 여기 한 곳에만.
- twitterapi.io 미등록(크레딧 소진) — X 검색은 Grok 경유 유일. 키는 settings 경유만.

---

## 5. 구현 순서 (마일스톤)

- [x] **M0** — ✅ `engine/contracts/` 완료 (2026-07-02): packets.py(PlanPacket→FinalAnswer 전 패킷 + EnvelopeMeta round 관통 + provenance/DA-DA/RetryDirective/SynthInput 캐리 — 2차 리뷰 반영) · events.py(NDJSON: heartbeat/layer(round)/final/error) · api.py(AnswerRequest+HistoryTurn.plan_summary)
  - 검증: ✅ 라운드트립·claim_key 정규화·strict 거부·이벤트 파싱 10/10 통과 (LLM 불필요). 골든 5문항 픽스처는 M2 PoC와 함께 (실 LLM 출력 기반이라 순서 조정)
- [ ] **M1** — 배관: FastAPI(healthz + 에코 답변 + **heartbeat**) + `lib/engine-client.mjs`(idle 타임아웃·전체 데드라인 8분·per-chat 뮤텍스) + runChatAnswer 교체(**messageNotes 분기 보존**) + **프론트 layer 패널 신설(~100~200줄)** + writeChat 원자화(tmp+rename) + Node 부팅 시 running 스윕
  - 검증: UI(#chat)에서 질문 → 더미 layer가 **화면에 렌더링**됨. "프론트 변경 0"은 정정 — 전송·API 변경 0, 렌더링은 신규 (2차 리뷰)
- [x] **M2** — ✅ MAF 설치 + 프로바이더/워크플로 PoC 완료 (2026-07-02, `engine/poc/` 8/8 통과)
  - ✅ **3사 실 API**: gpt-5.5 · claude-fable-5 · grok-4(x.ai base_url — 최대 리스크 해소) 각 1콜 성공
  - ✅ **structured output**: OpenAI·Anthropic 모두 `options={"response_format": Model}` → `resp.value` 파싱 확인
  - ✅ **Fable extended thinking**: `{"thinking":{"type":"adaptive"}, "output_config":{"effort":"low|medium|high"}, "max_tokens":N}` + response_format 동시 동작 (무라타 3.527배 정답). ※ `thinking.type.enabled`/budget_tokens는 Fable 미지원 → **effort 라벨이 확정 방식** (문서 think4k/8k/16k = effort low/medium/high로 해석)
  - ✅ **fan-in 핸들러는 `list` 수신** (PoC #4 해소) → ASSEMBLER `list[BranchPacket]` 설계 확정. 핸들러는 메시지 파라미터 타입 주석 필수
  - ✅ **switch-case 배타 라우팅** 동작 (Tier4 차단 / REFLECT 배타 라우팅 기반). `WorkflowBuilder(start_executor=...)` 필수, `.run()` → `.get_outputs()`
  - API 정정: 에이전트 생성은 `client.as_agent(instructions=...)` (create_agent 아님)
  - 남은(M4로 이관): Planner A/B(GPT vs Fable)·DA effort A/B(med vs high)는 실 파이프라인에서 골든 문항으로, REFLECT 사이클 사이클 실동작(verifier→dispatch 재진입)은 그래프 조립 후 확인
- [~] **M3** — 도구 계층 (대부분 완료, 2026-07-02):
  - ✅ **토스 모듈** (feed/company/price + client) — 라이브 스모크 3/3. 엔드포인트 인벤토리 `docs/toss-api-inventory.md`
  - ✅ **야후 시세** (`tools/price/yahoo.py`) — quote.py async 이식, universe_kospi.json 벤더링. 한글명/코드/해외심볼 해석
  - ✅ **매크로 세트** (`tools/price/macro.py`) — KOSPI/KOSDAQ/S&P/나스닥/USD-KRW/미10년/WTI/VIX 8종 스모크 통과
  - ✅ **finance_math** 벤더링 + never-raise `run()` 래퍼 + 회귀 테스트 4종(pp 규율·나눗셈0)
  - ✅ **레지스트리** (`tools/registry.py`) — ToolSpec·STAGE_ALLOWLIST·capabilities, env 게이팅 테스트 4종
  - **테스트 현황**: 오프라인 8(CI 가능) + 라이브 6 = 14/14 통과
  - 남은: brave/tavily 검색 도구 fn 바인딩(M4 executor와 함께), 토스/야후 차단 degrade 테스트, observe는 v1 자리만
- [~] **M4** — 실제 파이프라인 (에코 → 진짜 답변). 진행 중 (2026-07-02):
  - ✅ `providers.py` — 역할→모델 폴백 팩토리 (as_agent, Fable adaptive+effort, OpenAI/Grok)
  - ✅ `stages/plan.py` — PLAN 병렬 2콜(A/B)+G0 코드 게이트. 실 질문 검증: 삼성전기→009150 매칭·3분할·의존관계·교차판정 보수채택 동작
  - 구조 결정: 스테이지 로직을 순수 async 함수(`stages/`)로 분리 → 오케스트레이터가 호출 (독립 테스트·layer 스트리밍 용이, MAF 그래프는 로직 안정 후 얇게 감쌈)
  - structured output 실측 제약 확정: 정수 min/max 불가·자유 dict 불가·`additionalProperties:false`(extra=forbid) 필수 → 모든 SO 스키마 규칙
  - ✅ `stages/da.py` — 블라인드 이중(전체질문 GPT+Fable / 서브 GPT), 유닛 프롬프트에 전체 맥락
  - ✅ `stages/ra_external.py` — 토스 트렌드(global)+회사(ticker) 수집기
  - ✅ `stages/price_macro.py` — 야후 시세+매크로 8종, typed_facts 추출
  - ✅ `stages/synthesize.py` — Fable 2단계 합성 (검증 통과만 단정, 독립답변 비교, 매수/매도 지시 금지)
  - ✅ `orchestrator.py` — PLAN→[DA·RA·PRICE 병렬]→얇은 ASSEMBLER→SYNTHESIZE, layer 순서 스트리밍
  - ✅ **엔진 배선 완료** — 에코 제거, `mode=qa(M4)`. **전체 스택 실답변 검증**: "삼성전기 왜 올랐어"(전제 의심)·"SK하이닉스 살만해"(tier3, 지시 없이 판단재료) 둘 다 고품질. ~75초, layer 순서 스트리밍 확인
  - **남은(품질 게이트 확장)**: CALC 결정적 계산 연동 · VERIFIER G1~G4 · RISK bear case 스테이지 · AUDITOR 사후검증 · ASSEMBLER 충돌해소 · REFLECT 루프. (현재는 합성 프롬프트가 규율을 인코딩 — 코드 게이트로 승격 예정)
- [x] **M5** — ✅ 게이트 4종 + VERIFIER + REFLECT 루프 + RISK + AUDITOR + RA-외부 완성 (2026-07-03)
  - ✅ `stages/assemble.py` — 통합 claim table: metric 동의어 정규화·기간 호환 충돌 판정·해소(CALC>1차>최신), DA-DA 규칙, coverage 코드 매칭(metric 토큰 필수), richness 실측 재산출, 권위순 dedup
  - ✅ `stages/calc.py` — GPT 프로그램 작성→finance_math 결정적 실행. passthrough_fact_id(identity 금지), "값:단위" 상수, (metric,unit_id) 키, 결과 단위 sanity
  - ✅ `stages/verify.py` — G2/G3/G4 순수 코드(단위호환 앵커 대조·no-lookahead·지시어) + G1 선별 LLM(교차 채점: da_fable→GPT 심판) + 캡 초과 후보 verified 금지 + retry_directives(연구/replan)
  - ✅ REFLECT (orchestrator) — 배타 라우팅, 신규 확장 쿼리 강제(seen_queries/seen_urls), 신규 문서 0건→unobtainable 즉시 종료(라운드 미소비), replan 서브루틴 1회, 최대 2라운드
  - ✅ `stages/risk.py` — tier3 bear case, supporting_claim_ids 코드 라벨링(grounded/scenario), tier<3 passthrough
  - ✅ `stages/audit.py` — 숫자 regex 추출(만원/억/조 스케일)→verified 앵커만 대조(탈락 claim 배제), match 위치 기반 인라인 라벨, G4 완곡화, mini 신규 엔티티(GPT 계열 고정)
  - ✅ RA-외부 완성 — 유닛별 x_search(상한 3콜, grok→brave→tavily 폴백), web_knowledge(web 슬롯 발동, brave web→tavily+mini), toss_trend mini 합성(derived claim, 뉴스 id 필수), claim 추출 mini, contrast_questions 검색 전용, 수집기 gather 격리
  - ✅ price_macro — YTD 트리거 확장 (fiscal 표현 + metrics "수익률/올랐/YTD")
  - **검증 (M5 기준 4종 전부 통과)**: ① 삼성전자 수익률 — CALC/price 137.16%가 DA 추정 이김 ② 조작 수치(500%) G2 fail→unverified, 오프라인 6/6 ③ REFLECT 발동→재조사→verified 14→20, 2라운드 상한 확인 ④ SK하이닉스/네이버/카카오 tier3 — RISK grounded bear 4건 포함
  - **스테이지별 개별 라이브 테스트** `tests/test_stages_live.py` (ra/calc/verify/risk/audit/reflect 6/6) + 오프라인 `tests/test_gates_m5.py` 6/6
  - **codex 적대 리뷰** 23건 → critical/major 13건 수정 (G1 캡 우회·G2 전역 float 앵커·AUDIT 탈락 claim 앵커·라벨 오폭·REFLECT 라운드 회계·재조사 예외 격리·수집기 격리·coverage 오탐·CALC 키/단위 등). 미수정(수용): SynthInput 미사용(개별 인자 전달), seen_queries exact match, synth에 원문 증거 제공(라벨 규율+AUDIT 안전망으로 방어)
  - **풀스택 실질문**: "카카오 올해 수익률 어때? 지금 들어가도 괜찮아?" → 18 layer, YTD -44.04% ✅검증 표시, 미검증 수치 전량 라벨, RISK 4건, $1.19 · 155s
- [ ] **M6** — 하드닝: 장애 주입(토스 차단 / XAI·ANTHROPIC·OPENAI 키 제거), Tier4 차단, 타임아웃 예산
  - 검증: 각 장애에서 degraded 표기와 함께 답변 완성
- [ ] **M7** — 확장성 리허설: 더미 "pulse" 모드 WORKFLOWS 등록(~3파일) + README
  - 검증: 두 번째 모드가 API mode 필드로 호출됨 = 모드 카탈로그 seam 증명

## 6. 리스크 / 오픈 퀘스천

1. **Grok-OpenAI 호환 레이어** (최대) — M2 최우선, 폴백 설계 완비.
2. anthropic 커넥터 베타 — 정확 핀 + factory 한 파일 격리.
3. 레이턴시 — 유닛 분해 실행 포함 2~5분 예상. layer 스트리밍+heartbeat로 체감 완화. 브랜치 타임아웃은 60s 고정이 아니라 **max(유닛 콜 p95)+직렬 구간 합산**(2차 리뷰 정정) — DA는 high×이중 블라인드라 120s급.
4. 비용 (2차 리뷰 재산정) — 유닛 만재(1+5) 기준 **판단급 콜 ~33** (PLAN 2 + DA 7 + x_search 12 + web 6 + G1 2 + CALC 1 + RISK 1 + SYNTH 1~2 + AUDIT 1) + toss_trend 배치 요약 **mini 4~5콜** (뉴스 상한 30건·10건/콜 배치 — 상한 없으면 50~80콜 폭발). REFLECT 라운드당 재조사 유닛 몫만 추가 (global 수집기는 round≥1 skip).
4-1. REFLECT 사이클(verifier→dispatch 역방향 edge) + fan-in 상호작용 — MAF에서 미검증. M2 PoC에 추가, 불안정 시 REFLECT를 verifier 내부 서브루틴(재조사 도구 직접 호출)으로 구현하는 폴백 준비.
5. G2 강등 정책(미검증 숫자 = 라벨 통과)의 충분성 — 실사용 후 판단, 불충분 시 REFLECT 조기 도입.
6. 멀티턴 후속질문의 question_as_of 추출 품질 — 골든 픽스처에 상대시점 질문 포함.

## 7. 2차 적대 리뷰(전체 구조) 반영 — 확정 수정 요약 (2026-07-02)

4각도 공격 리뷰(데이터 계약/오케스트레이션/검증 건전성/운영 통합) 31건 + 자체 리뷰 8건 → 중복 제거 24건 전부 반영. 상세는 workflow-review.html 각 카드 + "Node 통합 하드닝" 카드.

**A. 구조 (그래프·계약):** ① verifier 뒤 switch-case 배타 라우팅 (라운드1 조기 방출 버그) ② AUDITOR를 최종 텍스트 게이트로 확장 (G4 재검사·신규 숫자 인라인 라벨·신규 사실 플래그) ③ toss_company 추출 단계 신설 (5.5-mini — 1차소스 우선순위 실행 가능화) ④ TrendPacket·web 서사를 derived claim으로 claim table 편입 (검증 우회 차단) ⑤ replan = dispatch 내부 서브루틴 ⑥ EnvelopeMeta{round, plan_ref} 전 패킷 관통 + ReflectState shared state (M0 계약) ⑦ bridge resolver (RA 1파→mini 1콜→3브랜치 공통 주입) ⑧ DA-DA 규칙 (불일치=da_disagreements+둘 다 unverified+집중검증 승격 / 일치=corroborated 플래그만 / provenance[] 교차 채점 라우팅)

**B. 폴백 무모순화:** ⑨ GPT 다운 → da_fable claim 코드 일괄 unverified (Fable 승격 금지) + AUDIT skip("숫자 감사 미수행") ⑩ 커버리지 1차 판정 = ASSEMBLER 코드 (Claude 다운이어도 REFLECT 사유③ 유지) + G1 유닛 샤딩

**C. Node 통합 (전부 v1):** ⑪ heartbeat + idle/전체 데드라인 + run_id 취소 ⑫ Node 부팅 시 running 스윕 (영구 잠금 해제) ⑬ per-chat 뮤텍스 + writeChat 원자화 + 노트 질문 409 가드 ⑭ messageNotes 경로 = mode="note" 경량 fable-5 단일 콜 ⑮ "프론트 변경 0" 정정 — layer 패널 ~100~200줄 M1 포함, layer round 태깅·초기화·이관 규칙 ⑯ 검색 쿼터: rps 세마포어+백오프 v1 승격, 사용량 /healthz 노출 ⑰ 골든 CI = 카세트 재생, 실 API는 야간/수동, as_of 고정 주입 ⑱ providers/thinkLevel 컨트롤 비활성+툴팁

**D. 예산 재산정:** ⑲ 판단급 ~33콜 + toss 배치요약 4~5콜 (뉴스 상한 30건·10건/콜) ⑳ 브랜치 타임아웃 = max(p95)+직렬 합산, DA 120s급

**E. 문서 정합:** ㉑ build_qa_v1 3브랜치 정정 ㉒ UX layer 어휘 정정 ㉓ source_type enum 정렬 ㉔ 멀티턴 plan_summary는 final meta 경유

## 8. 참고 원본

- 세션 노트: `~/ryze-equity-harness/docs/plans/2026-06-30-web-qa-session-notes.md`
- 하네스 계약: `~/ryze-equity-harness/skills/deep/references/` (worker_contract, verifier_rubric, numeric_policy, routing)
- 이식 코드: `~/ryze-equity-harness/skills/deep/scripts/finance_math.py`, `skills/price/scripts/quote.py`
- 외부 도구 목록: `~/longshot-wiki/tools/` (brave/tavily/yahoo/toss/nodemaven/cf-bypass)
- ai-berkshire 패턴: evidence_richness, answer_audit, 모드 카탈로그, news-pulse 4-scout

---

## 부록: M4 심화 + QA/리뷰 (2026-07-02 저녁)

### 추가 구현
- **TRIAGE 라우팅** (`stages/triage.py`) — 입구에서 deep/followup/smalltalk 분류 + needs_fresh_data. `/deep` 접두어로 강제 deep. "그럼 하이닉스는?"(새 종목)=deep, "그거 왜?"(참조)=followup 정확 구분. 직전 답변 참조 인식 강화(메타 클라우드 케이스).
- **followup 경량 경로** (`stages/followup.py`) — 직전 턴 raw(매크로·트렌드·시세·뉴스·claims) 재사용, 합성 1콜. Node history에 raw_layers 동봉.
- **Grok 실시간 검색** (`tools/news/grok_live.py`) — xAI **Agent Tools API**(`/v1/responses` + web_search·x_search). 구 Live Search는 410 제거됨. 시장 서사를 출처 URL과 함께. RA-외부의 핵심 수집기.
- **Brave 뉴스** (`tools/news/brave.py`) — 유닛별 검색어로 최신 기사.
- **비용 표시** — CostMeter(provider별 토큰·USD), 답변 하단 바 + trace layer. Grok은 xAI `cost_in_usd_ticks`(웹검색비 포함, tick/1e9=USD 실측 확정) 사용.
- **UI** — 마크다운 렌더링, 답변 과정 접이식 재보기, 모드 잠금(3사+xhigh 고정)+안내, 스크롤바 숨김, 넓은 레이아웃, 면책문 제거.

### 실측으로 잡은 것
- **`gpt-5.5-mini` 미존재** → 모든 경량 콜이 몰래 Fable 폴백 중이었음. `gpt-5.4-mini`로 수정 (비용·속도 왜곡의 숨은 원인).
- **`grok-4`는 검색 미지원** → `grok-4.3` (Agent Tools).
- Anthropic structured output: 정수 min/max·자유 dict·additionalProperties 제약 → 모든 SO 스키마는 extra=forbid + 코드 clamp.

### QA 결과 (5경로 전부 통과)
개념질문(tier0 뉴스off)·잡담(smalltalk)·주문차단(tier4)·deep(grok 실데이터)·followup(raw 재사용) 모두 정상. 라우팅·비용·layer·degraded 정확.

### codex 공동 리뷰 → 수정 완료
- ✅ [Major] `plan.search_queries` 계약 누락 → Brave 항상 AttributeError degrade. 필드 추가로 해결 (degraded 사라짐 확인).
- ✅ [Major] PLAN 병렬 2콜 return_exceptions 없음 → 한쪽 실패 시 파이프라인 중단. 폴백 추가.
- ✅ [Major] synthesize 미보호 → 합성 실패 시 final 없이 종료. try+DA 폴백으로 final 보장.
- ✅ [Major] RA 전체 실패가 skipped로 숨겨짐 → error 구분 + degraded 반영.
- ✅ [Major] Node disconnect 시 producer task await 안 함 → await로 정리 보장.
- ✅ [Major] 프롬프트 인젝션 방어 → 합성 프롬프트에 외부 텍스트 격리 규칙.
- ✅ [Minor] tier4 answer_markdown 빈 문자열 → 차단 메시지 채움. meter role KeyError 방지.
- 남김(엣지/운영): Role client 미close(SDK가 세션 관리 시 무해), fallback 중 parse 실패 시 usage 누락(SDK가 resp 미반환이라 불가피), /v1/answer 인증(내부망 전용 — 배포 설정 몫), toss_company 종목별 status 덮어쓰기(부분실패 표기).

### 남은 품질 게이트 (다음)
CALC 결정적 계산 연동 · VERIFIER G1~G4 · RISK 별도 스테이지 · AUDITOR 사후검증 · ASSEMBLER 충돌해소 · REFLECT 루프. (현재는 합성 프롬프트가 규율 인코딩)
