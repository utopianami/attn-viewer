# 시스템 전체 개선 계획 v2 (2026-07-06)

구성: §0 코덱스 안 대조 → §1~§4 RA(증거 수집) 개선 — 이번 사이클의 본체 →
**§5 전체 시스템 개선** (RA 밖 스테이지별) → §6 범위 밖.

> 입력 3원: ① 2026-07-03 품질 리서치(P1~P5 구현 완료분·잔존 약점 W1~W10) ② 코덱스 개선안
> (`docs/news-ra-improvement-plan.md`) ③ 2026-07-06 신규 발견 — grok 제거 후 상황 +
> **ryze-equity-harness kg.db 자산** (공시 재무·증권사 리포트·FTS, 코덱스·기존 리서치 모두 미인지).
> 예산 방향(사용자 확정): 품질 우선 — 질문당 +$0.2~0.3, +1분까지 허용.

---

## 0. 코덱스 안 대조 — 무엇을 흡수하고 무엇을 거르나

| 코덱스 제안 | 현행 상태 (2026-07-06 코드 기준) | 판정 |
|---|---|---|
| P0 retrieval_quality 게이트 (CRAG) | **~70% 구현됨** — curation(P1-2)이 문서 필터, answerability(P1-3)가 유닛별 충분성 판정+보완질문 재검색 | **증분 흡수** — 판정을 claim 추출 "앞"으로 당기고 bad→query rewrite 추가 (§2) |
| P0 unsupported_claim_sweep (CoVe) | **대부분 구현됨** — AUDITOR가 숫자 대조·신규사실 탐지·G4 재검사·인용 entailment(P5, provenance_soundness) | **증분 흡수** — source span 기록으로 entailment 정밀화 (§3) |
| P1 claim strength 라벨 (reported/likely/confirmed) | 없음 (uncertainty·corroborated_da만) | **채택** — 원인론 질문의 실질 개선 (§3) |
| P1 뉴스 숫자 → typed_fact 승격 | 뉴스 수치는 의도적으로 2차출처 claim (G1 담당) | **거부** — 뉴스 숫자를 계산 앵커로 승격하면 "CALC > 1차소스 > 뉴스" 우선순위가 무너짐. 같은 요구를 **공시 수치(kg.db)** 로 해결 (§1) |
| P1 독립 출처 수·source quality | 없음 | **채택** — strength 승격 규칙의 입력으로 (§3) |
| P2 adaptive retrieval budget | 없음 (W9 depth 레버와 동일 방향) | **채택 후순위** (§4) |
| P2 RA 평가셋·지표 | 골든셋 보류 중 (W1) | **변형 채택** — 골든셋 없이 되는 reference-free 상시 지표부터 (§4) |

코덱스가 못 본 것: ① kg.db 자산(공시 재무 observations 1,662건·증권사 리포트 28,815건·FTS 26만 청크가
같은 머신에 있음) ② x_search/brave_news 중복(같은 brave 뉴스 검색 2벌, URL dedup 없음 — 실측 중복 확인)
③ grok 제거로 인한 소스 공백.

---

## §1. 증거 소스 확장 — kg_search 수집기 + 뉴스 통합 [1순위, 최대 효과]

근거: FinTMMBench — 최고 시스템 오류의 46.5%가 retrieval (F6). 소스가 뉴스뿐인 것이 현 최대 구멍.

**1-1. `tools/kg/client.py` 신설** — 하네스 `ryze-equity-harness/data/kg.db` **읽기전용** 접속
(`file:...?mode=ro`, WAL이라 하네스 쓰기와 무충돌. 하네스 코드는 불변).
- `financial_facts(stock_code)`: observations(매출·영업이익·순이익·마진, period·known_at 포함)
  → **TypedFact 승격** (P3-2 토스 PER 승격과 같은 경로) → G2 앵커·CALC 입력.
  "영업이익 얼마?"가 뉴스 인용이 아니라 공시 수치로 답해짐. 코덱스 P1 typed_fact 요구의 올바른 해법.
- `search_documents(query, sources, since)`: raw_fts MATCH + 메타 join. 소스 필터 —
  tier3 판단 질문엔 `naver_research`(증권사 리포트), 사실 질문엔 `dart`(공시)·뉴스.
- `recent_filings(stock_code)`: raw_filings 최근 공시 제목 (유상증자·자사주 등 이벤트 포착).
- 모든 결과에 published_at/known_at 부착 — **오래된 데이터는 기존 G3 시점 게이트가 거름**
  (신선도 한계를 숨기지 않고 기존 안전망에 태움).

**1-2. ra_external에 `kg_search` 수집기 추가** (6번째, ticker/unit scope) — 수집기 단위 격리 동일:
kg.db 없음/잠김이면 그 수집기만 degraded.

**1-3. 뉴스 수집기 통합** — x_search를 brave_news에 흡수. 정제 검색어(search_queries)로
당일(pd)+주간(pw) 2단 freshness, **수집기 간 URL dedup 공유**. 구어체 질문 문장 검색 제거(W7 부분 해소).
절약된 검색콜(질문당 ~3콜)은 그대로 절감.

**1-4. 신선도 확보 — 하네스 최소 수집 트랙 주기화** (2026-07-06 조사로 확정, 나이브 읽기 금지)

조사 결과(하네스 코드 실사): 적재가 멈춘 건 파이프라인이 없어서가 아니라 **크론 미설치** 때문.
하네스에는 이미 ① 멱등·워터마크 증분 적재(`pipeline_watermarks`, 반복 실행 안전)
② 자동화 스크립트(`scripts/refresh_hourly.sh`) ③ systemd 타이머 설치기(`deploy/install-cron.sh`)
④ 단일 writer 락(`flock data/.writer.lock`)이 전부 구현돼 있음.

- 엔진이 필요한 건 **수집(ingest) 계열만**: `ryze ingest raw`(DART 미러→공시),
  `ingest financials --source dart`(재무 observations), `ingest research --pages 1`(증권사 리포트 증분).
  하네스의 무거운 LLM 가공(fill/reflect/embed — 로컬 q35로 시간 단위)은 엔진에 불필요 —
  그건 하네스 메모리 합성용이라 범위에서 제외.
- 실행안: **일 1회 "최소 수집 트랙" 타이머** (ingest 3종 + FTS 인덱싱) — LLM 없이 수십 분 내.
  기존 writer 락을 그대로 써서 하네스 자체 크론이 나중에 켜져도 충돌 없음.
- 확인 필요 1건: 리포트 PDF 본문 텍스트(raw_text/FTS 반영)가 ingest만으로 채워지는지,
  index-raw 단계가 필요한지 — 구현 시 1회 실측으로 확정.
- 마스터 DB는 `/shared/ryze/data/kg.db` (3.1GB, 레포 data/는 심링크) — 엔진은 이 경로를
  읽기전용(`mode=ro`)으로. 읽기는 다중 세션 안전 (하네스 규약 확인).
- **신선도 가시화**: 엔진 healthz·answer_meta에 kg 최신 적재 시각(`MAX(ingested_at)`) 노출 —
  타이머가 죽으면 보이게 (침묵 저하 금지). 시점 게이트(G3)는 published_at/known_at 기준으로
  오래된 수치를 최신인 척 못 쓰게 하는 2차 안전망.
  참고: 라이브 소스(brave 뉴스·토스·야후 시세)는 질문 시점 실시간 수집이라 신선도 관리 대상 아님 —
  관리 대상은 kg.db(공시·재무·리포트) 하나뿐.

대안(기각): 엔진에 DART OpenAPI·네이버 리서치 수집기를 신규 구축 — 하네스와 수집 로직
이중화, 유지보수 2벌, as-of 규약 재구현 필요. 하네스 자산 재사용이 명백 우위.

**1-5. 하네스 재사용 인벤토리 — 우리가 돌릴 것 / 안 돌릴 것** (2026-07-06 확정, 아직 계획만)

돌릴 것 (일 1회 "최소 수집 트랙", 전부 기존 명령 — 신규 코드 없음):

| 순서 | 명령 | 하는 일 | 입력/의존 | 산출 (kg.db) | 예상 소요 |
|---|---|---|---|---|---|
| 1 | `ryze ingest raw` | `/shared/dart` 미러의 당일 공시 XML을 목록·원문으로 적재 | 미러만 (외부 API 無) | raw_filings | 수십 초 |
| 2 | `ryze ingest financials --all --source dart` | 공시 XML에서 요약재무 파싱 → 재무 수치 | 미러 + extractors/.venv | observations (매출·영업이익·순이익·마진) | 분 단위 |
| 3 | `ryze ingest research --pages 1` | 네이버 금융 리서치 목록 증분 크롤 → 증권사 리포트 메타+PDF | 네트워크 | raw_documents(naver_research) | 분 단위 |
| 4 | (실측 후 확정) `index-raw` 상당 | 신규 원문 텍스트 추출·FTS 인덱싱 — 리포트 PDF 본문이 ingest만으로 raw_text에 들어가는지 1회 실측 후 포함 여부 결정 | 로컬 (LLM 無 확인 필요) | raw_text · raw_fts | 분 단위 |

실행 전제: `bin/ryze` 바이너리 + `extractors/.venv` 존재 확인, `flock data/.writer.lock`으로
단일 writer 준수, 실패해도 엔진은 기존 데이터로 계속 (수집기 degrade와 동일 사상).

안 돌릴 것 (이유 명시):

| 명령 | 이유 |
|---|---|
| `fill` (LLM distill) / `reflect` / `classify-mem` | 하네스 메모리 합성용 — 엔진은 원문·수치만 필요. 로컬 q35로 시간 단위 부담 |
| `embed-raw` / `embed-memory` | 임베딩 검색용 — 엔진 v1은 FTS(키워드)만 사용 |
| `ingest news` / `ingest toss` | 엔진이 이미 brave·토스 라이브 수집 보유 — 이중 수집 불필요 |
| `ingest macro` (FRED) / `events` (FOMC) / `sec` | 엔진 매크로는 야후 수집 존재, 미국 공시는 범위 밖 |

엔진(kg_search)이 읽는 것: observations(재무→TypedFact), raw_filings(최근 공시 목록),
raw_fts→raw_text/raw_documents(리포트·공시 본문 검색), provenance(출처 체인).

## §2. 증거 판정 전진 — retrieval_quality (코덱스 P0 증분)

현행: 수집 → curation(문서 필터) → claim 추출 → … → answerability(유닛 충분성)·REFLECT.
문제: 검색이 통째로 빗나간 유닛도 일단 claim 추출까지 감 (토큰 낭비 + 약한 근거 승격 위험).

- curation mini 콜에 유닛별 `retrieval_quality: enough|ambiguous|bad` 필드 추가 (**추가 콜 0**).
- `bad`: claim 추출 제외 + **query rewrite 1회 재검색** (mini가 검색어 재작성 — CRAG corrective).
  rewrite 후에도 bad면 그 유닛은 unobtainable 계열로 answerability에 전달.
- `ambiguous`: 추출은 하되 해당 유닛 claim에 약화 마킹 → G1 심판에 전달.
- 기존 answerability·REFLECT는 그대로 (2차 안전망) — 라운드 상한 2 공유 불변.

## §3. claim 강도·출처 정밀도 (코덱스 P1 흡수)

- **causal claim strength**: 원인 서술 claim에 `strength: reported|likely|confirmed` 부여.
  승격은 프롬프트 소원이 아니라 **코드 규칙**: reported(기사 1개) → likely(독립 도메인 2+ 또는
  리포트 동조) → confirmed(가격/실적 typed_fact와 결합). SYNTH 서술 규칙: reported는
  "~라는 보도가 있다", confirmed만 단정. 단일 출처 과잉 추론(코덱스 실패모드 2) 차단.
- **source span**: claim 추출 시 근거 문장 발췌(`ref_span` ≤200자) 저장 →
  AUDIT 인용 entailment이 본문 전체가 아니라 span 대조로 정밀·저렴해짐.
- **독립 출처 카운트**: assemble에서 claim_key별 서로 다른 도메인 수 집계 → strength 입력 + 답변 표기.

## §4. 운영·측정 (코덱스 P2 변형 + W1·W9)

- **상시 검색 품질 지표** (골든셋 불요, reference-free): §2의 retrieval_quality 분포 +
  유닛별 증거 충분도 + provenance_soundness(기존)를 answer_meta에 노출 → 추이 관찰.
  골든셋(P0)은 계속 보류 — 피드백 쌓이면 재개 (2026-07-03 결정 유지).
- **adaptive budget** (후순위): tier 0-1은 검색 유닛·DA effort 축소, tier 3·richness C는 현행 유지.
  W9(간단 질문도 풀 파이프라인) 해소. 품질 회귀 위험이 있어 상시 지표 확보 **후** 착수.

## §5. 전체 시스템 개선 — RA 밖 스테이지별

> 원천: 2026-07-03 약점 W1~W10 중 미해소분 + 2026-07-06 비용 개편 후속. RA(§1~4)와
> 독립적으로 진행 가능. 우선순위는 "측정 → 병목 → 편의" 순.

**5-1. 모델·effort 실측 A/B [측정, 0.5일]** — 오늘 fable→opus·DA high→medium·OpenAI effort
실전달이 한꺼번에 바뀜. 대표 질문 5~10개로 전후 답변을 나란히 비교해 품질 회귀 없는지 확인.
통과 시 **sonnet-5 부분 도입 실험**(risk·plan_extract 폴백 등 경량 심판부터, $2/$10) — 판정
일치율로 채택 결정. 임시 기본값 + A/B 프레임 (즉흥 전환 금지).

**5-2. G1 심판 캘리브레이션 (W3) [검증 품질, 1일]** — 심판(opus/gpt)의 supported/unsupported
판정이 맞는지 검사한 적 없음. 실런 verify layer에서 판정 30~50건 표본 추출 → 수동 라벨 →
정밀도/불지지 recall 측정 (F2: 게이트 품질은 불지지 recall로 봐야 저분해 회귀가 보임).
결과에 따라 G1 프롬프트·샤드 크기 조정.

**5-3. followup·멀티턴 강화 (W4·W6) [체감 품질, 1~2일]** — followup 경로는 P3-4로 mini
프리패스+brave 1쿼리가 붙었지만, 이제 kg_search(§1)도 태울 수 있음 (직전 턴 티커의 재무
facts 조회는 로컬이라 공짜). 멀티턴 참조 해소("그럼 작년엔?")는 대화 5턴+ 시나리오 3개로
실측 후 history 계약 보강 여부 결정 — 측정 전 구현 금지.

**5-4. depth 레버 / adaptive budget (W9) [비용·지연, 1일]** — §4와 동일 항목 (전체 시스템
관점에서 재기술): tier 0-1 질문은 서브질문 상한·DA effort·검색 유닛을 축소해 30초~1분·$0.2급
경로 신설. UI thinkLevel과 연결하면 v2 계획의 depth_profile 훅도 소화. 상시 지표(§4) 확보 후.

**5-5. RISK 근거 다양성 (W10) [판단 질문 품질, 0.5일]** — contrast 검색 결과(반대 근거)가
RISK 스테이지에 직결 안 됨. RaPacket의 contrast 유닛 증거를 RiskPacket 입력에 명시 전달 —
"검증된 claim 위에서 논증만"이라는 현 설계는 유지하되 반대 방향 증거를 빼먹지 않게.

**5-6. 평가 자산 (W1) [지속 개선의 전제]** — 골든셋은 계속 보류(7/3 결정)하되, 두 가지는
지금 가능: ① §4 상시 지표 ② 피드백(👎) → 골든 후보 큐 적재 (P0-4 설계 재사용, 수동 승격).
피드백이 20건+ 쌓이면 골든셋 재개 판단.

## §6. 범위 밖 백로그 (명시)

- 하네스 kg.db 적재 주기화 (cron) — 하네스 repo 과제
- 커뮤니티/소셜 수집, grok 재도입 — 하지 않음 (노이즈가 정확도를 깎음 F6, 비용 대비 유효성 낮음)
- 뉴스 숫자의 typed_fact 승격 — 하지 않음 (§0 거부 사유)
- 모드 카탈로그(pulse/checklist 등)·HITL·체크포인트 resume — v2/v3 유예 (기존 계획 유지)

## 실행 순서

```
RA 트랙 (본체):
[1] §1 kg_search + 뉴스 통합 (2~3일) ── 소스 확장, 최대 효과
[2] §2 retrieval_quality 전진 (0.5일) ── curation 콜 확장, 추가 콜 0
[3] §3 strength + span (1~2일) ── 원인론·감사 정밀화
[4] §4 상시 지표 (0.5일) → adaptive budget은 지표 확인 후

시스템 트랙 (병행 가능, 짧은 것부터):
[A] 5-1 모델 A/B 스팟체크 (0.5일) ── 오늘 개편의 품질 회귀 확인 — 가장 먼저
[B] 5-2 G1 캘리브레이션 (1일) · 5-5 RISK 다양성 (0.5일)
[C] 5-3 followup·멀티턴 (kg_search 이후) · 5-4 depth 레버 (상시 지표 이후)
```

각 단계 완료 기준(관례 유지): 오프라인 테스트 + 실질문 스팟체크 1건 이상, 스테이지 단위 커밋.
예상 비용 영향: §1 로컬 조회 무료·검색콜 감소, §2~4 mini 필드 확장 위주 — 질문당 순증 ≈ $0 ~ +0.1.
허용 예산(+$0.2~0.3) 안에 여유.
