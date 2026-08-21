import test from "node:test";
import assert from "node:assert/strict";

test("createLlmCliEnv removes LLM API keys without mutating data credentials", async () => {
  const module = await import("./llm-cli-env.mjs").catch(() => ({}));
  assert.equal(typeof module.createLlmCliEnv, "function");
  const source = {
    CLAUDE_API_KEY: "claude-secret",
    ANTHROPIC_API_KEY: "anthropic-secret",
    OPENAI_API_KEY: "openai-secret",
    CODEX_API_KEY: "codex-secret",
    XAI_API_KEY: "xai-secret",
    OPENROUTER_API_KEY: "keep-openrouter",
    KOSIS_API_KEY: "keep-kosis",
    PATH: "/bin",
  };

  const child = module.createLlmCliEnv(source);

  for (const key of [
    "CLAUDE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "XAI_API_KEY",
  ]) {
    assert.equal(key in child, false);
  }
  assert.equal(child.OPENROUTER_API_KEY, "keep-openrouter");
  assert.equal(child.KOSIS_API_KEY, "keep-kosis");
  assert.equal(child.PATH, "/bin");
  assert.equal(source.OPENAI_API_KEY, "openai-secret");
});
