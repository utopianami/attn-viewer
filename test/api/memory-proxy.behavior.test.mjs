import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

import { createTestRoot, requestJson, startTestServer } from "../helpers/test-server.mjs";

async function startFakeEngine() {
  const requests = [];
  let closed = false;
  const server = http.createServer((req, res) => {
    requests.push(req.url);
    const isBriefing = req.url?.startsWith("/v1/sector/briefing");
    res.writeHead(isBriefing ? 429 : 200, { "content-type": "application/json" });
    res.end(JSON.stringify({ upstream: true, path: req.url }));
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return {
    requests,
    url: `http://127.0.0.1:${address.port}`,
    close: () => {
      if (closed) return Promise.resolve();
      closed = true;
      return new Promise((resolve) => server.close(resolve));
    },
  };
}

test("memory-sector proxy preserves public access, clamps, and upstream statuses", async (t) => {
  const engine = await startFakeEngine();
  const root = await createTestRoot();
  const app = await startTestServer({ root, engineUrl: engine.url });
  t.after(async () => {
    await engine.close();
    await app.stop({ removeRoot: true });
  });

  const board = await requestJson(app.baseUrl, "/api/memory-board");
  assert.equal(board.response.status, 200);
  assert.deepEqual(board.body, { upstream: true, path: "/v1/sector/board" });

  for (const [query, forwarded] of [
    ["?days=999", "?days=365"],
    ["?days=1", "?days=7"],
    ["", "?days=90"],
  ]) {
    const prices = await requestJson(app.baseUrl, `/api/memory-prices${query}`);
    assert.equal(prices.response.status, 200);
    assert.equal(prices.body.path, `/v1/sector/prices${forwarded}`);
  }

  const badMetric = await requestJson(app.baseUrl, "/api/memory-metrics/Bad-Name");
  assert.equal(badMetric.response.status, 400);
  assert.deepEqual(badMetric.body, { error: "bad metric name" });

  const metric = await requestJson(app.baseUrl, "/api/memory-metrics/dram_price?n=99999");
  assert.equal(metric.response.status, 200);
  assert.equal(metric.body.path, "/v1/sector/metrics/dram_price?n=2000");

  const briefing = await requestJson(app.baseUrl, "/api/memory-briefing");
  assert.equal(briefing.response.status, 429);
  assert.deepEqual(briefing.body, { upstream: true, path: "/v1/sector/briefing" });

  assert.deepEqual(engine.requests, [
    "/v1/sector/board",
    "/v1/sector/prices?days=365",
    "/v1/sector/prices?days=7",
    "/v1/sector/prices?days=90",
    "/v1/sector/metrics/dram_price?n=2000",
    "/v1/sector/briefing",
  ]);

  await engine.close();
  const unavailable = await requestJson(app.baseUrl, "/api/memory-board");
  assert.equal(unavailable.response.status, 502);
  assert.match(unavailable.body.error, /^engine unreachable:/);
});
