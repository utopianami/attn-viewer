import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import { join } from "node:path";
import test from "node:test";

import { loadEnvFile, parsePositiveInteger } from "./env.mjs";

test("loadEnvFile preserves existing values and parses quotes and equals signs", async (t) => {
  const root = await mkdtemp(join(os.tmpdir(), "attn-env-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, ".env");
  const prefix = `ATTN_TEST_${process.pid}`;
  const existingKey = `${prefix}_EXISTING`;
  const quotedKey = `${prefix}_QUOTED`;
  const equalsKey = `${prefix}_EQUALS`;
  t.after(() => {
    delete process.env[existingKey];
    delete process.env[quotedKey];
    delete process.env[equalsKey];
  });
  process.env[existingKey] = "keep";
  await writeFile(
    path,
    `# ignored\n${existingKey}=replace\n${quotedKey}="hello world"\n${equalsKey}=left=right\n`,
  );

  loadEnvFile(path);

  assert.equal(process.env[existingKey], "keep");
  assert.equal(process.env[quotedKey], "hello world");
  assert.equal(process.env[equalsKey], "left=right");
});

test("loadEnvFile ignores a missing file", () => {
  assert.doesNotThrow(() => loadEnvFile("/path/that/does/not/exist/.env"));
});

test("parsePositiveInteger keeps the current fallback and flooring behavior", () => {
  assert.equal(parsePositiveInteger("4.9", 2), 4);
  assert.equal(parsePositiveInteger("0", 2), 2);
  assert.equal(parsePositiveInteger("bad", 2), 2);
});

