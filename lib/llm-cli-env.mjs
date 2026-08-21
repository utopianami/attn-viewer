const LLM_API_KEYS = new Set([
  "CLAUDE_API_KEY",
  "ANTHROPIC_API_KEY",
  "OPENAI_API_KEY",
  "CODEX_API_KEY",
  "XAI_API_KEY",
]);


export function createLlmCliEnv(source = process.env) {
  return Object.fromEntries(
    Object.entries(source).filter(([key]) => !LLM_API_KEYS.has(key)),
  );
}
