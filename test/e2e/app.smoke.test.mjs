import assert from "node:assert/strict";
import test from "node:test";

import { chromium } from "playwright";

import {
  TEST_PASSWORD,
  TEST_USERNAME,
  createTestRoot,
  seedDocument,
  startTestServer,
} from "../helpers/test-server.mjs";

const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
];

test("primary UI flows work at mobile and desktop widths", async (t) => {
  const root = await createTestRoot();
  await seedDocument(root);
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
      await page.locator("#loginView").waitFor({ state: "visible" });
      await page.locator("#loginUsername").fill(TEST_USERNAME);
      await page.locator("#loginPassword").fill(TEST_PASSWORD);
      await page.locator("#loginButton").click();

      await page.locator("#homeView").waitFor({ state: "visible" });
      await page.locator(".doc-item-title", { hasText: "Original title.pdf" }).waitFor();
      assert.equal(new URL(page.url()).hash, "#home");

      const horizontalOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      assert.ok(horizontalOverflow <= 1, `horizontal overflow: ${horizontalOverflow}px`);

      await page.locator(".doc-item-main").click();
      await page.locator("#readerView").waitFor({ state: "visible" });
      assert.equal(await page.locator("#documentTitle").textContent(), "Original title.pdf");
      assert.equal(new URL(page.url()).hash, "#read-document-1");

      await page.locator("#backButton").click();
      await page.locator("#homeView").waitFor({ state: "visible" });

      await page.locator("#inspectNavButton").click();
      await page.locator("#analysisView").waitFor({ state: "visible" });
      assert.equal(new URL(page.url()).hash, "#analysis");

      await page.locator("#chatNavButton").click();
      await page.locator("#chatView").waitFor({ state: "visible" });
      assert.match(new URL(page.url()).hash, /^#chat/);

      await page.locator("#bloggerNavButton").click();
      await page.locator("#bloggerView").waitFor({ state: "visible" });
      await page.locator("#bloggerView h2", { hasText: "블로거" }).waitFor();
      assert.equal(new URL(page.url()).hash, "#blogger");

      await page.locator("#memoryNavButton").click();
      await page.locator("#memoryView").waitFor({ state: "visible" });
      assert.equal(new URL(page.url()).hash, "#memory");

      await page.reload({ waitUntil: "domcontentloaded" });
      await page.locator("#memoryView").waitFor({ state: "visible" });
      assert.equal(new URL(page.url()).hash, "#memory");
      assert.deepEqual(pageErrors, []);

      await context.close();
    });
  }
});

