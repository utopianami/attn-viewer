import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SOURCE_URL = "https://openapi.tossinvest.com/openapi-docs/latest/openapi.json";
const EXPECTED_TITLE = "토스증권 Open API";
const HTTP_METHODS = new Set(["get", "post", "put", "patch", "delete"]);

// 안전 검토 없이 공식 API의 신규 경로가 자동으로 수집 대상이 되지 않도록 고정한다.
const READ_ONLY_OPERATION_IDS = [
  "getOrderbook",
  "getPrices",
  "getTrades",
  "getPriceLimit",
  "getCandles",
  "getStocks",
  "getStockWarnings",
  "getExchangeRate",
  "getKrMarketCalendar",
  "getUsMarketCalendar",
  "getRankings",
  "getMarketIndicatorPrices",
  "getMarketIndicatorCandles",
  "getMarketIndicatorInvestorTrading",
];

const ALLOWED_TAGS = new Set([
  "Market Data",
  "Stock Info",
  "Market Info",
  "Ranking",
  "Market Indicators",
]);

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const contractDir = resolve(rootDir, "api-contracts", "external", "toss");

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function allOperations(spec) {
  const operations = [];
  for (const [path, pathItem] of Object.entries(spec.paths || {})) {
    for (const [method, operation] of Object.entries(pathItem || {})) {
      if (!HTTP_METHODS.has(method) || !operation?.operationId) continue;
      operations.push({ path, method: method.toUpperCase(), operation });
    }
  }
  return operations;
}

function rateLimitGroup(description = "") {
  return description.match(/Rate Limits Group[^A-Z_]*([A-Z][A-Z_]+)/)?.[1] || null;
}

function buildAllowlist(spec) {
  const byId = new Map(allOperations(spec).map((item) => [item.operation.operationId, item]));
  return READ_ONLY_OPERATION_IDS.map((operationId) => {
    const item = byId.get(operationId);
    if (!item) throw new Error(`Official Toss operation missing: ${operationId}`);
    const tag = item.operation.tags?.[0] || "";
    if (item.method !== "GET") throw new Error(`Unsafe method for ${operationId}: ${item.method}`);
    if (!ALLOWED_TAGS.has(tag)) throw new Error(`Unsafe tag for ${operationId}: ${tag}`);
    if (/\/(?:accounts?|holdings?|orders?|buying-power|sellable-quantity|commissions)(?:\/|$)/i.test(item.path)) {
      throw new Error(`Account/order path cannot enter the allowlist: ${item.path}`);
    }
    return {
      operationId,
      method: item.method,
      path: item.path,
      tag,
      summary: item.operation.summary || "",
      rateLimitGroup: rateLimitGroup(item.operation.description),
    };
  });
}

async function main() {
  const response = await fetch(SOURCE_URL, {
    headers: { "user-agent": "attn-viewer-contract-sync/1.0" },
  });
  if (!response.ok) throw new Error(`Failed to fetch Toss OpenAPI: HTTP ${response.status}`);

  const sourceText = await response.text();
  const spec = JSON.parse(sourceText);
  if (!String(spec.openapi || "").startsWith("3.")) throw new Error("Expected OpenAPI 3.x");
  if (spec.info?.title !== EXPECTED_TITLE) throw new Error(`Unexpected API title: ${spec.info?.title}`);

  const allowlist = buildAllowlist(spec);
  const snapshotText = `${JSON.stringify(spec, null, 2)}\n`;
  const operations = allOperations(spec);
  const lock = {
    source: SOURCE_URL,
    fetchedAt: new Date().toISOString(),
    openapiVersion: spec.openapi,
    apiVersion: spec.info.version,
    sourceSha256: sha256(sourceText),
    snapshotSha256: sha256(snapshotText),
    pathCount: Object.keys(spec.paths || {}).length,
    operationCount: operations.length,
    readOnlyOperationCount: allowlist.length,
  };
  const allowlistDocument = {
    schemaVersion: 1,
    policy: "Account-independent Toss market data GET operations only. New operations require explicit review.",
    sourceApiVersion: spec.info.version,
    operations: allowlist,
  };

  await mkdir(contractDir, { recursive: true });
  await Promise.all([
    writeFile(resolve(contractDir, "openapi.json"), snapshotText, "utf8"),
    writeFile(resolve(contractDir, "lock.json"), `${JSON.stringify(lock, null, 2)}\n`, "utf8"),
    writeFile(
      resolve(contractDir, "read-only-operations.json"),
      `${JSON.stringify(allowlistDocument, null, 2)}\n`,
      "utf8",
    ),
  ]);

  console.log(
    `Pinned Toss OpenAPI ${lock.apiVersion}: ${lock.pathCount} paths, ` +
      `${lock.operationCount} operations, ${lock.readOnlyOperationCount} allowlisted GET operations.`,
  );
}

await main();
