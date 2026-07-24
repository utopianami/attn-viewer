import assert from "node:assert/strict";
import test from "node:test";

import { chromium } from "playwright";

import { startTestServer } from "../helpers/test-server.mjs";

const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
];

test("workflow review documents the Toss/Yahoo sector path at mobile and desktop widths", async (t) => {
  const server = await startTestServer();
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

      const response = await page.goto(
        `${server.baseUrl}/docs/workflow-review.html`,
        { waitUntil: "networkidle" },
      );
      assert.equal(response?.status(), 200);

      const priceCard = page.locator("#stage-price");
      await priceCard.waitFor({ state: "visible" });
      assert.match(await priceCard.textContent(), /KOSPI 보통주 200개/);
      assert.match(await priceCard.textContent(), /WTS inventory는 42개/);

      await priceCard.locator("details.prompt summary").click();
      await priceCard.locator("details.prompt pre").waitFor({ state: "visible" });

      const overflow = await page.evaluate(() => ({
        page: document.documentElement.scrollWidth - window.innerWidth,
        priceCard: document.querySelector("#stage-price").scrollWidth
          - document.querySelector("#stage-price").clientWidth,
        offenders: [...document.querySelectorAll("body *")]
          .map((element) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return {
              tag: element.tagName.toLowerCase(),
              id: element.id,
              className: String(element.className || "").slice(0, 80),
              right: Math.round(rect.right),
              width: Math.round(rect.width),
              clientWidth: element.clientWidth,
              scrollWidth: element.scrollWidth,
              overflowX: style.overflowX,
            };
          })
          .filter((item) => (
            item.overflowX === "visible"
            && (item.right > window.innerWidth + 1 || item.scrollWidth > item.clientWidth + 1)
          ))
          .sort((a, b) => (
            Math.max(b.right, b.scrollWidth) - Math.max(a.right, a.scrollWidth)
          ))
          .slice(0, 10),
      }));
      assert.ok(
        overflow.page <= 1,
        `page overflow: ${overflow.page}px; offenders: ${JSON.stringify(overflow.offenders)}`,
      );
      assert.ok(overflow.priceCard <= 1, `price card overflow: ${overflow.priceCard}px`);
      assert.deepEqual(pageErrors, []);

      await context.close();
    });
  }
});
