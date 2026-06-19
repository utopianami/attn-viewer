import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

loadEnvFile(join(process.cwd(), ".env"));

const port = process.env.PORT || "3000";
const domain =
  process.env.NGROK_DOMAIN ||
  process.env.NGROK_URL ||
  process.env.NGROK_STATIC_DOMAIN ||
  "";
const authtoken = process.env.NGROK_AUTHTOKEN || process.env.NGROK_AUTH_TOKEN || "";

const args = ["http", port, "--log", "stdout"];
const endpoint = normalizeEndpoint(domain);

if (endpoint) {
  args.push("--url", endpoint);
}

if (authtoken) {
  args.push("--authtoken", authtoken);
}

console.log(`Starting ngrok: http://127.0.0.1:${port}${endpoint ? ` -> ${endpoint}` : ""}`);

const ngrok = spawn("ngrok", args, {
  stdio: "inherit",
});

ngrok.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  }
  process.exit(code ?? 0);
});

function loadEnvFile(path) {
  if (!existsSync(path)) {
    return;
  }

  const lines = readFileSync(path, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const index = trimmed.indexOf("=");
    if (index === -1) {
      continue;
    }

    const key = trimmed.slice(0, index).trim();
    const value = unquote(trimmed.slice(index + 1).trim());
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

function unquote(value) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

function normalizeEndpoint(value) {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

