# Case-Memory 지식 스토어 적대적 리뷰 (index.jsonl 16건 / rules.jsonl 48건)

날짜·금리 경로·파산 시점 등 하드 팩트는 전반적으로 정확했다(엘피다 2012-02-27, 키몬다 2009-01, 61% 마진 2018-06, BOK 첫 빅스텝 2022-07-13, 2001년 11회 인하 등 모두 확인). 문제는 사실보다 **knowable_at 규율**과 일부 규칙의 논증 품질에 있다.

## (a) BLOCKER — 룩어헤드 오염 / 사실 오류

1. **[전 케이스 공통] 힌트사이트 phase label**: `mem-2007…gfc` phase2 `mid_2008_false_stabilization`("false"는 GFC 이후에만 판정 가능, knowable_at 2008-06-27), `mem-2016-2019` phase2 `peak_signals_inventory_build`, `fin-1999` phase1 `peak_exuberance`, `fin-2020-covid` phase0 `complacency`, `fin-1987` phase0 `pre_crash_tightening…`, `fin-2022-2025-nvda` phase0 `pre_ai_trough…`, `mem-2011` phase0 `late_cycle_price_stability`, `fin-2007-2009` phase0 `early_strains_downplayed`, `fin-1990-1993-japan` phase0 `…underrecognized…`. 라벨이 결과를 답으로 새겨 넣고 있어, 라벨을 검색/매칭 피처로 쓰면 그대로 정답 누출이다.
2. **[fin-1999] phase1 identifying_signals[2]** "5월 50bp 인상으로 6.5% 도달 — **긴축 사이클 정점**": '정점'(마지막 인상이었다는 것)은 2000-05 시점에 불가지. 게다가 phase knowable_at(2000-03-01)보다 뒤의 사건.
3. **[구조적] phase knowable_at ≠ signals의 실제 가지 시점**: knowable_at을 첫 증거 날짜로 잡고 signals에는 그 뒤에야 알 수 있는 사실을 섞음. 대표 사례 — `mem-2014-2016` phase2(FY16Q2 순손실 $48M은 2016-03-30에야 가지, knowable_at 2015-10-01), `mem-2023-2025` phase2("2025년분 배정 완료"는 2024-03-20 발언, knowable_at 2023-12-20), `mem-2020-2022` phase0(FY21 CapEx 축소는 2020-09-29 발표, knowable_at 2020-03-25), `nvda` phase0($702M 상각·수출규제는 2022-11-16/2022-09, knowable_at 2022-08-24), `mem-2016-2019` phase3(5% idle은 2019-03-20, knowable_at 2018-12-18), `mem-2011` phase3(스폰서 독점협상권은 2012-05~06 확인, knowable_at 2012-03-22), `fin-2023-svb` phase2(의사록 내용은 2023-04-12 공개, knowable_at 2023-03-22), `fin-1999` phase0(자산효과 지목은 1999-10-05 의사록, knowable_at 1999-06-30). phase knowable_at 기준으로 signals를 필터 없이 소비하면 전부 위양성 룩어헤드다. knowable_at 의미론을 "전 signals가 가지되는 시점"으로 통일하거나 signal별 날짜를 달아야 함.
4. **[증거가 period_end 이후]** 기계 확인 결과 4개 케이스 11건: 특히 `mem-2007…gfc` phase3(period_end 2009-03-05)에 2009-04-03 Qimonda 디폴트 인용 — 한 달 뒤 자료이자 내용상 다음 phase 소속. 나머지(FOMC minutes 공개 지연 수일)는 경미하나 같은 필드 규율 위반.
5. **[rules 사실 오류·상호모순] `rule-sellside-capitulation-cut-cluster`** connection이 "2019-06 **3사(삼성·하이닉스·마이크론) 감산 결정**"을 사실로 기술. 삼성은 2019년 공식 감산을 하지 않았고(인위적 감산 부인 기조), 같은 파일의 `rule-sellside-supplier-discipline-myth`가 삼성 첫 공식 감산을 2023-04로 명시해 **자기모순**. 애널리스트 인용문의 과잉 주장을 규칙 본문이 사실로 세탁한 사례.

## (b) SHOULD-FIX

1. **[mem-2011] phase0/1 기간 중첩**: phase0 end 2011-05-31 vs phase1 start 2011-05-01 — 한 달 이중 귀속. (`fin-1987` phase2/3도 1987-12-16 하루 중첩.)
2. **[fin-1990-1993-japan] phase0 signal[0]** "1990년 초에도 일본 성장을 '강한 지속'으로 평가": 같은 코퍼스의 1990-03-27 record가 이미 "growth had slowed in Japan"이라 기술 — phase 기간(~06-30) 내에서 2월 기록만 체리피킹, 주장 과장.
3. **[스키마 사문화] 전 케이스 supports_rules/refutes_rules가 빈 배열**인데 xc-룰들은 provenance로 케이스를 인용 — 양방향 링크 미구축, 케이스→룰 검증 경로가 죽어 있음.
4. **[rule-xc-record-results] trigger[2]** "**정점 국면에서** 경영진이 자사주 저평가 주장…": 트리거가 '정점임을 앎'을 전제로 하는 순환 정의. "기록 실적 발표와 동시에"처럼 관측 가능 조건으로 재기술 필요.
5. **[rule-xc-inventory-mention-precedes-crash]** "4개 사이클 모두 첫 언급 후 1~2분기 내 급락·순손실": 2007 사례는 재고 언급(2007-04-04)과 순손실 발표가 **같은 콜** — 리드타임 과장. 또 붕괴로 이어지지 않은 재고 언급의 기저율이 없음(종속변수 선택 편향).
6. **[rule-xc-structural-optimism]** connection이 "3사례 모두 2~4분기 내 다운턴"이라면서 자체 인용한 2018 사례는 "3개월 뒤"(1분기) — 명시한 시차 범위와 자기 사례가 불일치.
7. **[rule-xc-supply-cut-staged-bottom-lag] evidence[4]** (2023-06-28 "passed the bottom" 인용)는 어떤 트리거·연결고리도 뒷받침하지 않는 장식용 인용.
8. **[rule-buffett-party-clock] reservations** "버핏도 대붕괴 시점(2000-03-10)을 몇 달 뒤에야 알았다고 인정" — FY2000 서한에 해당 날짜·인정 문구 없음. 검증 불가한 귀속은 삭제 요망.
9. **[문서 날짜 불일치]** 동일 버크셔 서한이 index에선 실제 날짜(1987-02-27, 1988-02-29), rules에선 일괄 "03-01"(rule-buffett-fear-greed 등 6건) — 같은 문서에 knowable_at 두 개. 중복 제거·검색 정합 깨짐.
10. **[fin-2022-2025-nvda] sector: "finance"** — 금융 위기 세트에 NVDA 수요 사이클이 finance로 분류. 별도 섹터(tech/semis-demand) 또는 memory 연계 태그가 맞음.
11. **[rule-filing-capex-guidance-cut]** connection의 "FY2019의 $7~8B 삭감" — 인용문은 FY2019 10-K에 실린 **FY2020** capex 가이던스. 회계연도 1년 오프셋.
12. **[fin-1999] phase0 evidence[2]** (1999-11-16 성명) 문장 중간에서 잘렸고 signal의 "5.5% 도달"을 실증하지 못함 — 인용-주장 정합 미달.
13. **[증거 중복]** `mem-2014-2016` phase4와 `mem-2016-2019` phase0이 동일 인용 2건(2016-12-21) 공유 — 검색 시 이중 카운트 위험.

## (c) NIT

1. **[fin-2023-svb] phase1 signal[1]** "SVB에 이어 시그니처은행도 **같은 날** 폐쇄" — SVB는 3/10, 시그니처는 3/12. '같은 날'의 기준(공동성명일)이 모호해 오독 유발.
2. **[fin-1997] outcome** "1997년 말 약 1,700원대까지 급등" — 연말 종가(~1,695) 기준으론 맞지만 위기 정점(12/23 ~1,960원대)을 과소 표현.
3. **[메트릭 명명 불일치]** `usd_krw`(달러 선행) vs `jpy_usd`(엔 선행인데 방향은 USD/JPY 해석일 때만 성립) — 방향 오독 위험.
4. **[fin-2020] phase3 evidence** source가 "FOMC minutes (2020-04-08)"인데 URL은 fomcminutes20200315 — 회의일/공개일 표기 관례가 다른 증거들과 불일치 (knowable_at 자체는 공개일로 정확).
5. **[mem-2023-2025] phase 기간 비연속**: 0→1(2023-03-29~06-27), 1→2, 2→3 갭 — 연속 타일링을 가정하는 소비자는 2023 중반 신호를 귀속 못 함.
6. **[인용 추출 아티팩트]** mem-2007 phase1 "45%from the midpoint…theaggregate…productsdeclined", 셀사이드 인용의 "삼성전 자"·"부 분" 등 공백 깨짐 — verbatim 원칙상 불가피하나 표시용 정규화 레이어 필요.
7. **[용어 혼용]** "빗그로스/빗 출하" vs "비트 공급" 혼용.
8. **[fin-2020] phase4 knowable_at(2020-09-16)** 은 첫 증거(2020-04-29)보다 늦음 — 다른 케이스(첫 증거일 채택)와 반대 관례. knowable_at 규약 문서화 필요.
9. **[rule-sellside-theme-mainstreaming]** "2018-09 HBM 첫 언급" — 코퍼스 내 첫 언급일 뿐(HBM 셀사이드 언급은 2015~부터 존재). '코퍼스 기준'임을 명시하는 게 안전.

## 종합 판정 (3줄)

사실관계(날짜·수치·정책 경로)는 견고하고 인용-주장 정합도 표본 20여 건 중 대부분 양호 — 코어 데이터는 신뢰 가능. 그러나 **knowable_at 규율이 사실상 phase 단위에서 붕괴**해 있고(라벨 힌트사이트 + 신호별 가지 시점 미분리 + period_end 이후 증거), 이 상태로 ex-ante 매칭에 쓰면 백테스트가 체계적으로 낙관 오염된다. 라벨 중립화·signal별 knowable_at 부여, 그리고 삼성 2019 감산 모순(rules) 1건 수정이 출고 전 필수다.
