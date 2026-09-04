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
            name: "수혜 섹터",
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
            name: "위험 종목",
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

async function loginAndOpenReport(page, baseUrl) {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.locator("#loginUsername").fill(TEST_USERNAME);
  await page.locator("#loginPassword").fill(TEST_PASSWORD);
  await page.locator("#loginButton").click();
  await page.locator("#homeView").waitFor({ state: "visible" });
  await page.locator("#reportNavButton").click();
  await page.locator(`.report-row[data-id="${REPORT_ID}"]`).click();
  await page.locator(".axes-tabs").waitFor({ state: "visible" });
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
      assert.equal(await beneficiaryCard.locator(".bene-rationale .bene-detail-label").textContent(), "영향 이유");
      assert.equal(await beneficiaryCard.locator(".bene-financials .bene-detail-label").textContent(), "재무 숫자");
      assert.match(await beneficiaryCard.locator(".bene-financials").textContent(), /영업이익률/);
      assert.ok(await page.locator(".axes-panel.on .scn-reason-list li").count() >= 1);
      assert.equal(await page.locator(".axes-panel.on .axis-watch-card").count(), 2);
      assert.equal(await page.locator(".axes-panel.on .axis-watch-original").count(), 0,
        "editorial watch cards do not require legacy watch signals");

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
