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

const CHAT_ID = "22222222-2222-4222-8222-222222222222";
const NOW = "2026-08-21T00:00:00.000Z";


function answerMeta(cost) {
  return {
    layers: [{
      name: "answer_meta",
      round: 0,
      createdAt: NOW,
      data: { cost, elapsed_s: 12, degraded: [] },
    }],
  };
}


async function seedCompletedChat(root) {
  const chatsDir = join(root, "storage", "users", TEST_USERNAME, "chats");
  await mkdir(chatsDir, { recursive: true });
  const base = {
    providers: ["anthropic", "openai"],
    thinkLevel: 2,
    parentMessageId: "",
    modelMode: "",
    status: "completed",
    error: "",
    createdAt: NOW,
  };
  const chat = {
    id: CHAT_ID,
    title: "CLI 메타",
    status: "completed",
    messages: [
      { ...base, id: "m1", role: "user", content: "질문", artifacts: { layers: [] } },
      {
        ...base,
        id: "m2",
        role: "assistant",
        content: "새 CLI 답변",
        artifacts: answerMeta({
          billing_mode: "cli_subscription",
          cli_runs: { claude: 2, codex: 3 },
          by_provider: {},
          total_usd: 0,
          tokens: {},
        }),
      },
      {
        ...base,
        id: "m3",
        role: "assistant",
        content: "과거 API 답변",
        artifacts: answerMeta({
          by_provider: { grok: 0.123 },
          total_usd: 0.123,
          tokens: {},
        }),
      },
    ],
    messageNotes: [],
    providers: ["anthropic", "openai"],
    thinkLevel: 2,
    artifacts: { layers: [] },
    error: "",
    createdAt: NOW,
    updatedAt: NOW,
  };
  await writeFile(join(chatsDir, `${CHAT_ID}.json`), JSON.stringify(chat, null, 2));
  await writeFile(join(chatsDir, "index.json"), JSON.stringify({
    chats: [{
      id: CHAT_ID,
      title: chat.title,
      status: chat.status,
      messageCount: chat.messages.length,
      providers: chat.providers,
      thinkLevel: chat.thinkLevel,
      createdAt: NOW,
      updatedAt: NOW,
    }],
  }, null, 2));
}


test("chat UI labels new CLI usage truthfully and preserves historical Grok cost", async (t) => {
  const root = await createTestRoot();
  const server = await startTestServer({ root });
  await seedCompletedChat(root);
  const browser = await chromium.launch({ headless: true });
  t.after(async () => {
    await browser.close();
    await server.stop({ removeRoot: true });
  });

  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto(server.baseUrl, { waitUntil: "networkidle" });
  await page.locator("#loginView").waitFor({ state: "visible" });
  await page.locator("#loginUsername").fill(TEST_USERNAME);
  await page.locator("#loginPassword").fill(TEST_PASSWORD);
  await page.locator("#loginButton").click();
  await page.locator("#homeView").waitFor({ state: "visible" });
  await page.goto(`${server.baseUrl}/#chat-${CHAT_ID}`, { waitUntil: "networkidle" });
  await page.reload({ waitUntil: "networkidle" });
  await page.locator(".answer-meta").first().waitFor();

  const metaTexts = await page.locator(".answer-meta").allTextContents();
  assert.match(metaTexts[0], /Claude CLI 2회/);
  assert.match(metaTexts[0], /Codex CLI 3회/);
  assert.match(metaTexts[0], /프로젝트 API 과금 없음/);
  assert.doesNotMatch(metaTexts[0], /\$0\.000/);
  assert.match(metaTexts[1], /Grok \$0\.123/);

  const controlTitle = await page.locator(".chat-control-row").getAttribute("title");
  assert.match(controlTitle, /Claude·Codex/);
  assert.doesNotMatch(controlTitle, /Grok|3사/);
});
