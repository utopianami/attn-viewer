# 과거 사례 지식층 (Case-Memory Knowledge Layer) — 설계

작성일: 2026-07-21 · 상태: 설계(초안, 사용자 리뷰 대기)
관련: [설계 스냅샷](/html/market-report-design.html) §5·§7 · [금융 코퍼스 인벤토리](../../2026-07-21-financial-corpus-inventory.md) · [아키텍처 조사](../../2026-07-21-case-memory-architecture-research.md) · 선행 [memory-rag-plan_codex](../../memory-rag-plan_codex.md) · [memory-chain-answer-design](2026-07-20-memory-chain-answer-design.md)

---

## 1. 목적 & 한 줄 정의

메모리 반도체 데일리 리포트가 **"오늘 관측이 과거 어느 사이클의 어느 국면과 닮았고, 그 다음엔 뭐가 왔나"**를 물을 수 있게 하는 **과거 사례 지식층**을 만든다. 리포트는 이 층을 **API로만** 질의한다.

리포트의 킬러 기능(설계문서 §5)은 엔티티 다중홉 탐색이 아니라 **한 사례 안의 시간 순서(국면 시퀀스) 매칭**이다. 따라서 이 층의 본질은 지식그래프가 아니라 **사례 기반 추론(CBR, Case-Based Reasoning)**이다.

## 2. 스코프 & 2단 깊이 (2026-07-21 확정)

| 사례 | 깊이 | 표현형 | 소스 |
| --- | --- | --- | --- |
| **메모리 반도체 사이클** | 풀 케이스 | `CaseEpisode` (국면 시퀀스 + 정량 백본 + 근거) | 반도체 IR·한경컨센·SemiAnalysis·SIA/WSTS·Stanford DAM·ranto28 블로그 |
| **그 외 모든 위기** (닷컴·GFC·COVID·아시아'97·일본버블·국채·오일…) | 규칙만 증류 | `DistilledRule` = **기존 playbook 스키마** | Howard Marks·FOMC·JST·IMF·FCIC 등에서 패턴만 |

원칙: **"메모리는 사례로, 나머지는 규칙으로."** 원장 전체를 다운로드하지 않는다.

**비목표(Non-goals):** 실시간 뉴스/카드 수집(이미 `engine/sector/`가 담당) · 가격 축 심화(yvon 담당) · 범용 금융 QA · 전용 벡터/그래프 DB 도입.

## 3. 아키텍처 — 3-레이어 분리

**L1 — 지식 머신 (섹터 무관·재사용).** 수집→구조화(추출)→저장→검색 머신. 코드에 "메모리" 없음. 입력=도메인 팩, 출력=사례 카드 + 증류 규칙 + 검색 인덱스. 기존 `engine/sector/` + playbook 머신의 일반화.

**L2 — 메모리 섹터 팩 (인스턴스·데이터).** 코드가 아니라 설정+시드: 코퍼스 목록, 엔티티 사전(SAMSUNG·SK_HYNIX·MICRON·HBM…), 2단 깊이 배정, 메모리 전용 추출 프롬프트. 다른 섹터 = 새 팩 추가로 끝. L1 불변.

**L3 — API 경계 (소비자).** 데일리 리포트는 저장소를 직접 안 뒤지고 안정 API로만 질의. OpenAPI-first. orchestrator 스테이지 + 엔드포인트로 붙음.

기존 레포 매핑: L1 규칙 파트 = 기존 playbook 스토어(24개) · L1 사례 파트 = **신규** · L3 = orchestrator 주입 지점(기존 `sector_rag` 패턴 그대로) + openapi.

## 4. 데이터 모델

### 4.1 공통 — Bitemporal (룩어헤드 차단의 핵심)

모든 레코드에 두 시각을 둔다:
- `event_time` — 사건이 실제 일어난 때 (valid time)
- `knowable_at` — 그 사실을 **알 수 있게 된 때** (transaction time)

검색은 항상 `knowable_at <= T` **as-of 필터**를 건다. valid-time만 쓰면 미래 정보가 새어든다. 이게 규칙 확신도 백테스트 정직성의 토대이며 memory-chain 가드레일과 일치한다.

### 4.2 `CaseEpisode` (풀 케이스 — 메모리 사이클)

```
CaseEpisode
  id                 "mem-2018-downcycle"
  sector             memory            # L2가 채움. L1은 문자열로만 취급
  title, summary
  phases[] (순서 있음)
    order            0,1,2,3…
    label            capex_expansion → inventory_build → price_break → capitulation
    period           {start, end}      # event_time 범위
    knowable_at      국면이 식별 가능해진 시점
    identifying_signals[]   그 국면을 "당시에" 식별시킨 지표·이벤트 (구조화, point-in-time)
    quant_backbone[]        겹쳐볼 시계열 ref (metric_name + 기대 방향)
    evidence[]              당대 근거 인용 {source, grade, quote, url, knowable_at}
    next_phase_ref          다음 국면
  outcome            사후 실제 전개 (postmortem — evidence로만, signal 아님)
  supports_rules[]   / refutes_rules[]     # DistilledRule / playbook 링크
```

**불변식:** `identifying_signals`에는 그 국면 `knowable_at` 시점에 알 수 있었던 것만. 결과(`outcome`)를 signal로 역주입 금지.

### 4.3 `DistilledRule` (그 외 위기 → 기존 playbook 스키마)

새 스토어를 만들지 않고 **기존 `schemas/playbook.schema.json`**에 담는다(situation·triggers·gates·connection·reservations·asOf). 단 `status`는 검증 전까지 `holdout_passed`가 아니므로 리포트에 주입되지 않는다(기존 게이트 재사용). 출처 사례를 `provenance`로 표기(예: `"1990s Japan bubble"`).

## 5. 검색 — MAC/FAC 하이브리드 (전용 DB 없음)

CBR의 핵심 위험은 **표면 유사 vs 구조 유사**다. "2018 글럿 같다"는 구조적 주장인데 키워드/임베딩은 "메모리"라는 단어만 겹치는 가짜 유사를 물어온다. 고전 해법 MAC/FAC(싼 표면 프리필터 → 구조적 리랭크)를 쓴다:

```
query(오늘 관측 signal 집합, asOf=T)
  1. as-of 필터   knowable_at <= T          # 룩어헤드 차단
  2. 메타 필터    sector·entity·segment
  3. BM25 표면    키워드/토픽 프리필터 → 후보 K
  4. (옵션) 임베딩  브루트포스, 벡터DB 없이  # 트리거 전엔 생략
  5. 구조 리랭크   LLM이 signal 조합의 구조적 정합성으로 재정렬
  → { matched_case, matched_phase, next_phases(=예측), supporting_rules, contradictions, evidence }
```

수십~수백 건 규모에선 메타데이터 품질 > 알고리즘(조사 근거: 메타 필터로 MRR 0.12→0.68). 전용 벡터/그래프 DB는 조기 최적화.

## 6. 인제스천 / 증류 파이프라인 (L1, 섹터 무관)

### 6.1 깊게 (메모리) — CaseEpisode 구축
```
코퍼스 → 청킹(문서형: contextual retrieval식 부모-자식) → 국면·타임라인 추출(LLM)
  → identifying_signals·evidence를 knowable_at로 스탬프
  → quant_backbone 시계열 조인(코드가 계산, LLM 산술 금지)
  → CaseEpisode append
```

### 6.2 얇게 (그 외 위기) — 규칙 증류 = **가설 깔때기**
```
코퍼스 훑기 → LLM이 (조건→귀결) 후보 규칙 추출 → status=candidate
  → 검증 게이트(§7) 통과분만 status 승격 → 리포트 주입 자격
```

**핵심 경고 — 파라메트릭 룩어헤드 편향:** 학습 컷오프 이후를 아는 LLM은 과거 규칙을 뽑을 때 결과를 가중치에서 흘린다(DB로 못 막음). 그래서 증류물은 규칙이 아니라 **가설**이다. 완화:
- 가능하면 **컷오프 맞춘 모델**로 증류/검증
- 검증 입력은 **point-in-time**(`knowable_at`)만
- **LLM 자가확신도로 규칙 가중 절대 금지** — 코드가 검증된 관계에서 집계

## 7. 검증 게이트 (규칙 확신도) — 하드 가드레일

memory-chain P2 블로커 계승:
- 확신도·assessment는 **LLM 자가평가 금지** → 코드가 forward-captured proven 케이스에서 집계
- **cross-review 전 live append 금지** (append-only는 되돌릴 수 없음)
- **verifier는 fail-closed**
- 백테스트는 **point-in-time**(`knowable_at`) 입력 + purged CV / PBO(Probability of Backtest Overfitting) / Deflated Sharpe로 과적합 방어
- 백테스트는 forward-captured proven 케이스로만 (사후 라벨 금지)

## 8. L3 API 계약 (OpenAPI-first)

```
POST /api/case-memory/query
  req:  { situation | signals[], asOf, sector, k }
  res:  { ok, matchedCases[], matchedPhase, nextPhases[], matchedRules[],
          contradictions[], evidence[] }        # 원문·grade·knowable_at 포함
GET  /api/case-memory/cases            # 목록/필터
GET  /api/case-memory/cases/:id        # 단일 에피소드(관측성)
```
`openapi.yaml`부터 정의 후 구현. orchestrator는 기존 `sector_rag` 주입 지점 패턴으로 SYNTHESIZE에 결과 주입 + AUDITOR가 수치 주장 검증.

## 9. 저장 레이아웃 (append-only JSONL)

```
storage/rag/case_memory/
  cases/{sector}/{episode_id}.json      # CaseEpisode 원본
  index.jsonl                           # 검색 인덱스(append-no-prune)
  # 규칙은 기존 storage/users/*/corpus/playbooks/ 재사용 (provenance 표기)
```
섹터 하위 디렉토리로 L2 다중 인스턴스 수용.

## 10. 에러 처리 & 관측성

- **never-raise:** 스킵/실패해도 사유 담은 결과를 다음 단계로(무성 누락 금지)
- 소스별 독립 실패(하나 깨져도 파이프라인 안 멈춤)
- 관측성: 어떤 케이스/규칙이 왜 매칭됐고 확신도가 어떻게 조정됐는지 노출(data-collection.html 현행화)

## 11. 테스트

- 국면 매칭 골든 세트 + holdout (기존 eval 프레임 재사용)
- point-in-time 백테스트(누출 회귀: 미래 signal 주입 시 fail)
- 스테이지 테스트는 수제 입력 + 실제 상류 출력 두 층

## 12. 단계별 롤아웃 & 확장 트리거

- **MVP:** 2-레이어 JSONL 유지 + 모든 레코드에 `event_time`·`knowable_at` + MAC/FAC(메타 as-of → BM25 → 구조 리랭크, 임베딩 없이) + 메모리 사이클 3~4개 CaseEpisode 시드 + 규칙 증류 깔때기.
- **임베딩 추가 트리거:** 어휘 불일치 미스가 반복되고 카드가 수천 건 넘을 때 — **그래도 브루트포스, 전용 벡터DB 없음.**
- **그래프 추가 트리거:** 진짜 다중홉 + 시간추론 + 대규모 성장이 동시에 올 때(아마 없음).

## 13. 스코프 컷 (YAGNI)

전용 벡터DB · 그래프DB · 실시간 사례 인제스천 · 11개 위기 풀 케이스화 · 유료 데이터(TrendForce/Omdia) 자동화 — 전부 MVP 밖.

## 14. 미해결 / 근거 얇은 지점 (조사 플래그)

- 중립적 agent-memory 리더보드 없음(벤더 셀프런) → 벤치 수치 신뢰 낮음
- 금융 프로덕션 CBR 공개 사례 없음 → 구조 리랭크 설계는 우리 검증 필요
- 학습 regime/crisis 임베딩과 LLM-CBR 사례층 융합은 오픈 갭
- 컷오프 맞춘 증류 모델 확보 가능성(운영) 확인 필요
```
