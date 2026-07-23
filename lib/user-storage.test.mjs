import assert from "node:assert/strict";
import { mkdtemp, rm, stat } from "node:fs/promises";
import os from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createUserDirsResolver } from "./user-storage.mjs";

test("user directory resolver creates every runtime directory below the username", async (t) => {
  const root = await mkdtemp(join(os.tmpdir(), "attn-storage-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const ensureUserDirs = createUserDirsResolver(join(root, "users"));

  const dirs = await ensureUserDirs("alice");

  assert.equal(dirs.root, join(root, "users", "alice"));
  assert.deepEqual(Object.keys(dirs), [
    "root",
    "uploads",
    "converted",
    "documents",
    "assets",
    "analysis",
    "analysisHtml",
    "analysisHtmlChats",
    "chats",
    "feedback",
    "feedbackItems",
    "notes",
    "shares",
  ]);
  for (const path of Object.values(dirs)) {
    assert.equal((await stat(path)).isDirectory(), true, path);
    assert.equal(path.startsWith(dirs.root), true, path);
  }
});

