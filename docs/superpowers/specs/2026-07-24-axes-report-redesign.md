# 시황 리포트 v2 — 3축 카드 재설계 (2026-07-24)

사용자 지시(2026-07-24 오후): 기존 결과물(주장 카드·최종의견·종합·블로그체 완결 글)을
**전부 제거**하고, 3축 카드를 가로 스와이프로 보는 형태로 교체. 첫 버전 오늘 21:00 KST
자동 회차. 수치 기반, 가독성 우선.

## 결과물 정의

카드 3장 (가로 스와이프 [] [] []):

1. **매크로 축** — 거시에 집중한 현상 분석
2. **메모리 축** — 메모리 관점의 현상 분석
3. **그 외 축** — 나머지 이슈 중 가장 중요한 것 하나

각 카드의 내부 구조 (전 항목 수치 기반, 〔근거〕/〔가정〕/〔계산〕 라벨 유지):

```
현상 분석 (무슨 일이 있었나 — 팩트·수치 먼저)
  ↓ (필요하면)
주제 선정 후 추가 연구 (웹) — 예: "키미3가 나스닥을 흔들었다" 현상이면
  → 키미3가 학습 개선인지 인퍼런스 개선인지 논문·자료 확인
  → AI 회사들의 지출 구조 확인
  → 결론 도출 (예: 딥시크 때와 달리 메모리 수요는 오히려 증가)
  ↓
긍정 시나리오 / 부정 시나리오 (각각 성립 조건 명시)
  ↓ 각 시나리오마다
직접 / 간접 수혜(피해) 섹터·주식 — 2차 전이 인사이트 포함
  (예: 구글 클라우드 호실적+CAPEX 증액 → 메모리에도 좋지만 전력 인프라에 더 좋다)
  ↓ (필요하면)
해당 섹터/종목 재무분석 + 현재 상황 분석 (밸류에이션·실적 수치)
```

## 파이프라인 재설계

재사용(검증된 기존 부품): report_input(수집·창), f1/f2/f3 필터(이벤트 클러스터),
anchors(수치 앵커), macro_brief(거시 관측+중요도 게이트), casemem 대조,
run_research(웹 조사, 질문당 360s 예산), audit_article 수치 스윕, cli_role/Role 폴백.

제거(v2 경로에서 미사용): deepen→synth→verify→revise→draft→compose 체인 전체,
완결 글(article), 주장 카드(claims 노출), 최종의견/종합 노출.
(코드는 유지 — settings.report_format="axes"|"legacy" 플래그, 기본 axes. 롤백용.)

새 스테이지 (sector/report_axes.py):

```
[1] axis_split (LLM 1콜, CLI opus high, 상한 900s)
    입력: f3 이벤트 클러스터 + macro_brief + anchors 요약
         + f2 통과 항목 제목 최대 60개 (codex r1 H2: f1 관련성 필터가 비메모리
           최중요 이슈를 제거할 수 있어 — "그 외" 축 후보 보충 채널)
    출력(AxisPlan): 축 3개 각각 {axis_id, 배정 이벤트, 핵심 현상 후보(수치 포함),
                    비고}. "그 외" 축은 중요도 근거를 명시해 1개 이슈 선정.
[2] 축별 순차 (CLI 동시 실행 금지 — 로컬 자원):
    [2a] phenomenon (LLM 1콜/축, 상한 800s)
         현상 분석 작성(팩트·수치 먼저) + 추가 연구 필요 판단
         → research_questions 0~2개 (질문·이유·기대형태·검색힌트)
    [2b] research (조건부, run_research 재사용, 질문당 360s, 축당 상한 1000s)
         출처 있는 발견만 '근거' 라벨 — 없으면 해당 논점은 '가정' 강등
    [2c] scenarios (LLM 1콜/축, 상한 800s)
         긍정/부정 시나리오 + 시나리오별 직접/간접 수혜(피해) 섹터·종목
         + 필요시 재무·현황 미니 분석. 연구 결과·앵커 수치만 인용.
[3] assemble_axes (코드)
    카드 3장 조립 + audit_article 수치 스윕(라벨 없는 수치 ⚠각주)
    + 실패 축은 카드에 실패 사유 명시(전 축 실패해도 리포트는 발행 — 진단 카드)
```

시간 예산(codex r1 H1 반영 — 이전 초안은 최악 합이 하드캡 3h 초과):
axis_split 900 + 3×(800+1000+800) = 8,700s ≈ 2.4h < 3h. 필터 단계(~10분) 포함
최악 2.6h. 통상 LLM 11콜×~2.5분 ≈ 30~40분.

발행·재시도 계약 (codex r1 H3): infra_wiped()가 claims로 인프라 전멸을 판정하므로
axes 리포트가 매번 재시도로 오판될 수 있다 → format=="axes"면 cards 기준으로 판정.
publish_status: axes는 주장 검증 체인이 없으므로 "에러 아닌 카드 ≥1"이면 ok,
전 축 실패면 hold. UI 배너는 axes에서 카드 실패 수만 표시.

## 계약 (report_contracts.py 추가)

```python
class AxisBeneficiary(BaseModel):
    name: str                    # 섹터 또는 종목명(티커 병기)
    kind: Literal["sector", "stock"]
    direction: Literal["direct", "indirect"]   # 직접/간접
    polarity: Literal["benefit", "damage"]
    rationale: str               # 전이 경로 — 수치 라벨 포함
    financials: str = ""         # 필요시 재무·현황 미니 분석

class AxisScenario(BaseModel):
    polarity: Literal["positive", "negative"]
    thesis: str                  # 시나리오 서술 + 성립 조건
    beneficiaries: list[AxisBeneficiary]

class AxisCard(BaseModel):
    axis: Literal["macro", "memory", "other"]
    title: str                   # 수치 포함 헤드라인 (내부 용어 금지)
    phenomenon: str              # 현상 분석 (markdown, 수치 라벨)
    deep_dive: dict = {}         # {"topic": str, "findings": [...], "conclusion": str}
    scenarios: list[AxisScenario]
    watch_signals: list[str] = []
    sources: list[dict] = []     # 연구 출처 (url·title·published)
    error: str = ""              # 축 실패 시 사유

Report: cards: list[AxisCard] = [] + format: Literal["legacy","axes"] = "legacy"
```

openapi.yaml 동반 갱신(계약 우선).

## 프롬프트 원칙 (기존 사용자 피드백 전부 승계)

- 수치 기반: 모든 수치 〔근거: 출처〕/〔가정〕/〔계산: 식〕 라벨, 증감률은 분모(MoM/QoQ/YoY) 병기
- 내부 프레임 용어(국면N·단계명) 독자 텍스트 금지, 업계 용어·티커는 첫 언급 정의
- 면책 문구 금지, TL;DR성 요약이 카드 앞부분(현상 분석 첫 3~4불릿)
- 거시 ⚠중요 항목은 매크로 축 현상 분석에 강제 포함
- 추측 금지 — 연구로 확인 못 하면 '가정' 라벨로 정직하게
- 미검증 단정 금지: 시나리오는 "성립 조건"과 함께 조건부로 서술 (hold 게이트의 정신 승계 —
  v2는 주장/검증 체인이 없으므로 시나리오 조건부 서술 + 수치 스윕이 안전장치)

## UI (public/report.js)

- 상세 화면: r.format=="axes"면 카드 3장 가로 스와이프(CSS scroll-snap-x, 한 장 = 뷰포트 폭,
  하단 도트 인디케이터). 카드 내부: 제목 → 현상 분석 → (추가 연구 접이식) → 시나리오 2개
  (긍정 초록/부정 빨강 보더) → 수혜 섹터·종목 테이블(직접/간접 뱃지) → 관찰 신호.
- 기존 주장 카드·최종의견·종합·본문 렌더는 legacy 리포트에만.
- 사고흐름(디버그 접이식)은 유지.
- 모바일 우선(390px), 스크린샷 검증 필수.

## 리스크·완화

- 21:00 데드라인: 구현 후 수동 1회 실행(~40분)으로 검증할 시간이 없으면 21:00 회차가
  첫 실행 — 축별 never-raise(실패 축은 에러 카드)로 전체 실패 방지.
- CLI 혼잡: 질문 수 상한(축당 3), 스테이지 예산 명시.
- legacy 롤백: REPORT_FORMAT=legacy 환경변수 한 줄.
