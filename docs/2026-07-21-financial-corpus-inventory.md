# Financial Corpus — Public Corpora & Benchmarks (마스터 인벤토리)

작성일: 2026-07-21 · 성격: **전 섹터 공용 원장(reference)**

---

## 이 문서의 위치

이건 **금융 코퍼스 마스터 목록**이다 — 과거 사례 지식층(historical case memory)을 채울 수 있는 공개 코퍼스·벤치마크의 상위 집합. 특정 섹터에 종속되지 않는다.

지금 진행하는 빌드는 이 원장의 **메모리 반도체 전용 인스턴스**이며, 수집 깊이는 사례별로 2단으로 나눈다(2026-07-21 확정):

- **깊게 (풀 케이스)** — 메모리 반도체 사이클만. 원문 청크 + 시간 인과 타임라인 + 정량 백본 시계열까지 저장. = 설계문서 §5의 ② 사례 지식(temporal graph).
  - 대상 사이클: 2008 DRAM 공급과잉, 엘피다/키몬다 파산(2009·2012), 2018·2022-23 다운사이클, 2024~ HBM/AI 사이클.
  - 주 재료: 반도체 IR/실적(A5), 한경컨센서스·네이버 리서치(A14), Asianometry·SemiAnalysis·Fabricated Knowledge(A15), SIA/WSTS(G24), Stanford DAM, 보유 중인 ranto28 블로그 코퍼스(2,468편).
- **얇게 (규칙만 증류)** — 그 외 모든 위기(닷컴·GFC·COVID·아시아위기'97·일본버블·국채위기·오일쇼크…). 문서를 통째로 넣지 않고 LLM으로 "조건→귀결" 규칙 한 줄씩만 추출. = 설계문서 §5의 ① 개념/규칙 지식. **기존 playbook 레이어(24개 규칙)와 동일한 표현형에 담는다.**

즉 원칙은 **"메모리는 사례로, 나머지는 규칙으로."** 원장 전체를 다 다운로드하지 않는다 — 메모리 관련만 풀 수집, 나머지는 규칙 추출용으로 한 번 훑고 버린다.

---

# A. Company Voice — Earnings Calls & Filings

## 1. S&P 500 Earnings Transcripts ⭐⭐⭐⭐⭐
**Purpose** — 경영진이 서로 다른 시장 사이클에서 사업 환경을 실제로 어떻게 묘사했는지 학습. CAPEX 결정·재고 사이클·가격결정력·수요 전망·가이던스 변화·경영 실수 추출에 탁월.
**Coverage** — ~33,362 earnings call transcripts · ~685 S&P500 기업 · 2005–2025
**License** — MIT
**URL** — https://huggingface.co/datasets/kurry/sp500_earnings_transcripts

## 2. Strux Transcripts + Transcript APIs ⭐⭐⭐☆
**Purpose** — earnings call transcript 보강/지속 수집.
**Coverage** — Strux: 11,950 quarterly transcripts, NASDAQ/S&P500, 2017–2024 (Motley Fool sourced) · FMP, EarningsCall: 무료 티어 API로 지속 수집
**URL** — https://struxdata.github.io/ · https://financialmodelingprep.com · https://earningscall.biz

## 3. SEC EDGAR ⭐⭐⭐⭐☆
**Purpose** — 공식 SEC filing. 기업 펀더멘털 ground truth.
**Useful Documents** — 10-K, 10-Q, 8-K, Proxy statements
**Use Cases** — earnings call 주장 검증, CAPEX, MD&A, Risk Factors, 사업 변화
**Note** — Full-text search는 2001+ 커버
**URL** — https://www.sec.gov/edgar · https://www.sec.gov/edgar/search/ · https://github.com/dgunning/edgartools

## 4. OpenDART ⭐⭐⭐⭐☆
**Purpose** — 한국 상장사 공시.
**Useful Documents** — 사업보고서·분기보고서·"사업의 내용"(산업 환경 서술)
**URL** — https://opendart.fss.or.kr

## 5. Company IR Archives (Semiconductor) ⭐⭐⭐⭐⭐
**Purpose** — 분기 실적 덱·프레젠테이션·콜 자료를 원천에서 직접. 메모리 사이클 케이스에는 일반 transcript 데이터셋보다 밀도가 높다.
**Coverage** — Micron, SK hynix, Samsung, TSMC, ASML — 각 IR 사이트 다년 아카이브
**URL** — https://investors.micron.com · https://www.skhynix.com (IR) · https://www.samsung.com/global/ir/ · https://investor.tsmc.com · https://www.asml.com/en/investors

---

# B. News Archives

## 6. FNSPID ⭐⭐⭐⭐⭐
**Purpose** — 대규모 금융 뉴스 + 주가 코퍼스. 시장이 뉴스 이벤트에 어떻게 반응했는지 학습에 이상적.
**Coverage** — ~15.7M news articles · ~29.7M stock price records · 4,775 S&P500 기업 · 1999–2023
**License** — CC BY-NC (비상업만)
**URL** — https://github.com/Zdong104/FNSPID_Financial_News_Dataset · https://huggingface.co/datasets/Zihan1004/FNSPID

## 7. BigKinds (빅카인즈) ⭐⭐⭐⭐☆
**Purpose** — 한국언론진흥재단 뉴스 아카이브. 한국 이벤트 타임라인(반도체 사이클·IMF 등) 구축에 최적.
**Coverage** — 1990–현재 · 104개 매체 · ~100M articles
**Caveats** — 벌크 다운로드는 본문 첫 200자만(전문=유료 Newstore) · Open API 2025부터 유료화 → 타임라인/이벤트 감지용으로 쓰고 전문은 네이버 뉴스 크롤로 복원
**URL** — https://www.bigkinds.or.kr

## 8. GDELT ⭐⭐⭐☆
**Purpose** — 글로벌 뉴스 이벤트 메타데이터 + 기사 URL, 무료.
**Coverage** — v2 2015부터(15분 업데이트), events DB는 1979까지
**URL** — https://www.gdeltproject.org

---

# C. Policy & Central Bank Documents

## 9. FOMC Documents ⭐⭐⭐⭐⭐
**Purpose** — 정책결정자가 닷컴·GFC·COVID 당시 실시간으로 무엇을 보고 무엇을 말했나.
**Useful Documents** — statements & minutes · full transcripts(5년 지연, 1976부터) · Greenbook/Tealbook(스태프 전망, 5년 지연)
**URL** — https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm · https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm

## 10. Bank of Korea ⭐⭐⭐⭐☆
**Purpose** — 한국 정책 축.
**Useful Documents** — 금통위 의사록(MPC minutes) · ECOS API(한국 매크로 시계열)
**URL** — https://www.bok.or.kr · https://ecos.bok.or.kr

---

# D. Real-Time Cycle Observations (Investor Records)

## 11. Howard Marks Memos ⭐⭐⭐⭐⭐
**Purpose** — 사이클을 실시간으로 읽는 최고의 "당시 시점 해석" 소스. bubble.com(2000-01), 2005–2008 메모 등.
**Coverage** — 1990부터 메모 아카이브, 무료
**URL** — https://www.oaktreecapital.com/insights/memos

## 12. Berkshire Hathaway Shareholder Letters ⭐⭐⭐⭐☆
**Purpose** — 1970년대 말 이후 모든 사이클에 대한 버핏의 당대 시각.
**Coverage** — 1977–현재, 무료
**URL** — https://www.berkshirehathaway.com/letters/letters.html

## 13. GMO Quarterly Letters ⭐⭐⭐☆
**Purpose** — 그랜섬의 버블 콜(일본·닷컴·주택) — 밸류에이션 기반 사이클 논평.
**URL** — https://www.gmo.com

---

# E. Sell-side & Industry Commentary

## 14. 한경컨센서스 / Naver 증권 리서치 ⭐⭐⭐⭐⭐
**Purpose** — 한국 증권사 산업 리포트(무료 PDF). 메모리 사이클 국면 서술 밀도가 가장 높음 — 연도별 "반도체 산업" 리포트 스크랩.
**URL** — https://consensus.hankyung.com · https://finance.naver.com/research/

## 15. Semiconductor Commentary ⭐⭐⭐⭐☆
**Purpose** — 산업 역사 & 사이클 심층.
**Sources** — Asianometry(YouTube, 반도체 역사 최고 해설, yt-dlp로 자막 추출) · SemiAnalysis(무료 글) · Fabricated Knowledge(메모리 사이클 심층, 무료 글)
**URL** — https://www.youtube.com/@Asianometry · https://semianalysis.com · https://www.fabricatedknowledge.com

---

# F. Macro & Crisis History

## 16. JST Macrohistory Database ⭐⭐⭐⭐⭐
**Purpose** — 장기 거시·금융 역사. 금리·신용·GDP·인플레·주택가·주가·금융위기·은행업 역사.
**Best For** — 100년+ 걸친 반복 매크로 사이클 학습.
**URL** — https://www.macrohistory.net/database/

## 17. IMF Systemic Banking Crises Database ⭐⭐⭐⭐⭐
**Purpose** — 구조화된 은행위기 DB. 위기 시작일·정부개입·예금보증·재정비용·GDP 손실·해결방식.
**Best For** — 과거 은행위기 케이스 스터디 구축.
**URL** — https://www.imf.org/en/Publications/WP/Issues/2026/05/14/Systemic-Banking-Crises-Database-1970-2025-576036

## 18. Yale Program on Financial Stability ⭐⭐⭐⭐⭐
**Purpose** — 금융위기 케이스 스터디. 중앙은행 개입·구제금융·유동성 지원·규제 대응·교훈. YPFS 라이브러리는 1차 문서(Valukas 보고서 등)도 미러링.
**URL** — https://som.yale.edu/centers/program-on-financial-stability · https://som.yale.edu/centers/program-on-financial-stability/journal-of-financial-crises

## 19. FCIC Report + Valukas Report ⭐⭐⭐⭐☆
**Purpose** — GFC 부검을 1차 자료 형태로. FCIC 최종보고서 + 문서 아카이브(Stanford Law) · Valukas Lehman 파산 조사관 보고서 9권 ~2,200쪽(Repo 105 등).
**URL** — https://fcic.law.stanford.edu · https://web.stanford.edu/~jbulow/Lehmandocs/menu.html

## 20. Reinhart–Rogoff Database ⭐⭐⭐⭐☆
**Purpose** — 수세기 국채 디폴트·은행·통화 위기("This Time Is Different" 데이터). IMF Laeven–Valencia 보완.
**URL** — https://carmenreinhart.com/data/

---

# G. Quantitative Backbone (attach to each case)

## 21. Shiller Data ⭐⭐⭐⭐☆
**Coverage** — 미 주식 월별 1871~, CAPE · 미 주택가 1890~ · 장기 금리
**Best For** — 닷컴/주택/밸류에이션 사이클 케이스
**URL** — http://www.econ.yale.edu/~shiller/data.htm

## 22. BIS Statistics ⭐⭐⭐⭐☆
**Coverage** — Credit-to-GDP gaps · 주거용 부동산 가격(장기, 다국) · 부채상환비율(DSR)
**Best For** — 신용 사이클 맥락; JST 보완
**URL** — https://data.bis.org

## 23. FRED / NBER / EIA ⭐⭐⭐⭐☆
**Purpose** — FRED: 미·글로벌 매크로 시리즈 · NBER: 공식 경기순환 날짜 → 모든 케이스의 침체 앵커 · EIA: 오일쇼크 케이스
**URL** — https://fred.stlouisfed.org · https://www.nber.org/research/business-cycle-dating · https://www.eia.gov

## 24. SIA / WSTS Semiconductor Billings ⭐⭐⭐⭐☆
**Purpose** — 월별 글로벌 반도체 빌링(헤드라인 무료). 메모리 사이클 케이스의 정량 척추.
**Note** — DRAM spot(DXI/TrendForce)은 유료 → 뉴스 인용으로 간접 복원
**URL** — https://www.semiconductors.org · https://www.wsts.org

---

# H. Timeline Reference

## 25. Wikipedia Dumps ⭐⭐⭐☆
**Purpose** — 이벤트 요약을 타임라인 뼈대로(Qimonda 2009 / Elpida 2012 파산, DRAM 가격전쟁, 위기 연표).
**URL** — https://dumps.wikimedia.org

---

# LLM Training / Benchmark Datasets

위 데이터셋들과는 다르다. 위=**지식 코퍼스**(과거 사례 메모리의 원재료). 아래=금융 LLM 훈련/평가용 **instruction 데이터셋·벤치마크**. 그 자체로는 과거 금융 메모리로 부적합.

## 26. FinGPT ⭐⭐⭐☆
**Type** — 금융 LLM Instruction Dataset + Framework
**Purpose** — 금융 QA·감성분석·뉴스 이해·instruction tuning·챗봇 훈련
**Strengths** — 금융 NLP 태스크 대량 모음, instruction tuning 참조에 좋음
**Weaknesses** — 구조화된 과거 금융 케이스 없음, 시장 역사가 아니라 QA/NLP 감독 위주
**URL** — https://github.com/AI4Finance-Foundation/FinGPT

## 27. PIXIU / FinBen ⭐⭐⭐☆
**Type** — 금융 LLM 벤치마크
**Purpose** — 금융 추론 능력 평가(QA·감성·NER·분류·정보추출·추론)
**Strengths** — 금융 LLM 비교용 종합 벤치, 모델 개선 후 회귀 테스트에 유용
**Weaknesses** — 평가 데이터셋이지 지식 코퍼스 아님, 금융 메모리 구축 목적 아님
**URL** — https://github.com/The-FinAI/PIXIU

---

# Recommended Usage

## Historical Case Memory (Knowledge Base)

**Narrative sources (당시 발언)** — S&P500 Earnings Transcripts/Strux · Company IR archives(반도체) · SEC EDGAR/OpenDART · FNSPID/BigKinds/GDELT · FOMC/BOK minutes · Howard Marks/Berkshire/GMO letters · 한경컨센서스/Naver 리서치 · Asianometry/SemiAnalysis/Fabricated Knowledge

**Post-mortems & crisis DBs** — JST Macrohistory · IMF Banking Crisis DB · Yale YPFS · FCIC/Valukas · Reinhart–Rogoff

**Quantitative backbone** — Shiller/BIS/FRED/NBER/EIA · SIA/WSTS billings

↓ 구조화된 과거 케이스 추출:

닷컴 버블 · GFC · COVID 크래시 · AI 버블 · 메모리 반도체 사이클 · 지역은행 위기 · 주택 버블 · 오일쇼크 · 국채위기 · 아시아 금융위기(1997) · 일본 버블(1989–1992)

↓ 검색·추론용 구조화 Case Memory로 저장.

각 case card = narrative sources(당대 시각) + quantitative backbone(시계열) + policy documents(공식 대응) + post-mortem(실제 결과).

## Financial LLM Training / Evaluation

FinGPT · PIXIU/FinBen — instruction tuning · 금융 QA · 모델 평가 · 회귀 테스트. 과거 코퍼스를 **보완**하되 대체하지 않는다.

---

## 이 빌드에 어떻게 먹이나 (요약)

| 사례 | 깊이 | 표현형 | 주 소스 |
| --- | --- | --- | --- |
| 메모리 반도체 사이클 | 풀 케이스 | 사례 카드 + 시간 타임라인 + 정량 백본 | A5·A14·A15·G24·Stanford DAM·ranto28 블로그 |
| 그 외 위기(닷컴·GFC·COVID·아시아'97·일본버블·국채·오일 등) | 규칙만 증류 | if/then 규칙(기존 playbook 스키마) | D11·D12·F16~20·A1·C9 등에서 패턴만 추출 |
