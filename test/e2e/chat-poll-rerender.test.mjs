// 변경 없는 폴링 틱이 채팅 DOM을 재구축하면 안 된다 — 깜빡임·스크롤 버벅임의 근원
// (2026-07-13 ryze_yn 리포트: 답변 생성 중 화면 깜빡임 + 스크롤 잔렉)
import assert from "node:assert/strict";
import test from "node:test";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { chromium } from "playwright";

import {
  TEST_PASSWORD,
  TEST_USERNAME,
  createTestRoot,
  startTestServer,
} from "../helpers/test-server.mjs";

const CHAT_ID = "11111111-1111-4111-8111-111111111111";
const NOW = "2026-07-13T00:00:00.000Z";

// 서버 기동 '후'에 시딩 — 기동 시 sweepStaleRunningChats가 running을 failed로 뒤집음
async function seedRunningChat(root) {
  const chatsDir = join(root, "storage", "users", TEST_USERNAME, "chats");
  await mkdir(chatsDir, { recursive: true });
  const chat = {
    id: CHAT_ID,
    title: "질문",
    status: "running",
    messages: [{
      id: "m1", role: "user", content: "메모리 업황 어때?", providers: ["anthropic"],
      thinkLevel: 2, artifacts: { layers: [] }, parentMessageId: "", modelMode: "",
      status: "completed", error: "", createdAt: NOW,
    }],
    messageNotes: [],
    providers: ["anthropic"],
    thinkLevel: 2,
    artifacts: {
      layers: [{
        name: "plan", round: 0, createdAt: NOW,
        data: { tier: 2, standalone_question: "메모리 업황 어때?", sub_questions: [] },
      }],
    },
    error: "",
    createdAt: NOW,
    updatedAt: NOW,
  };
  await writeFile(join(chatsDir, `${CHAT_ID}.json`), JSON.stringify(chat, null, 2));
  await writeFile(join(chatsDir, "index.json"), JSON.stringify({
    chats: [{
      id: CHAT_ID, title: "질문", status: "running", messageCount: 1,
      providers: ["anthropic"], thinkLevel: 2, createdAt: NOW, updatedAt: NOW,
    }],
  }, null, 2));
}

test("변경 없는 폴링 틱은 채팅 스레드 DOM을 재구축하지 않는다", async (t) => {
  const root = await createTestRoot();
  const server = await startTestServer({ root });
  await seedRunningChat(root);
  const browser = await chromium.launch({ headless: true });
  t.after(async () => {
    await browser.close();
    await server.stop({ removeRoot: true });
  });

  const page = await browser.newPage();
  await page.goto(server.baseUrl, { waitUntil: "networkidle" });
  await page.locator("#loginView").waitFor({ state: "visible" });
  await page.locator("#loginUsername").fill(TEST_USERNAME);
  await page.locator("#loginPassword").fill(TEST_PASSWORD);
  await page.locator("#loginButton").click();
  await page.waitForTimeout(800);
  await page.goto(`${server.baseUrl}/#chat-${CHAT_ID}`, { waitUntil: "networkidle" });
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForFunction(
    () => (document.querySelector("#chatThread")?.childElementCount || 0) > 0,
    { timeout: 10_000 },
  );

  // 첫 렌더 안정화 후, 데이터 변경이 없는 폴링(1.2s) 4틱 동안 DOM 교체를 관측
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    window.__threadMutations = 0;
    const observer = new MutationObserver((records) => {
      window.__threadMutations += records.length;
    });
    observer.observe(document.querySelector("#chatThread"), { childList: true });
  });
  await page.waitForTimeout(5_000);
  const mutations = await page.evaluate(() => window.__threadMutations);
  assert.equal(mutations, 0,
    `변경 없는 폴링 중 스레드 DOM 재구축 ${mutations}회 — 매 틱 replaceChildren이 깜빡임·버벅임을 만든다`);
});
