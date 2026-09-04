import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

import { chromium } from "playwright";

import {
  TEST_PASSWORD,
  TEST_USERNAME,
  createTestRoot,
  startTestServer,
} from "../helpers/test-server.mjs";

const REPORT_ID = "2026-09-04-1";
const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844, scenarioColumns: 1, takeawayColumns: 1, metricColumns: 2 },
  { name: "desktop", width: 1440, height: 900, scenarioColumns: 2, takeawayColumns: 3, metricColumns: 4 },
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
    phenomenon: Array.from({ length: 10 }, (_, index) =>
      `### 관찰 ${index + 1}\n\n${paragraph}`,
    ).join("\n\n"),
    scenarios: [
      {
        polarity: "positive",
        thesis: `${label}의 우호적 흐름이 다음 발표까지 이어진다.`,
        beneficiaries: [
          { direction: "direct", polarity: "benefit", kind: "sector", name: "수혜 섹터", rationale: "수요 증가" },
        ],
      },
      {
        polarity: "negative",
        thesis: `${label}의 가격 신호가 재차 약해진다.`,
        beneficiaries: [
          { direction: "indirect", polarity: "damage", kind: "stock", name: "위험 종목", rationale: "마진 축소" },
        ],
      },
    ],
    deep_dive: {
      topic: `${label} 추가 검증`,
      conclusion: "후속 데이터가 필요하다.",
      findings: [{ label: "근거", answer: "공식 발표를 확인했다.", sources: [] }],
    },
    watch_signals: ["다음 가격 발표", "환율 변동", "수요 전망"],
    sources: [{ title: "공식 자료", url: "https://example.com/source", published: "2026-09-04" }],
  };
}

async function seedAxesReport(root) {
  const reportsDir = join(root, "storage", "rag", "memory_sector", "reports");
  await mkdir(reportsDir, { recursive: true });
  await writeFile(join(reportsDir, `${REPORT_ID}.json`), JSON.stringify({
    id: REPORT_ID,
    seq: 1,
    generatedAt: "2026-09-04T06:39:09+09:00",
    title: Array.from({ length: 6 }, () => "계약 가격과 소매 가격의 괴리가 확대되는 가운데 다음 확인 지점이 중요해졌다").join(" · "),
    window: { from: "2026-09-03T18:30:00+09:00", to: "2026-09-04T06:30:00+09:00" },
    format: "axes",
    editorial: {
      label: "읽기 편집본",
      baseReportId: REPORT_ID,
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
      axisCard("memory", "메모리"),
      axisCard("other", "기타"),
    ],
    pipeline: {
      stages: [{ name: "raw", label: "수집", inputs: Array.from({ length: 20 }, (_, i) => ({ title: `입력 ${i + 1}` })) }],
    },
    publish_status: "ok",
  }, null, 2));
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
      await page.getByText("읽기 편집본", { exact: true }).waitFor();
      await page.getByText("같은 시장 안에서 엇갈리는 신호를 거시·메모리·기타 변수로 나눠 읽는다.", { exact: true }).waitFor();
      assert.equal(await page.locator(".editorial-takeaway").count(), 3);
      const takeawayColumns = await page.locator(".editorial-takeaways").evaluate((node) =>
        getComputedStyle(node).gridTemplateColumns.split(" ").filter(Boolean).length,
      );
      assert.equal(takeawayColumns, viewport.takeawayColumns);

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
      await page.locator(".axes-panel.on").getByText("관찰 10", { exact: true }).waitFor({ state: "visible" });

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
      assert.match(await page.locator(".axes-panel.on .scn-condition").first().textContent(), /메모리 우호 조건/);
      await page.getByText("메모리의 우호적 흐름이 다음 발표까지 이어진다.", { exact: true })
        .waitFor({ state: "hidden" });
      await scenarioImpacts.first().locator(":scope > summary").click();
      await page.getByText("메모리의 우호적 흐름이 다음 발표까지 이어진다.", { exact: true })
        .waitFor({ state: "visible" });
      await page.locator(".axes-panel.on .bene-row").first().waitFor({ state: "visible" });
      assert.equal(await page.locator(".axes-panel.on .axis-watch-card").count(), 2);

      const scenarioColumns = await page.locator(".axes-panel.on .axis-scenarios").evaluate((node) =>
        getComputedStyle(node).gridTemplateColumns.split(" ").filter(Boolean).length,
      );
      assert.equal(scenarioColumns, viewport.scenarioColumns);
      assert.equal(await page.locator(".axes-panel.on .axis-deep").evaluate((node) => node.open), false);
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
});
