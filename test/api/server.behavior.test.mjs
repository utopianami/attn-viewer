import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

import {
  TEST_PASSWORD,
  TEST_USERNAME,
  createTestRoot,
  login,
  requestJson,
  seedDocument,
  startTestServer,
  waitForJsonFile,
} from "../helpers/test-server.mjs";

test("isolated server preserves the current auth, storage, and sharing behavior", async (t) => {
  const root = await createTestRoot();
  let server = await startTestServer({ root });
  t.after(async () => server.stop({ removeRoot: true }));

  await t.test("protected APIs reject anonymous requests with the existing shape", async () => {
    for (const path of ["/api/session", "/api/documents", "/api/chats", "/api/analysis-html"]) {
      const { response, body } = await requestJson(server.baseUrl, path);
      assert.equal(response.status, 401, path);
      assert.deepEqual(body, { ok: false, error: "로그인이 필요합니다." });
    }
  });

  await t.test("invalid and valid login responses remain stable", async () => {
    const invalid = await requestJson(server.baseUrl, "/api/login", {
      method: "POST",
      body: JSON.stringify({ username: TEST_USERNAME, password: `${TEST_PASSWORD}-wrong` }),
    });
    assert.equal(invalid.response.status, 401);
    assert.deepEqual(invalid.body, {
      ok: false,
      error: "아이디 또는 비밀번호가 올바르지 않습니다.",
    });

    const authenticated = await login(server.baseUrl);
    assert.equal(authenticated.response.status, 200);
    assert.deepEqual(authenticated.body, { ok: true, user: { username: TEST_USERNAME } });
    assert.match(authenticated.response.headers.get("set-cookie") || "", /HttpOnly; Path=\/; SameSite=Lax; Max-Age=1209600/);
    assert.match(authenticated.cookie, /^attn_session=[a-f0-9-]+$/);
  });

  const authenticated = await login(server.baseUrl);
  const { cookie } = authenticated;

  await t.test("sessions survive a normal process restart", async () => {
    const token = cookie.split("=", 2)[1];
    await waitForJsonFile(
      join(root, "storage", "sessions.json"),
      (sessions) => sessions[token]?.username === TEST_USERNAME,
    );
    await server.stop({ removeRoot: false });
    server = await startTestServer({ root });

    const session = await requestJson(server.baseUrl, "/api/session", { cookie });
    assert.equal(session.response.status, 200);
    assert.deepEqual(session.body, { ok: true, user: { username: TEST_USERNAME } });
  });

  await t.test("document data stays user-scoped and public sharing remaps URLs", async () => {
    const fixture = await seedDocument(root);
    const list = await requestJson(server.baseUrl, "/api/documents", { cookie });
    assert.equal(list.response.status, 200);
    assert.equal(list.body.documents.length, 1);
    assert.deepEqual(
      {
        id: list.body.documents[0].id,
        originalName: list.body.documents[0].originalName,
        hasAnalysis: list.body.documents[0].hasAnalysis,
        analysisStatus: list.body.documents[0].analysisStatus,
      },
      {
        id: fixture.id,
        originalName: "Original title.pdf",
        hasAnalysis: false,
        analysisStatus: "idle",
      },
    );

    const updated = await requestJson(server.baseUrl, `/api/documents/${fixture.id}`, {
      cookie,
      method: "PATCH",
      body: JSON.stringify({ originalName: "Updated title" }),
    });
    assert.equal(updated.response.status, 200);
    assert.equal(updated.body.document.originalName, "Updated title");
    assert.equal(updated.body.document.pdfUrl, `/api/documents/${fixture.id}/pdf`);
    const stored = JSON.parse(
      await readFile(join(fixture.userRoot, "documents", `${fixture.id}.json`), "utf8"),
    );
    assert.equal(stored.originalName, "Updated title");

    const createdShare = await requestJson(server.baseUrl, `/api/documents/${fixture.id}/shares`, {
      cookie,
      method: "POST",
    });
    assert.equal(createdShare.response.status, 200);
    assert.match(createdShare.body.share.sharePath, /^#share-[a-f0-9-]+$/);

    const shared = await requestJson(
      server.baseUrl,
      `/api/shares/${createdShare.body.share.token}`,
    );
    assert.equal(shared.response.status, 200);
    assert.equal(shared.body.document.id, fixture.id);
    assert.equal(
      shared.body.document.pdfUrl,
      `/api/shares/${createdShare.body.share.token}/pdf`,
    );
  });

  await t.test("chat CRUD and public share behavior remain stable without the engine", async () => {
    const created = await requestJson(server.baseUrl, "/api/chats", {
      cookie,
      method: "POST",
      body: JSON.stringify({ title: "Fixture chat" }),
    });
    assert.equal(created.response.status, 200);
    assert.equal(created.body.chat.title, "Fixture chat");
    assert.equal(created.body.chat.status, "idle");
    assert.deepEqual(created.body.chat.messages, []);

    const chatId = created.body.chat.id;
    const cancel = await requestJson(server.baseUrl, `/api/chats/${chatId}/cancel`, {
      cookie,
      method: "POST",
    });
    assert.equal(cancel.response.status, 409);
    assert.deepEqual(cancel.body, { ok: false, error: "진행 중인 답변이 없습니다." });

    const share = await requestJson(server.baseUrl, `/api/chats/${chatId}/shares`, {
      cookie,
      method: "POST",
    });
    assert.equal(share.response.status, 200);
    assert.match(share.body.share.sharePath, /^#chat-share-[a-f0-9-]+$/);

    const publicChat = await requestJson(
      server.baseUrl,
      `/api/chat-shares/${share.body.share.token}`,
    );
    assert.equal(publicChat.response.status, 200);
    assert.equal(publicChat.body.chat.id, chatId);

    const deleted = await requestJson(server.baseUrl, `/api/chats/${chatId}`, {
      cookie,
      method: "DELETE",
    });
    assert.equal(deleted.response.status, 200);
    assert.deepEqual(deleted.body, { ok: true });

    const revoked = await requestJson(
      server.baseUrl,
      `/api/chat-shares/${share.body.share.token}`,
    );
    assert.equal(revoked.response.status, 404);
  });

  await t.test("analysis HTML list, public share, and deletion preserve their response types", async () => {
    const file = "fixture.html";
    const htmlPath = join(
      root,
      "storage",
      "users",
      TEST_USERNAME,
      "analysis-html",
      file,
    );
    await writeFile(htmlPath, "<!doctype html><title>Fixture</title><main>Analysis body</main>");

    const list = await requestJson(server.baseUrl, "/api/analysis-html", { cookie });
    assert.equal(list.response.status, 200);
    assert.equal(list.body.files[0].file, file);
    assert.match(list.body.files[0].summary, /Fixture Analysis body/);

    const share = await requestJson(server.baseUrl, `/api/analysis-html/${file}/shares`, {
      cookie,
      method: "POST",
    });
    assert.equal(share.response.status, 200);

    const publicResponse = await fetch(
      `${server.baseUrl}/api/analysis-html-shares/${share.body.share.token}`,
    );
    assert.equal(publicResponse.status, 200);
    assert.match(publicResponse.headers.get("content-type") || "", /^text\/html/);
    assert.match(await publicResponse.text(), /Analysis body/);

    const deleted = await requestJson(server.baseUrl, `/api/analysis-html/${file}`, {
      cookie,
      method: "DELETE",
    });
    assert.equal(deleted.response.status, 200);

    const revoked = await fetch(
      `${server.baseUrl}/api/analysis-html-shares/${share.body.share.token}`,
    );
    assert.equal(revoked.status, 404);
  });

  await t.test("blog registration rejects an invalid crawl boundary before fetching Naver", async () => {
    const result = await requestJson(server.baseUrl, "/api/blogs", {
      cookie,
      method: "POST",
      body: JSON.stringify({ blogId: "boundedblog", crawlSince: "not-a-date" }),
    });
    assert.equal(result.response.status, 400);
    assert.deepEqual(result.body, {
      ok: false,
      error: "수집 시작 시각은 ISO 8601 날짜/시각이어야 합니다",
    });
  });

  await t.test("logout invalidates the current cookie", async () => {
    const logout = await requestJson(server.baseUrl, "/api/logout", {
      cookie,
      method: "POST",
    });
    assert.equal(logout.response.status, 200);
    assert.deepEqual(logout.body, { ok: true });
    assert.match(logout.response.headers.get("set-cookie") || "", /Max-Age=0/);

    const session = await requestJson(server.baseUrl, "/api/session", { cookie });
    assert.equal(session.response.status, 401);
  });
});
