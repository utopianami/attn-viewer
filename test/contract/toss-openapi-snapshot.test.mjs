import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";

const contractDir = resolve("api-contracts", "external", "toss");
const allowedTags = new Set([
  "Market Data",
  "Stock Info",
  "Market Info",
  "Ranking",
  "Market Indicators",
]);

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

test("pinned Toss OpenAPI snapshot matches its lock", async () => {
  const [snapshotText, lockText] = await Promise.all([
    readFile(resolve(contractDir, "openapi.json"), "utf8"),
    readFile(resolve(contractDir, "lock.json"), "utf8"),
  ]);
  const spec = JSON.parse(snapshotText);
  const lock = JSON.parse(lockText);

  assert.match(spec.openapi, /^3\./);
  assert.equal(spec.info.title, "토스증권 Open API");
  assert.equal(spec.info.version, lock.apiVersion);
  assert.equal(spec.openapi, lock.openapiVersion);
  assert.equal(Object.keys(spec.paths).length, lock.pathCount);
  assert.equal(sha256(snapshotText), lock.snapshotSha256);
  assert.equal(lock.source, "https://openapi.tossinvest.com/openapi-docs/latest/openapi.json");
});

test("official Toss collector allowlist is GET-only and account-independent", async () => {
  const [snapshotText, allowlistText] = await Promise.all([
    readFile(resolve(contractDir, "openapi.json"), "utf8"),
    readFile(resolve(contractDir, "read-only-operations.json"), "utf8"),
  ]);
  const spec = JSON.parse(snapshotText);
  const allowlist = JSON.parse(allowlistText);

  assert.equal(allowlist.operations.length, 14);
  assert.equal(new Set(allowlist.operations.map((item) => item.operationId)).size, 14);
  for (const item of allowlist.operations) {
    assert.equal(item.method, "GET", item.operationId);
    assert.ok(allowedTags.has(item.tag), `${item.operationId}: ${item.tag}`);
    assert.doesNotMatch(
      item.path,
      /\/(?:accounts?|holdings?|orders?|buying-power|sellable-quantity|commissions)(?:\/|$)/i,
    );
    const operation = spec.paths[item.path]?.get;
    assert.ok(operation, `${item.operationId}: missing GET ${item.path}`);
    assert.equal(operation.operationId, item.operationId);
    assert.equal(operation.tags[0], item.tag);
  }
});
