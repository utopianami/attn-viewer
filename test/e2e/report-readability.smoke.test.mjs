import assert from "node:assert/strict";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

import { chromium } from "playwright";

import {
  TEST_PASSWORD,
  TEST_USERNAME,
  createTestRoot,
  startTestServer,
} from "../helpers/test-server.mjs";

const BASE_REPORT_ID = "2026-09-04-1";
const REPORT_ID = "2026-09-04-2";
const DYNAMIC_REPORT_ID = "2026-09-04-3";
const FALLBACK_REPORT_ID = "2026-09-04-4";
const COLLISION_REPORT_ID = "2026-09-04-5";
const ERROR_REPORT_ID = "2026-09-04-6";
const SCREENSHOT_DIR = process.env.REPORT_SCREENSHOT_DIR || "";
const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844, takeawayColumns: 1, metricColumns: 2 },
  { name: "desktop", width: 1440, height: 900, takeawayColumns: 3, metricColumns: 4 },
];

const paragraph = [
  "금리와 환율, 메모리 가격이 서로 다른 방향으로 움직이며 공급망의 온도 차가 커졌다.",
  "계약 가격과 소매 가격의 시차를 구분하고 다음 발표에서 방향이 이어지는지 확인해야 한다.",
].join(" ");

function axisCard(axis, label) {
  return {
    axis,
    title: `${label} 축의 핵심 변화와 다음 확인 지점을 함께 읽는 헤드라인`,
    brief: {
      headline: `${label} 신호는 엇갈렸고 다음 발표가 방향을 가른다`,
      summary: `${label} 시장은 가격 신호와 실제 수요가 엇갈리는 구간이다.`,
      keyNumbers: [
        { label: "가격", value: "+55%", context: "계약가", tone: "positive" },
        { label: "소매", value: "-14.3%", context: "월간", tone: "negative" },
        { label: "금리", value: "4.76%", context: "미국 10년물", tone: "neutral" },
        { label: "확률", value: "54.6%", context: "인상 가능성", tone: "warning" },
      ],
      flow: [
        { label: "정책 신호", detail: "동결 가능성", tone: "positive" },
        { label: "시장 반응", detail: "금리 하락", tone: "neutral" },
        { label: "다음 확인", detail: "고용·물가", tone: "warning" },
      ],
      scenarioGuide: [
        { polarity: "positive", condition: `${label} 우호 조건`, outcome: "위험선호가 이어진다." },
        { polarity: "negative", condition: `${label} 경계 조건`, outcome: "가격 되돌림이 커진다." },
      ],
      watchlist: [
        { label: "다음 발표", current: "현재 중립", trigger: "예상 범위를 벗어나는지 확인" },
        { label: "가격 경계", current: "괴리 지속", trigger: "두 가격이 같은 방향으로 움직이는지 확인" },
      ],
      bottomLine: "방향을 단정하기보다 다음 지표에서 괴리가 좁혀지는지 확인한다.",
    },
    phenomenon: [
      `## 무슨 일이 있었나\n\n${paragraph}`,
      `## 해석\n\n${paragraph}`,
      `**추가 연구 후 정정** — 확인된 후속 수치를 반영하되 기존 판단 근거는 유지한다.`,
    ].join("\n\n"),
    scenarios: [
      {
        polarity: "positive",
        thesis: `${label}의 우호적 흐름이 다음 발표까지 이어진다.`,
        beneficiaries: [
          {
            direction: "direct",
            polarity: "benefit",
            kind: "sector",
            name: "범용 메모리(DRAM)",
            rationale: "수요 증가가 가동률과 가격 협상력을 함께 끌어올린다.",
            financials: "매출 +18%, 영업이익률 +3.2%p",
          },
        ],
      },
      {
        polarity: "negative",
        thesis: `${label}의 가격 신호가 재차 약해진다. 재고 소진이 늦어지면 마진 압박도 길어진다.`,
        beneficiaries: [
          {
            direction: "indirect",
            polarity: "damage",
            kind: "stock",
            name: "위험 종목 (EMBJ3.S)",
            rationale: "판매 단가 하락이 고정비 부담을 키운다.",
            financials: "영업이익률 -2.1%p",
          },
        ],
      },
    ],
    deep_dive: {
      topic: `${label} 추가 검증`,
      conclusion: "후속 데이터가 필요하다.",
      findings: [{
        label: "근거",
        answer: "공식 발표를 확인했다. 계약 가격은 올랐지만 소매 가격은 내려갔다. 다음 발표에서 괴리가 좁혀지는지 확인해야 한다.</answer>\n<parameter name=\"numbers\">not-json",
        numbers: ["+55%", "-14.3%"],
        sources: [
          { title: "공식 발표", url: "https://example.com/official", published: "2026-09-04" },
          { title: "가격 통계", url: "https://example.com/prices", published: "2026-09-03" },
        ],
      }, {
        label: "가정",
        answer: "후속 추세를 확인했다.</answer>\n<parameter name=\"numbers\">[\"66%\"]",
        numbers: [],
        sources: [],
      }],
    },
    watch_signals: ["다음 가격 발표", "환율 변동", "수요 전망"],
    sources: [{ title: "공식 자료", url: "https://example.com/source", published: "2026-09-04" }],
  };
}

async function seedAxesReport(root) {
  const reportsDir = join(root, "storage", "rag", "memory_sector", "reports");
  await mkdir(reportsDir, { recursive: true });
  const report = {
    id: REPORT_ID,
    seq: 2,
    generatedAt: "2026-09-04T06:39:09+09:00",
    title: Array.from({ length: 6 }, () => "계약 가격과 소매 가격의 괴리가 확대되는 가운데 다음 확인 지점이 중요해졌다").join(" · "),
    window: { from: "2026-09-03T18:30:00+09:00", to: "2026-09-04T06:30:00+09:00" },
    format: "axes",
    editorial: {
      label: "읽기 편집본",
      baseReportId: BASE_REPORT_ID,
      baseGeneratedAt: "2026-09-04T06:39:09+09:00",
      editedAt: "2026-09-04T14:30:00+09:00",
      headline: "계약가는 뛰고 소매가는 내렸다: 지금은 방향보다 괴리를 볼 때",
      deck: "같은 시장 안에서 엇갈리는 신호를 거시·메모리·기타 변수로 나눠 읽는다.",
      takeaways: [
        { axis: "macro", title: "거시", text: "금리 인상 공포가 완화됐지만 물가 확인이 남았다." },
        { axis: "memory", title: "메모리", text: "계약가 급등과 소매가 하락이 동시에 진행 중이다." },
        { axis: "other", title: "기타", text: "전쟁 비용은 현실화됐지만 시장 충격은 제한적이다." },
      ],
    },
    cards: [
      axisCard("macro", "거시"),
      { ...axisCard("memory", "메모리"), watch_signals: [] },
      axisCard("other", "기타"),
    ],
    pipeline: {
      stages: [{ name: "raw", label: "수집", inputs: Array.from({ length: 20 }, (_, i) => ({ title: `입력 ${i + 1}` })) }],
    },
    publish_status: "ok",
  };
  await writeFile(join(reportsDir, `${BASE_REPORT_ID}.json`), JSON.stringify({
    ...report,
    id: BASE_REPORT_ID,
    seq: 1,
    editorial: undefined,
  }, null, 2));
  await writeFile(join(reportsDir, `${REPORT_ID}.json`), JSON.stringify(report, null, 2));
}

function dynamicAxisCard(axis, label, topicKey) {
  const card = axisCard(axis, label);
  card.label = label;
  card.topicKey = topicKey;
  card.scenarios[0].beneficiaries[0].causalChain = "전력 수요 증가 → 직접 수주 확대";
  card.scenarios[0].beneficiaries[0].evidence = "전력망 발주 계획";
  card.scenarios[0].beneficiaries.push({
    direction: "indirect",
    polarity: "benefit",
    kind: "stock",
    name: "LS ELECTRIC (010120)",
    rationale: "전력망 투자가 배전기기 수요로 이어진다.",
    financials: "수주잔고 +12%",
    causalChain: "전력 수요 증가 → 송배전 투자 → 배전기기 수주 증가",
    evidence: "회사 수주잔고와 전력기기 매출 공시",
  });
  card.scenarios[1].beneficiaries.unshift({
    direction: "direct",
    polarity: "damage",
    kind: "sector",
    name: "방산 수출 섹터",
    rationale: "승인 지연이 당기 인도량을 낮춘다.",
    financials: "인도 일정 1개 분기 지연",
    causalChain: "수출 승인 지연 → 직접 인도량 감소",
    evidence: "수출 승인 일정",
  });
  card.scenarios[1].beneficiaries[1] = {
    ...card.scenarios[1].beneficiaries[1],
    name: "한화에어로스페이스 (012450)",
    causalChain: "수출 승인 지연 → 인도 지연 → 매출 인식 지연",
    evidence: "회사 수주잔고와 인도 일정 공시",
  };
  card.scenarios.forEach((scenario) => {
    scenario.beneficiaries.forEach((beneficiary) => {
      beneficiary.readerCopy = {
        displayName: beneficiary.name.replace(/\s*\([^)]+\)\s*$/, ""),
        rationale: "핵심 사건의 변화가 해당 대상의 사업 여건에 영향을 준다.",
        causalChain: "핵심 사건에서 시작된 변화가 관련 산업을 거쳐 해당 대상까지 전달된다.",
        evidence: beneficiary.kind === "stock" ? "회사 공시에서 관련 사업 근거를 확인했다." : "업종 자료에서 관련 근거를 확인했다.",
        financials: beneficiary.financials ? `핵심 재무 지표는 ${beneficiary.financials}다.` : "",
      };
    });
  });
  return card;
}

async function seedDynamicReport(root) {
  const reportsDir = join(root, "storage", "rag", "memory_sector", "reports");
  await mkdir(reportsDir, { recursive: true });
  const cards = [
    dynamicAxisCard("macro", "거시", "macro"),
    dynamicAxisCard("topic1", "AI 데이터센터 전력망", "ai-power-grid"),
    dynamicAxisCard("topic2", "방산·조선 수출 사이클", "defense-exports"),
  ];
  cards[1].scenarios[0].beneficiaries[1] = {
    ...cards[1].scenarios[0].beneficiaries[1],
    name: "램리서치 (LRCX)",
    evidence: "equip_revenue LRCX 6.72십억(+15.1% QoQ @2026-06), AMAT 7.91십억(+12.8% QoQ)"
      + " 선행 배경 설명".repeat(90) + " 후속 공식 발표에서 최종 승인 거절을 확인했다.",
    financials: "LRCX 분기매출 6.72십억(+15.1% QoQ, 직전 5.84)",
    readerCopy: {
      displayName: "램리서치",
      rationale: "데이터센터 투자 확대가 식각·증착 장비 수요로 이어져 램리서치 실적에 영향을 준다.",
      causalChain: "데이터센터 투자가 늘면 반도체 생산설비 발주가 증가하고 램리서치 장비 매출로 연결된다.",
      evidence: "램리서치의 2026년 6월 분기 매출은 67억 2천만 달러로, 전분기보다 15.1% 증가했다. 어플라이드 머티어리얼즈 매출도 전분기보다 12.8% 늘었다.",
      financials: "램리서치의 매출 증가율은 비교 대상 장비사보다 높았다.",
    },
  };
  cards[1].title = "AI 전력망과 방산 수출이 당일 시장을 이끈다";
  const report = {
    id: DYNAMIC_REPORT_ID,
    seq: 3,
    generatedAt: "2026-09-04T18:42:00+09:00",
    title: "AI 전력망과 방산 수출이 당일 시장을 이끈다",
    window: { from: "2026-09-04T06:30:00+09:00", to: "2026-09-04T18:30:00+09:00" },
    format: "axes",
    axisModel: "topics_v1",
    leadAxis: "topic1",
    readerModel: "brief_v1",
    finalOpinion: { text: "각 토픽의 전이 경로를 확인한다.", confidence: "중" },
    claims: [],
    editorial: {
      label: "읽기 편집본",
      baseReportId: DYNAMIC_REPORT_ID,
      baseGeneratedAt: "2026-09-04T18:42:00+09:00",
      editedAt: "2026-09-04T18:42:00+09:00",
      headline: "AI 전력망과 방산 수출이 당일 시장을 이끈다",
      deck: "거시 환경과 당일 핵심 토픽의 직접·간접 영향을 함께 읽는다.",
      takeaways: [
        { axis: "macro", title: "거시", text: "금리 경로를 확인한다." },
        { axis: "topic1", title: "AI 데이터센터 전력망", text: "전력 수요의 직접 영향을 본다." },
        { axis: "topic2", title: "방산·조선 수출 사이클", text: "수출의 간접 영향을 본다." },
      ],
    },
    cards,
    pipeline: { stages: [] },
    publish_status: "ok",
  };
  await writeFile(join(reportsDir, `${DYNAMIC_REPORT_ID}.json`), JSON.stringify(report, null, 2));
  await writeFile(join(reportsDir, `${FALLBACK_REPORT_ID}.json`), JSON.stringify({
    ...report,
    id: FALLBACK_REPORT_ID,
    seq: 4,
    generatedAt: "2026-09-04T05:00:00+09:00",
    title: "",
    format: "legacy",
    axisModel: undefined,
    leadAxis: undefined,
    readerModel: undefined,
    cards: [],
    editorial: undefined,
  }, null, 2));
  const collisionCards = [
    dynamicAxisCard("macro", "거시 A", "macro-a"),
    dynamicAxisCard("macro", "거시 B", "macro-b"),
    dynamicAxisCard("macro-2", "거시 C", "macro-c"),
  ];
  collisionCards.forEach((card) => { delete card.brief; });
  await writeFile(join(reportsDir, `${COLLISION_REPORT_ID}.json`), JSON.stringify({
    ...report,
    id: COLLISION_REPORT_ID,
    seq: 5,
    generatedAt: "2026-09-04T04:00:00+09:00",
    title: "축 식별자 충돌 회귀 테스트",
    axisModel: undefined,
    leadAxis: undefined,
    readerModel: undefined,
    editorial: undefined,
    cards: collisionCards,
  }, null, 2));
  const errorReport = structuredClone(report);
  errorReport.id = ERROR_REPORT_ID;
  errorReport.seq = 6;
  errorReport.generatedAt = "2026-09-04T03:00:00+09:00";
  errorReport.editorial.baseReportId = ERROR_REPORT_ID;
  errorReport.editorial.baseGeneratedAt = errorReport.generatedAt;
  errorReport.editorial.editedAt = errorReport.generatedAt;
  errorReport.cards[2] = {
    axis: "topic2",
    label: "원자재 공급",
    topicKey: "commodities-supply",
    title: "원자재 공급 분석을 완료하지 못했다",
    brief: {
      ...axisCard("topic2", "원자재 공급").brief,
      summary: "자료 수집은 완료됐지만 의미 감사를 통과하지 못해 방향 판단을 보류한다.",
      bottomLine: "다음 생성에서 감사 통과 여부를 다시 확인한다.",
    },
    phenomenon: "",
    deep_dive: {},
    scenarios: [],
    watch_signals: [],
    sources: [],
    error: "generation timeout",
  };
  await writeFile(join(reportsDir, `${ERROR_REPORT_ID}.json`), JSON.stringify(errorReport, null, 2));
}

async function loginAndOpenList(page, baseUrl) {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.locator("#loginUsername").fill(TEST_USERNAME);
  await page.locator("#loginPassword").fill(TEST_PASSWORD);
  await page.locator("#loginButton").click();
  await page.locator("#homeView").waitFor({ state: "visible" });
  await page.locator("#reportNavButton").click();
  await page.locator(".report-head").waitFor({ state: "visible" });
}

async function loginAndOpenReport(page, baseUrl, reportId = REPORT_ID) {
  await loginAndOpenList(page, baseUrl);
  await page.locator(`.report-row[data-id="${reportId}"]`).click();
  await page.locator(".axes-tabs").waitFor({ state: "visible" });
}

async function captureReportScreenshot(page, name, fullPage = false) {
  if (!SCREENSHOT_DIR) return;
  await mkdir(SCREENSHOT_DIR, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SCREENSHOT_DIR, `${name}.png`), fullPage });
}

test("axes reports provide a scan-first reading workflow at mobile and desktop widths", async (t) => {
  const root = await createTestRoot();
  await seedAxesReport(root);
  const server = await startTestServer({ root });
  const browser = await chromium.launch({ headless: true });
  t.after(async () => {
    await browser.close();
    await server.stop({ removeRoot: true });
  });

  for (const viewport of VIEWPORTS) {
    await t.test(viewport.name, async () => {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      page.setDefaultTimeout(5_000);
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));

      await loginAndOpenReport(page, server.baseUrl);

      assert.equal(await page.locator(".report-title").textContent(),
        "계약가는 뛰고 소매가는 내렸다: 지금은 방향보다 괴리를 볼 때");
      await page.getByText("이번 리포트 한눈에 보기", { exact: true }).waitFor();
      await page.getByText("한 줄 결론", { exact: true }).waitFor();
      await page.getByText("같은 시장 안에서 엇갈리는 신호를 거시·메모리·기타 변수로 나눠 읽는다.", { exact: true }).waitFor();
      assert.equal(await page.locator(".editorial-nav-card").count(), 3);
      const takeawayColumns = await page.locator(".editorial-takeaways").evaluate((node) =>
        getComputedStyle(node).gridTemplateColumns.split(" ").filter(Boolean).length,
      );
      assert.equal(takeawayColumns, viewport.takeawayColumns);
      const provenance = page.locator(".editorial-provenance");
      assert.equal(await provenance.evaluate((node) => node.open), false);
      assert.equal(await provenance.locator(":scope > summary").evaluate((node) => getComputedStyle(node, "::after").content), "none",
        "original information uses one disclosure icon");
      await provenance.locator(":scope > summary").click();
      await provenance.getByText("원본 2026-09-04 06:39", { exact: true }).waitFor({ state: "visible" });
      assert.equal(await provenance.locator(`a[href="#report-${BASE_REPORT_ID}"]`).count(), 1);
      await provenance.locator(":scope > summary").click();

      await page.locator('.editorial-nav-card[data-axis="memory"]').click();
      assert.equal(await page.getByRole("tab", { name: "메모리" }).getAttribute("aria-selected"), "true");
      await page.locator('.editorial-nav-card[data-axis="macro"]').click();

      await page.locator(".axes-panel.on .axis-brief-label").waitFor();
      assert.equal(await page.locator(".axes-panel.on .axis-title").textContent(),
        "거시 신호는 엇갈렸고 다음 발표가 방향을 가른다");
      assert.equal(await page.locator(".axes-panel.on .axis-metric").count(), 4);
      const metricColumns = await page.locator(".axes-panel.on .axis-metrics").evaluate((node) =>
        getComputedStyle(node).gridTemplateColumns.split(" ").filter(Boolean).length,
      );
      assert.equal(metricColumns, viewport.metricColumns);
      assert.equal(await page.locator(".axes-panel.on .axis-flow-node").count(), 3);

      const detailedAnalysis = page.locator(".axes-panel.on .axis-analysis");
      assert.equal(await detailedAnalysis.evaluate((node) => node.open), false);
      await detailedAnalysis.locator(":scope > summary").click();
      await page.locator(".axes-panel.on").getByText("추가 연구 후 정정", { exact: true }).waitFor({ state: "visible" });
      assert.equal(await detailedAnalysis.locator(".axis-original-kicker").textContent(), "원문 핵심 문장");
      assert.match(await detailedAnalysis.locator(".axis-original-text").textContent(), /거시 축의 핵심 변화/);
      assert.equal(await detailedAnalysis.locator(".analysis-section").count(), 3);
      assert.deepEqual(
        await detailedAnalysis.locator(".analysis-section-title").allTextContents(),
        ["무슨 일이 있었나", "해석", "추가 연구 후 정정"],
      );
      if (viewport.name === "desktop") {
        const [readingWidth, panelWidth] = await Promise.all([
          detailedAnalysis.locator(".axis-reading-body").evaluate((node) => node.getBoundingClientRect().width),
          page.locator(".axes-panel.on .axis-card").evaluate((node) => node.getBoundingClientRect().width),
        ]);
        assert.ok(readingWidth >= panelWidth - 40,
          `detailed analysis uses the available card width: ${readingWidth}px of ${panelWidth}px`);
      }

      const titleToggle = page.locator(".report-title-toggle");
      assert.equal(await titleToggle.count(), 0, "the editorial headline is short enough to scan without a disclosure");

      const tabList = page.getByRole("tablist", { name: "리포트 관점" });
      const tabs = tabList.getByRole("tab");
      assert.equal(await tabs.count(), 3);
      assert.equal(await tabs.nth(0).getAttribute("aria-selected"), "true");
      await tabs.nth(0).focus();
      await page.keyboard.press("ArrowRight");
      assert.equal(await tabs.nth(1).getAttribute("aria-selected"), "true");
      await page.getByRole("tabpanel", { name: "메모리" }).waitFor({ state: "visible" });

      const scenarioImpacts = page.locator(".axes-panel.on .scenario-impact");
      assert.equal(await scenarioImpacts.count(), 2);
      assert.equal(await scenarioImpacts.first().evaluate((node) => node.open), false);
      const impactSummary = scenarioImpacts.first().locator(":scope > summary");
      assert.ok((await impactSummary.boundingBox()).height <= 36, "scenario evidence control stays compact");
      assert.equal(await impactSummary.evaluate((node) => getComputedStyle(node, "::after").content), "none",
        "scenario evidence control has only one disclosure icon");
      assert.match(await page.locator(".axes-panel.on .scn-condition").first().textContent(), /메모리 우호 조건/);
      await page.getByText("메모리의 우호적 흐름이 다음 발표까지 이어진다.", { exact: true })
        .waitFor({ state: "hidden" });
      await scenarioImpacts.first().locator(":scope > summary").click();
      await page.getByText("메모리의 우호적 흐름이 다음 발표까지 이어진다.", { exact: true })
        .waitFor({ state: "visible" });
      const beneficiaryCard = page.locator(".axes-panel.on .bene-card").first();
      await beneficiaryCard.waitFor({ state: "visible" });
      assert.equal(await beneficiaryCard.locator(".bname").textContent(), "범용 메모리(DRAM)",
        "historical sector acronyms are explanatory names, not stock tickers");
      assert.equal(await beneficiaryCard.locator(".bene-rationale .bene-detail-label").textContent(), "왜 영향을 받나");
      assert.equal(await beneficiaryCard.locator(".bene-financials .bene-detail-label").textContent(), "숫자로 보면");
      assert.match(await beneficiaryCard.locator(".bene-financials").textContent(), /영업이익률/);
      assert.equal(await page.locator(".axes-panel.on .bene-causal-chain").count(), 0,
        "legacy impacts without a causalChain do not gain an empty row");
      assert.equal(await page.locator(".axes-panel.on .bene-evidence").count(), 0,
        "legacy impacts without company evidence do not gain an empty row");
      assert.ok(await page.locator(".axes-panel.on .scn-reason-list li").count() >= 1);
      assert.equal(await page.locator(".axes-panel.on .axis-watch-card").count(), 2);
      assert.equal(await page.locator(".axes-panel.on .axis-watch-original").count(), 0,
        "editorial watch cards do not require legacy watch signals");
      await scenarioImpacts.nth(1).locator(":scope > summary").click();
      assert.equal(await scenarioImpacts.nth(1).locator(".bname").textContent(), "위험 종목",
        "alphanumeric Reuters ticker suffixes stay out of historical reader views");

      const scenarioColumns = await page.locator(".axes-panel.on .axis-scenarios").evaluate((node) =>
        getComputedStyle(node).gridTemplateColumns.split(" ").filter(Boolean).length,
      );
      assert.equal(scenarioColumns, 1, "positive and negative scenarios use the full width in sequence");
      assert.equal(await page.locator(".axes-panel.on .scn-condition .scn-key").first().textContent(), "조건");
      assert.equal(await page.locator(".axes-panel.on .scn-outcome .scn-key").first().textContent(), "예상 결과");
      const deepDive = page.locator(".axes-panel.on .axis-deep");
      assert.equal(await deepDive.evaluate((node) => node.open), false);
      const deepSummary = deepDive.locator(":scope > summary");
      assert.equal(await deepSummary.locator(".axis-deep-heading").textContent(), "추가 연구");
      assert.ok((await deepSummary.boundingBox()).height <= 48, "additional research heading stays on one line");
      await deepSummary.click();
      await deepDive.getByText("메모리 추가 검증", { exact: true }).waitFor({ state: "visible" });
      assert.equal(await deepDive.locator(".dd-find-card").count(), 2);
      assert.equal(await deepDive.locator(".dd-answer-paragraph").count(), 4);
      assert.deepEqual(await deepDive.locator(".dd-number").allTextContents(), ["+55%", "-14.3%", "66%"]);
      assert.equal((await deepDive.textContent()).includes("<parameter"), false,
        "model transport markup is presented as structured numbers instead of raw text");
      const deepSources = deepDive.locator(".dd-sources");
      assert.equal(await deepSources.evaluate((node) => node.open), false);
      assert.equal(await deepSources.locator("a").count(), 2, "every source is preserved behind one compact control");
      assert.equal(await deepSources.locator(":scope > summary").textContent(), "근거 링크 2개");
      assert.equal(await deepSources.locator(":scope > summary").evaluate((node) => getComputedStyle(node, "::after").content), "none",
        "evidence links use one disclosure icon");
      await deepSources.locator(":scope > summary").click();
      await deepSources.locator("a").first().waitFor({ state: "visible" });
      const reportProcess = page.locator(".report-process");
      assert.equal(await reportProcess.evaluate((node) => node.open), false);
      assert.equal(await reportProcess.locator(".flow-stage").count(), 0,
        "collapsed process does not build the expensive trace DOM");
      await reportProcess.locator(":scope > summary").click();
      await reportProcess.locator(".flow-stage").waitFor();
      assert.equal(await reportProcess.locator(".flow-stage").count(), 1,
        "opening the process renders every trace stage on demand");
      await reportProcess.locator(":scope > summary").click();

      await page.evaluate(() => window.scrollTo(0, 1200));
      const stickyTabs = await page.locator(".axes-tabs").boundingBox();
      assert.ok(stickyTabs && stickyTabs.y >= 0 && stickyTabs.y < viewport.height,
        "axis tabs remain reachable while reading");
      await tabs.nth(2).click();
      const newPanel = await page.getByRole("tabpanel", { name: "기타" }).boundingBox();
      assert.ok(newPanel && newPanel.y >= 50 && newPanel.y < 180,
        `a newly selected axis starts at the top of the reading area: ${newPanel?.y}`);

      const horizontalOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      assert.ok(horizontalOverflow <= 1, `horizontal overflow: ${horizontalOverflow}px`);
      assert.deepEqual(pageErrors, []);

      await context.close();
    });
  }

  const directContext = await browser.newContext({ viewport: VIEWPORTS[0] });
  const directPage = await directContext.newPage();
  await directPage.goto(server.baseUrl, { waitUntil: "domcontentloaded" });
  await directPage.locator("#loginUsername").fill(TEST_USERNAME);
  await directPage.locator("#loginPassword").fill(TEST_PASSWORD);
  await directPage.locator("#loginButton").click();
  await directPage.locator("#homeView").waitFor({ state: "visible" });
  await directPage.goto(`${server.baseUrl}/#report-${REPORT_ID}`, { waitUntil: "domcontentloaded" });
  const directProvenance = directPage.locator(".editorial-provenance");
  await directProvenance.locator(":scope > summary").click();
  assert.equal(await directProvenance.locator(`a[href="#report-${BASE_REPORT_ID}"]`).count(), 1,
    "a direct report bookmark still resolves the active source report");
  await directContext.close();

  await rm(join(root, "storage", "rag", "memory_sector", "reports", `${BASE_REPORT_ID}.json`));
  const finalContext = await browser.newContext({ viewport: VIEWPORTS[0] });
  const finalPage = await finalContext.newPage();
  await loginAndOpenReport(finalPage, server.baseUrl);
  const finalProvenance = finalPage.locator(".editorial-provenance");
  await finalProvenance.locator(":scope > summary").click();
  assert.equal(await finalProvenance.locator("a").count(), 0,
    "a republished final report does not link to an archived source report");
  assert.match(await finalProvenance.locator(".editorial-provenance-title").textContent(), /원문 제목/);
  await finalContext.close();
});

test("topics_v1 reports keep exact topic identity and readable dynamic labels", async (t) => {
  const root = await createTestRoot();
  await seedDynamicReport(root);
  const server = await startTestServer({ root });
  const browser = await chromium.launch({ headless: true });
  t.after(async () => {
    await browser.close();
    await server.stop({ removeRoot: true });
  });

  for (const viewport of VIEWPORTS) {
    await t.test(viewport.name, async () => {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      page.setDefaultTimeout(5_000);
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));

      await loginAndOpenList(page, server.baseUrl);
      const listSubtitle = await page.locator(".report-head .sub").textContent();
      assert.equal(listSubtitle, "매일 06:30·18:30 KST 생성 시작 · 거시·당일 핵심 토픽 · 최신순");
      assert.equal(listSubtitle.includes("메모리 반도체 밸류체인"), false);
      assert.equal(
        await page.locator(`.report-row[data-id="${FALLBACK_REPORT_ID}"] .title`).textContent(),
        "시황 리포트",
      );
      let horizontalOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      assert.ok(horizontalOverflow <= 1, `report list horizontal overflow: ${horizontalOverflow}px`);
      await captureReportScreenshot(page, `${viewport.name}-list`);

      const dynamicRow = page.locator(`.report-row[data-id="${DYNAMIC_REPORT_ID}"]`);
      assert.equal(
        await dynamicRow.locator(".meta").textContent(),
        "읽기 편집본 · 자동 생성",
        "an integrated reading layer is not presented as a separate source report",
      );
      assert.equal(
        await dynamicRow.getAttribute("href"),
        `#report-${encodeURIComponent(DYNAMIC_REPORT_ID)}`,
        "a report row exposes a bookmarkable detail URL",
      );
      await page.locator("#reportNavButton").focus();
      let reachedDynamicRow = false;
      for (let press = 0; press < 40; press += 1) {
        await page.keyboard.press("Tab");
        reachedDynamicRow = await dynamicRow.evaluate((node) => node === document.activeElement);
        if (reachedDynamicRow) break;
      }
      assert.equal(reachedDynamicRow, true, "Tab reaches the report row");
      assert.notEqual(
        await dynamicRow.evaluate((node) => getComputedStyle(node).outlineStyle),
        "none",
        "keyboard focus is visible",
      );
      await page.keyboard.press("Enter");
      await page.locator(".axes-tabs").waitFor({ state: "visible" });
      assert.equal(new URL(page.url()).hash, `#report-${encodeURIComponent(DYNAMIC_REPORT_ID)}`);

      const tabs = page.getByRole("tablist", { name: "리포트 관점" }).getByRole("tab");
      assert.deepEqual(await tabs.allTextContents(), ["거시", "AI 데이터센터 전력망", "방산·조선 수출 사이클"]);
      assert.deepEqual(await page.locator(".axis-chip").allTextContents(),
        ["거시", "AI 데이터센터 전력망", "방산·조선 수출 사이클"]);
      assert.deepEqual(await page.locator(".editorial-nav-card").evaluateAll((nodes) =>
        nodes.map((node) => node.dataset.axis)), ["macro", "topic1", "topic2"]);
      assert.equal(await page.locator(".axis-brief").count(), 3,
        "every generated topic card keeps the permanent scan-first brief");
      const integratedProvenance = page.locator(".editorial-provenance");
      assert.equal(await integratedProvenance.locator(":scope > summary").textContent(), "생성 정보");
      await integratedProvenance.locator(":scope > summary").click();
      assert.equal(await integratedProvenance.locator("a").count(), 0);
      assert.match(await integratedProvenance.textContent(), /상세 분석·근거·출처는 아래 카드에 그대로 보존/);
      await integratedProvenance.locator(":scope > summary").click();

      await page.locator('.editorial-nav-card[data-axis="topic2"]').click();
      await page.locator(".axes-panel.on").evaluate((node) =>
        Promise.all(node.getAnimations().map((animation) => animation.finished)));
      assert.deepEqual(await tabs.evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("aria-selected"))), ["false", "false", "true"]);
      const selectedTab = page.locator('.axes-tab[aria-selected="true"]');
      const visiblePanel = page.locator(".axes-panel.on:not([hidden])");
      assert.equal(await selectedTab.count(), 1);
      assert.equal(await visiblePanel.count(), 1);
      assert.equal(await selectedTab.getAttribute("data-axis"), "topic2");
      assert.equal(await visiblePanel.getAttribute("data-axis"), await selectedTab.getAttribute("data-axis"));
      assert.equal(await visiblePanel.evaluate((node) => getComputedStyle(node).display), "block");
      assert.equal(await visiblePanel.evaluate((node) => getComputedStyle(node).opacity), "1");
      assert.equal(await visiblePanel.locator(".axis-chip").textContent(), "방산·조선 수출 사이클");

      const directImpact = page.locator(".axes-panel.on .bene-card").first();
      const stockImpact = page.locator(".axes-panel.on .bene-card").last();
      const scenarioCards = visiblePanel.locator(".axis-scn");
      assert.equal(await scenarioCards.count(), 2);
      for (let index = 0; index < 2; index += 1) {
        assert.equal(await scenarioCards.nth(index).locator(".bene-badge.direct").count(), 1,
          `scenario ${index} keeps one direct impact`);
        assert.equal(await scenarioCards.nth(index).locator(".bene-badge.indirect").count(), 1,
          `scenario ${index} keeps one indirect impact`);
        assert.equal(await scenarioCards.nth(index).locator(".bene-causal-chain").count(), 2,
          `scenario ${index} renders every transmission path`);
        assert.equal(await scenarioCards.nth(index).locator(".bene-evidence").count(), 2,
          `scenario ${index} renders every readable evidence row`);
      }
      assert.equal(await directImpact.locator(".bene-badge.direct").textContent(), "직접");
      assert.equal(await stockImpact.locator(".bene-badge.indirect").textContent(), "간접");
      assert.equal(await stockImpact.locator(".bname").textContent(), "한화에어로스페이스");
      assert.match(await directImpact.locator(".bene-causal-chain").textContent(), /어떻게 번지나.*핵심 사건/);
      assert.match(await stockImpact.locator(".bene-evidence").textContent(), /확인된 근거.*회사 공시/);
      assert.equal((await visiblePanel.textContent()).includes("(012450)"), false);

      await page.locator('.editorial-nav-card[data-axis="topic1"]').click();
      const topicOnePanel = page.locator(".axes-panel.on:not([hidden])");
      await topicOnePanel.locator(".scenario-impact").first().locator(":scope > summary").click();
      const readableLam = topicOnePanel.locator(".bene-card").filter({ hasText: "램리서치" }).first();
      await readableLam.waitFor({ state: "visible" });
      const readableLamText = await readableLam.locator(".bene-detail:not(.bene-raw-detail)").allTextContents()
        .then((parts) => parts.join(" "));
      assert.match(readableLamText, /2026년 6월 분기 매출/);
      assert.match(readableLamText, /전분기보다 15.1% 증가/);
      for (const internal of ["(LRCX)", "equip_revenue", "AMAT", "QoQ", "분기매출 6.72십억"])
        assert.equal(readableLamText.includes(internal), false, `${internal} stays out of reader-facing copy`);
      const rawData = readableLam.locator(".bene-raw");
      assert.equal(await rawData.evaluate((node) => node.open), false);
      assert.equal(await rawData.locator(":scope > summary").textContent(), "원문 데이터 보기");
      await rawData.locator(":scope > summary").click();
      const rawDataText = await rawData.locator(".bene-raw-detail").allTextContents()
        .then((parts) => parts.join(" "));
      assert.match(rawDataText, /equip_revenue.*LRCX.*AMAT/);
      assert.match(rawDataText, /후속 공식 발표에서 최종 승인 거절/,
        "long raw evidence remains user-accessible after readable copy clipping");

      const ids = await page.locator("[id^=axis-tab-], [id^=axis-panel-]")
        .evaluateAll((nodes) => nodes.map((node) => node.id));
      assert.equal(new Set(ids).size, ids.length, `axis DOM ids must be unique: ${ids.join(", ")}`);
      for (const axis of ["macro", "topic1", "topic2"]) {
        assert.ok(ids.includes(`axis-tab-${axis}`));
        assert.ok(ids.includes(`axis-panel-${axis}`));
      }
      if (viewport.name === "mobile") {
        assert.ok(await tabs.evaluateAll((nodes) => nodes.every((node) => node.scrollWidth <= node.clientWidth + 1)),
          "dynamic tab labels wrap inside their available width");
      }
      horizontalOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      assert.ok(horizontalOverflow <= 1, `dynamic report horizontal overflow: ${horizontalOverflow}px`);
      assert.deepEqual(pageErrors, []);
      await captureReportScreenshot(page, `${viewport.name}-detail`, true);

      await page.locator(".report-back").click();
      await page.locator(`.report-row[data-id="${FALLBACK_REPORT_ID}"]`).click();
      assert.equal(await page.locator(".report-title").textContent(), "시황 리포트");

      await page.locator(".report-back").click();
      await page.locator(`.report-row[data-id="${COLLISION_REPORT_ID}"]`).click();
      await page.locator(".axes-tabs").waitFor({ state: "visible" });
      const collisionIds = await page.locator(
        "[id^=axis-tab-], [id^=axis-panel-], [id^=axis-phenomenon-]",
      ).evaluateAll((nodes) => nodes.map((node) => node.id));
      assert.equal(collisionIds.length, 9);
      assert.equal(
        new Set(collisionIds).size,
        collisionIds.length,
        `collision-prone axis names still produce unique DOM ids: ${collisionIds.join(", ")}`,
      );

      await context.close();
    });
  }
});

test("topics_v1 error cards still render their persisted reading brief", async (t) => {
  const root = await createTestRoot();
  await seedDynamicReport(root);
  const server = await startTestServer({ root });
  const browser = await chromium.launch({ headless: true });
  t.after(async () => {
    await browser.close();
    await server.stop({ removeRoot: true });
  });

  const page = await browser.newPage({ viewport: VIEWPORTS[0] });
  await loginAndOpenReport(page, server.baseUrl, ERROR_REPORT_ID);
  await page.getByRole("tab", { name: "원자재 공급" }).click();

  const panel = page.locator(".axes-panel.on:not([hidden])");
  assert.equal(await panel.locator(".axis-brief").count(), 1);
  await panel.getByText("자료 수집은 완료됐지만 의미 감사를 통과하지 못해 방향 판단을 보류한다.", { exact: true }).waitFor();
  await panel.getByText("원자재 공급 우호 조건", { exact: true }).waitFor();
  await panel.getByText("다음 발표", { exact: true }).waitFor();
  await panel.getByText("generation timeout", { exact: true }).waitFor();
});
