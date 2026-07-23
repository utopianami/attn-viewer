import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function startFakeEngine() {
  let cancelRequestStarted = null;
  const cancelStarted = new Promise((resolve) => {
    cancelRequestStarted = resolve;
  });
  const server = http.createServer(async (req, res) => {
    const body = await readJson(req);
    if (body.question === "http-error") {
      res.writeHead(503).end();
      return;
    }

    res.writeHead(200, { "content-type": "application/x-ndjson" });
    if (body.question === "stream") {
      res.write('{"type":"heart');
      res.write('beat"}\n{"type":"layer","name":"plan","round":0,"data":{"tier":2}}\n');
      res.write('{"type":"progress","stage":"verify","detail":"checking"}\n');
      res.end('{"type":"final","answer":"done","meta":{"rounds":0}}\n');
      return;
    }
    if (body.question === "event-error") {
      res.end('{"type":"error","message":"engine failed","partial":true}\n');
      return;
    }
    if (body.question === "no-final") {
      res.end('{"type":"heartbeat"}\n');
      return;
    }
    if (body.question === "cancel") {
      cancelRequestStarted();
      const timer = setTimeout(() => {
        if (!res.destroyed) {
          res.end('{"type":"final","answer":"too late","meta":{}}\n');
        }
      }, 2_000);
      res.on("close", () => clearTimeout(timer));
      return;
    }
    res.end('{"type":"final","answer":"default","meta":{}}\n');
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return {
    cancelStarted,
    url: `http://127.0.0.1:${address.port}`,
    close: () => {
      server.closeAllConnections();
      return new Promise((resolve) => server.close(resolve));
    },
  };
}

test("engine client preserves streaming, failure, cancellation, and locking behavior", async (t) => {
  const engine = await startFakeEngine();
  t.after(() => engine.close());
  process.env.ENGINE_URL = engine.url;
  process.env.ENGINE_IDLE_TIMEOUT_MS = "500";
  process.env.ENGINE_TOTAL_DEADLINE_MS = "3000";
  t.after(() => {
    delete process.env.ENGINE_URL;
    delete process.env.ENGINE_IDLE_TIMEOUT_MS;
    delete process.env.ENGINE_TOTAL_DEADLINE_MS;
  });
  const { cancelEngineRun, runEngineAnswer, withChatLock } = await import(
    `./engine-client.mjs?test=${Date.now()}`
  );

  await t.test("parses events split across response chunks and ignores heartbeat", async () => {
    const seen = [];
    await runEngineAnswer(
      { question: "stream", chat_id: "stream-chat" },
      {
        onLayer: async (event) => seen.push(["layer", event.name, event.data.tier]),
        onProgress: async (event) => seen.push(["progress", event.stage, event.detail]),
        onFinal: async (event) => seen.push(["final", event.answer, event.meta.rounds]),
      },
    );
    assert.deepEqual(seen, [
      ["layer", "plan", 2],
      ["progress", "verify", "checking"],
      ["final", "done", 0],
    ]);
  });

  await t.test("surfaces HTTP, engine event, and missing-final failures", async () => {
    await assert.rejects(
      runEngineAnswer({ question: "http-error", chat_id: "http-error-chat" }),
      /엔진 응답 오류 \(503\)/,
    );
    await assert.rejects(
      runEngineAnswer({ question: "event-error", chat_id: "event-error-chat" }),
      /engine failed/,
    );
    await assert.rejects(
      runEngineAnswer({ question: "no-final", chat_id: "no-final-chat" }),
      /엔진 스트림이 최종 답변 없이 종료됐습니다/,
    );
  });

  await t.test("cancel aborts the live request for the matching chat", async () => {
    const running = runEngineAnswer({ question: "cancel", chat_id: "cancel-chat" });
    await engine.cancelStarted;
    assert.equal(cancelEngineRun("cancel-chat"), true);
    await assert.rejects(running, /사용자가 생성을 중단했습니다/);
    assert.equal(cancelEngineRun("cancel-chat"), false);
  });

  await t.test("per-chat lock stays serial even when an earlier task fails", async () => {
    const order = [];
    const first = withChatLock("locked-chat", async () => {
      order.push("first:start");
      await new Promise((resolve) => setTimeout(resolve, 20));
      order.push("first:end");
      throw new Error("expected");
    });
    const second = withChatLock("locked-chat", async () => {
      order.push("second");
    });
    await assert.rejects(first, /expected/);
    await second;
    assert.deepEqual(order, ["first:start", "first:end", "second"]);
  });
});
