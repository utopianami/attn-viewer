# dexter (virattt) 심층 분석 — 에이전틱 루프 참고 (2026-07-08)

> 사용자 지정 핵심 레퍼런스. 로컬 클론(커밋 `bae66167`, 2026-07-03) 소스 직접 확인 + GitHub API·웹 검증 (2026-07-08).
> **[코드]** = 소스에서 직접 확인 / **[웹]** = README·트윗·외부 글.

## 1. 개요

- "An autonomous agent for deep financial research" — 저자 표현 "Think: Claude Code, but for finance" [웹].
- 저자 virattt = ai-hedge-fund(43k+ 스타) 저자. ⭐ **27,333** · 포크 3,392 · 생성 2025-10-14 · 최근 push 2026-07-03 (GitHub API, 2026-07-08 확인).
- 스택 [코드]: TypeScript + Bun, LangChain core 멀티 프로바이더(기본 gpt-5.5), Ink 터미널 UI, WhatsApp 게이트웨이, 크론, LangSmith 평가. 데이터: Financial Datasets API.

## 2. 에이전틱 루프 — 핵심 발견

### 고정 파이프라인도 플래너-실행자도 아닌, Claude Code식 단일 자율 도구-루프 [코드: src/agent/agent.ts]

```
while (iteration < 10):                  // DEFAULT_MAX_ITERATIONS
  microcompact → stripOldThinking (최근 2개만 reasoning 유지)
  → LLM 스트리밍 (전체 도구 bind)
  → tool_calls 없음 = 최종 답, 종료
  → tool_calls 있음 = 병렬 실행 (concurrencySafe 배칭, 최대 10 동시)
  → 대형 결과 디스크 영속 + 프리뷰만 주입, 턴당 토큰 예산 강제
  → 컨텍스트 임계 초과: memory flush → LLM 압축 → 실패 시 절단
  → 도구 사용 현황 경고를 HumanMessage로 주입
```

- 별도 PLAN 단계 없음 — 계획은 시스템 프롬프트 정책 + 스킬 체크리스트 + 서브에이전트 위임으로 **창발**.
- 반복 심화 = `spawn_subagent`: 타입(general-purpose/research/analysis)별 {전용 프롬프트, read-only 도구 allowlist, maxIterations 8} 번들. 독립 태스크는 한 턴에 여러 개 emit → 병렬. 재위임 금지(1단계 깊이).

### ★ 역사적 사실: v1은 우리 엔진과 같은 구조였고, 저자가 버렸다

- 초기 커밋(`ec54a2f9`, 2025-10-30)의 `src/dexter/agent.py` [코드 확인]: **명시적 플래너-실행자-검증자** — `plan_tasks()` → 태스크별 (`ask_for_actions` → 도구 실행 → `ask_if_done` 검증) → `_generate_answer()`. max_steps 20, 태스크당 5스텝, 동일 액션 4회 반복 감지.
- **Dexter 2.0** (2025-12, TS 재작성)에서 이 골격을 제거하고 자율 루프 + 가드레일로 전환. "reduced loops 등으로 73% 빨라졌다" 트윗 [웹].
- 해석: "plan→execute→validate 고정 골격"을 직접 운영해 본 저자가 **모델에게 제어권 + 한도·압축·기록으로 감싸는 하네스** 쪽으로 이동.

## 3. 도구 구성 [코드: src/tools/registry.ts]

- 등록 단위: `{name, tool, description(장문), compactDescription, concurrencySafe}` — 시스템 프롬프트에는 **compact 설명만**(토큰 절약), 전체 스키마는 bindTools로.
- **메타 도구 패턴** (핵심): `get_financials`는 자연어 쿼리 1개 → 내부 라우터 LLM이 세부 도구 8개 중 선택 → **병렬 실행** → 포매터 정리 + sourceURL 반환. "ONCE with the full natural language query, 쪼개지 마라"를 프롬프트로 강제 — 상위 루프 반복 절약.
- web_search는 Exa/Perplexity/Tavily/LangSearch 키 존재 시 조건부 등록 폴백 체인.
- **스킬 시스템**: SKILL.md(frontmatter name/description) 기반, 빌트인 3개(dcf, write-memo, x-research) + 유저 디렉토리. 메타데이터만 상시 노출, 본문은 호출 시 로드, 쿼리당 1회 dedup.

## 4. 검증·품질 — 명시적 게이트 없음, 소프트 장치 4종 [코드]

1. **소프트 리밋 + 경고 주입** (scratchpad.ts): 도구당 제안 한도 3회, 쿼리 Jaccard 유사도 ≥0.7이면 "거의 같은 쿼리다 — 다른 도구/다른 검색어/갭 인정 중 택하라" 경고. **차단하지 않고 항상 허용 + 경고만**. 매 턴 도구 사용 현황 주입.
2. **숫자**: CALC류 코드 계산 없음. 압축 프롬프트가 "모든 핵심 숫자 보존" 필수 섹션 강제 + DCF 스킬에 절차적 검증 체크리스트(계산 EV가 보고치 ±30% 이내, 터미널 밸류 50-80% 등) — 검증이 엔진이 아니라 **스킬 문서 안에** 산다.
3. **자기 교정**: 도구 에러가 ToolMessage로 들어가 다음 반복에서 재시도하는 루프 내재 교정뿐. REFLECT 패스 없음.
4. **평가 하네스** (src/evals/): 237행 금융 QA 데이터셋(질문/정답/유형/전문가 소요시간/rubric) + LangSmith + LLM-as-judge. "Claude Code 대비 속도 92%·비용 26%·정확도 31% 우위" 주장 [웹 — 자체 테스트, 독립 검증 아님].
5. `SOUL.md`: 버핏·멍거 철학("invert always invert", margin of safety) 주입 — 반대시나리오를 구조가 아닌 **성격**으로.

## 5. 메모리·컨텍스트 [코드]

- **쿼리 스크래치패드**: `.dexter/scratchpad/*.jsonl` append-only (감사 로그 + 압축 원본).
- **4단 계단식 컨텍스트 관리**: stripOldThinking → microcompact(무LLM, 오래된 도구 결과 마커 치환) → full compaction(fast model, 9섹션 구조화 요약 — 숫자 전수·에러·**미수집 데이터·다음 단계** 포함 → 압축이 곧 재계획 문서) → 절단 폴백.
- **장기 메모리**: 압축 직전 memory flush ("내구성 사실·선호·결정만, 시장 데이터·주가 저장 금지") → 마크다운 + SQLite 하이브리드 검색(벡터 0.7+키워드 0.3), temporal decay(반감기 30일, evergreen 면제), MMR 다양성.

## 6. ai-hedge-fund와의 차이

| | ai-hedge-fund (2024~) | dexter (2025-10~) |
|---|---|---|
| 구조 | LangGraph 고정 그래프 (페르소나 병렬 → 리스크 → PM) | 자율 도구-루프 |
| 입력 | 티커 — 항상 같은 파이프라인 | 임의 질문 — 질문마다 경로 다름 |
| 목적 | 트레이딩 신호 시뮬레이션 | 오픈엔디드 딥 리서치 |

## 7. 우리 엔진에 가져올 것 / 안 가져올 것

**가져올 것** (요약 — 상세는 개선 계획 페이지):
1. 스킬 = 질문 유형별 처리(템플릿·CALC 공식·검증 룰)를 선언 파일로 — 코드 수정 없이 유형 확장.
2. 서브에이전트 타입 레지스트리 — {프롬프트, 도구 allowlist, 예산} 번들.
3. 단순 질문 즉답 정책 한 줄 ("개념 정의·안정적 과거 사실만 직접 답").
4. 소프트 리밋 + 유사 쿼리 감지 + 대안 3개 경고 — REFLECT 폭주 제어.
5. 메타 도구 — 수집기를 "자연어 1콜 → 내부 경량 라우팅 → 병렬 → 출처 포함 정형 반환"으로.
6. 계단식 컨텍스트 관리 + 압축에 "미수집/다음 단계" 필수 포함.
7. 압축 전 memory flush.
8. 대형 결과 디스크 영속 + 프리뷰, concurrencySafe 병렬 배칭, append-only JSONL 스크래치패드.
9. rubric 있는 평가 데이터셋 + LLM 심판 하네스.

**안 가져올 것**: LLM 산술(우리 CALC가 우위) · 명시적 검증 게이트 부재 · claim table 부재 · RISK 부재 — 전부 dexter의 약점이고 우리의 경쟁 우위. **루프 자율화를 가져가더라도 CALC·게이트·claim table은 유지.**

## 출처

[코드] 클론 커밋 `bae66167` (2026-07-03), 초기 구조는 커밋 `ec54a2f9` (2025-10-30) `src/dexter/agent.py`.
[웹, 2026-07-08 확인] GitHub API (⭐27,333) · README · 트윗(런칭 1978224884464357579 / 2.0 1997770360209453322 / 벤치 1997094009026523539 / 73% 1990905431200575565) · andrew.ooo 리뷰.
