import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { join } from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const manifestPath = join(process.cwd(), "ecosystem.config.cjs");

function loadManifest(ngrokEnabled) {
  const previous = process.env.ATTN_NGROK_ENABLED;
  if (ngrokEnabled) {
    process.env.ATTN_NGROK_ENABLED = "1";
  } else {
    delete process.env.ATTN_NGROK_ENABLED;
  }
  try {
    delete require.cache[require.resolve(manifestPath)];
    return require(manifestPath);
  } finally {
    if (previous === undefined) {
      delete process.env.ATTN_NGROK_ENABLED;
    } else {
      process.env.ATTN_NGROK_ENABLED = previous;
    }
  }
}

test("PM2 manifest has one process for every core role", () => {
  const { apps } = loadManifest(false);
  const names = apps.map((app) => app.name);
  assert.deepEqual(names, [
    "attn-viewer",
    "attn-engine",
    "attn-scheduler",
    "attn-vault-bridge",
  ]);
  assert.equal(new Set(names).size, names.length);
  assert.ok(apps.every((app) => app.instances === 1));
  assert.match(apps.find((app) => app.name === "attn-scheduler").args, /app\.scheduler_worker/);
});

test("ngrok is explicit and non-restarting", () => {
  const disabled = loadManifest(false);
  assert.equal(disabled.apps.some((app) => app.name === "attn-ngrok"), false);
  const enabled = loadManifest(true);
  const ngrok = enabled.apps.find((app) => app.name === "attn-ngrok");
  assert.ok(ngrok);
  assert.equal(ngrok.instances, 1);
  assert.equal(ngrok.autorestart, false);
});
