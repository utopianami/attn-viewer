import assert from "node:assert/strict";
import test from "node:test";

import { chromium } from "playwright";

import {
  TEST_PASSWORD,
  TEST_USERNAME,
  createTestRoot,
  startTestServer,
} from "../helpers/test-server.mjs";

const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
];

const SECTOR_LAYER = {
  name: "price",
  round: 0,
  data: {
    quotes: [],
    sector_momentum: {
      status: "ok",
      as_of: "2026-07-23",
      lookback_sessions: 3,
      universe_valid: 199,
      universe_requested: 200,
      coverage_pct: 99.5,
      positive_sector_count: 33,
      sectors: [
        {
          rank: 1,
          sector_name: "에너지장비및서비스",
          median_return_pct: 14.52,
          breadth_positive_pct: 80,
          member_count: 5,
          leaders: [
            { name: "HD현대에너지솔루션" },
            { name: "SK이터닉스" },
            { name: "두산퓨얼셀" },
          ],
        },
      ],
    },
  },
};

test("sector momentum layer wraps without overflow at mobile and desktop widths", async (t) => {
  const root = await createTestRoot();
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
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));

      await page.goto(server.baseUrl, { waitUntil: "networkidle" });
      await page.locator("#loginUsername").fill(TEST_USERNAME);
      await page.locator("#loginPassword").fill(TEST_PASSWORD);
      await page.locator("#loginButton").click();
      await page.locator("#homeView").waitFor({ state: "visible" });
      await page.locator("#chatNavButton").click();
      await page.locator("#chatView").waitFor({ state: "visible" });

      const rendered = await page.evaluate((layer) => {
        const thread = document.querySelector("#chatThread");
        thread.replaceChildren(renderChatLayer(layer, { defaultOpen: true }));
        const box = thread.querySelector(".chat-layer");
        return {
          text: box.querySelector(".chat-layer-body").textContent,
          pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
          layerOverflow: box.scrollWidth - box.clientWidth,
        };
      }, SECTOR_LAYER);

      assert.match(rendered.text, /상승업종 33개/);
      assert.match(rendered.text, /에너지장비및서비스: \+14.52%/);
      assert.ok(rendered.pageOverflow <= 1, `page overflow: ${rendered.pageOverflow}px`);
      assert.ok(rendered.layerOverflow <= 1, `layer overflow: ${rendered.layerOverflow}px`);
      assert.deepEqual(pageErrors, []);
      await context.close();
    });
  }
});
