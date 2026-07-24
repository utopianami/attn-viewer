import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const serverEntry = join(repoRoot, "server.mjs");

export const TEST_USERNAME = "test-user";
export const TEST_PASSWORD = "test-password";

async function reservePort() {
  return new Promise((resolve, reject) => {
    const socket = net.createServer();
    socket.unref();
    socket.once("error", reject);
    socket.listen(0, "127.0.0.1", () => {
      const address = socket.address();
      const port = typeof address === "object" && address ? address.port : 0;
      socket.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function waitForServer(child, timeoutMs = 10_000) {
  let output = "";
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error(`test server did not start\n${output}`));
    }, timeoutMs);

    const onOutput = (chunk) => {
      output += chunk.toString();
      if (output.includes("attn-viewer listening on")) {
        cleanup();
        resolve();
      }
    };
    const onExit = (code, signal) => {
      cleanup();
      reject(new Error(`test server exited before startup (${code ?? signal})\n${output}`));
    };
    const cleanup = () => {
      clearTimeout(timeout);
      child.stdout.off("data", onOutput);
      child.stderr.off("data", onOutput);
      child.off("exit", onExit);
    };

    child.stdout.on("data", onOutput);
    child.stderr.on("data", onOutput);
    child.once("exit", onExit);
  });
}

async function stopChild(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) {
    return;
  }

  await new Promise((resolve) => {
    const force = setTimeout(() => child.kill("SIGKILL"), 2_000);
    child.once("exit", () => {
      clearTimeout(force);
      resolve();
    });
    child.kill("SIGTERM");
  });
}

export async function createTestRoot() {
  const root = await mkdtemp(join(os.tmpdir(), "attn-viewer-test-"));
  await Promise.all([
    symlink(join(repoRoot, "public"), join(root, "public"), "dir"),
    symlink(join(repoRoot, "schemas"), join(root, "schemas"), "dir"),
    symlink(join(repoRoot, "scripts"), join(root, "scripts"), "dir"),
  ]);
  await writeFile(
    join(root, ".env"),
    `AUTH_USERS_JSON={"${TEST_USERNAME}":"${TEST_PASSWORD}"}\n`,
  );
  return root;
}

export async function seedDocument(root, id = "document-1") {
  const userRoot = join(root, "storage", "users", TEST_USERNAME);
  const uploadedAt = "2026-07-01T00:00:00.000Z";
  const metadata = {
    id,
    originalName: "Original title.pdf",
    storedName: `${id}.pdf`,
    size: 8,
    uploadedAt,
    convertedAt: uploadedAt,
  };
  await Promise.all([
    mkdir(join(userRoot, "documents"), { recursive: true }),
    mkdir(join(userRoot, "converted"), { recursive: true }),
    mkdir(join(userRoot, "uploads"), { recursive: true }),
    mkdir(join(userRoot, "assets", id), { recursive: true }),
  ]);
  await Promise.all([
    writeFile(join(userRoot, "documents", `${id}.json`), JSON.stringify(metadata, null, 2)),
    writeFile(join(userRoot, "converted", `${id}.md`), "# Fixture\n\nDocument body."),
    writeFile(join(userRoot, "uploads", `${id}.pdf`), "%PDF-test"),
    writeFile(
      join(userRoot, "assets", id, "manifest.json"),
      JSON.stringify({ pageCount: 1, charts: [], pages: [] }, null, 2),
    ),
  ]);
  return { id, userRoot };
}

export async function startTestServer({ root = null, engineUrl = "http://127.0.0.1:1" } = {}) {
  const ownsRoot = !root;
  const testRoot = root || await createTestRoot();
  const port = await reservePort();
  const child = spawn(process.execPath, [serverEntry], {
    cwd: testRoot,
    env: {
      ...process.env,
      PORT: String(port),
      AUTH_USERS_JSON: JSON.stringify({ [TEST_USERNAME]: TEST_PASSWORD }),
      BLOG_CHECK_INTERVAL_MS: String(24 * 60 * 60 * 1000),
      ENGINE_URL: engineUrl,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  await waitForServer(child);

  return {
    baseUrl: `http://127.0.0.1:${port}`,
    child,
    root: testRoot,
    async stop({ removeRoot = ownsRoot } = {}) {
      await stopChild(child);
      if (removeRoot) {
        await rm(testRoot, { recursive: true, force: true });
      }
    },
  };
}

export async function login(baseUrl) {
  const response = await fetch(`${baseUrl}/api/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: TEST_USERNAME, password: TEST_PASSWORD }),
  });
  const cookie = response.headers.get("set-cookie")?.split(";", 1)[0] || "";
  return { response, cookie, body: await response.json() };
}

export async function requestJson(baseUrl, path, { cookie = "", ...options } = {}) {
  const headers = new Headers(options.headers || {});
  if (cookie) headers.set("cookie", cookie);
  if (options.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const response = await fetch(`${baseUrl}${path}`, { ...options, headers });
  const body = await response.json();
  return { response, body };
}

export async function waitForJsonFile(path, predicate = () => true, timeoutMs = 3_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const parsed = JSON.parse(await readFile(path, "utf8"));
      if (predicate(parsed)) return parsed;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw lastError || new Error(`timed out waiting for ${path}`);
}
