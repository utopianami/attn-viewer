import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");


test("OpenAPI exposes only the two implemented chat providers", async () => {
  const script = String.raw`
import json, pathlib, yaml
doc = yaml.safe_load(pathlib.Path("openapi.yaml").read_text())
schemas = doc["components"]["schemas"]
names = ["ChatMessageRequest", "ChatSummary", "Chat", "ChatMessage"]
print(json.dumps({name: schemas[name]["properties"]["providers"]["items"]["enum"] for name in names}))
`;
  const { stdout } = await execFileAsync(
    join(ROOT, "engine", ".venv", "bin", "python"), ["-c", script], { cwd: ROOT },
  );
  const providersBySchema = JSON.parse(stdout);

  assert.deepEqual(providersBySchema, {
    ChatMessageRequest: ["anthropic", "openai"],
    ChatSummary: ["anthropic", "openai"],
    Chat: ["anthropic", "openai"],
    ChatMessage: ["anthropic", "openai"],
  });
});
