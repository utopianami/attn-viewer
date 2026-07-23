# 2026-07-23 메모리 시황 리포트 사실성 감사 — 세션 핸드오프

## 1. 감사 대상과 목적

- 공개 리포트: <https://ryze.vault.haus/#report-2026-07-23-1>
- 로컬 원본: `storage/rag/memory_sector/reports/2026-07-23-1.json`
- 리포트 ID: `2026-07-23-1`
- 생성 시각: `2026-07-23T13:16:51.513035+09:00`
- 명목 관측 구간: `2026-07-23 01:16:51~13:16:51 KST`
- 리포트 자체 판정: `unverified`, 신뢰도 `낮`, 최종 의견 `관망`

이번 감사의 목적은 투자 논리의 타당성을 평가하는 것이 아니다. 다음 항목만
검증했다.

1. 원본 데이터와 리포트 숫자가 일치하는가
2. QoQ, YoY, MoM 등 비교 기간이 맞는가
3. 데이터가 의미하는 지표와 리포트가 붙인 이름이 일치하는가
4. 원문 출처로 확인되지 않은 내용을 사실처럼 사용하지 않았는가
5. 검증 파이프라인이 위 오류를 실제로 차단하는가

## 2. 결론

현재 리포트는 **사실 검증을 통과한 결과물로 취급하면 안 된다.**

- QoQ 값을 YoY로 잘못 표기한 확정 오류가 2건 있다.
- 서로 다른 비교 기간을 같은 기간처럼 대조한 오류가 1건 있다.
- 월말 기간 문자열 때문에 5월을 건너뛴 증감률이 1건 있다.
- 소비자 소매 호가, 회사 전체 매출·CAPEX를 산업 현물가, AI 매출,
  메모리·AI CAPEX로 확장한 지표 의미 오류가 있다.
- 핵심 심화 분석이 타임아웃됐지만 합성이 계속됐다.
- 수치 검증기가 회사, 지표, 기간, 단위, 부호를 검증하지 않고 숫자 크기만
  대조해 무관한 수치도 통과시켰다.

즉, 단순히 “논리가 약하다”는 문제가 아니다. **리포트 문장 중 일부는
원본 데이터와 사실관계가 직접 불일치한다.**

## 3. 판정 기준

| 판정 | 의미 |
|---|---|
| 확정 오류 | 저장된 원본 수치 또는 공식 원문으로 반대 사실을 재현할 수 있음 |
| 지표 의미 오류 | 산술은 맞지만 데이터가 나타내는 대상과 리포트의 명칭·해석이 다름 |
| 근거 불충분 | 현재 수집된 자료만으로 사실 여부를 결정할 수 없음 |
| 파이프라인 결함 | 사실 오류를 유입시키거나 검증 통과시킬 수 있는 구현 문제 |

## 4. 확정 사실 오류

### 4.1 SK하이닉스 CAPEX `-35.8% YoY`

리포트 문장:

> SK하이닉스 capex 7,865b(-35.8% YoY)

저장 데이터:

| 기간 | 값 |
|---|---:|
| 2025-03 | 6,454.69 |
| 2025-12 | 12,245.76 |
| 2026-03 | 7,865.37 |

재계산:

```text
QoQ = 7,865.37 / 12,245.76 - 1 = -35.77%
YoY = 7,865.37 /  6,454.69 - 1 = +21.86%
```

판정: **확정 오류.** `-35.8%`는 QoQ다. YoY는 `+21.9%`이므로 리포트의
YoY 표기는 방향까지 반대다.

근거:

- `storage/rag/memory_sector/metrics/memory_capex.jsonl`
- `engine/sector/report_anchors.py`: 직전 저장 관측치와의 증감률만 계산함

### 4.2 Google CAPEX `+28.1% YoY`

리포트 문장:

> GOOGL 35.67b(+28.1% YoY)

저장 데이터:

| 기간 | 값 |
|---|---:|
| 2025-03 | 17.20 |
| 2025-12 | 27.85 |
| 2026-03 | 35.67 |

재계산:

```text
QoQ = 35.67 / 27.85 - 1 = +28.08%
YoY = 35.67 / 17.20 - 1 = +107.38%
```

판정: **확정 오류.** `+28.1%`는 QoQ이며 YoY가 아니다.

근거:

- `storage/rag/memory_sector/metrics/hyperscaler_capex.jsonl`
- `engine/sector/report_anchors.py`

### 4.3 HBM 가격 지표의 비교 기간 불일치

리포트 문장:

> HBM $/GB 16.0(+6.7%)이나 $/TBps 312(-11.4%) → 성능조정 가격은 하락

원본 시계열:

| 지표 | 이전값 | 최신값 | 파이프라인 증감률 |
|---|---|---|---:|
| HBM USD/GB | 2025-09: 15 | 2026-03: 16 | +6.67% |
| HBM USD/TBps | 2025-03: 352 | 2026-03: 312 | -11.36% |

두 증감률은 각각 6개월과 12개월 비교다. 같은 12개월로 정렬하면:

```text
HBM USD/GB   = 16 / 18 - 1   = -11.11%
HBM USD/TBps = 312 / 352 - 1 = -11.36%
```

판정: **확정 비교 오류.** 동일 기간 기준으로는 두 지표가 거의 같은 방향이다.
현재 리포트가 제시한 `+6.7% 대 -11.4%` 괴리는 비교 기간 차이에서 생겼다.

근거:

- `storage/rag/memory_sector/metrics/memory_price_usd_per_gb.jsonl`
- `engine/sector/report_anchors.py`

### 4.4 한국 반도체 수출 `+40.3%`

저장 데이터:

| 월 | 월말 기간 라벨 | 수출액, 천 달러 |
|---|---|---:|
| 2026-04 | `01~30` | 32,039,455 |
| 2026-05 | `01~31` | 37,285,085 |
| 2026-06 | `01~30` | 44,947,188 |

파이프라인은 `meta.item`이 같은 시계열끼리만 비교한다. 따라서 6월
`01~30`은 5월 `01~31`이 아니라 4월 `01~30`과 비교된다.

```text
파이프라인 값, 4→6월 = 44,947,188 / 32,039,455 - 1 = +40.29%
실제 연속 월, 4→5월 = 37,285,085 / 32,039,455 - 1 = +16.37%
실제 연속 월, 5→6월 = 44,947,188 / 37,285,085 - 1 = +20.55%
```

판정: `+40.3%`라는 산술은 맞지만 **연속 월간 증감률이 아니다.** 리포트는
비교 기준을 표시하지 않은 채 단기 강세 근거로 사용했으므로 사실 전달이
잘못됐다.

근거:

- `storage/rag/memory_sector/metrics/kr_semi_export.jsonl`
- `engine/sector/collectors/customs_kr.py`
- 관세청 공식 API 설명:
  <https://www.data.go.kr/data/15157908/openapi.do>

추가 문제: 관세청 수치는 당월 잠정치이고 과거 값이 수정될 수 있지만,
`engine/sector/store.py`는 동일 기간·항목이 이미 저장돼 있으면 새 값을
건너뛴다. 공식 수정치가 저장본에 반영되지 않을 수 있다.

## 5. 지표 의미 오류

### 5.1 Amazon 소비자 메모리 호가를 산업 현물가·ASP로 사용

리포트 문장:

> DDR4 8.41$/GB(+41.1% MoM)·DDR5 11.41$/GB(+21.7% MoM)  
> ASP 상승 자체는 실재

저장 데이터의 계산은 맞다.

| 지표 | 2026-06 | 2026-07 | 증감률 |
|---|---:|---:|---:|
| DDR4 Keepa | 5.95812 | 8.40625 | +41.09% |
| DDR5 Keepa | 9.37312 | 11.40609 | +21.69% |

하지만 Stanford DAM 방법론상 이 값은:

- Amazon/Keepa에서 관측한 월별 신품 소비자 DIMM 최저 호가
- 실제 체결 판매가격이 아니라 listing price
- 제조사 계약가격보다 후행할 수 있는 소매 데이터
- 2026년 7월 표본은 DDR4 `n=2`, DDR5 `n=20`
- 월별 최저가 상품이 달라질 수 있음

따라서 이 데이터가 입증하는 사실은 “일부 소비자용 메모리 최저 호가가
올랐다”까지다. 이를 “산업 DRAM 현물가” 또는 “삼성·SK·Micron의 실현
ASP”로 사용하는 것은 **지표 의미 오류**다.

외부 근거:

- Stanford DAM 방법론: <https://dam.stanford.edu/memory-prices.html>
- 원본 CSV:
  <https://dam.stanford.edu/assets/memory-prices/memory-prices.csv>

수집기 문제:

- `engine/sector/collectors/stanford_dam.py`가 원본 CSV의 `source`, `n`,
  실제 상품, 주석·주의사항을 저장하지 않는다.
- `engine/sector/metrics_registry.py`가 이 시리즈를 `메모리 현물가`로
  표시한다.

### 5.2 회사 전체 CAPEX를 메모리·AI CAPEX로 사용

`engine/sector/collectors/supply.py`와
`engine/sector/collectors/capex.py`는 Yahoo Finance의
`quarterlyCapitalExpenditure`를 수집한다.

- 삼성전자 값은 메모리만이 아니라 회사 전체 연결 CAPEX다.
- 빅테크 값도 AI 전용이 아니라 회사 전체 연결 CAPEX다.
- Amazon CAPEX에는 물류 등 비AI 투자가 포함될 수 있다.
- 삼성·SK하이닉스는 원화, Micron은 달러인데 모두 `b_local`로 저장된다.

판정: 방향성 프록시로 사용할 수는 있지만 **메모리 CAPEX 또는 AI CAPEX
실측값으로 표시하면 안 된다.** `company_total_capex_proxy`로 명시하고
세그먼트 자료와 분리해야 한다.

### 5.3 회사 전체 매출을 AI 반도체 매출로 사용

`engine/sector/collectors/ai_chips.py`가 수집하는 필드는
`quarterlyTotalRevenue`다.

- AMD에는 CPU, 게이밍, 임베디드 매출이 포함된다.
- Broadcom에는 소프트웨어 및 비AI 반도체 매출이 포함된다.
- NVIDIA도 데이터센터 비중이 높지만 전체 매출과 AI 매출은 동일하지 않다.

따라서 AMD 전체 매출 `-0.2% QoQ`를 AI 수요 약화로 직접 해석할 수 없다.
코드 주석에는 프록시라고 적혀 있지만 리포트 데이터에는 이 caveat가 전달되지
않는다.

### 5.4 SK하이닉스 P&T7 7.1조원

공식 공시에서 확인되는 내용:

- 투자 대상: 청주 P&T7 건설
- 표시 투자금액: 7,093,100,000,000원
- 투자 기간: 2025-11-26~2032-12-31
- 목적: AI 메모리 수요 대응 생산 기반 확보
- 건설투자 확대와 클린룸 오픈 일정 단축에 관한 이사회 결정

공식 공시:
<https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260722800829>

현재 리포트는 이를 `7.1조 신규투자` 또는 `7.1조 추가투자`라고 부르고,
2027년 공급 증가의 근거로 사용한다. 그러나 현재 수집 데이터에는 다음이 없다.

- 7.0931조원이 기존 계획 대비 순수 증가분인지 여부
- 장비 투자와 건설 투자의 구분
- 웨이퍼 투입량 또는 HBM bit output 증가량
- 실제 생산 램프 시점

판정: 건설투자 확대 자체는 확인되지만, **7.1조 전액이 순증 투자이며
2027년 메모리 공급으로 연결된다는 내용은 근거 불충분**이다. DART 카드에는
제목만 있고 본문이 비어 있어 합성기와 검증기가 이 맥락을 읽지 못했다.

### 5.5 Q3 계약가격 `+25%+`

리포트의 핵심 근거 `gn-37c9ec7a7286`은:

- 출처 등급 C
- 제목만 존재
- 본문 및 원자료가 없음
- finance.biggo의 재전재성 페이지

판정: 현재 자료만으로는 사실 여부를 확인할 수 없다. TrendForce,
DRAMeXchange 또는 기업 실적발표 등 원출처를 확보하기 전까지
load-bearing 근거로 사용하면 안 된다.

## 6. 검증 파이프라인 결함

### 6.1 심화 단계 타임아웃 후 합성 진행

리포트 진단:

```text
deepen: 스테이지 타임아웃(2400s)
deepen: timeout
```

`engine/sector/report_pipeline.py`는 `deepen` 실패 시 빈 문자열을
fallback으로 넣고 합성을 계속한다. 실제 synth 프롬프트는
`[논증]` 뒤가 비어 있는 상태로 실행됐다.

판정: 핵심 분석 단계가 실패한 리포트를 발행한 운영 오류다. 최소한
`deepen` 실패 시 발행 중단 또는 명시적 degraded 템플릿으로 전환해야 한다.

### 6.2 `numeric_facts` 스키마 불일치와 자동 수치 연결

코드는 다음 형태를 기대한다.

```json
{"anchor_id": "...", "value": 123, "field": "value|delta_pct"}
```

실제 LLM 응답은 synth 단계에서 `id`, `unit`, `delta`, `period`를,
revise 단계에서는 `label`, `value`, `unit`, `delta`를 사용했다.
`anchor_id`가 없는 선언은 폐기됐고 `engine/sector/report_synthesis.py`의
`_auto_declare()`가 수치를 다시 연결했다.

자동 연결 조건:

```python
abs(abs(claim_number) - abs(anchor_number)) <= 3% tolerance
```

따라서 회사, 지표, 단위, 기간, 부호가 달라도 숫자 크기만 비슷하면 연결된다.
실제 최종 `numeric_facts`에는 메모리 주장과 무관한 LLM 토큰 단가와 다른 회사
anchor가 포함됐다.

판정: 현재 `numeric_facts`는 출처 귀속 증거로 신뢰할 수 없다.

### 6.3 검증기도 전역 숫자 풀과 절댓값으로 대조

`engine/sector/report_verify.py`는 전체 anchor의 값과 증감률을
`anchor_pool`에 넣고 주장 숫자와 크기만 비교한다.

이 방식은 다음 오류를 잡지 못한다.

- SK하이닉스 수치를 Google 수치로 귀속
- QoQ 값을 YoY로 표기
- 양수와 음수 혼동
- 달러와 원화 혼동
- 매출과 CAPEX 혼동
- 6개월과 12개월 증감률 혼동

즉 현재 검증기는 사실 검증기가 아니라 **숫자 존재 여부 검사기**에 가깝다.

### 6.4 원문 손실과 출처 등급 손실

- raw 뉴스와 카드가 중복되면 raw 원문을 버리고 카드를 우선한다.
- 카드에는 최대 500자만 남는다.
- 합성 단계에는 더 짧은 발췌만 전달된다.
- EvidenceRef에는 source grade가 없어 C등급 제목만 있는 근거도 핵심 근거가
  될 수 있다.
- DART 공시는 본문이 비어 있었다.

관련 코드:

- `engine/sector/report_pipeline.py`
- `engine/sector/report_filters.py`
- `engine/sector/judge.py`
- `engine/sector/collectors/dart_edgar.py`

### 6.5 프롬프트가 데이터 없이 정량 결론을 요구

`engine/sector/report_synthesis.py`의 심화 프롬프트는:

- 투자 유형과 무관하게 `CapEx 리드타임 1.5~2년`을 고정 전제로 둔다.
- bit shipment, 원가, 실현 ASP, 감가상각 자료 없이 BEP를 역산하라고 한다.
- 같은 입력으로 매출·영업이익·FCF 귀결까지 요구한다.

이 구조는 근거 없는 `GM 수십%p 확대` 같은 정량 추정을 유도한다. 실제
리포트는 해당 표현을 나중에 철회했지만, 프롬프트 설계상 같은 문제가 반복될
수 있다.

## 7. 누락된 핵심 데이터

리포트의 제목을 사실로 검증하려면 최소한 다음 자료가 필요하다.

### 가격과 수익성

- TrendForce/DRAMeXchange 등 실제 DRAM spot 및 contract price
- 삼성전자·SK하이닉스·Micron의 realized ASP
- DRAM, NAND, HBM별 매출과 매출총이익
- 제품 믹스, 장기계약과 현물 계약 비중

### 공급

- DRAM/NAND/HBM별 bit shipment와 bit growth
- 재고일수, 가동률, 웨이퍼 투입량, 수율
- CAPEX의 메모리/파운드리/비반도체 구분
- 건설/장비, wafer fab/HBM packaging, node migration/net capacity 구분
- 투자별 실제 양산 시점과 추가 bit output

### 수요

- HBM backlog, 계약 물량, 고객 배정, 세대별 가격
- 서버당 DRAM/HBM 탑재량
- 데이터센터 CAPEX 중 서버·GPU·메모리 실제 비중
- 전력 확보와 인허가가 완료된 프로젝트와 계획 단계 프로젝트 구분

### 교차 검증

- DART/SEC 공시 본문과 기업 실적발표 원문
- ECOS DRAM 수출물가지수
- 중국 CXMT·YMTC 공급, DDR4 단종 일정, 유통 재고와 lead time
- 주가 반응 및 애널리스트 보고서

현재 리포트 진단에서도 `price_reaction`, `analyst_reports`가 비어 있다.

## 8. 사실만 남긴 안전한 표현

현재 데이터로 말할 수 있는 범위는 다음 정도다.

> 2026년 7월 일부 Amazon 소비자용 메모리 최저 호가는 6월보다 상승했다.
> 다만 표본이 작고 상품 구성이 달라 산업 계약가격이나 메모리 제조사의 실현
> ASP를 대표하지 않는다. 기업 전체 CAPEX 및 전체 매출 프록시는 혼재돼
> 있으며, 메모리 공급 증가 시점과 ASP 지속성은 현재 데이터로 검증되지 않았다.

따라서 기존 제목의 `단기 메모리 ASP 강세는 실재`는 현재 근거만으로 확정하면
안 된다.

## 9. 수정 우선순위

### P0 — 잘못된 리포트 재발 방지

1. `deepen` 실패 시 발행 중단
2. anchor에 `entity`, `metric`, `current_period`, `previous_period`,
   `previous_value`, `comparison_kind`, `unit`, `currency` 추가
3. `numeric_facts`를 엄격한 typed schema로 강제하고 fuzzy 자동 연결 제거
4. 검증 시 anchor ID와 회사·지표·기간·단위·부호를 모두 대조
5. QoQ/YoY/MoM은 LLM이 추측하지 않고 코드가 명시적으로 계산

### P1 — 데이터 의미 보존

1. Keepa 지표 이름을 `consumer_retail_listing_proxy`로 변경
2. Stanford CSV의 표본 수, 상품, source, caveat 저장
3. 회사 전체 매출·CAPEX에 `proxy=true`와 정확한 명칭 부여
4. DART/SEC 원문 본문을 저장하고 제목만 있는 공시는 load-bearing 금지
5. 관세청 월말 `01~30`/`01~31`을 동일한 `full_month` 시리즈로 정규화
6. 과거 공식 수치 수정값을 upsert할 수 있게 저장 키·정책 수정

### P2 — 핵심 데이터 보강

1. 실제 contract/spot price 및 realized ASP
2. 메모리 세그먼트 생산·재고·출하 데이터
3. 투자 유형별 CAPEX와 공급 기여 시점
4. price reaction과 analyst report seam 채우기

## 10. 다음 세션에 전달할 요청문

아래 문구와 이 문서 경로를 함께 전달하면 된다.

```text
docs/2026-07-23-market-report-factual-audit-handoff.md를 읽고,
2026-07-23-1 리포트의 투자 논리가 아니라 사실성 문제를 이어서 다뤄라.

우선 확정 오류 4건(SK하이닉스 QoQ/YoY, Google QoQ/YoY, HBM 비교기간,
관세청 full-month 비교)을 독립 재현하라. 그 다음 지표 의미 오류와
numeric_facts/verify 결함을 테스트로 고정하고, P0 순서대로 최소 수정안을
제시하라. 원본 API 계약이나 데이터 스키마를 변경할 경우 OpenAPI/typed
contract를 같은 변경에 포함하라.
```

## 11. 관련 파일

- 리포트: `storage/rag/memory_sector/reports/2026-07-23-1.json`
- 기존 수집 GIGO 감사: `docs/2026-07-22-collector-gigo-audit.md`
- anchor 계산: `engine/sector/report_anchors.py`
- 합성 및 자동 수치 귀속: `engine/sector/report_synthesis.py`
- 검증: `engine/sector/report_verify.py`
- 파이프라인 타임아웃 처리: `engine/sector/report_pipeline.py`
- 메모리 가격 수집: `engine/sector/collectors/stanford_dam.py`
- 메모리 3사 CAPEX 수집: `engine/sector/collectors/supply.py`
- 하이퍼스케일러 CAPEX 수집: `engine/sector/collectors/capex.py`
- AI 기업 매출 프록시: `engine/sector/collectors/ai_chips.py`
- 관세청 수출 수집: `engine/sector/collectors/customs_kr.py`
- 저장 중복 처리: `engine/sector/store.py`


---

## 12. 처리 결과 (2026-07-23, P0 반영 완료)

확정 오류 4건 독립 재현 후 P0 전체 + P1 일부를 반영했다. 커밋: `feat(report): 사실성 감사 P0`.

- **P0-2/5 (비교 정체성)**: Anchor에 `prev_period`·`prev_value`·`comparison_kind`(MoM/QoQ/YoY/nM — 코드가 기간 차로 판정) 추가. 합성·검증 프롬프트에 "Δ-35.8% QoQ, 직전 2025-12=12245.76" 형태로 명시 + "비교 종류를 바꿔 말하면 supported=false" 지시. 실데이터 검증: SK QoQ·GOOGL QoQ·HBM 6M vs YoY 혼재가 전부 표기됨.
- **P0-3 (fuzzy 자동 연결 제거)**: `_auto_declare` 삭제 — 미선언 수치는 A1 경고+확신도 상한 경로로 회귀. `numeric_facts`는 typed 스키마(CLI json-schema 구속).
- **P0-4 (단위 클래스 대조)**: 스윕 풀이 (값, 단위클래스) 쌍 — '+25%' anchor로 '25달러' 통과 불가. 완결 글(article) 감사에도 동일 적용.
- **P0-1 (강등 표시)**: deepen/synth/research/compose 실패 시 종합 첫 줄 "⚠ 강등 모드" + `diagnostics.degraded`. 발행 중단 대신 정직 라벨 채택(하루 2회 배치에서 전면 중단은 과잉 — never-raise 원칙 유지, 이견 있으면 재론).
- **4.4 (관세청)**: anchor 그룹 키에서 `01~(28|29|30|31)` → `full_month` 정규화 — 5월 건너뛴 +40.3%가 연속 월간 +20.6% MoM으로 교정(회귀 테스트 고정).
- **P1 일부**: Keepa 라벨 → "소비자 리테일 최저호가 프록시", 전사 CAPEX/매출 라벨에 "프록시(전용 아님·통화 혼재)" 명시, 프록시 경고를 앵커 source로 프롬프트까지 전달.

미처리(후속): Anchor `currency` 필드(b_local이 회사별 통화 혼재라 수집기 수정 필요), Stanford 표본수·caveat 저장, DART 본문 수집, 관세청 잠정치 upsert, P2 데이터 보강. 회귀 테스트 143개 통과.
