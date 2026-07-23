// 메모리 섹터 — Python 엔진의 대시보드 API를 같은 origin으로 프록시한다.

function engineUrl() {
  return process.env.ENGINE_URL || "http://127.0.0.1:8801";
}

export function registerMemoryRoutes(app) {
  app.get("/api/memory-briefing", async (req, res) => {
    try {
      const r = await fetch(`${engineUrl()}/v1/sector/briefing`, {
        signal: AbortSignal.timeout(45_000),
      });
      res.status(r.status).json(await r.json());
    } catch (err) {
      res.status(502).json({ error: `engine unreachable: ${err?.message || err}` });
    }
  });

  app.get("/api/memory-prices", async (req, res) => {
    try {
      const days = Math.min(365, Math.max(7, Number(req.query.days) || 90));
      const r = await fetch(`${engineUrl()}/v1/sector/prices?days=${days}`, {
        signal: AbortSignal.timeout(30_000),
      });
      res.status(r.status).json(await r.json());
    } catch (err) {
      res.status(502).json({ error: `engine unreachable: ${err?.message || err}` });
    }
  });

  app.get("/api/memory-metrics/:name", async (req, res) => {
    try {
      if (!/^[a-z0-9_]{1,64}$/.test(req.params.name)) {
        return res.status(400).json({ error: "bad metric name" });
      }
      const n = Math.min(2000, Math.max(1, Number(req.query.n) || 200));
      const r = await fetch(`${engineUrl()}/v1/sector/metrics/${req.params.name}?n=${n}`, {
        signal: AbortSignal.timeout(15_000),
      });
      res.status(r.status).json(await r.json());
    } catch (err) {
      res.status(502).json({ error: `engine unreachable: ${err?.message || err}` });
    }
  });

  app.get("/api/memory-board", async (req, res) => {
    try {
      const r = await fetch(`${engineUrl()}/v1/sector/board`, {
        signal: AbortSignal.timeout(15_000),
      });
      res.status(r.status).json(await r.json());
    } catch (err) {
      res.status(502).json({ error: `engine unreachable: ${err?.message || err}` });
    }
  });
}

