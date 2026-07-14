// matchKeys 생성 — 플레이북별 매칭 키를 codex로 뽑아 각 json 파일에 저장.
// 반드시 프로젝트 루트에서 실행. DO NOT run this (codex call — controller runs it).
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { runCodexSummary } from "../lib/summaries.mjs";
import { buildMatchKeysPrompt, loadPlaybooks, playbooksDir } from "../lib/playbooks.mjs";

const MATCHKEYS_SCHEMA = fileURLToPath(new URL("../schemas/playbook-matchkeys.schema.json", import.meta.url));

const args = process.argv.slice(2);
const userIdx = args.indexOf("--user");
if (userIdx === -1) { console.error("--user 필수"); process.exit(1); }
const user = args[userIdx + 1];
if (!user || user.startsWith("--")) { console.error("--user 값 필수"); process.exit(1); }

const corpusRoot = join("storage", "users", user, "corpus");
const playbooks = await loadPlaybooks(corpusRoot);
if (playbooks.length === 0) { console.log("플레이북 없음 — 종료"); process.exit(0); }

const prompt = buildMatchKeysPrompt(playbooks);
const raw = await runCodexSummary(prompt, { schemaPath: MATCHKEYS_SCHEMA, timeoutMs: 900_000 });
const { items } = JSON.parse(raw);

const bySlug = new Map(items.map((it) => [it.slug, it.keys]));

for (const pb of playbooks) {
  const keys = bySlug.get(pb.slug);
  if (!keys) {
    console.warn(`[matchkeys] ${pb.slug}: 응답에 없음 — matchKeys: [] 로 저장`);
  }
  const path = join(playbooksDir(corpusRoot), `${pb.slug}.json`);
  const cur = JSON.parse(await readFile(path, "utf8"));
  cur.matchKeys = keys ?? [];
  await writeFile(path, `${JSON.stringify(cur, null, 2)}\n`, "utf8");
  console.log(`${pb.slug}: matchKeys ${(keys ?? []).length}개 저장`);
}
